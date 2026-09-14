// Cloud Decoded — Mock data for NEXT_PUBLIC_MOCK_MODE=true
// All state lives in-memory only. Refreshing the page resets everything.

import type {
  AgentConnectionStatus,
  AuditSubmissionDetail,
  AuditSubmissionSummary,
  AwsRoleSetup,
  ComplianceReportData,
  ConnectionsStatus,
  FinOpsDashboardData,
  FinOpsHitlItem,
  Incident,
} from './types'

function ago(mins: number): string {
  return new Date(Date.now() - mins * 60_000).toISOString()
}

// ── Customer-Facing Agents 01-10 — HITL Incident Mock Data ───────────

const MOCK_INCIDENTS: Incident[] = [
  {
    incident_id: 'a1b2c3d4-e5f6-7890-abcd-ef1234567801',
    status: 'pending_approval',
    agent_id: 'agent_01_cicd_triage',
    cloud_provider: 'aws',
    repository: 'stackbridge/payments-api',
    branch: 'main',
    job_name: 'deploy-production',
    parsed_error:
      'GitHub Actions deploy-production job failed: IAM role github-deploy-role lacks s3:PutObject on prod-assets-bucket. Build artifacts cannot be uploaded and the deploy is blocked.',
    estimated_duration_seconds: 45,
    created_at: ago(3),
    options: [
      {
        id: 'opt_1',
        title: 'Apply least-privilege S3 policy patch',
        description:
          'Attach a targeted inline policy granting s3:PutObject and s3:GetObject on prod-assets-bucket only. No existing permissions are revoked. Verified against CIS AWS Benchmark 1.4.',
        impact: 'high',
        docs_url: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html',
      },
      {
        id: 'opt_2',
        title: 'Update prod-assets-bucket resource policy instead',
        description:
          'Modify the bucket policy to allow the deploy role. Lower blast radius than an IAM policy change, but requires confirming bucket ownership first.',
        impact: 'medium',
        docs_url:
          'https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-policies.html',
      },
      {
        id: 'hold',
        title: 'Hold — investigate manually',
        description: 'Pause automated remediation and escalate to a senior engineer.',
        impact: 'low',
        docs_url: '',
      },
    ],
  },
  {
    incident_id: 'b2c3d4e5-f6a7-8901-bcde-f12345678902',
    status: 'pending_approval',
    agent_id: 'agent_02_k8s_alert',
    cloud_provider: 'azure',
    repository: 'stackbridge/platform-services',
    branch: 'main',
    job_name: 'payment-service',
    parsed_error:
      'OOMKilled: payment-service pod crashed 4× in 30 minutes. Memory limit 512Mi exceeded under a 3.2× traffic spike. Remaining replicas are degraded.',
    estimated_duration_seconds: 90,
    created_at: ago(7),
    options: [
      {
        id: 'opt_1',
        title: 'Scale memory limit from 512Mi → 1Gi',
        description:
          'Patch deployment/payment-service resources.limits.memory. HPA redistributes load. Rolling restart with zero downtime.',
        impact: 'high',
        docs_url:
          'https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/',
      },
      {
        id: 'opt_2',
        title: 'Scale replicas from 3 → 6',
        description:
          'Double replica count to spread memory pressure horizontally. No restart required. Adds ~$180/month at current node pricing.',
        impact: 'medium',
        docs_url:
          'https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#scaling-a-deployment',
      },
      {
        id: 'hold',
        title: 'Hold — investigate manually',
        description: 'Pause automated remediation.',
        impact: 'low',
        docs_url: '',
      },
    ],
  },
  {
    incident_id: 'c3d4e5f6-a7b8-9012-cdef-123456789003',
    status: 'pending_approval',
    agent_id: 'agent_05_iam_minimizer',
    cloud_provider: 'aws',
    repository: 'stackbridge/infra-iam',
    branch: 'main',
    parsed_error:
      'IAM audit: ci_deploy_role has Action:* on Resource:*. Full AWS admin access is granted to the GitHub Actions deployment role — any compromised token is a full account takeover.',
    estimated_duration_seconds: 120,
    created_at: ago(15),
    options: [
      {
        id: 'opt_1',
        title: 'Replace wildcard with least-privilege policy',
        description:
          'Generate and apply a minimum-permission policy from 30-day CloudTrail usage. 847 allowed actions → 23 required actions.',
        impact: 'high',
        docs_url: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html',
      },
      {
        id: 'opt_2',
        title: 'Open PR with policy diff for human review',
        description:
          'Generate the least-privilege policy as a GitHub PR only — no automated apply. Adds 1-3 days but gives peer review.',
        impact: 'medium',
        docs_url:
          'https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_manage.html',
      },
      {
        id: 'hold',
        title: 'Hold — investigate manually',
        description: 'Pause automated remediation.',
        impact: 'low',
        docs_url: '',
      },
    ],
  },
  {
    incident_id: 'd4e5f6a7-b8c9-0123-defa-234567890104',
    status: 'pending_approval',
    agent_id: 'agent_08_drift_detection',
    cloud_provider: 'aws',
    repository: 'stackbridge/terraform-infra',
    branch: 'main',
    parsed_error:
      'IaC drift: RDS security group sg-prod-db has port 5432 open to 0.0.0.0/0. Terraform state says it should be VPC-only. Live infrastructure diverged from declared state.',
    estimated_duration_seconds: 60,
    created_at: ago(22),
    options: [
      {
        id: 'opt_1',
        title: 'Open Terraform PR to close public PostgreSQL port',
        description:
          'Commit corrected aws_security_group_rule to a fix branch, open PR #848. Plan: 1 to add, 0 to change, 0 to destroy. Slack alert sent to #infra-security.',
        impact: 'high',
        docs_url:
          'https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group_rule',
      },
      {
        id: 'opt_2',
        title: 'Apply drift correction directly via terraform apply',
        description:
          'Run terraform apply targeting only the security group rule. Faster but bypasses peer review. Requires elevated Terraform Cloud permissions.',
        impact: 'high',
        docs_url: 'https://developer.hashicorp.com/terraform/cli/commands/apply',
      },
      {
        id: 'hold',
        title: 'Hold — investigate manually',
        description: 'Pause automated remediation.',
        impact: 'low',
        docs_url: '',
      },
    ],
  },
  {
    incident_id: 'e5f6a7b8-c9d0-1234-efab-345678901205',
    status: 'executing',
    agent_id: 'agent_03_pr_review',
    cloud_provider: 'aws',
    repository: 'stackbridge/payments-api',
    branch: 'feat/checkout-v2',
    parsed_error:
      'PR #312 security flag: new checkout endpoint lacks input validation on the amount field. Potential integer overflow and price-manipulation vector.',
    estimated_duration_seconds: 180,
    created_at: ago(45),
    options: [],
  },
  {
    incident_id: 'f6a7b8c9-d0e1-2345-fabc-456789012306',
    status: 'executing',
    agent_id: 'agent_10_dependency_patch',
    cloud_provider: 'aws',
    repository: 'stackbridge/payments-api',
    branch: 'main',
    parsed_error:
      '3 critical CVEs in package.json: lodash@4.17.15 (CVE-2019-10744, prototype pollution), axios@0.21.1 (CVE-2021-3749, SSRF), follow-redirects@1.14.1 (CVE-2022-0536, credential exposure).',
    estimated_duration_seconds: 240,
    created_at: ago(12),
    options: [],
  },
  {
    incident_id: '07a8b9c0-d1e2-3456-abcd-567890123407',
    status: 'executed',
    agent_id: 'agent_04_migration',
    cloud_provider: 'aws',
    repository: 'stackbridge/data-platform',
    branch: 'main',
    parsed_error:
      'Migration 0042_add_user_preferences failed: column preferences already exists in users table. Idempotency guard missing from ALTER TABLE statement.',
    estimated_duration_seconds: 30,
    created_at: ago(180),
    options: [
      {
        id: 'opt_1',
        title: 'Apply idempotent migration fix',
        description:
          'Wrap ALTER TABLE in IF NOT EXISTS. Re-run against staging first. Zero data-loss.',
        impact: 'high',
        docs_url: 'https://alembic.sqlalchemy.org/en/latest/',
      },
    ],
  },
  {
    incident_id: '18b9c0d1-e2f3-4567-bcde-678901234508',
    status: 'executed',
    agent_id: 'agent_06_finops',
    cloud_provider: 'aws',
    repository: 'stackbridge/infra',
    branch: 'main',
    parsed_error:
      'FinOps alert: AWS Lambda data-export-job hit 2.3M invocations in a single day (baseline: 18k). Bill spiked $14,200 above budget. Root cause: retry loop in SQS event processor.',
    estimated_duration_seconds: 60,
    created_at: ago(360),
    options: [
      {
        id: 'opt_1',
        title: 'Add DLQ + MaxReceiveCount=5 to SQS trigger queue',
        description: 'Stops the retry cascade immediately. Failures route to dead-letter queue for inspection.',
        impact: 'high',
        docs_url:
          'https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html',
      },
    ],
  },
  {
    incident_id: '29c0d1e2-f3a4-5678-cdef-789012345609',
    status: 'executed',
    agent_id: 'agent_07_runbook',
    cloud_provider: 'gcp',
    repository: 'stackbridge/ml-platform',
    branch: 'main',
    parsed_error:
      'Cloud Run service ml-inference-api returned 503 for 8 minutes. Root cause: GPU quota exhausted in us-central1 during model warm-up after a cold-start burst.',
    estimated_duration_seconds: 45,
    created_at: ago(720),
    options: [],
  },
  {
    incident_id: '3ad1e2f3-a4b5-6789-defa-890123456710',
    status: 'held',
    agent_id: 'agent_09_onboarding_buddy',
    cloud_provider: 'aws',
    repository: 'stackbridge/platform-services',
    branch: 'main',
    parsed_error:
      'New engineer @jsmith joined #engineering-onboarding. Knowledge brief requested: incident response runbook, Terraform workflow, PR review standards, open incidents.',
    estimated_duration_seconds: null,
    created_at: ago(60),
    options: [
      {
        id: 'opt_1',
        title: 'Post knowledge brief to #engineering-onboarding',
        description:
          'Compile and post the onboarding brief with links to runbooks and open incidents.',
        impact: 'low',
        docs_url: '',
      },
    ],
  },
  {
    incident_id: '4be2f3a4-b5c6-7890-efab-901234567811',
    status: 'failed',
    agent_id: 'agent_01_cicd_triage',
    cloud_provider: 'gcp',
    repository: 'stackbridge/analytics-pipeline',
    branch: 'release/v2.1',
    parsed_error:
      'Cloud Build cannot push to Artifact Registry: service account lacks artifactregistry.repositories.uploadArtifacts. Automated remediation attempted but GCP token expired mid-execution.',
    estimated_duration_seconds: 30,
    created_at: ago(95),
    options: [],
  },
]

