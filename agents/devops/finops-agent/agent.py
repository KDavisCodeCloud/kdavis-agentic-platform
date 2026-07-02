"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

FinOps Agent — DevOps Internal Operations
agents/devops/finops-agent/agent.py

Analyzes a client's cloud cost report and identifies waste, anomalies, and
optimization opportunities. Produces a prioritized savings plan.

Read-only analysis only. All recommendations require human approval before
any resource changes are made (Governance Rule 11).
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT / ".llm"))

from router import complete


SYSTEM_PROMPT = """
You are a FinOps analysis agent for the KDavis Agentic Platform.

Your job: analyze cloud cost data and identify waste, anomalies, and
optimization opportunities. You never make changes — you produce a prioritized
savings plan that a human reviews and approves before anything is touched.

Waste categories you identify:
  Idle resources:      EC2/VMs running with <5% average CPU for 7+ days
  Oversized:           Resources provisioned far above actual utilization
  Unattached:          Volumes, IPs, load balancers with no active attachment
  Zombie workloads:    Services that were stood up and forgotten — no traffic or calls
  Overprovisioned:     RDS/databases with <20% connection utilization
  Reserved waste:      Reserved instances or savings plans not being utilized
  Data transfer:       Unexpected cross-region or egress charges
  Anomaly spikes:      Sudden cost increases vs. 30-day baseline

Optimization principles:
- Potential savings must be derived from the data — never invented
- "Rightsizing" recommendations must come with specific target sizes, not vague "reduce"
- Priority order: 1) Stop bleeding (active waste), 2) Rightsize (structural waste), 3) Architect (long-term)
- Every recommendation that involves stopping or deleting a resource must include a
  verification step ("confirm this resource has no active dependencies before deleting")

Output schema (return ONLY this JSON, no other text):
{
  "analysis_period": "billing period covered",
  "total_spend_usd": number,
  "estimated_waste_usd": number,
  "waste_percentage": number,
  "executive_summary": "2-3 sentences: total spend, biggest waste category, headline savings opportunity",
  "waste_items": [
    {
      "id": "FINOPS-001",
      "category": "Idle resources" or "Oversized" or "Unattached" or "Zombie workloads" or "Overprovisioned" or "Reserved waste" or "Data transfer" or "Anomaly spikes",
      "resource_type": "e.g. EC2, RDS, S3, Lambda, LoadBalancer",
      "resource_id": "resource identifier or 'multiple' if aggregated",
      "current_monthly_cost_usd": number,
      "potential_savings_usd": number,
      "recommendation": "specific, actionable recommendation with target state",
      "verification_required": "what to check before acting",
      "effort": "minutes" or "hours" or "days"
    }
  ],
  "priority_actions": [
    "ordered list: the 3-5 highest-value actions to take first"
  ],
  "anomalies_detected": [
    {
      "description": "what spiked and when",
      "likely_cause": "probable explanation",
      "recommended_action": "what to investigate first"
    }
  ],
  "total_potential_savings_usd": number,
  "projected_monthly_spend_after_optimizations_usd": number
}
"""


def run(
    client_slug: str,
    cloud_provider: str,
    cost_report: dict,
    billing_period: str,
    baseline_monthly_spend_usd: float = 0,
) -> dict:
    """
    Analyze cloud cost data and identify waste and optimization opportunities.

    Args:
        client_slug:                  Client identifier (e.g. "acme-corp")
        cloud_provider:               "aws", "azure", "gcp", or "multi"
        cost_report:                  Dict of cost data (service breakdown, resource-level costs, etc.)
        billing_period:               Period covered (e.g. "June 2026" or "2026-06-01 to 2026-06-30")
        baseline_monthly_spend_usd:   30-day baseline for anomaly detection (optional, 0 = unknown)

    Returns:
        FinOps analysis and savings plan dict.
    """
    baseline_line = (
        f"30-Day Baseline Spend: ${baseline_monthly_spend_usd:,.0f}/month"
        if baseline_monthly_spend_usd
        else "30-Day Baseline: not provided"
    )

    user_message = f"""
Client: {client_slug}
Cloud Provider: {cloud_provider}
Billing Period: {billing_period}
{baseline_line}

Cost Report:
{json.dumps(cost_report, indent=2)}

Identify all waste and optimization opportunities. Every savings estimate must be
derived from the data. Flag anomalies vs. the baseline where provided.
Return only JSON.
"""

    response = complete(
        task_type="finops_analysis",
        messages=[{"role": "user", "content": user_message}],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        clean = response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "analysis_period": billing_period,
            "total_spend_usd": 0,
            "estimated_waste_usd": 0,
            "waste_percentage": 0,
            "executive_summary": "FinOps analysis could not be completed — parse error.",
            "waste_items": [],
            "priority_actions": [],
            "anomalies_detected": [],
            "total_potential_savings_usd": 0,
            "projected_monthly_spend_after_optimizations_usd": 0,
            "_error": f"Agent parse error: {response[:200]}",
        }


if __name__ == "__main__":
    cost_report = {
        "total_spend_usd": 31420,
        "by_service": {
            "EC2": 14200,
            "RDS": 6800,
            "Lambda": 5900,
            "S3": 1200,
            "Data Transfer": 2100,
            "Load Balancers": 1220,
        },
        "ec2_utilization": {
            "i-0abc123 (m5.2xlarge, $367/mo)": {"avg_cpu_7d": "3.2%", "avg_memory_7d": "8.1%"},
            "i-0def456 (c5.4xlarge, $556/mo)": {"avg_cpu_7d": "4.8%", "avg_memory_7d": "12.3%"},
            "i-0ghi789 (m5.xlarge, $140/mo)":  {"avg_cpu_7d": "67%",  "avg_memory_7d": "71%"},
        },
        "rds_connections": {
            "prod-db-postgres (db.r5.2xlarge, $890/mo)": {"max_connections_7d": 18, "max_connections_capacity": 600},
        },
        "unattached_resources": {
            "ebs_volumes": [
                {"id": "vol-0abc", "size_gb": 500, "monthly_cost": 50, "last_attached": "2025-11-14"},
            ],
            "elastic_ips": [
                {"id": "eipalloc-0xyz", "monthly_cost": 3.65, "attached": False},
            ],
        },
        "lambda_spike": {
            "function": "data-export-job",
            "june_cost": 4100,
            "may_cost": 290,
            "note": "Spike on June 3rd — 2.3M invocations vs 18k average daily",
        },
    }

    result = run(
        client_slug="acme-corp",
        cloud_provider="aws",
        cost_report=cost_report,
        billing_period="June 2026",
        baseline_monthly_spend_usd=17000,
    )
    print(json.dumps(result, indent=2))
