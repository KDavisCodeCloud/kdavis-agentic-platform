'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// Settings → Policies (migrations 049/050). Admin-only. There is no
// execution-policy setting: every fix needs an explicit approval, and the
// old auto_execution_enabled toggle was removed (2026-11-18). Sections:
// - Resource exemptions: the full list with reasons and an un-exempt
//   action (creation happens inline on the incident card instead — see
//   RemediationCard.tsx's ExemptResourceButton).

import { useCallback, useEffect, useState } from 'react'
import { ShieldCheck, ShieldOff, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RepoMappingsSection } from '@/components/RepoMappingsSection'
import {
  getConnectionsStatus,
  listResourceExemptions, revokeResourceExemption,
} from '@/lib/api'
import type { ConnectionsStatus, ResourceExemption } from '@/lib/types'
import { timeAgo } from '@/lib/utils'

interface PoliciesPanelProps {
  token: string
}

export function PoliciesPanel({ token }: PoliciesPanelProps) {
  const [connections, setConnections] = useState<ConnectionsStatus | null>(null)
  const [exemptions, setExemptions] = useState<ResourceExemption[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revokingId, setRevokingId] = useState<string | null>(null)

  const isAdmin = connections?.member_role === null || connections?.member_role === 'admin'

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const conn = await getConnectionsStatus(token)
      setConnections(conn)
      const admin = conn.member_role === null || conn.member_role === 'admin'
      if (admin) {
        setExemptions(await listResourceExemptions(token))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load policies')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  async function handleRevoke(exemptionId: string) {
    setRevokingId(exemptionId)
    setError('')
    try {
      await revokeResourceExemption(token, exemptionId)
      setExemptions(prev => prev.filter(e => e.id !== exemptionId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke exemption')
    } finally {
      setRevokingId(null)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-xs text-zinc-600">Loading policies…</p>
      </div>
    )
  }

  if (!isAdmin) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <Lock className="mx-auto mb-3 h-8 w-8 text-zinc-600" />
          <p className="text-sm font-medium text-zinc-300">Admin access required</p>
          <p className="mt-1 text-xs text-zinc-500">
            Settings → Policies manages this workspace&apos;s resource exemptions — only a workspace admin
            can view or change them.
          </p>
        </div>
      </div>
    )
  }

  const activeExemptions = exemptions.filter(e => !e.revoked_at)

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl space-y-4">
        <div>
          <h2 className="text-base font-semibold text-zinc-100">Policies</h2>
          <p className="mt-1 text-xs text-zinc-500">
            Resource exemptions for this workspace. Admin-only.
          </p>
        </div>

        {error && (
          <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
          <div className="mb-2 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-zinc-400" />
            <h3 className="text-sm font-semibold text-zinc-100">Approval</h3>
          </div>
          <p className="text-xs leading-relaxed text-zinc-500">
            Every fix waits for an explicit approval on its incident before anything runs. There is no
            setting that changes this.
          </p>
        </div>

        <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
          <div className="mb-3 flex items-center gap-2">
            <ShieldOff className="h-4 w-4 text-zinc-400" />
            <h3 className="text-sm font-semibold text-zinc-100">Resource exemptions</h3>
          </div>
          <p className="mb-4 text-xs leading-relaxed text-zinc-500">
            Resources exempted from ingest — checked before diagnosis, so an exempted resource costs zero
            LLM tokens. Create one from the &quot;Exempt this resource&quot; action on an incident card.
          </p>
          {activeExemptions.length === 0 ? (
            <p className="text-xs text-zinc-600">No active exemptions.</p>
          ) : (
            <div className="space-y-2">
              {activeExemptions.map(e => (
                <div key={e.id} className="rounded border border-zinc-800 bg-zinc-950 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-xs text-zinc-300">{e.resource_name || e.resource_id}</p>
                      <p className="mt-1 text-xs text-zinc-500">{e.reason}</p>
                      <p className="mt-1 text-[11px] text-zinc-600">
                        {e.suppressed_count} alert{e.suppressed_count === 1 ? '' : 's'} suppressed
                        {e.created_by_email && <> · by {e.created_by_email}</>} · {timeAgo(e.created_at)}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="shrink-0 border border-zinc-700"
                      disabled={revokingId === e.id}
                      loading={revokingId === e.id}
                      onClick={() => handleRevoke(e.id)}
                    >
                      Un-exempt
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <RepoMappingsSection token={token} />
      </div>
    </div>
  )
}