// Mutable store — reset by page refresh (module re-initialises on load)
let _store: Incident[] | null = null

function getStore(): Incident[] {
  if (!_store) _store = JSON.parse(JSON.stringify(MOCK_INCIDENTS)) as Incident[]
  return _store
}

export function getMockIncidents(statusFilter?: string): Incident[] {
  const all = getStore()
  return statusFilter ? all.filter(i => i.status === statusFilter) : [...all]
}

export function mockApprove(incidentId: string, optionId: string): void {
  const inc = getStore().find(i => i.incident_id === incidentId)
  if (inc) inc.status = optionId === 'hold' ? 'held' : 'executing'
}

// ── Cloud Audit Remediation Plan — Mock Data ─────────────────────────

const MOCK_AUDIT_SUBMISSIONS: AuditSubmissionDetail[] = [
  {
    audit_id: 'b1c2d3e4-f5a6-7890-bcde-f12345678001',
    provider: 'aws',
    status: 'ready',
    total_findings: 9,
    total_estimated_monthly_waste_usd: 62.0,
    analysis_error: null,
    created_at: ago(60),
    items: [
      {
        id: 'item-001',
        severity: 'HIGH',
        category: 'SECURITY',
        title: 'Enforce MFA on IAM users',
        description: 'Multiple IAM users can sign in with only a password, lacking multi-factor authentication.',
        remediation: 'Enable MFA for all IAM users, particularly those with console access.',
        estimated_monthly_waste_usd: 0,
        priority_rank: 1,
        status: 'pending_approval',
      },
      {
        id: 'item-002',
        severity: 'MEDIUM',
        category: 'WASTE',
        title: 'Stopped instance still paying for storage',
        description: 'An EC2 instance is stopped but its attached EBS volumes continue to bill.',
        remediation: 'Terminate if no longer needed, or snapshot and delete the volumes.',
        estimated_monthly_waste_usd: 62.0,
        priority_rank: 2,
        status: 'pending_approval',
      },
      {
        id: 'item-003',
        severity: 'LOW',
        category: 'COMPLIANCE',
        title: 'Enable Security Hub',
        description: 'Security Hub is not enabled in this account/region.',
        remediation: 'Enable Security Hub to get continuous security findings.',
        estimated_monthly_waste_usd: 0,
        priority_rank: 3,
        status: 'approved',
      },
    ],
  },
  {
    audit_id: 'b1c2d3e4-f5a6-7890-bcde-f12345678002',
    provider: 'azure',
    status: 'ready',
    total_findings: 4,
    total_estimated_monthly_waste_usd: 8.0,
    analysis_error: null,
    created_at: ago(24 * 60),
    items: [
      {
        id: 'item-004',
        severity: 'MEDIUM',
        category: 'WASTE',
        title: 'Unattached managed disk',
        description: "A 160GB managed disk isn't attached to any VM.",
        remediation: 'Delete it if no longer needed, or attach it.',
        estimated_monthly_waste_usd: 8.0,
        priority_rank: 1,
        status: 'dismissed',
      },
      {
        id: 'item-005',
        severity: 'LOW',
        category: 'WASTE',
        title: 'Empty resource group',
        description: 'This resource group has no resources in it.',
        remediation: 'Delete it if no longer needed.',
        estimated_monthly_waste_usd: 0,
        priority_rank: 2,
        status: 'pending_approval',
      },
    ],
  },
]

