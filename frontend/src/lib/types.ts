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
