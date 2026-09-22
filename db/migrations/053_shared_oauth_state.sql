-- Migration 053 — shared OAuth state store, fixing a real "expired oauth
-- state" bug Kelvin hit live 2026-09-22 reconnecting LinkedIn.
--
-- Root cause: api/routes/internal_marketing.py's `_oauth_state_store` and
-- `_canva_pkce_store` were plain in-memory Python dicts, with a comment
-- literally admitting "fine for a single-process, single-owner manual
-- connect flow." This service runs `uvicorn --workers 4` in production
-- (Procfile / railway.json) -- 4 separate OS processes, each with its
-- own memory. The GET /connect/linkedin request that mints a state token
-- lands on one random worker; LinkedIn's callback request (a separate
-- HTTP request, seconds to minutes later) lands on another random
-- worker with a ~75% chance. That worker's dict never saw the state, so
-- every reconnect attempt failed "Invalid or expired OAuth state"
-- regardless of actual elapsed time -- not an intermittent issue, a
-- ~3-in-4-tries-fail-by-design one.
--
-- Fix: move both stores into Postgres, the shared store every worker
-- already connects to for everything else cross-process in this app
-- (advisory locks, notification queues, etc.) -- consistent with this
-- codebase's own convention rather than introducing Redis (present as a
-- transitive dependency, not an established pattern here).

CREATE TABLE IF NOT EXISTS internal_oauth_state (
  state          TEXT PRIMARY KEY,
  purpose        TEXT NOT NULL CHECK (purpose IN ('linkedin', 'canva')),
  code_verifier  TEXT,  -- Canva's PKCE verifier only; NULL for linkedin
  issued_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE internal_oauth_state ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "internal_oauth_state_service_role" ON internal_oauth_state;
CREATE POLICY "internal_oauth_state_service_role" ON internal_oauth_state
  FOR ALL TO service_role USING (true) WITH CHECK (true);
