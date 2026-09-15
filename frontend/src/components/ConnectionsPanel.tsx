'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

import { useCallback, useEffect, useState } from 'react'
import { Github, Cloud, CloudCog, GitBranch, Boxes, CheckCircle2, Circle, Key, AlertTriangle, Ticket } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CodeBlock } from '@/components/ui/code-block'
import { cn } from '@/lib/utils'
import {
  getConnectionsStatus, getGithubAppInstallUrl, setupAwsRole, connectAwsRole, connectAzureServicePrincipal,
  connectAzureDevOps, connectK8sCluster, saveLlmKey, getTicketingStatus, connectJira,
} from '@/lib/api'
import type { ConnectionsStatus, AwsRoleSetup, TicketingStatus } from '@/lib/types'

// Connects a workspace's real credentials to the core platform's own
// Agents 01 (CI/CD), 02 (K8s Alert), 05 (IAM), 06 (FinOps), 08 (Drift) --
// distinct from the AgentConnectFlow.tsx form used by the FinOps/Compliance
// *agent* tabs, which proxies to the separately-deployed satellite products
// instead. Backend: api/routes/workspace_credentials.py (migration 022).

interface ConnectionsPanelProps {
  token: string
}

function StatusPill({ connected }: { connected: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-mono font-medium',
        connected
          ? 'bg-green-500/10 text-green-400'
          : 'bg-zinc-800 text-zinc-500',
      )}
    >
      {connected ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
      {connected ? 'Connected' : 'Not connected'}
    </span>
  )
}

function SectionCard({
  icon: Icon,
  title,
  description,
  connected,
  children,
}: {
  icon: typeof Github
  title: string
  description: string
  connected: boolean
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-zinc-400" />
          <h3 className="text-sm font-semibold text-zinc-100">{title}</h3>
        </div>
        <StatusPill connected={connected} />
      </div>
      <p className="mb-4 text-xs text-zinc-500">{description}</p>
      {children}
    </div>
  )
}

