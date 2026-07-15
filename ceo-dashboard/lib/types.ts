export type Role = "admin" | "marketing" | "rnd";

export type Verdict = "pass" | "flagged" | "pending";
export type BlastRadius = "low" | "medium" | "high";
export type HitlStatus = "pending" | "approved" | "rejected";
export type StackStatus = "active" | "paused";
export type BuildPriority = "P1" | "P2" | "P3";
export type GapStatus = "open" | "closed";
export type BadgeStatus =
  | "active" | "building" | "planning" | "paused" | "backlog"
  | "pass" | "flagged" | "pending" | "rejected"
  | "healthy" | "degraded" | "error"
  | "approved" | "draft" | "published" | "rendering" | "complete" | "failed"
  | "READY_TO_BUILD" | "validated" | "watch"
  | "open" | "closed" | "P1" | "P2" | "P3"
  | "queued" | "in_progress" | "done"
  | "read" | "write" | "admin"
  // internal_agent_runs' real status vocab (core/hitl.py's execution_status
  // subset actually used by this table) - "executing"/"executed", not
  // "in_progress"/"complete"/"done".
  | "executing" | "executed" | "budget_exceeded";

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
  department_access: string[];
  permission_level: Role;
  last_active_at: string | null;
  created_at: string;
}

export interface AgentEvent {
  id: string;
  agent_name: string;
  department: string;
  action: string;
  verdict: Verdict;
  metadata: Record<string, unknown>;
  product: string | null;
  created_at: string;
}

export interface HitlItem {
  id: string;
  agent_name: string;
  proposed_action: string;
  blast_radius: BlastRadius;
  confidence_pct: number;
  status: HitlStatus;
  routed_to: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface StackItem {
  id: string;
  service_name: string;
  category: string;
  monthly_cost_usd: number;
  status: StackStatus;
  notes: string | null;
  updated_at: string;
}

export interface AgentRunRow {
  id: string;
  agent_name: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
}

// agents/internal/* runs (api/routes/internal_agents.py's internal_agent_runs
// table) - separate from AgentRunRow above, which is the commercial
// agent_01-10 system's agent_runs table. Different auth path, different
// status vocab, different data source - do not merge these two shapes.
export interface InternalAgentRun {
  run_id: string;
  agent_id: string;
  status: "executing" | "executed" | "failed";
  error: string | null;
  requested_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface BuildQueueItem {
  id: string;
  priority: BuildPriority;
  item: string;
  repo: string | null;
  owner: string | null;
  status: string;
  created_at: string;
}

export interface SessionLogEntry {
  id: string;
  session_date: string;
  product: string | null;
  summary: string;
  operator_id: string | null;
  created_at: string;
}

export interface GapItem {
  id: string;
  gap_name: string;
  product: string | null;
  status: GapStatus;
  notes: string | null;
  closed_at: string | null;
  created_at: string;
}

export interface LegalDocument {
  id: string;
  doc_name: string;
  product: string | null;
  version: string;
  storage_path: string | null;
  last_updated_at: string;
  created_at: string;
}

export interface AdvisoryThread {
  id: string;
  advisor_role: string;
  advisor_name: string;
  message: string;
  role: "user" | "advisor";
  memory_summary: string | null;
  created_at: string;
}

export interface OpportunityPipelineItem {
  id: string;
  vertical: string;
  pain_point: string;
  solution_concept: string;
  conservative_mrr_potential: number;
  build_confidence_score: number | null;
  status: string;
  competition_density: string | null;
  created_at: string;
}

export const DEPT_ROUTES = [
  { id: "overview",  label: "Overview",        path: "/dashboard/overview",   roles: ["admin", "marketing", "rnd"] },
  { id: "finance",   label: "Finance",          path: "/dashboard/finance",    roles: ["admin"] },
  { id: "marketing", label: "Marketing & Sales",path: "/dashboard/marketing",  roles: ["admin", "marketing"] },
  { id: "rnd",       label: "R&D",              path: "/dashboard/rnd",        roles: ["admin", "rnd"] },
  { id: "hr",        label: "HR",               path: "/dashboard/hr",         roles: ["admin", "marketing"] },
  { id: "tech",      label: "Technology",       path: "/dashboard/tech",       roles: ["admin", "rnd"] },
  { id: "legal",     label: "Legal",            path: "/dashboard/legal",      roles: ["admin"] },
  { id: "ops",       label: "Operations",       path: "/dashboard/ops",        roles: ["admin", "marketing"] },
  { id: "advisory",  label: "Advisory",         path: "/dashboard/advisory",   roles: ["admin"] },
  { id: "video",     label: "Video / Creative", path: "/dashboard/video",      roles: ["admin", "marketing"] },
] as const;

export type DeptId = typeof DEPT_ROUTES[number]["id"];
