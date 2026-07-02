'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Zap, ArrowRight, Shield, Clock, GitBranch } from 'lucide-react'
import { motion } from 'framer-motion'
import { Button } from '@/components/ui/button'
import { healthCheck } from '@/lib/api'

const MOCK_MODE = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'

export default function LandingPage() {
  const router               = useRouter()
  const [token, setToken]    = useState('')
  const [error, setError]    = useState('')
  const [apiUp, setApiUp]    = useState<boolean | null>(null)

  useEffect(() => {
    // In mock mode skip login entirely — go straight to the dashboard
    if (MOCK_MODE) {
      router.replace('/dashboard')
      return
    }
    // Redirect if already authenticated
    const stored = localStorage.getItem('workspace_token')
    if (stored) router.push('/dashboard')

    healthCheck().then(setApiUp)
  }, [router])

  function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    if (!token.trim()) {
      setError('Workspace token is required')
      return
    }
    localStorage.setItem('workspace_token', token.trim())
    router.push('/dashboard')
  }

  const features = [
    { icon: GitBranch, title: 'CI/CD Triage',    desc: 'Auto-diagnose pipeline failures in < 30 seconds' },
    { icon: Shield,    title: 'HITL Gate',        desc: 'Every fix requires explicit operator approval' },
    { icon: Clock,     title: 'Always Audited',   desc: 'Full audit trail for every agent action' },
  ]

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-zinc-950 px-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="w-full max-w-md"
      >
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600">
            <Zap className="h-6 w-6 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-zinc-100">Cloud Decoded</h1>
          <p className="mt-1 text-sm text-zinc-500">Autonomous DevOps agents with human oversight</p>
        </div>

        {/* Feature pills */}
        <div className="mb-6 flex flex-wrap justify-center gap-2">
          {features.map(f => (
            <div key={f.title} className="flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1 text-xs text-zinc-400">
              <f.icon className="h-3 w-3 text-blue-400" />
              {f.title}
            </div>
          ))}
        </div>

        {/* Login card */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-6">
          <h2 className="mb-4 text-sm font-semibold text-zinc-300">Sign in to your workspace</h2>
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                Workspace Token
              </label>
              <input
                type="password"
                value={token}
                onChange={e => { setToken(e.target.value); setError('') }}
                placeholder="ws_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2.5 font-mono text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-blue-500 focus:outline-none"
                autoComplete="current-password"
              />
              {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
            </div>
            <Button type="submit" className="w-full" size="default">
              Enter Dashboard <ArrowRight className="h-4 w-4" />
            </Button>
          </form>

          <div className="mt-4 border-t border-zinc-800 pt-4">
            <p className="text-center text-xs text-zinc-600">
              No account?{' '}
              <a href="#" className="text-blue-400 hover:text-blue-300">
                Start free trial
              </a>
              {' · '}
              <button
                type="button"
                onClick={() => router.push('/onboarding')}
                className="text-blue-400 hover:text-blue-300"
              >
                Setup wizard
              </button>
            </p>
          </div>
        </div>

        {/* API status */}
        {apiUp !== null && (
          <p className={`mt-3 text-center text-xs ${apiUp ? 'text-emerald-600' : 'text-red-600'}`}>
            API {apiUp ? 'online' : 'offline'} · {process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}
          </p>
        )}
      </motion.div>
    </div>
  )
}