let _auditStore: AuditSubmissionDetail[] | null = null

function getAuditStore(): AuditSubmissionDetail[] {
  if (!_auditStore) _auditStore = JSON.parse(JSON.stringify(MOCK_AUDIT_SUBMISSIONS)) as AuditSubmissionDetail[]
  return _auditStore
}

export function getMockAuditSubmissions(): AuditSubmissionSummary[] {
  return getAuditStore().map(({ items: _items, analysis_error: _analysisError, ...summary }) => summary)
}

export function getMockAuditReport(auditId: string): AuditSubmissionDetail {
  const submission = getAuditStore().find(s => s.audit_id === auditId)
  if (!submission) throw new Error('Audit submission not found')
  return submission
}

export function mockActionAuditItem(
  itemId: string,
  status: 'approved' | 'dismissed',
): { id: string; status: string } {
  for (const submission of getAuditStore()) {
    const item = submission.items.find(i => i.id === itemId)
    if (item) {
      item.status = status
      return { id: item.id, status: item.status }
    }
  }
  throw new Error('Remediation item not found')
}

// ── FinOps / Compliance agent — Mock Connection + Dashboard Data ─────
// Mirrors the real connect -> pending_setup -> connected state machine in
// api/routes/finops_agent.py / compliance_agent.py, entirely in-memory.

