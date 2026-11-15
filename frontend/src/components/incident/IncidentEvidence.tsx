'use client'

// Gap-table #6-#10: what an approver needs to decide well, kept out of
// RemediationCard (already past the 300-line refactor mark). All of these
// render nothing when an incident or option doesn't carry the data, so real
// agents that don't produce evidence/diffs yet look exactly as before.

import { useEffect, useState } from 'react'
import { FileText, History, RotateCcw, AlertTriangle } from 'lucide-react'
import { listIncidentAudit } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { BlastRadius, EvidenceBlock, IncidentAuditEntry } from '@/lib/types'

const KIND_LABEL: Record<string, string> = {
  log: 'LOG',
  kubectl: 'KUBECTL',
  metrics: 'METRICS',
  terraform: 'TERRAFORM',
  cli: 'CLI',
}

export function EvidencePanel({ evidence }: { evidence?: EvidenceBlock[] | null }) {
  if (!evidence?.length) return null
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Evidence</p>
      {evidence.map((block, i) => (
        <div key={i} className="min-w-0 overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950">
          <div className="flex min-w-0 items-center gap-2 border-b border-zinc-800 px-3 py-1.5">
            <span className="shrink-0 rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400">
              {KIND_LABEL[block.kind] ?? block.kind.toUpperCase()}
            </span>
            <span className="min-w-0 truncate font-mono text-[11px] text-zinc-400" title={block.title}>
              {block.title}
            </span>
          </div>
          <pre className="max-h-56 overflow-auto px-3 py-2 font-mono text-[11px] leading-relaxed text-zinc-300">
            {block.lines.join('\n')}
          </pre>
        </div>
      ))}
    </div>
  )
}

// Unified diff with per-line colouring. No highlighting library: the stack
// rule is no new dependencies, and +/- colouring is what an approver needs.
export function DiffView({ diff }: { diff?: string | null }) {
  if (!diff) return null
  const lines = diff.replace(/\n$/, '').split('\n')
  return (
    <div className="mt-2 min-w-0 overflow-hidden rounded-md border border-zinc-800 bg-zinc-950" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-1.5 border-b border-zinc-800 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-zinc-500">
        <FileText className="h-3 w-3" />
        Proposed change
      </div>
      <pre className="max-h-72 overflow-auto py-1 font-mono text-[11px] leading-relaxed">
        {lines.map((line, i) => {
          const isHeader = line.startsWith('+++') || line.startsWith('---')
          const isHunk = line.startsWith('@@')
          const isAdd = !isHeader && line.startsWith('+')
          const isDel = !isHeader && line.startsWith('-')
          return (
            <div
              key={i}
              className={cn(
                'px-3 whitespace-pre',
                isHeader && 'font-semibold text-zinc-400',
                isHunk && 'bg-blue-500/10 text-blue-300',
                isAdd && 'bg-emerald-500/10 text-emerald-300',
                isDel && 'bg-red-500/10 text-red-300',
                !isHeader && !isHunk && !isAdd && !isDel && 'text-zinc-400',
              )}
            >
              {line || ' '}
            </div>
          )
        })}
      </pre>
    </div>
  )
}

export function BlastRadiusBadge({ blast }: { blast?: BlastRadius | null }) {
  if (!blast) return null
  return (
    <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-1.5">
      <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">Blast radius</span>
      <span className="min-w-0 rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-[11px] text-zinc-300">
        {blast.scope}
      </span>
      <span className="rounded border border-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">
        via {blast.change_surface}
      </span>
      {blast.reversible ? (
        <span className="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-400">
          <RotateCcw className="h-2.5 w-2.5" />
          Reversible
        </span>
      ) : (
        <span className="inline-flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400">
          <AlertTriangle className="h-2.5 w-2.5" />
          Not reversible
        </span>
      )}
    </div>
  )
}

// The incident's own audit_events rows. Refetched whenever the status
// changes, so an approval or rejection appears here as soon as it lands.
export function AuditTrail({ incidentId, status, token }: { incidentId: string; status: string; token: string }) {
  const [entries, setEntries] = useState<IncidentAuditEntry[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    listIncidentAudit(token, incidentId)
      .then((rows) => { if (!cancelled) { setEntries(rows); setError(false) } })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [incidentId, status, token])

  return (
    <div className="mt-6 border-t border-zinc-800 pt-4">
      <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-zinc-500">
        <History className="h-3 w-3" />
        Audit trail
      </p>
      {error ? (
        <p className="text-xs text-zinc-600">Audit trail unavailable right now.</p>
      ) : entries === null ? (
        <p className="text-xs text-zinc-600">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-xs text-zinc-600">No decisions recorded yet. Every approval, rejection and manual resolution is logged here.</p>
      ) : (
        <ol className="space-y-1.5">
          {entries.map((e, i) => (
            <li key={i} className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-xs">
              <span className="shrink-0 font-mono text-[11px] text-zinc-600">
                {e.at ? new Date(e.at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}
              </span>
              <span className="text-zinc-300">{e.label}</span>
              {e.detail.selected_option_id && <span className="font-mono text-[11px] text-zinc-500">{e.detail.selected_option_id}</span>}
              {(e.detail.reason || e.detail.resolution_note) && (
                <span className="min-w-0 truncate text-zinc-500" title={e.detail.reason ?? e.detail.resolution_note}>
                  “{e.detail.reason ?? e.detail.resolution_note}”
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
