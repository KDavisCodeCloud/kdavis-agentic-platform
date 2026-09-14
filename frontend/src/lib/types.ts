// Cloud Decoded — shared TypeScript types (mirrors db/models.py)

export type IncidentStatus =
  | 'pending_approval'
  | 'executing'
  | 'executed'
  | 'held'
  | 'failed'
  | 'budget_exceeded'

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
  // enriched on the frontend from webhook context
  agent_id?: string
  cloud_provider?: string
  job_name?: string
  repository?: string
  branch?: string
  created_at?: string
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
}

export const IMPACT_META: Record<ImpactLevel, { label: string; color: string }> = {
  low:    { label: 'Low Impact',    color: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30' },
  medium: { label: 'Med Impact',    color: 'text-amber-400 bg-amber-400/10 border-amber-400/30' },
  high:   { label: 'High Impact',   color: 'text-red-400 bg-red-400/10 border-red-400/30' },
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
}

export interface AzureDevOpsInput {
  org: string
  pat: string
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
  aws_connected: boolean
  azure_connected: boolean
  azure_devops_connected: boolean
  k8s_connected: boolean
}

export interface AwsRoleSetup {
  external_id: string
  trust_policy: Record<string, unknown>
  permissions_policy: Record<string, unknown>
  instructions: string
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
