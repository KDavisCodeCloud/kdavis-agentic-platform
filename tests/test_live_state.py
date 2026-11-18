"""core/live_state.py: deterministic live reads used by G14 and G4 verification."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.live_state import (
    LiveStateError, aws_alarm_state, aws_instance_states, azure_alert_condition, azure_vm_power_states,
    normalize_policy,
)


def _ec2_session(reservations=None, error=None):
    paginator = MagicMock()
    if error:
        paginator.paginate.side_effect = error
    else:
        paginator.paginate.return_value = [{"Reservations": reservations or []}]
    client = MagicMock(); client.get_paginator.return_value = paginator
    session = MagicMock(); session.client.return_value = client
    return session


async def test_aws_states_and_missing_ids():
    session = _ec2_session([{"Instances": [{"InstanceId": "i-1", "State": {"Name": "stopped"}}]}])
    assert await aws_instance_states(session, ["i-1", "i-2"]) == {"i-1": "stopped", "i-2": "not-found"}


async def test_aws_error_is_a_live_state_error_never_an_answer():
    with pytest.raises(LiveStateError):
        await aws_instance_states(_ec2_session(error=RuntimeError("AccessDenied")), ["i-1"])
    with pytest.raises(LiveStateError):
        await aws_instance_states(None, ["i-1"])


def _http(*responses):
    client = AsyncMock(); client.get = AsyncMock(side_effect=list(responses))
    client.__aenter__ = AsyncMock(return_value=client); client.__aexit__ = AsyncMock(return_value=False)
    return client


def _r(status, body):
    return MagicMock(status_code=status, json=lambda: body)


async def test_azure_power_state_from_instance_view():
    client = _http(_r(200, {"statuses": [{"code": "ProvisioningState/succeeded"},
                                         {"code": "PowerState/deallocated"}]}), _r(404, {}))
    with patch("core.live_state.httpx.AsyncClient", return_value=client):
        out = await azure_vm_power_states("tok", "sub", "rg", ["vm-a", "vm-b"])
    assert out == {"vm-a": "PowerState/deallocated", "vm-b": "not-found"}


async def test_azure_error_raises():
    with patch("core.live_state.httpx.AsyncClient", return_value=_http(_r(403, {}))):
        with pytest.raises(LiveStateError):
            await azure_vm_power_states("tok", "sub", "rg", ["vm-a"])


async def test_alarm_state_reads_region_and_name_from_arn():
    cw = MagicMock(); cw.describe_alarms.return_value = {"MetricAlarms": [{"StateValue": "OK"}]}
    session = MagicMock(); session.client.return_value = cw
    assert await aws_alarm_state(session, "arn:aws:cloudwatch:us-east-1:1:alarm:cdlab-cpu") == "OK"
    session.client.assert_called_with("cloudwatch", region_name="us-east-1")
    cw.describe_alarms.assert_called_with(AlarmNames=["cdlab-cpu"])


async def test_azure_alert_condition():
    body = {"properties": {"essentials": {"monitorCondition": "Resolved"}}}
    with patch("core.live_state.httpx.AsyncClient", return_value=_http(_r(200, body))):
        assert await azure_alert_condition("tok", "/subscriptions/s/providers/Microsoft.AlertsManagement/alerts/a") == "Resolved"


def test_policy_comparison_ignores_order_and_string_vs_list():
    a = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"],
                                                 "Resource": "arn:aws:s3:::b", "Sid": "x"}]}
    b = {"Version": "2012-10-17", "Statement": {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetObject"],
                                                "Resource": ["arn:aws:s3:::b"]}}
    star = {"Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
    assert normalize_policy(a) == normalize_policy(b) != normalize_policy(star)
