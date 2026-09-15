import type { Metadata } from 'next'
import { MarketingHead, MarketingNav, MarketingFooter, Eyebrow, PrimaryCta, PAGE_BG, BODY_FONT, HEAD_FONT, MONO_FONT } from '@/components/marketing/SiteChrome'

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Features — All 11 Cloud Decoded Agents | Cloud Decoded',
  description:
    'Every Cloud Decoded agent workflow: CI/CD triage, Kubernetes alerts, PR review, migration, IAM, FinOps, runbooks, drift detection, on-call knowledge, dependency patching, and live resource health monitoring. Each one detects, triages, and proposes — you approve before anything executes.',
  alternates: { canonical: 'https://theclouddecoded.com/features' },
  openGraph: {
    type: 'website',
    url: 'https://theclouddecoded.com/features',
    title: 'Features — All 11 Cloud Decoded Agents',
    description: 'Every agent workflow, what it does, what it touches, and the approval gate in front of every one of them.',
  },
}

type Tier = 'Starter' | 'Growth+'

const AGENTS: { id: string; tier: Tier; name: string; blurb: string; touches: string; option: string }[] = [
  {
    id: 'agent_01', tier: 'Starter', name: 'CI/CD Pipeline Failure Triage',
    blurb: 'Detects a failed pipeline run, surfaces the root-cause step from the logs, and proposes the exact config or code fix — before you’ve finished reading the Slack alert.',
    touches: 'GitHub Actions / Azure DevOps pipelines, the failing repo',
    option: 'Reopen the PR with the fix, or open a new PR — your call, always reviewed first',
  },
  {
    id: 'agent_02', tier: 'Starter', name: 'Kubernetes Alert Fatigue & Remediation',
    blurb: 'Separates the pod restart that self-healed from the one that needs a human, and proposes the scale-up, rollback, or config patch for the ones that matter.',
    touches: 'Your cluster’s K8s API (read for triage, write only on approval)',
    option: 'Apply directly via kubectl, or route through a GitOps PR — whichever your team runs',
  },
  {
    id: 'agent_03', tier: 'Starter', name: 'PR Review — Architecture & Security',
    blurb: 'Reads a pull request the way a senior engineer would: flags security patterns, architectural drift, and the stuff a linter can’t catch, as a real review comment.',
    touches: 'The PR’s diff and repo context — read-only',
    option: 'Posts as a review; never merges, never blocks CI on its own',
  },
  {
    id: 'agent_04', tier: 'Growth+', name: 'Legacy Code & Infrastructure Migration',
    blurb: 'Takes a file or module you name — a Flask route, a Terraform 0.12 module, a Python 2.7 script — and drafts the migrated version with a step-by-step plan attached.',
    touches: 'One file or module at a time, on request',
    option: 'Opens a PR with the migrated code, or files a tracking issue with the plan',
  },
  {
    id: 'agent_05', tier: 'Growth+', name: 'IAM Policy Minimization',
    blurb: 'Diffs what a role actually used against what it’s allowed to do, and proposes the tightened policy — the least-privilege cleanup nobody has time to do by hand.',
    touches: 'AWS IAM / Azure RBAC / GCP IAM, read for analysis, write only on approval',
    option: 'Opens a PR against your IaC, or applies directly if you’ve enabled that',
  },
  {
    id: 'agent_06', tier: 'Growth+', name: 'FinOps Cost Optimization',
    blurb: 'Reads your actual billing export, finds the idle resources and the waste, and ranks fixes by real monthly savings — not a generic "right-size everything" report.',
    touches: 'Cost Explorer / Azure Cost Management exports, idle-resource inventory',
    option: 'Stop/delete the specific idle resources it found, or just get the report',
  },
  {
    id: 'agent_07', tier: 'Growth+', name: 'Interactive Runbook Automation',
    blurb: 'Turns a written runbook into an executable, step-gated workflow — each step runs, reports back, and waits before the next one fires.',
    touches: 'Whatever the runbook itself touches — shell, HTTP, or infra steps',
    option: 'Runs step by step with a stop-on-failure gate, never all-at-once',
  },
  {
    id: 'agent_08', tier: 'Growth+', name: 'Drift Detection & Auto-Correction',
    blurb: 'Compares live state against Terraform, CloudFormation, or a Kubernetes manifest, and proposes the correction — never applies IaC changes without a PR to review.',
    touches: 'Terraform state, CloudFormation stacks, K8s live resources — read for detection',
    option: 'Remediation PR (always), or kubectl apply directly for K8s if you’ve enabled that',
  },
  {
    id: 'agent_09', tier: 'Growth+', name: 'Context-Aware Onboarding & On-Call Buddy',
    blurb: 'Answers "how does this actually work" and "what do I do about this page" using your real runbooks and incident history — not a generic wiki search.',
    touches: 'Your knowledge base and incident history — read-only',
    option: 'Answers in chat; never takes an action on its own',
  },
  {
    id: 'agent_10', tier: 'Growth+', name: 'Dependency & Vulnerability Patching',
    blurb: 'Scans your manifest (npm, pip, go, maven, ruby, or cargo) against OSV.dev, and proposes the patched manifest with a severity-ranked vulnerability summary.',
    touches: 'One dependency manifest at a time, on request or schedule',
    option: 'Patch PR, a tracking issue, or both — your choice per finding',
  },
  {
    id: 'agent_11', tier: 'Growth+', name: 'Cloud Resource Health Monitoring',
    blurb: 'Catches a resource going down, a threshold breach, or a security finding the moment your cloud provider fires the alert — the runtime counterpart to CI/CD triage and drift detection.',
    touches: 'Azure Monitor Action Groups, AWS SNS/CloudWatch alarms — push-driven, no polling',
    option: 'Remediation PR, or a tracking issue — never a live restart/scale call on its own',
  },
]

