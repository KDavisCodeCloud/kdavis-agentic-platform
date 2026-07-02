'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  UserPlus, ExternalLink, Copy, CheckCircle2, AlertTriangle,
  Clock, XCircle, Loader2, ChevronRight, Users, TrendingUp,
  BarChart3, Plus, X,
} from 'lucide-react'
import {
  listLeads, getLead, createLead, markLeadSent, updateLeadStatus, getOutreachPacing,
  type OutreachLeadSummary, type OutreachLeadDetail, type PacingStatus, type OutreachLeadCreate,
} from '@/lib/api'

const POLL_INTERVAL = 5000

// ── Status helpers ────────────────────────────────────────────────────────────

const STATUS_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  new:          { label: 'New',          color: 'text-zinc-400 bg-zinc-800',           icon: <Clock className="w-3 h-3" /> },
  qualifying:   { label: 'Analyzing',   color: 'text-blue-400 bg-blue-900/40',         icon: <Loader2 className="w-3 h-3 animate-spin" /> },
  qualified:    { label: 'Ready',        color: 'text-green-400 bg-green-900/40',       icon: <CheckCircle2 className="w-3 h-3" /> },
  disqualified: { label: 'Not a fit',   color: 'text-zinc-500 bg-zinc-800/60',         icon: <XCircle className="w-3 h-3" /> },
  ready_to_send:{ label: 'Send today',  color: 'text-amber-400 bg-amber-900/40',       icon: <ChevronRight className="w-3 h-3" /> },
  sent:         { label: 'Sent',        color: 'text-purple-400 bg-purple-900/40',     icon: <UserPlus className="w-3 h-3" /> },
  accepted:     { label: 'Accepted',    color: 'text-green-400 bg-green-900/40',       icon: <CheckCircle2 className="w-3 h-3" /> },
  declined:     { label: 'Declined',    color: 'text-red-400 bg-red-900/40',           icon: <XCircle className="w-3 h-3" /> },
  no_response:  { label: 'No response', color: 'text-zinc-500 bg-zinc-800/60',         icon: <Clock className="w-3 h-3" /> },
}

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? STATUS_META['new']
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${meta.color}`}>
      {meta.icon}
      {meta.label}
    </span>
  )
}

function ScoreBar({ score, label }: { score: number; label: string }) {
  const pct = Math.round((score / 10) * 100)
  const color = score >= 8 ? 'bg-green-500' : score >= 6 ? 'bg-amber-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-zinc-400 w-20 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
        <motion.div
          className={`h-full rounded-full ${color}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
      <span className="text-xs text-zinc-300 w-6 text-right">{score}</span>
    </div>
  )
}

