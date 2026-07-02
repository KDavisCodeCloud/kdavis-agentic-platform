'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Linkedin, Twitter, Video, Clock, CheckCircle, XCircle,
  AlertTriangle, Loader2, Send, ThumbsUp, ThumbsDown,
  Edit3, BarChart2, Zap, RefreshCw, Plus,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Impact {
  tier: 'strong' | 'solid' | 'weak' | 'unknown'
  label: string
  description: string
  combined_score?: number
}

interface DraftSummary {
  id: string
  platform: string
  raw_idea: string
  goal: string
  status: string
  brand_voice_score: number | null
  brief_alignment_score: number | null
  brief_title: string | null
  impact: Impact
  created_at: string
  updated_at: string
}

interface DraftDetail extends DraftSummary {
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

interface Props {
  token: string
}

const MOCK_MODE = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_DRAFTS: DraftSummary[] = [
  {
    id: 'draft-001',
    platform: 'linkedin',
    raw_idea: 'Most engineering teams don't know how much time their on-call engineers spend triaging CI/CD failures before they can even start fixing them.',
    goal: 'education',
    status: 'pending_review',
    brand_voice_score: 9,
    brief_alignment_score: 8,
    brief_title: 'The hidden cost of CI/CD triage',
    impact: { tier: 'strong', label: 'Strong', description: 'High-quality hook and brief alignment. Estimated organic reach: 500–2,000 impressions. Directional only.', combined_score: 8.5 },
    created_at: new Date(Date.now() - 1000 * 60 * 8).toISOString(),
    updated_at: new Date(Date.now() - 1000 * 60 * 2).toISOString(),
  },
  {
    id: 'draft-002',
    platform: 'x',
    raw_idea: 'IAM policies are where cloud costs hide. Nobody audits them until something breaks.',
    goal: 'credibility',
    status: 'pending_review',
    brand_voice_score: 7,
    brief_alignment_score: 7,
    brief_title: 'IAM policy debt is a cost problem',
    impact: { tier: 'solid', label: 'Solid', description: 'Meets brand voice standards. Estimated organic reach: 50–300 impressions. Directional only.', combined_score: 7.0 },
    created_at: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
    updated_at: new Date(Date.now() - 1000 * 60 * 55).toISOString(),
  },
  {
    id: 'draft-003',
    platform: 'linkedin',
    raw_idea: 'What onboarding buddy agents actually do for new engineers on their first on-call rotation.',
    goal: 'awareness',
    status: 'published',
    brand_voice_score: 9,
    brief_alignment_score: 9,
    brief_title: 'First on-call rotation with an AI buddy',
    impact: { tier: 'strong', label: 'Strong', description: 'High-quality hook and brief alignment. Estimated organic reach: 500–2,000 impressions. Directional only.', combined_score: 9.0 },
    created_at: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(),
    updated_at: new Date(Date.now() - 1000 * 60 * 60 * 23).toISOString(),
  },
]

const MOCK_DETAIL: DraftDetail = {
  ...MOCK_DRAFTS[0],
  brief: {
    brief_title: 'The hidden cost of CI/CD triage',
    platform: 'linkedin',
    goal: 'education',
    hook_angle: 'Your senior engineers are spending 2 hours diagnosing a pipeline failure before writing a single line of fix.',
    key_message: 'The diagnosis phase of DevOps incidents is where the hours go — and it is automatable today.',
    supporting_points: [
      'Average CI/CD triage: 1.5–3 hours before a fix is even started',
      'Autonomous triage agents reduce that to under 10 minutes',
      'That is 6–12 engineer-hours per week returned to feature work',
    ],
    tone: 'direct',
    format: 'problem-solution',
    cta: 'Ask your on-call engineer how long their last triage took.',
    do_not_include: ['competitor names', 'unverified statistics', 'hype language'],
  },
  draft_output: {
    platform: 'linkedin',
    draft_a: {
      text: `Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.

Not fixing. Not shipping. Just triaging.

3 pipeline failures per week. 2 hours each. That is 6 engineer-hours before a single fix begins.

Autonomous triage agents cut that to under 10 minutes.

The diagnosis phase is the part nobody talks about. It is also the part that is fully automatable today.

Ask your on-call engineer: how long did your last triage take?

#DevOps #CloudEngineering #PlatformEngineering #SRE #CloudDecoded`,
      hook: 'Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.',
      word_count: 78,
      hashtags: ['#DevOps', '#CloudEngineering', '#PlatformEngineering', '#SRE', '#CloudDecoded'],
      engagement_prompt: 'Ask your on-call engineer: how long did your last triage take?',
    },
    draft_b: {
      text: `Nobody talks about the hour before the fix.

Your engineer gets paged. Pipeline is down. Now they spend the next 90 minutes figuring out what broke before they can write a single line of fix.

Multiply that by 3 failures a week. That is 4.5 hours of pure diagnosis — before any productive work starts.

We built an agent that does that diagnosis in under 10 minutes.

The fix still needs a human. The triage does not.

#DevOps #SRE #CloudDecoded #PlatformEngineering`,
      hook: 'Nobody talks about the hour before the fix.',
      word_count: 82,
      hashtags: ['#DevOps', '#SRE', '#CloudDecoded', '#PlatformEngineering'],
      engagement_prompt: 'The fix still needs a human. The triage does not.',
    },
    writer_notes: 'Draft A leads with the direct cost framing. Draft B leads with the narrative "hour before the fix" angle. Both execute the brief.',
  },
  review_output: {
    decision: 'approved',
    brand_voice_score: 9,
    brief_alignment_score: 8,
    flags: [],
    approved_draft: `Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.

Not fixing. Not shipping. Just triaging.

3 pipeline failures per week. 2 hours each. That is 6 engineer-hours before a single fix begins.

Autonomous triage agents cut that to under 10 minutes.

The diagnosis phase is the part nobody talks about. It is also the part that is fully automatable today.

Ask your on-call engineer: how long did your last triage take?

#DevOps #CloudEngineering #PlatformEngineering #SRE #CloudDecoded`,
    revision_notes: '',
  },
  publish_package: null,
  operator_edit: null,
  rejection_feedback: null,
  linkedin_post_id: null,
  x_post_id: null,
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  generating:    { label: 'Generating',    color: 'text-blue-400',   icon: Loader2 },
  pending_review:{ label: 'Needs Review',  color: 'text-amber-400',  icon: AlertTriangle },
  approved:      { label: 'Approved',      color: 'text-emerald-400', icon: CheckCircle },
  publishing:    { label: 'Publishing',    color: 'text-blue-400',   icon: Send },
  published:     { label: 'Published',     color: 'text-emerald-500', icon: CheckCircle },
  rejected:      { label: 'Rejected',      color: 'text-red-400',    icon: XCircle },
  failed:        { label: 'Failed',        color: 'text-red-400',    icon: XCircle },
}

const PLATFORM_ICON: Record<string, React.ElementType> = {
  linkedin: Linkedin,
  x:        Twitter,
  video:    Video,
}

const IMPACT_COLORS: Record<string, string> = {
  strong:  'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
  solid:   'text-blue-400 bg-blue-400/10 border-blue-400/20',
  weak:    'text-amber-400 bg-amber-400/10 border-amber-400/20',
  unknown: 'text-zinc-500 bg-zinc-500/10 border-zinc-500/20',
}

const SCORE_COLOR = (s: number | null) =>
  s === null ? 'text-zinc-600' :
  s >= 8 ? 'text-emerald-400' :
  s >= 6 ? 'text-blue-400' : 'text-amber-400'

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.generating
  const Icon = cfg.icon
  return (
    <span className={cn('flex items-center gap-1 text-xs font-medium', cfg.color)}>
      <Icon className={cn('h-3 w-3', status === 'generating' || status === 'publishing' ? 'animate-spin' : '')} />
      {cfg.label}
    </span>
  )
}