const MOCK_SETUP = {
  aws_trust_policy: {
    Version: '2012-10-17',
    Statement: [
      {
        Effect: 'Allow',
        Principal: { AWS: 'arn:aws:iam::402916653765:root' },
        Action: 'sts:AssumeRole',
        Condition: { StringEquals: { 'sts:ExternalId': 'demo-external-id-000' } },
      },
    ],
  },
  aws_permissions_policy: {
    Version: '2012-10-17',
    Statement: [{ Effect: 'Allow', Action: ['iam:ListUsers', 'iam:ListMFADevices'], Resource: '*' }],
  },
  azure_setup_instructions:
    'In Azure: run `az ad sp create-for-rbac --name demo-readonly --skip-assignment` to create a ' +
    'Service Principal, then assign it "Reader" and "Cost Management Reader" at your subscription scope.',
}

let _finopsConnection: AgentConnectionStatus = { connected: false, pending_setup: false, setup: null }
let _complianceConnection: AgentConnectionStatus = { connected: false, pending_setup: false, setup: null }

export function getMockAgentStatus(product: 'finops' | 'compliance'): AgentConnectionStatus {
  return product === 'finops' ? _finopsConnection : _complianceConnection
}

export function mockConnectAgent(product: 'finops' | 'compliance'): AgentConnectionStatus {
  const current = getMockAgentStatus(product)
  if (current.connected || current.pending_setup) {
    throw new Error(`${product === 'finops' ? 'FinOps' : 'Compliance'} agent already connected or pending setup`)
  }
  const next: AgentConnectionStatus = { connected: false, pending_setup: true, setup: MOCK_SETUP }
  if (product === 'finops') _finopsConnection = next
  else _complianceConnection = next
  return next
}

