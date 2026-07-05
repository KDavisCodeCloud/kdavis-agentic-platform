-- Empire Dashboard update — 2026-07-04 Session 4
-- Both dashboards built. Pipeline write bug fixed. CEO schema migration ready.
-- Paste into Supabase SQL Editor for the empire-dashboard project. Run all at once.


-- ─── PRODUCT STATUS UPDATE — MSE ──────────────────────────────────────────────

UPDATE products SET
  status        = 'Building',
  base_progress = 70,
  phase_note    = 'All 13 code gaps closed. Research swarm live (orchestrator + aggregator + 7-gate filter). MSE dashboard built: 5 pages (Overview, Research Swarm, Pipeline, Agents, Retention) with 3-col design shell. Pipeline write bug fixed — all NOT NULL columns now mapped. CEO FastAPI routes + migration 004 ready. Next: run migration 004, set env vars, deploy both dashboards. Week 2 agent (Pulse — Healthcare) Thursday 2026-07-10.',
  updated_at    = NOW()
WHERE id = 'micro-saas';


-- ─── PRODUCT STATUS UPDATE — CEO DECODED ──────────────────────────────────────

UPDATE products SET
  status        = 'Building',
  base_progress = 35,
  phase_note    = 'Dashboard built: Next.js 15, 10 departments, magic link auth, role-based middleware (admin/marketing/rnd), Supabase realtime on Overview. Needs: migration 004 run in microsaas-prod, .env.local created, user roles set in Supabase Auth, Vercel deploy to ceo.decodedempire.com.',
  updated_at    = NOW()
WHERE id = 'ceo-decoded';


-- ─── SESSION LOG ──────────────────────────────────────────────────────────────

INSERT INTO session_logs (product_id, content, created_at) VALUES
('micro-saas',
'2026-07-04 Session 4 — Both dashboards built. All 13 MSE code gaps closed.

DONE (code — Claude):
• api/routers/stripe.py — Stripe webhook, subscription lifecycle, tenant upsert
• core/supabase_client.py — service-role vs per-request split, RLS enforced via anon key + JWT
• legal/ — EULA.md, privacy-policy.md, dpa-template.md (AZ/Maricopa County)
• migration 003 — RLS rewritten to auth.uid() (dropped custom setting approach)
• agents/orchestrator/agent.py — LangGraph StateGraph, fans out to 6 verticals via asyncio.gather
• agents/aggregator/agent.py — 7-gate quality filter, READY_TO_BUILD stamp
• api/routers/research.py — /research/run (returns session_id) + /research/session/{id}
• Research swarm ran end-to-end — findings confirmed, pipeline write bug found
• Pipeline write bug FIXED — node_write_pipeline now maps all NOT NULL cols (pain_point, icp, etc.)
• api/routers/ceo.py — HITL approve/reject, legal Q&A, advisory brief, /ceo/health
• migration 004 — CEO schema: 10 tables seeded (team_members, agent_events, hitl_queue,
  operating_stack, build_queue, session_log, gap_tracker, legal_documents,
  advisory_threads, hitl_routing_rules) + operating stack + team + gaps seeded
• MSE dashboard (frontend/) — full rebuild: 5 pages, 3-col shell, green brand accent
• CEO dashboard (ceo-dashboard/) — 10 departments, mint brand, role-gated middleware

DONE (manual — Kelvin):
• ANTHROPIC_API_KEY filled in .env
• RESEND_API_KEY filled in .env
• n8n: first-run setup, Supabase credential added, both workflows activated
• SUPABASE_ANON_KEY added to .env

STILL OPEN (manual — next):
• Run migration 004 in Supabase SQL Editor (microsaas-prod)
• Create ceo-dashboard/.env.local with Supabase URL + anon key
• Create frontend/.env.local with Supabase URL + anon key
• Set user roles in Supabase Auth → user_metadata: {role: admin/marketing/rnd}
• Add auth redirect URLs (localhost:3000, localhost:3001, prod domains)
• Push both repos to GitHub
• Deploy CEO dashboard to Vercel (root: ceo-dashboard, domain: ceo.decodedempire.com)
• Deploy MSE frontend to Vercel (root: frontend, domain: mse.decodedempire.com)',
NOW()),

