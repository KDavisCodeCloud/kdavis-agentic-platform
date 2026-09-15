import type { Metadata } from 'next'
import { MarketingHead, MarketingNav, MarketingFooter, Eyebrow, PrimaryCta, PAGE_BG, BODY_FONT, HEAD_FONT, MONO_FONT } from '@/components/marketing/SiteChrome'

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Cloud Decoded vs Microsoft Copilot vs AWS AgentCore | Comparison',
  description:
    'How Cloud Decoded differs from Microsoft Copilot and AWS AgentCore: no single-cloud lock-in, a human approval gate that can’t be silently disabled, and pricing that doesn’t require a Microsoft or AWS enterprise agreement.',
  alternates: { canonical: 'https://theclouddecoded.com/comparison' },
  openGraph: {
    type: 'website',
    url: 'https://theclouddecoded.com/comparison',
    title: 'Cloud Decoded vs Microsoft Copilot vs AWS AgentCore',
    description: 'The no-lock-in angle, stated plainly, with the tradeoffs included.',
  },
}

type Row = { label: string; cd: string; msft: string; aws: string }

const ROWS: Row[] = [
  {
    label: 'Cloud dependency',
    cd: 'None — runs against Azure, AWS, or both from day one',
    msft: 'Built around the Microsoft/Azure and GitHub ecosystem',
    aws: 'Built around the AWS ecosystem',
  },
  {
    label: 'Human approval before execution',
    cd: 'Hard gate on every action — not a configurable default, can’t be silently turned off',
    msft: 'Varies by product surface and configuration',
    aws: 'Varies by agent configuration and IAM policy',
  },
  {
    label: 'Where it runs',
    cd: 'A standalone service you connect to your existing CI/CD, Kubernetes, and cloud accounts',
    msft: 'Layered into Microsoft’s own developer and cloud tooling',
    aws: 'Layered into AWS’s own agent and cloud tooling',
  },
  {
    label: 'Buying motion',
    cd: 'Direct plans — Starter, Growth, Enterprise — no larger platform agreement required',
    msft: 'Typically bundled with or licensed alongside Microsoft 365 / Azure agreements',
    aws: 'Typically consumed as part of an AWS account and billed through AWS',
  },
  {
    label: 'Target team size',
    cd: 'Mid-market platform teams (50–500 engineers, 3+ person platform team)',
    msft: 'Broad — individual developers through large enterprises',
    aws: 'Broad — individual accounts through large enterprises',
  },
  {
    label: 'Audit trail',
    cd: 'Every proposal, approval, and rejection logged — your team stays in control by design',
    msft: 'Depends on the specific product and configuration',
    aws: 'Depends on the specific service and CloudTrail configuration',
  },
]

function ComparisonRow({ r }: { r: Row }) {
  return (
    <div
      style={{
        display: 'grid', gridTemplateColumns: 'minmax(0,1.1fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)',
        gap: 20, padding: '20px 4px', borderBottom: '1px solid rgba(255,255,255,.06)', alignItems: 'start',
      }}
    >
      <div style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 14.5, color: '#e8ecf2' }}>{r.label}</div>
      <div style={{ fontSize: 13.5, lineHeight: 1.55, color: '#3fd17a' }}>{r.cd}</div>
      <div style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.62)' }}>{r.msft}</div>
      <div style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.62)' }}>{r.aws}</div>
    </div>
  )
}

export default function ComparisonPage() {
  return (
    <>
      <MarketingHead />
      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT }}>
        <MarketingNav />

        <section style={{ padding: '64px 40px 20px', maxWidth: 1140, margin: '0 auto' }}>
          <Eyebrow label="COMPARISON" sub="updated 2026-09" />
          <h1
            style={{
              fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 44, lineHeight: 1.1,
              letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px', maxWidth: 820,
            }}
          >
            Cloud Decoded vs Microsoft Copilot vs AWS AgentCore
          </h1>
          <p style={{ fontSize: 17, lineHeight: 1.65, color: 'rgba(232,236,242,.66)', margin: '0 0 8px', maxWidth: 740 }}>
            Microsoft Copilot and AWS AgentCore are both real, capable products — and both are built around their
            own cloud. If your infrastructure is entirely Azure or entirely AWS and you’re already committed to
            that ecosystem, the vendor-native tool is a reasonable default.
          </p>
          <p style={{ fontSize: 17, lineHeight: 1.65, color: 'rgba(232,236,242,.66)', margin: 0, maxWidth: 740 }}>
            Cloud Decoded exists for the teams that aren’t in that position: multi-cloud, cloud-agnostic by
            policy, or just unwilling to let a fix execute against production without a person looking at it
            first, every time.
          </p>
        </section>

        <section style={{ padding: '30px 40px 20px', maxWidth: 1140, margin: '0 auto', overflowX: 'auto' }}>
          <div style={{ minWidth: 760 }}>
            <div
              style={{
                display: 'grid', gridTemplateColumns: 'minmax(0,1.1fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)',
                gap: 20, padding: '0 4px 14px', borderBottom: '1px solid rgba(255,255,255,.12)',
              }}
            >
              <div />
              <div style={{ fontFamily: MONO_FONT, fontSize: 11, letterSpacing: '.06em', color: '#3fd17a' }}>CLOUD DECODED</div>
              <div style={{ fontFamily: MONO_FONT, fontSize: 11, letterSpacing: '.06em', color: 'rgba(232,236,242,.5)' }}>MICROSOFT COPILOT</div>
              <div style={{ fontFamily: MONO_FONT, fontSize: 11, letterSpacing: '.06em', color: 'rgba(232,236,242,.5)' }}>AWS AGENTCORE</div>
            </div>
            {ROWS.map((r) => (
              <ComparisonRow key={r.label} r={r} />
            ))}
          </div>
          <p style={{ fontSize: 11.5, color: 'rgba(232,236,242,.35)', marginTop: 18, fontFamily: MONO_FONT }}>
            Comparison reflects Cloud Decoded’s own architecture and public positioning of the named products as
            of 2026-09. Microsoft Copilot and AWS AgentCore are trademarks of their respective owners; this page
            isn’t sponsored by or affiliated with either.
          </p>
        </section>

        <section style={{ padding: '40px 40px 100px', maxWidth: 1140, margin: '0 auto' }}>
          <div
            style={{
              padding: '38px 40px', borderRadius: 16,
              border: '1px solid rgba(120,160,255,.25)',
              background: 'linear-gradient(135deg, rgba(90,150,255,.08), rgba(7,9,16,0))',
              display: 'flex', alignItems: 'center', gap: 28, flexWrap: 'wrap',
            }}
          >
            <div style={{ flex: 1, minWidth: 280 }}>
              <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 22, color: '#fff', margin: '0 0 8px' }}>
                No migration. No lock-in. No autonomous surprise.
              </h2>
              <p style={{ fontSize: 14.5, lineHeight: 1.6, color: 'rgba(232,236,242,.62)', margin: 0, maxWidth: 520 }}>
                Connect Cloud Decoded to what you already run. It starts read-only, and nothing executes until
                you approve it.
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
