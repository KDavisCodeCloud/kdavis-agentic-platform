"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
gap_detector_agent — finds coverage gaps in the agent roster and surfaces
them as build recommendations. Never builds anything itself (CLAUDE.md
non-negotiable #10: "When you identify a gap that needs a new agent,
write it to GAPS.md. Do not build it mid-session."). Runs weekly via the
cron in deploy.yml in production; callable on demand here.

Reads four signal sources, all passed in as plain dataclasses — this
agent has no DB connection of its own (persistence/wiring happens in a
later integration session, matching every other agents/internal/* module):
  - AgentRunRecord: shaped like the `agent_runs` table — surfaces agents
    with a repeating low-confidence or failed pattern.
  - HITLCorrection: shaped like repeated manual overrides on `hitl_queue`
    cards — the same agent being corrected the same way signals its logic
    should be fixed or a dedicated agent should take over that step.
  - ChatQuery: dashboard chat turns that fell through to the Claude think
    tank instead of a real handler — recurring topics signal a missing
    agent (CLAUDE.md: "these signal missing agents").
  - AgentRosterEntry: current roster, compared against the reference set
    of agents CLAUDE.md's BUILD SEQUENCE calls for, to catch agents
    speced but never built.

Output is a ranked list of GapRecommendation cards. Each one is a
decision card: options always end in "hold" (non-negotiable #9 — hold is
always available, no forced binary). append_to_gaps_md() renders them
into the exact section GAPS.md's own header promises
("gap_detector_agent writes here; human approves before build").
"""

import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

_id_counter = itertools.count(1)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAPS_MD_PATH = REPO_ROOT / "GAPS.md"

# Agents CLAUDE.md's BUILD SEQUENCE calls for, keyed by the roster name
# they should appear under once built. Used only for the coverage-gap
# detector — update this list as new agents are speced into CLAUDE.md.
REFERENCE_AGENT_ROSTER = [
    "research_agent",
    "content_agent",
    "sop_agent",
    "gap_detector_agent",
    "portfolio_monitor",
    "chat_router_agent",
    "release_notes_agent",
    "code_quality_agent",
    "email_sequence_agent",
    "visitor_capture_agent",
    "revenue_intelligence_agent",
]


@dataclass(frozen=True)
class AgentRunRecord:
    agent_name: str
    product_id: str
    status: str  # "completed" | "failed" | "paused" | "running"
    confidence_score: Optional[float]
    started_at: date


@dataclass(frozen=True)
class HITLCorrection:
    agent_name: str
    original_option: str
    corrected_option: str
    occurred_at: date


@dataclass(frozen=True)
class ChatQuery:
    text: str
    routed_to_claude: bool
    occurred_at: date


@dataclass(frozen=True)
class AgentRosterEntry:
    agent_name: str
    status: str  # "active" | "inactive" | "recommended"


@dataclass
class GapRecommendation:
    gap_description: str
    why_it_exists: str
    suggested_agent_name: str
    estimated_build_effort: str  # e.g. "1 session", "half day"
    estimated_business_impact: str
    confidence: float
    options: list[str] = field(default_factory=lambda: ["approve_to_build", "dismiss", "hold"])
    id: int = field(default_factory=lambda: next(_id_counter))

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "gap_description": self.gap_description,
            "why_it_exists": self.why_it_exists,
            "suggested_agent_name": self.suggested_agent_name,
            "estimated_build_effort": self.estimated_build_effort,
            "estimated_business_impact": self.estimated_business_impact,
            "confidence": self.confidence,
        }

    def to_markdown(self) -> str:
        return (
            f"## {self.suggested_agent_name}\n"
            f"- Gap: {self.gap_description}\n"
            f"- Why: {self.why_it_exists}\n"
            f"- Estimated build effort: {self.estimated_build_effort}\n"
            f"- Estimated business impact: {self.estimated_business_impact}\n"
            f"- Confidence: {self.confidence:.2f}\n"
            f"- Options: {', '.join(self.options)}\n"
        )


def detect_low_confidence_pattern(
    runs: list[AgentRunRecord], confidence_threshold: float = 0.85, min_occurrences: int = 3,
) -> list[GapRecommendation]:
    by_agent: dict[str, list[AgentRunRecord]] = defaultdict(list)
    for run in runs:
        if run.status == "failed" or (run.confidence_score is not None and run.confidence_score < confidence_threshold):
            by_agent[run.agent_name].append(run)

    recommendations = []
    for agent_name, matched in by_agent.items():
        if len(matched) < min_occurrences:
            continue
        failed = sum(1 for r in matched if r.status == "failed")
        recommendations.append(GapRecommendation(
            gap_description=f"{agent_name} has {len(matched)} low-confidence-or-failed runs in the observed window ({failed} failed outright).",
            why_it_exists="Confidence threshold breaches or failures repeat rather than being one-off — the prompt or logic likely needs revision, or this step needs a dedicated agent.",
            suggested_agent_name=f"{agent_name}_review",
            estimated_build_effort="half day",
            estimated_business_impact="Reduces HITL load and failed-run cost for this agent going forward.",
            confidence=min(0.9, 0.5 + 0.05 * len(matched)),
        ))
    return recommendations


def detect_repeated_corrections(
    corrections: list[HITLCorrection], min_occurrences: int = 3,
) -> list[GapRecommendation]:
    by_pattern: dict[tuple[str, str, str], int] = Counter(
        (c.agent_name, c.original_option, c.corrected_option) for c in corrections
    )
    recommendations = []
    for (agent_name, original, corrected), count in by_pattern.items():
        if count < min_occurrences:
            continue
        recommendations.append(GapRecommendation(
            gap_description=f"{agent_name}'s output has been manually corrected from '{original}' to '{corrected}' {count} times.",
            why_it_exists="A repeated manual correction pattern means the agent's default recommendation is systematically wrong for this case, not a one-off human preference.",
            suggested_agent_name=f"{agent_name}_prompt_revision",
            estimated_build_effort="1-2 hours (prompt/logic patch, not a new agent)",
            estimated_business_impact="Removes a recurring manual-override tax on every run of this agent.",
            confidence=min(0.85, 0.4 + 0.1 * count),
        ))
    return recommendations


def detect_claude_fallback_gap(
    queries: list[ChatQuery], min_occurrences: int = 5,
) -> list[GapRecommendation]:
    """Recurring chat topics that fell through to the Claude think tank
    instead of a real handler — CLAUDE.md: 'these signal missing agents.'
    Groups by first significant word as a coarse topic proxy; a real
    implementation would cluster by embedding similarity."""
    fallback = [q for q in queries if q.routed_to_claude]
    by_topic: dict[str, list[ChatQuery]] = defaultdict(list)
    for q in fallback:
        words = [w for w in q.text.lower().split() if len(w) > 3]
        topic = words[0] if words else "general"
        by_topic[topic].append(q)

    recommendations = []
    for topic, matched in by_topic.items():
        if len(matched) < min_occurrences:
            continue
        recommendations.append(GapRecommendation(
            gap_description=f"{len(matched)} chat questions about '{topic}' were routed to the Claude think tank instead of a dedicated handler.",
            why_it_exists="Recurring topic with no keyword-matched handler in chat_router_agent — a real usage pattern the roster doesn't cover yet.",
            suggested_agent_name=f"{topic}_agent",
            estimated_build_effort="1 session",
            estimated_business_impact="Moves a recurring query off ad-hoc Claude reasoning onto a deterministic, cheaper, faster handler.",
            confidence=min(0.75, 0.3 + 0.08 * len(matched)),
        ))
    return recommendations


def detect_roster_coverage_gap(
    roster: list[AgentRosterEntry], reference: Optional[list[str]] = None,
) -> list[GapRecommendation]:
    reference = reference if reference is not None else REFERENCE_AGENT_ROSTER
    active_names = {r.agent_name for r in roster if r.status == "active"}
    missing = [name for name in reference if name not in active_names]

    recommendations = []
    for name in missing:
        recommendations.append(GapRecommendation(
            gap_description=f"'{name}' is speced in CLAUDE.md's BUILD SEQUENCE but has no active roster entry.",
            why_it_exists="Roster comparison against CLAUDE.md's reference agent list found no matching active row.",
            suggested_agent_name=name,
            estimated_build_effort="1 session",
            estimated_business_impact="Closes a known build-sequence gap rather than a newly discovered one.",
            confidence=0.95,
        ))
    return recommendations


class GapDetectorAgent:
    """Runs all four gap detectors and ranks the results. Never writes to
    Supabase directly — append_to_gaps_md() is the one filesystem side
    effect, and only because GAPS.md already exists in this repo as the
    documented human-review sink for this exact agent."""

    def weekly_scan(
        self,
        runs: list[AgentRunRecord],
        corrections: list[HITLCorrection],
        chat_queries: list[ChatQuery],
        roster: list[AgentRosterEntry],
    ) -> list[GapRecommendation]:
        recommendations: list[GapRecommendation] = []
        recommendations += detect_low_confidence_pattern(runs)
        recommendations += detect_repeated_corrections(corrections)
        recommendations += detect_claude_fallback_gap(chat_queries)
        recommendations += detect_roster_coverage_gap(roster)
        return sorted(recommendations, key=lambda r: r.confidence, reverse=True)

    def append_to_gaps_md(
        self, recommendations: list[GapRecommendation], path: Path = DEFAULT_GAPS_MD_PATH,
    ) -> str:
        """Appends a dated section of recommendation cards to GAPS.md.
        Returns the path written. Creates the file with its standard
        header if it doesn't exist yet."""
        if not path.exists():
            path.write_text(
                "# GAPS\n\nPending agent recommendations. gap_detector_agent writes here; "
                "human approves before build.\n"
            )

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        section = [f"\n# {date_str} weekly scan\n"]
        section += [rec.to_markdown() for rec in recommendations]
        with open(path, "a") as f:
            f.write("\n".join(section))
        return str(path)