('ceo-decoded',
'2026-07-04 — CEO Decoded dashboard built.

37 files committed to kdavis-agentic-platform/ceo-dashboard/.
Stack: Next.js 15 App Router, Tailwind with design tokens, @supabase/ssr magic link auth.
10 departments: Overview, Finance, R&D, Tech, Ops, Marketing, HR, Legal, Advisory, Video.
Realtime: agent_events + hitl_queue on Overview (live approve/reject buttons wired).
Role gating: admin (Kelvin all), marketing (Wife: marketing/ops/hr/video), rnd (Son: rnd/tech read-only).
TypeScript: zero errors.

Next: run migration 004, set .env.local, set user roles, deploy to Vercel.',
NOW());


-- ─── MARK COMPLETED TASKS ─────────────────────────────────────────────────────

UPDATE tasks SET done = true, done_at = NOW()
WHERE product_id = 'micro-saas'
AND text IN (
  'Fill ANTHROPIC_API_KEY in .env (console.anthropic.com → API Keys)',
  'Fill RESEND_API_KEY in .env (resend.com → API Keys)',
  'n8n: complete first-run owner setup at localhost:5678',
  'n8n: add Supabase credential (microsaas-supabase) — URL + service role key',
  'n8n: update RESEND_API_KEY in n8n/start-n8n.sh and activate both workflows',
  'Claude: build api/routers/stripe.py — webhook handler, tenant lifecycle (create/update/churn)',
  'Claude: fix core/supabase_client.py — per-request authenticated client so RLS actually enforces',
  'Claude: build legal/EULA.md, legal/privacy-policy.md, legal/dpa-template.md',
  'Thursday: agents/orchestrator/agent.py — LangGraph graph wired to orchestrator/prompt.md',
  'Thursday: agents/aggregator/agent.py — 7-gate quality filter runner',
  'Thursday: wire _run_orchestrator_stub in research.py to real orchestrator',
  'Stripe CLI setup for local webhook testing (stripe listen --forward-to localhost:8000/stripe/webhook)'
);


-- ─── NEW TASKS ────────────────────────────────────────────────────────────────

INSERT INTO tasks (product_id, text, priority) VALUES

-- Manual setup (Kelvin — do before next session)
('micro-saas', 'Run migration 004 in Supabase SQL Editor (microsaas-prod) — CEO schema + seeds', 'high'),
('micro-saas', 'Create ceo-dashboard/.env.local — SUPABASE_URL, SUPABASE_ANON_KEY, MSE_API_URL', 'high'),
('micro-saas', 'Create frontend/.env.local — SUPABASE_URL, SUPABASE_ANON_KEY, API_URL', 'high'),
('micro-saas', 'Supabase Auth: set user_metadata {role:admin} for Kelvin, {role:marketing} for Wife, {role:rnd} for Son', 'high'),
('micro-saas', 'Supabase Auth → URL Config: add localhost:3000, localhost:3001, prod domain /auth/callback to redirect URLs', 'high'),
('micro-saas', 'Push kdavis-microsaas-engine to GitHub', 'mid'),
('micro-saas', 'Push kdavis-agentic-platform to GitHub', 'mid'),
('micro-saas', 'Deploy MSE frontend to Vercel — root: frontend, domain: mse.decodedempire.com', 'mid'),

('ceo-decoded', 'Deploy CEO dashboard to Vercel — root: ceo-dashboard, domain: ceo.decodedempire.com', 'mid'),

-- Next Claude sessions (agent cadence)
('micro-saas', 'Thursday 2026-07-10: Week 2 agent — Pulse (Healthcare vertical market sizing)', 'high'),
('micro-saas', 'Thursday 2026-07-17: Week 3 agent — Comply (Legal vertical competitor depth)', 'mid'),
('micro-saas', 'Thursday 2026-07-24: Week 4 agent — Anchor (Real estate ICP validation)', 'mid');
