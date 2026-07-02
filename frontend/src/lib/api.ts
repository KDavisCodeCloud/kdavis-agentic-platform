// Cloud Decoded — typed API client

import type { Incident, ApprovalRequest, ApprovalResponse, AgentsResponse } from './types'
import { getMockIncidents, mockApprove } from './mock-data'

const API_URL  = process.env.NEXT_PUBLIC_API_URL  || 'http://localhost:8000'
const MOCK_MODE = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  token: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_URL}/api/v1${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Workspace-Token': token,
      ...options.headers,
    },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? `HTTP ${res.status}`)
  }

  return res.json() as Promise<T>
}

// ── Incidents ──────────────────────────────────────────────────────────

export async function listIncidents(
  token: string,
  statusFilter?: string,
): Promise<Incident[]> {
  if (MOCK_MODE) return getMockIncidents(statusFilter)
  const qs = statusFilter ? `?status_filter=${statusFilter}` : ''
  return request<Incident[]>(`/incidents${qs}`, token)
}

export async function getIncident(token: string, incidentId: string): Promise<Incident> {
  if (MOCK_MODE) {
    const inc = getMockIncidents().find(i => i.incident_id === incidentId)
    if (!inc) throw new ApiError(404, 'Incident not found')
    return inc
  }
  return request<Incident>(`/incidents/${incidentId}`, token)
}

