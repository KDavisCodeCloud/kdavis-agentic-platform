'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Zap, LogOut, Settings, Activity, Shield, Layers, CreditCard, FileText, Users, Plug } from 'lucide-react'
import { IncidentConsole } from '@/components/IncidentConsole'
import { OpsHub } from '@/components/OpsHub'
import { ContentPipeline } from '@/components/ContentPipeline'
import OutreachPipeline from '@/components/OutreachPipeline'
import { IntegrationsDashboard } from '@/components/IntegrationsDashboard'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { getBillingPortalUrl } from '@/lib/api'

const MOCK_MODE  = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'
const DEMO_TOKEN = 'ws-test-001'

type DashTab = 'hitl' | 'ops' | 'content' | 'outreach' | 'integrations'

export default function DashboardPage() {
  const router                        = useRouter()
  const [token, setToken]             = useState<string | null>(null)
  const [hydrated, setHydrated]       = useState(false)
  const [activeTab, setActiveTab]     = useState<DashTab>('hitl')
  const [portalLoading, setPortalLoading] = useState(false)

  useEffect(() => {
    if (MOCK_MODE) {
      setToken(DEMO_TOKEN)
      setHydrated(true)
      return
    }
    const stored = localStorage.getItem('workspace_token')
    if (!stored) {
      router.replace('/')
      return
    }
    setToken(stored)
    setHydrated(true)
  }, [router])

  function handleLogout() {
    localStorage.removeItem('workspace_token')
    router.replace('/')
  }

  async function handleBillingPortal() {
    if (!token || MOCK_MODE) return
    setPortalLoading(true)
    try {
      const url = await getBillingPortalUrl(token)
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch {
      // Portal not available (e.g. no billing account yet) — silently ignore
    } finally {
      setPortalLoading(false)
    }
  }

  if (!hydrated || !token) return null

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
              title="Manage billing"
              disabled={portalLoading}
              onClick={handleBillingPortal}
            >
              <CreditCard className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            title="Settings"
            onClick={() => router.push('/onboarding')}
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
          onClick={() => setActiveTab('ops')}
          className={cn(
            'flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors',
            activeTab === 'ops'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-500 hover:text-zinc-300',
          )}
        >
          <Layers className="h-3.5 w-3.5" />
          Internal Ops
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
        {MOCK_MODE && (
          <span className="ml-auto text-xs text-zinc-700">
            Refresh page to reset demo
          </span>
        )}
      </div>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {activeTab === 'hitl'         && <IncidentConsole token={token} />}
        {activeTab === 'ops'          && <OpsHub />}
        {activeTab === 'content'      && <ContentPipeline token={token} />}
        {activeTab === 'outreach'     && <OutreachPipeline token={token} />}
        {activeTab === 'integrations' && <IntegrationsDashboard token={token} />}
      </main>
    </div>
  )
}
