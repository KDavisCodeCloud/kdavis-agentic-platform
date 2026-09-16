-- Onboarding completeness build, item 5 (welcome email as a 3-email
-- sequence). Tracks which of the day-2/day-5 emails a workspace has
-- already received, so the periodic sequence check (core/onboarding_sequence.py)
-- never sends either one twice. Day-0 (the existing welcome email,
-- core/email.py's welcome_email_html) is sent synchronously at checkout
-- and needs no tracking row -- it only ever fires once, from one call site.
CREATE TABLE IF NOT EXISTS workspace_onboarding_emails (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email_type    VARCHAR(20) NOT NULL CHECK (email_type IN ('day2_checklist', 'day5_setup_help')),
    sent_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, email_type)
);

CREATE INDEX IF NOT EXISTS idx_workspace_onboarding_emails_workspace
  ON workspace_onboarding_emails (workspace_id);
