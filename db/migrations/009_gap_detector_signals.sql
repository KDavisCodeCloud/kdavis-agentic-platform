-- Signal sources for gap_detector_agent.weekly_scan() — three of its four
-- inputs (AgentRunRecord, HITLCorrection, ChatQuery) had no live backing at
-- all. The fourth (AgentRosterEntry) is deliberately NOT a table here — it's
-- derived directly from api/routes/internal_agents.py's own
-- _KNOWN_INTERNAL_AGENTS/_WIRABLE_AGENTS constants at call time, which is
-- always in sync with reality and can't drift from a separate roster table.

-- Extends internal_agent_runs (008) rather than duplicating it — this IS a
-- real agent-run log already, just missing the two columns
-- gap_detector_agent's AgentRunRecord needs. Nullable: existing rows and
-- the 9 already-wired agents that don't pass these don't break.
ALTER TABLE internal_agent_runs ADD COLUMN IF NOT EXISTS product_id TEXT;
ALTER TABLE internal_agent_runs ADD COLUMN IF NOT EXISTS confidence_score NUMERIC;

-- Repeated HITL manual-override pattern — nothing in this codebase writes
-- here yet (the ceo-dashboard's HitlApprovalRow.tsx approve/reject flow
-- would need its own follow-up wiring to populate this on a "corrected"
-- action, out of scope for a backend-only pass). Table exists so
-- gap_detector_agent's dispatch has something real, if empty, to query.
CREATE TABLE IF NOT EXISTS hitl_corrections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_name TEXT NOT NULL,
  original_option TEXT NOT NULL,
  corrected_option TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hitl_corrections_agent ON hitl_corrections(agent_name);

ALTER TABLE hitl_corrections ENABLE ROW LEVEL SECURITY;
CREATE POLICY "hitl_corrections_service_role" ON hitl_corrections
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Chat turns that fell through to the Claude think tank instead of a real
-- handler. Actually populated (see api/routes/internal_agents.py's
-- chat_router_agent branch, updated in the same pass as this migration) —
-- unlike hitl_corrections, this one has a real writer from day one.
CREATE TABLE IF NOT EXISTS chat_queries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  query_text TEXT NOT NULL,
  routed_to_claude BOOLEAN NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_queries_occurred_at ON chat_queries(occurred_at DESC);

ALTER TABLE chat_queries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "chat_queries_service_role" ON chat_queries
  FOR ALL TO service_role USING (true) WITH CHECK (true);
