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
email_sequence_agent — drafts the three nurture sequences CLAUDE.md
specifies for every product (Phase 2 lead-capture section): trial
nurture (14 emails), email-only nurture (5 emails), and post-churn
win-back (4 emails). Never sends anything. Every email is a draft that
goes to the HITL queue individually and as a full sequence; only an
approved sequence produces a deploy dispatch payload.

llm_call is injected for the same reason as content_agent: this module
has zero import-time dependency on .llm/router.py, core/, or
agents/base_agent.py. Each email calls it three times (subject, body,
CTA) rather than parsing one blob back apart — that keeps every piece
independently promptable and independently testable with a stub.

Input is the plain `research` dict research_agent.ResearchAgent.run()
produces — same shape content_agent.py consumes, validated the same way.
"""

from typing import Callable

from agents.internal._copy_rules import scan_buzzwords, word_count
from agents.internal.research_agent import validate_research_schema

LLMCallFn = Callable[[str], str]

DEFAULT_WORD_LIMIT = 200
REENGAGEMENT_WORD_LIMIT = 150

# (day, theme) — themes are CLAUDE.md's exact spec, not generated.
TRIAL_NURTURE_PLAN = (
    (0, "Welcome + what to do first (onboarding)"),
    (1, "The one thing to set up today"),
    (2, "Here's what the agent did for someone like you (social proof)"),
    (3, "Check-in: have you hit your first win yet?"),
    (5, "The workflow problem most people miss (education)"),
    (7, "Halfway through your trial — here's what to look at"),
    (9, "A specific result the agent produces (concrete, no buzzwords)"),
    (11, "Your trial ends in 3 days — here's what happens next"),
    (12, "Side-by-side: what the manual workflow costs vs. this"),
    (13, "Last day — trial ends tomorrow"),
    (14, "Your trial ended. Here's how to keep access."),
    (16, "Still thinking? Here's the one question to ask yourself"),
    (21, "Re-engagement: did something get in the way?"),
    (30, "Final follow-up — door stays open"),
)

EMAIL_ONLY_NURTURE_PLAN = (
    (0, "The workflow overview they asked for (deliver the value)"),
    (3, "The specific problem this solves (education, no pitch)"),
    (7, "A real result (social proof, still no hard pitch)"),
    (10, "Here's what a trial looks like (soft CTA)"),
    (14, "Last nudge — free trial, no card required"),
)

POST_CHURN_WINBACK_PLAN = (
    (1, "We noticed you left — no pitch, just acknowledgment"),
    (7, "What changed since you left (new features or improvements)"),
    (21, "Would this change your mind? (specific objection addressed)"),
    (30, "Final check-in — always welcome back"),
)


class EmailSequenceAgent:
    def __init__(self, llm_call: LLMCallFn):
        self._llm_call = llm_call

    def draft_all_sequences(self, research: dict, product_id: str) -> dict:
        validate_research_schema(research)

        sequences = {
            "trial_nurture": self._draft_sequence(
                "trial_nurture", TRIAL_NURTURE_PLAN, research, DEFAULT_WORD_LIMIT
            ),
            "email_only_nurture": self._draft_sequence(
                "email_only_nurture", EMAIL_ONLY_NURTURE_PLAN, research, DEFAULT_WORD_LIMIT
            ),
            "post_churn_winback": self._draft_sequence(
                "post_churn_winback", POST_CHURN_WINBACK_PLAN, research, REENGAGEMENT_WORD_LIMIT
            ),
        }
        total_emails = sum(len(seq["emails"]) for seq in sequences.values())

        return {
            "product_id": product_id,
            "niche": research["niche"],
            "sequences": sequences,
            "hitl_card": self._build_hitl_card(research, product_id, total_emails),
        }

    def _draft_sequence(
        self, sequence_name: str, plan: tuple, research: dict, max_words: int
    ) -> dict:
        emails = [self._draft_email(day, theme, research, max_words) for day, theme in plan]
        return {"sequence_name": sequence_name, "max_words": max_words, "emails": emails}

    def _draft_email(self, day: int, theme: str, research: dict, max_words: int) -> dict:
        icp = research["icp"]
        context = (
            f"Day {day} nurture email for a {icp['job_title']} evaluating a solution for "
            f"'{research['niche']}'. Theme: {theme}. Tone: {icp['emotional_register']}."
        )

        subject = self._llm_call(f"{context} Write only the subject line — specific, no clickbait.")
        body = self._llm_call(
            f"{context} Write the email body. Plain text, reads like a person sent it. "
            f"No buzzwords ('AI-powered', 'revolutionary', 'game-changing'). "
            f"Under {max_words} words. One point only."
        )
        cta = self._llm_call(f"{context} Write only the single call-to-action for this email.")

        return {
            "day": day,
            "theme": theme,
            "subject": subject,
            "body": body,
            "cta": cta,
            "word_count": word_count(body),
            "meets_word_limit": word_count(body) <= max_words,
            "buzzword_flags": scan_buzzwords(subject) + scan_buzzwords(body) + scan_buzzwords(cta),
            "status": "pending",
        }

    def approve_sequence(self, sequence_name: str, product_id: str, sequence_id: str) -> dict:
        """
        Called once a sequence (or its held-and-revised remainder) is
        approved in the dashboard HITL queue. Returns the payload shape
        needed to trigger .github/workflows/email-sequence-deploy.yml's
        workflow_dispatch (product_id + sequence_id inputs) — the actual
        Actions API call is wired in the integration session.
        """
        return {
            "workflow": "email-sequence-deploy.yml",
            "inputs": {"product_id": product_id, "sequence_id": sequence_id},
            "sequence_name": sequence_name,
        }

    def _build_hitl_card(self, research: dict, product_id: str, total_emails: int) -> dict:
        return {
            "agent": "email_sequence_agent",
            "type": "RECOMMENDATION",
            "product_id": product_id,
            "what_happened": f"Drafted 3 nurture sequences ({total_emails} emails total) for '{research['niche']}'.",
            "why_it_matters": "Nothing sends until every email — or the sequence as a whole — is approved.",
            "options": [
                {"label": "Approve email", "action": "approve_email"},
                {"label": "Modify email", "action": "modify_email"},
                {"label": "Hold email", "action": "hold_email"},
                {"label": "Reject email", "action": "reject_email"},
                {"label": "Approve sequence", "action": "approve_sequence"},
            ],
        }
