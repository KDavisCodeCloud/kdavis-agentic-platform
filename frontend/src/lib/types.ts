// Cloud Decoded — shared TypeScript types (mirrors db/models.py)

export type IncidentStatus =
  | 'pending_approval'
  | 'executing'
  | 'executed'
  | 'held'
  | 'failed'
  | 'budget_exceeded'
  | 'resolved_manually'
  // POST /incidents/{id}/reject has set this since before this session --
  // it had no frontend representation at all until the 24-gap-closure
  // Phase 2 bulk-dismiss build needed to display its own result.
  | 'rejected'

export type ImpactLevel = 'low' | 'medium' | 'high'

export interface RemediationOption {
  id: string
  title: string
  description: string
  impact: ImpactLevel
  docs_url: string
}

export interface Incident {
  incident_id: string
  status: IncidentStatus
  parsed_error: string
  options: RemediationOption[]
  estimated_duration_seconds: number | null
  // 24-gap-closure Phase 1/2: severity/agent_id/resource_id/resource_name/
  // created_at/assigned_to are now genuinely returned by GET /incidents
  // and GET /incidents/{id} -- agent_id/created_at were referenced
  // throughout the frontend (PipelineTracker.tsx, RemediationCard.tsx)
  // long before the real API ever sent them; that was a real, silent gap
  // (always undefined outside MOCK_MODE), not something introduced here.
  severity?: 'critical' | 'high' | 'medium' | 'low'
  agent_id?: string
  resource_id?: string
  resource_name?: string
  cloud_provider?: string
  job_name?: string
  repository?: string
  branch?: string
  created_at?: string
  assigned_to?: string | null
  assigned_to_email?: string | null
  // set locally right after a manual resolution — not returned by
  // GET /incidents or GET /incidents/{id} (same convention as
  // custom_solution_input on the pre-existing custom-fix path)
  resolution_note?: string | null
}

// 24-gap-closure Phase 2 — incident search/filter API. All optional;
// resource_name is a partial match server-side, everything else exact.
// assigned_to accepts a real member id or the literal "me" (resolved
// server-side to the caller's own member session, so the frontend never
// needs to know its own member id).
export interface IncidentFilters {
  status_filter?: IncidentStatus
  severity?: 'critical' | 'high' | 'medium' | 'low'
  agent_id?: string
  resource_id?: string
  resource_name?: string
  date_from?: string
  date_to?: string
  assigned_to?: string
}

export interface WorkspaceMember {
  id: string
  email: string
  role: string
  status: string
  invited_at: string | null
  joined_at: string | null
}

export interface WorkspaceMembersResponse {
  members: WorkspaceMember[]
  seats_used: number
  max_seats: number
}

export interface IncidentComment {
  id: string
  incident_id: string
  member_id: string | null
  member_email: string | null
  body: string
  created_at: string
}

export type BulkIncidentActionType = 'dismiss' | 'resolve_manually'

export interface BulkIncidentActionResult {
  incident_id: string
  outcome: 'applied' | 'not_found' | 'not_pending'
}

export interface BulkIncidentActionResponse {
  action: BulkIncidentActionType
  results: BulkIncidentActionResult[]
}

export interface ApprovalRequest {
  selected_option_id: string
  custom_solution_input?: string
}

export interface ApprovalResponse {
  incident_id: string
  status: string
  selected_option_id: string
  message: string
}

// "I'll handle this myself" — not a custom execution path. The platform
// executes nothing here; resolution_note is a record of what the operator
// already did outside the platform, never an instruction it acts on.
export interface ManualResolutionRequest {
  resolution_note?: string
}

export interface ManualResolutionResponse {
  incident_id: string
  status: string
  resolution_note: string | null
  resolved_at: string
}

export interface AgentInfo {
  id: string
  name: string
  status: 'available' | 'coming_soon'
}

export interface AgentsResponse {
  tier: string
  available_agents: AgentInfo[]
  locked_agents: AgentInfo[]
  upgrade_url: string
}

// Status display metadata
export const STATUS_META: Record<
  IncidentStatus,
  { label: string; color: string; dot: string; bg: string }
