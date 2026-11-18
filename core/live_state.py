"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Deterministic live-state reads (item 4). No LLM: each function asks the
cloud API one factual question.

Used by:
  - G14: Agent 06 drops idle-resource recommendations for instances that
    are already stopped / VMs already deallocated (lab A4/Z5 re-flagged them).
  - G4: core/verification.py re-reads the resource after a fix to decide
    verified vs verification_failed.

Every reader raises LiveStateError when it can't answer (no credential,
API error). Callers treat that as "couldn't check", never as "fixed" or
"not fixed".
"""

import asyncio
import json
import logging
from urllib.parse import unquote

import httpx

log = logging.getLogger(__name__)

_ARM = "https://management.azure.com"
_TIMEOUT = 30

AWS_STOPPED = frozenset({"stopped", "stopping", "terminated", "shutting-down"})
AZURE_DEALLOCATED = frozenset({"PowerState/deallocated", "PowerState/deallocating"})


class LiveStateError(Exception):
    """The live state couldn't be read; the message says why."""


# ── compute power state (Agent 06: G14 + verification) ──────────────────────

async def aws_instance_states(aws_session, instance_ids: list[str]) -> dict[str, str]:
    """{instance_id: state name}; an ID AWS doesn't return maps to "not-found"."""
    if not aws_session:
        raise LiveStateError("AWS role not connected for this workspace")
    if not instance_ids:
        return {}

    def _read() -> dict[str, str]:
        ec2 = aws_session.client("ec2")
        states = {i: "not-found" for i in instance_ids}
        try:
            pages = ec2.get_paginator("describe_instances").paginate(InstanceIds=list(instance_ids))
            for page in pages:
                for reservation in page.get("Reservations", []):
                    for inst in reservation.get("Instances", []):
                        states[inst["InstanceId"]] = inst.get("State", {}).get("Name", "unknown")
        except Exception as exc:  # botocore ClientError and friends
            raise LiveStateError(f"Could not read EC2 instance state: {exc}") from exc
        return states

    return await asyncio.to_thread(_read)


async def azure_vm_power_states(azure_token: str, subscription_id: str, resource_group: str,
                                vm_names: list[str]) -> dict[str, str]:
    """{vm_name: "PowerState/..."} from each VM's instanceView."""
    if not azure_token:
        raise LiveStateError("Azure service principal not connected for this workspace")
    if not (subscription_id and resource_group):
        raise LiveStateError("subscription and resource group are needed to read VM power state")
    states: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for name in vm_names:
            url = (f"{_ARM}/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
                   f"/providers/Microsoft.Compute/virtualMachines/{name}/instanceView")
            try:
                resp = await client.get(url, headers={"Authorization": f"Bearer {azure_token}"},
                                        params={"api-version": "2023-09-01"})
            except httpx.HTTPError as exc:
                raise LiveStateError(f"Could not read power state of {name}: {exc}") from exc
            if resp.status_code == 404:
                states[name] = "not-found"
                continue
            if resp.status_code != 200:
                raise LiveStateError(f"Could not read power state of {name} ({resp.status_code})")
            codes = [s.get("code", "") for s in resp.json().get("statuses", [])]
            states[name] = next((c for c in codes if c.startswith("PowerState/")), "unknown")
    return states


# ── IAM (Agent 05 verification) ──────────────────────────────────────────────

async def aws_policy_default_document(aws_session, policy_arn: str) -> dict:
    if not aws_session:
        raise LiveStateError("AWS role not connected for this workspace")

    def _read() -> dict:
        iam = aws_session.client("iam")
        try:
            version = iam.get_policy(PolicyArn=policy_arn)["Policy"]["DefaultVersionId"]
            doc = iam.get_policy_version(PolicyArn=policy_arn, VersionId=version)["PolicyVersion"]["Document"]
        except Exception as exc:
            raise LiveStateError(f"Could not read policy {policy_arn}: {exc}") from exc
        return json.loads(unquote(doc)) if isinstance(doc, str) else doc

    return await asyncio.to_thread(_read)


def normalize_policy(doc: dict) -> str:
    """Order-insensitive comparison form: AWS returns Action/Resource as a string
    or a list, and statement order is not meaningful."""
    def _list(v):
        return sorted(v) if isinstance(v, list) else [v]
    statements = doc.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    norm = sorted(
        json.dumps({k: (_list(v) if k in ("Action", "NotAction", "Resource", "NotResource") else v)
                    for k, v in sorted(s.items()) if k != "Sid"}, sort_keys=True)
        for s in statements
    )
    return json.dumps(norm)


# ── alarms (Agent 11 verification) ───────────────────────────────────────────

async def aws_alarm_state(aws_session, alarm_arn: str) -> str:
    """CloudWatch StateValue: OK | ALARM | INSUFFICIENT_DATA."""
    if not aws_session:
        raise LiveStateError("AWS role not connected for this workspace")
    parts = (alarm_arn or "").split(":")
    if len(parts) < 7 or parts[2] != "cloudwatch":
        raise LiveStateError(f"not a CloudWatch alarm ARN: {alarm_arn!r}")
    region, name = parts[3], ":".join(parts[6:])

    def _read() -> str:
        try:
            alarms = aws_session.client("cloudwatch", region_name=region).describe_alarms(
                AlarmNames=[name]).get("MetricAlarms", [])
        except Exception as exc:
            raise LiveStateError(f"Could not read alarm {name}: {exc}") from exc
        if not alarms:
            raise LiveStateError(f"alarm {name} no longer exists")
        return alarms[0].get("StateValue", "UNKNOWN")

    return await asyncio.to_thread(_read)


async def azure_alert_condition(azure_token: str, alert_id: str) -> str:
    """Azure Monitor alert monitorCondition: Fired | Resolved."""
    if not azure_token:
        raise LiveStateError("Azure service principal not connected for this workspace")
    if not (alert_id or "").startswith("/subscriptions/"):
        raise LiveStateError(f"not an Azure Monitor alert ID: {alert_id!r}")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(f"{_ARM}{alert_id}", headers={"Authorization": f"Bearer {azure_token}"},
                                    params={"api-version": "2019-05-05-preview"})
        except httpx.HTTPError as exc:
            raise LiveStateError(f"Could not read alert: {exc}") from exc
    if resp.status_code != 200:
        raise LiveStateError(f"Could not read alert ({resp.status_code})")
    return resp.json().get("properties", {}).get("essentials", {}).get("monitorCondition", "Unknown")