function ScoreBar({ label, score }: { label: string; score: number | null }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 text-xs text-zinc-500 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-zinc-800">
        {score !== null && (
          <div
            className={cn('h-1.5 rounded-full transition-all', SCORE_COLOR(score).replace('text-', 'bg-'))}
            style={{ width: `${score * 10}%` }}
          />
        )}
      </div>
      <span className={cn('w-5 text-right text-xs font-mono font-semibold', SCORE_COLOR(score))}>
        {score ?? '—'}
      </span>
    </div>
  )
}

function ImpactPanel({ impact }: { impact: Impact }) {
  return (
    <div className={cn('rounded-lg border p-3 space-y-1', IMPACT_COLORS[impact.tier])}>
      <div className="flex items-center gap-1.5">
        <BarChart2 className="h-3.5 w-3.5 shrink-0" />
        <span className="text-xs font-semibold">Predicted Impact: {impact.label}</span>
        {impact.combined_score !== undefined && (
          <span className="ml-auto text-xs font-mono opacity-70">{impact.combined_score}/10</span>
        )}
      </div>
      {impact.description && (
        <p className="text-xs opacity-80 leading-relaxed">{impact.description}</p>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ContentPipeline({ token }: Props) {
  const [drafts, setDrafts]           = useState<DraftSummary[]>([])
  const [selected, setSelected]       = useState<DraftDetail | null>(null)
  const [loading, setLoading]         = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [activeVariant, setActiveVariant] = useState<'draft_a' | 'draft_b'>('draft_a')
  const [editMode, setEditMode]       = useState(false)
  const [editText, setEditText]       = useState('')
  const [acting, setActing]           = useState(false)

  const fetchDrafts = useCallback(async () => {
    if (MOCK_MODE) {
      setDrafts(MOCK_DRAFTS)
      setLoading(false)
      return
    }
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/content/drafts`, {
        headers: { 'X-Workspace-Token': token },
      })
      if (res.ok) setDrafts(await res.json())
    } finally {
      setLoading(false)
    }
  }, [token])

  const fetchDetail = useCallback(async (id: string) => {
    if (MOCK_MODE) {
      setSelected(id === 'draft-001' ? MOCK_DETAIL : { ...MOCK_DRAFTS.find(d => d.id === id)! as DraftDetail, brief: null, draft_output: null, review_output: null, publish_package: null, operator_edit: null, rejection_feedback: null, linkedin_post_id: null, x_post_id: null })
      return
    }
    setDetailLoading(true)
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/content/drafts/${id}`, {
        headers: { 'X-Workspace-Token': token },
      })
      if (res.ok) setSelected(await res.json())
    } finally {
      setDetailLoading(false)
    }
  }, [token])

  useEffect(() => { fetchDrafts() }, [fetchDrafts])

  // Poll for generating drafts
  useEffect(() => {
    const hasGenerating = drafts.some(d => d.status === 'generating' || d.status === 'publishing')
    if (!hasGenerating) return
    const t = setTimeout(fetchDrafts, 5000)
    return () => clearTimeout(t)
  }, [drafts, fetchDrafts])

  async function handleApprove() {
    if (!selected || acting) return
    setActing(true)
    try {
      if (MOCK_MODE) {
        setDrafts(prev => prev.map(d => d.id === selected.id ? { ...d, status: 'published' } : d))
        setSelected(prev => prev ? { ...prev, status: 'published' } : null)
        return
      }
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/content/drafts/${selected.id}/approve`,
        {
          method: 'POST',
          headers: { 'X-Workspace-Token': token, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            selected_draft: activeVariant,
            operator_edit: editMode ? editText || undefined : undefined,
          }),
        }
      )
      if (res.ok) {
        await fetchDrafts()
        await fetchDetail(selected.id)
        setEditMode(false)
      }
    } finally {
      setActing(false)
    }
  }

  async function handleReject() {
    if (!selected || acting) return
    const feedback = window.prompt('Rejection feedback for the draft agent (what to improve):')
    if (!feedback) return
    setActing(true)
    try {
      if (MOCK_MODE) {
        setDrafts(prev => prev.map(d => d.id === selected.id ? { ...d, status: 'rejected' } : d))
        setSelected(prev => prev ? { ...prev, status: 'rejected' } : null)
        return
      }
      await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/v1/content/drafts/${selected.id}/reject`,
        {
          method: 'POST',
          headers: { 'X-Workspace-Token': token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ feedback }),
        }
      )
      await fetchDrafts()
      await fetchDetail(selected.id)
    } finally {
      setActing(false)
    }
  }

  const currentDraftText = selected?.draft_output
    ? (selected.draft_output[activeVariant]?.text ?? '')
    : ''

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left — Draft Queue */}
      <div className="w-64 shrink-0 flex flex-col border-r border-zinc-800 bg-zinc-950">
        <div className="flex h-10 items-center justify-between px-3 border-b border-zinc-800">
          <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Draft Queue</span>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={fetchDrafts} title="Refresh">
            <RefreshCw className="h-3 w-3" />
          </Button>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1 px-2 py-2 border-b border-zinc-800/50">
          {['All', 'Review', 'Done'].map(f => (
            <button key={f}
              className="flex-1 rounded px-1.5 py-1 text-xs text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors">
              {f}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-20">
              <Loader2 className="h-4 w-4 animate-spin text-zinc-600" />
            </div>
          ) : drafts.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 gap-2 px-4 text-center">
              <Plus className="h-6 w-6 text-zinc-700" />
              <p className="text-xs text-zinc-600">No drafts yet. Generate your first piece of content.</p>
            </div>
          ) : (
            drafts.map(draft => {
              const PlatformIcon = PLATFORM_ICON[draft.platform] ?? Zap
              const isSelected = selected?.id === draft.id
              return (
                <button
                  key={draft.id}
                  onClick={() => { fetchDetail(draft.id); setEditMode(false) }}
                  className={cn(
                    'w-full text-left px-3 py-3 border-b border-zinc-800/50 transition-colors',
                    isSelected ? 'bg-zinc-800' : 'hover:bg-zinc-900',
                  )}
                >
                  <div className="flex items-start gap-2 mb-1.5">
                    <PlatformIcon className="h-3.5 w-3.5 text-zinc-500 mt-0.5 shrink-0" />
                    <span className="text-xs text-zinc-300 font-medium leading-tight line-clamp-2">
                      {draft.brief_title ?? draft.raw_idea.slice(0, 60)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-1 mt-1.5">
                    <StatusBadge status={draft.status} />
                    <span className="text-xs text-zinc-600">{timeAgo(draft.updated_at)}</span>
                  </div>
                  {draft.impact.tier !== 'unknown' && (
                    <div className={cn('mt-1.5 text-xs font-medium', IMPACT_COLORS[draft.impact.tier].split(' ')[0])}>
                      {draft.impact.label}
                    </div>
                  )}
                </button>
              )
            })
          )}
        </div>
      </div>

      {/* Right — Detail Pane */}
      <div className="flex-1 overflow-y-auto bg-zinc-950">
        <AnimatePresence mode="wait">
          {detailLoading ? (
            <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex items-center justify-center h-48">
              <Loader2 className="h-5 w-5 animate-spin text-zinc-600" />
            </motion.div>
          ) : !selected ? (
            <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center h-full gap-3 text-zinc-600">
              <Zap className="h-8 w-8" />
              <p className="text-sm">Select a draft to review</p>
            </motion.div>
          ) : (
            <motion.div key={selected.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }} transition={{ duration: 0.15 }}
              className="p-5 space-y-5 max-w-3xl">

              {/* Header */}
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    {React.createElement(PLATFORM_ICON[selected.platform] ?? Zap, { className: 'h-4 w-4 text-zinc-400' })}
                    <span className="text-xs text-zinc-500 uppercase tracking-wider">{selected.platform}</span>
                    <span className="text-xs text-zinc-600">·</span>
                    <span className="text-xs text-zinc-500">{selected.goal}</span>
                  </div>
                  <h2 className="text-sm font-semibold text-zinc-100">
                    {(selected.brief as Record<string, string> | null)?.brief_title ?? 'Draft'}
                  </h2>
                  <p className="mt-1 text-xs text-zinc-500 leading-relaxed line-clamp-2">{selected.raw_idea}</p>
                </div>
                <StatusBadge status={selected.status} />
              </div>

              {/* Scores + Impact */}
              {selected.review_output && (
                <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4 space-y-3">
                  <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Quality Scores</p>
                  <ScoreBar label="Brand Voice" score={selected.brand_voice_score} />
                  <ScoreBar label="Brief Alignment" score={selected.brief_alignment_score} />
                  {selected.review_output.flags.length > 0 && (
                    <div className="mt-2 space-y-1.5">
                      {selected.review_output.flags.map((f, i) => (
                        <div key={i} className="flex gap-2 text-xs text-amber-400/80">
                          <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
                          <span><span className="font-medium">{f.type}:</span> "{f.quote}" — {f.reason}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <ImpactPanel impact={selected.impact} />

              {/* Draft variants */}
              {selected.draft_output && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Draft</p>
                    <div className="flex rounded-md overflow-hidden border border-zinc-800">
                      {(['draft_a', 'draft_b'] as const).map(v => (
                        <button key={v} onClick={() => { setActiveVariant(v); setEditMode(false) }}
                          className={cn(
                            'px-3 py-1 text-xs font-medium transition-colors',
                            activeVariant === v ? 'bg-zinc-700 text-zinc-100' : 'bg-zinc-900 text-zinc-500 hover:text-zinc-300'
                          )}>
                          {v === 'draft_a' ? 'A' : 'B'}
                        </button>
                      ))}
                    </div>
                    {selected.status === 'pending_review' && !editMode && (
                      <button onClick={() => { setEditMode(true); setEditText(currentDraftText) }}
                        className="ml-auto flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300">
                        <Edit3 className="h-3 w-3" /> Edit before approving
                      </button>
                    )}
                  </div>

                  {editMode ? (
                    <textarea
                      value={editText}
                      onChange={e => setEditText(e.target.value)}
                      className="w-full rounded-lg border border-blue-500/50 bg-zinc-900 p-3 text-sm text-zinc-100 leading-relaxed resize-none focus:outline-none focus:ring-1 focus:ring-blue-500/50"
                      rows={12}
                    />
                  ) : (
                    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
                      <p className="text-xs text-zinc-200 leading-relaxed whitespace-pre-wrap">{currentDraftText}</p>
                      {selected.draft_output[activeVariant]?.hashtags?.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-1">
                          {selected.draft_output[activeVariant].hashtags.map(h => (
                            <span key={h} className="text-xs text-blue-400/70">{h}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {selected.draft_output.writer_notes && (
                    <p className="text-xs text-zinc-600 italic">Writer notes: {selected.draft_output.writer_notes}</p>
                  )}
                </div>
              )}

              {/* Published result */}
              {selected.status === 'published' && (selected.linkedin_post_id || selected.x_post_id) && (
                <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 flex items-center gap-2">
                  <CheckCircle className="h-4 w-4 text-emerald-400 shrink-0" />
                  <span className="text-xs text-emerald-400">
                    Published — post ID: {selected.linkedin_post_id ?? selected.x_post_id}
                  </span>
                </div>
              )}

              {/* Actions */}
              {selected.status === 'pending_review' && (
                <div className="flex gap-2 pt-1">
                  <Button
                    onClick={handleApprove}
                    disabled={acting}
                    className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs h-8 px-4"
                  >
                    {acting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ThumbsUp className="h-3.5 w-3.5" />}
                    {editMode ? 'Approve with edits' : `Approve ${activeVariant === 'draft_a' ? 'A' : 'B'}`}
                  </Button>
                  {editMode && (
                    <Button variant="ghost" onClick={() => setEditMode(false)}
                      className="text-xs h-8 px-3 text-zinc-400">
                      Cancel edit
                    </Button>
                  )}
                  <Button
                    onClick={handleReject}
                    disabled={acting}
                    variant="ghost"
                    className="flex items-center gap-1.5 text-red-400 hover:text-red-300 hover:bg-red-400/10 text-xs h-8 px-3 ml-auto"
                  >
                    <ThumbsDown className="h-3.5 w-3.5" />
                    Reject
                  </Button>
                </div>
              )}

            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
