import type { Metadata } from 'next'

// Landing page — full copy and positioning overhaul (2026-09). Structure
// rebuilt around customer outcomes: Hero, 10 Problems, How It Works, What
// We Monitor, Pricing, Footer. Design tokens unchanged (#070910 / #5a96ff
// / #f5a623 / #3fd17a, Space Grotesk / IBM Plex Sans / JetBrains Mono).
//
// Positioning rules enforced throughout: zero "AI" / "artificial
// intelligence" / "agentic" / "LLM" anywhere on this page; every claim is
// an outcome the customer experiences, not a technology description; the
// approval model is "your team stays in control," never "human in the
// loop"; no agent names (Agent 01, Agent 08, etc.) are shown to customers
// -- capabilities are described by what they do.
//
// This page stays a self-contained, hand-styled Server Component (not
// migrated onto components/marketing/SiteChrome) to preserve its own
// hero's custom visual treatment -- see that file's own comment for why
// it was extracted for the *other* marketing pages instead of this one.

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Cloud Decoded — Find Infrastructure Problems Faster, Fix Them With Confidence',
  description:
    'Cloud Decoded monitors Azure and AWS, surfaces every issue with a clear diagnosis, and gives your team fix options — nothing executes until you approve. No vendor lock-in.',
  alternates: { canonical: 'https://theclouddecoded.com' },
  openGraph: {
    type: 'website',
    url: 'https://theclouddecoded.com',
    title: 'Cloud Decoded — Find Infrastructure Problems Faster, Fix Them With Confidence',
    description:
      'Cloud Decoded monitors Azure and AWS, surfaces every issue with a clear diagnosis, and gives your team fix options — nothing executes until you approve. No vendor lock-in.',
    // No explicit images[] here -- app/opengraph-image.tsx (Next.js's file
    // convention) generates and serves it, auto-injected into og:image
    // and twitter:image.
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Cloud Decoded — Find Infrastructure Problems Faster, Fix Them With Confidence',
    description:
      'Cloud Decoded monitors Azure and AWS, surfaces every issue with a clear diagnosis, and gives your team fix options — nothing executes until you approve. No vendor lock-in.',
  },
}

const FAQ_JSON_LD = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: [
    {
      '@type': 'Question',
      name: 'Does Cloud Decoded require switching cloud providers?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'No. Cloud Decoded runs on top of the cloud providers you already use — Azure, AWS, or both — with no migration and no dependency on any single vendor. It connects to your existing CI/CD, Kubernetes, and infrastructure tooling rather than replacing it.',
      },
    },
    {
      '@type': 'Question',
      name: 'Can Cloud Decoded change my infrastructure without my approval?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: "No. Nothing executes against your infrastructure until your team approves it. Detection and diagnosis happen automatically, but the fix itself sits at a hard approval step that can't be silently disabled. You approve, edit, or reject every fix — your team stays in control the entire time.",
      },
    },
    {
      '@type': 'Question',
      name: 'What happens if a proposed fix is wrong?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'You reject it, and nothing happens to your infrastructure — because no fix executes before your team approves it. Every proposal shows the exact change and a diff before you decide, so a wrong suggestion is caught at review, not in production. Rejected proposals are logged alongside approved ones for a full audit trail.',
      },
    },
    {
      '@type': 'Question',
      name: 'How is this different from a cloud vendor’s own native tooling?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: "Cloud Decoded has no dependency on a single cloud vendor and no cloud-first bias — it works across Azure and AWS instead of locking you into one provider's ecosystem. Every action passes through your team's approval by design, rather than executing on its own. It's built specifically for mid-market engineering teams who want full-surface coverage without vendor lock-in.",
      },
    },
    {
      '@type': 'Question',
      name: 'What does a typical onboarding look like?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'Onboarding starts read-only: you connect Cloud Decoded to your existing CI/CD, Kubernetes, and infrastructure tools, and it begins surfacing issues with a diagnosis and fix options — without permission to execute anything. Once you trust the proposals, you enable execution so approved fixes can apply with one click. Most teams are reviewing real, specific findings within the first day.',
      },
    },
    {
      '@type': 'Question',
      name: 'Is it safe to connect Cloud Decoded to production infrastructure?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: "Yes. Cloud Decoded connects read-only by default and can't execute any change to production until your team approves it. Every proposed and approved action is recorded in a full audit trail, and access is scoped with SSO and role-based controls. You decide what it can touch, and nothing happens at 2am without your team's say-so.",
      },
    },
  ],
}

const PROBLEMS = [
  {
    n: '01',
    name: 'You find out about failures too late',
    cost: 'By the time monitoring fires, customers are already affected.',
    fix: 'Cloud Decoded surfaces problems the moment they start, across every resource type.',
  },
  {
    n: '02',
    name: 'Root cause takes longer than the fix',
    cost: '40 minutes of log-reading for a 3-minute fix.',
    fix: 'The cause is identified before your engineer opens a second tab.',
  },
  {
    n: '03',
    name: 'Your infrastructure drifts from what your code says',
    cost: "What's running and what Terraform says should be running are two different things.",
    fix: 'Drift is detected continuously and surfaced with the exact delta.',
  },
  {
    n: '04',
    name: 'Misconfigurations sit quietly until they cause an outage',
    cost: 'IAM rules, NSGs, storage policies — small gaps become big incidents.',
    fix: 'Continuous misconfiguration checks across all five infrastructure domains.',
  },
  {
    n: '05',
    name: "One engineer can't watch everything",
    cost: 'Two clouds, five domains, one team. Something gets missed.',
    fix: 'Full-surface monitoring in one dashboard, no manual checking required.',
  },
  {
    n: '06',
    name: 'On-call means starting from a blank screen',
    cost: 'A page fires at 2am. Five consoles. No context.',
    fix: 'The alert, the diagnosis, and the fix options arrive together.',
  },
  {
    n: '07',
    name: "Junior engineers don't know the right fix",
    cost: 'Senior engineers are overloaded. Everyone else guesses.',
    fix: 'Fix options are surfaced — the engineer approves, it executes.',
  },
  {
    n: '08',
    name: 'Compliance posture slips between audits',
    cost: 'Drift accumulates silently until an auditor finds it.',
    fix: 'Continuous CIS benchmark and RBAC compliance checks.',
  },
  {
    n: '09',
    name: 'Pipeline failures waste cycles',
    cost: 'A failed deploy with no clear diagnosis means trial and error.',
    fix: 'Deploy failures are diagnosed immediately across Terraform, Bicep, ARM, and CloudFormation.',
  },
  {
    n: '10',
    name: 'Nothing is documented after an incident',
    cost: 'Post-mortems require piecing together Slack threads and memory.',
    fix: 'Every detection, approval, and execution is logged automatically.',
  },
]

