// Cloud Decoded — Mock data for NEXT_PUBLIC_MOCK_MODE=true
// All state lives in-memory only. Refreshing the page resets everything.

import type { Incident } from './types'

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

// ── Phase 6 Internal Ops — Mock Pipeline Outputs ─────────────────────

export const MOCK_SALES_DATA = {
  lead: {
    name: 'Marcus Webb',
    company: 'StackBridge Inc.',
    role: 'VP of Engineering',
    team_size: 38,
    cloud_provider: 'AWS',
    pain_points:
      'CI/CD failures eating on-call hours, Lambda cost spike caught us off guard, no IaC drift detection',
  },
  qualify: {
    qualified: true,
    fit_score: 9,
    tier_recommendation: 'growth',
    icp_matches: [
      'Team size 5-100 engineers ✓',
      'AWS primary cloud ✓',
      'DevOps pain quantified ✓',
      'Engineering-led buying decision ✓',
    ],
    disqualifiers: [],
    recommended_action: 'book_call',
    talk_track:
      "Open with the $14k Lambda spike — that's board-level pain. Pivot to CI/CD triage hours. Marcus already quantified both. Close on recovered engineer time.",
    reasoning:
      'StackBridge hits every ICP dimension. VP Engineering is the right buyer. Pain is recurring and financially quantified. High close probability.',
  },
  assess: {
    assessment_title: 'Infrastructure Assessment — StackBridge Inc.',
    executive_summary:
      'StackBridge has three compounding risks: a CI/CD reliability gap costing 6+ engineer-hours of weekly triage, an IAM posture with wildcard admin policies in production, and unmonitored Lambda spend that produced a $14k bill spike. All three are addressable with existing Cloud Decoded agents.',
    risk_areas: [
      {
        area: 'CI/CD Reliability',
        severity: 'high',
        description: '3-4 pipeline failures/week at 2hrs triage each = 6-8 engineer-hours/week in diagnosis alone',
        impact_if_ignored: 'On-call burnout, slower release velocity, senior engineer attrition',
      },
      {
        area: 'IAM Security',
        severity: 'critical',
        description: 'ci_deploy_role has Action:* on Resource:* — full AWS admin via GitHub Actions',
        impact_if_ignored: 'Single compromised token = full AWS account access including billing and IAM',
      },
      {
        area: 'Cloud Cost Control',
        severity: 'high',
        description: 'Unmonitored Lambda retry loop produced $14k overage in 24 hours',
        impact_if_ignored: 'Continued unbudgeted overages, board-level scrutiny on cloud spend',
      },
    ],
    quick_wins: [
      {
        action: 'IAM wildcard cleanup',
        impact: 'CRITICAL security fix in 2-4 hours',
        effort: 'low',
        agent_id: 'agent_05',
      },
      {
        action: 'Lambda DLQ configuration',
        impact: 'Prevents recurrence of $14k spike',
        effort: 'low',
        agent_id: 'agent_06',
      },
      {
        action: 'Terraform drift detection',
        impact: 'Catch config drift before it becomes an incident',
        effort: 'medium',
        agent_id: 'agent_08',
      },
    ],
    recommended_tier: 'growth',
    estimated_monthly_hours_saved: 48,
    estimated_monthly_value_usd: 9600,
    confidence: 0.91,
  },
  propose: {
    proposal_title: 'Cloud Decoded Engagement Proposal — StackBridge Inc.',
    prepared_for: 'Marcus Webb, VP of Engineering',
    executive_summary:
      'StackBridge is losing 48+ engineer-hours per month to preventable DevOps incidents. Cloud Decoded deploys autonomous agents that diagnose, propose, and execute fixes with your team in the loop. Based on your infrastructure, we project $9,600/month in recovered engineer time within 90 days — at a $699/month investment.',
    recommended_tier: 'growth',
    monthly_investment: '$699/month',
    roi_case:
      'At $200/hr fully loaded, 48 recovered hours = $9,600/month. Growth tier: $699/month. That is a 13.7× ROI in recovered productivity — before counting prevented IAM incidents or future Lambda overages.',
    agent_breakdown: [
      {
        agent_name: 'CI/CD Pipeline Failure Triage',
        agent_id: 'agent_01',
        use_case: 'Auto-diagnose failed GitHub Actions deploys, propose IAM and config fixes',
        expected_outcome: 'Triage time: 2 hours → under 10 minutes per incident',
      },
      {
        agent_name: 'IAM Policy Minimizer',
        agent_id: 'agent_05',
        use_case: 'Audit and remediate the wildcard ci_deploy_role policy',
        expected_outcome: 'CRITICAL finding resolved in sprint 1; continuous policy drift detection ongoing',
      },
      {
        agent_name: 'FinOps Cost Monitor',
        agent_id: 'agent_06',
        use_case: 'Monitor Lambda spend and flag anomaly spikes before they hit $1k',
        expected_outcome: 'No more undetected $14k Lambda bills',
      },
      {
        agent_name: 'IaC Drift Detection',
        agent_id: 'agent_08',
        use_case: 'Detect Terraform state drift and open PRs to correct it',
        expected_outcome: 'Live infrastructure always matches declared state',
      },
    ],
    next_steps: [
      '30-minute technical call with Marcus + lead infra engineer',
      'Review proposal — flag any scope questions',
      'Sign Growth tier agreement + provide GitHub App installation',
      'Week 1: Agent 05 IAM audit (read-only, zero risk)',
      'Week 2: Agent 01 CI/CD triage live on payments-api repo',
    ],
    customize_flags: [
      '[CUSTOMIZE] Reference the specific on-call incident Kelvin knows about',
      '[CUSTOMIZE] Confirm Growth pricing — no active promotions',
    ],
  },
}

