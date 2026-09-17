import type { LinkedInQueuePost, MSEContentPost } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Agents that live in agents/internal/* and require the separate owner/team
// auth path (Supabase session JWT + admin role, api/routes/internal_agents.py)
// instead of the commercial X-Workspace-Token model in api/routes/agents.py.
// Keep in sync with that file's _KNOWN_INTERNAL_AGENTS.
const INTERNAL_AGENT_IDS = new Set([
  "accounting_agent", "chat_router_agent", "code_quality_agent",
  "content_agent", "email_sequence_agent", "finance_assistant_agent",
  "gap_detector_agent", "onboarding_agent", "platform_health_check",
  "portfolio_monitor", "release_notes_agent", "research_agent",
  "revenue_intelligence_agent", "sop_agent", "tax_agent",
  "visitor_capture_agent", "wealth_agent",
]);

function isInternalAgent(agentId: string): boolean {
  return INTERNAL_AGENT_IDS.has(agentId);
}

export interface TriggerResult {
  runId: string;
  status: string;
  message: string;
}

export async function triggerAgent(
  agentId: string,
  payload: Record<string, unknown>,
  authToken: string,
): Promise<TriggerResult> {
  const internal = isInternalAgent(agentId);
  // NOTE: both routers are mounted under /api/v1 in api/main.py — a prior
  // version of this file called `${API_BASE}/agents/...` with no /api/v1,
  // which 404'd before auth was ever checked. Both branches below include it.
  const url = internal
    ? `${API_BASE}/api/v1/internal/agents/${agentId}/run`
    : `${API_BASE}/api/v1/agents/${agentId}/run`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({ payload }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Agent trigger failed: ${res.status}`);
  }
  const data = await res.json();
  return {
    runId: internal ? data.run_id : data.incident_id,
    status: data.status,
    message: data.message,
  };
}

export interface PollResult {
  status: string;
  result?: unknown;
  error?: string;
}

export async function pollIncident(
  agentId: string,
  runId: string,
  authToken: string,
): Promise<PollResult> {
  const internal = isInternalAgent(agentId);
  const url = internal
    ? `${API_BASE}/api/v1/internal/agents/runs/${runId}`
    : `${API_BASE}/api/v1/incidents/${runId}`;

  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`Poll failed: ${res.status}`);
  const data = await res.json();

  // Commercial /incidents/{id} returns { status: <execution_status> } —
  // same terminal-state vocabulary (executed/failed/budget_exceeded) as the
  // internal path's { status, result, error }, so both shapes normalize to
  // the same PollResult without translation.
  return { status: data.status, result: data.result, error: data.error };
}

export interface InternalAgentRunSummary {
  run_id: string;
  agent_id: string;
  status: string;
  error: string | null;
  requested_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export async function fetchInternalAgentRuns(
  authToken: string,
  limit = 20,
): Promise<InternalAgentRunSummary[]> {
  const res = await fetch(`${API_BASE}/api/v1/internal/agents/runs?limit=${limit}`, {
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok) throw new Error(`Fetching recent runs failed: ${res.status}`);
  const data = await res.json();
  return data.runs;
}

// ── LinkedIn monthly batch (app/api/linkedin-queue/*) ───────────────────────
// Runs as Next.js route handlers directly in this app (service-role
// Supabase client server-side) — NOT the FastAPI backend in
// api/routes/internal_marketing.py, which has never been deployed
// anywhere publicly reachable (found 2026-07-24: this is why the batch
// panel showed "Failed to fetch" — NEXT_PUBLIC_API_URL wasn't set in
// Vercel production, so it fell back to http://localhost:8000, which
// obviously isn't reachable from a real visitor's browser). Cookie-based
// session auth is automatic for same-origin fetches, so no Bearer token
// needed here — see lib/api-auth.ts for the server-side role check.
// Image thumbnails (fetchAssetBlobUrl below) are unaffected by this
// change and still point at the FastAPI backend, since the actual image
// bytes live on that repo's filesystem, not reachable from this app.

export async function fetchLinkedInQueue(
  filters: { batchMonth?: string; status?: string } = {},
): Promise<LinkedInQueuePost[]> {
  const params = new URLSearchParams();
  if (filters.batchMonth) params.set("batch_month", filters.batchMonth);
  if (filters.status) params.set("status", filters.status);
  const qs = params.toString();

  const res = await fetch(`/api/linkedin-queue${qs ? `?${qs}` : ""}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Fetching LinkedIn queue failed: ${res.status}`);
  }
  const data = await res.json();
  return data.posts;
}

export async function updateLinkedInQueueRow(
  queueId: string,
  update: { status?: string; hitl_notes?: string; scheduled_for?: string },
): Promise<void> {
  const res = await fetch(`/api/linkedin-queue/${queueId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Updating queue row failed: ${res.status}`);
  }
}

export async function fetchMSEContentQueue(
  filters: { productId?: string; status?: string; platform?: string } = {},
): Promise<MSEContentPost[]> {
  const params = new URLSearchParams();
  if (filters.productId) params.set("product_id", filters.productId);
  if (filters.status) params.set("status", filters.status);
  if (filters.platform) params.set("platform", filters.platform);
  const qs = params.toString();

  const res = await fetch(`/api/mse-content-queue${qs ? `?${qs}` : ""}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Fetching MSE content queue failed: ${res.status}`);
  }
  const data = await res.json();
  return data.posts;
}

export async function updateMSEContentRow(
  contentId: string,
  update: { status?: string; hitl_notes?: string },
): Promise<void> {
  const res = await fetch(`/api/mse-content-queue/${contentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Updating MSE content row failed: ${res.status}`);
  }
}

// Fetches one assets_library/my_originals/ file and returns an object URL
// for use as an <img src>. Caller owns the returned URL and must revoke
// it (URL.revokeObjectURL) when done — see AssetThumbnail.tsx. assetPath
// is image_brief.image_path with the "assets_library/" prefix already
// stripped (e.g. "my_originals/foo.png"). Served by app/api/asset/[...path]/
// route.ts directly in this app (see next.config.ts's outputFileTracingIncludes)
// — not the FastAPI backend, which has never been deployed anywhere
// publicly reachable.
export async function fetchAssetBlobUrl(assetPath: string): Promise<string> {
  const res = await fetch(`/api/asset/${assetPath}`);
  if (!res.ok) throw new Error(`Fetching asset failed: ${res.status}`);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export interface GeneratedLinkedInPost {
  id: string;
  pillar_name: string;
  topic: string;
  scheduled_for: string;
}

// "Fire posts now" — hits app/api/linkedin-queue/generate/route.ts, which
// proxies server-side to the Cloud Decoded FastAPI backend (real MKT-LI1
// drafting, not a Supabase-only write like the rest of this file).
// pillarFocus: null/"balanced" apportions across the 40/30/20/10 mix, or a
// single "pillar_1".."pillar_4" to force every post into one pillar.
export async function generateLinkedInPosts(
  count: number,
  pillarFocus: string | null,
): Promise<{ post_count: number; posts: GeneratedLinkedInPost[] }> {
  const res = await fetch(`/api/linkedin-queue/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count, pillar_focus: pillarFocus }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Generating posts failed: ${res.status}`);
  }
  return res.json();
}

export async function batchApproveLinkedInQueue(
  batchMonth: string,
): Promise<{ approved_count: number }> {
  const res = await fetch(`/api/linkedin-queue/batch-approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_month: batchMonth }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Batch approve failed: ${res.status}`);
  }
  return res.json();
}

// --- Lead pipeline manual controls (n8n-outage fallback) ---
// Each hits an app/api/marketing-leads/*/route.ts, which proxies
// server-side to the microsaas-engine backend's own /marketing/leads/*
// routes -- the same endpoints n8n/lead_finder_workflow.json and
// n8n/outreach-sender-workflow.json call on a schedule. A human clicking
// these buttons gets identical behavior to those crons, for when n8n
// itself is down.

