-- Migration 015: audit_log.outcome constraint was scoped to one caller's
-- narrow vocabulary and blocked every other agent in the codebase.
--
-- Found 2026-07-23/24 running the first real end-to-end MKT-LI1 batch:
-- audit_log_outcome_check only allowed 'win'/'lose' (the MSE opportunity
-- dashboard's vocabulary -- the only caller that had ever actually
-- written a row, per the 113 pre-existing rows checked before this fix).
-- Every other agent in this codebase uses its own independent vocabulary:
--   agents/marketing/*        -- "success" / "failure: <detail>"
--   agents/marketing/mkt_10   -- "passed" / "flagged: <n> issue(s)"
--   agents/mse/{opportunity_finder,product_spec_writer,demand_validator}
--                             -- "ok" / "error"
--   core/engine.py            -- "hitl_approved" / "ok" / "assertion_failed"
-- None of these had ever been exercised against the live schema before
-- today, so the mismatch was invisible until MKT-LI1 became the first
-- non-MSE caller to actually run.
--
-- A whitelist constraint doesn't fit a column with this many independently
-- evolved vocabularies and no single source of truth across agent
-- families -- replaced with a simple non-empty check rather than
-- continuing to whack-a-mole new values in as each agent family's first
-- real run discovers another gap.

ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_outcome_check;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_outcome_check CHECK (length(outcome) > 0);
