'use client'

import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, PlayCircle, CheckCircle2, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { AgentConnectFlow } from './AgentConnectFlow'
import {
  getComplianceStatus, connectCompliance, verifyComplianceAwsRole,
  getComplianceReport, triggerComplianceScan,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import type { AgentConnectionStatus, ComplianceReportData } from '@/lib/types'

interface ComplianceAgentDashboardProps {
  token: string
}

export function ComplianceAgentDashboard({ token }: ComplianceAgentDashboardProps) {
  const [status, setStatus]         = useState<AgentConnectionStatus | null>(null)
  const [report, setReport]         = useState<ComplianceReportData | null>(null)
  const [loading, setLoading]       = useState(true)
  const [connecting, setConnecting] = useState(false)
  const [verifying, setVerifying]   = useState(false)
  const [scanning, setScanning]     = useState(false)
  const [error, setError]           = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const s = await getComplianceStatus(token)
      setStatus(s)
      if (s.connected) {
        try {
          setReport(await getComplianceReport(token))
        } catch {
          // No scan yet -- not an error worth showing, just an empty state.
          setReport(null)
        }
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load Compliance status')
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
      setStatus(await connectCompliance(token))
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
      await verifyComplianceAwsRole(token, roleArn)
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not verify that role')
    } finally {
      setVerifying(false)
    }
  }

  async function handleScan() {
    setScanning(true)
    setError(null)
    try {
      const result = await triggerComplianceScan(token)
      setReport(result.report)
      if (!result.report) setError(result.error_message ?? 'Scan did not produce a report')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-zinc-800 px-6 py-3">
        <h2 className="text-sm font-semibold text-zinc-100">Compliance</h2>
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
          productName="Compliance"
          status={status}
          connecting={connecting}
          verifying={verifying}
          error={error}
          onConnect={handleConnect}
          onVerifyRole={handleVerifyRole}
        />
      ) : (
        <div className="flex-1 overflow-y-auto p-4">
          {error && (
            <div className="mb-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              {error}
            </div>
          )}

          {!report ? (
            <p className="py-16 text-center text-xs text-zinc-600">
              No scans yet — click &quot;Run Scan&quot; to check your connected AWS account.
            </p>
          ) : (
            <div className="mx-auto max-w-2xl space-y-4">
              <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-zinc-300">{report.framework}</span>
                  <span className="font-mono text-lg font-bold text-blue-400">{report.readiness_score}%</span>
                </div>
                <p className="mt-2 text-xs leading-relaxed text-zinc-500">{report.coverage_note}</p>
              </div>

              <div className="space-y-2">
                {report.controls.map(c => (
                  <div key={c.control_id} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-2">
                        {c.status === 'PASS' ? (
                          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                        ) : (
                          <XCircle className="h-4 w-4 shrink-0 text-red-400" />
                        )}
                        <span className="font-mono text-xs text-zinc-500">
                          {c.control_id} / {c.security_hub_id}
                        </span>
                      </div>
                      <Badge variant={c.status === 'PASS' ? 'success' : 'danger'}>{c.status}</Badge>
                    </div>
                    <p className="mt-1.5 text-xs text-zinc-300">{c.title}</p>
                    {!c.exact_match && c.caveat && (
                      <p className="mt-1.5 rounded border border-amber-500/20 bg-amber-500/5 px-2 py-1 text-[11px] leading-relaxed text-amber-500/80">
                        {c.caveat}
                      </p>
                    )}
                  </div>
                ))}
              </div>

              <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-zinc-600">
                  Manual review checklist
                </p>
                <div className="mt-2 space-y-1.5">
                  {report.documentation_checklist.map(d => (
                    <div key={d.item} className="flex items-center justify-between text-xs">
                      <span className="text-zinc-400">{d.item}</span>
                      <span className="text-zinc-600">{d.guidance}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