export interface IcpProduct {
  product_id: string;
  name: string;
  slug: string | null;
  vertical: string | null;
  target_count: number | null;
}

// middleware.ts gates every path under this app, /api/* included, on a
// live Supabase session check -- if that session lapsed between page load
// and this client-side fetch firing (or the auth check itself hiccups),
// the browser's fetch() follows the resulting redirect to /login and gets
// back a 200 HTML page, not JSON. res.ok is true in that case, so the
// normal !res.ok branch below never fires -- res.json() would otherwise
// throw a cryptic "Unexpected token '<'" (or worse, silently coerce to {}
// via a .catch and look like an empty/"Not Found" result). res.redirected
// catches this before either happens, with a message that actually tells
// the user what to do.
function assertNotRedirectedToLogin(res: Response): void {
  if (res.redirected && new URL(res.url).pathname.startsWith("/login")) {
    throw new Error("Your session needs a refresh -- reload the page and sign in again.");
  }
}

export async function listIcpProducts(): Promise<IcpProduct[]> {
  const res = await fetch(`/api/marketing-leads/products`, { cache: "no-store" });
  assertNotRedirectedToLogin(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Fetching ICP-configured products failed: ${res.status}`);
  }
  const data = await res.json();
  return data.products ?? [];
}

export async function triggerLeadFinder(productId: string): Promise<{ run_id: string; status: string }> {
  const res = await fetch(`/api/marketing-leads/find`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product_id: productId }),
  });
  assertNotRedirectedToLogin(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Triggering lead finder failed: ${res.status}`);
  }
  return res.json();
}