export const MOCK_CONTENT_DATA = {
  brief: {
    brief_title: 'The hidden cost of CI/CD triage',
    platform: 'linkedin',
    goal: 'education',
    hook_angle:
      'Your senior engineers are spending 2 hours diagnosing a pipeline failure before they write a single line of fix.',
    key_message:
      "The diagnosis phase of DevOps incidents is automatable today. Most teams just haven't done it yet.",
    supporting_points: [
      '2 hours average triage time per CI/CD failure (client-validated)',
      '3-4 failures/week at a 30-50 engineer org = 6-8 hrs/week in diagnosis',
      'Autonomous triage agents cut this to under 10 minutes',
    ],
    tone: 'Direct, practitioner-first. Sounds like a senior engineer, not a marketer.',
    format: 'Short paragraphs (1-3 lines). No bullet lists. CTA as a question.',
    cta: 'Ask your on-call engineer: how long did your last triage take?',
    do_not_include: ['competitor names', 'invented statistics', 'em-dashes'],
  },
  draft: {
    platform: 'linkedin',
    draft_a: {
      text: `Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.

Not fixing. Not shipping. Just triaging.

Here is what that looks like in real numbers: 3 failures per week, 2 hours each, 6 engineer-hours per week before a single fix begins.

Autonomous triage agents cut that to under 10 minutes.

The diagnosis phase is the part nobody talks about. It is also the part that is fully automatable today.

Ask your on-call engineer: how long did your last triage take?

#DevOps #CloudEngineering #PlatformEngineering #CloudDecoded`,
      hook: 'Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.',
      word_count: 89,
      hashtags: ['#DevOps', '#CloudEngineering', '#PlatformEngineering', '#CloudDecoded'],
      engagement_prompt: 'Ask your on-call engineer: how long did your last triage take?',
    },
    draft_b: {
      text: `3 pipeline failures per week. 2 hours of triage each. That is 6 engineer-hours before anyone starts fixing anything.

Most teams accept this as normal. It is not.

The diagnosis phase has been automatable for two years. The reason most teams still do it manually is nobody set it up.

Autonomous triage agents read the error, query your IAM policies, check recent deploys, and surface a root cause in under 10 minutes. Your senior engineer reviews and approves.

What would your team do with 6 extra hours a week?

#DevOps #SRE #CloudEngineering #PlatformEngineering`,
      hook: '3 pipeline failures per week. 2 hours of triage each.',
      word_count: 107,
      hashtags: ['#DevOps', '#SRE', '#CloudEngineering', '#PlatformEngineering'],
      engagement_prompt: 'What would your team do with 6 extra hours a week?',
    },
    writer_notes:
      'Draft A is tighter and leads with loss-framing, which performs better on LinkedIn. Draft B has a stronger closing question. Consider A body + B closing for final version.',
  },
  review: {
    decision: 'approved',
    brand_voice_score: 9,
    brief_alignment_score: 10,
    flags: [],
    approved_draft: `Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.

Not fixing. Not shipping. Just triaging.

Here is what that looks like in real numbers: 3 failures per week, 2 hours each, 6 engineer-hours per week before a single fix begins.

Autonomous triage agents cut that to under 10 minutes.

The diagnosis phase is the part nobody talks about. It is also the part that is fully automatable today.

Ask your on-call engineer: how long did your last triage take?

#DevOps #CloudEngineering #PlatformEngineering #CloudDecoded`,
    revision_notes: '',
  },
  publish: {
    platform: 'linkedin',
    publish_ready: true,
    compliance_passed: true,
    compliance_notes: [],
    publish_package: {
      main_text: `Your engineers are losing 2 hours per CI/CD failure to diagnosis alone.

Not fixing. Not shipping. Just triaging.

Here is what that looks like in real numbers: 3 failures per week, 2 hours each, 6 engineer-hours per week before a single fix begins.

Autonomous triage agents cut that to under 10 minutes.

The diagnosis phase is the part nobody talks about. It is also the part that is fully automatable today.

Ask your on-call engineer: how long did your last triage take?

#DevOps #CloudEngineering #PlatformEngineering #CloudDecoded`,
      character_count: 492,
      hashtags: ['#DevOps', '#CloudEngineering', '#PlatformEngineering', '#CloudDecoded'],
      thread_posts: [],
      caption_text: '',
      alt_text_needed: true,
      visual_recommendation:
        'Two-panel graphic: left shows a clock at 2:00:00 labeled "Manual Triage", right shows 0:09:42 labeled "Agent". Dark background, red vs emerald accent.',
    },
    scheduling_metadata: {
      campaign_tag: 'q3-education-series',
      recommended_post_time: 'Tue–Thu 8:00–10:00 AM EST',
      content_pillar: 'education',
    },
    operator_flags: [
      'Visual not yet created — provide image + alt text before scheduling',
    ],
  },
}

