'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, PlayCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AgentConnectFlow } from './AgentConnectFlow'
import { FinOpsHitlItemCard } from './FinOpsHitlItemCard'
import {
  getFinopsStatus, connectFinops, verifyFinopsAwsRole, verifyFinopsAzureServicePrincipal,
  getFinopsDashboard, triggerFinopsScan,
} from '@/lib/api'
import { cn, timeAgo } from '@/lib/utils'
import type { AgentConnectionStatus, AzureServicePrincipalInput, FinOpsDashboardData } from '@/lib/types'

interface FinOpsAgentDashboardProps {
  token: string
}

export function FinOpsAgentDashboard({ token }: FinOpsAgentDashboardProps) {
  const [status, setStatus]         = useState<AgentConnectionStatus | null>(null)
  const [dashboard, setDashboard]   = useState<FinOpsDashboardData | null>(null)
  const [loading, setLoading]       = useState(true)
  const [connecting, setConnecting] = useState(false)
  const [verifying, setVerifying]   = useState(false)
  const [scanning, setScanning]     = useState(false)
  const [error, setError]           = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const s = await getFinopsStatus(token)
      setStatus(s)
      if (s.connected) setDashboard(await getFinopsDashboard(token))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load FinOps status')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  async function handleConnect() {
    setConnecting(true)
    setError(null)
    try {
      setStatus(await connectFinops(token))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to connect')
    } finally {
      setConnecting(false)
    }
  }

  async function handleVerifyRole(roleArn: string) {
    setVerifying(true)
    setError(null)
    try {
      await verifyFinopsAwsRole(token, roleArn)
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not verify that role')
    } finally {
      setVerifying(false)
    }
  }

  async function handleVerifyAzure(input: AzureServicePrincipalInput) {
    setVerifying(true)
    setError(null)
    try {
      await verifyFinopsAzureServicePrincipal(token, input)
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not verify that Service Principal')
    } finally {
      setVerifying(false)
    }
  }

  async function handleScan() {
    setScanning(true)
    setError(null)
    try {
      setDashboard(await triggerFinopsScan(token))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  function handleItemActioned(itemId: string) {
    // open_items only ever holds pending_approval items (same filter the
    // backend's GET /dashboard applies) -- once approved/dismissed, the
    // item just drops out of this list.
    setDashboard(prev => (prev ? { ...prev, open_items: prev.open_items.filter(i => i.id !== itemId) } : prev))
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <h2 className="text-sm font-semibold text-zinc-100">FinOps</h2>
        <div className="flex items-center gap-2">
          {status?.connected && (
            <Button size="sm" variant="outline" disabled={scanning} loading={scanning} onClick={handleScan}>
              <PlayCircle className="h-3.5 w-3.5" />
              Run Scan
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className={cn('h-7 w-7', loading && 'opacity-50')}
            onClick={() => load()}
            disabled={loading}
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      {loading && !status ? (
        <div className="flex flex-1 items-center justify-center">
          <RefreshCw className="h-5 w-5 animate-spin text-zinc-600" />
        </div>
      ) : status && !status.connected ? (
        <AgentConnectFlow
          productName="FinOps"
          status={status}
          connecting={connecting}
          verifying={verifying}
          error={error}
          onConnect={handleConnect}
          onVerifyRole={handleVerifyRole}
          onVerifyAzure={handleVerifyAzure}
        />
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          {error && (
            <div className="mb-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              {error}
            </div>
          )}

          {dashboard?.latest_scan && (
            <div className="mb-4 flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900 p-3 text-xs text-zinc-400">
              <span>
                Last scan: {dashboard.latest_scan.total_findings} findings,{' '}
                <span className="font-mono text-amber-400">
                  ${dashboard.latest_scan.total_estimated_monthly_waste_usd.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                  })}/mo
                </span>{' '}
                waste
              </span>
              <span>{timeAgo(dashboard.latest_scan.started_at)}</span>
            </div>
          )}

          {!dashboard?.latest_scan ? (
            <p className="py-16 text-center text-xs text-zinc-600">
              No scans yet — click &quot;Run Scan&quot; to check your connected AWS account.
            </p>
          ) : dashboard.open_items.length === 0 ? (
            <p className="py-16 text-center text-xs text-zinc-600">No open items — nice and clean.</p>
          ) : (
            <div className="space-y-3">
              {dashboard.open_items.map(item => (
                <FinOpsHitlItemCard key={item.id} item={item} token={token} onActioned={handleItemActioned} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