export function mockVerifyAgentRole(product: 'finops' | 'compliance'): { status: string } {
  const next: AgentConnectionStatus = { connected: true, pending_setup: false, setup: null }
  if (product === 'finops') _finopsConnection = next
  else _complianceConnection = next
  return { status: 'active' }
}

let _finopsItems: FinOpsHitlItem[] = [
  {
    id: 'fo-item-001',
    severity: 'HIGH',
    category: 'SECURITY',
    title: 'Root account has no MFA',
    description: 'The root account can sign in with just a password, the single highest-value target in the account.',
    remediation: 'Enable a hardware or virtual MFA device on the root account immediately.',
    estimated_monthly_waste_usd: 0,
    priority_rank: 1,
    status: 'pending_approval',
  },
  {
    id: 'fo-item-002',
    severity: 'MEDIUM',
    category: 'WASTE',
    title: 'Stopped instance still paying for storage',
    description: 'An EC2 instance is stopped but its attached EBS volumes continue to bill monthly.',
    remediation: 'Terminate if no longer needed, or snapshot and delete the volumes.',
    estimated_monthly_waste_usd: 48.0,
    priority_rank: 2,
    status: 'pending_approval',
  },
]

export function getMockFinopsDashboard(): FinOpsDashboardData {
  return {
    tenant_id: 'demo-finops-tenant',
    status: 'active',
    latest_scan: {
      scan_id: 'demo-finops-scan-1',
      provider: 'aws',
      status: 'ready',
      total_findings: _finopsItems.length,
      total_estimated_monthly_waste_usd: _finopsItems.reduce((sum, i) => sum + i.estimated_monthly_waste_usd, 0),
      started_at: ago(5),
      completed_at: ago(4),
    },
    open_items: _finopsItems.filter(i => i.status === 'pending_approval'),
  }
}

export function mockActionFinopsItem(itemId: string, status: 'approved' | 'dismissed'): { id: string; status: string } {
  const item = _finopsItems.find(i => i.id === itemId)
  if (!item) throw new Error('HITL item not found')
  item.status = status
  return { id: item.id, status: item.status }
}

