# SOP: Enterprise MCP Invite (Cloud Decoded)
Date created: 2026-09-14
Product: Cloud Decoded
Status: Live (provisioning), alerting not yet automated

## When this applies
An Enterprise-tier customer needs per-user MCP OAuth 2.1 access (Claude
Code / Claude Desktop connecting directly via `mcp.theclouddecoded.com`)
instead of the shared workspace-token model Starter/Growth use.

## How you find out this is needed (currently manual)
As of 2026-09-14 there is **no automated alert** when a workspace becomes
Enterprise-eligible or when someone actually asks for MCP access — this
is discovered by:
- A direct customer request (email/call), or
- You noticing a workspace's `product_tier` is `enterprise` while
  checking `GET /internal/workspaces`.

`workspaces.contact_email` (migration 026) exists now specifically so
this loop can eventually be closed with a real alert — see GAPS.md for
the "wire a notification on tier change" item. Until that's built, check
manually.

## Provisioning the invite
1. Confirm the workspace is actually Enterprise:
   `GET /internal/workspaces/{id}` → `product_tier == "enterprise"`. If
   it isn't yet, set it first: `PATCH /internal/workspaces/{id}/tier`
   with `{"tier": "enterprise"}`.
2. `POST /internal/workspaces/{id}/mcp-invite` with:
   ```json
   {"email": "person@customer.com", "name": "Jane Doe", "scopes": ["mcp:read", "mcp:write"]}
   ```
   This provisions a real Supabase Auth account, sends Supabase's own
   invite email, and sets `app_metadata` (`workspace_id`, `workspace_tier`,
   `mcp_scopes`) that `mcp/auth/oauth.py` trusts at connection time.
3. If the response is a `502` about "invite email was sent but linking to
   the workspace failed" — the Supabase user exists but has no
   `workspace_id` set. Don't re-invite (creates a duplicate account
   conflict); fix `app_metadata` directly in Supabase or delete and
   re-invite that one user.
4. Confirm with the customer once they've completed Supabase's invite
   flow that their Claude Code / Claude Desktop MCP connection works
   against `mcp.theclouddecoded.com`.

## Revoking access
There's no dedicated revoke endpoint yet — remove/disable the user
directly in Supabase Auth (same instance internal admin users share,
distinguished via `app_metadata`). Flag as a gap if this comes up often.
