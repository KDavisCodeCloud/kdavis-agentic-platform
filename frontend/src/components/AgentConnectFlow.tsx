'use client'

import { useState } from 'react'
import { Cloud } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CodeBlock } from '@/components/ui/code-block'
import { cn } from '@/lib/utils'
import type { AgentConnectionStatus, AzureServicePrincipalInput } from '@/lib/types'

// Shared "connect a cloud account" flow for FinOpsAgentDashboard.tsx and
// ComplianceAgentDashboard.tsx -- both proxy to a separately-deployed
// Railway service with the exact same onboarding shape for either cloud:
// POST /connect returns setup instructions for both AWS (trust/permissions
// policy JSON to paste in) and Azure (a Service Principal to create), then
// PATCH .../aws-role or .../verify-azure verifies the resulting credential.

interface AgentConnectFlowProps {
  productName: string
  status: AgentConnectionStatus
  connecting: boolean
  verifying: boolean
  error: string | null
  onConnect: () => void
  onVerifyRole: (roleArn: string) => void
  onVerifyAzure: (input: AzureServicePrincipalInput) => void
}

export function AgentConnectFlow({
  productName,
  status,
  connecting,
  verifying,
  error,
  onConnect,
  onVerifyRole,
  onVerifyAzure,
}: AgentConnectFlowProps) {
  const [provider, setProvider] = useState<'aws' | 'azure'>('aws')
  const [roleArn, setRoleArn] = useState('')
  const [azureTenantId, setAzureTenantId] = useState('')
  const [azureClientId, setAzureClientId] = useState('')
  const [azureClientSecret, setAzureClientSecret] = useState('')
  const [azureSubscriptionId, setAzureSubscriptionId] = useState('')

  const azureFormComplete =
    azureTenantId.trim() && azureClientId.trim() && azureClientSecret.trim() && azureSubscriptionId.trim()

  if (!status.pending_setup) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
        <Cloud className="h-8 w-8 text-zinc-600" />
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Connect your cloud account</h3>
          <p className="mt-1 max-w-sm text-xs text-zinc-500">
            Grant {productName} read-only, revocable access to your AWS or Azure account. Nothing
            scans until you verify the connection below.
          </p>
        </div>
        {error && (
          <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
        )}
        <Button size="sm" onClick={onConnect} disabled={connecting} loading={connecting}>
          Connect Cloud Account
        </Button>
      </div>
    )
  }

  const setup = status.setup

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <div>
        <h3 className="text-sm font-semibold text-zinc-100">Finish connecting your cloud account</h3>
      </div>

      <div className="flex gap-1 rounded-md border border-zinc-800 bg-zinc-900 p-1 text-xs">
        {(['aws', 'azure'] as const).map(p => (
          <button
            key={p}
            onClick={() => setProvider(p)}
            className={cn(
              'flex-1 rounded px-3 py-1.5 font-medium capitalize transition-colors',
              provider === p ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-500 hover:text-zinc-300',
            )}
          >
            {p}
          </button>
        ))}
      </div>

      {provider === 'aws' ? (
        <>
          <p className="text-xs text-zinc-500">
            In AWS: create an IAM role using the trust policy below as its trust relationship, and
            attach the permissions policy as an inline policy (read-only, scoped to exactly what gets
            scanned). Then paste the role&apos;s ARN below.
          </p>

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
        </>
      ) : (
        <>
          {setup && (
            <pre className="whitespace-pre-wrap rounded-lg border border-zinc-800 bg-zinc-900 p-3 font-mono text-[11px] leading-relaxed text-zinc-400">
              {setup.azure_setup_instructions}
            </pre>
          )}

          {error && (
            <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
          )}

          <div className="space-y-2">
            <input
              type="text"
              value={azureTenantId}
              onChange={e => setAzureTenantId(e.target.value)}
              placeholder="Azure tenant ID"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <input
              type="text"
              value={azureClientId}
              onChange={e => setAzureClientId(e.target.value)}
              placeholder="Client ID (appId)"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <input
              type="password"
              value={azureClientSecret}
              onChange={e => setAzureClientSecret(e.target.value)}
              placeholder="Client secret (password)"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <input
              type="text"
              value={azureSubscriptionId}
              onChange={e => setAzureSubscriptionId(e.target.value)}
              placeholder="Subscription ID"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <Button
              size="sm"
              className="w-full"
              disabled={verifying || !azureFormComplete}
              loading={verifying}
              onClick={() =>
                onVerifyAzure({
                  azure_tenant_id: azureTenantId.trim(),
                  client_id: azureClientId.trim(),
                  client_secret: azureClientSecret.trim(),
                  subscription_id: azureSubscriptionId.trim(),
                })
              }
            >
              Verify
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
