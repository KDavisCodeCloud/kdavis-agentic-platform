-- Migration 061: root-cause evidence on incidents (gap-table #6).
--
-- An ordered list of evidence blocks -- log excerpts, kubectl output,
-- metrics, terraform plan, CLI output -- each {kind, title, lines[]}, shown
-- above the remediation options so an approver sees WHY before choosing
-- WHAT. Nullable: every existing incident and every agent that doesn't
-- produce evidence yet keeps rendering exactly as before.
--
-- The per-option additions (diff, blast_radius, execution_log) live inside
-- the existing remediation_options JSONB, so they need no column.
--
-- No new table, so no new RLS policy; incidents keeps its workspace-scoped
-- RLS from migration 031.

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS evidence JSONB;
