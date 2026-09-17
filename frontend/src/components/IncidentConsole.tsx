'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw, Wifi, WifiOff, Filter, X, UserCheck, XCircle } from 'lucide-react'
import { AnimatePresence } from 'framer-motion'
import { PipelineTracker } from './PipelineTracker'
import { RemediationCard } from './RemediationCard'
import { Button } from '@/components/ui/button'
import { listIncidents, bulkIncidentAction, getConnectionsStatus } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { Incident, IncidentStatus, IncidentFilters, ConnectionsStatus } from '@/lib/types'

interface IncidentConsoleProps {
  token: string
}

type FilterTab = 'all' | IncidentStatus

const FILTER_TABS: { id: FilterTab; label: string }[] = [
  { id: 'all',               label: 'All' },
  { id: 'pending_approval',  label: 'Needs Action' },
  { id: 'executing',         label: 'Running' },
  { id: 'executed',          label: 'Resolved' },
  { id: 'resolved_manually', label: 'Resolved Manually' },
  { id: 'failed',            label: 'Failed' },
]

const SEVERITY_OPTIONS = ['critical', 'high', 'medium', 'low'] as const

const AGENT_OPTIONS = [
  'agent_01_cicd_triage', 'agent_02_k8s_alert', 'agent_03_pr_review', 'agent_04_migration',
  'agent_05_iam_minimizer', 'agent_06_finops', 'agent_07_runbook', 'agent_08_drift_detection',
  'agent_09_onboarding_buddy', 'agent_10_dependency_patch', 'agent_11_resource_health',
]

const POLL_INTERVAL_MS = 5_000

// Settings → Policies, Step 3. Mirrors api/routes/incidents.py's
// _CLOUD_CONNECTION_MODE_GATED_AGENTS -- only agents 05 (IAM) and 06
// (FinOps) call AWS/Azure ARM write APIs directly; every other agent's
// writes go through a repo PR or a Kubernetes API call, unaffected by
// aws_connection_mode/azure_connection_mode regardless of cloud_provider.
const _CLOUD_CONNECTION_MODE_GATED_AGENTS = new Set(['agent_05_iam_minimizer', 'agent_06_finops'])

function isReadOnlyBlocked(incident: Incident, connections: ConnectionsStatus | null): boolean {
  if (!connections || !incident.agent_id || !_CLOUD_CONNECTION_MODE_GATED_AGENTS.has(incident.agent_id)) return false
  if (incident.cloud_provider === 'aws') return connections.aws_connection_mode === 'read_only'
  if (incident.cloud_provider === 'azure') return connections.azure_connection_mode === 'read_only'
  return false
}

// 24-gap-closure Phase 2 -- search/filter API + dashboard UI.
interface SearchFilters {
  resource_name: string
  severity: string
  agent_id: string
  date_from: string
  date_to: string
  assignedToMe: boolean
}

const EMPTY_SEARCH_FILTERS: SearchFilters = {
  resource_name: '', severity: '', agent_id: '', date_from: '', date_to: '', assignedToMe: false,
}

function hasActiveSearchFilters(f: SearchFilters): boolean {
  return !!(f.resource_name || f.severity || f.agent_id || f.date_from || f.date_to || f.assignedToMe)
}