> = {
  pending_approval: {
    label: 'Awaiting Approval',
    color: 'text-amber-400',
    dot:   'bg-amber-400',
    bg:    'bg-amber-400/10 border-amber-400/30',
  },
  executing: {
    label: 'Executing',
    color: 'text-blue-400',
    dot:   'bg-blue-400 animate-pulse',
    bg:    'bg-blue-400/10 border-blue-400/30',
  },
  executed: {
    label: 'Resolved',
    color: 'text-emerald-400',
    dot:   'bg-emerald-400',
    bg:    'bg-emerald-400/10 border-emerald-400/30',
  },
  held: {
    label: 'Held',
    color: 'text-zinc-400',
    dot:   'bg-zinc-500',
    bg:    'bg-zinc-800/50 border-zinc-700',
  },
  failed: {
    label: 'Failed',
    color: 'text-red-400',
    dot:   'bg-red-400',
    bg:    'bg-red-400/10 border-red-400/30',
  },
  budget_exceeded: {
    label: 'Budget Exceeded',
    color: 'text-orange-400',
    dot:   'bg-orange-400',
    bg:    'bg-orange-400/10 border-orange-400/30',
  },
  resolved_manually: {
    label: 'Resolved Manually',
    color: 'text-emerald-400',
    dot:   'bg-emerald-400',
    bg:    'bg-emerald-400/10 border-emerald-400/30',
  },
  rejected: {
    label: 'Dismissed',
    color: 'text-zinc-400',
    dot:   'bg-zinc-500',
    bg:    'bg-zinc-800/50 border-zinc-700',
  },
}