export function ConnectionsPanel({ token }: ConnectionsPanelProps) {
  const [status, setStatus] = useState<ConnectionsStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Ticketing (Jira today; Linear/GitHub Issues/ServiceNow land in later
  // phases of this build) -- fires on incident RESOLUTION, not creation.
  // At most one ticketing channel at a time.
  const [ticketingStatus, setTicketingStatus] = useState<TicketingStatus | null>(null)
  const [jiraInstanceUrl, setJiraInstanceUrl] = useState('')
  const [jiraApiToken, setJiraApiToken] = useState('')
  const [jiraProjectKey, setJiraProjectKey] = useState('')
  const [jiraIssueType, setJiraIssueType] = useState('Task')
  const [jiraBusy, setJiraBusy] = useState(false)

  // GitHub -- item 4 App migration: no PAT form, just an install-URL redirect
  const [githubBusy, setGithubBusy] = useState(false)

  // AWS
  const [awsSetup, setAwsSetup] = useState<AwsRoleSetup | null>(null)
  const [awsRoleArn, setAwsRoleArn] = useState('')
  const [awsBusy, setAwsBusy] = useState(false)

  // Azure
  const [azureTenantId, setAzureTenantId] = useState('')
  const [azureClientId, setAzureClientId] = useState('')
  const [azureClientSecret, setAzureClientSecret] = useState('')
  const [azureSubscriptionId, setAzureSubscriptionId] = useState('')
  const [azureBusy, setAzureBusy] = useState(false)

  // Azure DevOps
  const [adoOrg, setAdoOrg] = useState('')
  const [adoPat, setAdoPat] = useState('')
  const [adoBusy, setAdoBusy] = useState(false)
  const [adoWebhookSecret, setAdoWebhookSecret] = useState<string | null>(null)

  // Kubernetes
  const [k8sApiUrl, setK8sApiUrl] = useState('')
  const [k8sToken, setK8sToken] = useState('')
  const [k8sCaCert, setK8sCaCert] = useState('')
  const [k8sBusy, setK8sBusy] = useState(false)

  // LLM key (BYOK) -- previously only settable via the disconnected/stale
  // OnboardingWizard, which re-creates a whole new workspace if reached from
  // an already-logged-in session. This is the real, safe home for it.
  const [llmProvider, setLlmProvider] = useState<'anthropic' | 'openai'>('anthropic')
  const [llmApiKey, setLlmApiKey] = useState('')
  const [llmBusy, setLlmBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [connections, ticketing] = await Promise.all([
        getConnectionsStatus(token),
        getTicketingStatus(token),
      ])
      setStatus(connections)
      setTicketingStatus(ticketing)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load connection status')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  async function handleInstallGithubApp() {
    setGithubBusy(true)
    setError(null)
    try {
      const { install_url } = await getGithubAppInstallUrl(token)
      window.location.href = install_url
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start the GitHub App install flow')
      setGithubBusy(false)
    }
    // No finally: a successful call navigates away immediately, so leaving
    // githubBusy=true avoids a flash of the enabled button before redirect.
  }

  async function handleStartAwsSetup() {
    setAwsBusy(true)
    setError(null)
    try {
      setAwsSetup(await setupAwsRole(token))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start AWS role setup')
    } finally {
      setAwsBusy(false)
    }
  }

  async function handleVerifyAwsRole() {
    setAwsBusy(true)
    setError(null)
    try {
      await connectAwsRole(token, awsRoleArn.trim())
      setAwsSetup(null)
      setAwsRoleArn('')
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not verify that role')
    } finally {
      setAwsBusy(false)
    }
  }

  async function handleConnectAzure() {
    setAzureBusy(true)
    setError(null)
    try {
      await connectAzureServicePrincipal(token, {
        azure_tenant_id: azureTenantId.trim(),
        client_id: azureClientId.trim(),
        client_secret: azureClientSecret.trim(),
        subscription_id: azureSubscriptionId.trim(),
      })
      setAzureTenantId('')
      setAzureClientId('')
      setAzureClientSecret('')
      setAzureSubscriptionId('')
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not verify that Service Principal')
    } finally {
      setAzureBusy(false)
    }
  }

  async function handleConnectAzureDevOps() {
    setAdoBusy(true)
    setError(null)
    try {
      const result = await connectAzureDevOps(token, { org: adoOrg.trim(), pat: adoPat.trim() })
      if (result.webhook_secret) setAdoWebhookSecret(result.webhook_secret)
      setAdoPat('')
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not verify that Azure DevOps PAT')
    } finally {
      setAdoBusy(false)
    }
  }

  async function handleConnectK8s() {
    setK8sBusy(true)
    setError(null)
    try {
      await connectK8sCluster(token, {
        api_url: k8sApiUrl.trim(),
        token: k8sToken.trim(),
        ca_cert: k8sCaCert.trim() || undefined,
      })
      setK8sToken('')
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not verify cluster access')
    } finally {
      setK8sBusy(false)
    }
  }

  async function handleConnectJira() {
    setJiraBusy(true)
    setError(null)
    try {
      await connectJira(token, {
        instance_url: jiraInstanceUrl.trim(),
        api_token: jiraApiToken.trim(),
        project_key: jiraProjectKey.trim(),
        issue_type: jiraIssueType.trim() || 'Task',
      })
      setJiraApiToken('')
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save that Jira connection')
    } finally {
      setJiraBusy(false)
    }
  }

  async function handleSaveLlmKey() {
    setLlmBusy(true)
    setError(null)
    try {
      await saveLlmKey(token, llmProvider, llmApiKey.trim())
      setLlmApiKey('')
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save that LLM key')
    } finally {
      setLlmBusy(false)
    }
  }

  if (loading || !status) {
    return (
      <div className="flex h-full items-center justify-center">
        <RefreshingLabel />
      </div>
    )
  }

  const azureFormComplete =
    azureTenantId.trim() && azureClientId.trim() && azureClientSecret.trim() && azureSubscriptionId.trim()

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl space-y-4">
        <div>
          <h2 className="text-base font-semibold text-zinc-100">Connections</h2>
          <p className="mt-1 text-xs text-zinc-500">
            Grant Cloud Decoded scoped, revocable access to your repo and cloud accounts so Agents 01
            (CI/CD), 05 (IAM), 06 (FinOps), and 08 (Drift) can act on your real infrastructure. Every
            correction still requires your approval in the HITL Console.
          </p>
        </div>

        {error && (
          <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <SectionCard
          icon={Github}
          title="GitHub"
          description="The Cloud Decoded GitHub App -- fine-grained, revocable access to read IaC files and open remediation PRs. Commits are attributed to Cloud Decoded, not a personal token."
          connected={status.github_connected}
        >
          {status.github_via_legacy_pat && (
            <div className="mb-3 flex items-start gap-2 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Still connected via a legacy personal access token. Install the GitHub App instead for
                fine-grained, revocable access and commits attributed to Cloud Decoded.
              </span>
            </div>
          )}
          <Button
            size="sm"
            disabled={githubBusy}
            loading={githubBusy}
            onClick={handleInstallGithubApp}
          >
            {status.github_via_legacy_pat
              ? 'Migrate to the GitHub App'
              : status.github_connected
                ? 'Reinstall / manage on GitHub'
                : 'Install the Cloud Decoded GitHub App'}
          </Button>
        </SectionCard>

        <SectionCard
          icon={Cloud}
          title="AWS"
          description="A cross-account IAM role, assumed with an external ID -- never a raw access key."
          connected={status.aws_connected}
        >
          {!awsSetup ? (
            <Button size="sm" disabled={awsBusy} loading={awsBusy} onClick={handleStartAwsSetup}>
              {status.aws_connected ? 'Reconnect a different role' : 'Start AWS role setup'}
            </Button>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-zinc-500">
                Create an IAM role in your AWS account using the trust policy below as its trust
                relationship, and attach the permissions policy as an inline policy. Then paste the
                role&apos;s ARN below.
              </p>
              <CodeBlock label="Trust policy" code={JSON.stringify(awsSetup.trust_policy, null, 2)} />
              <CodeBlock label="Permissions policy" code={JSON.stringify(awsSetup.permissions_policy, null, 2)} />
              <div className="flex gap-2">
                <input
                  type="text"
                  value={awsRoleArn}
                  onChange={e => setAwsRoleArn(e.target.value)}
                  placeholder="arn:aws:iam::123456789012:role/your-role"
                  className="flex-1 rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
                />
                <Button
                  size="sm"
                  disabled={awsBusy || !awsRoleArn.trim()}
                  loading={awsBusy}
                  onClick={handleVerifyAwsRole}
                >
                  Verify
                </Button>
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard
          icon={CloudCog}
          title="Azure"
          description="A Service Principal with Contributor access -- this platform's agents write, not just read."
          connected={status.azure_connected}
        >
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
              disabled={azureBusy || !azureFormComplete}
              loading={azureBusy}
              onClick={handleConnectAzure}
            >
              {status.azure_connected ? 'Update' : 'Verify'}
            </Button>
          </div>
        </SectionCard>

        <SectionCard
          icon={GitBranch}
          title="Azure DevOps"
          description="A Personal Access Token scoped to Code (Read & Write), used to read IaC files and open remediation PRs in Azure Repos."
          connected={status.azure_devops_connected}
        >
          {adoWebhookSecret && (
            <div className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 p-3">
              <p className="mb-1 text-xs font-medium text-amber-300">
                Save this webhook secret now — it won&apos;t be shown again. Register it as your Azure
                DevOps service hook&apos;s Basic auth password.
              </p>
              <code className="block truncate font-mono text-xs text-amber-200">{adoWebhookSecret}</code>
            </div>
          )}
          <div className="space-y-2">
            <input
              type="text"
              value={adoOrg}
              onChange={e => setAdoOrg(e.target.value)}
              placeholder="Organization (e.g. acme-org)"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <div className="flex gap-2">
              <input
                type="password"
                value={adoPat}
                onChange={e => setAdoPat(e.target.value)}
                placeholder="Personal access token"
                className="flex-1 rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <Button
                size="sm"
                disabled={adoBusy || !adoOrg.trim() || !adoPat.trim()}
                loading={adoBusy}
                onClick={handleConnectAzureDevOps}
              >
                {status.azure_devops_connected ? 'Update' : 'Connect'}
              </Button>
            </div>
          </div>
        </SectionCard>

        <SectionCard
          icon={Boxes}
          title="Kubernetes"
          description="A service-account bearer token for your cluster's API server, used by Agents 02 (K8s Alert) and 08 (Drift) to read state and apply corrections."
          connected={status.k8s_connected}
        >
          <div className="space-y-2">
            <input
              type="text"
              value={k8sApiUrl}
              onChange={e => setK8sApiUrl(e.target.value)}
              placeholder="Cluster API server URL (e.g. https://xxxx.eks.amazonaws.com)"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <input
              type="password"
              value={k8sToken}
              onChange={e => setK8sToken(e.target.value)}
              placeholder="Service account bearer token"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <textarea
              value={k8sCaCert}
              onChange={e => setK8sCaCert(e.target.value)}
              placeholder="Cluster CA certificate (PEM) -- optional, required for most real clusters (EKS/AKS use a private CA)"
              rows={3}
              className="w-full resize-none rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <Button
              size="sm"
              className="w-full"
              disabled={k8sBusy || !k8sApiUrl.trim() || !k8sToken.trim()}
              loading={k8sBusy}
              onClick={handleConnectK8s}
            >
              {status.k8s_connected ? 'Update' : 'Verify'}
            </Button>
          </div>
        </SectionCard>

        <SectionCard
          icon={Ticket}
          title="Ticketing"
          description="Automatically open a ticket when an incident resolves -- Jira today, more providers landing soon. A workspace can connect one ticketing system at a time."
          connected={!!ticketingStatus?.channel}
        >
          {ticketingStatus?.channel && ticketingStatus.channel.channel_type !== 'jira' && (
            <p className="mb-3 text-xs text-zinc-500">
              Currently connected to <span className="font-mono text-zinc-300">{ticketingStatus.channel.channel_type}</span>.
              Connecting Jira below will replace it.
            </p>
          )}
          <div className="space-y-2">
            <input
              type="text"
              value={jiraInstanceUrl}
              onChange={e => setJiraInstanceUrl(e.target.value)}
              placeholder="Jira instance URL (e.g. https://acme.atlassian.net)"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <input
              type="password"
              value={jiraApiToken}
              onChange={e => setJiraApiToken(e.target.value)}
              placeholder="API token"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
            />
            <div className="flex gap-2">
              <input
                type="text"
                value={jiraProjectKey}
                onChange={e => setJiraProjectKey(e.target.value)}
                placeholder="Project key (e.g. OPS)"
                className="flex-1 rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <input
                type="text"
                value={jiraIssueType}
                onChange={e => setJiraIssueType(e.target.value)}
                placeholder="Issue type"
                className="w-28 rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
            </div>
            <Button
              size="sm"
              className="w-full"
              disabled={jiraBusy || !jiraInstanceUrl.trim() || !jiraApiToken.trim() || !jiraProjectKey.trim()}
              loading={jiraBusy}
              onClick={handleConnectJira}
            >
              {ticketingStatus?.channel?.channel_type === 'jira' ? 'Update Jira connection' : 'Connect Jira'}
            </Button>
          </div>
        </SectionCard>

        <SectionCard
          icon={Key}
          title="LLM Key"
          description="Bring your own LLM API key (Anthropic or OpenAI). Encrypted at rest, decrypted only for the duration of the call that needs it."
          connected={status.llm_configured}
        >
          {status.llm_configured && (
            <p className="mb-3 text-xs text-zinc-500">
              Currently using <span className="font-mono text-zinc-300">{status.llm_provider}</span>. Save a new
              key below to replace it.
            </p>
          )}
          <div className="space-y-2">
            <select
              value={llmProvider}
              onChange={e => setLlmProvider(e.target.value as 'anthropic' | 'openai')}
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-200 focus:border-blue-500/60 focus:outline-none"
            >
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
            </select>
            <div className="flex gap-2">
              <input
                type="password"
                value={llmApiKey}
                onChange={e => setLlmApiKey(e.target.value)}
                placeholder={llmProvider === 'anthropic' ? 'sk-ant-...' : 'sk-...'}
                className="flex-1 rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <Button
                size="sm"
                disabled={llmBusy || !llmApiKey.trim()}
                loading={llmBusy}
                onClick={handleSaveLlmKey}
              >
                {status.llm_configured ? 'Update' : 'Save'}
              </Button>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  )
}

function RefreshingLabel() {
  return <p className="text-xs text-zinc-600">Loading connections…</p>
}
