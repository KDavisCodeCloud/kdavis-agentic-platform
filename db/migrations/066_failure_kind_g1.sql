-- Migration 066: allow G1's failure kinds (lab run 3).
--
-- core/execution_outcome.py (Break-It Lab item 2, G1) records an approved
-- option that did nothing as failure_kind 'not_executed', and one that only
-- partly ran as 'partial_execution'. Migration 050's CHECK still allowed only
-- 'permission_denied' / 'execution_error', so every such write raised
-- CheckViolationError on a real database (found on staging, lab run 3: A4/Z5).
-- No new table, so no new RLS policy.

ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_failure_kind_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_failure_kind_check
    CHECK (failure_kind IS NULL OR failure_kind IN
           ('permission_denied', 'execution_error', 'not_executed', 'partial_execution'));
