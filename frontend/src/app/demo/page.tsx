'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Zap, Sparkles } from 'lucide-react'
import { IncidentConsole } from '@/components/IncidentConsole'
import { startDemoSession, getDemoConfig, ApiError } from '@/lib/api'
import { captureAttributionFromUrl, getAttribution, trackEvent } from '@/lib/attribution'

// Phase 6 public demo sandbox. GET /api/v1/demo mints a scoped,
// approver-level, 24h session with its OWN copy of the 8 synthetic
// incidents (migration 059 -- see core/demo_sandbox.py), so nothing one
// visitor does changes what another sees. No signup, no auth. Approve/Reject/Resolve
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
  // Gap-table #11: shown after the visitor's first approval.
  const [showCta, setShowCta] = useState(false)
  const [bookingUrl, setBookingUrl] = useState<string | null>(null)

  useEffect(() => {
    void getDemoConfig().then(c => setBookingUrl(c.booking_url))
  }, [])

  const mintSession = useCallback(() => {
    setLoading(true)
    // Before minting: React runs this page's effects before the root
    // layout's AttributionCapture, so capture ?ref= / utm_* here or the
    // first visit from an outreach link would mint an unattributed session.
    captureAttributionFromUrl()
    startDemoSession(getAttribution())
      .then(session => {
        sessionStorage.setItem(_STORAGE_KEY, session.demo_token)
        setToken(session.demo_token)
        setExpiresAt(session.expires_at)
        // Counted once per new demo session, not on every reload.
        trackEvent('demo_opened', { demoToken: session.demo_token })
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

  useEffect(() => {
    const cached = sessionStorage.getItem(_STORAGE_KEY)
    if (cached) {
      setToken(cached)
      setLoading(false)
      return
    }
    mintSession()
  }, [mintSession])

  // The API rejected the cached token: it expired (24h) or was retired.
  // Drop it and mint a fresh session with its own seeded incidents.
  // At most one automatic re-mint per page load: a brand-new token being
  // rejected too means something is wrong server-side, and looping would
  // just burn through the rate limit.
  const remintedRef = useRef(false)
  const handleAuthError = useCallback(() => {
    sessionStorage.removeItem(_STORAGE_KEY)
    setToken(null)
    if (remintedRef.current) {
      setError('Could not start the demo session. Please refresh in a minute.')
      return
    }
    remintedRef.current = true
    mintSession()
  }, [mintSession])

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
          Get started on your own stack →
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
        <IncidentConsole token={token} onAuthError={handleAuthError} onFixApproved={() => setShowCta(true)} />
      </main>

      {showCta && (
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-blue-500/30 bg-blue-500/10 px-5 py-3">
          <p className="min-w-0 flex-1 text-sm text-zinc-200">
            <strong className="font-semibold text-zinc-100">That&apos;s the loop.</strong> Cloud Decoded diagnoses, you
            approve, then it runs. Nothing executes on your infrastructure without your approval.
          </p>
          {bookingUrl && (
            <a
              href={bookingUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => trackEvent('booking_clicked', { demoToken: token, properties: { cta: '/demo' } })}
              className="inline-flex min-h-[44px] items-center rounded-lg border border-zinc-600 px-4 py-2 text-sm text-zinc-100 hover:bg-zinc-900"
            >
              Book a 15-min walkthrough
            </a>
          )}
          <a
            href="/signup"
            className="inline-flex min-h-[44px] items-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500"
          >
            Get started →
          </a>
        </div>
      )}
    </div>
  )
}
