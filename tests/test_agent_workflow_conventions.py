"""
tests/test_agent_workflow_conventions.py

Static regression guard for a real, systemic production bug found live
during the Azure Action Group end-to-end verification, 2026-09-15:
7 of 11 agents (02, 03, 04, 07, 09, 10, 11) had copy-pasted the same
line into their run() method, right after ainvoke() returns from an
interrupted run:

    for task in (self._graph.get_state(config).tasks or []):

self._graph.get_state() is the SYNCHRONOUS variant. app.state.checkpointer
(core/checkpointer_lock.py's LockedAsyncPostgresSaver) only implements
the async checkpoint-saver interface -- its sync methods (get_tuple, get,
put, put_writes) fall back to BaseCheckpointSaver's default
`raise NotImplementedError`. Calling the sync get_state() therefore
raised NotImplementedError on every single interrupted run for these 7
agents, in production, for real customers -- confirmed live via a real
synthetic Azure Monitor alert against Agent 11: the incident was created
correctly and the interrupt fired correctly, but run() then crashed
immediately after, uncaught, propagating out through
api/routes/webhooks.py's exception handler.

No existing unit test caught this because every existing test mocks
self._graph (a MagicMock auto-satisfies both `.get_state(x)` and
`await x.aget_state(y)` without complaint) -- this class of bug is only
visible against a real LangGraph checkpointer, which this repo's test
suite deliberately never exercises (no live-DB/live-network test infra
here). A static source-level check is the right regression guard for
"do not copy-paste this exact sync/async mismatch again."

Agents 01, 05, 06, 08 never had this bug -- they extract incident_id
directly from ainvoke()'s own return value instead of separately
inspecting graph state, and are excluded from these checks by design
(not because they're untested).
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

_AGENTS_WITH_POST_INTERRUPT_STATE_INSPECTION = [
    "agent_02_k8s_alert",
    "agent_03_pr_review",
    "agent_04_migration",
    "agent_07_runbook",
    "agent_09_onboarding_buddy",
    "agent_10_dependency_patch",
    "agent_11_resource_health",
]

# Matches `self._graph.get_state(` but not `self._graph.aget_state(` --
# word boundary via the preceding `.` ensures "aget_state" (which
# contains "get_state" as a substring) is never mistakenly flagged.
_SYNC_GET_STATE_CALL = re.compile(r"(?<!a)self\._graph\.get_state\(")


class TestNoSyncGetStateAgainstAsyncOnlyCheckpointer:
    def test_no_agent_workflow_calls_sync_get_state(self):
        offenders = []
        for path in sorted((_REPO_ROOT / "agents").glob("agent_*/workflow.py")):
            content = path.read_text()
            if _SYNC_GET_STATE_CALL.search(content):
                offenders.append(str(path.relative_to(_REPO_ROOT)))

        assert offenders == [], (
            "These workflow.py files call the synchronous self._graph.get_state() "
            "against an async-only checkpointer (core/checkpointer_lock.py's "
            "LockedAsyncPostgresSaver) -- must be `await self._graph.aget_state(...)` "
            f"instead: {offenders}"
        )

    def test_previously_affected_agents_use_aget_state(self):
        # Positive check, not just "no sync call found": confirms each of
        # the 7 agents that had this bug now genuinely calls aget_state,
        # rather than this test accidentally passing because the whole
        # post-interrupt inspection block was silently removed.
        missing = []
        for agent_dir in _AGENTS_WITH_POST_INTERRUPT_STATE_INSPECTION:
            content = (_REPO_ROOT / "agents" / agent_dir / "workflow.py").read_text()
            if "await self._graph.aget_state(config)" not in content:
                missing.append(agent_dir)

        assert missing == [], f"Expected 'await self._graph.aget_state(config)' in: {missing}"
