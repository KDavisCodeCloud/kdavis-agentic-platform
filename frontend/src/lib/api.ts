// Cloud Decoded — typed API client

import type {
  Incident, ApprovalRequest, ApprovalResponse, ManualResolutionRequest, ManualResolutionResponse, AgentsResponse,
  AuditSubmissionSummary, AuditSubmissionDetail,
  AgentConnectionStatus, FinOpsDashboardData, ComplianceScanResult, ComplianceReportData,
  DraftSummary, DraftDetail, AzureServicePrincipalInput, AzureDevOpsInput, K8sClusterInput,
  ConnectionsStatus, AwsRoleSetup, TicketingStatus, JiraConnectInput, LinearConnectInput, GithubIssuesConnectInput,
  ServiceNowConnectInput, WorkspaceTokenStatus, RotateWorkspaceTokenResult,
  IncidentFilters, WorkspaceMembersResponse, IncidentComment, BulkIncidentActionType, BulkIncidentActionResponse,
  ExhaustedRetriesResponse,
} from './types'
import {
  getMockIncidents, mockApprove, mockResolveManually, getMockAuditSubmissions, getMockAuditReport, mockActionAuditItem,
  getMockAgentStatus, mockConnectAgent, mockVerifyAgentRole,
  getMockFinopsDashboard, mockActionFinopsItem, getMockComplianceReport,
  getMockConnectionsStatus, mockSetupAwsRole, mockConnectAwsRole, mockConnectAzure,
  mockConnectAzureDevOps, mockGetGithubAppInstallUrl, mockConnectK8s, mockSaveLlmKey,
  getMockTicketingStatus, mockConnectJira, mockConnectLinear, mockConnectGithubIssues, mockConnectServiceNow,
  getMockWorkspaceTokenStatus, mockRotateWorkspaceToken,
  mockAssignIncident, getMockWorkspaceMembers, getMockIncidentComments, mockCreateIncidentComment,
  mockBulkIncidentAction,
} from './mock-data'

export const API_URL  = process.env.NEXT_PUBLIC_API_URL  || 'http://localhost:8000'
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

export function isPaywallError(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 402
}

// A 402 means get_workspace (api/middleware/auth.py) blocked this workspace
// -- pending_payment, canceled, or suspended. Every dashboard tab reaches
// its data through request(), so handling it here once means no individual
// component needs to know about billing state. /billing itself reads
// status through get_workspace_any_status, which never 402s, so this can't
// loop back on itself.
function redirectToBilling() {
  if (typeof window === 'undefined') return
  if (window.location.pathname === '/billing') return
  window.location.href = '/billing?locked=1'
}

// A raw workspace token always starts with 'cd_ws_' (api/routes/
// workspaces.py's _TOKEN_PREFIX). A Supabase session access token (the
// membership-plan Phase A additive auth path, api/middleware/auth.py's
// get_workspace_member) never does -- so the same `token` value threaded
// through every existing call site can carry either credential, and
// request() picks the right header by shape instead of every caller
// needing to know or care which kind it has. See lib/supabase.ts and
// app/login/page.tsx for where a member session token is produced.
const _WORKSPACE_TOKEN_PREFIX = 'cd_ws_'

export function isMemberSessionToken(token: string): boolean {
  return !!token && !token.startsWith(_WORKSPACE_TOKEN_PREFIX)
}

