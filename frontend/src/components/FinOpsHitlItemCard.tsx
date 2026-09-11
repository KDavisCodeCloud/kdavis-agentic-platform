'use client'

import { useState } from 'react'
import { Check, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { approveFinopsItem, dismissFinopsItem } from '@/lib/api'
import { FINOPS_ITEM_STATUS_META, type FinOpsHitlItem, type FinOpsItemStatus } from '@/lib/types'

// Mirrors AuditRemediationItemCard.tsx's shape exactly -- same optimistic
// update-without-reload pattern, same severity badge/remediation layout.

interface FinOpsHitlItemCardProps {
  item: FinOpsHitlItem
  token: string
  onActioned: (itemId: string, status: FinOpsItemStatus) => void
}

const SEVERITY_VARIANT = {
  HIGH:   'danger',
  MEDIUM: 'pending',
  LOW:    'muted',
} as const

export function FinOpsHitlItemCard({ item, token, onActioned }: FinOpsHitlItemCardProps) {
  const [loading, setLoading] = useState<'approve' | 'dismiss' | null>(null)
  const [error, setError]     = useState<string | null>(null)

  const isPending  = item.status === 'pending_approval'
  const statusMeta = FINOPS_ITEM_STATUS_META[item.status]

  async function handleAction(action: 'approve' | 'dismiss') {
    setLoading(action)
    setError(null)
    try {
      const fn = action === 'approve' ? approveFinopsItem : dismissFinopsItem
      const result = await fn(token, item.id)
      onActioned(item.id, result.status as FinOpsItemStatus)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : `${action === 'approve' ? 'Approve' : 'Dismiss'} failed`)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge variant={SEVERITY_VARIANT[item.severity]}>{item.severity}</Badge>
          <span className="text-xs text-zinc-500">{item.category}</span>
        </div>
        {isPending ? (
          item.estimated_monthly_waste_usd > 0 && (
            <span className="font-mono text-sm font-semibold text-amber-400">
              ${item.estimated_monthly_waste_usd.toLocaleString(undefined, { minimumFractionDigits: 2 })}/mo
            </span>
          )
        ) : (
          <span className={`rounded border px-2 py-0.5 text-xs font-medium ${statusMeta.color}`}>
            {statusMeta.label}
          </span>
        )}
      </div>

      <h3 className="text-sm font-medium text-zinc-100">{item.title}</h3>
      <p className="mt-1 text-xs leading-relaxed text-zinc-400">{item.description}</p>

      <div className="mt-2 rounded border border-zinc-800 bg-zinc-950 p-2.5">
        <p className="text-xs font-semibold uppercase tracking-wider text-zinc-600">Remediation</p>
        <p className="mt-1 text-xs leading-relaxed text-zinc-300">{item.remediation}</p>
      </div>

      {error && (
        <p className="mt-2 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {error}
        </p>
      )}

      {isPending && (
        <div className="mt-3 flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="flex-1 border border-zinc-700"
            disabled={loading !== null}
            loading={loading === 'dismiss'}
            onClick={() => handleAction('dismiss')}
          >
            <X className="h-3.5 w-3.5" />
            Dismiss
          </Button>
          <Button
            size="sm"
            className="flex-1"
            disabled={loading !== null}
            loading={loading === 'approve'}
            onClick={() => handleAction('approve')}
          >
            <Check className="h-3.5 w-3.5" />
            Approve
          </Button>
        </div>
      )}
    </div>
  )
}
