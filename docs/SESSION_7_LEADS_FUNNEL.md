# Session 7 — Leads Funnel Completion

Paste this prompt into Claude Code from `/mnt/c/Users/Kelvin/projects/kdavis-agentic-platform`.
Walk away — no input needed.

---

Read CLAUDE.md and EXECUTION_ORDER.md.

Task: Complete the leads capture funnel so that signups from pixel.js / signup_handler.py
flow into Supabase and trigger a Slack notification. The `leads/` directory already has
the scaffold — complete what's missing or incomplete.

**Context:**
- `leads/capture/pixel.js` — tracking pixel / JS snippet
- `leads/capture/signup_handler.py` — handles signup form POST
- `leads/capture/trial_handler.py` — handles trial start
- `leads/integrations/webhook_receiver.py` — receives external webhook (e.g. Systeme.io)
- `leads/integrations/systeme_io.py` — Systeme.io API client
- `leads/integrations/slack.py` — Slack notification

**Step 1 — Read all 6 files in leads/ before writing anything.**

**Step 2 — Identify what's missing:**
- Does `signup_handler.py` write to Supabase `leads` table? If not, add it.
- Does `webhook_receiver.py` parse the Systeme.io payload and write to Supabase? If not, fix it.
- Does `slack.py` send a Slack message with lead name, email, product, source? If not, complete it.

**Step 3 — Create SQL migration if leads table doesn't exist in `db/migrations/`:**
Check `db/migrations/` for a leads table. If not found, create `db/migrations/005_leads.sql`:
```sql
-- 005_leads.sql
CREATE TABLE IF NOT EXISTS leads (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id    text NOT NULL,
  tenant_id     uuid REFERENCES workspaces(id) ON DELETE SET NULL,
  email         text NOT NULL,
  name          text,
  source        text NOT NULL DEFAULT 'organic',
  stage         text NOT NULL DEFAULT 'signup' CHECK (stage IN ('signup','trial','converted','churned')),
  metadata      jsonb DEFAULT '{}',
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON leads
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "workspace_read" ON leads
  FOR SELECT TO authenticated
  USING (tenant_id = (current_setting('app.workspace_id')::uuid));
```

**Step 4 — Complete signup_handler.py:**
Read `os.getenv('SUPABASE_URL')` and `os.getenv('SUPABASE_SERVICE_ROLE_KEY')`.
On valid POST:
- Validate email (regex)
- Insert into `leads` table
- Call `slack.send_lead_notification(name, email, product_id, source)`
- Write to `audit_log`: action='lead_captured', agent_id='leads_funnel'
- Return `{"success": True, "lead_id": str(lead_id)}`
On failure: raise with descriptive message (no silent failures).

**Step 5 — Complete slack.py:**
Read `SLACK_LEADS_WEBHOOK_URL` from `os.getenv()`.
If not set: log a warning, return early (do not raise).
If set: POST to Slack with message:
```
🎯 New lead on {product_id}
Name: {name or 'unknown'}
Email: {email}
Source: {source}
```

**Step 6 — Add missing env vars to .env.example:**
Add these with empty values if not already present:
- `SUPABASE_URL=`
- `SUPABASE_SERVICE_ROLE_KEY=`
- `SLACK_LEADS_WEBHOOK_URL=`

**Step 7 — Smoke test:**
Run: `python -c "from leads.capture.signup_handler import handle_signup; print('OK')"`
Fix any import errors.

Do NOT modify any files outside `leads/`, `db/migrations/`, `.env.example`.

Output ✅ DONE or 🚫 BLOCKED then stop.
