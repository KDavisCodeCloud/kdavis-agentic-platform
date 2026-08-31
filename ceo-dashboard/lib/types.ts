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
  | "executing" | "executed" | "budget_exceeded"
  // linkedin_content_queue's real status vocab (db/migrations/007).
  | "pending_review";

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

// build_tasks (kdavis-microsaas-engine migration 20260806000019) -- the
// per-product build checklist team.thdstack.com writes to (mark complete
// + notes). Read-only here, same as the MSE dashboard's own reflection --
// the actual doing/checking-off happens on the team dashboard.
export interface BuildTaskItem {
  id: string;
  opportunity_id: string;
  task_type: "standard" | "custom";
  title: string;
  status: "pending" | "in_progress" | "completed";
  completed_by: string | null;
  sort_order: number;
}

export interface ImageBrief {
  image_id: string | null;
  image_path: string | null;
  credit_line: string | null;
  is_original: boolean | null;
  selected_because: string;
  generation_available?: boolean;
}

// linkedin_content_queue rows, as returned by
// GET /internal/marketing/linkedin-queue (api/routes/internal_marketing.py).
export interface LinkedInQueuePost {
  id: string;
  pillar: number | null;
  pillar_name: string | null;
  topic: string | null;
  post_copy: string;
  hook_variants: string[] | null;
  format: "text_post" | "document_carousel";
  image_brief: ImageBrief | null;
  hitl_tier: number | null;
  status: "pending_review" | "approved" | "rejected" | "published";
  hitl_notes: string | null;
  batch_month: string | null;
  scheduled_for: string | null;
  published_at: string | null;
  created_at: string;
}

// MKT-V1's Reddit/Facebook community-post output (mse_social_content,
// kdavis-microsaas-engine). "sent" is a manual confirmation, not an
// automated publish -- no posting client exists for either platform yet.
export interface MSEContentPost {
  id: string;
  product_id: string;
  campaign_build_id: string;
  platform: "reddit" | "facebook";
  title: string | null;
  body: string;
  status: "pending_review" | "approved" | "rejected" | "sent";
  hitl_notes: string | null;
  reviewed_at: string | null;
  sent_at: string | null;
  created_at: string;
}

// mse_monitoring_events (kdavis-microsaas-engine
// supabase/migrations/20260717000011_factory_expansion.sql). NOVA gap-
// closure Phase C1 -- first UI surface for this table anywhere; it's
// populated today by nova/agents/ledger/monitoring_activation.py's
// $4K-MRR/30-day threshold trigger (jarvis-decoded), 'triggered' run_type
// only so far, 'nightly'/'manual' are real values the schema supports but
// nothing writes yet.
export type MonitoringSeverity = "P1" | "P2" | "P3" | "healthy";
export type MonitoringEventStatus = "open" | "acknowledged" | "resolved" | "dismissed";

export interface MonitoringEvent {
  id: string;
  product_slug: string;
  product_name: string;
  run_type: "nightly" | "triggered" | "manual";
  severity: MonitoringSeverity | null;
  triggered_thresholds: Array<{ metric: string; value: number; threshold: number }>;
  recommended_action: string | null;
  requires_human_decision: boolean;
  context: string | null;
  status: MonitoringEventStatus;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_notes: string | null;
  created_at: string;
}

// nova_agent_status (jarvis-decoded supabase/migrations/011_nova_agent_status.sql).
// Remote status/control channel for NOVA's voice agents -- purely
// outbound-Supabase on both sides (dashboard writes `enabled`,
// nova-voice.service polls it + writes last_heartbeat_at), deliberately
// not routed through nova-api.service/the Cloudflare tunnel. `health` is
// computed server-side in app/api/agent-status/route.ts, not stored.
export type VoiceAgentHealth = "healthy" | "unhealthy" | "off";

// current_state (migration 012) is NOVA's own single global voice-loop
// state, not per-agent -- matches the NOVA HUD design prototype's real
// behavior (one `mode` driving one animation system, not five
// independently-animated agents). Only meaningful on the "nova" row.
export type NovaVoiceState = "idle" | "listening" | "thinking" | "talking" | "error";

export interface VoiceAgentStatus {
  agent_slug: "nova" | "apollo" | "ledger" | "counsel" | "board";
  label: string;
  enabled: boolean;
  health: VoiceAgentHealth;
  last_heartbeat_at: string | null;
  status_detail: string | null;
  current_state: NovaVoiceState;
  state_updated_at: string | null;
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
  { id: "empire",    label: "Decoded Empire",   path: "/dashboard/empire",     roles: ["admin"] },
  { id: "agents",    label: "Voice Agents",     path: "/dashboard/agents",    roles: ["admin"] },
] as const;

export type DeptId = typeof DEPT_ROUTES[number]["id"];

// DIST Phase 1 (2026-08-30). mse_funnel_events.step is queried directly
// (not just mse_attribution_summary, which only rolls up signups/paid) so
// the panel can show real per-step drop-off, not just first/last touch.
export const FUNNEL_STEPS = ["signup", "email_verified", "activated", "trial_started", "paid", "churned"] as const;
export type FunnelStep = typeof FUNNEL_STEPS[number];

export interface MseFunnelEvent {
  id: string;
  product_id: string;
  tenant_id: string;
  step: FunnelStep;
  occurred_at: string;
  metadata: Record<string, unknown> | null;
}

export interface MseProduct {
  id: string;
  slug: string;
  name: string;
  status: string;
  activation_definition: string | null;
}

// DIST Phase 5 (2026-08-30) -- mse_content_surfaces (migration 032).
// hitl_tier: 1 auto-publishes on a quality-gate pass (never appears here
// with status='pending_review' for long), 2 is this panel's own scope,
// 3 is owner-only/individual and deliberately excluded from bulk review.
export type ContentArchetype = "vs_competitor" | "alternatives_to" | "jurisdiction" | "jtbd" | "calculator" | "faq_block";
export type SurfaceStatus = "draft" | "pending_review" | "approved" | "published" | "stale" | "archived";

export interface MseContentSurface {
  id: string;
  product_id: string;
  archetype: ContentArchetype;
  slug: string;
  title: string;
  body_mdx: string | null;
  hitl_tier: 1 | 2 | 3;
  status: SurfaceStatus;
  reject_reason: string | null;
  created_at: string;
}
