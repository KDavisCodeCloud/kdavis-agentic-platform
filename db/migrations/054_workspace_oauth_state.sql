-- Migration 054 — shared OAuth state store for the customer-facing
-- content pipeline's LinkedIn/X connect flow (api/routes/content.py).
--
-- Same root cause as migration 053's internal_oauth_state, found while
-- investigating that one: content.py's `_oauth_state_store` is the exact
-- same in-memory dict pattern, with its own comment admitting the gap
-- ("In production: move to Redis with TTL" -- never done). This service
-- runs 4 uvicorn workers in production, so a paying customer connecting
-- their own LinkedIn or X account via GET /content/connect/{linkedin,x}
-- has had roughly a 3-in-4 chance of the callback landing on a worker
-- that never saw the state, failing "Invalid or expired OAuth state"
-- regardless of how fast they completed the platform's login screen.
-- This is customer-facing (workspace_social_connections), not just the
-- internal owner-only flow -- likely support friction nobody traced to
-- this cause.
--
-- workspace_id is stored per-state (not resolvable from the state token
-- itself) so the callback can attribute the connection to the right
-- workspace regardless of which worker handles it. code_verifier is
-- X's PKCE-only field, NULL for LinkedIn.

CREATE TABLE IF NOT EXISTS workspace_oauth_state (
  state          TEXT PRIMARY KEY,
  workspace_id   UUID NOT NULL,
  platform       TEXT NOT NULL CHECK (platform IN ('linkedin', 'x')),
  code_verifier  TEXT,
  issued_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE workspace_oauth_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "workspace_oauth_state_service_role" ON workspace_oauth_state;
CREATE POLICY "workspace_oauth_state_service_role" ON workspace_oauth_state
  FOR ALL TO service_role USING (true) WITH CHECK (true);
