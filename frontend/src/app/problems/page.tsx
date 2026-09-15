import type { Metadata } from 'next'
import { MarketingHead, MarketingNav, MarketingFooter, Eyebrow, PrimaryCta, PAGE_BG, BODY_FONT, HEAD_FONT, MONO_FONT } from '@/components/marketing/SiteChrome'

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: '10 Problems Cloud Decoded Solves for Platform Engineering Teams',
  description:
    'The specific, recurring problems mid-market platform engineering teams hit — alert fatigue, root-cause triage eating senior hours, IAM sprawl, cost waste, dependency backlogs — and what Cloud Decoded does about each one.',
  alternates: { canonical: 'https://theclouddecoded.com/problems' },
  openGraph: {
    type: 'website',
    url: 'https://theclouddecoded.com/problems',
    title: '10 Problems Cloud Decoded Solves for Platform Engineering Teams',
    description: 'One real problem per section, one direct answer each — what Cloud Decoded does about it.',
  },
}

const PROBLEMS = [
  {
    q: 'How do you stop paging engineers for incidents that self-heal before anyone reads the alert?',
    a: 'Cloud Decoded’s Kubernetes Alert agent triages every alert before it reaches a human — a transient pod restart that self-corrects gets closed automatically with a note, not a page. Only alerts that actually need a decision reach your on-call rotation.',
  },
  {
    q: 'Why does root-cause triage eat so much senior engineering time?',
    a: 'Because reconstructing what happened from raw logs is manual, repetitive work. Cloud Decoded’s CI/CD Triage agent reads the failed run, surfaces the exact failing step, and proposes the fix in the time it takes a human to open the log tab — turning a 20-minute investigation into a 2-minute approval.',
  },
  {
    q: 'How do you avoid vendor lock-in when adopting AI-driven DevOps automation?',
    a: 'By choosing a tool with no runtime dependency on a single cloud. Cloud Decoded connects to Azure, AWS, or both, and never requires migrating your CI/CD, Kubernetes, or infrastructure tooling to adopt it.',
  },
  {
    q: 'Is it safe to let an AI agent execute changes against production infrastructure?',
    a: 'Only if nothing executes without a human approving it first. Cloud Decoded’s HITL gate is not a configurable setting that can be silently disabled — every proposed fix, from every agent, waits for explicit approval before it touches your infrastructure.',
  },
  {
    q: 'How do you clean up over-permissioned IAM roles without breaking something?',
    a: 'Cloud Decoded’s IAM Policy Minimization agent diffs what a role actually used against what it’s currently allowed to do, and proposes the tightened policy as a reviewable PR — so the least-privilege cleanup happens on your timeline, with a diff you can read before it ships.',
  },
  {
    q: 'Where does most cloud cost waste actually come from, and how do you find it?',
    a: 'Idle resources nobody remembered to delete — unattached volumes, stopped-but-still-billed instances, unused Elastic IPs. Cloud Decoded’s FinOps agent reads your real Cost Explorer or Azure Cost Management export and ranks specific, actionable fixes by real monthly savings, not a generic rightsizing report.',
  },
  {
    q: 'How do you keep Terraform state from silently drifting from what’s actually running?',
    a: 'Cloud Decoded’s Drift Detection agent compares live infrastructure state against your Terraform, CloudFormation, or Kubernetes manifests on a schedule, and opens a remediation PR the moment it finds a difference — so drift gets caught in days, not at the next incident.',
  },
  {
    q: 'How do you patch vulnerable dependencies across multiple ecosystems without a manual audit every sprint?',
    a: 'Cloud Decoded’s Dependency & Vulnerability Patching agent scans npm, pip, go, maven, ruby, and cargo manifests against OSV.dev, and proposes a patched manifest with a severity-ranked summary — as a PR, a tracking issue, or both.',
  },
  {
    q: 'How do new on-call engineers get context on an unfamiliar incident fast?',
    a: 'Cloud Decoded’s Onboarding & On-Call Buddy agent answers "what do I do about this" against your team’s actual runbooks and incident history — not a generic wiki search — so a new on-call engineer isn’t starting from zero at 2am.',
  },
  {
    q: 'How do you turn a written runbook into something that actually executes reliably?',
    a: 'Cloud Decoded’s Interactive Runbook agent turns a written procedure into a step-gated workflow: each step runs, reports its result, and waits before the next one fires — so a runbook stops being a document someone has to interpret under pressure.',
  },
]

const QA_JSON_LD = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: PROBLEMS.map((p) => ({
    '@type': 'Question',
    name: p.q,
    acceptedAnswer: { '@type': 'Answer', text: p.a },
  })),
}

function ProblemSection({ p, index }: { p: (typeof PROBLEMS)[number]; index: number }) {
  return (
    <section style={{ padding: '34px 0', borderBottom: '1px solid rgba(255,255,255,.06)' }} data-section={`problem-${index + 1}`}>
      <div style={{ display: 'flex', gap: 22, alignItems: 'flex-start' }}>
        <span style={{ fontFamily: MONO_FONT, fontSize: 13, color: 'rgba(159,194,255,.85)', paddingTop: 4, minWidth: 40 }}>
          {String(index + 1).padStart(2, '0')}
        </span>
        <div>
          <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 21, lineHeight: 1.35, color: '#f0f3f8', margin: '0 0 10px', maxWidth: 720 }}>
            {p.q}
          </h2>
          <p style={{ fontSize: 15, lineHeight: 1.65, color: 'rgba(232,236,242,.66)', margin: 0, maxWidth: 700 }}>
            {p.a}
          </p>
        </div>
      </div>
    </section>
  )
}

export default function ProblemsPage() {
  return (
    <>
      <MarketingHead />
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(QA_JSON_LD) }}
      />
      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT }}>
        <MarketingNav />

        <section style={{ padding: '64px 40px 10px', maxWidth: 900, margin: '0 auto' }}>
          <Eyebrow label="WHY CLOUD DECODED" sub="10 problems, answered directly" />
          <h1
            style={{
              fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 42, lineHeight: 1.12,
              letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px',
            }}
          >
            The problems platform teams actually page each other about.
          </h1>
          <p style={{ fontSize: 17, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: 0 }}>
            Ten specific, recurring problems — each with a direct answer, no product-brochure filler.
          </p>
        </section>

        <section style={{ padding: '20px 40px 100px', maxWidth: 900, margin: '0 auto' }} data-section="problems-list">
          {PROBLEMS.map((p, i) => (
            <ProblemSection key={p.q} p={p} index={i} />
          ))}

          <div
            style={{
              marginTop: 48, padding: '38px 40px', borderRadius: 16,
              border: '1px solid rgba(120,160,255,.25)',
              background: 'linear-gradient(135deg, rgba(90,150,255,.08), rgba(7,9,16,0))',
              display: 'flex', alignItems: 'center', gap: 28, flexWrap: 'wrap',
            }}
          >
            <div style={{ flex: 1, minWidth: 260 }}>
              <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 22, color: '#fff', margin: '0 0 8px' }}>
                See all eleven agents in detail.
              </h2>
              <p style={{ fontSize: 14.5, lineHeight: 1.6, color: 'rgba(232,236,242,.62)', margin: 0 }}>
                What each one touches, and what it needs your approval for.
              </p>
            </div>
            <PrimaryCta href="/features">View features</PrimaryCta>
          </div>
        </section>

        <MarketingFooter />
      </div>
    </>
  )
}
