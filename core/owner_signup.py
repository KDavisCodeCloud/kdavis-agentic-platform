"""
core/owner_signup.py
Owner account at signup (Kelvin, 2026-11-18).

/signup creates the founder's Supabase Auth account in the browser
(supabase.auth.signUp, which sends the verification email — the password
never reaches this API), then calls POST /workspaces with that account's id.
verify_new_owner() checks the id really is a brand-new account for the
email being signed up, so a request can't attach someone else's existing
account to a new workspace. The route then makes it the workspace's admin
member in the same transaction that creates the workspace.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# signUp and POST /workspaces run back to back in the browser; anything older
# than this is not a fresh signup.
OWNER_ACCOUNT_MAX_AGE = timedelta(minutes=30)


class OwnerVerificationError(ValueError):
    """The owner account can't be used for this signup; the message is safe to show."""


def _supabase_admin():
    from supabase import create_client  # lazy, same convention as api/middleware/auth.py

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured")
    return create_client(url, key)


def _parse_ts(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


async def verify_new_owner(supabase_user_id: str, email: str, now: datetime | None = None) -> None:
    """Raise OwnerVerificationError unless supabase_user_id is a fresh account for `email`."""
    try:
        resp = await asyncio.to_thread(_supabase_admin().auth.admin.get_user_by_id, str(supabase_user_id))
        user = getattr(resp, "user", None)
    except RuntimeError:
        raise
    except Exception:
        user = None
    if not user:
        raise OwnerVerificationError("We couldn't find your new account. Please sign up again.")

    if (getattr(user, "email", "") or "").strip().lower() != email.strip().lower():
        log.warning("[OwnerSignup] email mismatch for supabase_user=%s", supabase_user_id)
        raise OwnerVerificationError("The account email doesn't match the email you signed up with.")

    created = _parse_ts(getattr(user, "created_at", None))
    now = now or datetime.now(timezone.utc)
    if created is None or now - created > OWNER_ACCOUNT_MAX_AGE:
        raise OwnerVerificationError("This email already has an account. Log in instead.")