export const IMPACT_META: Record<ImpactLevel, { label: string; color: string }> = {
  low:    { label: 'Low Impact',    color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30' },
  medium: { label: 'Med Impact',    color: 'text-amber-400 bg-amber-400/10 border-amber-400/30' },
  high:   { label: 'High Impact',   color: 'text-red-400 bg-red-400/10 border-red-400/30' },
}

// 24-gap-closure Phase 1/2 -- incidents.severity display metadata.
export const SEVERITY_META: Record<'critical' | 'high' | 'medium' | 'low', { label: string; color: string }> = {
  critical: { label: 'Critical', color: 'text-red-400 bg-red-400/10 border-red-400/30' },
  high:     { label: 'High',     color: 'text-orange-400 bg-orange-400/10 border-orange-400/30' },
  medium:   { label: 'Medium',   color: 'text-amber-400 bg-amber-400/10 border-amber-400/30' },
  low:      { label: 'Low',      color: 'text-zinc-400 bg-zinc-800/50 border-zinc-700' },
}

// ── Cloud audit remediation plan (mirrors api/routes/audit.py) ─────────────

export type AuditItemStatus = 'pending_approval' | 'approved' | 'dismissed'
export type AuditSeverity = 'HIGH' | 'MEDIUM' | 'LOW'
export type AuditCategory = 'WASTE' | 'SECURITY' | 'COMPLIANCE'

export interface RemediationItem {
  id: string
  severity: AuditSeverity
  category: AuditCategory
  title: string
  description: string
  remediation: string
  estimated_monthly_waste_usd: number
  priority_rank: number
  status: AuditItemStatus
}

export interface AuditSubmissionSummary {
  audit_id: string
  provider: string
  status: string
  total_findings: number
  total_estimated_monthly_waste_usd: number
  created_at: string
}

export interface AuditSubmissionDetail extends AuditSubmissionSummary {
  analysis_error: string | null
  items: RemediationItem[]
}

export const AUDIT_ITEM_STATUS_META: Record<AuditItemStatus, { label: string; color: string }> = {
  pending_approval: { label: 'Pending',   color: 'text-amber-400 bg-amber-400/10 border-amber-400/30' },
  approved:         { label: 'Approved',  color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30' },
  dismissed:        { label: 'Dismissed', color: 'text-zinc-500 bg-zinc-900 border-zinc-700' },
}

// ── FinOps / Compliance agent connection (mirrors api/routes/finops_agent.py
// and api/routes/compliance_agent.py -- shared shape, both proxy to a
// separately-deployed Railway service via Cloud Decoded's own backend) ────

export interface AgentSetupPolicy {
  aws_trust_policy: Record<string, unknown>
  aws_permissions_policy: Record<string, unknown>
  azure_setup_instructions: string
}

export interface AgentConnectionStatus {
  connected: boolean
  pending_setup: boolean
  setup: AgentSetupPolicy | null
}

export interface AzureServicePrincipalInput {
  azure_tenant_id: string
  client_id: string
  client_secret: string
  subscription_id: string
  // 24-gap-closure Phase 5 -- captured at connection time, not
  // generated (chosen by the customer in Azure AD).
  client_secret_expires_at?: string | null
}

export interface AzureDevOpsInput {
  org: string
  pat: string
  // 24-gap-closure Phase 5
  pat_expires_at?: string | null
}

export interface K8sClusterInput {
  api_url: string
  token: string
  ca_cert?: string
}

// ── Workspace connections (core platform's own Agents 01/02/05/06/08 --
// api/routes/workspace_credentials.py. Separate from the FinOps/Compliance
// agent connection types above, which proxy to the satellite products) ────

export interface ConnectionsStatus {
  github_connected: boolean
  github_via_legacy_pat: boolean
  aws_connected: boolean
  azure_connected: boolean
  azure_devops_connected: boolean
  k8s_connected: boolean
  llm_configured: boolean
  llm_provider: string | null
  // null for a token-authenticated caller (full trust); set only for a
  // logged-in member session. Onboarding completeness build, item 4.
  member_role: string | null
  // 24-gap-closure Phase 4
  product_tier?: string | null
  require_mfa?: boolean
  // 24-gap-closure Phase 7 follow-up, item 7 (2026-09-17)
  has_contact_email?: boolean
}

// Onboarding completeness build, item 4. last4/rotated_at are display
// hints only -- workspaces.workspace_token stores a one-way hash, so
// 24-gap-closure Phase 6 -- mirrors api/routes/setup_checklist.py's
// SetupChecklistResponse.
export interface SetupChecklist {
  cloud_connected: boolean
  repo_connected: boolean
  alert_source_verified: boolean
  notification_channel_set: boolean
  end_to_end_test_passed: boolean
  completed_count: number
}

export interface ConnectionTestResult {
  incident_id: string
}

// 24-gap-closure Phase 7 -- mirrors api/routes/llm_usage.py's
// LlmUsageResponse/AgentUsage.
export interface AgentUsage {
  agent_id: string
  tokens_used: number
  cost_usd: number
}

export interface LlmUsage {
  billing_month: string
  total_tokens: number
  total_cost_usd: number
  budget_usd: number
  utilization_pct: number
  by_agent: AgentUsage[]
}

// there is no raw token to "reveal" after issuance. See
// db/migrations/040_workspace_token_display_metadata.sql.
export interface WorkspaceTokenStatus {
  last4: string | null
  rotated_at: string | null
  // 24-gap-closure Phase 4
  last_used_at?: string | null
  expires_at?: string | null
  // 24-gap-closure Phase 5 -- non-null only while a prior token is
  // still inside its 72h rotation grace window (survives a page reload,
  // not just the response from the rotate call itself).
  grace_period_ends_at?: string | null
}

export interface RotateWorkspaceTokenResult {
  workspace_token: string
  last4: string
  rotated_at: string
  // 24-gap-closure Phase 5
  grace_period_ends_at: string
  alert_source_checklist: string[]
}

// 24-gap-closure Phase 4 -- mirrors api/routes/workspace_credentials.py's
// SetTokenExpiryResponse.
export interface SetTokenExpiryResult {
  expires_at: string | null
}

// 24-gap-closure Phase 4 -- member removal/deactivation + workspace-wide
// MFA requirement toggle. Mirrors api/routes/workspace_members.py's
// RequireMfaResponse.
export interface RequireMfaResult {
  require_mfa: boolean
}

// Ticketing integrations (Jira/Linear/GitHub Issues/ServiceNow) -- fires on
// incident RESOLUTION, not creation. api/routes/workspace_ticketing.py. A
// workspace may have zero or one of these configured at a time.
export interface TicketingChannelStatus {
  channel_type: string
  enabled: boolean
}

export interface TicketingStatus {
  channel: TicketingChannelStatus | null
  // Only used to gate the ServiceNow form to Enterprise-tier workspaces --
  // the config-save endpoint enforces the real 402 either way.
  product_tier: string
}

export interface ServiceNowConnectInput {
  instance_url: string
  username: string
  password: string
  assignment_group: string
}

export interface JiraConnectInput {
  instance_url: string
  api_token: string
  project_key: string
  issue_type?: string
}

export interface LinearConnectInput {
  api_key: string
  team_id: string
}

export interface GithubIssuesConnectInput {
  repo: string
}

export interface AwsRoleSetup {
  external_id: string
  trust_policy: Record<string, unknown>
  permissions_policy: Record<string, unknown>
  instructions: string
}

// 24-gap-closure Phase 3 -- mirrors api/routes/workspace_notifications.py's
// ExhaustedRetryResponse/ExhaustedRetriesResponse.
export interface ExhaustedRetry {
  id: string
  channel_type: string
  send_kind: string
  attempt_count: number
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface ExhaustedRetriesResponse {
  retries: ExhaustedRetry[]
}


// ── FinOps agent (mirrors kdavis-finops-agent's api/routes/tenants.py +
// scans.py + hitl.py, proxied through api/routes/finops_agent.py) ─────────

export type FinOpsSeverity = 'HIGH' | 'MEDIUM' | 'LOW'
export type FinOpsCategory = 'WASTE' | 'SECURITY' | 'COMPLIANCE'
export type FinOpsItemStatus = 'pending_approval' | 'approved' | 'dismissed'

export interface FinOpsHitlItem {
  id: string
  severity: FinOpsSeverity
  category: FinOpsCategory
  title: string
  description: string
  remediation: string
  estimated_monthly_waste_usd: number
  priority_rank: number
  status: FinOpsItemStatus
}

export interface FinOpsScanSummary {
  scan_id: string
  provider: string
  status: string
  total_findings: number
  total_estimated_monthly_waste_usd: number
  started_at: string
  completed_at: string | null
}

export interface FinOpsDashboardData {
  tenant_id: string
  status: string
  latest_scan: FinOpsScanSummary | null
  open_items: FinOpsHitlItem[]
}

export const FINOPS_ITEM_STATUS_META: Record<FinOpsItemStatus, { label: string; color: string }> = {
  pending_approval: { label: 'Pending',   color: 'text-amber-400 bg-amber-400/10 border-amber-400/30' },
  approved:         { label: 'Approved',  color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30' },
  dismissed:        { label: 'Dismissed', color: 'text-zinc-500 bg-zinc-900 border-zinc-700' },
}

// ── Compliance agent (mirrors kdavis-compliance-agent's
// compliance/gap_report.py, proxied through api/routes/compliance_agent.py) ──

export type CisControlStatus = 'PASS' | 'FAIL'

export interface CisControl {
  control_id: string
  security_hub_id: string
  title: string
  status: CisControlStatus
  exact_match: boolean
  caveat: string | null
}

export interface ComplianceDocChecklistItem {
  item: string
  status: string
  guidance: string
}

export interface ComplianceReportData {
  framework: string
  controls_assessed: number
  controls_total_in_framework: number
  readiness_score: number
  controls: CisControl[]
  coverage_note: string
  documentation_checklist: ComplianceDocChecklistItem[]
}

export interface ComplianceScanResult {
  scan_id: string
  tenant_id: string
  status: string
  provider: string
  report: ComplianceReportData | null
  error_message: string | null
  started_at: string
  completed_at: string | null
}

// ── Content Pipeline ─────────────────────────────────────────────────────

export interface ContentImpact {
  tier: 'strong' | 'solid' | 'weak' | 'unknown'
  label: string
  description: string
  combined_score?: number
}

export interface DraftSummary {
  id: string
  platform: string
  raw_idea: string
  goal: string
  status: string
  brand_voice_score: number | null
  brief_alignment_score: number | null
  brief_title: string | null
  impact: ContentImpact
  created_at: string
  updated_at: string
}

export interface DraftDetail extends DraftSummary {
  brief: Record<string, unknown> | null
  draft_output: {
    platform: string
    draft_a: { text: string; hook: string; word_count: number; hashtags: string[]; engagement_prompt: string }
    draft_b: { text: string; hook: string; word_count: number; hashtags: string[]; engagement_prompt: string }
    writer_notes: string
  } | null
  review_output: {
    decision: string
    brand_voice_score: number
    brief_alignment_score: number
    flags: Array<{ type: string; quote: string; reason: string }>
    approved_draft: string
    revision_notes: string
  } | null
  publish_package: Record<string, unknown> | null
  operator_edit: string | null
  rejection_feedback: string | null
  linkedin_post_id: string | null
  x_post_id: string | null
}
