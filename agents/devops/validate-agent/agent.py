"""
Validate Agent — KDavis Agentic Platform
agents/devops/validate-agent/agent.py

Checks whether a fix resolved the original issue.
Reads the original issue ONLY — never the fix plan.
This is intentional: validates outcome, not intention.
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a DevOps validation agent for the KDavis Agentic Platform.

Your job: determine whether an infrastructure issue has been resolved.

Critical rules:
- You read the ORIGINAL issue only — not the fix plan
- You validate outcomes, not intentions
- You never modify .governance/ files
- You always return valid JSON matching the output schema

Output schema (return ONLY this JSON, no other text):
{
  "resolved": true or false,
  "evidence": "what you observed that supports your conclusion",
  "confidence": "low" or "medium" or "high",
  "remaining_issues": "any issues still present, or empty string if none"
}
"""


def run(original_issue_title: str, original_issue_body: str, current_state: str = "") -> dict:
    """
    Validate whether an issue is resolved.
    Returns a validation result dict.
    """

    user_message = f"""
Original Issue Title: {original_issue_title}

Original Issue Body:
{original_issue_body}

Current System State (observed after fix attempt):
{current_state or "No current state provided — use issue context only."}

Is this issue resolved? Return your assessment as JSON.
"""

    response = complete(
        task_type="validation",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
    except json.JSONDecodeError:
        result = {
            "resolved": False,
            "evidence": f"Could not parse agent response: {response[:200]}",
            "confidence": "low",
            "remaining_issues": "Validation agent returned unparseable response"
        }

    return result


if __name__ == "__main__":
    print("Running validate agent test...\n")
    result = run(
        original_issue_title="Pod CrashLoopBackOff on prod-api-deployment",
        original_issue_body="Pods OOMKilled — memory limit 512Mi exceeded. 40% of requests failing.",
        current_state="All 3 pods running. Memory limit increased to 1Gi. No OOMKilled events in last 10 minutes. Error rate back to baseline."
    )
    print(json.dumps(result, indent=2))
