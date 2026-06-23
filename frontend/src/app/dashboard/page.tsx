'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Zap, LogOut, Settings, Activity } from 'lucide-react'
import { IncidentConsole } from '@/components/IncidentConsole'
import { Button } from '@/components/ui/button'

export default function DashboardPage() {
  const router                   = useRouter()
  const [token, setToken]        = useState<string | null>(null)
  const [hydrated, setHydrated]  = useState(false)

  useEffect(() => {
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
          <span className="rounded border border-zinc-800 px-1.5 py-0.5 text-xs text-zinc-600">
            HITL Console
          </span>
        </div>

        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-8 w-8" title="Activity">
            <Activity className="h-3.5 w-3.5" />
          </Button>
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

      {/* Main content — fills remaining height */}
      <main className="flex-1 overflow-hidden">
        <IncidentConsole token={token} />
      </main>
    </div>
  )
}
