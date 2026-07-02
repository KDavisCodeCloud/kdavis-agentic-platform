'use client'

import React, { useState } from 'react'
import {
  Users, FileText, Wrench,
  CheckCircle2, AlertTriangle, Clock,
  ChevronRight, Info,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import {
  MOCK_SALES_DATA,
  MOCK_CONTENT_DATA,
  MOCK_DEVOPS_OPS_DATA,
} from '@/lib/mock-data'

type OpsTab = 'sales' | 'content' | 'devops'

const OPS_TABS: { id: OpsTab; label: string; icon: React.ElementType }[] = [
  { id: 'sales',   label: 'Sales Pipeline',   icon: Users },
  { id: 'content', label: 'Content Pipeline', icon: FileText },
  { id: 'devops',  label: 'DevOps Ops',       icon: Wrench },
]

// ── Shared helpers ────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
      {children}
    </p>
  )
}

function InfoBox({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('rounded-lg border border-zinc-800 bg-zinc-950 p-3', className)}>
      {children}
    </div>
  )
}

function SeverityBadge({ sev }: { sev: string }) {
  const map: Record<string, { variant: 'danger' | 'warning' | 'pending' | 'muted'; label: string }> = {
    CRITICAL: { variant: 'danger',   label: 'CRITICAL' },
    HIGH:     { variant: 'warning',  label: 'HIGH' },
    MEDIUM:   { variant: 'pending',  label: 'MEDIUM' },
    LOW:      { variant: 'muted',    label: 'LOW' },
    critical: { variant: 'danger',   label: 'CRITICAL' },
    high:     { variant: 'warning',  label: 'HIGH' },
    medium:   { variant: 'pending',  label: 'MEDIUM' },
    low:      { variant: 'muted',    label: 'LOW' },
  }
  const m = map[sev] ?? { variant: 'muted' as const, label: sev.toUpperCase() }
  return <Badge variant={m.variant}>{m.label}</Badge>
}

interface SidebarStage {
  id: string
  label: string
  sublabel: string
  done?: boolean
}

function StageSidebar({
  header,
  stages,
  selected,
  onSelect,
  footer,
}: {
  header: React.ReactNode
  stages: SidebarStage[]
  selected: string
  onSelect: (id: string) => void
  footer?: React.ReactNode
}) {
  return (
    <div className="w-56 shrink-0 overflow-y-auto border-r border-zinc-800 p-4 space-y-4">
      {header}
      <div className="space-y-1.5">
        {stages.map((s, i) => (
          <div key={s.id}>
            <button
              onClick={() => onSelect(s.id)}
              className={cn(
                'w-full rounded-lg border p-3 text-left transition-all',
                selected === s.id
                  ? 'border-blue-500/50 bg-blue-500/10'
                  : 'border-zinc-800 bg-zinc-950 hover:border-zinc-700 hover:bg-zinc-900/60',
              )}
            >
              <div className="flex items-center gap-2">
                <CheckCircle2
                  className={cn(
                    'h-3.5 w-3.5 shrink-0',
                    s.done !== false ? 'text-emerald-400' : 'text-zinc-700',
                  )}
                />
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium text-zinc-100">{s.label}</p>
                  <p className="truncate text-xs text-zinc-600">{s.sublabel}</p>
                </div>
              </div>
            </button>
            {i < stages.length - 1 && (
              <div className="flex justify-center py-0.5">
                <div className={cn('h-3 w-px', s.done !== false ? 'bg-emerald-700' : 'bg-zinc-800')} />
              </div>
            )}
          </div>
        ))}
      </div>
      {footer}
    </div>
  )
}

function DetailPane({ stageKey, children }: { stageKey: string; children: React.ReactNode }) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={stageKey}
        initial={{ opacity: 0, x: 10 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -10 }}
        transition={{ duration: 0.15 }}
        className="flex-1 overflow-y-auto p-5"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  )
}

// ── Sales Pipeline ────────────────────────────────────────────────────

type SalesStage = 'qualify' | 'assess' | 'propose'

