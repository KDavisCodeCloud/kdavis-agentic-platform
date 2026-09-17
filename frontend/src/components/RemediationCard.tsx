'use client'

import { useEffect, useRef, useState } from 'react'
import { ExternalLink, ShieldCheck, Clock, ChevronDown, ChevronUp, AlertTriangle, Loader2, CheckCircle2, XCircle, UserCheck, MessageSquare, Send, ShieldOff } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  approveIncident, resolveIncidentManually, assignIncident, listWorkspaceMembers,
  listIncidentComments, createIncidentComment, exemptResourceFromIncident,
} from '@/lib/api'
import { cn, fmtDuration, timeAgo } from '@/lib/utils'
import { IMPACT_META, SEVERITY_META, STATUS_META, type Incident, type RemediationOption, type WorkspaceMember, type IncidentComment } from '@/lib/types'

// Not a real RemediationOption returned by the agent — a fourth,
// platform-added entry rendered alongside them. Its id is never sent to
// POST /incidents/{id}/approve; selecting it routes to its own inline
// form and POST /incidents/{id}/resolve-manually instead (see
// ManualResolveForm below), never the shared Approve & Execute footer.
const MANUAL_RESOLVE_ID = 'manual_resolve'

// Agent-specific log lines for the execution terminal
const EXEC_LOGS: Record<string, string[]> = {
  agent_01_cicd_triage: [
    '▶  Connecting to AWS IAM...',
    '✓  Authenticated via role assumption',
    '▶  Fetching role: github-deploy-role',
    '✓  Policy retrieved (2 statements)',
    '▶  Computing least-privilege delta...',
    '✓  Statement: Allow s3:PutObject on prod-assets-bucket',
    '▶  Applying policy update...',
    '✓  Policy attached successfully',
    '▶  Triggering pipeline rerun...',
    '✓  GitHub Actions workflow dispatched',
  ],
  agent_02_k8s_alert: [
    '▶  Connecting to AKS cluster...',
    '✓  kubectl context: prod-aks-eastus',
    '▶  Inspecting deployment/payment-service...',
    '✓  Current memory limit: 512Mi',
    '▶  Drafting manifest patch...',
    '✓  resources.limits.memory → 1Gi',
    '▶  Applying rollout...',
    '✓  Rollout triggered: 3/3 pods updating',
    '▶  Verifying pod readiness...',
    '✓  payment-service running healthy',
  ],
  agent_08_drift_detection: [
    '▶  Loading Terraform remote state...',
    '✓  Workspace: prod-us-east-1',
    '▶  Generating corrected resource block...',
    '✓  aws_security_group_rule.deny_public_5432',
    '▶  Opening pull request...',
    '✓  PR #847: fix(security): close public PostgreSQL port',
    '▶  Running terraform plan (dry run)...',
    '✓  Plan: 1 to add, 0 to change, 0 to destroy',
    '▶  Sending alert to #infra-security...',
    '✓  Slack notification sent',
  ],
}

const FALLBACK_LOGS = [
  '▶  Initializing remediation agent...',
  '✓  Authentication successful',
  '▶  Fetching resource state...',
  '✓  Current state retrieved',
  '▶  Computing remediation plan...',
  '✓  Plan validated (0 conflicts)',
  '▶  Applying changes...',
  '✓  Changes applied successfully',
  '▶  Verifying fix...',
  '✓  Incident resolved',
]

