'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { ArrowLeft, CreditCard, LogOut, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getBillingPortalUrl, getBillingStatus, type BillingStatus } from '@/lib/api'

const MOCK_MODE  = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'
const DEMO_TOKEN = 'ws-test-001'

const TIER_LABELS: Record<string, string> = {
  starter: 'Starter',
  growth: 'Growth',
  enterprise: 'Enterprise',
}

const STATUS_COPY: Record<
  string,
  { label: string; tone: 'green' | 'blue' | 'amber' | 'red' }
> = {
  active:          { label: 'Active',                tone: 'green' },
  trialing:        { label: 'Trial',                 tone: 'blue' },
  past_due:        { label: 'Payment past due',       tone: 'amber' },
  pending_payment: { label: 'Payment required',       tone: 'amber' },
  canceled:        { label: 'Canceled',               tone: 'red' },
  suspended:       { label: 'Suspended',              tone: 'red' },
}

const TONE_CLASSES: Record<string, string> = {
  green: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
  blue:  'border-blue-500/30 bg-blue-500/10 text-blue-400',
  amber: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
  red:   'border-red-500/30 bg-red-500/10 text-red-400',
}

function BillingContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const wasLocked = searchParams.get('locked') === '1'

  const [token, setToken]     = useState<string | null>(null)
  const [status, setStatus]   = useState<BillingStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [portalLoading, setPortalLoading] = useState(false)

  useEffect(() => {
    const t = MOCK_MODE ? DEMO_TOKEN : localStorage.getItem('workspace_token')
    if (!t) {
      router.replace('/login')
      return
    }
    setToken(t)
    getBillingStatus(t)
      .then(setStatus)
      .catch(() => setError('Could not load billing status. Try refreshing.'))
      .finally(() => setLoading(false))
  }, [router])

  async function handleManageBilling() {
    if (!token || MOCK_MODE) return
    setPortalLoading(true)
    try {
      const url = await getBillingPortalUrl(token)
      window.location.href = url
    } catch {
      setError('No billing account on file yet — complete checkout first.')
    } finally {
      setPortalLoading(false)
    }
  }

  function handleCompleteSignup() {
    if (!token) return
    sessionStorage.setItem('pending_workspace_token', token)
    router.push('/checkout')
  }

  function handleLogout() {
    localStorage.removeItem('workspace_token')
    router.replace('/')
  }

  const copy = status ? STATUS_COPY[status.subscription_status] : null
  const isLocked = status
    ? ['pending_payment', 'canceled', 'suspended'].includes(status.subscription_status)
    : false

  return (
    <div className="flex min-h-screen flex-col bg-zinc-950">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-950 px-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-600">
            <Zap className="h-3.5 w-3.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-zinc-100">Cloud Decoded</span>
        </div>
        <div className="flex items-center gap-1">
          {!isLocked && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title="Back to dashboard"
              onClick={() => router.push('/dashboard')}
            >
              <ArrowLeft className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-8 w-8" title="Sign out" onClick={handleLogout}>
            <LogOut className="h-3.5 w-3.5" />
          </Button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-lg flex-1 px-5 py-10">
        <h1 className="text-lg font-semibold text-zinc-100">Billing</h1>
        <p className="mt-1 text-sm text-zinc-500">Your plan, subscription status, and payment details.</p>

        {wasLocked && (
          <div className="mt-5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            Workspace access is currently locked — resolve your subscription below to get back in.
          </div>
        )}

        {loading && (
          <div className="mt-8 flex items-center justify-center py-10">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-zinc-700 border-t-blue-500" />
          </div>
        )}

        {error && !loading && (
          <div className="mt-5 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {status && !loading && (
          <div className="mt-6 rounded-xl border border-zinc-800 bg-zinc-900 p-6">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs uppercase tracking-wide text-zinc-500">Current plan</div>
                <div className="mt-1 text-xl font-semibold text-zinc-100">
                  {TIER_LABELS[status.tier] ?? status.tier}
                </div>
              </div>
              {copy && (
                <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${TONE_CLASSES[copy.tone]}`}>
                  {copy.label}
                </span>
              )}
            </div>

            <div className="mt-6 border-t border-zinc-800 pt-5">
              {status.subscription_status === 'pending_payment' && (
                <>
                  <p className="text-sm text-zinc-400">
                    Your workspace was created but checkout was never completed. Finish signing up to unlock access.
                  </p>
                  <Button className="mt-4 w-full" onClick={handleCompleteSignup}>
                    Complete signup →
                  </Button>
                </>
              )}

              {status.subscription_status === 'suspended' && (
                <p className="text-sm text-zinc-400">
                  This workspace was suspended for a Terms of Service violation. Contact support to appeal —
                  this can&apos;t be resolved through self-service billing.
                </p>
              )}

              {status.subscription_status === 'canceled' && (
                <>
                  <p className="text-sm text-zinc-400">
                    Your subscription was canceled. Reactivate it from the billing portal to restore access.
                  </p>
                  {status.has_billing_account ? (
                    <Button className="mt-4 w-full" disabled={portalLoading} onClick={handleManageBilling}>
                      {portalLoading ? 'Opening…' : 'Reactivate in billing portal →'}
                    </Button>
                  ) : (
                    <Button className="mt-4 w-full" onClick={handleCompleteSignup}>
                      Start a new subscription →
                    </Button>
                  )}
                </>
              )}

              {(status.subscription_status === 'active' ||
                status.subscription_status === 'trialing' ||
                status.subscription_status === 'past_due') && (
                <>
                  {status.subscription_status === 'past_due' && (
                    <p className="mb-4 text-sm text-amber-300">
                      Your last payment failed. Update your payment method to avoid losing access.
                    </p>
                  )}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm text-zinc-400">
                      <CreditCard className="h-4 w-4" />
                      Payment method and invoices are managed by Stripe
                    </div>
                  </div>
                  <Button
                    className="mt-4 w-full"
                    variant="outline"
                    disabled={!status.has_billing_account || portalLoading || MOCK_MODE}
                    onClick={handleManageBilling}
                  >
                    {MOCK_MODE ? 'Manage billing (disabled in demo)' : portalLoading ? 'Opening…' : 'Manage billing →'}
                  </Button>
                </>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default function BillingPage() {
  return (
    <Suspense fallback={null}>
      <BillingContent />
    </Suspense>
  )
}