export interface LeadFinderRun {
  id: string;
  product_id: string;
  status: "pending" | "running" | "complete" | "failed";
  started_at: string | null;
  completed_at: string | null;
  leads_found: number;
  leads_verified: number;
  leads_deduplicated: number;
  sources_used: string[];
  error_message: string | null;
  current_step: string | null;
  total_steps: number | null;
  completed_steps: number;
  estimated_seconds_remaining: number | null;
}

export async function fetchLeadFinderRun(runId: string): Promise<LeadFinderRun> {
  const res = await fetch(`/api/marketing-leads/runs/${encodeURIComponent(runId)}`, { cache: "no-store" });
  assertNotRedirectedToLogin(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Fetching lead finder run status failed: ${res.status}`);
  }
  return res.json();
}

export async function triggerSendSequences(): Promise<{ status: string }> {
  const res = await fetch(`/api/marketing-leads/send-sequences`, { method: "POST" });
  assertNotRedirectedToLogin(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Triggering sequence send failed: ${res.status}`);
  }
  return res.json();
}

export interface PipelineSummary {
  product_id: string | null;
  total: number;
  stages: Record<string, number>;
}

export async function fetchPipelineSummary(productId?: string): Promise<PipelineSummary> {
  const qs = productId ? `?product_id=${encodeURIComponent(productId)}` : "";
  const res = await fetch(`/api/marketing-leads/pipeline-summary${qs}`, { cache: "no-store" });
  assertNotRedirectedToLogin(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Fetching pipeline summary failed: ${res.status}`);
  }
  return res.json();
}

export interface OutreachSummaryRow {
  product_id: string;
  name: string;
  sent: number;
  meetings: number;
}

export async function fetchOutreachSummary(): Promise<OutreachSummaryRow[]> {
  const res = await fetch(`/api/marketing-leads/outreach-summary`, { cache: "no-store" });
  assertNotRedirectedToLogin(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Fetching outreach summary failed: ${res.status}`);
  }
  const data = await res.json();
  return data.products ?? [];
}

// --- Cloud Decoded workspace admin (api/routes/internal_workspaces.py) -----
// Same Bearer-session-token path as the INTERNAL_AGENT_IDS branch of
// triggerAgent above (get_internal_user, not the customer X-Workspace-Token
// model) -- these are the actual suspend/reactivate/revoke levers for a paid
// Cloud Decoded workspace, previously only reachable by calling the API by
// hand.

export interface WorkspaceSummary {
  id: string;
  company_name: string;
  product_tier: string;
  stripe_subscription_status: string;
  created_at: string;
}

async function internalWorkspaceRequest<T>(
  path: string,
  authToken: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}/api/v1/internal/workspaces${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
      ...options.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `Workspace admin request failed: ${res.status}`);
  }
  return res.json();
}

export async function listWorkspaces(authToken: string): Promise<WorkspaceSummary[]> {
  return internalWorkspaceRequest<WorkspaceSummary[]>("", authToken);
}

export async function suspendWorkspace(
  workspaceId: string,
  authToken: string,
): Promise<{ id: string; stripe_subscription_status: string }> {
  return internalWorkspaceRequest(`/${workspaceId}/suspend`, authToken, { method: "POST" });
}

export async function reactivateWorkspace(
  workspaceId: string,
  authToken: string,
): Promise<{ id: string; stripe_subscription_status: string }> {
  return internalWorkspaceRequest(`/${workspaceId}/reactivate`, authToken, { method: "POST" });
}

export async function rotateWorkspaceToken(
  workspaceId: string,
  authToken: string,
): Promise<{ id: string; workspace_token: string; warning: string }> {
  return internalWorkspaceRequest(`/${workspaceId}/rotate-token`, authToken, { method: "POST" });
}
