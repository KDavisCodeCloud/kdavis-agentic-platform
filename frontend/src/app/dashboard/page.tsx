'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Zap, LogOut, Settings, Activity, Shield, CreditCard, FileText, Users, Plug, ClipboardList, DollarSign, ShieldCheck, Check, Copy, KeyRound } from 'lucide-react'
import { IncidentConsole } from '@/components/IncidentConsole'
import { ContentPipeline } from '@/components/ContentPipeline'
import OutreachPipeline from '@/components/OutreachPipeline'
import { IntegrationsDashboard } from '@/components/IntegrationsDashboard'
import { AuditDashboard } from '@/components/AuditDashboard'
import { FinOpsAgentDashboard } from '@/components/FinOpsAgentDashboard'
import { ComplianceAgentDashboard } from '@/components/ComplianceAgentDashboard'
import { ConnectionsPanel } from '@/components/ConnectionsPanel'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { getBillingStatus } from '@/lib/api'

const MOCK_MODE  = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'
const DEMO_TOKEN = 'ws-test-001'

type DashTab = 'hitl' | 'content' | 'outreach' | 'integrations' | 'audit' | 'finops-agent' | 'compliance-agent' | 'connections'

// Stripe's success_url (api/routes/stripe_billing.py) redirects here with
// ?checkout_success=1 -- the workspace only exists as a locked
// (pending_payment) sessionStorage token up to this point (see /signup,
// /checkout), since it's useless until Stripe's webhook actually fires.
// This polls briefly to absorb the race between the browser landing here
// and the webhook arriving, then promotes the token to a real logged-in
// session and reveals it once for the user to save.
function CheckoutSuccessGate({ onReady }: { onReady: (token: string) => void }) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const isCheckoutSuccess = searchParams.get('checkout_success') === '1'
  const [state, setState] = useState<'confirming' | 'ready' | 'error' | 'skip'>('confirming')
  const [revealedToken, setRevealedToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!isCheckoutSuccess) {
      setState('skip')
      return
    }
    const pending = sessionStorage.getItem('pending_workspace_token')
    if (!pending) {
      setState('skip')
      return
    }

    let cancelled = false
    async function poll() {
      for (let attempt = 0; attempt < 10; attempt++) {
        try {
          const status = await getBillingStatus(pending as string)
          if (status.subscription_status !== 'pending_payment') {
            if (cancelled) return
            localStorage.setItem('workspace_token', pending as string)
            sessionStorage.removeItem('pending_workspace_token')
            setRevealedToken(pending)
            setState('ready')
            return
          }
        } catch {
          // keep polling — the webhook may just not have landed yet
        }
        await new Promise(r => setTimeout(r, 1500))
      }
      if (!cancelled) setState('error')
    }
    poll()
    return () => { cancelled = true }
  }, [isCheckoutSuccess])

  if (state === 'skip') return null

  function finish() {
    if (revealedToken) onReady(revealedToken)
    // Land directly on Connections instead of a bare dashboard -- there was
    // previously no guided path from "just paid" to "has a working connected
    // workspace" at all.
    router.replace('/dashboard?tab=connections&welcome=1')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/95 backdrop-blur-sm">
      <div className="mx-4 w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900 p-7 text-center">
        {state === 'confirming' && (
          <>
            <div className="mx-auto mb-5 h-10 w-10 animate-spin rounded-full border-2 border-zinc-700 border-t-blue-500" />
            <h2 className="text-lg font-semibold text-zinc-100">Confirming your payment…</h2>
            <p className="mt-2 text-sm text-zinc-500">This usually takes a few seconds.</p>
          </>
        )}
        {state === 'error' && (
          <>
            <h2 className="text-lg font-semibold text-zinc-100">Still confirming</h2>
            <p className="mt-2 text-sm text-zinc-500">
              Stripe hasn&apos;t confirmed your payment yet. Refresh in a moment, or check your email for a receipt.
            </p>
          </>
        )}
        {state === 'ready' && revealedToken && (
          <>
            <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full border border-emerald-500/40 bg-emerald-500/10">
              <Check className="h-6 w-6 text-emerald-400" />
            </div>
            <h2 className="text-lg font-semibold text-zinc-100">Trial started — you&apos;re in.</h2>
            <p className="mt-2 text-sm text-zinc-500">Save your workspace access token now — it won&apos;t be shown again.</p>
            <div className="mt-4 flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950 p-3">
              <code className="flex-1 truncate font-mono text-xs text-blue-300">{revealedToken}</code>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(revealedToken)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 2000)
                }}
                className="shrink-0 rounded border border-zinc-700 bg-zinc-800 p-1.5 text-zinc-400 hover:text-zinc-200"
              >
                {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
            <Button className="mt-5 w-full" onClick={finish}>Connect your stack →</Button>
          </>
        )}
      </div>
    </div>
  )
}

const _VALID_TABS: DashTab[] = [
  'hitl', 'content', 'outreach', 'integrations', 'audit', 'finops-agent', 'compliance-agent', 'connections',
]