export function IncidentConsole({ token }: IncidentConsoleProps) {
  const [incidents, setIncidents]     = useState<Incident[]>([])
  const [selected, setSelected]       = useState<Incident | null>(null)
  const [filter, setFilter]           = useState<FilterTab>('all')
  const [searchFilters, setSearchFilters] = useState<SearchFilters>(EMPTY_SEARCH_FILTERS)
  const [showSearch, setShowSearch]   = useState(false)
  const [loading, setLoading]         = useState(true)
  const [error, setError]             = useState<string | null>(null)
  const [connected, setConnected]     = useState(true)
  // Settings → Policies, Step 3 -- so RemediationCard can render execution
  // options disabled for a Read-Only-mode connection without waiting for
  // the approve call to 403. Fetched once; connection mode changes rarely
  // enough that this doesn't need to be part of the 5s incident poll.
  const [connections, setConnections] = useState<ConnectionsStatus | null>(null)
  const [lastPoll, setLastPoll]       = useState<Date | null>(null)
  const pollRef                       = useRef<ReturnType<typeof setInterval> | null>(null)
  // Ref so fetchIncidents can read latest selected without being in its deps
  const selectedRef                   = useRef<Incident | null>(null)
  selectedRef.current = selected

  // Bulk select — only ever holds pending_approval incident ids (the only
  // status bulk dismiss/resolve-manually apply to, same as the
  // single-incident endpoints). Cleared on every successful fetch that no
  // longer contains a checked id (e.g. it moved out of pending elsewhere).
  const [checkedIds, setCheckedIds]   = useState<Set<string>>(new Set())
  const [bulkNote, setBulkNote]       = useState('')
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkError, setBulkError]     = useState<string | null>(null)

  const fetchIncidents = useCallback(async () => {
    try {
      const statusFilter = filter === 'all' ? undefined : filter
      const apiFilters: Omit<IncidentFilters, 'status_filter'> = {
        severity: (searchFilters.severity || undefined) as IncidentFilters['severity'],
        agent_id: searchFilters.agent_id || undefined,
        resource_name: searchFilters.resource_name || undefined,
        date_from: searchFilters.date_from || undefined,
        date_to: searchFilters.date_to || undefined,
        assigned_to: searchFilters.assignedToMe ? 'me' : undefined,
      }
      const data = await listIncidents(token, statusFilter, apiFilters)
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

      // Drop any checked id that's no longer present or no longer pending
      setCheckedIds(prev => {
        if (prev.size === 0) return prev
        const stillValid = new Set(
          data.filter(i => i.status === 'pending_approval' && prev.has(i.incident_id)).map(i => i.incident_id),
        )
        return stillValid.size === prev.size ? prev : stillValid
      })
    } catch (e: unknown) {
      setConnected(false)
      setError(e instanceof Error ? e.message : 'Failed to load incidents')
    } finally {
      setLoading(false)
    }
  }, [token, filter, searchFilters])

  useEffect(() => {
    setLoading(true)
    fetchIncidents()
    pollRef.current = setInterval(fetchIncidents, POLL_INTERVAL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [fetchIncidents])

  useEffect(() => {
    getConnectionsStatus(token).then(setConnections).catch(() => setConnections(null))
  }, [token])

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

  function handleResolvedManually(incidentId: string, resolutionNote: string | null) {
    setIncidents(prev =>
      prev.map(i =>
        i.incident_id === incidentId
          ? { ...i, status: 'resolved_manually', resolution_note: resolutionNote }
          : i,
      ),
    )
    if (selected?.incident_id === incidentId) {
      setSelected(prev =>
        prev ? { ...prev, status: 'resolved_manually', resolution_note: resolutionNote } : null,
      )
    }
  }

  const pendingCount = incidents.filter(i => i.status === 'pending_approval').length

  function handleAssigned(incidentId: string, assignedTo: string | null, assignedToEmail: string | null) {
    setIncidents(prev =>
      prev.map(i => (i.incident_id === incidentId ? { ...i, assigned_to: assignedTo, assigned_to_email: assignedToEmail } : i)),
    )
    if (selected?.incident_id === incidentId) {
      setSelected(prev => (prev ? { ...prev, assigned_to: assignedTo, assigned_to_email: assignedToEmail } : null))
    }
  }

  function toggleCheck(incidentId: string) {
    setCheckedIds(prev => {
      const next = new Set(prev)
      if (next.has(incidentId)) next.delete(incidentId)
      else next.add(incidentId)
      return next
    })
  }

  async function handleBulkAction(action: 'dismiss' | 'resolve_manually') {
    if (checkedIds.size === 0) return
    setBulkLoading(true)
    setBulkError(null)
    try {
      const ids = [...checkedIds]
      const note = bulkNote.trim() || undefined
      await bulkIncidentAction(
        token, ids, action,
        action === 'dismiss' ? { reason: note } : { resolution_note: note },
      )
      setCheckedIds(new Set())
      setBulkNote('')
      await fetchIncidents()
    } catch (e: unknown) {
      setBulkError(e instanceof Error ? e.message : 'Bulk action failed')
    } finally {
      setBulkLoading(false)
    }
  }

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
            size="sm"
            className={cn('h-7 gap-1.5 px-2 text-xs', (showSearch || hasActiveSearchFilters(searchFilters)) && 'bg-zinc-800 text-zinc-100')}
            onClick={() => setShowSearch(s => !s)}
          >
            <Filter className="h-3 w-3" />
            Search
            {hasActiveSearchFilters(searchFilters) && (
              <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
            )}
          </Button>

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

      {/* Search / filter panel — 24-gap-closure Phase 2. resource_id has
          no input here (it's an opaque cloud identifier, not something an
          operator types from memory) -- resource_name covers the
          human-readable search case this UI is actually for. */}
      {showSearch && (
        <div className="flex flex-wrap items-end gap-3 border-b border-zinc-800 bg-zinc-950/50 px-6 py-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Resource name</label>
            <input
              type="text"
              value={searchFilters.resource_name}
              onChange={(e) => setSearchFilters(f => ({ ...f, resource_name: e.target.value }))}
              placeholder="e.g. payment-service"
              className="w-44 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/50 focus:outline-none"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Severity</label>
            <select
              value={searchFilters.severity}
              onChange={(e) => setSearchFilters(f => ({ ...f, severity: e.target.value }))}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:border-blue-500/50 focus:outline-none"
            >
              <option value="">Any</option>
              {SEVERITY_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">Agent</label>
            <select
              value={searchFilters.agent_id}
              onChange={(e) => setSearchFilters(f => ({ ...f, agent_id: e.target.value }))}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:border-blue-500/50 focus:outline-none"
            >
              <option value="">Any</option>
              {AGENT_OPTIONS.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">From</label>
            <input
              type="date"
              value={searchFilters.date_from}
              onChange={(e) => setSearchFilters(f => ({ ...f, date_from: e.target.value }))}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:border-blue-500/50 focus:outline-none"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-zinc-500">To</label>
            <input
              type="date"
              value={searchFilters.date_to}
              onChange={(e) => setSearchFilters(f => ({ ...f, date_to: e.target.value }))}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:border-blue-500/50 focus:outline-none"
            />
          </div>
          <button
            onClick={() => setSearchFilters(f => ({ ...f, assignedToMe: !f.assignedToMe }))}
            className={cn(
              'flex h-[26px] items-center gap-1.5 rounded border px-2.5 text-xs font-medium transition-colors',
              searchFilters.assignedToMe
                ? 'border-blue-500/50 bg-blue-500/10 text-blue-400'
                : 'border-zinc-700 text-zinc-500 hover:text-zinc-300',
            )}
          >
            <UserCheck className="h-3 w-3" />
            Assigned to me
          </button>
          {hasActiveSearchFilters(searchFilters) && (
            <button
              onClick={() => setSearchFilters(EMPTY_SEARCH_FILTERS)}
              className="flex h-[26px] items-center gap-1 rounded px-2 text-xs text-zinc-500 hover:text-zinc-300"
            >
              <X className="h-3 w-3" />
              Clear
            </button>
          )}
        </div>
      )}

      {/* Bulk action bar — 24-gap-closure Phase 2. Only ever appears when
          1+ pending_approval incidents are checked. */}
      {checkedIds.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 bg-blue-500/5 px-6 py-2.5">
          <span className="text-xs font-medium text-zinc-300">
            {checkedIds.size} selected
          </span>
          <input
            type="text"
            value={bulkNote}
            onChange={(e) => setBulkNote(e.target.value)}
            placeholder="Optional reason / note for all selected"
            className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/50 focus:outline-none"
          />
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 border border-zinc-700 text-xs"
            disabled={bulkLoading}
            onClick={() => handleBulkAction('dismiss')}
          >
            <XCircle className="h-3.5 w-3.5" />
            Dismiss
          </Button>
          <Button
            size="sm"
            className="h-7 gap-1.5 text-xs"
            disabled={bulkLoading}
            loading={bulkLoading}
            onClick={() => handleBulkAction('resolve_manually')}
          >
            <UserCheck className="h-3.5 w-3.5" />
            Resolve Manually
          </Button>
          <button
            onClick={() => setCheckedIds(new Set())}
            className="text-xs text-zinc-500 hover:text-zinc-300"
          >
            Clear selection
          </button>
        </div>
      )}
      {bulkError && (
        <div className="mx-4 mt-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {bulkError}
        </div>
      )}

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
              checkedIds={checkedIds}
              onToggleCheck={toggleCheck}
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
                onResolvedManually={handleResolvedManually}
                onAssigned={handleAssigned}
                readOnlyConnection={isReadOnlyBlocked(selected, connections)}
              />
            </div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