export function getMockComplianceReport(): ComplianceReportData {
  return {
    framework: 'CIS AWS Foundations Benchmark v3.0.0',
    controls_assessed: 4,
    controls_total_in_framework: 62,
    readiness_score: 50,
    controls: [
      {
        control_id: '1.4',
        security_hub_id: 'IAM.4',
        title: 'IAM root user access key should not exist',
        status: 'PASS',
        exact_match: true,
        caveat: null,
      },
      {
        control_id: '1.5',
        security_hub_id: 'IAM.9',
        title: 'MFA should be enabled for the root user',
        status: 'FAIL',
        exact_match: true,
        caveat: null,
      },
      {
        control_id: '1.10',
        security_hub_id: 'IAM.5',
        title: "MFA should be enabled for all IAM users that have a console password",
        status: 'PASS',
        exact_match: false,
        caveat:
          'AWSProvider flags any IAM user with no MFA device at all -- it cannot determine whether a given user actually has a console password. Conservative proxy, not exact.',
      },
      {
        control_id: '1.14',
        security_hub_id: 'IAM.3',
        title: "IAM users' access keys should be rotated every 90 days or less",
        status: 'FAIL',
        exact_match: true,
        caveat: null,
      },
    ],
    coverage_note:
      'This report automatically assesses 4 of 62 CIS AWS Foundations Benchmark v3.0.0 controls -- the ones this scan can verify from AWS API data alone. The readiness score reflects only the assessed subset -- it is not a complete CIS assessment.',
    documentation_checklist: [
      { item: 'Information Security Policy', status: 'cannot_verify_from_scan', guidance: 'Must be authored manually' },
      { item: 'Incident Response Plan', status: 'cannot_verify_from_scan', guidance: 'Must be authored manually' },
      { item: 'Access Control Policy', status: 'cannot_verify_from_scan', guidance: 'Must be authored manually' },
    ],
  }
}


// ── Workspace connections (core platform's own Agents 01/05/06/08) ────────

let _connectionsStatus: ConnectionsStatus = {
  github_connected: false,
  aws_connected: false,
  azure_connected: false,
  azure_devops_connected: false,
  k8s_connected: false,
}

export function getMockConnectionsStatus(): ConnectionsStatus {
  return _connectionsStatus
}

export function mockGetGithubAppInstallUrl(): { install_url: string } {
  // Demo mode has nowhere real to redirect to -- marks the connection
  // "installed" immediately so the mock dashboard still demonstrates the
  // connected state without a real GitHub round trip.
  _connectionsStatus = { ..._connectionsStatus, github_connected: true }
  return { install_url: 'https://github.com/apps/cloud-decoded-demo/installations/new' }
}

export function mockSetupAwsRole(): AwsRoleSetup {
  return {
    external_id: 'demo-external-id-' + Math.random().toString(36).slice(2, 10),
    trust_policy: MOCK_SETUP.aws_trust_policy,
    permissions_policy: MOCK_SETUP.aws_permissions_policy,
    instructions:
      "In AWS: create an IAM role using trust_policy as its trust relationship, and attach " +
      "permissions_policy as an inline policy. Then call PATCH /workspace/credentials/aws-role with the role's ARN.",
  }
}

export function mockConnectAwsRole(): { id: string } {
  _connectionsStatus = { ..._connectionsStatus, aws_connected: true }
  return { id: 'demo-workspace-001' }
}

export function mockConnectAzure(): { id: string } {
  _connectionsStatus = { ..._connectionsStatus, azure_connected: true }
  return { id: 'demo-workspace-001' }
}

export function mockConnectAzureDevOps(): { status: string; webhook_secret: string | null } {
  const firstTime = !_connectionsStatus.azure_devops_connected
  _connectionsStatus = { ..._connectionsStatus, azure_devops_connected: true }
  return { status: 'verified', webhook_secret: firstTime ? 'demo_ado_whsec_' + Math.random().toString(36).slice(2) : null }
}

export function mockConnectK8s(): { id: string } {
  _connectionsStatus = { ..._connectionsStatus, k8s_connected: true }
  return { id: 'demo-workspace-001' }
}