export const MOCK_DEVOPS_OPS_DATA = {
  security: {
    client_slug: 'stackbridge',
    scan_summary:
      'StackBridge has a critical IAM exposure requiring immediate action: the CI/CD role holds full wildcard AWS permissions. Two high-severity findings follow — SSH open to the internet and CloudTrail disabled. Overall security posture is elevated risk until the IAM issue is resolved.',
    critical_count: 1,
    high_count: 2,
    medium_count: 3,
    low_count: 2,
    findings: [
      {
        id: 'SEC-001',
        severity: 'CRITICAL',
        category: 'IAM',
        resource: 'iam-role/ci_deploy_role',
        title: 'Wildcard IAM policy grants full AWS access to CI/CD role',
        description:
          'ci_deploy_role has Action:* on Resource:*. A compromised GitHub Actions token gives full AWS account control including IAM, S3, RDS, and billing.',
        remediation:
          'Replace with least-privilege policy using CloudTrail data. Minimum required: s3:PutObject on prod-assets-bucket, ecr:GetAuthorizationToken, ecr:BatchCheckLayerAvailability, ecr:PutImage.',
        docs_url: 'https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html',
        effort_estimate: '1 hour',
      },
      {
        id: 'SEC-002',
        severity: 'HIGH',
        category: 'Network',
        resource: 'sg-api-prod',
        title: 'SSH port 22 open to 0.0.0.0/0 on production security group',
        description:
          'Production EC2 instances are directly SSH-accessible from the public internet. Single credential exposure = full server access.',
        remediation:
          'Restrict port 22 ingress to VPN CIDR, or use AWS Systems Manager Session Manager and remove the SSH rule entirely.',
        docs_url: 'https://docs.aws.amazon.com/vpc/latest/userguide/security-group-rules.html',
        effort_estimate: '15 minutes',
      },
      {
        id: 'SEC-003',
        severity: 'HIGH',
        category: 'Logging',
        resource: 'cloudtrail/us-east-1',
        title: 'CloudTrail disabled — no API audit log in any region',
        description:
          'All IAM, S3, EC2, and management API calls go unlogged. Forensic investigation after an incident would be impossible.',
        remediation:
          'Enable CloudTrail with S3 log delivery to a protected bucket. Enable log file validation and MFA delete on the log bucket.',
        docs_url:
          'https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-create-and-update-a-trail.html',
        effort_estimate: '1 hour',
      },
      {
        id: 'SEC-004',
        severity: 'MEDIUM',
        category: 'Compliance',
        resource: 's3/acme-prod-assets',
        title: 'S3 production assets bucket has public access enabled',
        description:
          'acme-prod-assets has BlockPublicAccess disabled. Any misconfigured bucket policy or ACL could expose build artifacts publicly.',
        remediation:
          'Enable S3 Block Public Access at the bucket level. Verify no legitimate public read is required first.',
        docs_url:
          'https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html',
        effort_estimate: '15 minutes',
      },
      {
        id: 'SEC-005',
        severity: 'MEDIUM',
        category: 'Kubernetes',
        resource: 'k8s/namespace-prod',
        title: 'Default service account token auto-mounting enabled',
        description:
          'Pods in namespace-prod auto-mount service account tokens. A compromised pod can use these tokens to interact with the Kubernetes API.',
        remediation:
          'Set automountServiceAccountToken: false on the default service account. Add it explicitly only to pods that need API access.',
        docs_url:
          'https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/#opt-out-of-api-credential-automounting',
        effort_estimate: '1 hour',
      },
    ],
    immediate_actions: [
      'Constrain ci_deploy_role IAM policy within 24 hours (CRITICAL)',
      'Remove public SSH rule from sg-api-prod (HIGH, 15 minutes)',
      'Enable CloudTrail in all regions before end of day (HIGH)',
      'Audit all S3 buckets for Block Public Access configuration',
    ],
    missing_data: [
      'RDS security group rules not provided',
      'Lambda execution role policies not reviewed',
      'VPC flow log status unknown',
    ],
  },
  finops: {
    client_slug: 'stackbridge',
    analysis_period: 'June 2026',
    total_spend_usd: 31420,
    estimated_waste_usd: 8215,
    waste_percentage: 26.1,
    executive_summary:
      'StackBridge spent $31,420 in June against a $17,000 baseline — an 85% overage. The Lambda data-export-job spike ($3,810 excess) is the most urgent item, driven by a retry loop. Two idle EC2 instances account for $923/month in continuous waste. Total addressable savings: $8,215/month.',
    waste_items: [
      {
        id: 'FINOPS-001',
        category: 'Anomaly spike',
        resource_type: 'Lambda',
        resource_id: 'data-export-job',
        current_monthly_cost_usd: 4100,
        potential_savings_usd: 3810,
        recommendation: 'Add DLQ with MaxReceiveCount=5 to the trigger SQS queue. Normalized cost: ~$290/month.',
        effort: 'hours',
      },
      {
        id: 'FINOPS-002',
        category: 'Idle resource',
        resource_type: 'EC2',
        resource_id: 'i-0abc123 (m5.2xlarge)',
        current_monthly_cost_usd: 367,
        potential_savings_usd: 367,
        recommendation: 'Terminate: 3.2% avg CPU / 8.1% avg memory over 7 days. No active workload detected.',
        effort: 'minutes',
      },
      {
        id: 'FINOPS-003',
        category: 'Idle resource',
        resource_type: 'EC2',
        resource_id: 'i-0def456 (c5.4xlarge)',
        current_monthly_cost_usd: 556,
        potential_savings_usd: 556,
        recommendation: 'Terminate: 4.8% avg CPU over 7 days. c5.4xlarge is compute-optimized and expensive for this utilization.',
        effort: 'minutes',
      },
      {
        id: 'FINOPS-004',
        category: 'Overprovisioned',
        resource_type: 'RDS',
        resource_id: 'prod-db-postgres (db.r5.2xlarge)',
        current_monthly_cost_usd: 890,
        potential_savings_usd: 445,
        recommendation: 'Downsize to db.r5.large. Max connections: 18 of 600 capacity (3%). Saves ~$445/month.',
        effort: 'days',
      },
      {
        id: 'FINOPS-005',
        category: 'Unattached',
        resource_type: 'EBS',
        resource_id: 'vol-0abc (500 GB)',
        current_monthly_cost_usd: 50,
        potential_savings_usd: 50,
        recommendation: 'Delete: unattached since 2025-11-14. Snapshot first if data retention required.',
        effort: 'minutes',
      },
    ],
    priority_actions: [
      'Fix Lambda retry loop (DLQ): $3,810/month saved, hours of effort',
      'Terminate idle EC2 i-0abc123: $367/month, minutes of effort',
      'Terminate idle EC2 i-0def456: $556/month, minutes of effort',
      'RDS downsize after maintenance window: $445/month saved',
      'Delete unattached EBS vol-0abc: $50/month, minutes of effort',
    ],
    anomalies_detected: [
      {
        description: 'Lambda data-export-job: $4,100 in June vs $290 baseline (+1,314%)',
        likely_cause: 'Retry loop June 3rd — 2.3M invocations vs 18k daily average',
        recommended_action: 'Review SQS trigger configuration and add DLQ immediately',
      },
    ],
    total_potential_savings_usd: 8215,
    projected_monthly_spend_after_optimizations_usd: 23205,
  },
  fixIssue: {
    issue_title: 'RDS connection pool exhaustion on prod-db-postgres during deploys',
    fix_title: 'Configure PgBouncer to prevent RDS max-connection exhaustion during deploys',
    severity: 'high',
    estimated_duration_minutes: 90,
    risk_level: 'medium',
    pre_conditions: [
      'Access to production RDS parameter group',
      'PgBouncer installed on application servers (confirm with ops team)',
      'Maintenance window scheduled — connection reset causes ~30s of elevated latency',
    ],
    fix_steps: [
      {
        step: 1,
        action: 'Set max_connections on db.r5.2xlarge to 100 (current: 600)',
        expected_outcome: 'Forces connection pooling adoption at the database layer',
        destructive: false,
        rollback_step: 'Revert parameter group max_connections to 600 and reboot',
      },
      {
        step: 2,
        action: 'Configure PgBouncer: pool_size=20 per server, pool_mode=transaction',
        expected_outcome: '20 connections × 5 servers = 100 max at peak',
        destructive: false,
        rollback_step: 'Revert pgbouncer.ini and restart PgBouncer',
      },
      {
        step: 3,
        action: 'Update app DATABASE_URL to PgBouncer (port 6432) instead of RDS direct (port 5432)',
        expected_outcome: 'All application connections route through the pool',
        destructive: false,
        rollback_step: 'Revert DATABASE_URL to RDS endpoint and redeploy',
      },
      {
        step: 4,
        action: 'Deploy and monitor pg_stat_activity during next deploy cycle',
        expected_outcome: 'Connection count stays under 100 during full parallel deploy',
        destructive: false,
        rollback_step: 'Roll back app version if connection spike recurs',
      },
    ],
    validation_steps: [
      'SELECT count(*) FROM pg_stat_activity — confirm below 100 during peak',
      'Watch deploy pipeline for FATAL: remaining connection slots reserved errors',
      'Review PgBouncer logs for pool overflow warnings after 2 deploy cycles',
    ],
    documentation_references: [
      { title: 'PgBouncer configuration reference', url: 'https://www.pgbouncer.org/config.html' },
      {
        title: 'RDS max_connections parameter',
        url: 'https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithParamGroups.html',
      },
    ],
    missing_information: [
      'Exact number of application servers in the pool',
      'Current PgBouncer version installed',
    ],
    requires_approval: true,
    approval_note:
      'Step 3 (DATABASE_URL change) requires a coordinated deploy. Confirm with Marcus Webb before execution.',
  },
}