const MONITOR_DOMAINS = [
  {
    id: 'M·01',
    name: 'Compute',
    body: 'EC2, VMs, App Service, AKS, and EKS node pools — health, capacity, and restarts watched continuously.',
    chips: ['EC2', 'Azure VMs', 'App Service', 'AKS', 'EKS'],
  },
  {
    id: 'M·02',
    name: 'Networking',
    body: 'NSGs, VPCs, load balancers, VPN tunnels, DNS, firewalls, and private endpoints checked for exposure and misrouting.',
    chips: ['NSGs', 'VPCs', 'Load balancers', 'VPN', 'DNS', 'Firewalls'],
  },
  {
    id: 'M·03',
    name: 'Storage',
    body: 'S3 and Azure Blob encryption, access policy, and replication health checked against expected configuration.',
    chips: ['S3', 'Azure Blob', 'Encryption', 'Replication'],
  },
  {
    id: 'M·04',
    name: 'Identity & Access',
    body: 'IAM roles, Azure RBAC, managed identities, and policy compliance drift surfaced before they become an exposure.',
    chips: ['IAM', 'Azure RBAC', 'Managed identities'],
  },
  {
    id: 'M·05',
    name: 'Pipelines & Deployments',
    body: 'GitHub Actions and Azure DevOps failures diagnosed across Terraform, Bicep, ARM, and CloudFormation deploys.',
    chips: ['GitHub Actions', 'Azure DevOps', 'Terraform', 'Bicep', 'ARM', 'CloudFormation'],
  },
  {
    id: 'M·06',
    name: 'Live Resource Health',
    body: 'Availability alerts, performance thresholds, and capacity warnings caught the moment your cloud provider fires them.',
    chips: ['CloudWatch', 'Azure Monitor', 'Thresholds', 'Capacity'],
  },
]