async function request<T>(
  path: string,
  token: string,
  options: RequestInit = {},
): Promise<T> {
  const authHeader: Record<string, string> = isMemberSessionToken(token)
    ? { Authorization: `Bearer ${token}` }
    : { 'X-Workspace-Token': token }

  const res = await fetch(`${API_URL}/api/v1${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...authHeader,
      ...options.headers,
    },
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    const err = new ApiError(res.status, body.detail ?? `HTTP ${res.status}`)
    if (res.status === 402) redirectToBilling()
    throw err
  }

  return res.json() as Promise<T>
}

// ── Incidents ──────────────────────────────────────────────────────────

// 24-gap-closure Phase 2: statusFilter kept as its own positional param
// for every existing call site (backward compatible); pass a full
// IncidentFilters object as the third argument for the new resource_id/
// resource_name/severity/agent_id/date range/assigned_to filters.
export async function listIncidents(
  token: string,
  statusFilter?: string,
  filters?: Omit<IncidentFilters, 'status_filter'>,
): Promise<Incident[]> {
  if (MOCK_MODE) return getMockIncidents({ status_filter: statusFilter, ...filters })
  const params = new URLSearchParams()
  if (statusFilter) params.set('status_filter', statusFilter)
  if (filters?.severity) params.set('severity', filters.severity)
  if (filters?.agent_id) params.set('agent_id', filters.agent_id)
  if (filters?.resource_id) params.set('resource_id', filters.resource_id)
  if (filters?.resource_name) params.set('resource_name', filters.resource_name)
  if (filters?.date_from) params.set('date_from', filters.date_from)
  if (filters?.date_to) params.set('date_to', filters.date_to)
  if (filters?.assigned_to) params.set('assigned_to', filters.assigned_to)
  const qs = params.toString() ? `?${params.toString()}` : ''
  return request<Incident[]>(`/incidents${qs}`, token)
}

export async function assignIncident(
  token: string,
  incidentId: string,
  memberId: string | null,
): Promise<Incident> {
  if (MOCK_MODE) {
    const inc = mockAssignIncident(incidentId, memberId)
    if (!inc) throw new ApiError(404, 'Incident not found')
    return inc
  }
  return request<Incident>(`/incidents/${incidentId}/assign`, token, {
    method: 'PATCH',
    body: JSON.stringify({ member_id: memberId }),
  })
}

export async function listWorkspaceMembers(token: string): Promise<WorkspaceMembersResponse> {
  if (MOCK_MODE) return getMockWorkspaceMembers()
  return request<WorkspaceMembersResponse>('/workspace-members', token)
}

export async function listIncidentComments(token: string, incidentId: string): Promise<IncidentComment[]> {
  if (MOCK_MODE) return getMockIncidentComments(incidentId)
  return request<IncidentComment[]>(`/incidents/${incidentId}/comments`, token)
}

export async function createIncidentComment(
  token: string,
  incidentId: string,
  body: string,
): Promise<IncidentComment> {
  if (MOCK_MODE) return mockCreateIncidentComment(incidentId, body)
  return request<IncidentComment>(`/incidents/${incidentId}/comments`, token, {
    method: 'POST',
    body: JSON.stringify({ body }),
  })
}

export async function bulkIncidentAction(
  token: string,
  incidentIds: string[],
  action: BulkIncidentActionType,
  extra?: { reason?: string; resolution_note?: string },
): Promise<BulkIncidentActionResponse> {
  if (MOCK_MODE) return mockBulkIncidentAction(incidentIds, action)
  return request<BulkIncidentActionResponse>('/incidents/bulk', token, {
    method: 'POST',
    body: JSON.stringify({ incident_ids: incidentIds, action, ...extra }),
  })
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

// "I'll handle this myself" — not a custom execution path. See
// db/models.py's IncidentResolveManuallyRequest / api/routes/incidents.py's
// resolve_incident_manually for the backend side of this contract.
export async function resolveIncidentManually(
  token: string,
  incidentId: string,
  body: ManualResolutionRequest,
): Promise<ManualResolutionResponse> {
  if (MOCK_MODE) return mockResolveManually(incidentId, body.resolution_note)
  return request<ManualResolutionResponse>(`/incidents/${incidentId}/resolve-manually`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ── Agents ─────────────────────────────────────────────────────────────

export async function listAgents(token: string): Promise<AgentsResponse> {
  return request<AgentsResponse>('/agents', token)
}

// ── Content Pipeline ───────────────────────────────────────────────────
// ContentPipeline.tsx previously made its own raw fetch() calls here instead
// of going through this shared client like every other tab -- moved so it
// picks up the same 402 → /billing redirect handling in request() for free.

export async function listContentDrafts(token: string): Promise<DraftSummary[]> {
  return request<DraftSummary[]>('/content/drafts', token)
}

export async function getContentDraft(token: string, draftId: string): Promise<DraftDetail> {
  return request<DraftDetail>(`/content/drafts/${draftId}`, token)
}

export async function approveContentDraft(
  token: string,
  draftId: string,
  body: { selected_draft: string; operator_edit?: string },
): Promise<DraftDetail> {
  return request<DraftDetail>(`/content/drafts/${draftId}/approve`, token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function rejectContentDraft(
  token: string,
  draftId: string,
  feedback: string,
): Promise<DraftDetail> {
  return request<DraftDetail>(`/content/drafts/${draftId}/reject`, token, {
    method: 'POST',
    body: JSON.stringify({ feedback }),
  })
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

// ── Workspaces ─────────────────────────────────────────────────────────

export async function createWorkspace(companyName: string, contactEmail: string, tosAccepted: boolean): Promise<{
  id: string
  workspace_token: string
  warning: string
}> {
  const res = await fetch(`${API_URL}/api/v1/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ company_name: companyName, contact_email: contactEmail, tos_accepted: tosAccepted }),
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? `HTTP ${res.status}`)
  }

  return res.json()
}

