'use client'

import { useEffect, useRef, useState } from 'react'
import { ExternalLink, ShieldCheck, Clock, ChevronDown, ChevronUp, AlertTriangle, Loader2, CheckCircle2, XCircle } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { approveIncident } from '@/lib/api'
import { cn, fmtDuration } from '@/lib/utils'
import { IMPACT_META, STATUS_META, type Incident, type RemediationOption } from '@/lib/types'

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

interface RemediationCardProps {
  incident: Incident
  token: string
  onApproved: (incidentId: string, optionId: string) => void
}

export function RemediationCard({ incident, token, onApproved }: RemediationCardProps) {
  const [selected, setSelected]     = useState<string | null>(null)
  const [customInput, setCustom]    = useState('')
  const [expanded, setExpanded]     = useState<string | null>(null)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState<string | null>(null)

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

  const allOptions: RemediationOption[] = [
    ...incident.options.filter((o) => o.id !== 'hold'),
    {
      id: 'custom',
      title: 'Enter custom solution',
      description: 'Describe a custom fix for the platform to execute.',
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
              : incident.status === 'failed'
              ? <XCircle className="h-3 w-3" />
              : <span className={cn('h-1.5 w-1.5 rounded-full', statusMeta.dot)} />
            }
            {statusMeta.label}
          </span>
        </div>

        {incident.agent_id && (
          <div className="mb-2">
            <Badge variant="default" className="text-xs">
              {incident.agent_id.replace(/_/g, ' ').replace('agent ', 'Agent ').toUpperCase()}
            </Badge>
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
              const isSelected = selected === opt.id
              const isExp      = expanded === opt.id
              const isHold     = opt.id === 'hold'
              const isCustom   = opt.id === 'custom'
              const impact     = IMPACT_META[opt.impact]

              return (
                <div
                  key={opt.id}
                  onClick={() => setSelected(opt.id)}
                  className={cn(
                    'rounded-lg border p-3 transition-all cursor-pointer',
                    isSelected
                      ? isHold
                        ? 'border-zinc-600 bg-zinc-800'
                        : 'border-blue-500/60 bg-blue-500/10'
                      : 'border-zinc-800 bg-zinc-950 hover:border-zinc-700 hover:bg-zinc-900/80',
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className={cn(
                      'mt-0.5 h-4 w-4 shrink-0 rounded-full border-2 transition-colors',
                      isSelected
                        ? isHold ? 'border-zinc-500 bg-zinc-500' : 'border-blue-500 bg-blue-500'
                        : 'border-zinc-600',
                    )} />

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <span className={cn(
                          'text-sm font-medium',
                          isHold ? 'text-zinc-400' : 'text-zinc-100',
                        )}>
                          {opt.title}
                        </span>
                        {!isHold && !isCustom && (
                          <span className={cn('rounded border px-1.5 py-0.5 text-xs', impact.color)}>
                            {impact.label}
                          </span>
                        )}
                      </div>

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
                <div>
                  <p className="text-sm font-medium text-red-400">Execution failed</p>
                  <p className="mt-1 text-xs text-zinc-500">Review the logs and retry manually or escalate.</p>
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
          </div>
        )}
      </div>

      {/* Footer — approve buttons (pending only) */}
      {isPending && (
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