function ExecutionLog({ incident }: { incident: Incident }) {
  const [visibleCount, setVisibleCount] = useState(0)
  const [elapsed, setElapsed]           = useState(0)
  const startRef                        = useRef(Date.now())
  const lines = EXEC_LOGS[incident.agent_id ?? ''] ?? FALLBACK_LOGS
  const estimated = incident.estimated_duration_seconds ?? 30
  // Cap visual progress at 95% — final jump to 100% happens when poll detects completion
  const progress = Math.min((elapsed / estimated) * 100, 95)

  useEffect(() => {
    const logTimer = setInterval(() => {
      setVisibleCount(n => Math.min(n + 1, lines.length))
    }, 800)
    const clockTimer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)
    return () => { clearInterval(logTimer); clearInterval(clockTimer) }
  }, [lines.length])

  return (
    <div className="space-y-3">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold text-blue-400">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Executing remediation...
        </div>
        <span className="text-xs tabular-nums text-zinc-500">{elapsed}s elapsed</span>
      </div>

      {/* Progress bar */}
      <div className="h-1 w-full overflow-hidden rounded-full bg-zinc-800">
        <motion.div
          className="h-full rounded-full bg-blue-500"
          initial={{ width: '0%' }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 1, ease: 'linear' }}
        />
      </div>

      {/* Terminal */}
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 overflow-hidden">
        {/* Terminal chrome */}
        <div className="flex items-center gap-1.5 border-b border-zinc-800 px-3 py-2">
          <span className="h-2 w-2 rounded-full bg-red-500/60" />
          <span className="h-2 w-2 rounded-full bg-amber-500/60" />
          <span className="h-2 w-2 rounded-full bg-emerald-500/60" />
          <span className="ml-2 text-xs text-zinc-600 font-mono">agent-execution-log</span>
        </div>

        {/* Log lines */}
        <div className="p-3 font-mono text-xs space-y-0.5 min-h-[120px]">
          {lines.slice(0, visibleCount).map((line, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.15 }}
              className={cn(
                'leading-relaxed',
                line.startsWith('✓') ? 'text-emerald-400' : 'text-zinc-400',
              )}
            >
              {line}
            </motion.div>
          ))}
          {visibleCount < lines.length && (
            <span className="animate-pulse text-blue-400 text-sm">▌</span>
          )}
        </div>
      </div>
    </div>
  )
}