function PacingBar({ label, sent, warn, limit, pct, warning, atLimit }: {
  label: string; sent: number; warn: number; limit: number
  pct: number; warning: boolean; atLimit: boolean
}) {
  const barColor = atLimit ? 'bg-red-500' : warning ? 'bg-amber-500' : 'bg-green-500'
  return (
    <div className="space-y-1">
      <div className="flex justify-between items-baseline">
        <span className="text-xs text-zinc-400">{label}</span>
        <span className={`text-xs font-medium ${atLimit ? 'text-red-400' : warning ? 'text-amber-400' : 'text-zinc-300'}`}>
          {sent} / {limit}
        </span>
      </div>
      <div className="h-2 bg-zinc-700 rounded-full overflow-hidden relative">
        <motion.div
          className={`h-full rounded-full ${barColor}`}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(pct * 100, 100)}%` }}
          transition={{ duration: 0.5 }}
        />
        {/* warn marker */}
        <div
          className="absolute top-0 bottom-0 w-px bg-zinc-500/60"
          style={{ left: `${Math.round((warn / limit) * 100)}%` }}
        />
      </div>
    </div>
  )
}

// ── Add lead form ─────────────────────────────────────────────────────────────

const EMPTY_FORM: OutreachLeadCreate = {
  lead_name: '', company: '', role: '', team_size: '', cloud_provider: '',
  pain_points: '', how_they_found_us: '', linkedin_url: '', additional_context: '',
}

function AddLeadModal({ onClose, onSubmit }: {
  onClose: () => void
  onSubmit: (body: OutreachLeadCreate) => Promise<void>
}) {
  const [form, setForm] = useState<OutreachLeadCreate>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = (k: keyof OutreachLeadCreate) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await onSubmit(form)
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to add lead')
      setSubmitting(false)
    }
  }

  const inputCls = "w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
  const labelCls = "block text-xs text-zinc-400 mb-1"

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <motion.div
        className="bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto"
        initial={{ opacity: 0, scale: 0.96, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 16 }}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-700">
          <h2 className="text-sm font-semibold text-zinc-100">Add lead to pipeline</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Name *</label>
              <input className={inputCls} value={form.lead_name} onChange={set('lead_name')} placeholder="Marcus Chen" required />
            </div>
            <div>
              <label className={labelCls}>Company *</label>
              <input className={inputCls} value={form.company} onChange={set('company')} placeholder="Meridian Health" required />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Role *</label>
              <input className={inputCls} value={form.role} onChange={set('role')} placeholder="VP Engineering" required />
            </div>
            <div>
              <label className={labelCls}>Team size *</label>
              <input className={inputCls} value={form.team_size} onChange={set('team_size')} placeholder="50-200" required />
            </div>
          </div>
          <div>
            <label className={labelCls}>Cloud provider(s) *</label>
            <input className={inputCls} value={form.cloud_provider} onChange={set('cloud_provider')} placeholder="AWS + Azure" required />
          </div>
          <div>
            <label className={labelCls}>Pain points *</label>
            <textarea className={`${inputCls} resize-none`} rows={2} value={form.pain_points} onChange={set('pain_points')} placeholder="Manual deployment pipelines consuming 20+ hrs/week..." required />
          </div>
          <div>
            <label className={labelCls}>How they found us</label>
            <input className={inputCls} value={form.how_they_found_us} onChange={set('how_they_found_us')} placeholder="LinkedIn post, conference, referral…" />
          </div>
          <div>
            <label className={labelCls}>LinkedIn URL</label>
            <input className={inputCls} value={form.linkedin_url} onChange={set('linkedin_url')} placeholder="https://linkedin.com/in/…" />
          </div>
          <div>
            <label className={labelCls}>Additional context</label>
            <textarea className={`${inputCls} resize-none`} rows={2} value={form.additional_context} onChange={set('additional_context')} placeholder="SOC2 compliance push, budget opens Q4…" />
          </div>
          {error && (
            <div className="bg-red-900/30 border border-red-700/40 rounded p-2 text-xs text-red-300">{error}</div>
          )}
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={onClose} className="flex-1 px-3 py-2 rounded text-sm text-zinc-300 border border-zinc-700 hover:bg-zinc-800 transition-colors">
              Cancel
            </button>
            <button type="submit" disabled={submitting} className="flex-1 px-3 py-2 rounded text-sm font-medium bg-zinc-100 text-zinc-900 hover:bg-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2">
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              {submitting ? 'Analyzing…' : 'Add lead'}
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  )
}

// ── Pacing panel ──────────────────────────────────────────────────────────────

function PacingPanel({ pacing }: { pacing: PacingStatus }) {
  const rate = pacing.acceptance_rate !== null ? `${Math.round(pacing.acceptance_rate * 100)}%` : 'N/A'
  const rateColor = pacing.acceptance_rate_warning
    ? 'text-amber-400'
    : pacing.acceptance_rate !== null && pacing.acceptance_rate >= 0.3
    ? 'text-green-400'
    : 'text-zinc-300'

  return (
    <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-4 space-y-4">
      <div className="flex items-center gap-2">
        <BarChart3 className="w-4 h-4 text-zinc-400" />
        <span className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">Pacing</span>
        {(pacing.daily_at_limit || pacing.weekly_at_limit) && (
          <span className="ml-auto text-xs text-red-400 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Limit reached
          </span>
        )}
        {!pacing.daily_at_limit && !pacing.weekly_at_limit && (pacing.daily_warning || pacing.weekly_warning) && (
          <span className="ml-auto text-xs text-amber-400 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> Approaching limit
          </span>
        )}
      </div>
      <div className="space-y-3">
        <PacingBar
          label="Today"
          sent={pacing.daily_sent} warn={pacing.daily_warn} limit={pacing.daily_limit}
          pct={pacing.daily_pct} warning={pacing.daily_warning} atLimit={pacing.daily_at_limit}
        />
        <PacingBar
          label="This week"
          sent={pacing.weekly_sent} warn={pacing.weekly_warn} limit={pacing.weekly_limit}
          pct={pacing.weekly_pct} warning={pacing.weekly_warning} atLimit={pacing.weekly_at_limit}
        />
      </div>
      <div className="flex items-center gap-4 pt-1 border-t border-zinc-800">
        <div className="flex-1 text-center">
          <div className={`text-lg font-bold ${rateColor}`}>{rate}</div>
          <div className="text-xs text-zinc-500">acceptance rate</div>
        </div>
        <div className="flex-1 text-center">
          <div className="text-lg font-bold text-zinc-100">{pacing.total_sent}</div>
          <div className="text-xs text-zinc-500">total sent</div>
        </div>
        <div className="flex-1 text-center">
          <div className="text-lg font-bold text-green-400">{pacing.total_accepted}</div>
          <div className="text-xs text-zinc-500">accepted</div>
        </div>
      </div>
      {(pacing.daily_at_limit || pacing.weekly_at_limit || pacing.acceptance_rate_warning) && (
        <div className={`text-xs px-3 py-2 rounded ${pacing.daily_at_limit || pacing.weekly_at_limit ? 'bg-red-900/30 border border-red-700/40 text-red-300' : 'bg-amber-900/30 border border-amber-700/40 text-amber-300'}`}>
          {pacing.message}
        </div>
      )}
    </div>
  )
}

// ── Lead detail panel ─────────────────────────────────────────────────────────

function LeadDetail({ lead, token, onStatusChange }: {
  lead: OutreachLeadDetail
  token: string
  onStatusChange: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [marking, setMarking] = useState(false)
  const [updatingStatus, setUpdatingStatus] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const copyNote = async () => {
    if (!lead.connection_note) return
    await navigator.clipboard.writeText(lead.connection_note)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const openLinkedIn = () => {
    window.open(lead.linkedin_search_url, '_blank', 'noopener,noreferrer')
  }

  const handleMarkSent = async () => {
    setError(null)
    setMarking(true)
    try {
      await markLeadSent(token, lead.id)
      onStatusChange()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to mark sent')
    } finally {
      setMarking(false)
    }
  }

  const handleStatus = async (status: string) => {
    setError(null)
    setUpdatingStatus(true)
    try {
      await updateLeadStatus(token, lead.id, status)
      onStatusChange()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to update status')
    } finally {
      setUpdatingStatus(false)
    }
  }

  const canSend = lead.status === 'qualified' || lead.status === 'ready_to_send'
  const canUpdateStatus = lead.status === 'sent'
  const noteCharCount = lead.connection_note?.length ?? 0

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-zinc-100">{lead.lead_name}</h2>
        <p className="text-sm text-zinc-400">{lead.role} · {lead.company}</p>
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          <StatusBadge status={lead.status} />
          {lead.fit_score !== null && (
            <span className="text-xs text-zinc-400">ICP score: <span className="text-zinc-200 font-medium">{lead.fit_score}/10</span></span>
          )}
          {lead.tier_recommendation && (
            <span className="text-xs text-zinc-400">Tier: <span className="text-zinc-200 font-medium capitalize">{lead.tier_recommendation}</span></span>
          )}
        </div>
      </div>

      {/* Connection note — the core of Phase 3 */}
      {lead.connection_note ? (
        <div className="bg-zinc-800/60 border border-zinc-700 rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">Connection note</span>
            <span className={`text-xs ${noteCharCount > 270 ? 'text-amber-400' : 'text-zinc-500'}`}>{noteCharCount}/300</span>
          </div>
          <p className="text-sm text-zinc-200 leading-relaxed">{lead.connection_note}</p>
          <div className="flex gap-2 pt-1">
            <button
              onClick={copyNote}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-zinc-700 hover:bg-zinc-600 text-zinc-200 transition-colors"
            >
              {copied ? <CheckCircle2 className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
              {copied ? 'Copied' : 'Copy note'}
            </button>
            <button
              onClick={openLinkedIn}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-zinc-700 hover:bg-zinc-600 text-zinc-200 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              Find on LinkedIn
            </button>
          </div>
          <p className="text-xs text-zinc-500 leading-relaxed">
            Copy the note above, then open LinkedIn in your browser. Send manually — this system never sends on your behalf.
          </p>
        </div>
      ) : lead.status === 'qualifying' ? (
        <div className="bg-zinc-800/40 border border-zinc-700/60 rounded-xl p-4 flex items-center gap-3">
          <Loader2 className="w-4 h-4 text-blue-400 animate-spin shrink-0" />
          <span className="text-sm text-zinc-400">Agents are analyzing this lead — check back in a moment.</span>
        </div>
      ) : null}

      {/* Scores */}
      {lead.fit_score !== null && (
        <div className="space-y-2">
          <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">ICP fit</span>
          <ScoreBar score={lead.fit_score} label="Overall fit" />
        </div>
      )}

      {/* ICP matches */}
      {lead.icp_matches.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Signals</p>
          <div className="flex flex-wrap gap-1.5">
            {lead.icp_matches.map((m, i) => (
              <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-green-900/30 text-green-300 border border-green-800/40">{m}</span>
            ))}
          </div>
        </div>
      )}

      {/* Disqualifiers */}
      {lead.disqualifiers.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Disqualifiers</p>
          <div className="flex flex-wrap gap-1.5">
            {lead.disqualifiers.map((d, i) => (
              <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-red-900/30 text-red-300 border border-red-800/40">{d}</span>
            ))}
          </div>
        </div>
      )}

      {/* Talk track */}
      {lead.talk_track && (
        <div className="bg-zinc-800/40 rounded-lg p-3">
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1.5">Talk track</p>
          <p className="text-xs text-zinc-300 leading-relaxed">{lead.talk_track}</p>
        </div>
      )}

      {/* ROI estimate */}
      {(lead.estimated_monthly_hours_saved || lead.estimated_monthly_value_usd) && (
        <div className="grid grid-cols-2 gap-3">
          {lead.estimated_monthly_hours_saved && (
            <div className="bg-zinc-800/40 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-zinc-100">{lead.estimated_monthly_hours_saved}h</div>
              <div className="text-xs text-zinc-500">est. monthly savings</div>
            </div>
          )}
          {lead.estimated_monthly_value_usd && (
            <div className="bg-zinc-800/40 rounded-lg p-3 text-center">
              <div className="text-lg font-bold text-zinc-100">${lead.estimated_monthly_value_usd.toLocaleString()}</div>
              <div className="text-xs text-zinc-500">est. monthly value</div>
            </div>
          )}
        </div>
      )}

      {/* Risk areas */}
      {lead.risk_areas.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Risk areas</p>
          <ul className="space-y-1">
            {lead.risk_areas.map((r, i) => (
              <li key={i} className="text-xs text-zinc-400 flex items-start gap-1.5">
                <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0 mt-0.5" />
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Actions */}
      {error && (
        <div className="bg-red-900/30 border border-red-700/40 rounded p-2 text-xs text-red-300">{error}</div>
      )}

      {canSend && (
        <button
          onClick={handleMarkSent}
          disabled={marking}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium bg-zinc-100 text-zinc-900 hover:bg-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {marking ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
          {marking ? 'Marking…' : 'Mark as sent'}
        </button>
      )}

      {canUpdateStatus && (
        <div className="space-y-2">
          <p className="text-xs text-zinc-500">Update connection result:</p>
          <div className="flex gap-2">
            <button onClick={() => handleStatus('accepted')} disabled={updatingStatus} className="flex-1 px-3 py-2 rounded text-xs font-medium bg-green-900/40 text-green-300 border border-green-800/40 hover:bg-green-900/60 disabled:opacity-50 transition-colors">
              Accepted
            </button>
            <button onClick={() => handleStatus('declined')} disabled={updatingStatus} className="flex-1 px-3 py-2 rounded text-xs font-medium bg-red-900/40 text-red-300 border border-red-800/40 hover:bg-red-900/60 disabled:opacity-50 transition-colors">
              Declined
            </button>
            <button onClick={() => handleStatus('no_response')} disabled={updatingStatus} className="flex-1 px-3 py-2 rounded text-xs font-medium bg-zinc-800 text-zinc-400 border border-zinc-700 hover:bg-zinc-700 disabled:opacity-50 transition-colors">
              No reply
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function OutreachPipeline({ token }: { token: string }) {
  const [leads, setLeads] = useState<OutreachLeadSummary[]>([])
  const [pacing, setPacing] = useState<PacingStatus | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<OutreachLeadDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [showAddModal, setShowAddModal] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchLeads = useCallback(async () => {
    try {
      const [ls, p] = await Promise.all([listLeads(token), getOutreachPacing(token)])
      setLeads(ls)
      setPacing(p)
    } catch {
      // silently suppress poll errors
    }
  }, [token])

  const fetchDetail = useCallback(async (id: string) => {
    setLoadingDetail(true)
    setDetailError(null)
    try {
      const d = await getLead(token, id)
      setDetail(d)
    } catch (err: unknown) {
      setDetailError(err instanceof Error ? err.message : 'Failed to load lead')
    } finally {
      setLoadingDetail(false)
    }
  }, [token])

  useEffect(() => {
    fetchLeads()
  }, [fetchLeads])

  // Poll while any lead is still qualifying
  useEffect(() => {
    const hasActive = leads.some(l => l.status === 'qualifying' || l.status === 'new')
    if (hasActive && !pollRef.current) {
      pollRef.current = setInterval(fetchLeads, POLL_INTERVAL)
    } else if (!hasActive && pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    }
  }, [leads, fetchLeads])

  // Also poll detail if it's still qualifying
  useEffect(() => {
    if (!selectedId || !detail) return
    if (detail.status !== 'qualifying' && detail.status !== 'new') return
    const t = setInterval(() => fetchDetail(selectedId), POLL_INTERVAL)
    return () => clearInterval(t)
  }, [selectedId, detail, fetchDetail])

  const handleSelect = (id: string) => {
    setSelectedId(id)
    setDetail(null)
    fetchDetail(id)
  }

  const handleStatusChange = () => {
    fetchLeads()
    if (selectedId) fetchDetail(selectedId)
  }

  const handleAddLead = async (body: OutreachLeadCreate) => {
    await createLead(token, body)
    await fetchLeads()
  }

  return (
    <div className="flex h-full min-h-0">
      {/* Left panel — lead queue */}
      <div className="w-64 shrink-0 flex flex-col border-r border-zinc-800 h-full overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <Users className="w-4 h-4 text-zinc-400" />
            <span className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">Leads</span>
            <span className="text-xs text-zinc-500">({leads.length})</span>
          </div>
          <button
            onClick={() => setShowAddModal(true)}
            className="w-6 h-6 flex items-center justify-center rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {leads.length === 0 ? (
            <div className="p-4 text-center">
              <Users className="w-6 h-6 text-zinc-600 mx-auto mb-2" />
              <p className="text-xs text-zinc-500">No leads yet.</p>
              <button onClick={() => setShowAddModal(true)} className="mt-2 text-xs text-zinc-400 hover:text-zinc-200 underline">Add first lead</button>
            </div>
          ) : (
            leads.map(lead => (
              <button
                key={lead.id}
                onClick={() => handleSelect(lead.id)}
                className={`w-full text-left px-4 py-3 border-b border-zinc-800/60 hover:bg-zinc-800/40 transition-colors ${selectedId === lead.id ? 'bg-zinc-800/60' : ''}`}
              >
                <div className="flex items-start justify-between gap-1 mb-1">
                  <span className="text-xs font-medium text-zinc-200 truncate">{lead.lead_name}</span>
                  {lead.fit_score !== null && (
                    <span className={`text-xs font-bold shrink-0 ${lead.fit_score >= 8 ? 'text-green-400' : lead.fit_score >= 6 ? 'text-amber-400' : 'text-red-400'}`}>
                      {lead.fit_score}
                    </span>
                  )}
                </div>
                <p className="text-xs text-zinc-500 truncate mb-1.5">{lead.company}</p>
                <StatusBadge status={lead.status} />
              </button>
            ))
          )}
        </div>
      </div>

      {/* Right panel — detail + pacing */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Pacing always visible */}
          {pacing && <PacingPanel pacing={pacing} />}

          {/* Detail */}
          {selectedId && (
            <div className="bg-zinc-900/40 border border-zinc-800 rounded-xl p-5">
              {loadingDetail ? (
                <div className="flex items-center gap-3 text-zinc-400">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span className="text-sm">Loading…</span>
                </div>
              ) : detailError ? (
                <div className="text-sm text-red-400">{detailError}</div>
              ) : detail ? (
                <LeadDetail lead={detail} token={token} onStatusChange={handleStatusChange} />
              ) : null}
            </div>
          )}

          {!selectedId && pacing && leads.length > 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <TrendingUp className="w-8 h-8 text-zinc-600 mb-3" />
              <p className="text-sm text-zinc-400">Select a lead to view the connection note and pipeline outputs.</p>
            </div>
          )}

          {!selectedId && leads.length === 0 && !pacing && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <Users className="w-8 h-8 text-zinc-600 mb-3" />
              <p className="text-sm text-zinc-400">Add your first lead to start the outreach pipeline.</p>
              <button onClick={() => setShowAddModal(true)} className="mt-3 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-sm text-zinc-200 transition-colors flex items-center gap-2">
                <Plus className="w-4 h-4" /> Add lead
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Add lead modal */}
      <AnimatePresence>
        {showAddModal && (
          <AddLeadModal
            onClose={() => setShowAddModal(false)}
            onSubmit={handleAddLead}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