export async function saveLlmKey(
  token: string,
  provider: 'anthropic' | 'openai',
  apiKey: string,
): Promise<{ status: string }> {
  if (MOCK_MODE) return mockSaveLlmKey(provider)
  return request<{ status: string }>('/workspaces/llm-key', token, {
    method: 'POST',
    body: JSON.stringify({ provider, api_key: apiKey }),
  })
}

// ── Cloud Audit Remediation Plan ─────────────────────────────────────────

export async function listAuditSubmissions(token: string): Promise<AuditSubmissionSummary[]> {
  if (MOCK_MODE) return getMockAuditSubmissions()
  return request<AuditSubmissionSummary[]>('/audit', token)
}

export async function getAuditReport(token: string, auditId: string): Promise<AuditSubmissionDetail> {
  if (MOCK_MODE) return getMockAuditReport(auditId)
  return request<AuditSubmissionDetail>(`/audit/${auditId}/report`, token)
}

export async function approveAuditItem(token: string, itemId: string): Promise<{ id: string; status: string }> {
  if (MOCK_MODE) return mockActionAuditItem(itemId, 'approved')
  return request<{ id: string; status: string }>(`/audit/items/${itemId}/approve`, token, { method: 'POST' })
}

export async function dismissAuditItem(token: string, itemId: string): Promise<{ id: string; status: string }> {
  if (MOCK_MODE) return mockActionAuditItem(itemId, 'dismissed')
  return request<{ id: string; status: string }>(`/audit/items/${itemId}/dismiss`, token, { method: 'POST' })
}

// ── FinOps agent ───────────────────────────────────────────────────────
// Proxied through Cloud Decoded's own backend (api/routes/finops_agent.py) --
// this frontend never sees a kdavis-finops-agent tenant token, only its own
// X-Workspace-Token.

export async function getFinopsStatus(token: string): Promise<AgentConnectionStatus> {
  if (MOCK_MODE) return getMockAgentStatus('finops')
  return request<AgentConnectionStatus>('/finops-agent/status', token)
}

export async function connectFinops(token: string): Promise<AgentConnectionStatus> {
  if (MOCK_MODE) return mockConnectAgent('finops')
  return request<AgentConnectionStatus>('/finops-agent/connect', token, { method: 'POST' })
}

export async function verifyFinopsAwsRole(token: string, roleArn: string): Promise<{ status: string }> {
  if (MOCK_MODE) return mockVerifyAgentRole('finops')
  return request<{ status: string }>('/finops-agent/verify-role', token, {
    method: 'POST',
    body: JSON.stringify({ role_arn: roleArn }),
  })
}

