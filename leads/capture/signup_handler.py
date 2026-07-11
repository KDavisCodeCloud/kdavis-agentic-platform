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
signup_handler — processes both capture points described in CLAUDE.md's
Lead Capture section: the above-fold "Start free trial" CTA and the
lightweight email-only capture form. Writes to Supabase `leads`,
best-effort notifies visitor_capture_agent, and syncs the contact to
Systeme.io with the right tag + nurture sequence for the signup type.

trial_handler.py builds on top of this — it calls process_signup() with
signup_type="trial" first, then layers the Stripe subscription on top.
Keeping the shared lead-writing logic here avoids duplicating it.

Supabase/httpx clients are resolved lazily (module import must succeed
in a bare environment without those packages installed — same
convention as security/audit_log.py) and are always injectable via
keyword argument for testing.
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from leads.integrations import slack
from leads.integrations.systeme_io import SystemeIOClient

log = logging.getLogger(__name__)

LEADS_TABLE = "leads"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

VALID_SIGNUP_TYPES = ("trial", "email_only")

_supabase_client: Optional[Any] = None
_service_role_client: Optional[Any] = None


def _get_supabase_client() -> Any:
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client

        _supabase_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _supabase_client


def _get_service_role_client() -> Any:
    """Service-role Supabase client for handle_signup() — the leads-funnel
    completion entry point. Kept distinct from _get_supabase_client() above
    (which reads SUPABASE_KEY and backs process_signup()/trial_handler.py)
    since Session 7 explicitly requires SUPABASE_SERVICE_ROLE_KEY here."""
    global _service_role_client
    if _service_role_client is None:
        from supabase import create_client

        _service_role_client = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        )
    return _service_role_client


def _write_lead_captured_audit_log(client: Any, product_id: str, email: str) -> None:
    """Direct insert rather than security.audit_log.AuditLog: that class
    requires a non-null tenant_id, which a freshly-captured lead doesn't
    have yet (leads.tenant_id is nullable — see db/migrations/005_leads.sql).
    No try/except here — a failed write must raise, per the no-silent-
    failures rule, same as everything else in handle_signup()."""
    client.table("audit_log").insert({
        "agent_id": "leads_funnel",
        "action": "lead_captured",
        "product_id": product_id,
        "resource": email,
    }).execute()


def handle_signup(data: dict, *, supabase_client: Optional[Any] = None) -> dict:
    """
    Leads-funnel completion entry point (Session 7): validates email,
    inserts into the minimal `leads` schema (product_id, email, name,
    source), fires a lead Slack notification, writes an audit_log entry,
    and returns {"success": True, "lead_id": ...}.

    Distinct from process_signup() above — that function serves the
    richer CLAUDE.md lead-capture flow (company/role/UTM/signup_type) that
    trial_handler.py builds on and is left unchanged here.
    """
    email = (data.get("email") or "").strip().lower()
    name = data.get("name")
    product_id = (data.get("product_id") or "").strip()
    source = data.get("source") or "organic"

    if not email or not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid or missing email: {data.get('email')!r}")
    if not product_id:
        raise ValueError("product_id is required")

    client = supabase_client if supabase_client is not None else _get_service_role_client()

    response = client.table(LEADS_TABLE).insert({
        "product_id": product_id,
        "email": email,
        "name": name,
        "source": source,
    }).execute()

    rows = getattr(response, "data", None)
    if not rows:
        raise RuntimeError(f"Failed to insert lead for {email}: no row returned from Supabase")
    lead_id = rows[0]["id"]

    slack.send_lead_notification(name, email, product_id, source)

    _write_lead_captured_audit_log(client, product_id, email)

    return {"success": True, "lead_id": str(lead_id)}


@dataclass(frozen=True)
class SignupPayload:
    email: str
    product_id: str
    signup_type: str = "email_only"
    first_name: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    ip_country: Optional[str] = None
    page_path: Optional[str] = None


