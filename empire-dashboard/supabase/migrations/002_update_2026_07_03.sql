-- Empire Dashboard data update — 2026-07-03
-- Paste into Supabase SQL Editor for the empire-dashboard project.
-- Run all at once.

-- ─── PRODUCT STATUS UPDATES ─────────────────────────────────────────────────

-- Micro SaaS Engine: Backlog → Building, scaffold complete
UPDATE products SET
  status        = 'Building',
  base_progress = 20,
  phase_note    = 'Scaffold + retention infra done. Awaiting: Supabase link, n8n import, Next.js init. Agent build starts Thursday.',
  updated_at    = NOW()
WHERE id = 'micro-saas';

-- Cloud Decoded: still Building, no change to progress — infra blockers unchanged
-- Leaving at 85% / "MVP built - deploy blockers: Supabase, Stripe IDs, hosting, DNS, auth pages"
-- Uncomment and edit if status changes:
-- UPDATE products SET phase_note = '...', updated_at = NOW() WHERE id = 'cloud-decoded';


-- ─── SESSION LOGS ────────────────────────────────────────────────────────────

-- Micro SaaS Engine — Sprint 1 build session
INSERT INTO session_logs (product_id, content, created_at) VALUES
('micro-saas',
'Sprint 1 complete (2026-07-03). Built full scaffold in one session:
• All 6 Supabase retention tables + RLS migrations written (001, 002)
• FastAPI: 7 routers (events, milestones, digest, pipeline, mcp, reengagement, research), 2 middleware, main.py
• Core retention: milestone_detector, reengagement_trigger, digest_generator, llm_router (Haiku/Sonnet split), DataSanitizationShield
• Agent prompts: orchestrator (fan-out controller), aggregator (7-gate quality filter, READY_TO_BUILD stamp authority)
• n8n workflows: weekly digest (Sunday 20:00 MST) + reengagement (daily 09:00 MST) — JSON ready to import
• Frontend: UsageTracker, MilestoneToast, WeeklySnapshot components + dashboard/pipeline/research pages
• Docs: full data dictionary + 6 architecture decision records
• Repo live: github.com/KDavisCodeCloud/kdavis-microsaas-engine
Blocked on: Supabase project link, Python venv install, Next.js init, n8n import. All manual steps.',
NOW());


-- ─── OPEN TASKS — MICRO SAAS ENGINE ─────────────────────────────────────────

-- Clear any stale placeholder tasks first (only if you want a clean slate)
-- DELETE FROM tasks WHERE product_id = 'micro-saas' AND done = false;

-- Manual setup tasks (Kelvin runs these)
INSERT INTO tasks (product_id, text, priority) VALUES
('micro-saas', 'pip install -r requirements.txt + fill .env with real keys', 'high'),
('micro-saas', 'supabase init + link microsaas-prod + push both migrations', 'high'),
('micro-saas', 'Verify all 6 tables exist with RLS in Supabase dashboard', 'high'),
('micro-saas', 'npx create-next-app in /frontend + wire UsageTracker into layout.tsx', 'high'),
('micro-saas', 'Import both n8n workflow JSONs + configure Supabase + Resend credentials', 'high'),
('micro-saas', 'Run uvicorn + hit /health + test POST /events with a Supabase JWT', 'high'),
('micro-saas', 'Stripe CLI setup for local webhook testing (stripe listen --forward-to localhost:8000/stripe/webhook)', 'mid'),

-- Next Claude session tasks
('micro-saas', 'Claude: fix RLS — refactor supabase_client.py to use per-request authenticated client (not service_role for tenant queries)', 'high'),
('micro-saas', 'Claude: build api/routers/stripe.py — webhook handler + tenant lifecycle (create on sub.created, tier on sub.updated, churn on sub.deleted)', 'high'),
('micro-saas', 'Claude: build legal/ — EULA.md, privacy-policy.md, dpa-template.md', 'mid'),

-- Thursday agent build night (Week 1)
('micro-saas', 'Thursday: agents/orchestrator/agent.py — LangGraph graph wired to orchestrator/prompt.md', 'high'),
('micro-saas', 'Thursday: agents/aggregator/agent.py — 7-gate quality filter runner', 'high'),
('micro-saas', 'Thursday: wire _run_orchestrator_stub in research.py to real orchestrator', 'high'),
('micro-saas', 'Thursday: test single vertical (healthcare) before enabling full swarm', 'mid'),

-- Thursday agent build night (Week 2+)
('micro-saas', 'Week 2 Thursday: agents/healthcare-intel/prompt.md + agent.py', 'mid'),
('micro-saas', 'Week 3 Thursday: agents/legal-intel/prompt.md + agent.py', 'mid'),
('micro-saas', 'Week 4 Thursday: agents/ecommerce-intel/prompt.md + agent.py', 'mid'),
('micro-saas', 'Week 5 Thursday: agents/realestate-intel/prompt.md + agent.py', 'mid'),
('micro-saas', 'Week 6 Thursday: agents/hr-ops-intel/prompt.md + agent.py', 'mid'),
('micro-saas', 'Week 7 Thursday: agents/finance-intel/prompt.md + agent.py', 'mid'),
('micro-saas', 'Week 8 Thursday: full swarm end-to-end test — all 6 verticals → aggregator → pipeline → READY_TO_BUILD', 'mid');
