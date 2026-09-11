-- Migration 019: cloud_audit_submissions + cloud_audit_remediation_items
--
-- Phase 2C of kdavis-cloud-audit: api/routes/audit.py's POST /api/v1/audit/submit
-- stores a CLI-submitted findings scan, and agents/audit_analysis/workflow.py
-- turns it into a prioritized, human-approvable remediation plan.
--
-- Named cloud_audit_* rather than audit_* on purpose: this shared database
-- already has audit_log, audit_dimensions, audit_findings, audit_reports,
-- and audit_sessions tables belonging to an unrelated consulting/scorecard
-- product -- confirmed live 2026-09-10 while investigating gap #4. Using
-- audit_findings here would either collide outright or silently no-op
-- against the wrong table if run with IF NOT EXISTS.
--
-- No resume/execution flow needed on the remediation items (unlike
-- incidents.execution_status): approving one is a terminal status change a
-- human acts on manually, never automatic. See GAPS.md / EXECUTION_ORDER.md
-- for why this doesn't reuse the incidents table.

CREATE TABLE IF NOT EXISTS cloud_audit_submissions (
    id                                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id                      UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider                          VARCHAR(20) NOT NULL,
    scan_duration_seconds             NUMERIC(10,2),
    total_findings                    INT NOT NULL DEFAULT 0,
    total_estimated_monthly_waste_usd NUMERIC(10,2) NOT NULL DEFAULT 0,
    raw_findings                      JSONB NOT NULL,
    status                            VARCHAR(20) NOT NULL DEFAULT 'analyzing',
    analysis_error                    TEXT,
    created_at                        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cloud_audit_remediation_items (
    id                           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id                UUID NOT NULL REFERENCES cloud_audit_submissions(id) ON DELETE CASCADE,
    workspace_id                 UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    severity                     VARCHAR(10) NOT NULL,
    category                     VARCHAR(20) NOT NULL,
    title                        TEXT NOT NULL,
    description                  TEXT NOT NULL,
    remediation                  TEXT NOT NULL,
    estimated_monthly_waste_usd  NUMERIC(10,2) NOT NULL DEFAULT 0,
    priority_rank                INT NOT NULL,
    status                       VARCHAR(20) NOT NULL DEFAULT 'pending_approval',
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actioned_at                  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cloud_audit_submissions_workspace ON cloud_audit_submissions (workspace_id);
CREATE INDEX IF NOT EXISTS idx_cloud_audit_items_submission ON cloud_audit_remediation_items (submission_id);
CREATE INDEX IF NOT EXISTS idx_cloud_audit_items_workspace ON cloud_audit_remediation_items (workspace_id);

ALTER TABLE cloud_audit_submissions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON cloud_audit_submissions
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "workspace_read" ON cloud_audit_submissions
  FOR SELECT TO authenticated
  USING (workspace_id = (current_setting('app.workspace_id')::uuid));

ALTER TABLE cloud_audit_remediation_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON cloud_audit_remediation_items
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "workspace_read" ON cloud_audit_remediation_items
  FOR SELECT TO authenticated
  USING (workspace_id = (current_setting('app.workspace_id')::uuid));
