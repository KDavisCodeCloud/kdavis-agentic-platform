'use client'

export const dynamic = 'force-dynamic'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import { DashboardProvider } from '@/lib/DashboardContext'
import { Dashboard } from '@/components/Dashboard'

export default function DashboardPage() {
  const [ready, setReady] = useState(false)
  const router = useRouter()

  useEffect(() => {
    // Implicit flow: tokens arrive in the URL hash (#access_token=...).
    // detectSessionInUrl processes the hash automatically, then fires
    // onAuthStateChange with SIGNED_IN. We must NOT redirect to login
    // before that event fires — check the URL first.
    const hasAuthInUrl =
      window.location.hash.includes('access_token') ||
      window.location.search.includes('code=')

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (session) {
        // Clear the hash from the URL so it doesn't show in the address bar
        if (window.location.hash) {
          window.history.replaceState(null, '', window.location.pathname)
        }
        setReady(true)
      } else if (event === 'SIGNED_OUT') {
        router.replace('/login')
      } else if (event === 'INITIAL_SESSION' && !hasAuthInUrl) {
        // No existing session and no tokens incoming — send to login
        router.replace('/login')
      }
    })

    return () => subscription.unsubscribe()
  }, [router])

  if (!ready) return <div className="loading-screen">Loading…</div>

  return (
    <DashboardProvider>
      <Dashboard />
    </DashboardProvider>
  )
}