export default function LandingPage() {
  return (
    <>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link
        href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap"
        rel="stylesheet"
      />
      <style>{`
        @keyframes cd-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-12px)}}
        @keyframes cd-float2{0%,100%{transform:translateY(0)}50%{transform:translateY(-18px)}}
        @keyframes cd-glow{0%,100%{opacity:.6}50%{opacity:1}}
        @media (prefers-reduced-motion: reduce){.cd-anim{animation:none !important}}
      `}</style>
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(FAQ_JSON_LD) }}
      />

      <div style={{ width: 1280, margin: '0 auto', background: '#070910', overflow: 'hidden', maxWidth: '100%' }}>
        {/* ================= HERO ================= */}
        <header
          style={{
            position: 'relative',
            width: '100%',
            minHeight: 780,
            background: '#070910',
            overflow: 'hidden',
            fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 0,
              backgroundImage:
                'linear-gradient(rgba(120,160,255,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(120,160,255,.045) 1px,transparent 1px)',
              backgroundSize: '52px 52px',
              WebkitMaskImage: 'radial-gradient(130% 100% at 70% 40%,#000,transparent 72%)',
              maskImage: 'radial-gradient(130% 100% at 70% 40%,#000,transparent 72%)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              top: 80,
              right: 120,
              width: 680,
              height: 680,
              background: 'radial-gradient(circle,rgba(47,111,230,.3),transparent 60%)',
            }}
          />

          <nav
            style={{
              position: 'relative',
              zIndex: 5,
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              padding: '22px 40px',
            }}
          >
            <div
              style={{
                position: 'relative',
                width: 26,
                height: 26,
                borderRadius: 8,
                background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 0 14px rgba(61,125,255,.55)',
              }}
            >
              <div
                style={{
                  width: 13,
                  height: 13,
                  background: '#fff',
                  clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)',
                }}
              />
            </div>
            <span
              style={{
                fontFamily: "'Space Grotesk',sans-serif",
                fontWeight: 600,
                fontSize: 16,
                color: '#fff',
                letterSpacing: '-.01em',
              }}
            >
              Cloud Decoded
            </span>
            <div style={{ marginLeft: 34, display: 'flex', gap: 26, fontSize: 13 }}>
              <a href="#problems" style={{ color: 'rgba(232,236,242,.62)', textDecoration: 'none' }}>
                Problems
              </a>
              <a href="#how-it-works" style={{ color: 'rgba(232,236,242,.62)', textDecoration: 'none' }}>
                How it works
              </a>
              <a href="#monitor" style={{ color: 'rgba(232,236,242,.62)', textDecoration: 'none' }}>
                What we monitor
              </a>
              <a href="#pricing" style={{ color: 'rgba(232,236,242,.62)', textDecoration: 'none' }}>
                Pricing
              </a>
              <a href="/blog" style={{ color: 'rgba(232,236,242,.62)', textDecoration: 'none' }}>
                Blog
              </a>
            </div>
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 16 }}>
              <a href="/login" style={{ fontSize: 13, color: 'rgba(232,236,242,.7)', textDecoration: 'none' }}>
                Sign in
              </a>
              <a
                href="/signup"
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: '#06101f',
                  background: '#e8ecf2',
                  padding: '8px 15px',
                  borderRadius: 8,
                  textDecoration: 'none',
                }}
              >
                Start free
              </a>
            </div>
          </nav>

          <div style={{ position: 'relative', zIndex: 4, padding: '120px 40px 90px', maxWidth: 520 }}>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                fontFamily: "'JetBrains Mono',monospace",
                fontSize: 11,
                letterSpacing: '.04em',
                color: '#9fc2ff',
                border: '1px solid rgba(120,160,255,.28)',
                background: 'rgba(47,111,230,.08)',
                padding: '6px 12px',
                borderRadius: 99,
                marginBottom: 24,
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: '#f5a623',
                  boxShadow: '0 0 8px #f5a623',
                }}
              />
              DETECT → DIAGNOSE → YOU APPROVE → RESOLVE
            </div>
            <h1
              style={{
                fontFamily: "'Space Grotesk',sans-serif",
                fontWeight: 600,
                fontSize: 52,
                lineHeight: 1.08,
                letterSpacing: '-.025em',
                color: '#fff',
                margin: '0 0 22px',
              }}
            >
              Your infrastructure problems, <span style={{ color: '#5a96ff' }}>found faster and fixed with confidence.</span>
            </h1>
            <p
              style={{
                fontSize: 17,
                lineHeight: 1.6,
                color: 'rgba(232,236,242,.66)',
                margin: '0 0 30px',
                maxWidth: 480,
              }}
            >
              Cloud Decoded monitors Azure and AWS, surfaces every issue with a clear diagnosis, and gives your team
              fix options — nothing executes until you approve.
            </p>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <a
                href="#demo"
                style={{
                  textDecoration: 'none',
                  fontSize: 14,
                  fontWeight: 600,
                  color: '#06101f',
                  background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)',
                  padding: '13px 22px',
                  borderRadius: 10,
                  boxShadow: '0 12px 30px -10px rgba(61,125,255,.7)',
                }}
              >
                See it in action
              </a>
              <a
                href="/signup"
                style={{
                  textDecoration: 'none',
                  fontSize: 14,
                  fontWeight: 500,
                  color: 'rgba(232,236,242,.85)',
                  border: '1px solid rgba(255,255,255,.16)',
                  padding: '13px 22px',
                  borderRadius: 10,
                }}
              >
                Start free
              </a>
            </div>
            <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)', margin: '18px 0 0' }}>
              14-day money-back guarantee · no card required to start
            </p>

            {/* Social proof bar */}
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 14,
                marginTop: 48,
                paddingTop: 28,
                borderTop: '1px solid rgba(255,255,255,.08)',
              }}
            >
              {['1,500+ tests passing in production', 'Azure + AWS + Kubernetes', 'SOC 2-ready architecture'].map(stat => (
                <div
                  key={stat}
                  style={{
                    fontFamily: "'JetBrains Mono',monospace",
                    fontSize: 11.5,
                    color: 'rgba(232,236,242,.55)',
                    border: '1px solid rgba(255,255,255,.1)',
                    borderRadius: 8,
                    padding: '8px 13px',
                  }}
                >
                  {stat}
                </div>
              ))}
            </div>
          </div>

          {/* Dimmed background decoration -- static approximation of the
              app's real, authenticated incident console, not the live
              component (restored from the previous hero iteration; text
              updated to match this iteration's positioning). */}
          <div
            style={{
              position: 'absolute',
              zIndex: 2,
              right: -160,
              top: 90,
              width: 560,
              height: 700,
              perspective: 1800,
              WebkitMaskImage: 'linear-gradient(180deg,#000 70%,transparent)',
              maskImage: 'linear-gradient(180deg,#000 70%,transparent)',
            }}
          >
            <div
              style={{
                width: 760,
                transform: 'rotateY(-20deg) rotateX(5deg) scale(.66)',
                transformOrigin: 'top left',
                opacity: 0.5,
                filter: 'blur(1.5px) saturate(.8)',
                boxShadow: '0 40px 100px -40px rgba(0,0,0,.9)',
                background: '#0a0d16',
                border: '1px solid rgba(255,255,255,.08)',
                borderRadius: 14,
                padding: 20,
              }}
            >
              <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 18, color: '#fff' }}>
                Incident console
              </div>
              <div
                style={{
                  marginTop: 16,
                  height: 900,
                  background:
                    'repeating-linear-gradient(180deg, rgba(255,255,255,.03) 0 60px, transparent 60px 64px)',
                  borderRadius: 10,
                }}
              />
            </div>
          </div>

          <div
            className="cd-anim"
            style={{
              position: 'absolute',
              zIndex: 4,
              right: 120,
              top: 248,
              width: 430,
              background: 'linear-gradient(180deg,#121826,#0c111c)',
              border: '1px solid rgba(74,139,255,.4)',
              borderRadius: 14,
              padding: 18,
              boxShadow: '0 40px 90px -30px rgba(0,0,0,.9),0 0 60px -18px rgba(61,125,255,.45)',
              animation: 'cd-float2 8s ease-in-out infinite',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 11 }}>
              <span
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 18,
                  height: 18,
                  borderRadius: '50%',
                  border: '2px solid #f5a623',
                }}
              >
                <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#f5a623' }} />
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 13, fontWeight: 600, color: '#fff' }}>
                #inc-007
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 10,
                  color: 'rgba(232,236,242,.75)',
                  background: 'rgba(255,255,255,.06)',
                  border: '1px solid rgba(255,255,255,.1)',
                  borderRadius: 5,
                  padding: '2px 7px',
                }}
              >
                Kubernetes
              </span>
              <span
                style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#f5a623' }}
              >
                NEEDS ACTION
              </span>
            </div>
            <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.8)', margin: '0 0 13px' }}>
              Pod <span style={{ fontFamily: "'JetBrains Mono',monospace", color: '#9fc2ff' }}>checkout-api</span> in{' '}
              <span style={{ color: '#ffb84d' }}>CrashLoopBackOff</span> — OOMKilled, leak in{' '}
              <span style={{ fontFamily: "'JetBrains Mono',monospace", color: '#9fc2ff' }}>v2.4.2</span>.
            </p>
            <div
              style={{
                border: '1px dashed rgba(245,166,35,.4)',
                background: 'rgba(245,166,35,.06)',
                borderRadius: 9,
                padding: '11px 12px',
              }}
            >
              <div
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 9,
                  letterSpacing: '.08em',
                  color: 'rgba(245,166,35,.9)',
                  marginBottom: 5,
                }}
              >
                PROPOSED FIX · AWAITING YOUR APPROVAL
              </div>
              <div style={{ fontSize: 12.5, color: '#f0f3f8', marginBottom: 12 }}>
                Roll back to <span style={{ fontFamily: "'JetBrains Mono',monospace", color: '#9fc2ff' }}>v2.4.1</span>{' '}
                &amp; raise limit → 768Mi
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: '#06101f',
                    background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)',
                    padding: '8px 14px',
                    borderRadius: 8,
                    boxShadow: '0 6px 18px -6px rgba(61,125,255,.7)',
                  }}
                >
                  Approve &amp; Execute
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 500,
                    color: 'rgba(232,236,242,.8)',
                    border: '1px solid rgba(255,255,255,.15)',
                    padding: '8px 13px',
                    borderRadius: 8,
                  }}
                >
                  View diff
                </span>
              </div>
            </div>
          </div>

          <div
            className="cd-anim"
            style={{
              position: 'absolute',
              zIndex: 5,
              right: 78,
              top: 198,
              display: 'flex',
              alignItems: 'center',
              gap: 9,
              background: '#0c111c',
              border: '1px solid rgba(245,166,35,.45)',
              borderRadius: 99,
              padding: '8px 14px',
              boxShadow: '0 18px 40px -14px rgba(0,0,0,.9)',
              animation: 'cd-float 6s ease-in-out infinite',
            }}
          >
            <span
              style={{
                width: 18,
                height: 18,
                borderRadius: '50%',
                background: 'rgba(245,166,35,.16)',
                border: '2px solid #f5a623',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#f5a623' }} />
            </span>
            <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: '#f5a623', fontWeight: 600 }}>
              awaiting approval
            </span>
          </div>

          <div
            className="cd-anim"
            style={{
              position: 'absolute',
              zIndex: 5,
              right: 230,
              top: 560,
              background: '#0c111c',
              border: '1px solid rgba(255,255,255,.1)',
              borderRadius: 12,
              padding: '13px 16px',
              boxShadow: '0 24px 50px -18px rgba(0,0,0,.9)',
              animation: 'cd-float2 9s ease-in-out infinite',
            }}
          >
            <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 22, color: '#fff' }}>
              6 domains
            </div>
            <div
              style={{
                fontFamily: "'JetBrains Mono',monospace",
                fontSize: 9,
                letterSpacing: '.06em',
                color: 'rgba(232,236,242,.45)',
                marginTop: 2,
              }}
            >
              COMPUTE · NETWORK · STORAGE · IAM · CI/CD · HEALTH
            </div>
          </div>
        </header>

        {/* ================= 10 PROBLEMS ================= */}
        <section
          id="problems"
          style={{
            position: 'relative', width: '100%', padding: '96px 40px 104px', boxSizing: 'border-box',
            background: '#070910', fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 1140, margin: '0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 26 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.12em', color: 'rgba(245,166,35,.9)', border: '1px solid rgba(245,166,35,.32)', borderRadius: 5, padding: '4px 9px' }}>
                THE PROBLEMS
              </span>
              <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,.12),transparent)' }} />
            </div>
            <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 42, lineHeight: 1.08, letterSpacing: '-.025em', color: '#fff', margin: '0 0 14px', maxWidth: 780 }}>
              The problems your team deals with every day.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 0 56px', maxWidth: 680 }}>
              Cloud Decoded was built to solve each one.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 18 }}>
              {PROBLEMS.map(p => (
                <article
                  key={p.n}
                  style={{
                    border: '1px solid rgba(255,255,255,.08)', borderRadius: 14,
                    background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))',
                    padding: 20, display: 'flex', flexDirection: 'column',
                  }}
                >
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.4)', marginBottom: 12 }}>
                    PROBLEM·{p.n}
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 17, lineHeight: 1.28, color: '#fff', margin: '0 0 14px' }}>
                    {p.name}
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 'auto' }}>
                    <div style={{ fontSize: 12.5, lineHeight: 1.5, color: 'rgba(255,138,122,.85)' }}>
                      <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.06em', color: 'rgba(255,138,122,.7)' }}>COST </span>
                      {p.cost}
                    </div>
                    <div style={{ fontSize: 12.5, lineHeight: 1.5, color: 'rgba(63,209,122,.9)' }}>
                      <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.06em', color: 'rgba(63,209,122,.75)' }}>FIX </span>
                      {p.fix}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ================= HOW IT WORKS ================= */}
        <section
          id="how-it-works"
          style={{
            position: 'relative', width: '100%', padding: '96px 40px 110px', boxSizing: 'border-box',
            background: 'linear-gradient(180deg,#070910,#090c16 50%,#070910)', fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 1140, margin: '0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 26 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.12em', color: 'rgba(159,194,255,.9)', border: '1px solid rgba(120,160,255,.32)', borderRadius: 5, padding: '4px 9px' }}>
                HOW IT WORKS
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.06em', color: 'rgba(232,236,242,.4)' }}>
                three steps, one of them is you
              </span>
              <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,.12),transparent)' }} />
            </div>

            <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 42, lineHeight: 1.08, letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px', maxWidth: 760 }}>
              Connect it, see the issue, make the call.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 0 60px', maxWidth: 700 }}>
              Cloud Decoded connects to what you already run, surfaces issues with full context, and stops. Nothing
              touches your infrastructure until your team approves it.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.12fr 1fr', gap: 0, alignItems: 'stretch' }}>
              {/* STEP 01 CONNECT */}
              <div style={{ position: 'relative', padding: '0 18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 18 }}>
                  <span
                    style={{
                      width: 34, height: 34, borderRadius: 9, border: '1px solid rgba(120,160,255,.35)',
                      background: 'rgba(47,111,230,.1)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 15, color: '#9fc2ff',
                    }}
                  >
                    1
                  </span>
                  <div style={{ flex: 1, height: 1, background: 'rgba(120,160,255,.5)' }} />
                  <span style={{ color: 'rgba(120,160,255,.7)', fontSize: 16, marginRight: -4 }}>→</span>
                </div>
                <div style={{ border: '1px solid rgba(255,255,255,.08)', borderRadius: 13, background: 'rgba(255,255,255,.02)', padding: '20px 18px', height: 210, boxSizing: 'border-box' }}>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: 'rgba(159,194,255,.85)', marginBottom: 12 }}>
                    STEP 01 · CONNECT
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: 1.2, color: '#fff', margin: '0 0 10px' }}>
                    Connect your environment.
                  </h3>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.6)', margin: 0 }}>
                    Link your Azure or AWS account and your IaC repositories. Takes minutes. Nothing starts
                    monitoring until you&apos;ve confirmed the scope.
                  </p>
                </div>
              </div>

              {/* STEP 02 SURFACE — THE HIGHLIGHT */}
              <div style={{ position: 'relative', padding: '0 18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 18 }}>
                  <span
                    style={{
                      width: 34, height: 34, borderRadius: 9, border: '1px solid rgba(245,166,35,.45)',
                      background: 'rgba(245,166,35,.12)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 15, color: '#f5a623',
                    }}
                  >
                    2
                  </span>
                  <div style={{ flex: 1, height: 1, background: 'rgba(245,166,35,.5)' }} />
                  <span style={{ color: 'rgba(245,166,35,.8)', fontSize: 16, marginRight: -4 }}>→</span>
                </div>
                <div style={{ border: '1px solid rgba(255,255,255,.08)', borderRadius: 13, background: 'rgba(255,255,255,.02)', padding: '20px 18px', height: 210, boxSizing: 'border-box' }}>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: '#f5a623', marginBottom: 12 }}>
                    STEP 02 · ISSUES SURFACE
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: 1.2, color: '#fff', margin: '0 0 10px' }}>
                    Full context, no digging.
                  </h3>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.6)', margin: 0 }}>
                    When something goes wrong or drifts from expected state, it appears in your dashboard — with
                    the cause already identified and specific fix options ready to review.
                  </p>
                </div>
              </div>

              {/* STEP 03 YOU APPROVE — THE GATE */}
              <div style={{ position: 'relative', padding: '0 18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 18 }}>
                  <span
                    style={{
                      width: 34, height: 34, borderRadius: 9, border: '2px solid #3fd17a',
                      background: 'rgba(63,209,122,.16)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: "'Space Grotesk',sans-serif", fontWeight: 700, fontSize: 15, color: '#3fd17a',
                      boxShadow: '0 0 18px -2px rgba(63,209,122,.6)',
                    }}
                  >
                    3
                  </span>
                  <div style={{ flex: 1, height: 2, background: 'repeating-linear-gradient(90deg,rgba(63,209,122,.7) 0 6px,transparent 6px 12px)' }} />
                </div>
                <div
                  style={{
                    position: 'relative', border: '1.5px solid rgba(63,209,122,.55)', borderRadius: 13,
                    background: 'linear-gradient(180deg,rgba(63,209,122,.09),rgba(8,20,14,.4))', padding: '20px 18px',
                    height: 210, boxSizing: 'border-box',
                    boxShadow: '0 0 0 1px rgba(63,209,122,.12),0 24px 60px -24px rgba(63,209,122,.4)',
                    transform: 'translateY(-10px)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: '#3fd17a', fontWeight: 700 }}>
                      STEP 03 · APPROVE
                    </span>
                    <span style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 8.5, letterSpacing: '.1em', color: '#06101f', background: '#3fd17a', borderRadius: 4, padding: '2px 6px', fontWeight: 700 }}>
                      YOU DECIDE
                    </span>
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: 1.2, color: '#fff', margin: '0 0 10px' }}>
                    Approve and move on.
                  </h3>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.72)', margin: 0 }}>
                    Select the fix you want. It executes. Everything is logged. Your team made the call.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ================= WHAT WE MONITOR ================= */}
        <section
          id="monitor"
          style={{
            position: 'relative', width: '100%', padding: '96px 40px 110px', boxSizing: 'border-box',
            background: '#070910', fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 1140, margin: '0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 26 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.12em', color: 'rgba(159,194,255,.9)', border: '1px solid rgba(120,160,255,.32)', borderRadius: 5, padding: '4px 9px' }}>
                WHAT WE MONITOR
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.06em', color: 'rgba(232,236,242,.4)' }}>
                six domains · one dashboard
              </span>
              <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,.12),transparent)' }} />
            </div>

            <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 42, lineHeight: 1.08, letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px', maxWidth: 780 }}>
              Full-surface infrastructure coverage.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 0 56px', maxWidth: 720 }}>
              Six domains, watched continuously across Azure and AWS — so nothing depends on one engineer
              remembering to check.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 18 }}>
              {MONITOR_DOMAINS.map(d => (
                <article
                  key={d.id}
                  style={{
                    border: '1px solid rgba(255,255,255,.08)', borderRadius: 14,
                    background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))',
                    padding: 20, display: 'flex', flexDirection: 'column',
                  }}
                >
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.45)', marginBottom: 14 }}>
                    {d.id}
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 18, lineHeight: 1.22, color: '#fff', margin: '0 0 9px' }}>
                    {d.name}
                  </h3>
                  <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.58)', margin: '0 0 16px', flex: 1 }}>
                    {d.body}
                  </p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {d.chips.map(chip => (
                      <span
                        key={chip}
                        style={{
                          fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(159,194,255,.85)',
                          border: '1px solid rgba(120,160,255,.25)', background: 'rgba(47,111,230,.06)',
                          borderRadius: 5, padding: '4px 8px',
                        }}
                      >
                        {chip}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* ================= DEMO EMBED =================
            TO GO LIVE: replace the poster div below with a real
            <iframe src="https://www.loom.com/embed/REPLACE_WITH_VIDEO_ID" ... />
        */}
        <section
          id="demo"
          style={{
            position: 'relative', width: '100%', padding: '100px 40px 110px', boxSizing: 'border-box',
            background: 'linear-gradient(180deg,#070910,#090c16 55%,#070910)', fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 1000, margin: '0 auto', textAlign: 'center' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, marginBottom: 22 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.12em', color: 'rgba(159,194,255,.9)', border: '1px solid rgba(120,160,255,.32)', borderRadius: 5, padding: '4px 9px' }}>
                WALKTHROUGH
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)' }}>runtime 3:48</span>
            </div>
            <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 40, lineHeight: 1.1, letterSpacing: '-.025em', color: '#fff', margin: '0 0 14px' }}>
              Watch it run, start to approval.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 auto 44px', maxWidth: 620 }}>
              See a real incident go from detection to your team&apos;s approval — in under four minutes.
            </p>

            <div style={{ position: 'relative', borderRadius: 16, padding: 1, background: 'linear-gradient(160deg,rgba(120,160,255,.45),rgba(255,255,255,.04) 40%,rgba(245,166,35,.2))', boxShadow: '0 50px 120px -40px rgba(0,0,0,.9),0 0 90px -30px rgba(47,111,230,.4)' }}>
              <div style={{ position: 'relative', borderRadius: 15, overflow: 'hidden', background: '#080b13' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '11px 16px', borderBottom: '1px solid rgba(255,255,255,.06)', background: '#0c111c' }}>
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ff5f57' }} />
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#febc2e' }} />
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#28c840' }} />
                  <span style={{ marginLeft: 14, fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.45)' }}>
                    cloud-decoded · live-incident-walkthrough.mp4
                  </span>
                </div>
                <div style={{ position: 'relative', aspectRatio: '16/9', background: 'radial-gradient(120% 120% at 50% 0%,#0e1422,#070910)', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                  <div style={{ position: 'absolute', inset: 0, backgroundImage: 'linear-gradient(rgba(120,160,255,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(120,160,255,.06) 1px,transparent 1px)', backgroundSize: '46px 46px', WebkitMaskImage: 'radial-gradient(80% 80% at 50% 45%,#000,transparent 75%)', maskImage: 'radial-gradient(80% 80% at 50% 45%,#000,transparent 75%)' }} />
                  <div style={{ position: 'absolute', left: 0, right: 0, bottom: 34, display: 'flex', alignItems: 'center', gap: 0, padding: '0 60px' }}>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#9fc2ff' }}>DETECT</span>
                    <span style={{ flex: 1, height: 1, background: 'rgba(120,160,255,.4)', margin: '0 10px' }} />
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#9fc2ff' }}>DIAGNOSE</span>
                    <span style={{ flex: 1, height: 1, background: 'rgba(120,160,255,.4)', margin: '0 10px' }} />
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#f5a623' }}>YOU APPROVE</span>
                    <span style={{ flex: 1, height: 1, background: 'repeating-linear-gradient(90deg,rgba(245,166,35,.6) 0 5px,transparent 5px 10px)', margin: '0 10px' }} />
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#3fd17a' }}>RESOLVE</span>
                  </div>
                  <div style={{ position: 'relative', zIndex: 2, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
                    <div style={{ width: 78, height: 78, borderRadius: '50%', background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 18px 50px -10px rgba(61,125,255,.8),0 0 0 10px rgba(90,150,255,.1)' }}>
                      <span style={{ width: 0, height: 0, borderLeft: '22px solid #fff', borderTop: '13px solid transparent', borderBottom: '13px solid transparent', marginLeft: 6 }} />
                    </div>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.08em', color: 'rgba(232,236,242,.55)' }}>
                      PLAY WALKTHROUGH · 3:48
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div style={{ marginTop: 42, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
              <a href="/signup" style={{ textDecoration: 'none', fontSize: 15, fontWeight: 600, color: '#06101f', background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: '15px 30px', borderRadius: 11, boxShadow: '0 14px 34px -10px rgba(61,125,255,.75)' }}>
                Start free
              </a>
              <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.42)', margin: 0 }}>
                14-day money-back guarantee · no card required to start
              </p>
            </div>
          </div>
        </section>

        {/* ================= PRICING ================= */}
        <section
          id="pricing"
          style={{
            position: 'relative', width: '100%', padding: '96px 40px 110px', boxSizing: 'border-box',
            background: '#070910', fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 1100, margin: '0 auto' }}>
            <div style={{ textAlign: 'center', marginBottom: 14 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.12em', color: 'rgba(159,194,255,.9)', border: '1px solid rgba(120,160,255,.32)', borderRadius: 5, padding: '4px 9px' }}>
                PRICING
              </span>
            </div>
            <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 42, lineHeight: 1.08, letterSpacing: '-.025em', color: '#fff', margin: '0 0 14px', textAlign: 'center' }}>
              Pricing that scales with your stack.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 auto 56px', maxWidth: 640, textAlign: 'center' }}>
              Cloud Decoded pricing starts at $299 per month. Flat monthly tiers — no per-incident metering, no
              per-seat surprises, no annual lock-in required.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 20, alignItems: 'stretch' }}>
              <div style={{ border: '1px solid rgba(255,255,255,.08)', borderRadius: 16, background: 'linear-gradient(180deg,rgba(255,255,255,.02),rgba(255,255,255,0))', padding: '28px 26px', display: 'flex', flexDirection: 'column' }}>
                <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.1em', color: 'rgba(232,236,242,.5)', marginBottom: 16 }}>STARTER</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 6 }}>
                  <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 44, letterSpacing: '-.02em', color: '#fff' }}>$299</span>
                  <span style={{ fontSize: 14, color: 'rgba(232,236,242,.5)' }}>/mo</span>
                </div>
                <p style={{ fontSize: 13.5, lineHeight: 1.5, color: 'rgba(232,236,242,.55)', margin: '0 0 22px' }}>
                  For a single team putting its first workflows under your team&apos;s control.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginBottom: 26 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Pipeline failure diagnosis and Kubernetes alert triage</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Core integrations — GitHub Actions, Azure DevOps, Kubernetes</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Approval console — full review UI, audit log, diff view</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Up to 3 team members</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Community support</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.38)' }}><span style={{ color: 'rgba(255,255,255,.28)' }}>✕</span>No SSO</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.38)' }}><span style={{ color: 'rgba(255,255,255,.28)' }}>✕</span>No role-based access</div>
                </div>
                <a href="/signup" style={{ marginTop: 'auto', textAlign: 'center', display: 'block', textDecoration: 'none', fontSize: 14, fontWeight: 500, color: '#e8ecf2', border: '1px solid rgba(255,255,255,.18)', padding: 12, borderRadius: 10 }}>
                  Start free
                </a>
              </div>

              <div style={{ position: 'relative', border: '1px solid rgba(120,160,255,.5)', borderRadius: 16, background: 'linear-gradient(180deg,rgba(47,111,230,.1),rgba(255,255,255,.01))', padding: '28px 26px', display: 'flex', flexDirection: 'column', boxShadow: '0 24px 70px -30px rgba(47,111,230,.5)' }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.1em', color: '#9fc2ff' }}>GROWTH</span>
                  <span style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 9.5, letterSpacing: '.08em', color: '#9fc2ff', border: '1px solid rgba(120,160,255,.4)', borderRadius: 5, padding: '3px 8px' }}>MOST POPULAR</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 6 }}>
                  <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 44, letterSpacing: '-.02em', color: '#fff' }}>$699</span>
                  <span style={{ fontSize: 14, color: 'rgba(232,236,242,.5)' }}>/mo</span>
                </div>
                <p style={{ fontSize: 13.5, lineHeight: 1.5, color: 'rgba(232,236,242,.6)', margin: '0 0 22px' }}>
                  For engineering orgs monitoring full-surface coverage across multiple services.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginBottom: 26 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>Full-surface coverage — compute, networking, storage, identity, pipelines, resource health</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>Continuous IaC drift detection across Terraform, Bicep, ARM, CloudFormation</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>All integrations — GitHub, Azure DevOps, AWS, PagerDuty, Slack</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>Approval console + full audit log — 90-day history, exportable</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>Up to 15 team members</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>SSO (SAML/OIDC)</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>Priority email support — 1 business day response</div>
                </div>
                <a href="/signup" style={{ marginTop: 'auto', textAlign: 'center', display: 'block', textDecoration: 'none', fontSize: 14, fontWeight: 600, color: '#06101f', background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 12, borderRadius: 10, boxShadow: '0 12px 30px -10px rgba(61,125,255,.7)' }}>
                  Start free
                </a>
              </div>

              <div style={{ border: '1px solid rgba(255,255,255,.08)', borderRadius: 16, background: 'linear-gradient(180deg,rgba(255,255,255,.02),rgba(255,255,255,0))', padding: '28px 26px', display: 'flex', flexDirection: 'column' }}>
                <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.1em', color: 'rgba(232,236,242,.5)', marginBottom: 16 }}>ENTERPRISE</div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 6 }}>
                  <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 44, letterSpacing: '-.02em', color: '#fff' }}>$2,499</span>
                  <span style={{ fontSize: 14, color: 'rgba(232,236,242,.5)' }}>/mo</span>
                </div>
                <p style={{ fontSize: 13.5, lineHeight: 1.5, color: 'rgba(232,236,242,.55)', margin: '0 0 22px' }}>
                  For regulated teams that need audit depth, SLAs, and dedicated support.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginBottom: 26 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Everything in Growth, plus continuous CIS benchmark compliance checks</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Custom integrations — bespoke connectors for your stack</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Full audit log + role-based access — 1-year history, scoped approvals, exportable for compliance</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Unlimited team members</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>SSO + automated user provisioning</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Dedicated support + SLA — named CSM, 4-hour response, uptime SLA</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Data residency options — client-configurable region</div>
                </div>
                <a href="mailto:hello@theclouddecoded.com?subject=Enterprise%20inquiry" style={{ marginTop: 'auto', textAlign: 'center', display: 'block', textDecoration: 'none', fontSize: 14, fontWeight: 500, color: 'rgba(232,236,242,.7)', border: '1px solid rgba(255,255,255,.12)', padding: 12, borderRadius: 10 }}>
                  Talk to us
                </a>
              </div>
            </div>
          </div>
        </section>

        {/* ================= FINAL CTA ================= */}
        <section
          id="cta"
          style={{
            position: 'relative', width: '100%', padding: '104px 40px 116px', boxSizing: 'border-box',
            background: 'radial-gradient(120% 90% at 50% 0%,#0c1322,#070910 62%)', overflow: 'hidden',
            fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div className="cd-anim" style={{ position: 'absolute', left: 0, right: 0, top: 300, height: 200, background: 'radial-gradient(60% 100% at 50% 0%,rgba(47,111,230,.34),transparent 70%)', animation: 'cd-glow 5s ease-in-out infinite' }} />
          <div style={{ position: 'absolute', left: '50%', top: 340, width: 2600, height: 760, transform: 'translateX(-50%) perspective(620px) rotateX(64deg)', transformOrigin: '50% 0', backgroundImage: 'linear-gradient(rgba(120,170,255,.22) 1px,transparent 1px),linear-gradient(90deg,rgba(120,170,255,.22) 1px,transparent 1px)', backgroundSize: '60px 60px', WebkitMaskImage: 'linear-gradient(180deg,#000 0,transparent 55%)', maskImage: 'linear-gradient(180deg,#000 0,transparent 55%)' }} />

          <div style={{ position: 'relative', zIndex: 2, maxWidth: 920, margin: '0 auto', textAlign: 'center' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.04em', color: '#9fc2ff', border: '1px solid rgba(120,160,255,.28)', background: 'rgba(47,111,230,.08)', padding: '6px 12px', borderRadius: 99, marginBottom: 26 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f5a623', boxShadow: '0 0 8px #f5a623' }} />
              BUILT BY ENGINEERS WHO&apos;VE LIVED THE 2AM PAGE
            </div>

            <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 52, lineHeight: 1.05, letterSpacing: '-.03em', color: '#fff', margin: '0 0 22px' }}>
              Keep the control.
              <br />
              Lose the 2am page.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 auto 40px', maxWidth: 600 }}>
              Full-surface infrastructure coverage for mid-market engineering teams — without handing your
              infrastructure, your runtime, or your judgment to a single vendor.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16, marginBottom: 44, textAlign: 'left' }}>
              <div style={{ border: '1px solid rgba(255,255,255,.1)', borderRadius: 13, background: 'rgba(255,255,255,.025)', padding: '18px 18px' }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, border: '1px solid rgba(120,160,255,.35)', background: 'rgba(47,111,230,.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 13, color: '#9fc2ff', fontFamily: "'JetBrains Mono',monospace", fontSize: 14 }}>⌁</div>
                <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff', marginBottom: 6 }}>No vendor lock-in</div>
                <p style={{ fontSize: 13, lineHeight: 1.5, color: 'rgba(232,236,242,.58)', margin: 0 }}>
                  No dependency on a single cloud vendor&apos;s runtime or billing. Your coverage isn&apos;t bolted
                  to anyone&apos;s platform.
                </p>
              </div>
              <div style={{ border: '1px solid rgba(245,166,35,.3)', borderRadius: 13, background: 'rgba(245,166,35,.05)', padding: '18px 18px' }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, border: '1px solid rgba(245,166,35,.45)', background: 'rgba(245,166,35,.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 13, color: '#f5a623', fontFamily: "'JetBrains Mono',monospace", fontSize: 14 }}>⏻</div>
                <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff', marginBottom: 6 }}>Your team stays in control</div>
                <p style={{ fontSize: 13, lineHeight: 1.5, color: 'rgba(232,236,242,.58)', margin: 0 }}>
                  Nothing executes against your infrastructure until your team approves it. The approval step is
                  built in, not a toggle.
                </p>
              </div>
              <div style={{ border: '1px solid rgba(255,255,255,.1)', borderRadius: 13, background: 'rgba(255,255,255,.025)', padding: '18px 18px' }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, border: '1px solid rgba(63,209,122,.35)', background: 'rgba(63,209,122,.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 13, color: '#3fd17a', fontFamily: "'JetBrains Mono',monospace", fontSize: 14 }}>⊞</div>
                <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff', marginBottom: 6 }}>Works with your stack</div>
                <p style={{ fontSize: 13, lineHeight: 1.5, color: 'rgba(232,236,242,.58)', margin: 0 }}>
                  Azure, AWS, or both. Cloud Decoded plugs into the tooling you already run — no migration, no
                  cloud-first bias.
                </p>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <a href="/signup" style={{ textDecoration: 'none', fontSize: 15, fontWeight: 600, color: '#06101f', background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: '15px 30px', borderRadius: 11, boxShadow: '0 14px 34px -10px rgba(61,125,255,.75)' }}>
                Start free
              </a>
            </div>
            <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)', margin: '20px 0 0' }}>
              14-day money-back guarantee · connect read-only first · no card required to start
            </p>
          </div>
        </section>

        {/* ================= FAQ + FOOTER ================= */}
        <section
          id="faq"
          style={{
            position: 'relative', width: '100%', padding: '96px 40px 120px', boxSizing: 'border-box',
            background: '#070910', fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 880, margin: '0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 26 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.12em', color: 'rgba(159,194,255,.9)', border: '1px solid rgba(120,160,255,.32)', borderRadius: 5, padding: '4px 9px' }}>
                FAQ
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.06em', color: 'rgba(232,236,242,.4)' }}>
                the questions buyers ask before they visit
              </span>
              <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,.12),transparent)' }} />
            </div>
            <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 42, lineHeight: 1.08, letterSpacing: '-.025em', color: '#fff', margin: '0 0 48px', maxWidth: 640 }}>
              Straight answers, no hedging.
            </h2>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {FAQ_JSON_LD.mainEntity.map(qa => (
                <div key={qa.name} style={{ border: '1px solid rgba(255,255,255,.08)', borderRadius: 13, background: 'rgba(255,255,255,.018)', padding: '24px 26px' }}>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: 1.3, color: '#fff', margin: '0 0 11px' }}>
                    {qa.name}
                  </h3>
                  <p style={{ fontSize: 15, lineHeight: 1.65, color: 'rgba(232,236,242,.65)', margin: 0 }}>
                    {qa.acceptedAnswer.text}
                  </p>
                </div>
              ))}
            </div>

            <footer style={{ marginTop: 64, paddingTop: 30, borderTop: '1px solid rgba(255,255,255,.07)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
                <div style={{ position: 'relative', width: 24, height: 24, borderRadius: 7, background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 12px rgba(61,125,255,.5)' }}>
                  <div style={{ width: 12, height: 12, background: '#fff', clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)' }} />
                </div>
                <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 15, color: '#fff' }}>Cloud Decoded</span>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)' }}>by THD Agentic Systems LLC</span>
                <nav style={{ marginLeft: 'auto', display: 'flex', gap: 22, fontSize: 12.5, flexWrap: 'wrap' }}>
                  <a href="#problems" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>Problems</a>
                  <a href="#how-it-works" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>How it Works</a>
                  <a href="#monitor" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>What we Monitor</a>
                  <a href="#pricing" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>Pricing</a>
                  <a href="/blog" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>Blog</a>
                  <a href="#faq" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>FAQ</a>
                </nav>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, paddingTop: 14, borderTop: '1px solid rgba(255,255,255,.05)', flexWrap: 'wrap' }}>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)' }}>© 2026 · Built for the 2am page</span>
                <nav style={{ display: 'flex', gap: 16, fontFamily: "'JetBrains Mono',monospace", fontSize: 11 }}>
                  <a href="/status" style={{ color: 'rgba(232,236,242,.4)', textDecoration: 'none' }}>Status</a>
                  <a href="/terms" style={{ color: 'rgba(232,236,242,.4)', textDecoration: 'none' }}>Terms</a>
                  <a href="/privacy" style={{ color: 'rgba(232,236,242,.4)', textDecoration: 'none' }}>Privacy</a>
                </nav>
                <a href="mailto:hello@theclouddecoded.com?subject=Enterprise%20inquiry" style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.32)', textDecoration: 'none' }}>
                  Enterprise inquiry →
                </a>
              </div>
            </footer>
          </div>
        </section>
      </div>
    </>
  )
}
