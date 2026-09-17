'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// 24-gap-closure Phase 6 -- persistent setup-completeness card, shown on
// every dashboard tab until 5/5, then gone. alert_source_verified is the
// one item that can only ever be proven by a real inbound webhook
// (api/routes/setup_checklist.py reads alert_ingestion_log directly) --
// there is no button here that can flip it, by design.

import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Circle, FlaskConical, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getSetupChecklist, runConnectionTest, cleanupConnectionTest } from '@/lib/api'
import type { SetupChecklist } from '@/lib/types'

interface SetupChecklistCardProps {
  token: string
}

const ITEMS: { key: keyof SetupChecklist; label: string }[] = [
  { key: 'cloud_connected', label: 'Cloud account connected' },
  { key: 'repo_connected', label: 'Repository connected' },
  { key: 'alert_source_verified', label: 'Alert source verified (real webhook received)' },
  { key: 'notification_channel_set', label: 'Notification channel configured' },
  { key: 'end_to_end_test_passed', label: 'End-to-end test passed' },
]

export function SetupChecklistCard({ token }: SetupChecklistCardProps) {
  const [checklist, setChecklist] = useState<SetupChecklist | null>(null)
  const [dismissed, setDismissed] = useState(false)
  const [testBusy, setTestBusy] = useState(false)
  const [testIncidentId, setTestIncidentId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setChecklist(await getSetupChecklist(token))
    } catch {
      setChecklist(null)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  async function handleRunTest() {
    setTestBusy(true)
    setError('')
    try {
      const result = await runConnectionTest(token)
      setTestIncidentId(result.incident_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the test incident')
    } finally {
      setTestBusy(false)
    }
  }

  async function handleCleanup() {
    if (!testIncidentId) return
    setTestBusy(true)
    setError('')
    try {
      await cleanupConnectionTest(token, testIncidentId)
      setTestIncidentId(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not clean up the test incident')
    } finally {
      setTestBusy(false)
    }
  }

  if (!checklist || dismissed || checklist.completed_count === 5) return null

  return (
    <div className="mx-5 mt-3 rounded-lg border border-blue-500/20 bg-blue-500/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-100">
          Setup checklist ({checklist.completed_count}/5)
        </h3>
        <button onClick={() => setDismissed(true)} className="text-zinc-500 hover:text-zinc-300">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mb-3 space-y-1.5">
        {ITEMS.map(item => {
          const done = Boolean(checklist[item.key])
          return (
            <div key={item.key} className="flex items-center gap-2 text-xs">
              {done ? (
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
              ) : (
                <Circle className="h-3.5 w-3.5 shrink-0 text-zinc-600" />
              )}
              <span className={done ? 'text-zinc-300' : 'text-zinc-500'}>{item.label}</span>
            </div>
          )
        })}
      </div>

      {error && <p className="mb-2 text-xs text-red-400">{error}</p>}

      {!checklist.end_to_end_test_passed && (
        testIncidentId ? (
          <div className="flex items-center gap-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2">
            <p className="flex-1 text-xs text-amber-300">
              Test incident created — check it out in the HITL Console, then clean it up here.
            </p>
            <Button size="sm" variant="outline" disabled={testBusy} loading={testBusy} onClick={handleCleanup}>
              Clean up
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" disabled={testBusy} loading={testBusy} onClick={handleRunTest}>
            <FlaskConical className="h-3.5 w-3.5" /> Run connection test
          </Button>
        )
      )}
    </div>
  )
}
