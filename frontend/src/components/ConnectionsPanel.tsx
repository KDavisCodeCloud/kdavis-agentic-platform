'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

import { useCallback, useEffect, useState } from 'react'
import { Github, Cloud, CloudCog, GitBranch, Boxes, CheckCircle2, Circle, Key, AlertTriangle, Ticket, ChevronDown, Siren, KeyRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CodeBlock } from '@/components/ui/code-block'
import { cn } from '@/lib/utils'
import {
  getConnectionsStatus, getGithubAppInstallUrl, setupAwsRole, connectAwsRole, connectAzureServicePrincipal,
  connectAzureDevOps, connectK8sCluster, saveLlmKey, getTicketingStatus, connectJira, connectLinear, connectGithubIssues,
  connectServiceNow, getWorkspaceTokenStatus, rotateWorkspaceToken, isMemberSessionToken, API_URL,
  listExhaustedRetries,
} from '@/lib/api'
import type { ConnectionsStatus, AwsRoleSetup, TicketingStatus, WorkspaceTokenStatus, ExhaustedRetry } from '@/lib/types'

// Onboarding completeness build, item 3: the real webhook URL a customer
// pastes into Azure/AWS/GitHub/Azure DevOps. Only ever shown with a real
// embedded token when this session actually holds the raw workspace
// token (isMemberSessionToken(token) === false) -- a logged-in member
// session never has the raw token (it's a one-way hash server-side, see
// db/migrations/040_workspace_token_display_metadata.sql), so it gets a
// placeholder instead of a fabricated value.
function webhookUrl(path: string, token: string): string {
  const tokenParam = isMemberSessionToken(token) ? '<your-workspace-token>' : token
  return `${API_URL}/api/v1/webhooks/${path}?token=${tokenParam}`
}

function ExpandableInstructions({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2 rounded border border-zinc-800">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-xs font-medium text-zinc-300 hover:text-zinc-100"
      >
        <span>{title}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 text-zinc-500 transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="border-t border-zinc-800 px-3 py-3">{children}</div>}
    </div>
  )
}

// Connects a workspace's real credentials to the core platform's own
// Agents 01 (CI/CD), 02 (K8s Alert), 05 (IAM), 06 (FinOps), 08 (Drift) --
// distinct from the AgentConnectFlow.tsx form used by the FinOps/Compliance
// *agent* tabs, which proxies to the separately-deployed satellite products
// instead. Backend: api/routes/workspace_credentials.py (migration 022).

type TicketingProvider = 'jira' | 'linear' | 'github_issues' | 'servicenow'

