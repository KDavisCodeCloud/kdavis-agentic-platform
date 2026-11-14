"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Public demo sandbox (24-gap-closure build, Phase 6).

GET /demo -- no auth, no signup. Mints a scoped, 24h demo session
(core/demo_sandbox.py's create_demo_session) against the one shared demo
workspace, pre-seeded with 8 synthetic incidents. The returned token is
approver-level (Approve/Reject/Resolve-manually all genuinely work) but
cannot authenticate against Settings/Members/Billing/Connections routes
at all -- see api/middleware/auth.py's get_workspace_or_member_or_demo
and core/demo_sandbox.py's module docstring for the three independent
guarantees that no real cloud action can ever fire from this workspace.

Rate-limited with the shared `limiter` (api/middleware/rate_limiter.py),
same fixed-string convention api/routes/email_public.py already uses for
anonymous/pre-workspace requests -- falls back to source IP since there
is no workspace token yet to key on.

State (migration 059): every call seeds the new session its own copy of
the 8 baseline incidents, so no visitor can change what another visitor
sees. api/main.py's _demo_reset_loop (core/demo_sandbox.py's
run_demo_reset) prunes expired sessions every 30 minutes, and their
incidents and comments cascade away with them.
"""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from api.middleware.rate_limiter import limiter
from core.demo_sandbox import create_demo_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/demo", tags=["demo"])


class DemoSessionResponse(BaseModel):
    demo_token: str
    expires_at: str
    message: str = "Synthetic demo workspace — nothing here is real, and no action here ever touches a real cloud account."


@router.get("", response_model=DemoSessionResponse)
@limiter.limit("10/minute")
async def start_demo_session(request: Request) -> DemoSessionResponse:
    demo_token, expires_at = await create_demo_session(request.app.state.db_pool)
    log.info("[Demo] New demo session minted, expires_at=%s", expires_at.isoformat())
    return DemoSessionResponse(demo_token=demo_token, expires_at=expires_at.isoformat())
