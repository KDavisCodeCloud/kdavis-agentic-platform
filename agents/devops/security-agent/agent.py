"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Security Agent — DevOps Internal Operations
agents/devops/security-agent/agent.py

Scans a client's configuration data for security misconfigurations and flags
findings by severity. Produces a prioritized list of remediation actions.

Read-only analysis only. This agent never touches infrastructure.
All findings require human review before any remediation begins (Rule 11).
Credentials must never appear in config_data — reference by name only (Rule 8).
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a cloud security analysis agent for the KDavis Agentic Platform.

Your job: analyze configuration data for security misconfigurations and produce
a prioritized, actionable findings report. You never touch infrastructure —
you only analyze configuration data provided to you.

Security domains you assess:
  IAM:         Overly permissive roles, wildcard policies, unused credentials,
               missing MFA, excessive admin grants, cross-account trust
  Network:     Public exposure of internal resources, open security groups,
               missing VPC flow logs, unrestricted egress
  Kubernetes:  Privileged containers, hostNetwork/hostPID, missing RBAC,
               default service accounts with broad permissions, missing pod security
  Secrets:     Hardcoded credentials, unencrypted secrets, excessive secret access
  Encryption:  Unencrypted storage, unencrypted transit, weak cipher suites
  Logging:     Missing audit logs, disabled CloudTrail, missing access logs
  Compliance:  Public S3 buckets, unrestricted RDS, missing backup policies

Severity definitions:
  CRITICAL — active exploitation risk or data exposure. Fix within 24 hours.
  HIGH     — significant risk. Fix within 7 days.
  MEDIUM   — elevated risk. Fix within 30 days.
  LOW      — best practice gap. Address in next sprint.

Output schema (return ONLY this JSON, no other text):
{
  "scan_summary": "2-3 sentences: overall security posture and headline risk",
  "critical_count": integer,
  "high_count": integer,
  "medium_count": integer,
  "low_count": integer,
  "findings": [
    {
      "id": "SEC-001",
      "severity": "CRITICAL" or "HIGH" or "MEDIUM" or "LOW",
      "category": "IAM" or "Network" or "Kubernetes" or "Secrets" or "Encryption" or "Logging" or "Compliance",
      "resource": "specific resource identifier if known, else 'unknown'",
      "title": "one-line description of the finding",
      "description": "what is misconfigured and why it is a risk",
      "remediation": "specific steps to fix — exact commands or config changes",
      "docs_url": "official vendor documentation URL (AWS/Azure/GCP/Kubernetes only)",
      "effort_estimate": "15 minutes" or "1 hour" or "half day" or "1 day" or "1 week"
    }
  ],
  "immediate_actions": [
    "ordered list of the 3-5 most critical things to do right now"
  ],
  "missing_data": [
    "config areas not provided that would improve the scan's coverage"
  ]
}
"""


def run(
    client_slug: str,
    cloud_provider: str,
    config_data: dict,
    scan_scope: list[str] | None = None,
) -> dict:
    """
    Scan configuration data for security misconfigurations.

    Args:
        client_slug:    Client identifier (e.g. "acme-corp")
        cloud_provider: "aws", "azure", "gcp", or "multi"
        config_data:    Dict of configuration excerpts to analyze.
                        IMPORTANT: Never include credential values here — names only.
        scan_scope:     List of domains to focus on (optional — scans all if omitted).
                        Options: IAM, Network, Kubernetes, Secrets, Encryption, Logging, Compliance

    Returns:
        Security findings report dict.
    """
    scope_line = (
        f"Scan Scope (focus areas): {', '.join(scan_scope)}"
        if scan_scope
        else "Scan Scope: All security domains"
    )

    user_message = f"""
Client: {client_slug}
Cloud Provider: {cloud_provider}
{scope_line}

Configuration Data (analyze for security misconfigurations):
{json.dumps(config_data, indent=2)}

Identify all security findings. Prioritize by severity.
Do not flag items that are correctly configured — only actual gaps.
Return only JSON.
"""

    response = complete(
        task_type="security_scan",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "scan_summary": "Security scan could not be completed — parse error.",
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "findings": [],
            "immediate_actions": [],
            "missing_data": [f"Agent parse error: {response[:200]}"],
        }


if __name__ == "__main__":
    config = {
        "iam_policies": {
            "ci_deploy_role": {
                "actions": ["*"],
                "resources": ["*"],
                "note": "Used by GitHub Actions deployment pipeline",
            },
            "dev_team_policy": {
                "actions": ["s3:*", "ec2:*", "rds:Describe*"],
                "resources": ["*"],
            },
        },
        "s3_buckets": {
            "acme-prod-assets": {"public_access_blocked": False, "encryption": "AES256"},
            "acme-logs": {"public_access_blocked": True, "encryption": "AES256"},
        },
        "security_groups": {
            "sg-api-prod": {
                "inbound": [{"port": 443, "source": "0.0.0.0/0"}, {"port": 22, "source": "0.0.0.0/0"}]
            }
        },
        "cloudtrail": {"enabled": False, "regions": []},
        "kubernetes": {
            "namespace_prod": {
                "pod_security_policy": "none",
                "default_service_account_automount": True,
            }
        },
    }
    result = run(
        client_slug="acme-corp",
        cloud_provider="aws",
        config_data=config,
    )
    print(json.dumps(result, indent=2))
