'use client'

import { useEffect, useState } from 'react'
import { Zap, Sparkles } from 'lucide-react'
import { IncidentConsole } from '@/components/IncidentConsole'
import { startDemoSession, ApiError } from '@/lib/api'

// Phase 6 public demo sandbox. GET /api/v1/demo mints a scoped,
// approver-level, 24h session against the one shared demo workspace
// (8 synthetic incidents, reset every 30 minutes server-side -- see
// core/demo_sandbox.py). No signup, no auth. Approve/Reject/Resolve
// Manually all genuinely work; nothing here can ever touch a real cloud
// account (three independent structural guarantees, see that module's
// docstring) and this page never renders Settings/Members/Billing/
// Connections at all -- there is nothing here for a demo token to touch
// even if it tried.
//
// sessionStorage, not localStorage: a demo session is meant to live for
// this one tab/visit, not linger on a shared machine the way a real
// workspace_token would.
const _STORAGE_KEY = 'cd_demo_session_token'

export default function DemoPage() {
  const [token, setToken] = useState<string | null>(null)
  const [expiresAt, setExpiresAt] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const cached = sessionStorage.getItem(_STORAGE_KEY)
    if (cached) {
      setToken(cached)
      setLoading(false)
      return
    }
    startDemoSession()
      .then(session => {
        sessionStorage.setItem(_STORAGE_KEY, session.demo_token)
        setToken(session.demo_token)
        setExpiresAt(session.expires_at)
      })
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 429) {
          setError('The demo is getting a lot of visitors right now — please wait a minute and refresh.')
        } else {
          setError(e instanceof Error ? e.message : 'Could not start the demo session.')
        }
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-zinc-950">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-700 border-t-blue-500" />
      </div>
    )
  }

  if (error || !token) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-zinc-950 px-6 text-center">
        <p className="max-w-md text-sm text-zinc-400">{error ?? 'Could not start the demo session.'}</p>
        <a
          href="/"
          className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-900"
        >
          Back to homepage
        </a>
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col bg-zinc-950">
      <header className="flex h-12 shrink-0 items-center gap-2.5 border-b border-zinc-800 bg-zinc-950 px-5">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-600">
          <Zap className="h-3.5 w-3.5 text-white" />
        </div>
        <span className="text-sm font-semibold text-zinc-100">Cloud Decoded</span>
        <a
          href="/signup"
          className="ml-auto rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-500"
        >
          Start your own free trial →
        </a>
      </header>

      {/* Unmissable, permanent — not dismissible. This is the whole point
          of the page: no visitor should ever wonder if this is real. */}
      <div className="flex shrink-0 items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-5 py-2 text-xs text-amber-300">
        <Sparkles className="h-3.5 w-3.5 shrink-0" />
        <span>
          <strong className="font-semibold">DEMO MODE</strong> — synthetic data, nothing real. Every incident below is
          fake and approving one never touches a real cloud account.
          {expiresAt && ' Your demo session lasts 24 hours.'}
        </span>
      </div>

      <main className="flex-1 overflow-hidden">
        <IncidentConsole token={token} />
      </main>
    </div>
  )
}
