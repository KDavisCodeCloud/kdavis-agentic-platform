'use client'

import { useEffect, useState } from 'react'
import { GitBranch, Zap, CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn, agentLabel, timeAgo } from '@/lib/utils'
import type { Incident, IncidentStatus } from '@/lib/types'

interface PipelineTrackerProps {
  incidents: Incident[]
  onSelect: (incident: Incident) => void
  selectedId: string | null
}

type PipelineStep = {
  id: string
  label: string
  status: 'done' | 'active' | 'waiting' | 'error'
}

function stepsForStatus(status: IncidentStatus): PipelineStep[] {
  const steps = [
    { id: 'ingest',   label: 'Ingested' },
    { id: 'diagnose', label: 'Diagnosed' },
    { id: 'hitl',     label: 'Awaiting Approval' },
    { id: 'execute',  label: 'Executing' },
    { id: 'complete', label: 'Resolved' },
  ]

  const activeIndex: Record<IncidentStatus, number> = {
    pending_approval: 2,
    executing:        3,
    executed:         4,
    held:             2, // stopped at HITL gate — steps 3-4 stay waiting
    failed:           3,
    budget_exceeded:  2,
  }

  const active = activeIndex[status] ?? 2
  // Any terminal status: the active step is done, not spinning
  const isTerminal = ['executed', 'held', 'budget_exceeded'].includes(status)

  return steps.map((s, i) => ({
    ...s,
    status:
      status === 'failed' && i === active
        ? 'error'
        : i < active || (isTerminal && i === active)
        ? 'done'
        : i === active
        ? 'active'
        : 'waiting',
  }))
}

function StepDot({ status }: { status: PipelineStep['status'] }) {
  return (
    <div className={cn(
      'relative flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2',
      status === 'done'    && 'border-emerald-500 bg-emerald-500',
      status === 'active'  && 'border-blue-400 bg-blue-400/20',
      status === 'error'   && 'border-red-400 bg-red-400/20',
      status === 'waiting' && 'border-zinc-700 bg-zinc-900',
    )}>
      {status === 'done'   && <CheckCircle2 className="h-3 w-3 text-white" />}
      {status === 'active' && <Loader2 className="h-3 w-3 text-blue-400 animate-spin" />}
      {status === 'error'  && <XCircle className="h-3 w-3 text-red-400" />}
    </div>
  )
}

function IncidentRow({ incident, isSelected, onClick }: {
  incident: Incident
  isSelected: boolean
  onClick: () => void
}) {
  const steps = stepsForStatus(incident.status)
  const isPending = incident.status === 'pending_approval'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 4 }}
      onClick={onClick}
      className={cn(
        'cursor-pointer rounded-lg border p-3 transition-all',
        isSelected
          ? 'border-blue-500/50 bg-blue-500/10'
          : 'border-zinc-800 bg-zinc-950 hover:border-zinc-700 hover:bg-zinc-900/60',
        isPending && !isSelected && 'border-amber-500/30 bg-amber-500/5',
      )}
    >
      {/* Top row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          {incident.status === 'pending_approval' && (
            <span className="h-2 w-2 shrink-0 rounded-full bg-amber-400 animate-pulse" />
          )}
          {incident.status === 'executing' && (
            <Loader2 className="h-3 w-3 shrink-0 text-blue-400 animate-spin" />
          )}
          {incident.status === 'executed' && (
            <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
          )}
          {incident.status === 'held' && (
            <span className="h-2 w-2 shrink-0 rounded-full bg-zinc-500" />
          )}
          {incident.status === 'failed' && (
            <XCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />
          )}
          <span className="truncate text-xs font-mono text-zinc-400">
            #{incident.incident_id.slice(0, 8)}
          </span>
          <span className="shrink-0 rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">
            {agentLabel(incident.agent_id ?? 'agent_01_cicd_triage')}
          </span>
        </div>
        <span className="shrink-0 text-xs text-zinc-600">
          {incident.created_at ? timeAgo(incident.created_at) : '—'}
        </span>
      </div>

      {/* Repo + branch */}
      {(incident.repository || incident.branch) && (
        <div className="mb-2 flex items-center gap-1.5 text-xs text-zinc-500">
          <GitBranch className="h-3 w-3 shrink-0" />
          <span className="truncate">
            {incident.repository && <span className="text-zinc-400">{incident.repository}</span>}
            {incident.branch && <span className="text-zinc-600"> @ {incident.branch}</span>}
          </span>
        </div>
      )}

      {/* Error preview */}
      <p className="mb-3 text-xs leading-relaxed text-zinc-400 line-clamp-2">
        {incident.parsed_error}
      </p>

      {/* Pipeline step progress */}
      <div className="flex items-center gap-0">
        {steps.map((step, i) => (
          <div key={step.id} className="flex items-center">
            <StepDot status={step.status} />
            {i < steps.length - 1 && (
              <div className={cn(
                'h-px w-4 transition-colors',
                step.status === 'done' ? 'bg-emerald-700' : 'bg-zinc-800',
              )} />
            )}
          </div>
        ))}
        <span className="ml-2 text-xs text-zinc-600">
          {{
            pending_approval: 'Awaiting Approval',
            executing:        'Executing',
            executed:         'Resolved',
            held:             'Held',
            failed:           'Failed',
            budget_exceeded:  'Budget Exceeded',
          }[incident.status]}
        </span>
      </div>
    </motion.div>
  )
}

export function PipelineTracker({ incidents, onSelect, selectedId }: PipelineTrackerProps) {
  const [tick, setTick] = useState(0)

  // Update relative timestamps every 30 seconds
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30_000)
    return () => clearInterval(id)
  }, [])

  const pending  = incidents.filter(i => i.status === 'pending_approval')
  const active   = incidents.filter(i => i.status === 'executing')
  const resolved = incidents.filter(i => ['executed', 'held', 'failed', 'budget_exceeded'].includes(i.status))

  if (incidents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <Zap className="mb-3 h-8 w-8 text-zinc-700" />
        <p className="text-sm text-zinc-500">No incidents yet</p>
        <p className="mt-1 text-xs text-zinc-700">
          Connect a webhook to start receiving pipeline failures
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4" key={tick}>
      {pending.length > 0 && (
        <section>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-amber-400">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
            Awaiting Approval ({pending.length})
          </h3>
          <AnimatePresence mode="popLayout">
            <div className="space-y-2">
              {pending.map(inc => (
                <IncidentRow
                  key={inc.incident_id}
                  incident={inc}
                  isSelected={inc.incident_id === selectedId}
                  onClick={() => onSelect(inc)}
                />
              ))}
            </div>
          </AnimatePresence>
        </section>
      )}

      {active.length > 0 && (
        <section>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-blue-400">
            <Loader2 className="h-3 w-3 animate-spin" />
            Executing ({active.length})
          </h3>
          <div className="space-y-2">
            {active.map(inc => (
              <IncidentRow
                key={inc.incident_id}
                incident={inc}
                isSelected={inc.incident_id === selectedId}
                onClick={() => onSelect(inc)}
              />
            ))}
          </div>
        </section>
      )}

      {resolved.length > 0 && (
        <section>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-400">
            <CheckCircle2 className="h-3 w-3" />
            Resolved ({resolved.length})
          </h3>
          <div className="space-y-2">
            {resolved.slice(0, 10).map(inc => (
              <IncidentRow
                key={inc.incident_id}
                incident={inc}
                isSelected={inc.incident_id === selectedId}
                onClick={() => onSelect(inc)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
