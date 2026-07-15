const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Agents that live in agents/internal/* and require the separate owner/team
// auth path (Supabase session JWT + admin role, api/routes/internal_agents.py)
// instead of the commercial X-Workspace-Token model in api/routes/agents.py.
// Keep in sync with that file's _KNOWN_INTERNAL_AGENTS.
const INTERNAL_AGENT_IDS = new Set([
  "accounting_agent", "chat_router_agent", "code_quality_agent",
  "content_agent", "email_sequence_agent", "finance_assistant_agent",
  "gap_detector_agent", "onboarding_agent", "portfolio_monitor",
  "release_notes_agent", "research_agent", "revenue_intelligence_agent",
  "sop_agent", "tax_agent", "visitor_capture_agent", "wealth_agent",
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
