"""
Triage Agent — KDavis Agentic Platform
agents/devops/triage-agent/agent.py
"""

import sys
import json
from pathlib import Path

# Add .llm directory directly to path
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a DevOps triage agent for the KDavis Agentic Platform.

Your job: classify infrastructure issues and decide if they are actionable.

Rules you always follow:
- You never modify files in .governance/
- You accept only issues that are clearly infrastructure-related
- You reject duplicates, vague requests, and out-of-scope items
- You always return valid JSON matching the output schema

Output schema (return ONLY this JSON, no other text):
{
  "decision": "accept" or "reject",
  "severity": "p1" or "p2" or "p3",
  "classification": "one-line description of the issue type",
  "reasoning": "why you accepted or rejected",
  "escalate_immediately": true or false
}

Severity guide:
- p1: Production down, data loss risk, security breach
- p2: Degraded performance, partial outage, elevated error rate
- p3: Non-urgent, cosmetic, optimization opportunity
"""


def run(issue_title: str, issue_body: str, client_stack: dict = None) -> dict:
    user_message = f"""
Issue Title: {issue_title}

Issue Body:
{issue_body}

Client Stack Context:
{json.dumps(client_stack or {}, indent=2)}

Classify this issue and return your decision as JSON.
"""

    response = complete(
        task_type="issue_triage",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
    except json.JSONDecodeError:
        result = {
            "decision": "reject",
            "severity": "p3",
            "classification": "parse_error",
            "reasoning": f"Could not parse agent response: {response[:200]}",
            "escalate_immediately": False
        }

    return result


if __name__ == "__main__":
    test_issue = {
        "title": "Pod CrashLoopBackOff on prod-api-deployment",
        "body": """
## What is happening
The prod-api-deployment has 3 pods in CrashLoopBackOff state.
Started approximately 20 minutes ago after the last deployment.
Error logs show: OOMKilled — container exceeded memory limit of 512Mi.

## Impact
Production API is returning 503 errors. Approximately 40% of requests failing.

## Steps taken
Checked pod logs. Confirmed OOMKilled. No recent config changes other than deployment.
        """,
        "client_stack": {
            "cloud": "aws",
            "kubernetes": "eks",
            "namespace": "production"
        }
    }

    print("Running triage agent test...\n")
    result = run(
        issue_title=test_issue["title"],
        issue_body=test_issue["body"],
        client_stack=test_issue["client_stack"]
    )
    print(json.dumps(result, indent=2))
