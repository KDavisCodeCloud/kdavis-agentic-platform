'use client'

import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

// Shared with FinOpsAgentDashboard.tsx and ComplianceAgentDashboard.tsx --
// both need to display a JSON policy blob for the user to copy into AWS.
// Same visual shape as IntegrationsDashboard.tsx's local CodeBlock/CopyButton,
// factored out here since it now has two independent callers.

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1 text-xs text-zinc-500 transition-colors hover:text-zinc-200"
    >
      {copied ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

export function CodeBlock({ code, label, className }: { code: string; label?: string; className?: string }) {
  return (
    <div className={cn('overflow-hidden rounded-md border border-zinc-800 bg-zinc-900', className)}>
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-1.5">
        <span className="font-mono text-[10px] text-zinc-600">{label ?? 'code'}</span>
        <CopyButton text={code} />
      </div>
      <pre className="overflow-x-auto whitespace-pre p-3 font-mono text-xs leading-5 text-zinc-300">
        <code>{code}</code>
      </pre>
    </div>
  )
}
