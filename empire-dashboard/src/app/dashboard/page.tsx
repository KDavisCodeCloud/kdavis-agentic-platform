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
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) {
        router.replace('/login')
      } else {
        setReady(true)
      }
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_e, session) => {
      if (!session) router.replace('/login')
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
