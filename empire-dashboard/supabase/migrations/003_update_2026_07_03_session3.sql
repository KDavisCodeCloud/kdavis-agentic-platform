-- Empire Dashboard update — 2026-07-03 Session 3
-- Full infrastructure sprint complete.
-- Paste into Supabase SQL Editor for the empire-dashboard project. Run all at once.

-- ─── PRODUCT STATUS UPDATE ────────────────────────────────────────────────────

UPDATE products SET
  status        = 'Building',
  base_progress = 45,
  phase_note    = 'Full infra live: Supabase (6 tables + RLS), FastAPI (12 routes, e2e tested), Next.js 15 (4 routes), n8n 2.28.6 (2 workflows imported). Stripe account created (Micro Saas Decoded). Code gaps remain: Stripe webhook handler, RLS per-request client, legal docs. Agent build cadence starts Thursday.',
  updated_at    = NOW()
WHERE id = 'micro-saas';


-- ─── SESSION LOG ──────────────────────────────────────────────────────────────

INSERT INTO session_logs (product_id, content, created_at) VALUES
('micro-saas',
'Manual setup + infra sprint complete (2026-07-03 Session 3).
DONE:
• Python packages installed globally (supabase, langgraph, langchain-anthropic, resend, stripe)
• .env created and 80% filled (Supabase keys, Stripe live key — ANTHROPIC + RESEND still needed)
• Stripe account created: Micro Saas Decoded (acct_1TpLcKLIpoJRr7Tc) — separate from Decoded Holdings LLC per Rule 8
• Supabase project created: microsaas-prod
• Supabase CLI v2.109.0 installed + project linked + both migrations pushed
• All 6 tables live with RLS: tenants, usage_events, milestones, retention_sequences, weekly_digest_log, opportunity_pipeline
• API fully operational: 12 routes, /health 200, /docs 200, POST /events writes row to prod DB (confirmed)
• Bug fixed: tenant_context.py was blocking /docs + /openapi.json with JWT auth
• Node.js v22 + v24 installed via nvm
• Next.js 15 initialized: 4 routes live (/, /dashboard, /pipeline, /research), UsageTracker wired into root layout
• n8n 2.28.6 installed on Node 22 (patched @langchain/core exports bug), both workflows imported, health OK at localhost:5678
STILL OPEN:
• ANTHROPIC_API_KEY + RESEND_API_KEY to fill in .env
• n8n: first-run owner setup + Supabase credential + workflow activation (manual UI)
• Stripe webhook handler (api/routers/stripe.py) — next Claude session
• RLS per-request client fix (core/supabase_client.py) — next Claude session
• Legal docs (legal/) — next Claude session
• Agent .py files — Thursday build cadence',
NOW());


-- ─── MARK COMPLETED TASKS ─────────────────────────────────────────────────────

UPDATE tasks SET done = true, updated_at = NOW()
WHERE product_id = 'micro-saas'
AND text IN (
  'pip install -r requirements.txt + fill .env with real keys',
  'supabase init + link microsaas-prod + push both migrations',
  'Verify all 6 tables exist with RLS in Supabase dashboard',
  'npx create-next-app in /frontend + wire UsageTracker into layout.tsx',
  'Run uvicorn + hit /health + test POST /events with a Supabase JWT'
);


-- ─── NEW TASKS ────────────────────────────────────────────────────────────────

INSERT INTO tasks (product_id, text, priority) VALUES

-- Remaining manual setup (Kelvin)
('micro-saas', 'Fill ANTHROPIC_API_KEY in .env (console.anthropic.com → API Keys)', 'high'),
('micro-saas', 'Fill RESEND_API_KEY in .env (resend.com → API Keys)', 'high'),
('micro-saas', 'n8n: complete first-run owner setup at localhost:5678', 'high'),
('micro-saas', 'n8n: add Supabase credential (microsaas-supabase) — URL + service role key', 'high'),
('micro-saas', 'n8n: update RESEND_API_KEY in n8n/start-n8n.sh and activate both workflows', 'high'),

-- Next Claude session (code)
('micro-saas', 'Claude: build api/routers/stripe.py — webhook handler, tenant lifecycle (create/update/churn)', 'high'),
('micro-saas', 'Claude: fix core/supabase_client.py — per-request authenticated client so RLS actually enforces', 'high'),
('micro-saas', 'Claude: build legal/EULA.md, legal/privacy-policy.md, legal/dpa-template.md', 'mid');