// 24-gap-closure Phase 2 — assignment. Fetches the workspace's member
// list once per mount (not per incident -- the list doesn't change as
// the operator clicks between incidents) and lets the caller reassign
// inline. Errors surface as a small inline message, not a blocking one,
// since assignment is metadata, not the incident's own action flow.
function AssigneePicker({ incident, token, onAssigned }: {
  incident: Incident
  token: string
  onAssigned: (assignedTo: string | null, assignedToEmail: string | null) => void
}) {
  const [members, setMembers] = useState<WorkspaceMember[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  useEffect(() => {
    listWorkspaceMembers(token)
      .then(res => setMembers(res.members))
      .catch(() => { /* non-fatal -- picker just shows "Unassigned" only */ })
  }, [token])

  async function handleChange(memberId: string) {
    setLoading(true)
    setError(null)
    try {
      const updated = await assignIncident(token, incident.incident_id, memberId || null)
      onAssigned(updated.assigned_to ?? null, updated.assigned_to_email ?? null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not update assignment')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-zinc-500">Assigned to</span>
      <select
        value={incident.assigned_to ?? ''}
        onChange={(e) => handleChange(e.target.value)}
        disabled={loading}
        className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-xs text-zinc-200 focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
      >
        <option value="">Unassigned</option>
        {members.map(m => (
          <option key={m.id} value={m.id}>{m.email}</option>
        ))}
      </select>
      {error && <span className="text-xs text-red-400">{error}</span>}
    </div>
  )
}

// 24-gap-closure Phase 2 — comments thread. Any authenticated caller can
// read/post (same trust level as viewing the incident itself); a
// token-authenticated caller's own comments come back with no
// member_email, shown as "You" here rather than a blank author.
function CommentsThread({ incidentId, token }: { incidentId: string; token: string }) {
  const [comments, setComments]   = useState<IncidentComment[]>([])
  const [draft, setDraft]         = useState('')
  const [loading, setLoading]     = useState(true)
  const [posting, setPosting]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listIncidentComments(token, incidentId)
      .then(data => { if (!cancelled) setComments(data) })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Could not load comments') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [incidentId, token])

  async function handleSubmit() {
    const body = draft.trim()
    if (!body) return
    setPosting(true)
    setError(null)
    try {
      const comment = await createIncidentComment(token, incidentId, body)
      setComments(prev => [...prev, comment])
      setDraft('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not post comment')
    } finally {
      setPosting(false)
    }
  }

  return (
    <div className="mt-4 border-t border-zinc-800 pt-4">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
        <MessageSquare className="h-3 w-3" />
        Comments {comments.length > 0 && `(${comments.length})`}
      </div>

      {loading ? (
        <div className="flex justify-center py-3">
          <Loader2 className="h-4 w-4 animate-spin text-zinc-600" />
        </div>
      ) : comments.length === 0 ? (
        <p className="py-2 text-xs text-zinc-600">No comments yet.</p>
      ) : (
        <div className="mb-3 space-y-2 max-h-48 overflow-y-auto">
          {comments.map(c => (
            <div key={c.id} className="rounded border border-zinc-800 bg-zinc-950 p-2">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-zinc-300">{c.member_email ?? 'You'}</span>
                <span className="text-xs text-zinc-600">{timeAgo(c.created_at)}</span>
              </div>
              <p className="text-xs leading-relaxed text-zinc-400 whitespace-pre-wrap">{c.body}</p>
            </div>
          ))}
        </div>
      )}

      {error && (
        <p className="mb-2 rounded border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-400">{error}</p>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !posting) handleSubmit() }}
          placeholder="Add a comment..."
          disabled={posting}
          className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/50 focus:outline-none disabled:opacity-50"
        />
        <Button
          size="icon"
          className="h-7 w-7 shrink-0"
          disabled={posting || !draft.trim()}
          loading={posting}
          onClick={handleSubmit}
        >
          <Send className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}

// Settings → Policies, Step 2 — "Exempt this resource" on the incident
// card. Only meaningful when the incident has a resource_id (agents 08/11
// today — see api/routes/policies.py's exempt_resource_from_incident,
// which 400s without one) -- doesn't change this incident's own status,
// only suppresses FUTURE alerts for the same resource.
function ExemptResourceButton({ incident, token }: { incident: Incident; token: string }) {
  const [open, setOpen]       = useState(false)
  const [reason, setReason]   = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [done, setDone]       = useState(false)

  if (!incident.resource_id) return null
  if (done) {
    return (
      <p className="mt-2 flex items-center gap-1.5 text-xs text-zinc-500">
        <ShieldOff className="h-3 w-3" />
        Future alerts for this resource are suppressed.
      </p>
    )
  }

  async function handleConfirm() {
    setLoading(true)
    setError(null)
    try {
      await exemptResourceFromIncident(token, incident.incident_id, reason.trim())
      setDone(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not exempt this resource')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mt-2">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-300"
        >
          <ShieldOff className="h-3 w-3" />
          Exempt this resource from future alerts
        </button>
      ) : (
        <div className="space-y-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
          <p className="text-xs text-zinc-500">
            Future alerts for <span className="font-mono text-zinc-400">{incident.resource_name || incident.resource_id}</span> will
            be suppressed before diagnosis (no LLM spend) until un-exempted in Settings → Policies.
          </p>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (required) — e.g. known-noisy dev resource"
            className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/50 focus:outline-none"
          />
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" className="border border-zinc-700" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button size="sm" disabled={loading || !reason.trim()} loading={loading} onClick={handleConfirm}>
              Confirm exemption
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

interface RemediationCardProps {
  incident: Incident
  token: string
  onApproved: (incidentId: string, optionId: string) => void
  onResolvedManually: (incidentId: string, resolutionNote: string | null) => void
  onAssigned?: (incidentId: string, assignedTo: string | null, assignedToEmail: string | null) => void
  // Settings → Policies, Step 3: true when this incident's cloud
  // connection (AWS/Azure) is in Read-Only mode for a write-capable
  // agent. Execution options render disabled; manual resolution becomes
  // the primary action. No approve call is ever attempted from here —
  // the server independently rejects it too (defense in depth).
  readOnlyConnection?: boolean
}

export function RemediationCard({ incident, token, onApproved, onResolvedManually, onAssigned, readOnlyConnection }: RemediationCardProps) {
  const [selected, setSelected]         = useState<string | null>(null)
  const [customInput, setCustom]        = useState('')
  const [expanded, setExpanded]         = useState<string | null>(null)
  const [loading, setLoading]           = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [manualNote, setManualNote]     = useState('')
  const [manualLoading, setManualLoading] = useState(false)
  const [manualError, setManualError]   = useState<string | null>(null)

  const isPending   = incident.status === 'pending_approval'
  const isExecuting = incident.status === 'executing'
  const statusMeta  = STATUS_META[incident.status]

  async function handleApprove() {
    if (!selected) return
    setLoading(true)
    setError(null)
    try {
      await approveIncident(token, incident.incident_id, {
        selected_option_id: selected,
        custom_solution_input: selected === 'custom' ? customInput : undefined,
      })
      onApproved(incident.incident_id, selected)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Approval failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleConfirmManualResolve() {
    setManualLoading(true)
    setManualError(null)
    try {
      const result = await resolveIncidentManually(token, incident.incident_id, {
        resolution_note: manualNote.trim() || undefined,
      })
      onResolvedManually(incident.incident_id, result.resolution_note)
    } catch (e: unknown) {
      setManualError(e instanceof Error ? e.message : 'Could not record resolution')
    } finally {
      setManualLoading(false)
    }
  }

  const allOptions: RemediationOption[] = [
    ...incident.options.filter((o) => o.id !== 'hold'),
    {
      id: 'custom',
      title: 'Enter custom solution',
      description: 'Describe a custom fix for the platform to execute.',
      impact: 'low',
      docs_url: '',
    },
    {
      id: MANUAL_RESOLVE_ID,
      title: "I'll handle this myself",
      description: 'Resolve this outside the platform. No cloud API call, agent run, or credential access — just a record of what you did, for your own audit trail.',
      impact: 'low',
      docs_url: '',
    },
    ...incident.options.filter((o) => o.id === 'hold'),
  ]

  return (
    <motion.div
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 16 }}
      transition={{ duration: 0.2 }}
      className="flex h-full flex-col overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900"
    >
      {/* Header */}
      <div className="border-b border-zinc-800 p-5">
        <div className="mb-3 flex items-center justify-between gap-3">
          <span className="text-xs font-mono text-zinc-500 truncate">
            #{incident.incident_id.slice(0, 8)}
          </span>
          <span className={cn('inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium', statusMeta.bg, statusMeta.color)}>
            {incident.status === 'executed'
              ? <CheckCircle2 className="h-3 w-3" />
              : incident.status === 'resolved_manually'
              ? <UserCheck className="h-3 w-3" />
              : incident.status === 'failed'
              ? <XCircle className="h-3 w-3" />
              : <span className={cn('h-1.5 w-1.5 rounded-full', statusMeta.dot)} />
            }
            {statusMeta.label}
          </span>
        </div>

        {(incident.agent_id || incident.severity) && (
          <div className="mb-2 flex items-center gap-2">
            {incident.agent_id && (
              <Badge variant="default" className="text-xs">
                {incident.agent_id.replace(/_/g, ' ').replace('agent ', 'Agent ').toUpperCase()}
              </Badge>
            )}
            {incident.severity && (
              <span className={cn('rounded border px-2 py-0.5 text-xs font-medium', SEVERITY_META[incident.severity].color)}>
                {SEVERITY_META[incident.severity].label}
              </span>
            )}
          </div>
        )}

        {onAssigned && (
          <div className="mb-2">
            <AssigneePicker
              incident={incident}
              token={token}
              onAssigned={(assignedTo, assignedToEmail) => onAssigned(incident.incident_id, assignedTo, assignedToEmail)}
            />
          </div>
        )}

        {/* Diagnosis */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            <AlertTriangle className="h-3 w-3" />
            Root Cause
          </div>
          <p className="text-sm leading-relaxed text-zinc-200">{incident.parsed_error}</p>
        </div>

        {incident.estimated_duration_seconds && isPending && (
          <div className="mt-2 flex items-center gap-1.5 text-xs text-zinc-500">
            <Clock className="h-3 w-3" />
            Est. fix time: {fmtDuration(incident.estimated_duration_seconds)}
          </div>
        )}

        <ExemptResourceButton incident={incident} token={token} />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-5">
        {/* Execution log — shown while running */}
        {isExecuting && <ExecutionLog incident={incident} />}

        {/* Option selector — shown while pending */}
        {isPending && (
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Select Remediation Option
            </p>

            {allOptions.map((opt) => {
              const isSelected      = selected === opt.id
              const isExp           = expanded === opt.id
              const isHold          = opt.id === 'hold'
              const isCustom        = opt.id === 'custom'
              const isManualResolve = opt.id === MANUAL_RESOLVE_ID
              const impact          = IMPACT_META[opt.impact]
              // Settings → Policies, Step 3: hold and manual-resolve never
              // execute anything, so they're never blocked by read-only mode.
              const isBlockedByReadOnly = !!readOnlyConnection && !isHold && !isManualResolve

              return (
                <div
                  key={opt.id}
                  onClick={() => { if (!isBlockedByReadOnly) setSelected(opt.id) }}
                  className={cn(
                    'rounded-lg border p-3 transition-all',
                    isBlockedByReadOnly
                      ? 'cursor-not-allowed border-zinc-800 bg-zinc-950/50 opacity-50'
                      : 'cursor-pointer',
                    !isBlockedByReadOnly && isSelected
                      ? isHold
                        ? 'border-zinc-600 bg-zinc-800'
                        : isManualResolve
                        ? 'border-emerald-500/60 bg-emerald-500/10'
                        : 'border-blue-500/60 bg-blue-500/10'
                      : !isBlockedByReadOnly ? 'border-zinc-800 bg-zinc-950 hover:border-zinc-700 hover:bg-zinc-900/80' : '',
                  )}
                >
                  <div className="flex items-start gap-3">
                    {isManualResolve ? (
                      <UserCheck className={cn(
                        'mt-0.5 h-4 w-4 shrink-0',
                        isSelected ? 'text-emerald-400' : 'text-zinc-500',
                      )} />
                    ) : (
                      <div className={cn(
                        'mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 transition-colors',
                        isSelected
                          ? isHold ? 'border-zinc-500 bg-zinc-500' : 'border-blue-500 bg-blue-500'
                          : 'border-zinc-600',
                      )} />
                    )}

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <span className={cn(
                          'text-sm font-medium',
                          isHold ? 'text-zinc-400' : 'text-zinc-100',
                        )}>
                          {opt.title}
                        </span>
                        {!isHold && !isCustom && !isManualResolve && (
                          <span className={cn('rounded border px-1.5 py-0.5 text-xs', impact.color)}>
                            {impact.label}
                          </span>
                        )}
                      </div>

                      {isBlockedByReadOnly && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-amber-400">
                          <AlertTriangle className="h-3 w-3 shrink-0" />
                          Requires write access — this connection is in Read-Only mode. See the
                          permission guide, or use &quot;I&apos;ll handle this myself&quot; below.
                        </p>
                      )}

                      {isManualResolve ? (
                        <p className="mt-1 text-xs leading-relaxed text-zinc-500">{opt.description}</p>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); setExpanded(isExp ? null : opt.id) }}
                            className="mt-1 flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300"
                          >
                            {isExp ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                            {isExp ? 'Hide details' : 'Show details'}
                          </button>

                          <AnimatePresence>
                            {isExp && (
                              <motion.div
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: 'auto', opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                transition={{ duration: 0.15 }}
                                className="overflow-hidden"
                              >
                                <p className="mt-2 text-xs leading-relaxed text-zinc-400">
                                  {opt.description}
                                </p>
                                {opt.docs_url && (
                                  <a
                                    href={opt.docs_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    onClick={(e) => e.stopPropagation()}
                                    className="mt-1.5 inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
                                  >
                                    <ExternalLink className="h-3 w-3" />
                                    Official docs
                                  </a>
                                )}
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </>
                      )}

                      {isCustom && isSelected && (
                        <textarea
                          value={customInput}
                          onChange={(e) => setCustom(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          placeholder="Describe the custom fix (e.g., 'Update the npm lock file and rerun')"
                          rows={3}
                          className="mt-2 w-full resize-none rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500 focus:outline-none"
                        />
                      )}

                      {/* Inline "I'll handle this myself" form — its own
                          Confirm button, its own endpoint. Never routes
                          through the shared Approve & Execute footer. */}
                      {isManualResolve && isSelected && (
                        <div className="mt-3 space-y-2" onClick={(e) => e.stopPropagation()}>
                          <label className="block text-xs text-zinc-500">
                            What did you do? <span className="text-zinc-600">(stored in your audit log)</span>
                          </label>
                          <textarea
                            value={manualNote}
                            onChange={(e) => setManualNote(e.target.value)}
                            placeholder="Optional — e.g., 'Rotated the credential manually in the AWS console.'"
                            rows={3}
                            maxLength={4000}
                            className="w-full resize-none rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none"
                          />
                          {manualError && (
                            <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                              {manualError}
                            </p>
                          )}
                          <Button
                            size="sm"
                            className="w-full bg-emerald-600 hover:bg-emerald-500"
                            disabled={manualLoading}
                            loading={manualLoading}
                            onClick={handleConfirmManualResolve}
                          >
                            <UserCheck className="h-4 w-4" />
                            Confirm
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Completion panel — shown for resolved/held/failed */}
        {!isPending && !isExecuting && (
          <div className="flex flex-col items-center justify-center py-8 text-center gap-3">
            {incident.status === 'executed' && (
              <>
                <CheckCircle2 className="h-10 w-10 text-emerald-400" />
                <div>
                  <p className="text-sm font-medium text-emerald-400">Remediation complete</p>
                  <p className="mt-1 text-xs text-zinc-500">The incident has been resolved and verified.</p>
                </div>
              </>
            )}
            {incident.status === 'held' && (
              <>
                <span className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-zinc-600 text-zinc-500 text-xl">—</span>
                <div>
                  <p className="text-sm font-medium text-zinc-400">Held by operator</p>
                  <p className="mt-1 text-xs text-zinc-500">Awaiting manual resolution.</p>
                </div>
              </>
            )}
            {incident.status === 'failed' && (
              <>
                <XCircle className="h-10 w-10 text-red-400" />
                <div className="max-w-sm">
                  <p className="text-sm font-medium text-red-400">
                    {incident.failure_kind === 'permission_denied' ? 'Insufficient permissions' : 'Execution failed'}
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                    {incident.failure_reason
                      ?? 'Review the logs and retry manually or escalate.'}
                  </p>
                </div>
              </>
            )}
            {incident.status === 'budget_exceeded' && (
              <>
                <span className="text-3xl">⚠</span>
                <div>
                  <p className="text-sm font-medium text-orange-400">Monthly token budget exceeded</p>
                  <p className="mt-1 text-xs text-zinc-500">Upgrade your plan or wait for next billing cycle.</p>
                </div>
              </>
            )}
            {incident.status === 'resolved_manually' && (
              <>
                <UserCheck className="h-10 w-10 text-emerald-400" />
                <div className="max-w-xs">
                  <p className="text-sm font-medium text-emerald-400">Resolved manually</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {incident.resolution_note
                      ? `"${incident.resolution_note}"`
                      : 'Marked resolved outside the platform. No action was executed here.'}
                  </p>
                </div>
              </>
            )}
            {incident.status === 'rejected' && (
              <>
                <XCircle className="h-10 w-10 text-zinc-500" />
                <div>
                  <p className="text-sm font-medium text-zinc-400">Dismissed</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    This remediation was dismissed. No action was executed.
                  </p>
                </div>
              </>
            )}
          </div>
        )}

        {/* Comments thread — 24-gap-closure Phase 2. Always visible,
            regardless of incident status; a comment thread is a
            collaborative record, not part of the approve/resolve flow. */}
        <CommentsThread incidentId={incident.incident_id} token={token} />
      </div>

      {/* Footer — approve buttons (pending only, and not while the
          manual-resolve form's own Confirm button is the active action) */}
      {isPending && selected !== MANUAL_RESOLVE_ID && (
        <div className="border-t border-zinc-800 p-4 space-y-2">
          {error && (
            <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="flex-1 border border-zinc-700"
              disabled={loading}
              onClick={() => setSelected('hold')}
            >
              Hold / Skip
            </Button>
            <Button
              className="flex-1"
              size="sm"
              disabled={!selected || loading}
              loading={loading}
              onClick={handleApprove}
            >
              <ShieldCheck className="h-4 w-4" />
              Approve & Execute
            </Button>
          </div>
          {!selected && (
            <p className="text-center text-xs text-zinc-600">Select an option above to approve</p>
          )}
        </div>
      )}
    </motion.div>
  )
}