export async function verifyFinopsAzureServicePrincipal(
  token: string,
  body: AzureServicePrincipalInput,
): Promise<{ status: string }> {
  if (MOCK_MODE) return mockVerifyAgentRole('finops')
  return request<{ status: string }>('/finops-agent/verify-azure', token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function triggerFinopsScan(token: string): Promise<FinOpsDashboardData> {
  if (MOCK_MODE) return getMockFinopsDashboard()
  return request<FinOpsDashboardData>('/finops-agent/scan', token, { method: 'POST' })
}

export async function getFinopsDashboard(token: string): Promise<FinOpsDashboardData> {
  if (MOCK_MODE) return getMockFinopsDashboard()
  return request<FinOpsDashboardData>('/finops-agent/dashboard', token)
}

export async function approveFinopsItem(token: string, itemId: string): Promise<{ id: string; status: string }> {
  if (MOCK_MODE) return mockActionFinopsItem(itemId, 'approved')
  return request<{ id: string; status: string }>(`/finops-agent/items/${itemId}/approve`, token, { method: 'POST' })
}

export async function dismissFinopsItem(token: string, itemId: string): Promise<{ id: string; status: string }> {
  if (MOCK_MODE) return mockActionFinopsItem(itemId, 'dismissed')
  return request<{ id: string; status: string }>(`/finops-agent/items/${itemId}/dismiss`, token, { method: 'POST' })
}

// ── Compliance agent ───────────────────────────────────────────────────
// Same proxy shape as FinOps (api/routes/compliance_agent.py), minus HITL --
// CIS control pass/fail is deterministic, not something a human approves.

export async function getComplianceStatus(token: string): Promise<AgentConnectionStatus> {
  if (MOCK_MODE) return getMockAgentStatus('compliance')
  return request<AgentConnectionStatus>('/compliance-agent/status', token)
}

export async function connectCompliance(token: string): Promise<AgentConnectionStatus> {
  if (MOCK_MODE) return mockConnectAgent('compliance')
  return request<AgentConnectionStatus>('/compliance-agent/connect', token, { method: 'POST' })
}

export async function verifyComplianceAwsRole(token: string, roleArn: string): Promise<{ status: string }> {
  if (MOCK_MODE) return mockVerifyAgentRole('compliance')
  return request<{ status: string }>('/compliance-agent/verify-role', token, {
    method: 'POST',
    body: JSON.stringify({ role_arn: roleArn }),
  })
}

export async function verifyComplianceAzureServicePrincipal(
  token: string,
  body: AzureServicePrincipalInput,
): Promise<{ status: string }> {
  if (MOCK_MODE) return mockVerifyAgentRole('compliance')
  return request<{ status: string }>('/compliance-agent/verify-azure', token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function triggerComplianceScan(token: string): Promise<ComplianceScanResult> {
  if (MOCK_MODE) {
    return {
      scan_id: 'demo-compliance-scan-1',
      tenant_id: 'demo-compliance-tenant',
      status: 'ready',
      provider: 'aws',
      report: getMockComplianceReport(),
      error_message: null,
      started_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
    }
  }
  return request<ComplianceScanResult>('/compliance-agent/scan', token, { method: 'POST' })
}

export async function getComplianceReport(token: string): Promise<ComplianceReportData> {
  if (MOCK_MODE) return getMockComplianceReport()
  const result = await request<ComplianceScanResult>('/compliance-agent/report', token)
  if (!result.report) throw new ApiError(404, 'No compliance report yet')
  return result.report
}

// -- Workspace connections (core platform's own Agents 01/05/06/08 --
// api/routes/workspace_credentials.py. Distinct from the FinOps/Compliance
// functions above, which proxy to the separately-deployed satellite
// products -- this is the platform's own per-workspace credential store,
// migration 022) --------------------------------------------------------

export async function getConnectionsStatus(token: string): Promise<ConnectionsStatus> {
  if (MOCK_MODE) return getMockConnectionsStatus()
  return request<ConnectionsStatus>('/workspace/credentials/status', token)
}

// Onboarding completeness build, item 4 -- self-serve token view/rotate.
export async function getWorkspaceTokenStatus(token: string): Promise<WorkspaceTokenStatus> {
  if (MOCK_MODE) return getMockWorkspaceTokenStatus()
  return request<WorkspaceTokenStatus>('/workspace/credentials/token', token)
}

export async function rotateWorkspaceToken(token: string): Promise<RotateWorkspaceTokenResult> {
  if (MOCK_MODE) return mockRotateWorkspaceToken()
  return request<RotateWorkspaceTokenResult>('/workspace/credentials/token/rotate', token, { method: 'POST' })
}

// 24-gap-closure Phase 3 -- "flagged in dashboard" for exhausted outbound
// notification/ticketing retries. No mock-data fixture needed: this is a
// flag surface, not a core connection-status feature demoed in sandbox mode.
export async function listExhaustedRetries(token: string): Promise<ExhaustedRetriesResponse> {
  if (MOCK_MODE) return { retries: [] }
  return request<ExhaustedRetriesResponse>('/workspace/notifications/retry-queue/exhausted', token)
}

// Item 4 GitHub App migration -- PATCH /workspace/credentials/github is
// retired (410); connections go through this install-URL redirect instead.
// See api/routes/workspace_credentials.py's get_github_app_install_url +
// github_app_install_callback.
export async function getGithubAppInstallUrl(token: string): Promise<{ install_url: string }> {
  if (MOCK_MODE) return mockGetGithubAppInstallUrl()
  return request<{ install_url: string }>('/workspace/credentials/github-app/install-url', token)
}

export async function setupAwsRole(token: string): Promise<AwsRoleSetup> {
  if (MOCK_MODE) return mockSetupAwsRole()
  return request<AwsRoleSetup>('/workspace/credentials/aws-role/setup', token, { method: 'POST' })
}

export async function connectAwsRole(token: string, roleArn: string): Promise<{ id: string }> {
  if (MOCK_MODE) return mockConnectAwsRole()
  return request<{ id: string }>('/workspace/credentials/aws-role', token, {
    method: 'PATCH',
    body: JSON.stringify({ role_arn: roleArn }),
  })
}

export async function connectAzureServicePrincipal(
  token: string,
  body: AzureServicePrincipalInput,
): Promise<{ id: string }> {
  if (MOCK_MODE) return mockConnectAzure()
  return request<{ id: string }>('/workspace/credentials/azure', token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function connectAzureDevOps(
  token: string,
  body: AzureDevOpsInput,
): Promise<{ status: string; webhook_secret: string | null }> {
  if (MOCK_MODE) return mockConnectAzureDevOps()
  return request<{ status: string; webhook_secret: string | null }>('/workspace/credentials/azure-devops', token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function connectK8sCluster(token: string, body: K8sClusterInput): Promise<{ id: string }> {
  if (MOCK_MODE) return mockConnectK8s()
  return request<{ id: string }>('/workspace/credentials/k8s', token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

// -- Ticketing (Jira/Linear/GitHub Issues/ServiceNow -- fires on incident
// RESOLUTION, not creation) -- api/routes/workspace_ticketing.py. At most
// one channel at a time. ---------------------------------------------------

export async function getTicketingStatus(token: string): Promise<TicketingStatus> {
  if (MOCK_MODE) return getMockTicketingStatus()
  return request<TicketingStatus>('/workspace/ticketing', token)
}

export async function connectJira(
  token: string,
  body: JiraConnectInput,
): Promise<{ channel_type: string; enabled: boolean }> {
  if (MOCK_MODE) return mockConnectJira(body)
  return request<{ channel_type: string; enabled: boolean }>('/workspace/ticketing/jira', token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function connectLinear(
  token: string,
  body: LinearConnectInput,
): Promise<{ channel_type: string; enabled: boolean }> {
  if (MOCK_MODE) return mockConnectLinear(body)
  return request<{ channel_type: string; enabled: boolean }>('/workspace/ticketing/linear', token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function connectGithubIssues(
  token: string,
  body: GithubIssuesConnectInput,
): Promise<{ channel_type: string; enabled: boolean }> {
  if (MOCK_MODE) return mockConnectGithubIssues(body)
  return request<{ channel_type: string; enabled: boolean }>('/workspace/ticketing/github-issues', token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

// Enterprise tier only -- the backend 402s on starter/growth; this call
// site does not pre-check tier client-side beyond hiding the form (see
// ConnectionsPanel.tsx), the server enforcement is what actually matters.
export async function connectServiceNow(
  token: string,
  body: ServiceNowConnectInput,
): Promise<{ channel_type: string; enabled: boolean }> {
  if (MOCK_MODE) return mockConnectServiceNow(body)
  return request<{ channel_type: string; enabled: boolean }>('/workspace/ticketing/servicenow', token, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

// -- Health ---------------------------------------------------------------

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`)
    return res.ok
  } catch {
    return false
  }
}

export interface SystemStatusService {
  status: 'ok' | 'degraded' | 'error'
  detail: string
}

export interface SystemStatus {
  status: 'ok' | 'degraded' | 'error'
  services: {
    backend: SystemStatusService
    database: SystemStatusService
    frontend: SystemStatusService
  }
  timestamp: string
}

// Real status backing /status (Phase 5) -- returns null on any fetch
// failure so the page can render its own "status unavailable" state
// rather than throwing.
export async function getSystemStatus(): Promise<SystemStatus | null> {
  try {
    const res = await fetch(`${API_URL}/api/status`, { cache: 'no-store' })
    if (!res.ok) return null
    return (await res.json()) as SystemStatus
  } catch {
    return null
  }
}
