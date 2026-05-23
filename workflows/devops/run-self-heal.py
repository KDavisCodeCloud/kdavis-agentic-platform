"""
Self-Heal Orchestrator — KDavis Agentic Platform
workflows/devops/run-self-heal.py

Runs the full self-healing loop for a simulated or real GitHub issue.
Flow: Triage → Fix Plan → HITL Gate (if destructive) → Validate → Close or Escalate

Usage:
  python3 workflows/devops/run-self-heal.py
  python3 workflows/devops/run-self-heal.py --issue-id 1  (real GitHub issue)
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete

# ── Simulated issue for testing ──────────────────────────────
SIMULATED_ISSUE = {
    "id": "SIM-001",
    "title": "Pod CrashLoopBackOff on prod-api-deployment",
    "body": """
## What is happening
The prod-api-deployment has 3 pods in CrashLoopBackOff state.
Started approximately 20 minutes ago after the last deployment.
Error logs show: OOMKilled — container exceeded memory limit of 512Mi.

## Impact
Production API is returning 503 errors. Approximately 40% of requests failing.

## Steps taken
Checked pod logs. Confirmed OOMKilled. No config changes other than deployment.
    """,
    "client_slug": "simulated-client",
    "client_stack": {"cloud": "aws", "kubernetes": "eks", "namespace": "production"}
}


# ── Audit logger ─────────────────────────────────────────────
def audit(client_slug: str, step: str, action: str, reasoning: str, outcome: str = ""):
    log_dir = ROOT / "knowledge" / "clients" / client_slug / "audit-trail"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.md"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"""
## {timestamp} — {step}
- **Action:** {action}
- **Reasoning:** {reasoning}
- **Outcome:** {outcome or "pending"}

"""
    if not log_file.exists():
        log_file.write_text(f"# Audit Trail — {client_slug}\n")
    with open(log_file, "a") as f:
        f.write(entry)
    print(f"  [AUDIT] {step} logged to vault")


# ── Step 1: Triage ────────────────────────────────────────────
def run_triage(issue: dict) -> dict:
    print("\n── STEP 1: TRIAGE ──────────────────────────────────────")

    audit(
        issue["client_slug"], "triage",
        f"Classifying issue: {issue['title']}",
        "New issue detected — running triage agent"
    )

    sys.path.insert(0, str(ROOT / "agents" / "devops" / "triage-agent"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "triage", ROOT / "agents" / "devops" / "triage-agent" / "agent.py"
    )
    mod = importlib.util.load_from_spec = None

    result = complete(
        task_type="issue_triage",
        messages=[{"role": "user", "content": f"""
Issue Title: {issue['title']}
Issue Body: {issue['body']}
Client Stack: {json.dumps(issue.get('client_stack', {}))}
Classify this issue and return JSON only.
        """}],
        system_prompt="""You are a DevOps triage agent. Return ONLY valid JSON:
{
  "decision": "accept" or "reject",
  "severity": "p1" or "p2" or "p3",
  "classification": "one-line description",
  "reasoning": "why",
  "escalate_immediately": true or false
}"""
    )

    clean = result.strip().replace("```json", "").replace("```", "").strip()
    triage_result = json.loads(clean)

    print(f"  Decision:  {triage_result['decision'].upper()}")
    print(f"  Severity:  {triage_result['severity'].upper()}")
    print(f"  Class:     {triage_result['classification']}")

    audit(
        issue["client_slug"], "triage",
        f"Triage complete — {triage_result['decision']}",
        triage_result["reasoning"],
        f"Label: factory:{triage_result['decision']}"
    )

    return triage_result


# ── Step 2: Fix Plan ──────────────────────────────────────────
def run_fix_plan(issue: dict, triage: dict) -> dict:
    print("\n── STEP 2: FIX PLAN ────────────────────────────────────")

    audit(
        issue["client_slug"], "fix-plan",
        f"Planning fix for: {issue['title']}",
        f"Triage accepted as {triage['severity']} — generating fix plan"
    )

    result = complete(
        task_type="fix_planning",
        messages=[{"role": "user", "content": f"""
Issue: {issue['title']}
Body: {issue['body']}
Triage Classification: {triage['classification']}
Severity: {triage['severity']}

Propose a fix plan. Return ONLY valid JSON:
{{
  "fix_description": "what you will do",
  "steps": ["step 1", "step 2"],
  "is_destructive": true or false,
  "reasoning": "why this fix",
  "confidence": "low" or "medium" or "high",
  "rollback_path": "how to undo if it fails"
}}
        """}],
        system_prompt="""You are a DevOps fix planning agent.
