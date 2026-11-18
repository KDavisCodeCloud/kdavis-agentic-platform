"""
Option catalog: one definition per remediation option, shared by the
approval card and the code that runs when the option is approved.

Why this exists (Break-It Lab G12, 2026-11-17): every agent let the LLM write
each option's `title` and `description`, while `execute_option` dispatched on
the `id` alone. The card an operator approved could say "Enable CloudTrail"
or "Remove Owner role assignment" while the code behind that id wrote a new
IAM policy version or created a role assignment. Labels were never bound to
behavior.

Now:
  * Each agent's tools module defines `option_catalog(context)` returning
    `OptionSpec`s: the title, description and impact shown to the operator,
    and `calls`, the exact tool methods `execute_option` invokes for that id.
  * The diagnose node passes the LLM's options through `bind_options`, which
    replaces the LLM's title/description/impact with the catalog's and keeps
    the LLM's own wording as `rationale` (why the agent suggests it). Ids that
    aren't in the catalog are dropped: there is no code behind them.
  * `execute_option` refuses ids outside the catalog for that context
    (`not_available_result`), so an option can't run code it doesn't describe.
  * tests/test_option_catalog.py executes every option of every agent with
    the tool methods mocked and asserts the methods actually called are
    exactly `calls`.

The catalog can vary by context (cloud, CI provider, drift source, whether a
PR number exists) because the code does; the same context keys are used at
diagnose time and at execute time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Mapping

log = logging.getLogger(__name__)

HOLD_ID = "hold"
_IMPACTS = ("low", "medium", "high")


@dataclass(frozen=True)
class OptionSpec:
    id: str
    title: str
    description: str          # what the code does, in plain language
    impact: str               # low | medium | high (frontend IMPACT_META keys)
    calls: tuple[str, ...] = field(default_factory=tuple)  # tool methods execute_option invokes
    # True when success only proposes a fix (opens a PR or issue, posts an alert)
    # and nothing live changes until someone acts on it. The incident then ends
    # as 'proposed', never 'executed' (G1, core/execution_outcome.py).
    proposal: bool = False

    def __post_init__(self) -> None:
        if self.impact not in _IMPACTS:
            raise ValueError(f"OptionSpec {self.id}: impact must be one of {_IMPACTS}, got {self.impact!r}")
        if self.id != HOLD_ID and not self.calls:
            raise ValueError(f"OptionSpec {self.id}: a non-hold option must declare the tool calls it makes")


HOLD = OptionSpec(
    id=HOLD_ID,
    title="Hold — handle it manually",
    description="Nothing is executed. The incident stays open with this analysis for you to act on yourself.",
    impact="low",
)


def catalog_dict(*specs: OptionSpec) -> dict[str, OptionSpec]:
    """Build an ordered {id: spec} map; HOLD is always appended last."""
    out: dict[str, OptionSpec] = {}
    for spec in (*specs, HOLD):
        if spec.id in out:
            raise ValueError(f"duplicate option id {spec.id!r} in catalog")
        out[spec.id] = spec
    return out


def bind_options(llm_options: Iterable[Mapping] | None, catalog: Mapping[str, OptionSpec],
                 agent_label: str = "") -> list[dict]:
    """
    Return the options to store on the incident, in catalog order.

    An option is offered when the LLM proposed its id (the LLM decides which
    actions fit the situation) and the catalog has it (the code can do it).
    Title, description and impact always come from the catalog. The LLM's own
    text for that id is kept as `rationale`; `docs_url` is kept as given.
    Hold is always offered.
    """
    proposed: dict[str, Mapping] = {}
    for opt in llm_options or []:
        if not isinstance(opt, Mapping):
            continue
        oid = str(opt.get("id", "")).strip()
        if oid in catalog:
            proposed.setdefault(oid, opt)
        elif oid:
            log.warning("[OptionCatalog]%s dropped LLM option %r: no code behind it (title was %r)",
                        f" {agent_label}" if agent_label else "", oid, str(opt.get("title", ""))[:80])

    bound: list[dict] = []
    for oid, spec in catalog.items():
        if oid not in proposed and oid != HOLD_ID:
            continue
        llm = proposed.get(oid, {})
        rationale = " — ".join(
            s for s in (str(llm.get("title", "")).strip(), str(llm.get("description", "")).strip()) if s
        )
        bound.append({
            "id": spec.id,
            "title": spec.title,
            "description": spec.description,
            "impact": spec.impact,
            "proposal": spec.proposal,
            "docs_url": str(llm.get("docs_url", "") or ""),
            "rationale": rationale,
        })
    return bound


def catalog_prompt_block(catalog: Mapping[str, OptionSpec]) -> str:
    """
    Text appended to the diagnose request so the LLM proposes only actions
    that exist, and writes its option text as the reason for that action.
    """
    lines = [
        "AVAILABLE ACTIONS — these are the only actions this agent can execute.",
        "Return in `options` only ids from this list that fit this situation (always include `hold`).",
        "Do not invent other ids. Each option's `title`/`description` you return is shown to the",
        "operator as your rationale for that action; the action itself is exactly as described here.",
    ]
    for spec in catalog.values():
        lines.append(f"- {spec.id}: {spec.title}. {spec.description}")
    return "\n".join(lines)


def not_available_result(option_id: str, catalog: Mapping[str, OptionSpec]) -> dict:
    """execute_option's answer for an id with no code behind it in this context."""
    return {
        "status": "not_available",
        "option_id": option_id,
        "reason": f"option {option_id!r} has no executable action here (available: {', '.join(catalog)})",
    }
