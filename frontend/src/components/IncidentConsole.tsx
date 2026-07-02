'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw, Wifi, WifiOff, Filter } from 'lucide-react'
import { AnimatePresence } from 'framer-motion'
import { PipelineTracker } from './PipelineTracker'
import { RemediationCard } from './RemediationCard'
import { Button } from '@/components/ui/button'
import { listIncidents } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { Incident, IncidentStatus } from '@/lib/types'

interface IncidentConsoleProps {
  token: string
}

type FilterTab = 'all' | IncidentStatus

const FILTER_TABS: { id: FilterTab; label: string }[] = [
  { id: 'all',              label: 'All' },
  { id: 'pending_approval', label: 'Needs Action' },
  { id: 'executing',        label: 'Running' },
  { id: 'executed',         label: 'Resolved' },
  { id: 'failed',           label: 'Failed' },
]

const POLL_INTERVAL_MS = 5_000

export function IncidentConsole({ token }: IncidentConsoleProps) {
  const [incidents, setIncidents]     = useState<Incident[]>([])
  const [selected, setSelected]       = useState<Incident | null>(null)
  const [filter, setFilter]           = useState<FilterTab>('all')
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState<string | null>(null)
  const [connected, setConnected]     = useState(true)
  const [lastPoll, setLastPoll]       = useState<Date | null>(null)
  const pollRef                       = useRef<ReturnType<typeof setInterval> | null>(null)
  // Ref so fetchIncidents can read latest selected without being in its deps
  const selectedRef                   = useRef<Incident | null>(null)
  selectedRef.current = selected

  const fetchIncidents = useCallback(async () => {
    try {
      const statusFilter = filter === 'all' ? undefined : filter
      const data = await listIncidents(token, statusFilter)
      setIncidents(data)
      setConnected(true)
      setError(null)
      setLastPoll(new Date())

      // Keep selected incident in sync — use ref to avoid this callback
      // being recreated (and the poll being restarted) on every selection change
      const cur = selectedRef.current
      if (cur) {
        const updated = data.find(i => i.incident_id === cur.incident_id)
        if (updated) setSelected(updated)
      }
    } catch (e: unknown) {
      setConnected(false)
      setError(e instanceof Error ? e.message : 'Failed to load incidents')
    } finally {
      setLoading(false)
    }
  }, [token, filter])

  useEffect(() => {
    setLoading(true)
    fetchIncidents()
    pollRef.current = setInterval(fetchIncidents, POLL_INTERVAL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [fetchIncidents])

  function handleApproved(incidentId: string, optionId: string) {
    setIncidents(prev =>
      prev.map(i =>
        i.incident_id === incidentId
          ? { ...i, status: optionId === 'hold' ? 'held' : 'executing' }
          : i,
      ),
    )
    if (selected?.incident_id === incidentId) {
      setSelected(prev =>
        prev ? { ...prev, status: optionId === 'hold' ? 'held' : 'executing' } : null,
      )
    }
  }

  const pendingCount = incidents.filter(i => i.status === 'pending_approval').length

  return (
    <div className="flex h-full flex-col">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-zinc-100">Incident Console</h2>
          {pendingCount > 0 && (
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500 px-1.5 text-xs font-bold text-zinc-900">
              {pendingCount}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Connection status */}
          <div className="flex items-center gap-1.5 text-xs">
            {connected
              ? <Wifi className="h-3 w-3 text-emerald-400" />
              : <WifiOff className="h-3 w-3 text-red-400" />}
            <span className={connected ? 'text-emerald-400' : 'text-red-400'}>
              {connected ? 'Live' : 'Disconnected'}
            </span>
            {lastPoll && (
              <span className="text-zinc-600 hidden sm:inline">
                · Updated {lastPoll.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
            )}
          </div>

          <Button
            variant="ghost"
            size="icon"
            className={cn('h-7 w-7', loading && 'opacity-50')}
            onClick={() => fetchIncidents()}
            disabled={loading}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 border-b border-zinc-800 px-6 py-2">
        <Filter className="h-3 w-3 text-zinc-600 mr-1" />
        {FILTER_TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setFilter(tab.id)}
            className={cn(
              'rounded px-2.5 py-1 text-xs font-medium transition-colors',
              filter === tab.id
                ? 'bg-zinc-800 text-zinc-100'
                : 'text-zinc-500 hover:text-zinc-300',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-4 mt-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {error} — retrying in {POLL_INTERVAL_MS / 1000}s
        </div>
      )}

      {/* Main split layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: incident list */}
        <div className={cn(
          'flex-shrink-0 overflow-y-auto border-r border-zinc-800 p-4',
          selected ? 'w-1/2 xl:w-[55%]' : 'w-full',
        )}>
          {loading && incidents.length === 0 ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCw className="h-5 w-5 animate-spin text-zinc-600" />
            </div>
          ) : (
            <PipelineTracker
              incidents={incidents}
              onSelect={setSelected}
              selectedId={selected?.incident_id ?? null}
            />
          )}
        </div>

        {/* Right: remediation detail */}
        <AnimatePresence>
          {selected && (
            <div className="flex-1 overflow-y-auto p-4">
              <RemediationCard
                key={selected.incident_id}
                incident={selected}
                token={token}
                onApproved={handleApproved}
              />
            </div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
