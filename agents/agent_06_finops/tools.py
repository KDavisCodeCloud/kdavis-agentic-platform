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
Agent 06 — FinOps Cost Optimization execution tools.

These tools are called ONLY after operator approval via POST /incidents/{id}/approve.
They never execute autonomously. Governance Rule 11.

Two categories:
  READ (always safe) — fetch current cloud billing data
  WRITE (post-approval) — stop idle resources, create GitHub issue, post Slack alert

Supported clouds: AWS, Azure, GCP
"""

import json
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_GH_API      = "https://api.github.com"
_AWS_CE      = "https://ce.us-east-1.amazonaws.com"
_ARM_COST    = "https://management.azure.com"
_GCP_BILLING = "https://cloudbilling.googleapis.com"
_AWS_EC2     = "https://ec2.amazonaws.com"
_ARM_COMPUTE = "https://management.azure.com"
_GCP_COMPUTE = "https://compute.googleapis.com"


class FinOpsTools:
    """
    Post-approval execution tools for Agent 06.
    Reads billing data from cloud APIs, then applies zero-risk quick wins
    (stop/deallocate idle resources) only after operator approval.
    """

    def __init__(
        self,
        github_token: Optional[str] = None,
        slack_webhook_url: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        azure_access_token: Optional[str] = None,
        gcp_access_token: Optional[str] = None,
    ):
        self.github_token          = github_token          or os.environ.get("GITHUB_TOKEN", "")
        self.slack_webhook_url     = slack_webhook_url     or os.environ.get("SLACK_WEBHOOK_URL", "")
        self.aws_access_key_id     = aws_access_key_id     or os.environ.get("AWS_ACCESS_KEY_ID", "")
        self.aws_secret_access_key = aws_secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        self.azure_access_token    = azure_access_token    or os.environ.get("AZURE_ACCESS_TOKEN", "")
        self.gcp_access_token      = gcp_access_token      or os.environ.get("GCP_ACCESS_TOKEN", "")

    # ──────────────────────────────────────────────
    # Read — billing data fetch (always safe)
    # ──────────────────────────────────────────────

    async def get_aws_cost_data(
        self,
        start_date: str,
        end_date: str,
        granularity: str = "MONTHLY",
    ) -> dict:
        """
        Query AWS Cost Explorer for spend grouped by SERVICE.
        Ref: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_GetCostAndUsage.html
        """
        if not self.aws_access_key_id:
            raise EnvironmentError("AWS_ACCESS_KEY_ID not configured for this workspace")

        payload = {
            "TimePeriod": {"Start": start_date, "End": end_date},
            "Granularity": granularity,
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
            "Metrics": ["UnblendedCost", "UsageQuantity"],
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_AWS_CE}/GetCostAndUsage",
                headers=_aws_ce_headers(self.aws_access_key_id, self.aws_secret_access_key),
                json=payload,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"AWS Cost Explorer error {resp.status_code}: {resp.text[:200]}")

        return resp.json()

    async def get_azure_cost_data(
        self,
        subscription_id: str,
        start_date: str,
        end_date: str,
    ) -> dict:
        """
        Query Azure Cost Management for spend grouped by ServiceName.
        Ref: https://learn.microsoft.com/en-us/rest/api/cost-management/query/usage
        """
        if not self.azure_access_token:
            raise EnvironmentError("AZURE_ACCESS_TOKEN not configured for this workspace")

        url = (
            f"{_ARM_COST}/subscriptions/{subscription_id}"
            "/providers/Microsoft.CostManagement/query"
            "?api-version=2023-11-01"
        )
        payload = {
            "type": "ActualCost",
            "dataSet": {
                "granularity": "Monthly",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ServiceName"}],
            },
            "timeframe": "Custom",
            "timePeriod": {"from": f"{start_date}T00:00:00Z", "to": f"{end_date}T23:59:59Z"},
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                headers=_azure_headers(self.azure_access_token),
                json=payload,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"Azure Cost Management error {resp.status_code}: {resp.text[:200]}")

        return resp.json()

    async def get_gcp_cost_data(
        self,
        billing_account_id: str,
        start_date: str,
        end_date: str,
    ) -> dict:
        """
        Query GCP Cloud Billing to list SKUs and spend for a billing account.
        Ref: https://cloud.google.com/billing/docs/reference/rest/v1/billingAccounts.services/list
        Note: Full spend data requires BigQuery export; this fetches service metadata.
        """
        if not self.gcp_access_token:
            raise EnvironmentError("GCP_ACCESS_TOKEN not configured for this workspace")

        url = f"{_GCP_BILLING}/v1/billingAccounts/{billing_account_id}/services"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                headers=_gcp_headers(self.gcp_access_token),
                params={"pageSize": 50},
            )

        if resp.status_code != 200:
            raise RuntimeError(f"GCP Billing error {resp.status_code}: {resp.text[:200]}")

        return resp.json()

    # ──────────────────────────────────────────────
    # Write — quick wins (post-approval only)
    # ──────────────────────────────────────────────

    async def stop_ec2_instances(self, instance_ids: list[str]) -> dict:
        """
        Stop (not terminate) idle AWS EC2 instances.
        Ref: https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_StopInstances.html
        """
        if not self.aws_access_key_id:
            raise EnvironmentError("AWS_ACCESS_KEY_ID not configured for this workspace")
        if not instance_ids:
            return {"status": "skipped", "reason": "no instance IDs provided"}

        params = {"Action": "StopInstances", "Version": "2016-11-15"}
        for i, iid in enumerate(instance_ids, 1):
            params[f"InstanceId.{i}"] = iid

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _AWS_EC2,
                headers=_aws_ec2_headers(self.aws_access_key_id, self.aws_secret_access_key),
                data=params,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"AWS StopInstances error {resp.status_code}: {resp.text[:200]}")

        log.info("[FinOpsTools] Stopped EC2 instances: %s", instance_ids)
        return {
            "status": "instances_stopped",
            "instance_ids": instance_ids,
            "cloud": "aws",
        }

    async def delete_unattached_ebs_volumes(self, volume_ids: list[str]) -> dict:
        """
        Delete unattached EBS volumes that are incurring idle storage cost.
        Ref: https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DeleteVolume.html
        """
        if not self.aws_access_key_id:
            raise EnvironmentError("AWS_ACCESS_KEY_ID not configured for this workspace")
        if not volume_ids:
            return {"status": "skipped", "reason": "no volume IDs provided"}

        deleted = []
        errors  = []
        for vid in volume_ids:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    _AWS_EC2,
                    headers=_aws_ec2_headers(self.aws_access_key_id, self.aws_secret_access_key),
                    data={"Action": "DeleteVolume", "VolumeId": vid, "Version": "2016-11-15"},
                )
            if resp.status_code == 200:
                deleted.append(vid)
            else:
                errors.append({"volume_id": vid, "error": resp.text[:100]})

        log.info("[FinOpsTools] Deleted EBS volumes: %s (errors: %d)", deleted, len(errors))
        return {
            "status": "volumes_deleted",
            "deleted": deleted,
            "errors": errors,
            "cloud": "aws",
        }

    async def release_elastic_ips(self, allocation_ids: list[str]) -> dict:
        """
        Release unused Elastic IPs back to the pool.
        Ref: https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_ReleaseAddress.html
        """
        if not self.aws_access_key_id:
            raise EnvironmentError("AWS_ACCESS_KEY_ID not configured for this workspace")
        if not allocation_ids:
            return {"status": "skipped", "reason": "no allocation IDs provided"}

        released = []
        errors   = []
        for aid in allocation_ids:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    _AWS_EC2,
                    headers=_aws_ec2_headers(self.aws_access_key_id, self.aws_secret_access_key),
                    data={"Action": "ReleaseAddress", "AllocationId": aid, "Version": "2016-11-15"},
                )
            if resp.status_code == 200:
                released.append(aid)
            else:
                errors.append({"allocation_id": aid, "error": resp.text[:100]})

        log.info("[FinOpsTools] Released Elastic IPs: %s", released)
        return {
            "status": "ips_released",
            "released": released,
            "errors": errors,
            "cloud": "aws",
        }

    async def deallocate_azure_vms(
        self,
        vm_names: list[str],
        resource_group: str,
        subscription_id: str,
    ) -> dict:
        """
        Deallocate (stop + deallocate, not delete) idle Azure VMs to stop compute charges.
        Ref: https://learn.microsoft.com/en-us/rest/api/compute/virtual-machines/deallocate
        """
        if not self.azure_access_token:
            raise EnvironmentError("AZURE_ACCESS_TOKEN not configured for this workspace")
        if not vm_names:
            return {"status": "skipped", "reason": "no VM names provided"}

        deallocated = []
        errors      = []
        for vm in vm_names:
            url = (
                f"{_ARM_COMPUTE}/subscriptions/{subscription_id}"
                f"/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Compute/virtualMachines/{vm}/deallocate"
                "?api-version=2024-03-01"
            )
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, headers=_azure_headers(self.azure_access_token))
            if resp.status_code in (200, 202):
                deallocated.append(vm)
            else:
                errors.append({"vm": vm, "error": resp.text[:100]})

        log.info("[FinOpsTools] Deallocated Azure VMs: %s", deallocated)
        return {
            "status": "vms_deallocated",
            "deallocated": deallocated,
            "errors": errors,
            "cloud": "azure",
        }

    async def delete_unattached_azure_disks(
        self,
        disk_names: list[str],
        resource_group: str,
        subscription_id: str,
    ) -> dict:
        """
        Delete unattached Azure managed disks.
        Ref: https://learn.microsoft.com/en-us/rest/api/compute/disks/delete
        """
        if not self.azure_access_token:
            raise EnvironmentError("AZURE_ACCESS_TOKEN not configured for this workspace")
        if not disk_names:
            return {"status": "skipped", "reason": "no disk names provided"}

        deleted = []
        errors  = []
        for disk in disk_names:
            url = (
                f"{_ARM_COMPUTE}/subscriptions/{subscription_id}"
                f"/resourceGroups/{resource_group}"
                f"/providers/Microsoft.Compute/disks/{disk}"
                "?api-version=2024-03-02"
            )
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.delete(url, headers=_azure_headers(self.azure_access_token))
            if resp.status_code in (200, 202, 204):
                deleted.append(disk)
            else:
                errors.append({"disk": disk, "error": resp.text[:100]})

        log.info("[FinOpsTools] Deleted Azure disks: %s", deleted)
        return {
            "status": "disks_deleted",
            "deleted": deleted,
            "errors": errors,
            "cloud": "azure",
        }

    async def stop_gce_instances(
        self,
        instance_names: list[str],
        zone: str,
        project: str,
    ) -> dict:
        """
        Stop idle GCE instances to eliminate compute billing.
        Ref: https://cloud.google.com/compute/docs/reference/rest/v1/instances/stop
        """
        if not self.gcp_access_token:
            raise EnvironmentError("GCP_ACCESS_TOKEN not configured for this workspace")
        if not instance_names:
            return {"status": "skipped", "reason": "no instance names provided"}

        stopped = []
        errors  = []
        for name in instance_names:
            url = f"{_GCP_COMPUTE}/compute/v1/projects/{project}/zones/{zone}/instances/{name}/stop"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, headers=_gcp_headers(self.gcp_access_token))
            if resp.status_code == 200:
                stopped.append(name)
            else:
                errors.append({"instance": name, "error": resp.text[:100]})

        log.info("[FinOpsTools] Stopped GCE instances: %s", stopped)
        return {
            "status": "instances_stopped",
            "stopped": stopped,
            "errors": errors,
            "cloud": "gcp",
        }

    async def create_cost_report_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: Optional[list[str]] = None,
    ) -> dict:
        """
        Create a GitHub issue with the full FinOps cost optimization report.
        Ref: https://docs.github.com/en/rest/issues/issues#create-an-issue
        """
        if not self.github_token:
            raise EnvironmentError("GITHUB_TOKEN not configured for this workspace")

        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/issues",
                headers=_gh_headers(self.github_token),
                json=payload,
            )

        if resp.status_code in (200, 201):
            issue = resp.json()
            log.info("[FinOpsTools] Cost report issue created: %s", issue.get("html_url"))
            return {
                "status": "issue_created",
                "issue_url": issue.get("html_url", ""),
                "issue_number": issue.get("number"),
            }

        raise RuntimeError(f"GitHub issue error {resp.status_code}: {resp.text[:200]}")

    async def post_slack_alert(self, message: str) -> dict:
        """
        Post a FinOps cost alert to the configured Slack webhook.
        Ref: https://api.slack.com/messaging/webhooks
        """
        if not self.slack_webhook_url:
            raise EnvironmentError("SLACK_WEBHOOK_URL not configured for this workspace")

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                self.slack_webhook_url,
                json={"text": message},
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code == 200:
            log.info("[FinOpsTools] Slack alert posted")
            return {"status": "slack_sent"}

        raise RuntimeError(f"Slack webhook error {resp.status_code}: {resp.text[:100]}")

    # ──────────────────────────────────────────────
    # Routing
    # ──────────────────────────────────────────────

    async def execute_option(self, option: dict, context: dict) -> dict:
        """
        Dispatch to the approved FinOps action.

        context must include:
          cloud_provider, owner, repo, report_title, report_body,
          quick_win_resources (dict with instance_ids, volume_ids, etc.)
        """
        option_id = option.get("id", "")
        cloud     = context.get("cloud_provider", "aws")

        log.info("[FinOpsTools] Executing approved option '%s' (cloud=%s)", option_id, cloud)

        if option_id == "hold":
            return {"status": "held", "message": "Operator chose to review cost optimizations manually"}

        if option_id == "opt_1":
            # Create GitHub cost report issue
            return await self.create_cost_report_issue(
                owner=context.get("owner", ""),
                repo=context.get("repo", ""),
                title=context.get("report_title", "FinOps: Cloud Cost Optimization Report"),
                body=context.get("report_body", ""),
                labels=["finops", "cost-optimization"],
            )

        if option_id == "opt_2":
            # Apply zero-risk quick wins (stop/delete idle resources)
            resources = context.get("quick_win_resources", {})
            results   = {}

            if cloud == "aws":
                if resources.get("instance_ids"):
                    results["ec2"] = await self.stop_ec2_instances(resources["instance_ids"])
                if resources.get("volume_ids"):
                    results["ebs"] = await self.delete_unattached_ebs_volumes(resources["volume_ids"])
                if resources.get("allocation_ids"):
                    results["eip"] = await self.release_elastic_ips(resources["allocation_ids"])

            elif cloud == "azure":
                rg  = resources.get("resource_group", context.get("resource_group", ""))
                sub = resources.get("subscription_id", context.get("subscription_id", ""))
                if resources.get("vm_names"):
                    results["vms"] = await self.deallocate_azure_vms(resources["vm_names"], rg, sub)
                if resources.get("disk_names"):
                    results["disks"] = await self.delete_unattached_azure_disks(resources["disk_names"], rg, sub)

            elif cloud in ("gcp", "google"):
                if resources.get("instance_names"):
                    results["gce"] = await self.stop_gce_instances(
                        resources["instance_names"],
                        zone=resources.get("zone", "us-central1-a"),
                        project=resources.get("project", context.get("project", "")),
                    )

            if not results:
                return {"status": "skipped", "reason": "no quick-win resources identified for this cloud"}

            return {"status": "quick_wins_applied", "results": results, "cloud": cloud}

        if option_id == "opt_3":
            # Post Slack alert with cost summary
            return await self.post_slack_alert(context.get("slack_message", "FinOps alert from Cloud Decoded"))

        return {"status": "not_implemented", "option_id": option_id}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _azure_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _gcp_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _aws_ce_headers(access_key_id: str, secret_key: str) -> dict:
    return {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSInsightsIndexService.GetCostAndUsage",
        "X-Amz-Access-Key-Id": access_key_id,
    }


def _aws_ec2_headers(access_key_id: str, secret_key: str) -> dict:
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Amz-Access-Key-Id": access_key_id,
    }


def _format_currency(amount: float, currency: str = "USD") -> str:
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency, currency + " ")
    return f"{symbol}{amount:,.2f}"
