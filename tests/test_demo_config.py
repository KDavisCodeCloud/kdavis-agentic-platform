"""
tests/test_demo_config.py
Gap-table #11: the demo page's post-approval CTA. CAL_BOOKING_URL is read per
request by GET /api/v1/demo/config, so setting or clearing it needs no code
change or frontend build. Only a plain https URL is ever returned.
"""

from types import SimpleNamespace

import pytest

from api.middleware.rate_limiter import limiter
from core.funnel_events import CLIENT_EVENTS, SERVER_EVENTS


@pytest.fixture(autouse=True)
def _no_rate_limit():
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def _req():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("", None),
    ("   ", None),
    ("https://cal.com/someone/15min", "https://cal.com/someone/15min"),
    ("  https://cal.com/someone/15min  ", "https://cal.com/someone/15min"),
    ("http://cal.com/someone/15min", None),
    ("javascript:alert(1)", None),
    ("https://cal.com/some one/15min", None),
])
async def test_booking_url_from_env(monkeypatch, value, expected):
    from api.routes.demo import demo_config

    if value is None:
        monkeypatch.delenv("CAL_BOOKING_URL", raising=False)
    else:
        monkeypatch.setenv("CAL_BOOKING_URL", value)
    assert (await demo_config(_req())).booking_url == expected


async def test_read_per_request_not_at_import(monkeypatch):
    from api.routes.demo import demo_config

    monkeypatch.delenv("CAL_BOOKING_URL", raising=False)
    assert (await demo_config(_req())).booking_url is None
    monkeypatch.setenv("CAL_BOOKING_URL", "https://cal.com/someone/15min")
    assert (await demo_config(_req())).booking_url == "https://cal.com/someone/15min"


def test_booking_click_is_a_client_event_and_conversions_are_not():
    assert "booking_clicked" in CLIENT_EVENTS
    assert "booking_clicked" not in SERVER_EVENTS
    assert not ({"signup_completed", "subscribed", "fix_approved"} & CLIENT_EVENTS)
