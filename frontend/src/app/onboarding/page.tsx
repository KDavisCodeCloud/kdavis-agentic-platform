'use client'

import { useRouter } from 'next/navigation'
import { Zap } from 'lucide-react'
import { motion } from 'framer-motion'
import { OnboardingWizard } from '@/components/OnboardingWizard'

export default function OnboardingPage() {
  const router = useRouter()

  function handleComplete(token: string) {
    localStorage.setItem('workspace_token', token)
    router.push('/dashboard')
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-zinc-950 px-4 py-12">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-lg"
      >
        {/* Header */}
        <div className="mb-8 text-center">
          <div className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600">
            <Zap className="h-5 w-5 text-white" />
          </div>
          <h1 className="text-xl font-bold text-zinc-100">Welcome to Cloud Decoded</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Get your first pipeline failure triaged in under 5 minutes.
          </p>
        </div>

        <OnboardingWizard onComplete={handleComplete} />

        <p className="mt-6 text-center text-xs text-zinc-700">
          Already set up?{' '}
          <button
            onClick={() => router.push('/')}
            className="text-blue-500 hover:text-blue-400"
          >
            Sign in
          </button>
        </p>
      </motion.div>
    </div>
  )
}
