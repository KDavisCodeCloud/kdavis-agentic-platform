'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Cloud } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AuditRemediationItemCard } from './AuditRemediationItemCard'
import { listAuditSubmissions, getAuditReport } from '@/lib/api'
import { cn, timeAgo } from '@/lib/utils'
import type { AuditSubmissionSummary, AuditSubmissionDetail, AuditItemStatus } from '@/lib/types'

interface AuditDashboardProps {
  token: string
}

export function AuditDashboard({ token }: AuditDashboardProps) {
  const [submissions, setSubmissions]   = useState<AuditSubmissionSummary[]>([])
  const [selectedId, setSelectedId]     = useState<string | null>(null)
  const [detail, setDetail]             = useState<AuditSubmissionDetail | null>(null)
  const [loading, setLoading]           = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError]               = useState<string | null>(null)

  const fetchSubmissions = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listAuditSubmissions(token)
      setSubmissions(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load audit submissions')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    fetchSubmissions()
  }, [fetchSubmissions])

  async function handleSelect(auditId: string) {
    setSelectedId(auditId)
    setDetailLoading(true)
    setDetail(null)
    try {
      const data = await getAuditReport(token, auditId)
      setDetail(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load audit report')
    } finally {
      setDetailLoading(false)
    }
  }

  function handleItemActioned(itemId: string, status: AuditItemStatus) {
    setDetail(prev =>
      prev ? { ...prev, items: prev.items.map(i => (i.id === itemId ? { ...i, status } : i)) } : prev,
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <h2 className="text-sm font-semibold text-zinc-100">Cloud Audit Remediation Plan</h2>
        <Button
          variant="ghost"
          size="icon"
          className={cn('h-7 w-7', loading && 'opacity-50')}
          onClick={() => fetchSubmissions()}
          disabled={loading}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
        </Button>
      </div>

      {error && (
        <div className="mx-4 mt-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* Left: submission list */}
        <div className={cn(
          'flex-shrink-0 overflow-y-auto border-r border-zinc-800 p-4',
          selectedId ? 'w-1/2 xl:w-[40%]' : 'w-full',
        )}>
          {loading && submissions.length === 0 ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCw className="h-5 w-5 animate-spin text-zinc-600" />
            </div>
          ) : submissions.length === 0 ? (
            <p className="py-16 text-center text-xs text-zinc-600">
              No audits submitted yet — run <code className="font-mono">python -m audit --submit</code> from the CLI.
            </p>
          ) : (
            <div className="space-y-2">
              {submissions.map(s => (
                <button
                  key={s.audit_id}
                  onClick={() => handleSelect(s.audit_id)}
                  className={cn(
                    'w-full rounded-lg border p-3 text-left transition-colors',
                    selectedId === s.audit_id
                      ? 'border-blue-500/60 bg-blue-500/10'
                      : 'border-zinc-800 bg-zinc-900 hover:border-zinc-700',
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-xs font-medium text-zinc-200">
                      <Cloud className="h-3.5 w-3.5 text-zinc-500" />
                      {s.provider.toUpperCase()}
                    </div>
                    <span className="font-mono text-xs font-semibold text-amber-400">
                      ${s.total_estimated_monthly_waste_usd.toLocaleString(undefined, { minimumFractionDigits: 2 })}/mo
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center justify-between gap-2 text-xs text-zinc-500">
                    <span>{s.total_findings} findings</span>
                    <span>{timeAgo(s.created_at)}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right: selected submission's remediation items */}
        {selectedId && (
          <div className="flex-1 overflow-y-auto p-4">
            {detailLoading ? (
              <div className="flex items-center justify-center py-16">
                <RefreshCw className="h-5 w-5 animate-spin text-zinc-600" />
              </div>
            ) : detail?.analysis_error ? (
              <div className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                Analysis did not complete: {detail.analysis_error}
              </div>
            ) : detail ? (
              <div className="space-y-3">
                {detail.items.map(item => (
                  <AuditRemediationItemCard
                    key={item.id}
                    item={item}
                    token={token}
                    onActioned={handleItemActioned}
                  />
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
