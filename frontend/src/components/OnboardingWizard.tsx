'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Check, Copy, ChevronRight, Zap, Key, Cloud, Webhook } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface OnboardingWizardProps {
  onComplete: (token: string) => void
}

type Step = 1 | 2 | 3

interface FormData {
  companyName: string
  workspaceToken: string
  llmProvider: 'anthropic' | 'openai'
  llmApiKey: string
  cloudProviders: string[]
}

const STEPS = [
  { id: 1 as Step, label: 'Workspace', icon: Zap },
  { id: 2 as Step, label: 'LLM Key',   icon: Key },
  { id: 3 as Step, label: 'Webhooks',  icon: Webhook },
]

export function OnboardingWizard({ onComplete }: OnboardingWizardProps) {
  const [step, setStep]         = useState<Step>(1)
  const [form, setForm]         = useState<FormData>({
    companyName:    '',
    workspaceToken: '',
    llmProvider:    'anthropic',
    llmApiKey:      '',
    cloudProviders: [],
  })
  const [copied, setCopied]     = useState<string | null>(null)

  function update(patch: Partial<FormData>) {
    setForm(f => ({ ...f, ...patch }))
  }

  function toggleCloud(provider: string) {
    update({
      cloudProviders: form.cloudProviders.includes(provider)
        ? form.cloudProviders.filter(p => p !== provider)
        : [...form.cloudProviders, provider],
    })
  }

  function copyToClipboard(text: string, key: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  function canAdvance(): boolean {
    if (step === 1) return form.companyName.length > 0 && form.workspaceToken.length > 0
    if (step === 2) return form.llmApiKey.length > 0
    return true
  }

  const webhookBase = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
  const githubWebhookUrl  = `${webhookBase}/api/v1/webhooks/github?token=${form.workspaceToken}`
  const azureWebhookUrl   = `${webhookBase}/api/v1/webhooks/azure-devops?token=${form.workspaceToken}`

  return (
    <div className="mx-auto w-full max-w-lg">
      {/* Step indicators */}
      <div className="mb-8 flex items-center justify-center gap-0">
        {STEPS.map((s, i) => {
          const done   = s.id < step
          const active = s.id === step
          const Icon   = s.icon
          return (
            <div key={s.id} className="flex items-center">
              <div className="flex flex-col items-center gap-1.5">
                <div className={cn(
                  'flex h-9 w-9 items-center justify-center rounded-full border-2 transition-all',
                  done   && 'border-emerald-500 bg-emerald-500',
                  active && 'border-blue-500 bg-blue-500/20',
                  !done && !active && 'border-zinc-700 bg-zinc-900',
                )}>
                  {done
                    ? <Check className="h-4 w-4 text-white" />
                    : <Icon className={cn('h-4 w-4', active ? 'text-blue-400' : 'text-zinc-600')} />
                  }
                </div>
                <span className={cn(
                  'text-xs font-medium',
                  active ? 'text-zinc-200' : 'text-zinc-600',
                )}>
                  {s.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div className={cn(
                  'mb-5 h-px w-16 transition-colors',
                  step > s.id ? 'bg-emerald-700' : 'bg-zinc-800',
                )} />
              )}
            </div>
          )
        })}
      </div>

      {/* Step content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.2 }}
          className="rounded-xl border border-zinc-800 bg-zinc-900 p-6"
        >
          {step === 1 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-zinc-100">Set up your workspace</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Enter your company name and the workspace token from your Cloud Decoded account.
                </p>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                    Company Name
                  </label>
                  <input
                    type="text"
                    value={form.companyName}
                    onChange={e => update({ companyName: e.target.value })}
                    placeholder="Acme Engineering"
                    className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                    Workspace Token
                  </label>
                  <input
                    type="password"
                    value={form.workspaceToken}
                    onChange={e => update({ workspaceToken: e.target.value })}
                    placeholder="ws_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                    className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-blue-500 focus:outline-none"
                  />
                  <p className="mt-1.5 text-xs text-zinc-600">
                    Find this in your Cloud Decoded account settings.
                  </p>
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-zinc-100">Connect your LLM key</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Cloud Decoded uses BYOK (Bring Your Own Key). Your key is encrypted at rest and
                  never shared with third parties.
                </p>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                    LLM Provider
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    {(['anthropic', 'openai'] as const).map(p => (
                      <button
                        key={p}
                        onClick={() => update({ llmProvider: p })}
                        className={cn(
                          'rounded-md border px-3 py-2.5 text-sm font-medium transition-colors',
                          form.llmProvider === p
                            ? 'border-blue-500 bg-blue-500/10 text-blue-300'
                            : 'border-zinc-700 bg-zinc-950 text-zinc-400 hover:border-zinc-600',
                        )}
                      >
                        {p === 'anthropic' ? 'Anthropic (Claude)' : 'OpenAI (GPT-4)'}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                    API Key
                  </label>
                  <input
                    type="password"
                    value={form.llmApiKey}
                    onChange={e => update({ llmApiKey: e.target.value })}
                    placeholder={form.llmProvider === 'anthropic' ? 'sk-ant-api03-…' : 'sk-proj-…'}
                    className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-blue-500 focus:outline-none"
                  />
                </div>

                <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs text-zinc-500 space-y-1">
                  <p className="font-medium text-zinc-400">BYOK Security Guarantee</p>
                  <p>• Encrypted with AES-256 (Fernet) before storage</p>
                  <p>• Decrypted in-memory only at the moment of each API call</p>
                  <p>• Never written to logs, audit trails, or incident records</p>
                  <p>• Revoked automatically on account cancellation</p>
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-5">
              <div>
                <h2 className="text-lg font-semibold text-zinc-100">Connect your CI/CD pipelines</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Add these webhook URLs to your CI/CD systems to start receiving triage alerts.
                </p>
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                  Which cloud providers do you use?
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: 'github',       label: 'GitHub Actions' },
                    { id: 'azure_devops', label: 'Azure DevOps' },
                    { id: 'aws',          label: 'AWS (coming soon)', disabled: true },
                    { id: 'gcp',          label: 'GCP (coming soon)', disabled: true },
                  ].map(p => (
                    <button
                      key={p.id}
                      disabled={p.disabled}
                      onClick={() => toggleCloud(p.id)}
                      className={cn(
                        'rounded-md border px-3 py-2 text-xs font-medium transition-colors',
                        p.disabled && 'cursor-not-allowed opacity-40',
                        form.cloudProviders.includes(p.id)
                          ? 'border-blue-500 bg-blue-500/10 text-blue-300'
                          : 'border-zinc-700 bg-zinc-950 text-zinc-400 hover:border-zinc-600',
                      )}
                    >
                      {form.cloudProviders.includes(p.id) && <Check className="mr-1.5 inline h-3 w-3" />}
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-3">
                {form.cloudProviders.includes('github') && (
                  <WebhookRow
                    label="GitHub Actions Webhook URL"
                    url={githubWebhookUrl}
                    hint="Settings → Webhooks → Add webhook · Content type: application/json · Event: Workflow runs"
                    copied={copied}
                    onCopy={url => copyToClipboard(url, 'github')}
                    copyKey="github"
                  />
                )}
                {form.cloudProviders.includes('azure_devops') && (
                  <WebhookRow
                    label="Azure DevOps Service Hook URL"
                    url={azureWebhookUrl}
                    hint="Project Settings → Service hooks → Web Hooks · Event: Build completed (Status: Failed)"
                    copied={copied}
                    onCopy={url => copyToClipboard(url, 'azure')}
                    copyKey="azure"
                  />
                )}
                {form.cloudProviders.length === 0 && (
                  <p className="text-xs text-zinc-600">Select a provider above to see your webhook URL.</p>
                )}
              </div>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {/* Navigation */}
      <div className="mt-4 flex items-center justify-between">
        <Button
          variant="ghost"
          size="sm"
          disabled={step === 1}
          onClick={() => setStep((s) => (s - 1) as Step)}
        >
          Back
        </Button>

        {step < 3 ? (
          <Button
            size="sm"
            disabled={!canAdvance()}
            onClick={() => setStep((s) => (s + 1) as Step)}
          >
            Continue <ChevronRight className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            size="sm"
            className="bg-emerald-700 hover:bg-emerald-600"
            onClick={() => onComplete(form.workspaceToken)}
          >
            <Check className="h-4 w-4" />
            Go to Dashboard
          </Button>
        )}
      </div>
    </div>
  )
}

function WebhookRow({
  label, url, hint, copied, onCopy, copyKey,
}: {
  label: string
  url: string
  hint: string
  copied: string | null
  onCopy: (url: string) => void
  copyKey: string
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 space-y-1.5">
      <p className="text-xs font-medium text-zinc-400">{label}</p>
      <div className="flex items-center gap-2">
        <code className="flex-1 truncate rounded bg-zinc-900 px-2 py-1 text-xs font-mono text-blue-300 border border-zinc-800">
          {url}
        </code>
        <button
          onClick={() => onCopy(url)}
          className="shrink-0 rounded border border-zinc-700 bg-zinc-800 p-1.5 text-zinc-400 hover:text-zinc-200"
        >
          {copied === copyKey
            ? <Check className="h-3.5 w-3.5 text-emerald-400" />
            : <Copy className="h-3.5 w-3.5" />
          }
        </button>
      </div>
      <p className="text-xs text-zinc-600">{hint}</p>
    </div>
  )
}