export default function DashboardPage() {
  const router                        = useRouter()
  const [token, setToken]             = useState<string | null>(null)
  const [hydrated, setHydrated]       = useState(false)
  const [activeTab, setActiveTab]     = useState<DashTab>('hitl')
  const [showWelcome, setShowWelcome] = useState(false)

  useEffect(() => {
    // Read once on mount, plain window.location like the checkout_success
    // check below -- avoids the Suspense boundary useSearchParams() would
    // otherwise require for this top-level page.
    const params = new URLSearchParams(window.location.search)
    const requestedTab = params.get('tab')
    if (requestedTab && (_VALID_TABS as string[]).includes(requestedTab)) {
      setActiveTab(requestedTab as DashTab)
    }
    if (params.get('welcome') === '1') setShowWelcome(true)
  }, [])

  useEffect(() => {
    if (MOCK_MODE) {
      setToken(DEMO_TOKEN)
      setHydrated(true)
      return
    }
    // Membership plan, Phase A: workspace_token (existing) takes priority
    // when both are present, matching lib/api.ts's request() -- but a
    // member-only login (no workspace token ever issued to that human)
    // must still reach the dashboard on their Supabase session alone.
    const stored = localStorage.getItem('workspace_token') || localStorage.getItem('member_session_token')
    if (!stored) {
      // A fresh checkout-success redirect hasn't promoted its sessionStorage
      // token to localStorage yet -- let CheckoutSuccessGate handle it
      // instead of bouncing straight back to the marketing page.
      const isCheckoutSuccess = new URLSearchParams(window.location.search).get('checkout_success') === '1'
      const hasPending = !!sessionStorage.getItem('pending_workspace_token')
      if (isCheckoutSuccess && hasPending) {
        setHydrated(true)
        return
      }
      router.replace('/login')
      return
    }
    setToken(stored)
    setHydrated(true)
  }, [router])

  function handleLogout() {
    localStorage.removeItem('workspace_token')
    localStorage.removeItem('member_session_token')
    router.replace('/')
  }

  if (!hydrated) return null
  if (!token) {
    return (
      <Suspense fallback={null}>
        <CheckoutSuccessGate onReady={setToken} />
      </Suspense>
    )
  }

  return (
    <div className="flex h-screen flex-col bg-zinc-950">
      {/* Top nav */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-950 px-5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-600">
            <Zap className="h-3.5 w-3.5 text-white" />
          </div>
          <span className="text-sm font-semibold text-zinc-100">Cloud Decoded</span>
          {MOCK_MODE && (
            <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-400">
              DEMO
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-8 w-8" title="Activity">
            <Activity className="h-3.5 w-3.5" />
          </Button>
          {!MOCK_MODE && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title="Billing"
              onClick={() => router.push('/billing')}
            >
              <CreditCard className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            title="Settings"
            // Used to route to /onboarding -- OnboardingWizard independently
            // creates a NEW workspace when reached from an already-logged-in
            // session, since it has no notion of the current session. The
            // Connections tab (LLM key included) is the real, safe settings
            // surface.
            onClick={() => setActiveTab('connections')}
          >
            <Settings className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            title="Sign out"
            onClick={handleLogout}
          >
            <LogOut className="h-3.5 w-3.5" />
          </Button>
        </div>
      </header>

      {/* Primary tab bar */}
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-zinc-800 bg-zinc-950 px-5">
        <button
          onClick={() => setActiveTab('hitl')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'hitl'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <Shield className="h-3.5 w-3.5" />
          HITL Console
        </button>
        <button
          onClick={() => setActiveTab('content')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'content'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <FileText className="h-3.5 w-3.5" />
          Content
        </button>
        <button
          onClick={() => setActiveTab('outreach')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'outreach'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <Users className="h-3.5 w-3.5" />
          Outreach
        </button>
        <button
          onClick={() => setActiveTab('integrations')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'integrations'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <Plug className="h-3.5 w-3.5" />
          Integrations
        </button>
        <button
          onClick={() => setActiveTab('audit')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'audit'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <ClipboardList className="h-3.5 w-3.5" />
          Cloud Audit
        </button>
        <button
          onClick={() => setActiveTab('finops-agent')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'finops-agent'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <DollarSign className="h-3.5 w-3.5" />
          FinOps
        </button>
        <button
          onClick={() => setActiveTab('compliance-agent')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'compliance-agent'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <ShieldCheck className="h-3.5 w-3.5" />
          Compliance
        </button>
        <button
          onClick={() => setActiveTab('connections')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'connections'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <KeyRound className="h-3.5 w-3.5" />
          Connections
        </button>
        {MOCK_MODE && (
          <span className="ml-auto text-xs text-zinc-700">
            Refresh page to reset demo
          </span>
        )}
      </div>

      {showWelcome && activeTab === 'connections' && (
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-blue-500/20 bg-blue-500/10 px-5 py-2.5 text-xs text-blue-200">
          <span>
            <strong className="font-semibold">Trial started.</strong> Connect a repo and a cloud account below
            so your agents have something real to look at — nothing runs without your approval in the HITL
            Console.
          </span>
          <button
            onClick={() => setShowWelcome(false)}
            className="shrink-0 text-blue-300 hover:text-blue-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {activeTab === 'hitl'         && <IncidentConsole token={token} />}
        {activeTab === 'content'      && <ContentPipeline token={token} />}
        {activeTab === 'outreach'     && <OutreachPipeline token={token} />}
        {activeTab === 'integrations' && <IntegrationsDashboard token={token} />}
        {activeTab === 'audit'        && <AuditDashboard token={token} />}
        {activeTab === 'finops-agent'     && <FinOpsAgentDashboard token={token} />}
        {activeTab === 'compliance-agent' && <ComplianceAgentDashboard token={token} />}
        {activeTab === 'connections'      && <ConnectionsPanel token={token} />}
      </main>
    </div>
  )
}
