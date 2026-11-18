'use client'

// Post-checkout setup (owner account at signup, 2026-11-18). The founder
// arrives signed in with their member session after Stripe confirms payment.
// This replaces the old OnboardingWizard, which created a second workspace
// and handed out the workspace token as a login. The token is now generated
// in Settings → Connections (shown once) and only used for webhooks and MCP.

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Cloud, GitBranch, Bell, Zap } from 'lucide-react'
import { SetupChecklistCard } from '@/components/SetupChecklistCard'
import { Button } from '@/components/ui/button'

const STEPS = [
  {
    icon: Cloud,
    title: 'Connect your cloud',
    body: 'Link an AWS role or Azure service principal. New connections start Read-Only: diagnosis runs, nothing is changed.',
    href: '/dashboard?tab=connections',
    cta: 'Open Connections',
  },
  {
    icon: GitBranch,
    title: 'Connect your repository',
    body: 'Install the Cloud Decoded GitHub App on the repositories that hold your infrastructure code, then map them.',
    href: '/dashboard?tab=integrations',
    cta: 'Open Integrations',
  },
  {
    icon: Bell,
    title: 'Send your alerts',
    body: 'Generate a workspace token in Connections (it is shown once), then use it in the webhook URL for Azure Monitor, CloudWatch or Prometheus.',
    href: '/dashboard?tab=connections',
    cta: 'Generate a token',
  },
]

export default function OnboardingPage() {
  const router = useRouter()
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    const session = localStorage.getItem('member_session_token')
    if (!session) {
      router.replace('/login')
      return
    }
    setToken(session)
  }, [router])

  if (!token) return null

  return (
    <div className="flex min-h-screen flex-col items-center bg-zinc-950 px-4 py-12">
      <div className="w-full max-w-2xl space-y-6">
        <div className="text-center">
          <div className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <h1 className="text-xl font-bold text-zinc-100">Welcome to Cloud Decoded</h1>
          <p className="mt-1 text-sm text-zinc-500">Three steps to your first diagnosed incident.</p>
        </div>

        <ol className="space-y-3">
          {STEPS.map((step, i) => (
            <li key={step.title} className="flex items-start gap-4 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-zinc-700 text-sm font-semibold text-zinc-300">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <step.icon className="h-4 w-4 text-zinc-400" />
                  <h2 className="text-sm font-semibold text-zinc-100">{step.title}</h2>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-zinc-500">{step.body}</p>
              </div>
              <Button size="sm" variant="outline" className="shrink-0" onClick={() => router.push(step.href)}>
                {step.cta}
              </Button>
            </li>
          ))}
        </ol>

        <SetupChecklistCard token={token} />

        <div className="text-center">
          <Button onClick={() => router.push('/dashboard')}>Go to the dashboard →</Button>
        </div>
      </div>
    </div>
  )
}