const TIER_COLOR: Record<Tier, string> = { Starter: '#3fd17a', 'Growth+': '#f5a623' }

function AgentCard({ a, index }: { a: (typeof AGENTS)[number]; index: number }) {
  const color = TIER_COLOR[a.tier]
  return (
    <article
      style={{
        border: '1px solid rgba(255,255,255,.08)', borderRadius: 14,
        background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))',
        padding: 22, display: 'flex', flexDirection: 'column',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{ fontFamily: MONO_FONT, fontSize: 10, color: 'rgba(232,236,242,.45)' }}>
          AGENT·{String(index + 1).padStart(2, '0')}
        </span>
        <span
          style={{
            marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6,
            fontFamily: MONO_FONT, fontSize: 9, letterSpacing: '.06em', color,
            border: `1px solid ${color}55`, background: `${color}14`, borderRadius: 5, padding: '3px 7px',
          }}
        >
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: color }} />
          {a.tier.toUpperCase()}
        </span>
      </div>
      <h3 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 17, lineHeight: 1.25, color: '#fff', margin: '0 0 9px' }}>
        {a.name}
      </h3>
      <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.6)', margin: '0 0 14px', flex: 1 }}>
        {a.blurb}
      </p>
      <div style={{ borderTop: '1px solid rgba(255,255,255,.06)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ fontFamily: MONO_FONT, fontSize: 10.5, color: 'rgba(232,236,242,.4)' }}>
          <span style={{ color: 'rgba(159,194,255,.85)' }}>TOUCHES </span>{a.touches}
        </div>
        <div style={{ fontFamily: MONO_FONT, fontSize: 10.5, color: 'rgba(232,236,242,.4)' }}>
          <span style={{ color: '#f5a623' }}>ON APPROVAL </span>{a.option}
        </div>
      </div>
    </article>
  )
}

export default function FeaturesPage() {
  return (
    <>
      <MarketingHead />
      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT }}>
        <MarketingNav />

        <section style={{ padding: '64px 40px 20px', maxWidth: 1140, margin: '0 auto' }}>
          <Eyebrow label="FEATURES" sub="11 agents · every one HITL-gated" />
          <h1
            style={{
              fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 46, lineHeight: 1.08,
              letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px', maxWidth: 820,
            }}
          >
            Eleven agents. One rule none of them can break.
          </h1>
          <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 0 20px', maxWidth: 720 }}>
            Every workflow below detects, triages, and proposes a fix — and every one of them stops at a hard
            approval gate before anything touches your infrastructure. Detection is automatic. Action never is,
            unless you say so.
          </p>
        </section>

        <section style={{ padding: '20px 40px 100px', maxWidth: 1140, margin: '0 auto' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
              gap: 18,
            }}
          >
            {AGENTS.map((a, i) => (
              <AgentCard key={a.id} a={a} index={i} />
            ))}
          </div>

          <div
            style={{
              marginTop: 56, padding: '38px 40px', borderRadius: 16,
              border: '1px solid rgba(120,160,255,.25)',
              background: 'linear-gradient(135deg, rgba(90,150,255,.08), rgba(7,9,16,0))',
              display: 'flex', alignItems: 'center', gap: 28, flexWrap: 'wrap',
            }}
          >
            <div style={{ flex: 1, minWidth: 280 }}>
              <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 24, color: '#fff', margin: '0 0 8px' }}>
                Starter gets you three. Growth+ gets you all eleven.
              </h2>
              <p style={{ fontSize: 14.5, lineHeight: 1.6, color: 'rgba(232,236,242,.62)', margin: 0, maxWidth: 520 }}>
                CI/CD triage, Kubernetes alerts, and PR review ship on every plan. The other eight — migration,
                IAM, FinOps, runbooks, drift, on-call knowledge, dependency patching, and resource health
                monitoring — come with Growth and Enterprise.
              </p>
            </div>
            <PrimaryCta>Start free trial</PrimaryCta>
          </div>
        </section>

        <MarketingFooter />
      </div>
    </>
  )
}
