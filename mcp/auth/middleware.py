"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
MCPAuthMiddleware — pure ASGI middleware for MCP server authentication.

Why pure ASGI (not Starlette's BaseHTTPMiddleware):
  BaseHTTPMiddleware buffers the entire response body before sending it.
  SSE responses are infinite streams — buffering breaks them. This
  middleware wraps the ASGI app directly and never touches the response.

Flow per request:
  1. Skip exempt paths (/health, /.well-known/...)
  2. Extract Authorization: Bearer <token> header
  3. Determine auth method: API key (cd_mcp_ prefix) or OAuth JWT
  4. Validate and build CallerIdentity
  5. Set CallerIdentity in ContextVar (auth/context.py)
  6. Forward to the next ASGI app

On any failure: send a JSON 401/403 and stop — never forward to the app.

Per-request identity rule: every request must carry its own token.
No session stickiness, no shared auth across SSE and message endpoints.
"""

import json
import logging

from starlette.types import ASGIApp, Scope, Receive, Send

from auth.apikey import validate_api_key, API_KEY_PREFIX
from auth.context import set_caller
from auth.models import AuthError
from auth.oauth import validate_oauth_token
from db import get_pool

log = logging.getLogger(__name__)

# Paths that bypass auth — liveness probe and OAuth metadata discovery
_EXEMPT_PATHS: frozenset[str] = frozenset({
    "/health",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
})


class MCPAuthMiddleware:
    """
    Pure ASGI auth middleware. SSE-safe — never buffers the response body.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only inspect HTTP requests — pass WebSocket and lifespan events through
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        if path in _EXEMPT_PATHS:
            await self._app(scope, receive, send)
            return

        # Parse Authorization header from ASGI scope headers (bytes)
        headers: dict[bytes, bytes] = {k.lower(): v for k, v in scope.get("headers", [])}
        auth_value: str = headers.get(b"authorization", b"").decode("latin-1")

        if not auth_value.lower().startswith("bearer "):
            await _send_error(
                send, 401,
                "unauthorized",
                "Missing or malformed Authorization header. "
                "Expected: Authorization: Bearer <token>",
            )
            return

        raw_token = auth_value[7:].strip()  # strip "Bearer "

        try:
            if raw_token.startswith(API_KEY_PREFIX):
                identity = await validate_api_key(raw_token, get_pool())
            else:
                identity = await validate_oauth_token(raw_token)

            set_caller(identity)
            log.debug(
                "[Auth] OK workspace=%s method=%s scope=%s path=%s",
                identity.workspace_id,
                identity.auth_method,
                ",".join(sorted(identity.scopes)),
                path,
            )

        except AuthError as exc:
            log.warning(
                "[Auth] Rejected path=%s method=%s error=%s",
                path,
                "api_key" if raw_token.startswith(API_KEY_PREFIX) else "oauth",
                exc,
            )
            await _send_error(send, exc.status_code, "unauthorized", str(exc))
            return

        await self._app(scope, receive, send)


async def _send_error(
    send: Send,
    status_code: int,
    error: str,
    detail: str,
) -> None:
    body = json.dumps({"error": error, "detail": detail}).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status_code,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", b'Bearer realm="mcp.theclouddecoded.com"'),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })
