'use client'

import { useState } from 'react'
import { Cloud } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CodeBlock } from '@/components/ui/code-block'
import type { AgentConnectionStatus } from '@/lib/types'

// Shared "connect an AWS account" flow for FinOpsAgentDashboard.tsx and
// ComplianceAgentDashboard.tsx -- both proxy to a separately-deployed
// Railway service with the exact same onboarding shape (POST /connect
// returns a trust/permissions policy JSON pair to paste into AWS, then
// PATCH .../aws-role verifies the resulting role ARN).

interface AgentConnectFlowProps {
  productName: string
  status: AgentConnectionStatus
  connecting: boolean
  verifying: boolean
  error: string | null
  onConnect: () => void
  onVerifyRole: (roleArn: string) => void
}

export function AgentConnectFlow({
  productName,
  status,
  connecting,
  verifying,
  error,
  onConnect,
  onVerifyRole,
}: AgentConnectFlowProps) {
  const [roleArn, setRoleArn] = useState('')

  if (!status.pending_setup) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
        <Cloud className="h-8 w-8 text-zinc-600" />
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Connect your AWS account</h3>
          <p className="mt-1 max-w-sm text-xs text-zinc-500">
            Grant {productName} read-only, revocable access via an IAM role. Nothing scans until you
            verify the role below.
          </p>
        </div>
        {error && (
          <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
        )}
        <Button size="sm" onClick={onConnect} disabled={connecting} loading={connecting}>
          Connect AWS Account
        </Button>
      </div>
    )
  }

  const setup = status.setup
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <div>
        <h3 className="text-sm font-semibold text-zinc-100">Finish connecting AWS</h3>
        <p className="mt-1 text-xs text-zinc-500">
          In AWS: create an IAM role using the trust policy below as its trust relationship, and
          attach the permissions policy as an inline policy (read-only, scoped to exactly what gets
          scanned). Then paste the role&apos;s ARN below.
        </p>
      </div>

      {setup && (
        <>
          <CodeBlock label="Trust policy" code={JSON.stringify(setup.aws_trust_policy, null, 2)} />
          <CodeBlock label="Permissions policy" code={JSON.stringify(setup.aws_permissions_policy, null, 2)} />
        </>
      )}

      {error && (
        <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={roleArn}
          onChange={e => setRoleArn(e.target.value)}
          placeholder="arn:aws:iam::123456789012:role/your-role"
          className="flex-1 rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
        />
        <Button
          size="sm"
          disabled={verifying || !roleArn.trim()}
          loading={verifying}
          onClick={() => onVerifyRole(roleArn.trim())}
        >
          Verify
        </Button>
      </div>
    </div>
  )
}
