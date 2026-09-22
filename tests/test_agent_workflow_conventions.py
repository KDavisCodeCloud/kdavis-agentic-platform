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

---

A SECOND, deeper bug in the same 7 agents (plus, it turned out,
agent_11 itself was never actually fixed for either bug despite an
earlier pass believing it had been -- caught only by re-testing live
after the first fix deployed) was found immediately after fixing the
above: even with aget_state() in place, a real approve->resume still
crashed with

    langgraph.errors.InvalidUpdateError: Must write to at least one of
    [...state keys...] During task with name '__start__' and id '...'

Root cause: run() generates a fresh thread_id for the LangGraph
checkpoint config, but never seeds initial_state["incident_id"] with
that same value (it was hardcoded to None) -- and even where it
recently was corrected in isolation, the agent's own _ingest_node
independently returned {"incident_id": None, ...}, silently
overwriting the seed straight back to None on the very first node.
core/hitl.py's create_incident() was therefore called with no
incident_id kwarg, so the database auto-generated a random UUID for
the incident row -- a value that never matched the real LangGraph
thread_id the graph was actually checkpointed under. POST
/incidents/{id}/approve naturally uses the (wrong) DB incident id as
resume()'s thread_id, finds no checkpoint under that id, and LangGraph
treats Command(resume=...) as a fresh entry into __start__ -- which
raises, since a Command object is not valid raw state input there.

Agents 01, 05, 06, 08 already do this correctly: thread_id is generated
*before* initial_state, initial_state["incident_id"] is seeded with it,
their ingest node never re-touches that key in its return dict, and
their create_incident(...) call passes incident_id=state["incident_id"]
explicitly (see agent_01_cicd_triage/workflow.py's own comment on this
exact requirement). The checks below apply to and enforce that same
shape across all 11 agents, not just the 7 that were broken -- the
whole point is that a 12th agent copy-pasted from any of them can't
reintroduce this gap either.
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

_ALL_AGENT_WORKFLOW_PATHS = sorted((_REPO_ROOT / "agents").glob("agent_*/workflow.py"))

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


class TestIncidentIdMatchesLangGraphThreadId:
    """
    Every agent's incidents-table row id must be the exact same value as
    the LangGraph checkpoint thread_id it was created under, or a real
    approve->resume can never find its checkpoint (InvalidUpdateError,
    see module docstring). Checks all 11 agents, not just the 7 found
    broken live -- this shape must hold for any future agent too.
    """

    def test_every_agent_seeds_incident_id_with_thread_id_in_initial_state(self):
        offenders = []
        for path in _ALL_AGENT_WORKFLOW_PATHS:
            content = path.read_text()
            if not re.search(r'"incident_id":\s*thread_id,', content):
                offenders.append(str(path.relative_to(_REPO_ROOT)))

        assert offenders == [], (
            "These agents' run() does not seed initial_state['incident_id'] with "
            f"the real thread_id (still None or something else): {offenders}"
        )

    # One deliberate, understood exception to the "no None-reset" rule
    # below: agent_11's _resolution_check_node (GAPS.md scale-readiness
    # build, Prometheus Alertmanager/Grafana "resolved"-status support)
    # sets incident_id=None ONLY on its terminal "resolved alert, no
    # matching open incident" path -- no incident row is ever created on
    # that path (create_incident is never called), and the graph routes
    # straight to resolution_complete -> END without ever reaching
    # hitl_gate/execute, so there is no resume()/checkpoint concern this
    # guard exists to catch (see this class's own docstring and the
    # module docstring above for what that concern actually is).
    #
    # Allowlisted by exact file + expected match COUNT, not by weakening
    # the regex itself -- a second, unrelated None-reset added to
    # agent_11 later (or a change to this one that grows a duplicate)
    # still trips this test, same as for every other agent.
    _ALLOWED_NONE_RESETS = {
        "agents/agent_11_resource_health/workflow.py": 1,
    }

    def test_no_agent_workflow_resets_incident_id_to_none_after_seeding(self):
        # A node returning {"incident_id": None, ...} anywhere overwrites
        # run()'s seed right back to None on that node's turn -- this is
        # the exact second half of the live bug (agent_11's _ingest_node
        # had this even after run() itself was fixed).
        offenders = []
        for path in _ALL_AGENT_WORKFLOW_PATHS:
            content = path.read_text()
            count = len(re.findall(r'"incident_id":\s*None,', content))
            rel = str(path.relative_to(_REPO_ROOT))
            if count > self._ALLOWED_NONE_RESETS.get(rel, 0):
                offenders.append(rel)

        assert offenders == [], (
            f"These agents have a node that resets incident_id back to None: {offenders}"
        )

    def test_every_agent_passes_incident_id_kwarg_to_create_incident(self):
        # create_incident( -- not create_failed_incident(, which has no
        # incident_id parameter and legitimately never needs one (a
        # failed-diagnosis run never reaches interrupt(), so there's no
        # checkpoint to resume from either way).
        offenders = []
        call_re = re.compile(r"self\.hitl\.create_incident\(\s*\n(?:.*\n){0,4}")
        for path in _ALL_AGENT_WORKFLOW_PATHS:
            content = path.read_text()
            matches = list(call_re.finditer(content))
            if not matches:
                continue
            for m in matches:
                if "incident_id=" not in m.group(0):
                    offenders.append(str(path.relative_to(_REPO_ROOT)))

        assert offenders == [], (
            f"These agents call create_incident() without incident_id=state['incident_id']: {offenders}"
        )