function QualifyDetail() {
  const { lead, qualify } = MOCK_SALES_DATA
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Lead Qualification</h3>
          <p className="text-xs text-zinc-500">{lead.name} · {lead.company}</p>
        </div>
        <Badge variant="success">Qualified</Badge>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-1">Fit Score</p>
          <p className="text-2xl font-bold text-emerald-400">{qualify.fit_score}<span className="text-sm text-zinc-600">/10</span></p>
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-1">Recommended Tier</p>
          <p className="text-sm font-semibold text-blue-400 capitalize">{qualify.tier_recommendation}</p>
          <p className="text-xs text-zinc-600 mt-0.5">$699/month</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>ICP Matches</SectionLabel>
        <div className="space-y-1.5">
          {qualify.icp_matches.map((m, i) => (
            <div key={i} className="flex items-center gap-2 text-xs text-zinc-300">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
              {m}
            </div>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Recommended Action</SectionLabel>
        <Badge variant="active" className="mb-2">Book Discovery Call</Badge>
        <InfoBox className="mt-2">
          <p className="text-xs font-semibold text-zinc-400 mb-1">Talk Track</p>
          <p className="text-xs leading-relaxed text-zinc-300">{qualify.talk_track}</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Agent Reasoning</SectionLabel>
        <p className="text-xs leading-relaxed text-zinc-400 italic">{qualify.reasoning}</p>
      </div>
    </div>
  )
}

function AssessDetail() {
  const { assess } = MOCK_SALES_DATA
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Infrastructure Assessment</h3>
          <p className="text-xs text-zinc-500">{assess.assessment_title}</p>
        </div>
        <Badge variant="default">Confidence {Math.round(assess.confidence * 100)}%</Badge>
      </div>

      <InfoBox>
        <p className="text-xs leading-relaxed text-zinc-300">{assess.executive_summary}</p>
      </InfoBox>

      <div className="grid grid-cols-2 gap-3">
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-1">Hours Saved/Month</p>
          <p className="text-2xl font-bold text-blue-400">{assess.estimated_monthly_hours_saved}<span className="text-sm text-zinc-600"> hrs</span></p>
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-1">Monthly Value</p>
          <p className="text-2xl font-bold text-emerald-400">${(assess.estimated_monthly_value_usd / 1000).toFixed(1)}k</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Risk Areas</SectionLabel>
        <div className="space-y-2">
          {assess.risk_areas.map((r, i) => (
            <InfoBox key={i}>
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs font-medium text-zinc-100">{r.area}</p>
                <SeverityBadge sev={r.severity} />
              </div>
              <p className="text-xs text-zinc-400">{r.description}</p>
              <p className="mt-1 text-xs text-zinc-600 italic">Impact: {r.impact_if_ignored}</p>
            </InfoBox>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Quick Wins</SectionLabel>
        <div className="space-y-2">
          {assess.quick_wins.map((w, i) => (
            <div key={i} className="flex items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-xs font-medium text-zinc-100">{w.action}</p>
                <p className="text-xs text-zinc-500">{w.impact}</p>
                <span className="mt-1 inline-block rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-zinc-400">{w.agent_id}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ProposeDetail() {
  const { propose } = MOCK_SALES_DATA
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Proposal Draft</h3>
          <p className="text-xs text-zinc-500">{propose.prepared_for}</p>
        </div>
        <Badge variant="pending">Ready for Review</Badge>
      </div>

      <InfoBox>
        <p className="text-xs leading-relaxed text-zinc-300">{propose.executive_summary}</p>
      </InfoBox>

      <div className="grid grid-cols-2 gap-3">
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-1">Recommended Tier</p>
          <p className="text-sm font-semibold text-blue-400 capitalize">{propose.recommended_tier}</p>
          <p className="text-lg font-bold text-zinc-100 mt-0.5">{propose.monthly_investment}</p>
        </InfoBox>
        <InfoBox className="border-emerald-500/20 bg-emerald-500/5">
          <p className="text-xs text-zinc-500 mb-1">Projected ROI</p>
          <p className="text-2xl font-bold text-emerald-400">13.7×</p>
          <p className="text-xs text-zinc-500 mt-0.5">recovered productivity</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>ROI Case</SectionLabel>
        <InfoBox>
          <p className="text-xs leading-relaxed text-zinc-300">{propose.roi_case}</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Agent Breakdown</SectionLabel>
        <div className="space-y-2">
          {propose.agent_breakdown.map((a, i) => (
            <InfoBox key={i}>
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs font-medium text-zinc-100">{a.agent_name}</p>
                <span className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-zinc-400">{a.agent_id}</span>
              </div>
              <p className="text-xs text-zinc-400">{a.use_case}</p>
              <p className="mt-1 text-xs text-emerald-400">{a.expected_outcome}</p>
            </InfoBox>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Next Steps</SectionLabel>
        <div className="space-y-1.5">
          {propose.next_steps.map((s, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-zinc-300">
              <span className="shrink-0 rounded-full bg-zinc-800 px-1.5 py-0.5 text-xs font-bold text-zinc-400">{i + 1}</span>
              {s}
            </div>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Customize Flags</SectionLabel>
        {propose.customize_flags.map((f, i) => (
          <div key={i} className="mb-1.5 flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/5 px-2.5 py-2 text-xs text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-400" />
            {f}
          </div>
        ))}
      </div>
    </div>
  )
}

function SalesPanel() {
  const [stage, setStage] = useState<SalesStage>('qualify')
  const { lead } = MOCK_SALES_DATA

  const stages: SidebarStage[] = [
    { id: 'qualify', label: 'Qualify Lead',   sublabel: 'Fit score · tier · action' },
    { id: 'assess',  label: 'Assess Infra',   sublabel: '3 risk areas · quick wins' },
    { id: 'propose', label: 'Proposal Draft', sublabel: '$699/mo · 13.7× ROI' },
  ]

  const header = (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">Active Lead</p>
      <p className="text-sm font-medium text-zinc-100">{lead.name}</p>
      <p className="text-xs text-zinc-500">{lead.role}</p>
      <p className="text-xs text-zinc-500">{lead.company}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <span className="rounded border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-xs text-blue-400">{lead.cloud_provider}</span>
        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">{lead.team_size} eng</span>
      </div>
    </div>
  )

  const footer = (
    <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
      <p className="text-xs font-semibold text-emerald-400">Pipeline Complete</p>
      <p className="mt-1 text-xs text-zinc-500">Proposal ready for Kelvin's review.</p>
    </div>
  )

  return (
    <div className="flex h-full overflow-hidden">
      <StageSidebar header={header} stages={stages} selected={stage} onSelect={id => setStage(id as SalesStage)} footer={footer} />
      <DetailPane stageKey={stage}>
        {stage === 'qualify' && <QualifyDetail />}
        {stage === 'assess'  && <AssessDetail />}
        {stage === 'propose' && <ProposeDetail />}
      </DetailPane>
    </div>
  )
}

// ── Content Pipeline ──────────────────────────────────────────────────

type ContentStage = 'brief' | 'draft' | 'review' | 'publish'

function BriefDetail() {
  const { brief } = MOCK_CONTENT_DATA
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">{brief.brief_title}</h3>
          <div className="mt-1 flex gap-1.5">
            <Badge variant="default">{brief.platform}</Badge>
            <Badge variant="muted">{brief.goal}</Badge>
          </div>
        </div>
      </div>

      <div>
        <SectionLabel>Hook Angle</SectionLabel>
        <InfoBox className="border-blue-500/20 bg-blue-500/5">
          <p className="text-sm leading-relaxed text-zinc-100">{brief.hook_angle}</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Key Message</SectionLabel>
        <InfoBox>
          <p className="text-xs leading-relaxed text-zinc-300">{brief.key_message}</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Supporting Points</SectionLabel>
        <div className="space-y-1.5">
          {brief.supporting_points.map((p, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-zinc-300">
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-zinc-600 mt-0.5" />
              {p}
            </div>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Call to Action</SectionLabel>
        <InfoBox className="border-amber-500/20 bg-amber-500/5">
          <p className="text-xs font-medium text-amber-300">{brief.cta}</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Format & Tone</SectionLabel>
        <div className="grid grid-cols-2 gap-2">
          <InfoBox>
            <p className="text-xs text-zinc-500 mb-0.5">Tone</p>
            <p className="text-xs text-zinc-300">{brief.tone}</p>
          </InfoBox>
          <InfoBox>
            <p className="text-xs text-zinc-500 mb-0.5">Format</p>
            <p className="text-xs text-zinc-300">{brief.format}</p>
          </InfoBox>
        </div>
      </div>
    </div>
  )
}

function DraftDetail() {
  const { draft } = MOCK_CONTENT_DATA
  const [active, setActive] = useState<'a' | 'b'>('a')
  const d = active === 'a' ? draft.draft_a : draft.draft_b

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-100">Content Drafts</h3>
        <div className="flex gap-1">
          {(['a', 'b'] as const).map(v => (
            <button
              key={v}
              onClick={() => setActive(v)}
              className={cn(
                'rounded px-3 py-1 text-xs font-medium transition-colors',
                active === v ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300',
              )}
            >
              Draft {v.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <InfoBox>
        <p className="mb-1 text-xs font-semibold text-zinc-500">Hook</p>
        <p className="text-sm font-medium text-zinc-100">{d.hook}</p>
      </InfoBox>

      <div>
        <SectionLabel>Full Draft</SectionLabel>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs leading-relaxed text-zinc-300 whitespace-pre-wrap">
          {d.text}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Word Count</p>
          <p className="text-sm font-bold text-zinc-100">{d.word_count}</p>
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Hashtags</p>
          <p className="text-sm font-bold text-zinc-100">{d.hashtags.length}</p>
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">CTA</p>
          <p className="text-xs text-zinc-300 truncate">{d.engagement_prompt.slice(0, 24)}…</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Writer Notes</SectionLabel>
        <InfoBox className="border-amber-500/20 bg-amber-500/5">
          <p className="text-xs leading-relaxed text-amber-300">{draft.writer_notes}</p>
        </InfoBox>
      </div>
    </div>
  )
}

function ReviewDetail() {
  const { review } = MOCK_CONTENT_DATA
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-sm font-semibold text-zinc-100">Content Review</h3>
        <Badge variant={review.decision === 'approved' ? 'success' : 'warning'}>
          {review.decision === 'approved' ? '✓ Approved' : 'Revised'}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-1">Brand Voice</p>
          <p className="text-2xl font-bold text-emerald-400">{review.brand_voice_score}<span className="text-sm text-zinc-600">/10</span></p>
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-1">Brief Alignment</p>
          <p className="text-2xl font-bold text-emerald-400">{review.brief_alignment_score}<span className="text-sm text-zinc-600">/10</span></p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Flags</SectionLabel>
        {review.flags.length === 0 ? (
          <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            <p className="text-xs text-emerald-400">No flags — draft passed all checks.</p>
          </div>
        ) : (
          review.flags.map((f, i) => (
            <InfoBox key={i} className="mb-2 border-red-400/20">
              <p className="text-xs text-red-400">{f.type}: {f.quote}</p>
            </InfoBox>
          ))
        )}
      </div>

      <div>
        <SectionLabel>Approved Draft</SectionLabel>
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs leading-relaxed text-zinc-300 whitespace-pre-wrap max-h-64 overflow-y-auto">
          {review.approved_draft}
        </div>
      </div>
    </div>
  )
}

function PublishDetail() {
  const { publish } = MOCK_CONTENT_DATA
  const pkg = publish.publish_package
  const sched = publish.scheduling_metadata
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-sm font-semibold text-zinc-100">Publish Package</h3>
        <Badge variant={publish.publish_ready ? 'success' : 'warning'}>
          {publish.publish_ready ? 'Ready to Schedule' : 'Not Ready'}
        </Badge>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Characters</p>
          <p className="text-sm font-bold text-zinc-100">{pkg.character_count}<span className="text-xs text-zinc-600">/3000</span></p>
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Hashtags</p>
          <p className="text-sm font-bold text-zinc-100">{pkg.hashtags.length}</p>
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Pillar</p>
          <p className="text-xs font-medium text-blue-400 capitalize">{sched.content_pillar}</p>
        </InfoBox>
      </div>

      <div>
        <SectionLabel>Hashtags</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          {pkg.hashtags.map((h, i) => (
            <span key={i} className="rounded border border-blue-500/20 bg-blue-500/10 px-2 py-0.5 text-xs text-blue-400">{h}</span>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Scheduling</SectionLabel>
        <InfoBox>
          <div className="flex items-center gap-2 mb-1.5">
            <Clock className="h-3.5 w-3.5 text-zinc-500" />
            <p className="text-xs text-zinc-300">{sched.recommended_post_time}</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">campaign</span>
            <p className="text-xs text-zinc-400 font-mono">{sched.campaign_tag}</p>
          </div>
        </InfoBox>
      </div>

      {pkg.visual_recommendation && (
        <div>
          <SectionLabel>Visual Recommendation</SectionLabel>
          <InfoBox className="border-blue-500/20 bg-blue-500/5">
            <p className="text-xs leading-relaxed text-zinc-300">{pkg.visual_recommendation}</p>
          </InfoBox>
        </div>
      )}

      {publish.operator_flags.length > 0 && (
        <div>
          <SectionLabel>Operator Flags</SectionLabel>
          {publish.operator_flags.map((f, i) => (
            <div key={i} className="flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/5 px-2.5 py-2 text-xs text-amber-300 mb-1.5">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-400" />
              {f}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ContentPanel() {
  const [stage, setStage] = useState<ContentStage>('brief')
  const { brief } = MOCK_CONTENT_DATA

  const stages: SidebarStage[] = [
    { id: 'brief',   label: 'Content Brief',  sublabel: 'Hook · key message · CTA' },
    { id: 'draft',   label: 'Draft',          sublabel: 'Draft A + B generated' },
    { id: 'review',  label: 'Review',         sublabel: 'Approved 9/10 voice score' },
    { id: 'publish', label: 'Publish Package', sublabel: '492 chars · 4 hashtags' },
  ]

  const header = (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">Active Topic</p>
      <p className="text-xs font-medium text-zinc-100 leading-relaxed">{brief.brief_title}</p>
      <div className="mt-2 flex gap-1.5">
        <span className="rounded border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-xs text-blue-400">LinkedIn</span>
        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">Education</span>
      </div>
    </div>
  )

  const footer = (
    <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
      <p className="text-xs font-semibold text-emerald-400">Ready to Schedule</p>
      <p className="mt-1 text-xs text-zinc-500">Awaiting visual asset before posting.</p>
    </div>
  )

  return (
    <div className="flex h-full overflow-hidden">
      <StageSidebar header={header} stages={stages} selected={stage} onSelect={id => setStage(id as ContentStage)} footer={footer} />
      <DetailPane stageKey={stage}>
        {stage === 'brief'   && <BriefDetail />}
        {stage === 'draft'   && <DraftDetail />}
        {stage === 'review'  && <ReviewDetail />}
        {stage === 'publish' && <PublishDetail />}
      </DetailPane>
    </div>
  )
}

// ── DevOps Ops Panel ──────────────────────────────────────────────────

type DevOpsCard = 'security' | 'finops' | 'fix'

function SecurityDetail() {
  const { security } = MOCK_DEVOPS_OPS_DATA
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Security Scan</h3>
          <p className="text-xs text-zinc-500">{security.client_slug} · AWS</p>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2">
        {[
          { label: 'CRITICAL', count: security.critical_count, color: 'text-red-400' },
          { label: 'HIGH',     count: security.high_count,     color: 'text-orange-400' },
          { label: 'MEDIUM',   count: security.medium_count,   color: 'text-amber-400' },
          { label: 'LOW',      count: security.low_count,      color: 'text-zinc-400' },
        ].map(s => (
          <InfoBox key={s.label}>
            <p className={cn('text-xl font-bold', s.color)}>{s.count}</p>
            <p className="text-xs text-zinc-600">{s.label}</p>
          </InfoBox>
        ))}
      </div>

      <InfoBox>
        <p className="text-xs leading-relaxed text-zinc-300">{security.scan_summary}</p>
      </InfoBox>

      <div>
        <SectionLabel>Findings</SectionLabel>
        <div className="space-y-2">
          {security.findings.map(f => (
            <div key={f.id} className="rounded-lg border border-zinc-800 bg-zinc-950 overflow-hidden">
              <button
                onClick={() => setExpanded(expanded === f.id ? null : f.id)}
                className="w-full p-3 text-left"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <SeverityBadge sev={f.severity} />
                    <span className="truncate text-xs font-medium text-zinc-100">{f.title}</span>
                  </div>
                  <span className="shrink-0 text-xs text-zinc-600">{f.id}</span>
                </div>
                <p className="mt-1 text-xs text-zinc-500">{f.category} · {f.resource} · {f.effort_estimate}</p>
              </button>
              {expanded === f.id && (
                <div className="border-t border-zinc-800 px-3 pb-3 pt-2 space-y-2">
                  <p className="text-xs leading-relaxed text-zinc-400">{f.description}</p>
                  <div>
                    <p className="text-xs font-semibold text-zinc-500 mb-1">Remediation</p>
                    <p className="text-xs leading-relaxed text-zinc-300">{f.remediation}</p>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Immediate Actions</SectionLabel>
        <div className="space-y-1.5">
          {security.immediate_actions.map((a, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <span className="shrink-0 rounded-full bg-red-500/20 px-1.5 py-0.5 text-xs font-bold text-red-400">{i + 1}</span>
              <span className="text-zinc-300">{a}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function FinOpsDetail() {
  const { finops } = MOCK_DEVOPS_OPS_DATA
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">FinOps Analysis</h3>
          <p className="text-xs text-zinc-500">{finops.client_slug} · {finops.analysis_period}</p>
        </div>
        <Badge variant="warning">{finops.waste_percentage}% waste</Badge>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Total Spend</p>
          <p className="text-lg font-bold text-zinc-100">${(finops.total_spend_usd / 1000).toFixed(1)}k</p>
        </InfoBox>
        <InfoBox className="border-red-400/20 bg-red-400/5">
          <p className="text-xs text-zinc-500 mb-0.5">Waste Found</p>
          <p className="text-lg font-bold text-red-400">${(finops.estimated_waste_usd / 1000).toFixed(1)}k</p>
        </InfoBox>
        <InfoBox className="border-emerald-500/20 bg-emerald-500/5">
          <p className="text-xs text-zinc-500 mb-0.5">After Fixes</p>
          <p className="text-lg font-bold text-emerald-400">${(finops.projected_monthly_spend_after_optimizations_usd / 1000).toFixed(1)}k</p>
        </InfoBox>
      </div>

      <InfoBox>
        <p className="text-xs leading-relaxed text-zinc-300">{finops.executive_summary}</p>
      </InfoBox>

      {finops.anomalies_detected.length > 0 && (
        <div>
          <SectionLabel>Anomalies Detected</SectionLabel>
          {finops.anomalies_detected.map((a, i) => (
            <InfoBox key={i} className="border-red-400/20 bg-red-400/5 mb-2">
              <p className="text-xs font-medium text-red-300">{a.description}</p>
              <p className="mt-1 text-xs text-zinc-400">Likely: {a.likely_cause}</p>
              <p className="mt-1 text-xs text-zinc-500">→ {a.recommended_action}</p>
            </InfoBox>
          ))}
        </div>
      )}

      <div>
        <SectionLabel>Waste Items</SectionLabel>
        <div className="space-y-2">
          {finops.waste_items.map(w => (
            <InfoBox key={w.id}>
              <div className="flex items-start justify-between gap-2 mb-1">
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium text-zinc-100">{w.resource_id}</p>
                  <p className="text-xs text-zinc-500">{w.resource_type} · {w.category}</p>
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-xs font-bold text-emerald-400">−${w.potential_savings_usd}/mo</p>
                  <p className="text-xs text-zinc-600">{w.effort}</p>
                </div>
              </div>
              <p className="text-xs text-zinc-400">{w.recommendation}</p>
            </InfoBox>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Priority Actions</SectionLabel>
        <div className="space-y-1.5">
          {finops.priority_actions.map((a, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <span className="shrink-0 rounded-full bg-zinc-800 px-1.5 py-0.5 text-xs font-bold text-zinc-400">{i + 1}</span>
              <span className="text-zinc-300">{a}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function FixIssueDetail() {
  const { fixIssue } = MOCK_DEVOPS_OPS_DATA
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">{fixIssue.fix_title}</h3>
          <p className="text-xs text-zinc-500 mt-0.5">{fixIssue.issue_title}</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Severity</p>
          <SeverityBadge sev={fixIssue.severity} />
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Duration</p>
          <p className="text-sm font-bold text-zinc-100">{fixIssue.estimated_duration_minutes}m</p>
        </InfoBox>
        <InfoBox>
          <p className="text-xs text-zinc-500 mb-0.5">Risk</p>
          <p className="text-xs font-medium capitalize text-amber-400">{fixIssue.risk_level}</p>
        </InfoBox>
      </div>

      <div className="flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2.5">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-400" />
        <p className="text-xs text-amber-300">{fixIssue.approval_note}</p>
      </div>

      <div>
        <SectionLabel>Pre-Conditions</SectionLabel>
        <div className="space-y-1.5">
          {fixIssue.pre_conditions.map((c, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-zinc-300">
              <Info className="h-3.5 w-3.5 shrink-0 text-blue-400 mt-0.5" />
              {c}
            </div>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Fix Steps</SectionLabel>
        <div className="space-y-2">
          {fixIssue.fix_steps.map(s => (
            <InfoBox key={s.step}>
              <div className="flex items-start gap-2">
                <span className="shrink-0 rounded-full bg-blue-500/20 border border-blue-500/30 px-1.5 py-0.5 text-xs font-bold text-blue-400">{s.step}</span>
                <div className="min-w-0">
                  <p className="text-xs font-medium text-zinc-100">{s.action}</p>
                  <p className="mt-0.5 text-xs text-zinc-500">Expected: {s.expected_outcome}</p>
                  <p className="mt-0.5 text-xs text-zinc-600">Rollback: {s.rollback_step}</p>
                </div>
              </div>
            </InfoBox>
          ))}
        </div>
      </div>

      <div>
        <SectionLabel>Validation Steps</SectionLabel>
        <div className="space-y-1.5">
          {fixIssue.validation_steps.map((v, i) => (
            <div key={i} className="flex items-start gap-2 font-mono text-xs text-zinc-400">
              <span className="text-emerald-600">$</span>
              {v}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function DevOpsPanel() {
  const [card, setCard] = useState<DevOpsCard>('security')
  const { security, finops, fixIssue } = MOCK_DEVOPS_OPS_DATA

  const stages: SidebarStage[] = [
    {
      id: 'security',
      label: 'Security Scan',
      sublabel: `${security.critical_count} CRIT · ${security.high_count} HIGH · ${security.medium_count} MED`,
    },
    {
      id: 'finops',
      label: 'FinOps Analysis',
      sublabel: `$${(finops.estimated_waste_usd / 1000).toFixed(1)}k waste · ${finops.waste_percentage}%`,
    },
    {
      id: 'fix',
      label: 'Fix Issue',
      sublabel: `RDS pooling · HIGH · ${fixIssue.estimated_duration_minutes}m`,
    },
  ]

  const header = (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">Client</p>
      <p className="text-sm font-medium text-zinc-100">{security.client_slug}</p>
      <div className="mt-2 flex gap-1.5">
        <span className="rounded border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-xs text-blue-400">AWS</span>
        <span className="rounded border border-red-400/20 bg-red-400/5 px-1.5 py-0.5 text-xs text-red-400">1 CRITICAL</span>
      </div>
    </div>
  )

  const footer = (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
      <p className="text-xs font-semibold text-amber-400">Requires Approval</p>
      <p className="mt-1 text-xs text-zinc-500">All findings need human sign-off before action.</p>
    </div>
  )

  return (
    <div className="flex h-full overflow-hidden">
      <StageSidebar header={header} stages={stages} selected={card} onSelect={id => setCard(id as DevOpsCard)} footer={footer} />
      <DetailPane stageKey={card}>
        {card === 'security' && <SecurityDetail />}
        {card === 'finops'   && <FinOpsDetail />}
        {card === 'fix'      && <FixIssueDetail />}
      </DetailPane>
    </div>
  )
}

// ── OpsHub (main export) ──────────────────────────────────────────────

export function OpsHub() {
  const [tab, setTab] = useState<OpsTab>('sales')

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <h2 className="text-sm font-semibold text-zinc-100">Internal Ops Hub</h2>
        <div className="flex items-center gap-1">
          {OPS_TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
                tab === t.id
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'text-zinc-500 hover:text-zinc-300',
              )}
            >
              <t.icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.1 }}
            className="h-full"
          >
            {tab === 'sales'   && <SalesPanel />}
            {tab === 'content' && <ContentPanel />}
            {tab === 'devops'  && <DevOpsPanel />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}