Propose remediation for infrastructure issues.
Never plan destructive actions without flagging is_destructive: true.
Return ONLY valid JSON."""
    )

    clean = result.strip().replace("```json", "").replace("```", "").strip()
    fix_result = json.loads(clean)

    print(f"  Fix:        {fix_result['fix_description']}")
    print(f"  Destructive: {fix_result['is_destructive']}")
    print(f"  Confidence: {fix_result['confidence']}")
    print(f"  Rollback:   {fix_result['rollback_path']}")

    audit(
        issue["client_slug"], "fix-plan",
        fix_result["fix_description"],
        fix_result["reasoning"],
        f"Destructive: {fix_result['is_destructive']} | Confidence: {fix_result['confidence']}"
    )

    return fix_result


# ── Step 3: HITL Gate ─────────────────────────────────────────
def run_hitl_gate(issue: dict, fix: dict) -> str:
    print("\n── STEP 3: HITL GATE ───────────────────────────────────")
    print("  Destructive action detected. Human approval required.\n")

    escalation_dir = ROOT / "knowledge" / "clients" / issue["client_slug"] / "escalations"
    escalation_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    escalation_file = escalation_dir / f"{timestamp}.md"

    escalation_msg = f"""# Escalation — {timestamp}

**Workflow:** self-heal
**Issue:** {issue['title']}
**Client:** {issue['client_slug']}

I need approval to execute a destructive infrastructure change.

Here is why:
{fix['reasoning']}

Without it:
The issue remains unresolved. {issue['title']} continues to impact production.

What I have already tried:
- Triage: classified as {issue.get('severity', 'unknown')}
- Fix plan generated with confidence: {fix['confidence']}

Options:
(A) Approve — execute the fix immediately
(B) Read-only diagnostic only — no changes made
(C) Pause workflow — escalate to senior engineer

Your choice determines next action.
"""

    escalation_file.write_text(escalation_msg)
    print(escalation_msg)

    # In simulation mode — auto-prompt for input
    choice = input("  [HITL] Enter your choice (A/B/C): ").strip().upper()
    return choice


# ── Step 4: Validate ──────────────────────────────────────────
def run_validate(issue: dict, fix: dict) -> dict:
    print("\n── STEP 4: VALIDATE ────────────────────────────────────")

    audit(
        issue["client_slug"], "validate",
        f"Validating resolution of: {issue['title']}",
        "Fix executed — running validation agent against original issue only"
    )

    # Simulate post-fix state for testing
    simulated_state = (
        "All pods running. Memory limit increased to 1Gi. "
        "No OOMKilled events in last 10 minutes. Error rate at baseline."
    )

    result = complete(
        task_type="validation",
        messages=[{"role": "user", "content": f"""
Original Issue: {issue['title']}
Original Body: {issue['body']}
Current State: {simulated_state}

Is this issue resolved? Return ONLY valid JSON:
{{
  "resolved": true or false,
  "evidence": "what you observed",
  "confidence": "low" or "medium" or "high",
  "remaining_issues": "any issues still present or empty string"
}}
        """}],
        system_prompt="""You are a DevOps validation agent.
Validate outcomes against the original issue only — not the fix plan.
Return ONLY valid JSON."""
    )

    clean = result.strip().replace("```json", "").replace("```", "").strip()
    val_result = json.loads(clean)

    print(f"  Resolved:   {val_result['resolved']}")
    print(f"  Confidence: {val_result['confidence']}")
    print(f"  Evidence:   {val_result['evidence'][:100]}...")

    audit(
        issue["client_slug"], "validate",
        f"Validation complete — resolved: {val_result['resolved']}",
        val_result["evidence"],
        f"Confidence: {val_result['confidence']}"
    )

    return val_result


# ── Main orchestrator ─────────────────────────────────────────
def main():
    print("\n" + "="*60)
    print("  KDavis Agentic Platform — Self-Heal Workflow")
    print("="*60)

    issue = SIMULATED_ISSUE
    print(f"\n  Issue: {issue['title']}")
    print(f"  Client: {issue['client_slug']}\n")

    # Step 1 — Triage
    triage = run_triage(issue)
    if triage["decision"] == "reject":
        print("\n  [WORKFLOW] Issue rejected at triage. Closing.")
        return

    # Step 2 — Fix Plan
    fix = run_fix_plan(issue, triage)

    # Step 3 — HITL gate if destructive
    if fix["is_destructive"]:
        choice = run_hitl_gate(issue, fix)
        if choice == "C":
            print("\n  [WORKFLOW] Workflow paused by human. No further action.")
            return
        elif choice == "B":
            print("\n  [WORKFLOW] Read-only diagnostic mode selected.")
        else:
            print("\n  [WORKFLOW] Fix approved. Executing...")
            time.sleep(1)  # Simulate execution

    # Step 4 — Validate
    validation = run_validate(issue, fix)

    # Final outcome
    print("\n── OUTCOME ─────────────────────────────────────────────")
    if validation["resolved"]:
        print("  [SUCCESS] Issue resolved and validated.")
        print(f"  Audit trail: knowledge/clients/{issue['client_slug']}/audit-trail/")
    else:
        print("  [ESCALATE] Validation failed. Escalating to human.")
        print(f"  Escalation log: knowledge/clients/{issue['client_slug']}/escalations/")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