const TICKETING_PROVIDER_LABELS: Record<TicketingProvider, string> = {
  jira: 'Jira',
  linear: 'Linear',
  github_issues: 'GitHub Issues',
  servicenow: 'ServiceNow',
}

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

  // Ticketing (Jira + Linear today; GitHub Issues/ServiceNow land in later
  // phases of this build) -- fires on incident RESOLUTION, not creation.
  // At most one ticketing channel at a time -- a provider tab selector
  // switches which config form is shown, matching whichever channel (if
  // any) is already connected.
  const [ticketingStatus, setTicketingStatus] = useState<TicketingStatus | null>(null)
  const [ticketingProvider, setTicketingProvider] = useState<TicketingProvider>('jira')
  const [jiraInstanceUrl, setJiraInstanceUrl] = useState('')
  const [jiraApiToken, setJiraApiToken] = useState('')
  const [jiraProjectKey, setJiraProjectKey] = useState('')
  const [jiraIssueType, setJiraIssueType] = useState('Task')
  const [jiraBusy, setJiraBusy] = useState(false)
  const [linearApiKey, setLinearApiKey] = useState('')
  const [linearTeamId, setLinearTeamId] = useState('')
  const [linearBusy, setLinearBusy] = useState(false)
  const [githubIssuesRepo, setGithubIssuesRepo] = useState('')
  const [githubIssuesBusy, setGithubIssuesBusy] = useState(false)
  const [snowInstanceUrl, setSnowInstanceUrl] = useState('')
  const [snowUsername, setSnowUsername] = useState('')
  const [snowPassword, setSnowPassword] = useState('')
  const [snowAssignmentGroup, setSnowAssignmentGroup] = useState('')
  const [snowBusy, setSnowBusy] = useState(false)

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

  // Workspace token (onboarding completeness build, item 4)
  const [tokenStatus, setTokenStatus] = useState<WorkspaceTokenStatus | null>(null)
  const [tokenBusy, setTokenBusy] = useState(false)
  const [rotatedToken, setRotatedToken] = useState<string | null>(null)

  // 24-gap-closure Phase 3 -- "flagged in dashboard" when an outbound
  // notification/ticketing send exhausted all 5 retry attempts.
  const [exhaustedRetries, setExhaustedRetries] = useState<ExhaustedRetry[]>([])

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

      // Token status is admin-only server-side (403 for viewer/approver
      // member sessions) -- fail silently here rather than surfacing the
      // panel-wide error banner for what's really just "this section
      // isn't for your role."
      if (connections.member_role === null || connections.member_role === 'admin') {
        try {
          setTokenStatus(await getWorkspaceTokenStatus(token))
        } catch {
          setTokenStatus(null)
        }
      }

      if (
        ticketing.channel?.channel_type === 'jira' ||
        ticketing.channel?.channel_type === 'linear' ||
        ticketing.channel?.channel_type === 'github_issues' ||
        ticketing.channel?.channel_type === 'servicenow'
      ) {
        setTicketingProvider(ticketing.channel.channel_type)
      }

      try {
        const retries = await listExhaustedRetries(token)
        setExhaustedRetries(retries.retries)
      } catch {
        setExhaustedRetries([])  // non-fatal -- this is a flag, not a core connection status
      }
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

  async function handleConnectLinear() {
    setLinearBusy(true)
    setError(null)
    try {
      await connectLinear(token, { api_key: linearApiKey.trim(), team_id: linearTeamId.trim() })
      setLinearApiKey('')
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save that Linear connection')
    } finally {
      setLinearBusy(false)
    }
  }

  async function handleConnectGithubIssues() {
    setGithubIssuesBusy(true)
    setError(null)
    try {
      await connectGithubIssues(token, { repo: githubIssuesRepo.trim() })
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save that GitHub Issues connection')
    } finally {
      setGithubIssuesBusy(false)
    }
  }

  async function handleConnectServiceNow() {
    setSnowBusy(true)
    setError(null)
    try {
      await connectServiceNow(token, {
        instance_url: snowInstanceUrl.trim(),
        username: snowUsername.trim(),
        password: snowPassword.trim(),
        assignment_group: snowAssignmentGroup.trim(),
      })
      setSnowPassword('')
      await load()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not save that ServiceNow connection')
    } finally {
      setSnowBusy(false)
    }
  }

  async function handleRotateToken() {
    setTokenBusy(true)
    setError(null)
    try {
      const result = await rotateWorkspaceToken(token)
      setRotatedToken(result.workspace_token)
      setTokenStatus({ last4: result.last4, rotated_at: result.rotated_at })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not rotate the workspace token')
    } finally {
      setTokenBusy(false)
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

        {exhaustedRetries.length > 0 && (
          <div className="flex items-start gap-2 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              {exhaustedRetries.length} outbound notification{exhaustedRetries.length > 1 ? 's' : ''} failed
              after 5 retry attempts and gave up
              {' '}({[...new Set(exhaustedRetries.map(r => r.channel_type))].join(', ')}).
              Check that channel&apos;s credentials are still valid.
            </span>
          </div>
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
          {status.github_via_legacy_pat && (
            <ExpandableInstructions title="How to set this up (legacy PAT webhook)">
              <div className="space-y-2 text-xs text-zinc-400">
                <p>Register a webhook in your repository&apos;s Settings → Webhooks:</p>
                <ul className="list-disc space-y-1 pl-4">
                  <li>Content type: <code className="text-zinc-300">application/json</code></li>
                  <li>Events: <strong className="text-zinc-300">Workflow runs</strong> (for CI/CD triage) and, if using PR review, <strong className="text-zinc-300">Pull requests</strong></li>
                  <li>Secret: the webhook secret shown when you first connected — register it as the webhook&apos;s secret so signatures verify</li>
                </ul>
                <CodeBlock label="Webhook URL" code={webhookUrl('github', token)} />
              </div>
            </ExpandableInstructions>
          )}
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
          <ExpandableInstructions title="How to set this up (service hook)">
            <div className="space-y-2 text-xs text-zinc-400">
              <p>In Azure DevOps: Project Settings → Service hooks → Create subscription → Web Hooks.</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>Trigger: <strong className="text-zinc-300">Build completed</strong>, with filter Status = Failed</li>
                <li>Basic authentication password: the webhook secret shown above when you first connected</li>
              </ul>
              <CodeBlock label="Webhook URL" code={webhookUrl('azure-devops', token)} />
            </div>
          </ExpandableInstructions>
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
          <ExpandableInstructions title="How to send K8s alerts here (Agent 02)">
            <div className="space-y-2 text-xs text-zinc-400">
              <p>Separate from the cluster connection above -- this is the alert-source
              registration so Agent 02 gets pod-failure alerts pushed in as they happen.</p>
              <p className="font-medium text-zinc-300">Prometheus Alertmanager (alertmanager.yml):</p>
              <CodeBlock label="alertmanager.yml" code={`receivers:\n  - name: cloud-decoded\n    webhook_configs:\n      - url: ${webhookUrl('aks-alert', token)}`} />
              <p className="font-medium text-zinc-300">Or as an Azure Monitor Action Group webhook action</p>
              <p>(same Common Alert Schema requirements as the Alert Ingestion section below -- register
              Microsoft.Insights + Microsoft.AlertsManagement first, use a plain Webhook action, turn
              Common Alert Schema ON):</p>
              <CodeBlock label="Webhook URL" code={webhookUrl('aks-alert', token)} />
            </div>
          </ExpandableInstructions>
        </SectionCard>

        <SectionCard
          icon={Siren}
          title="Alert Ingestion"
          description="General cloud-resource health/security alerts for Agent 11 -- any resource, not just Kubernetes. Register once; every alert from a connected source shows up automatically."
          connected={false}
        >
          <div className="space-y-3">
            <CodeBlock label="Webhook URL (Azure Action Group / AWS SNS subscription / Alertmanager / Grafana)" code={webhookUrl('resource-health-alert', token)} />

            <ExpandableInstructions title="How to set this up — Azure Monitor">
              <div className="space-y-2 text-xs text-zinc-400">
                <p className="text-amber-300">Live-verified setup path (see agents/agent_11_resource_health/sop.md for the full trace) --
                the two most common reasons this silently never fires are both covered below.</p>
                <ol className="list-decimal space-y-2 pl-4">
                  <li>
                    <strong className="text-zinc-300">Register the resource providers first</strong>, on the subscription:
                    <CodeBlock code={`az provider register --namespace Microsoft.Insights\naz provider register --namespace Microsoft.AlertsManagement`} />
                    Wait for both to report <code>Registered</code> (<code>az provider show --namespace Microsoft.Insights --query registrationState</code>) before continuing.
                  </li>
                  <li>
                    <strong className="text-zinc-300">Create the Action Group</strong>, then add an action of type <strong className="text-zinc-300">Webhook — not &quot;Secure Webhook&quot;</strong>.
                    Secure Webhook requires an Azure AD handshake this backend doesn&apos;t implement.
                  </li>
                  <li>
                    <strong className="text-zinc-300">Turn the &quot;Common Alert Schema&quot; toggle ON</strong> for the webhook action. Not optional —
                    the legacy schema is a different payload shape and is silently dropped (no error), so this is easy to miss.
                  </li>
                  <li>Paste the webhook URL above (already includes your token).</li>
                  <li>
                    <strong className="text-zinc-300">Test it</strong>: Action Group → Test action group → sample type Metric alert. If Azure reports
                    403 Forbidden, check for a stray space or line-break pasted into the token value.
                  </li>
                </ol>
              </div>
            </ExpandableInstructions>

            <ExpandableInstructions title="How to set this up — AWS (SNS / CloudWatch)">
              <div className="space-y-2 text-xs text-zinc-400">
                <p>Subscribe the URL above as an HTTPS endpoint on an SNS topic that your CloudWatch Alarms
                (or GuardDuty findings via EventBridge → SNS) publish to:</p>
                <CodeBlock code={`aws sns subscribe \\\n  --topic-arn arn:aws:sns:us-east-1:123456789012:cloud-decoded-alerts \\\n  --protocol https \\\n  --notification-endpoint "${webhookUrl('resource-health-alert', token)}"`} />
                <p>AWS sends a SubscriptionConfirmation once, immediately after this — confirmed automatically,
                nothing further needed on your side. Every Notification&apos;s signature is verified against
                AWS&apos;s own signing certificate before it&apos;s trusted.</p>
              </div>
            </ExpandableInstructions>
          </div>
        </SectionCard>

        <SectionCard
          icon={Ticket}
          title="Ticketing"
          description="Automatically open a ticket when an incident resolves -- Jira, Linear, GitHub Issues, and ServiceNow (Enterprise) today. A workspace can connect one ticketing system at a time."
          connected={!!ticketingStatus?.channel}
        >
          {ticketingStatus?.channel && ticketingStatus.channel.channel_type !== ticketingProvider && (
            <p className="mb-3 text-xs text-zinc-500">
              Currently connected to <span className="font-mono text-zinc-300">{ticketingStatus.channel.channel_type}</span>.
              Connecting {TICKETING_PROVIDER_LABELS[ticketingProvider]} below will replace it.
            </p>
          )}

          <div className="mb-3 flex gap-1 rounded-lg border border-zinc-800 bg-zinc-900/50 p-1">
            {(
              ticketingStatus?.product_tier === 'enterprise'
                ? (['jira', 'linear', 'github_issues', 'servicenow'] as const)
                : (['jira', 'linear', 'github_issues'] as const)
            ).map(provider => (
              <button
                key={provider}
                type="button"
                onClick={() => setTicketingProvider(provider)}
                className={cn(
                  'flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  ticketingProvider === provider
                    ? 'bg-zinc-800 text-zinc-100'
                    : 'text-zinc-500 hover:text-zinc-300',
                )}
              >
                {TICKETING_PROVIDER_LABELS[provider]}
              </button>
            ))}
          </div>

          {ticketingProvider === 'jira' ? (
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
          ) : ticketingProvider === 'linear' ? (
            <div className="space-y-2">
              <input
                type="password"
                value={linearApiKey}
                onChange={e => setLinearApiKey(e.target.value)}
                placeholder="Linear API key"
                className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <input
                type="text"
                value={linearTeamId}
                onChange={e => setLinearTeamId(e.target.value)}
                placeholder="Team ID"
                className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <Button
                size="sm"
                className="w-full"
                disabled={linearBusy || !linearApiKey.trim() || !linearTeamId.trim()}
                loading={linearBusy}
                onClick={handleConnectLinear}
              >
                {ticketingStatus?.channel?.channel_type === 'linear' ? 'Update Linear connection' : 'Connect Linear'}
              </Button>
            </div>
          ) : ticketingProvider === 'github_issues' ? (
            <div className="space-y-2">
              <p className="text-xs text-zinc-500">
                Uses the GitHub App connection above -- install it first if you haven&apos;t. Only the repo is
                needed here.
              </p>
              <input
                type="text"
                value={githubIssuesRepo}
                onChange={e => setGithubIssuesRepo(e.target.value)}
                placeholder="owner/repo (e.g. acme/infra)"
                className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <Button
                size="sm"
                className="w-full"
                disabled={githubIssuesBusy || !githubIssuesRepo.trim()}
                loading={githubIssuesBusy}
                onClick={handleConnectGithubIssues}
              >
                {ticketingStatus?.channel?.channel_type === 'github_issues'
                  ? 'Update GitHub Issues connection'
                  : 'Connect GitHub Issues'}
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-zinc-500">Enterprise tier only.</p>
              <input
                type="text"
                value={snowInstanceUrl}
                onChange={e => setSnowInstanceUrl(e.target.value)}
                placeholder="Instance URL (e.g. https://acme.service-now.com)"
                className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <input
                type="text"
                value={snowUsername}
                onChange={e => setSnowUsername(e.target.value)}
                placeholder="Username"
                className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <input
                type="password"
                value={snowPassword}
                onChange={e => setSnowPassword(e.target.value)}
                placeholder="Password"
                className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <input
                type="text"
                value={snowAssignmentGroup}
                onChange={e => setSnowAssignmentGroup(e.target.value)}
                placeholder="Assignment group"
                className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-blue-500/60 focus:outline-none"
              />
              <Button
                size="sm"
                className="w-full"
                disabled={
                  snowBusy ||
                  !snowInstanceUrl.trim() ||
                  !snowUsername.trim() ||
                  !snowPassword.trim() ||
                  !snowAssignmentGroup.trim()
                }
                loading={snowBusy}
                onClick={handleConnectServiceNow}
              >
                {ticketingStatus?.channel?.channel_type === 'servicenow'
                  ? 'Update ServiceNow connection'
                  : 'Connect ServiceNow'}
              </Button>
            </div>
          )}
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

        {(status.member_role === null || status.member_role === 'admin') && (
          <SectionCard
            icon={KeyRound}
            title="Workspace Token"
            description="Authenticates every request this workspace makes. There is no way to view the token after it was issued -- only rotate it for a new one."
            connected={!!tokenStatus}
          >
            {rotatedToken ? (
              <div className="space-y-2">
                <p className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                  Save this token now — it won&apos;t be shown again. The old token stopped working immediately;
                  it does <strong>not</strong> stay valid for a grace period today.
                </p>
                <CodeBlock label="New workspace token" code={rotatedToken} />
                <p className="text-xs text-zinc-500">Update every alert source and webhook registered above with this
                new token before they&apos;ll work again -- GitHub/Azure DevOps webhooks, Azure Action Groups, and
                any AWS SNS subscription all include the token in their URL.</p>
                <Button size="sm" onClick={() => setRotatedToken(null)}>Done</Button>
              </div>
            ) : (
              <div className="space-y-2">
                <p className="font-mono text-xs text-zinc-400">
                  {tokenStatus?.last4 ? `cd_ws_••••••••${tokenStatus.last4}` : 'cd_ws_•••••••• (no hint available yet -- rotate to get one)'}
                </p>
                {tokenStatus?.rotated_at && (
                  <p className="text-[11px] text-zinc-600">
                    Last rotated {new Date(tokenStatus.rotated_at).toLocaleDateString()}
                  </p>
                )}
                <Button size="sm" variant="warning" disabled={tokenBusy} loading={tokenBusy} onClick={handleRotateToken}>
                  Rotate token
                </Button>
              </div>
            )}
          </SectionCard>
        )}
      </div>
    </div>
  )
}

function RefreshingLabel() {
  return <p className="text-xs text-zinc-600">Loading connections…</p>
}
