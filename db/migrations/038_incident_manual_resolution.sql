-- Migration 038: manual resolution path for HITL incident cards.
--
-- "I'll handle this myself" is a resolution acknowledgment, not an
-- execution path -- the platform never runs anything here. It just
-- records that the operator resolved the incident outside the platform
-- (no cloud API call, no agent run, no credential access) and, if they
-- chose to, what they did -- so it's queryable for their own reporting
-- ("all incidents resolved manually this month") and counted in MTTR
-- alongside 'executed' incidents (resolved_at - created_at is populated
-- identically to core/hitl.py's mark_executed() path).
--
-- execution_status keeps its existing convention (VARCHAR(50), no CHECK
-- constraint -- see migration 001) of documenting valid values in a
-- comment rather than a DB-enforced enum; 'resolved_manually' joins that
-- comment here, not a new constraint.

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS resolution_note TEXT;

COMMENT ON COLUMN incidents.execution_status IS
    'pending_approval | executing | executed | held | failed | budget_exceeded | rejected | resolved_manually';

COMMENT ON COLUMN incidents.resolution_note IS
    'Optional operator note on manual resolution ("I''ll handle this myself" on the HITL card). NULL for every other resolution path.';
