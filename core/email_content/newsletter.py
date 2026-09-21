"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

'newsletter' sequence (Decoded Ops) -- 16 issues, evergreen drip relative
to each subscriber's own signup date. Issue 1 fires immediately (the
signup form's own confirmation email IS issue 1 -- single opt-in, per
the build spec). Issues 2-6 every 4 days, 7-16 weekly. Hard CTAs only on
4, 8, 12, 16 (cta_url set); every other issue is a soft/no plug
(cta_url=None).

Topics and titles are Kelvin's own list from the build spec, unchanged.
Body copy is generated, grounded in this codebase's real, observed
architecture (HITL gate, notification retry/backoff, RLS, setup
checklist, alert dedup) rather than inventing additional unverified
statistics -- the two numeric claims in the titles themselves ("2,000
tests", "27-client architecture") are Kelvin's own given facts, restated
in context, not independently fabricated here.

4 overflow topics (17-20) are seeded at pending_approval with no
step_number reachable by the active 16-issue drip (they simply stay
unapproved/unscheduled unless Kelvin later approves and renumbers one
into an active slot) -- satisfies "drafted, unscheduled" without a
separate schema concept.
"""

from core.email_content._render import (
    _APP_URL,
    _PRICING_URL,
    _SECURITY_URL,
    _TEN_PROBLEMS_URL,
    render_html,
    render_text,
)

SEQUENCE = {
    "key": "newsletter",
    "name": "Decoded Ops",
    "description": "16-issue evergreen drip, per-subscriber relative to their own signup date.",
    "trigger_type": "newsletter_signup",
    "exit_rules": {"exit_on": []},
}

_DEMO_URL = f"{_APP_URL.rsplit('/dashboard', 1)[0]}/#demo"
_QUESTIONNAIRE_URL = f"{_SECURITY_URL}#questionnaire"


def _issue(step, delay_days, subject, preheader, paragraphs, cta_text=None, cta_url=None):
    return {
        "key": f"newsletter_issue_{step}",
        "step_number": step, "delay_days": delay_days,
        "subject": subject, "preheader": preheader,
        "body_html": render_html(subject, paragraphs, cta_text, cta_url),
        "body_text": render_text(subject, paragraphs, cta_text, cta_url),
        "cta_url": cta_url,
        "skip_if": None,
    }


TEMPLATES = [
    _issue(1, 0,
        "Nothing executes without approval — the case for linear agent graphs",
        "Why the whole platform is built as a straight line, not a mesh.",
        [
            "Decoded Ops -- production agentic operations, decoded. 16 letters. No fluff. This is "
            "issue one, and it's about the single architectural decision everything else here builds "
            "on: agent graphs run linear, not as a mesh of agents calling agents.",
            "A linear graph (validate → sanitize → execute → assert → audit) has exactly one place "
            "an approval gate can sit and mean something -- before 'execute'. A mesh where agents "
            "can invoke each other has no single choke point; you end up bolting approval checks "
            "onto every edge and hoping you didn't miss one. Linear isn't a limitation. It's what "
            "makes 'nothing executes without approval' an actual guarantee instead of a policy.",
        ]),
    _issue(2, 4,
        "The credential leak pattern hiding in most agent platforms",
        "It's rarely the model. It's the connection pooling.",
        [
            "The scariest bugs in agent platforms aren't prompt injection -- they're connection "
            "reuse. A transaction-mode Postgres pooler doesn't guarantee your next query lands on "
            "the same underlying server connection as your last one. Cache a prepared statement or a "
            "session-scoped anything, and it can silently collide with a completely different "
            "tenant's query moments later.",
            "The fix is boring: disable prepared-statement caching against a pooled connection, "
            "scope everything explicitly per request, never trust connection state to persist. "
            "Boring fixes are usually the correct ones.",
        ]),
    _issue(3, 4,
        "AI is an efficiency play, not a replacement play",
        "The teams getting real value aren't trying to remove engineers from the loop.",
        [
            "Every agentic tool that markets itself as 'replace your on-call rotation' is selling a "
            "story, not a system. The actual value is triage speed: an agent reading a raw "
            "CloudWatch alarm and producing a parsed diagnosis with remediation options in seconds "
            "is a real efficiency gain. An agent that executes the fix without anyone looking at it "
            "is a liability wearing an efficiency costume.",
            "The honest pitch is: keep the human, remove the busywork between 'alert fires' and "
            "'human has enough context to make a decision.'",
        ]),
    _issue(4, 4,
        "What 2,000 tests taught me about agentic reliability",
        "Most of the value was in the boring cases, not the clever ones.",
        [
            "Two thousand tests across an agentic platform teaches you something uncomfortable: the "
            "bugs that actually bite in production are almost never in the agent logic. They're in "
            "the plumbing -- a rate limiter callable signature slowapi calls with the wrong "
            "arguments, a migration that was committed but never actually wired into the deploy "
            "pipeline, a downgrade path that quietly blocked instead of applying.",
            "Reliability in an agentic system looks a lot like reliability in any distributed "
            "system. The agent is the easy part.",
        ],
        "See it running", _DEMO_URL),
    _issue(5, 4,
        "Kubernetes: architecture before tools",
        "The tool you pick matters less than the boundary you draw first.",
        [
            "Before choosing a drift-detection tool, an alerting stack, or an agent framework for "
            "Kubernetes, draw the boundary: what's allowed to read, what's allowed to write, and "
            "what a fix looks like when it's wrong. Skip that step and every tool choice after it is "
            "solving the wrong problem well.",
            "A read-only diagnosis agent with a human approval gate on every kubectl apply is a "
            "boring architecture. It's also one that survives an on-call engineer's 2am mistake.",
        ]),
    _issue(6, 4,
        "Alert fatigue math — dedup and why repeat alerts shouldn't cost an LLM call",
        "The same alert firing 40 times shouldn't mean 40 diagnoses.",
        [
            "A flapping alert that fires 40 times in an hour is one incident, not 40. If your "
            "pipeline calls an LLM to re-diagnose it every single time, you're paying real inference "
            "cost to re-derive the same answer over and over, and burying the actual signal under "
            "duplicate noise.",
            "Dedup on a fingerprint (resource + error signature + time window) before anything "
            "touches an LLM. The model should only ever see genuinely new information.",
        ]),
    _issue(7, 7,
        "Read-only vs execute: least privilege for AI agents",
        "The permission scope should match the actual job, every time.",
        [
            "A diagnosis agent doesn't need write access to anything. It needs to read logs, read "
            "metrics, read configuration -- and produce an opinion. Write access belongs exclusively "
            "to the execution step that runs after a human approves a specific action, scoped to "
            "exactly that action.",
            "Most 'least privilege' failures aren't malicious escalation. They're a convenient IAM "
            "role that got reused because scoping a new one felt like extra work.",
        ]),
    _issue(8, 7,
        "The real cost of manual incident triage",
        "It's not the engineer's hourly rate. It's what they weren't doing instead.",
        [
            "Manual triage cost is usually calculated wrong -- as the minutes an engineer spends "
            "reading a stack trace. The real cost is everything else that engineer was pulled off "
            "of, and the context-switch tax of getting back to it afterward.",
            "That's the number worth comparing against a triage agent's output: not 'how much faster "
            "is this diagnosis,' but 'how much of my best engineer's actual work did this get back.'",
        ],
        "See the 10 problems", _TEN_PROBLEMS_URL),
    _issue(9, 7,
        "Platform engineering is DevOps rebranded",
        "The name changed. The unsolved problems mostly didn't.",
        [
            "Platform engineering promised to fix what DevOps didn't: too much cognitive load pushed "
            "onto product engineers, too many bespoke pipelines, no golden path. Most of that is "
            "still true five years in -- the org chart changed before the actual tooling did.",
            "An agentic layer doesn't fix that by itself either. It only helps if it reduces the "
            "number of things a platform team has to hand-hold, not just adds another dashboard to "
            "watch.",
        ]),
    _issue(10, 7,
        "Ship-fast culture builds on stilts",
        "Velocity without a stable base just moves the collapse further out.",
        [
            "'Move fast' works right up until the infrastructure underneath it wasn't built to hold "
            "the weight -- then every incident takes longer to diagnose because nobody fully "
            "understands what's actually running anymore.",
            "The fix isn't slowing down. It's making sure every fast-shipped change leaves behind "
            "something legible enough that an agent -- or a human -- can reconstruct what happened "
            "when it breaks.",
        ]),
    _issue(11, 7,
        "MTTR and what \"I'll handle it myself\" actually costs",
        "The manual-override path is necessary. It's also where the clock keeps running.",
        [
            "Every good incident system needs a manual-override path -- sometimes the fix really is "
            "faster typed by hand than picked from a list of generated options. But every minute "
            "spent in that path is a minute MTTR doesn't improve, no matter how good the agent's "
            "diagnosis was.",
            "The honest metric isn't 'percentage of incidents an agent touched.' It's 'percentage of "
            "incidents where the agent's diagnosis was actually what got used.'",
        ]),
    _issue(12, 7,
        "How to security-review an agentic vendor",
        "The questions that actually matter, not the ones on a generic checklist.",
        [
            "Most vendor security questionnaires ask about SOC 2 and encryption at rest. For an "
            "agentic vendor, ask three more specific things: can it execute anything without a human "
            "approving it first, is tenant isolation enforced at the database layer or just in "
            "application code, and can you get an exact list of every permission scope each agent "
            "requests.",
            "If any of those three comes back vague, that's the actual finding -- not whatever's on "
            "page four of the questionnaire.",
        ],
        "Request the questionnaire", _QUESTIONNAIRE_URL),
    _issue(13, 7,
        "Drift detection war stories: effective-rule evaluation",
        "The rule that's technically still active but functionally dead.",
        [
            "The nastiest drift-detection bugs aren't missing rules -- they're rules that exist, "
            "look active, and quietly stopped evaluating months ago because of a config change "
            "nobody connected to them. Auditing 'what rules exist' isn't enough; you have to audit "
            "'what rules actually fired in the last N days.'",
            "An agent that flags a rule as effectively dead (defined, enabled, zero real "
            "evaluations) catches a class of drift that a static rule inventory never will.",
        ]),
    _issue(14, 7,
        "The cloud spend already leaking",
        "Most of it isn't waste from bad decisions. It's waste from decisions nobody revisited.",
        [
            "The typical unattended cloud bill isn't full of obviously bad choices -- it's full of "
            "reasonable choices made once, under different constraints, that nobody has looked at "
            "since. An oversized instance from a launch-day traffic spike a year ago. A dev "
            "environment nobody remembered to schedule down.",
            "FinOps agent work is less about finding one dramatic overspend and more about "
            "continuously re-asking 'is this still the right size for what it's actually doing now.'",
        ]),
    _issue(15, 7,
        "Vendor lock-in: the Copilot/AgentCore problem",
        "The lock-in isn't the model. It's the execution surface.",
        [
            "The real lock-in risk with a managed agent platform isn't which model it calls -- "
            "that's swappable. It's whether the execution surface (the actual changes it makes to "
            "your infrastructure) is portable, or whether unwinding the vendor means unwinding every "
            "change it ever made on your behalf.",
            "An architecture where every remediation is a normal, auditable change against your own "
            "infrastructure -- not a vendor-specific execution primitive -- is the difference between "
            "'we switched vendors' and 'we're rebuilding half our ops tooling.'",
        ]),
    _issue(16, 7,
        "The 27-client architecture — running ops for dozens of tenants solo",
        "What actually has to be true in the schema for this to work without a team.",
        [
            "Running production operations across dozens of tenant workspaces without a dedicated "
            "ops team only works if tenant isolation, audit logging, and the approval gate are "
            "structural -- enforced by the database and the request path, not by careful discipline "
            "that has to hold up across every single workspace, every single day.",
            "That's the actual argument for row-level security and a linear agent graph: not "
            "elegance, just the only way this scales past a handful of tenants without either "
            "hiring a team or accepting real risk.",
        ],
        "See how it's built", _SECURITY_URL),
]

# Overflow -- pending_approval, unscheduled (see module docstring).
OVERFLOW_TEMPLATES = [
    _issue(17, 7,
        "The permissions manifest as a sales document",
        "Showing your access scopes instead of describing them wins more deals than it loses.",
        ["Draft -- overflow topic, not scheduled into the active 16-issue drip."]),
    _issue(18, 7,
        "Why HITL queues need a Hold option, not just approve/reject",
        "A binary decision under time pressure produces worse decisions than a deferred one.",
        ["Draft -- overflow topic, not scheduled into the active 16-issue drip."]),
    _issue(19, 7,
        "The token circuit breaker nobody thinks they need until they do",
        "A hard spend cap on agent execution is cheap insurance against a bad prompt loop.",
        ["Draft -- overflow topic, not scheduled into the active 16-issue drip."]),
    _issue(20, 7,
        "Prompt versioning is code versioning, not a nice-to-have",
        "Semver and a changelog on prompts catches regressions the same way it does on code.",
        ["Draft -- overflow topic, not scheduled into the active 16-issue drip."]),
]
