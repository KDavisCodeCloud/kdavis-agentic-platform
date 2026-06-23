'use client'

import { useState } from 'react'
import { ExternalLink, ShieldCheck, Clock, ChevronDown, ChevronUp, AlertTriangle } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { approveIncident } from '@/lib/api'
import { cn, fmtDuration } from '@/lib/utils'
import { IMPACT_META, STATUS_META, type Incident, type RemediationOption } from '@/lib/types'

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

  const isPending = incident.status === 'pending_approval'
  const statusMeta = STATUS_META[incident.status]

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
    // hold is always last
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
            <span className={cn('h-1.5 w-1.5 rounded-full', statusMeta.dot)} />
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

        {incident.estimated_duration_seconds && (
          <div className="mt-2 flex items-center gap-1.5 text-xs text-zinc-500">
            <Clock className="h-3 w-3" />
            Est. fix time: {fmtDuration(incident.estimated_duration_seconds)}
          </div>
        )}
      </div>

      {/* Options */}
      <div className="flex-1 overflow-y-auto p-5 space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Select Remediation Option
        </p>

        {allOptions.map((opt) => {
          const isSelected = selected === opt.id
          const isExpanded = expanded === opt.id
          const isHold     = opt.id === 'hold'
          const isCustom   = opt.id === 'custom'
          const impact     = IMPACT_META[opt.impact]

          return (
            <div
              key={opt.id}
              onClick={() => isPending && setSelected(opt.id)}
              className={cn(
                'rounded-lg border p-3 transition-all',
                isPending ? 'cursor-pointer' : 'cursor-default opacity-70',
                isSelected
                  ? isHold
                    ? 'border-zinc-600 bg-zinc-800'
                    : 'border-blue-500/60 bg-blue-500/10'
                  : 'border-zinc-800 bg-zinc-950 hover:border-zinc-700 hover:bg-zinc-900/80',
              )}
            >
              <div className="flex items-start gap-3">
                {/* Radio indicator */}
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

                  {/* Expandable description */}
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setExpanded(isExpanded ? null : opt.id) }}
                    className="mt-1 flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300"
                  >
                    {isExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    {isExpanded ? 'Hide details' : 'Show details'}
                  </button>

                  <AnimatePresence>
                    {isExpanded && (
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

                  {/* Custom input textarea */}
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

      {/* Footer actions */}
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
              onClick={() => { setSelected('hold'); }}
            >
              Hold / Skip
            </Button>
            <Button
              className="flex-1"
              size="sm"
              disabled={!selected || selected === '' || loading}
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

      {!isPending && (
        <div className="border-t border-zinc-800 p-4">
          <p className={cn('text-center text-sm', statusMeta.color)}>
            {incident.status === 'executed' && '✓ Remediation complete'}
            {incident.status === 'held' && '— Held by operator'}
            {incident.status === 'executing' && 'Executing remediation…'}
            {incident.status === 'failed' && '✗ Execution failed'}
            {incident.status === 'budget_exceeded' && '⚠ Monthly token budget exceeded'}
          </p>
        </div>
      )}
    </motion.div>
  )
}