export async function approveIncident(
  token: string,
  incidentId: string,
  body: ApprovalRequest,
): Promise<ApprovalResponse> {
  if (MOCK_MODE) {
    mockApprove(incidentId, body.selected_option_id)
    return {
      incident_id: incidentId,
      status: 'accepted',
      selected_option_id: body.selected_option_id,
      message: 'Demo mode: approval recorded. Refresh page to reset.',
    }
  }
  return request<ApprovalResponse>(`/incidents/${incidentId}/approve`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ── Agents ─────────────────────────────────────────────────────────────

export async function listAgents(token: string): Promise<AgentsResponse> {
  return request<AgentsResponse>('/agents', token)
}

// ── Billing ────────────────────────────────────────────────────────────

export interface BillingStatus {
  tier: string
  subscription_status: string
  has_billing_account: boolean
}

export async function getBillingStatus(token: string): Promise<BillingStatus> {
  if (MOCK_MODE) {
    return { tier: 'growth', subscription_status: 'active', has_billing_account: false }
  }
  return request<BillingStatus>('/billing/status', token)
}

export async function createCheckoutSession(token: string, tier: string): Promise<string> {
  const res = await request<{ checkout_url: string; tier: string }>(
    '/billing/checkout',
    token,
    { method: 'POST', body: JSON.stringify({ tier }) },
  )
  return res.checkout_url
}

export async function getBillingPortalUrl(token: string): Promise<string> {
  const res = await request<{ portal_url: string }>('/billing/portal', token, { method: 'POST' })
  return res.portal_url
}

// ── Outreach ───────────────────────────────────────────────────────────

export interface OutreachLeadCreate {
  lead_name: string
  company: string
  role: string
  team_size: string
  cloud_provider: string
  pain_points: string
  how_they_found_us: string
  linkedin_url?: string
  additional_context?: string
}

export interface OutreachLeadSummary {
  id: string
  lead_name: string
  company: string
  role: string
  status: string
  fit_score: number | null
  recommended_action: string | null
  tier_recommendation: string | null
  connection_note: string | null
  linkedin_url: string
  sent_at: string | null
  created_at: string
  updated_at: string
}

export interface OutreachLeadDetail extends OutreachLeadSummary {
  team_size: string
  cloud_provider: string
  pain_points: string
  how_they_found_us: string
  additional_context: string
  talk_track: string | null
  icp_matches: string[]
  disqualifiers: string[]
  risk_areas: string[]
  recommended_agents: string[]
  estimated_monthly_hours_saved: number | null
  estimated_monthly_value_usd: number | null
  qualify_output: Record<string, unknown> | null
  assessment_output: Record<string, unknown> | null
  proposal_output: Record<string, unknown> | null
  status_updated_at: string | null
  linkedin_search_url: string
}

export interface PacingStatus {
  daily_sent: number
  daily_warn: number
  daily_limit: number
  daily_pct: number
  daily_warning: boolean
  daily_at_limit: boolean
  weekly_sent: number
  weekly_warn: number
  weekly_limit: number
  weekly_pct: number
  weekly_warning: boolean
  weekly_at_limit: boolean
  total_sent: number
  total_accepted: number
  total_declined: number
  total_no_response: number
  acceptance_rate: number | null
  acceptance_rate_warning: boolean
  message: string
}

const MOCK_LEADS: OutreachLeadSummary[] = [
  {
    id: 'lead-001',
    lead_name: 'Marcus Chen',
    company: 'Meridian Health Systems',
    role: 'VP of Engineering',
    status: 'qualified',
    fit_score: 8,
    recommended_action: 'proceed',
    tier_recommendation: 'growth',
    connection_note: "Marcus, saw your team is running multi-cloud for compliance — we built autonomous agents specifically for that overhead. Thought it made sense to connect.",
    linkedin_url: 'https://linkedin.com/in/marcuschen',
    sent_at: null,
    created_at: new Date(Date.now() - 3600000).toISOString(),
    updated_at: new Date(Date.now() - 1800000).toISOString(),
  },
  {
    id: 'lead-002',
    lead_name: 'Priya Nair',
    company: 'Apex Logistics Group',
    role: 'CTO',
    status: 'qualifying',
    fit_score: null,
    recommended_action: null,
    tier_recommendation: null,
    connection_note: null,
    linkedin_url: '',
    sent_at: null,
    created_at: new Date(Date.now() - 900000).toISOString(),
    updated_at: new Date(Date.now() - 900000).toISOString(),
  },
  {
    id: 'lead-003',
    lead_name: 'Derek Walsh',
    company: 'NovaBuild Technologies',
    role: 'Head of Platform Engineering',
    status: 'sent',
    fit_score: 7,
    recommended_action: 'proceed',
    tier_recommendation: 'starter',
    connection_note: "Derek, noticed NovaBuild is scaling platform infra for multiple product teams — this is exactly where autonomous DevOps agents cut the most overhead.",
    linkedin_url: 'https://linkedin.com/in/derekwalsh',
    sent_at: new Date(Date.now() - 86400000).toISOString(),
    created_at: new Date(Date.now() - 172800000).toISOString(),
    updated_at: new Date(Date.now() - 86400000).toISOString(),
  },
]

const MOCK_PACING: PacingStatus = {
  daily_sent: 3, daily_warn: 20, daily_limit: 30, daily_pct: 0.1,
  daily_warning: false, daily_at_limit: false,
  weekly_sent: 11, weekly_warn: 100, weekly_limit: 200, weekly_pct: 0.055,
  weekly_warning: false, weekly_at_limit: false,
  total_sent: 47, total_accepted: 19, total_declined: 8, total_no_response: 9,
  acceptance_rate: 0.402, acceptance_rate_warning: false,
  message: 'Pacing is healthy. 3 sent today, 11 this week.',
}

export async function listLeads(token: string, statusFilter?: string): Promise<OutreachLeadSummary[]> {
  if (MOCK_MODE) return MOCK_LEADS
  const qs = statusFilter ? `?status_filter=${statusFilter}` : ''
  return request<OutreachLeadSummary[]>(`/outreach/leads${qs}`, token)
}

export async function getLead(token: string, leadId: string): Promise<OutreachLeadDetail> {
  if (MOCK_MODE) {
    const lead = MOCK_LEADS.find(l => l.id === leadId)
    if (!lead) throw new ApiError(404, 'Lead not found')
    return {
      ...lead,
      team_size: '50-200',
      cloud_provider: 'AWS + Azure',
      pain_points: 'Manual deployment pipelines consuming 20+ hours/week',
      how_they_found_us: 'LinkedIn post on DevOps automation',
      additional_context: 'Compliance-heavy environment, SOC2 in progress',
      talk_track: 'Frame around compliance overhead reduction — their team is burning cycles on manual audit trails',
      icp_matches: ['50-500 employee range', 'Multi-cloud complexity', 'Active scaling phase'],
      disqualifiers: [],
      risk_areas: ['Budget cycle ends Q3', 'May prefer open-source tooling'],
      recommended_agents: ['incident-response', 'deployment-guard', 'cost-sentinel'],
      estimated_monthly_hours_saved: 80,
      estimated_monthly_value_usd: 12000,
      qualify_output: { fit_score: 8, recommended_action: 'proceed', tier_recommendation: 'growth' },
      assessment_output: null,
      proposal_output: null,
      status_updated_at: null,
      linkedin_search_url: lead.linkedin_url || 'https://www.linkedin.com/search/results/people/?keywords=Marcus+Chen+Meridian',
    }
  }
  return request<OutreachLeadDetail>(`/outreach/leads/${leadId}`, token)
}

export async function createLead(token: string, body: OutreachLeadCreate): Promise<{ lead_id: string; status: string }> {
  if (MOCK_MODE) return { lead_id: `lead-${Date.now()}`, status: 'qualifying' }
  return request<{ lead_id: string; status: string }>('/outreach/leads', token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function markLeadSent(token: string, leadId: string): Promise<{ lead_id: string; status: string; pacing: PacingStatus }> {
  if (MOCK_MODE) return { lead_id: leadId, status: 'sent', pacing: MOCK_PACING }
  return request(`/outreach/leads/${leadId}/mark-sent`, token, { method: 'POST' })
}

export async function updateLeadStatus(token: string, leadId: string, status: string): Promise<{ lead_id: string; status: string }> {
  if (MOCK_MODE) return { lead_id: leadId, status }
  return request(`/outreach/leads/${leadId}/status`, token, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
}

export async function getOutreachPacing(token: string): Promise<PacingStatus> {
  if (MOCK_MODE) return MOCK_PACING
  return request<PacingStatus>('/outreach/pacing', token)
}

// ── MCP Key Management ─────────────────────────────────────────────────

export interface MCPApiKey {
  id: string
  name: string
  key_prefix: string
  scopes: string[]
  expires_at: string
  last_used_at: string | null
  created_at: string
  is_expired: boolean
}

export interface MCPConnectionStatus {
  last_seen_at: string | null
  last_tool: string | null
  active_connections: number
  tool_call_counts: Record<string, number>
  total_calls: number
}

const MOCK_MCP_KEYS: MCPApiKey[] = [
  {
    id: 'key-001',
    name: 'Claude Code — dev',
    key_prefix: 'cd_mcp_X7gK',
    scopes: ['mcp:read'],
    expires_at: new Date(Date.now() + 60 * 24 * 3600 * 1000).toISOString(),
    last_used_at: new Date(Date.now() - 120000).toISOString(),
    created_at: new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString(),
    is_expired: false,
  },
]

const MOCK_MCP_STATUS: MCPConnectionStatus = {
  last_seen_at: new Date(Date.now() - 120000).toISOString(),
  last_tool: 'list_incidents',
  active_connections: 2,
  tool_call_counts: { list_incidents: 32, get_incident: 15, approve_incident: 3 },
  total_calls: 50,
}

let _mockKeys = [...MOCK_MCP_KEYS]

export async function listMCPKeys(token: string): Promise<MCPApiKey[]> {
  if (MOCK_MODE) return [..._mockKeys]
  return request<MCPApiKey[]>('/mcp/keys', token)
}

export async function generateMCPKey(
  token: string,
  name: string,
  scopes: string[],
  expiry_days: number,
): Promise<{ raw_key: string; key: MCPApiKey; warning: string }> {
  if (MOCK_MODE) {
    const rand = Math.random().toString(36).slice(2, 14)
    const raw = `cd_mcp_${rand}`
    const newKey: MCPApiKey = {
      id: `key-${Date.now()}`,
      name,
      key_prefix: raw.slice(0, 12),
      scopes,
      expires_at: new Date(Date.now() + expiry_days * 24 * 3600 * 1000).toISOString(),
      last_used_at: null,
      created_at: new Date().toISOString(),
      is_expired: false,
    }
    _mockKeys = [newKey, ..._mockKeys]
    return { raw_key: raw, key: newKey, warning: 'Save this key now — it will not be shown again.' }
  }
  return request('/mcp/keys', token, {
    method: 'POST',
    body: JSON.stringify({ name, scopes, expiry_days }),
  })
}

export async function revokeMCPKey(token: string, keyId: string): Promise<{ key_id: string; status: string }> {
  if (MOCK_MODE) {
    _mockKeys = _mockKeys.filter(k => k.id !== keyId)
    return { key_id: keyId, status: 'revoked' }
  }
  return request(`/mcp/keys/${keyId}`, token, { method: 'DELETE' })
}

export async function revokeAllMCPKeys(token: string): Promise<{ status: string; count: number }> {
  if (MOCK_MODE) {
    const count = _mockKeys.length
    _mockKeys = []
    return { status: 'all_revoked', count }
  }
  return request('/mcp/keys', token, { method: 'DELETE' })
}

export async function getMCPStatus(token: string): Promise<MCPConnectionStatus> {
  if (MOCK_MODE) return MOCK_MCP_STATUS
  return request<MCPConnectionStatus>('/mcp/status', token)
}

export async function testMCPConnection(
  token: string,
): Promise<{ ok: boolean; incident_count: number; message: string }> {
  if (MOCK_MODE) return { ok: true, incident_count: 3, message: '3 incidents found in queue.' }
  try {
    const incidents = await request<unknown[]>('/incidents', token)
    const n = incidents.length
    return { ok: true, incident_count: n, message: `${n} incident${n !== 1 ? 's' : ''} in queue.` }
  } catch (err) {
    const msg = err instanceof ApiError ? err.message : 'Connection failed'
    return { ok: false, incident_count: 0, message: msg }
  }
}

// ── Health ─────────────────────────────────────────────────────────────

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`)
    return res.ok
  } catch {
    return false
  }
}