def validate_signup_payload(data: dict) -> SignupPayload:
    email = (data.get("email") or "").strip().lower()
    product_id = (data.get("product_id") or "").strip()
    signup_type = data.get("signup_type") or "email_only"

    if not email or not _EMAIL_RE.match(email):
        raise ValueError(f"Invalid or missing email: {data.get('email')!r}")
    if not product_id:
        raise ValueError("product_id is required")
    if signup_type not in VALID_SIGNUP_TYPES:
        raise ValueError(f"signup_type must be one of {VALID_SIGNUP_TYPES}, got {signup_type!r}")

    return SignupPayload(
        email=email,
        product_id=product_id,
        signup_type=signup_type,
        first_name=data.get("first_name"),
        company=data.get("company"),
        role=data.get("role"),
        utm_source=data.get("utm_source"),
        utm_medium=data.get("utm_medium"),
        utm_campaign=data.get("utm_campaign"),
        ip_country=data.get("ip_country"),
        page_path=data.get("page_path"),
    )


def _lead_row(payload: SignupPayload) -> dict:
    return {
        "product_id": payload.product_id,
        "email": payload.email,
        "name": payload.first_name,
        "company": payload.company,
        "role": payload.role,
        "source": payload.utm_source or "direct",
        "utm_source": payload.utm_source,
        "utm_medium": payload.utm_medium,
        "utm_campaign": payload.utm_campaign,
        "ip_country": payload.ip_country,
        "page_path": payload.page_path,
        "signup_type": payload.signup_type,
    }


def _insert_lead(row: dict, supabase_client: Optional[Any]) -> dict:
    client = supabase_client if supabase_client is not None else _get_supabase_client()
    response = client.table(LEADS_TABLE).insert(row).execute()
    data = getattr(response, "data", response)
    return data[0] if isinstance(data, list) and data else row


def _notify_visitor_capture_agent(lead: dict, webhook_url: Optional[str], http_client: Optional[Any]) -> Optional[str]:
    """Best-effort — a downstream enrichment hiccup must never fail the
    user's signup. Returns a warning string on failure, None on success
    or when no webhook URL is configured."""
    webhook_url = webhook_url or os.getenv("VISITOR_CAPTURE_WEBHOOK_URL")
    if not webhook_url:
        return None
    try:
        client = http_client
        if client is None:
            import httpx

            client = httpx
        client.post(webhook_url, json=lead, timeout=5.0)
        return None
    except Exception as exc:  # noqa: BLE001 — deliberately broad: never break signup on webhook failure
        log.warning("visitor_capture_agent webhook failed: %s", exc)
        return f"visitor_capture_agent webhook failed: {exc}"


def _sync_to_systeme(payload: SignupPayload, systeme_client: Optional[SystemeIOClient]) -> Optional[str]:
    """Best-effort CRM sync — same failure philosophy as the webhook
    notify above. A Systeme.io outage must not block signup."""
    if systeme_client is None:
        return None
    tag = f"product_{payload.product_id}_{'trial_active' if payload.signup_type == 'trial' else 'interested'}"
    try:
        systeme_client.create_contact(payload.email, tags=[tag], fields={"first_name": payload.first_name} if payload.first_name else None)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("Systeme.io sync failed for %s: %s", payload.email, exc)
        return f"Systeme.io sync failed: {exc}"


def process_signup(
    data: dict,
    *,
    supabase_client: Optional[Any] = None,
    systeme_client: Optional[SystemeIOClient] = None,
    visitor_capture_webhook_url: Optional[str] = None,
    http_client: Optional[Any] = None,
) -> dict:
    payload = validate_signup_payload(data)
    row = _lead_row(payload)
    lead = _insert_lead(row, supabase_client)

    warnings = []
    for warning in (
        _notify_visitor_capture_agent(lead, visitor_capture_webhook_url, http_client),
        _sync_to_systeme(payload, systeme_client),
    ):
        if warning:
            warnings.append(warning)

    return {"lead": lead, "warnings": warnings}
