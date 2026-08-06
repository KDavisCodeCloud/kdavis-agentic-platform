export type TaskStatus =
  | "assigned"
  | "in_progress"
  | "submitted"
  | "approved"
  | "revision_needed"
  | "completed";

export type Priority = "high" | "normal" | "low";

export type Task = {
  id: string;
  product_id: string;
  product_name: string;
  task_type: string;
  status: TaskStatus;
  priority: Priority;
  due_date: string;
  title: string;
  description: string | null;
  current_step: number | null;
  total_steps: number | null;
  submitted_at: string | null;
  submission_notes: string | null;
};

export type TaskStep = {
  step_number: number;
  title: string;
  description: string;
  status: "completed" | "current" | "upcoming";
};

export type FileRequirement = {
  filename: string;
  path: string;
  checked: boolean;
};

export const MOCK_MEMBER = {
  name: "Builder",
  initials: "B",
  role: "CLAUDE CODE",
};

export const MOCK_TASKS: Task[] = [
  {
    id: "task-001",
    product_id: "freight-audit",
    product_name: "FreightAudit",
    task_type: "CLAUDE CODE",
    status: "in_progress",
    priority: "high",
    due_date: "3 days",
    title: "Build agent pipeline + signup flow",
    description: "Wire agent.py to config.yaml, implement FastAPI routes, build Next.js signup page.",
    current_step: 3,
    total_steps: 6,
    submitted_at: null,
    submission_notes: null,
  },
  {
    id: "task-002",
    product_id: "lead-sequencer",
    product_name: "LeadSequencer",
    task_type: "CLAUDE CODE",
    status: "assigned",
    priority: "normal",
    due_date: "7 days",
    title: "Scaffold product from template",
    description: "Clone agents/products/_template, configure product in products.yaml and Stripe.",
    current_step: null,
    total_steps: null,
    submitted_at: null,
    submission_notes: null,
  },
];

export const MOCK_STEPS: TaskStep[] = [
  { step_number: 1, title: "Clone product template",     description: "agents/products/_template/ → agents/products/freight-audit/", status: "completed" },
  { step_number: 2, title: "Configure config.yaml",      description: "Set product_id, pricing_tier, token_cap, mcp_required fields", status: "completed" },
  { step_number: 3, title: "Wire agent.py",              description: "Implement execute() method, connect to shared LLM router", status: "current" },
  { step_number: 4, title: "FastAPI routes",             description: "POST /freight/analyze, GET /freight/health, wire to agent", status: "upcoming" },
  { step_number: 5, title: "Next.js signup page",        description: "app/signup/freight-audit/page.tsx, Supabase auth, Stripe checkout", status: "upcoming" },
  { step_number: 6, title: "End-to-end test",            description: "Trial signup → agent run → HITL queue → dashboard event", status: "upcoming" },
];

export const MOCK_FILES: FileRequirement[] = [
  { filename: "agent.py",         path: "agents/products/freight-audit/agent.py",      checked: false },
  { filename: "config.yaml",      path: "agents/products/freight-audit/config.yaml",   checked: false },
  { filename: "signup/page.tsx",  path: "app/signup/freight-audit/page.tsx",           checked: false },
];

export const NAV_ITEMS = [
  { label: "My Tasks",      href: "/tasks" },
  { label: "Current Task",  href: "/current-task" },
  { label: "Build Queue",   href: "/build-queue" },
  { label: "Resources",     href: "/resources" },
];

// Deliberately curated for the team view — CLAUDE.md's Team Management
// System keeps finance/revenue/agent-internals off team members' screens.
// No MRR, no verdict confidence score, no human_review_comment (can
// contain internal reasoning) — just enough to answer "what's queued,
// what's shipped." Built server-side in app/build-queue/page.tsx from the
// real opportunity_pipeline/mse_build_briefs tables via the service-role
// client (team members' own session can't read those tables — RLS is
// admin-only — so this curation happens before any data reaches the
// client, not as a client-side filter).
export type BuildQueueItem = {
  id: string;
  product_name: string;
  vertical: string;
  has_brief: boolean;
  status: "queued" | "launched";
};

// Mirrors kdavis-microsaas-engine's build_tasks table (migration
// 20260806000019). Read via the admin client server-side (same reasoning
// as BuildQueueItem — RLS on the joined opportunity data is admin-only),
// but build_tasks itself has an "authenticated" RLS policy, so the actual
// mark-complete/notes writes happen client-side with the team member's own
// session, not through a server route.
export type BuildTask = {
  id: string;
  opportunity_id: string;
  task_type: "standard" | "custom";
  title: string;
  description: string | null;
  sort_order: number;
  status: "pending" | "in_progress" | "completed";
  notes: string | null;
  completed_by: string | null;
  completed_at: string | null;
};
