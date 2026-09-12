import type { Metadata } from 'next'

// Real marketing landing page, recreated from the design handoff
// (~/projects/Cloud Decoded Hero Design.zip -> design_handoff_cloud_decoded/
// Cloud Decoded Landing.dc.html) -- replaces the bare workspace-token login
// field that was previously living at "/" and had ended up exposed as
// theclouddecoded.com's actual homepage.
//
// This page is pure static marketing content (no auth, no client state,
// no interactivity beyond plain <a> links to /login and /signup), so it's
// implemented as a Server Component. The body markup below is transcribed
// near-verbatim from the handoff's inline-styled HTML to preserve its
// pixel-level design decisions exactly, rather than hand-converted into
// individual React style objects -- with two substitutions: the handoff's
// <sc-for> findings placeholder is replaced with the 4 concrete finding
// rows the handoff's own companion data script specifies, and the
// <dc-import name="IncidentConsole"> background decoration (a real,
// authenticated dashboard component in this same app) is replaced with a
// simplified static approximation, since rendering the real component
// unauthenticated on a public page isn't appropriate -- it's 50% opacity
// and blurred in the design anyway, so the loss of fidelity there is
// minimal.

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Cloud Decoded — Human-Gated DevOps Automation for Mid-Market Engineering Teams',
  description:
    'Cloud Decoded detects incidents, triages root cause, and proposes fixes — then waits for a human to approve before anything touches your infrastructure. No vendor lock-in. Azure, AWS, or both.',
  alternates: { canonical: 'https://theclouddecoded.com' },
  openGraph: {
    type: 'website',
    url: 'https://theclouddecoded.com',
    title: 'Cloud Decoded — Human-Gated DevOps Automation for Mid-Market Engineering Teams',
    description:
      'Cloud Decoded detects incidents, triages root cause, and proposes fixes — then waits for a human to approve before anything touches your infrastructure. No vendor lock-in. Azure, AWS, or both.',
    images: ['/og-image.png'],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Cloud Decoded — Human-Gated DevOps Automation for Mid-Market Engineering Teams',
    description:
      'Cloud Decoded detects incidents, triages root cause, and proposes fixes — then waits for a human to approve before anything touches your infrastructure. No vendor lock-in. Azure, AWS, or both.',
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
        text: 'No. Cloud Decoded runs on top of the cloud providers you already use — Azure, AWS, or both — with no migration and no runtime dependency on any single vendor. It connects to your existing CI/CD, Kubernetes, and infrastructure tooling rather than replacing it.',
      },
    },
    {
      '@type': 'Question',
      name: 'Can the agents take action in my infrastructure without my approval?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: "No. No proposed fix executes against your infrastructure until a human approves it. Detection, triage, and proposal are automated, but the action itself sits at a hard approval gate that can't be silently disabled. You can approve, edit, or reject every fix.",
      },
    },
    {
      '@type': 'Question',
      name: 'What happens if an agent proposes the wrong fix?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'You reject it, and nothing happens to your infrastructure — because no fix executes before a human approves it. Every proposal shows the exact change and a diff before you decide, so a wrong suggestion is caught at review, not in production. Rejected proposals are logged alongside approved ones for a full audit trail.',
      },
    },
    {
      '@type': 'Question',
      name: 'How is this different from Microsoft Copilot or AWS AgentCore?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: "Cloud Decoded has no runtime dependency on a single cloud vendor and no cloud-first bias — it works across Azure and AWS instead of locking you into one provider's ecosystem. Every action passes through a human approval gate by design, rather than acting autonomously. It's built specifically for mid-market engineering teams who want agentic ops without vendor lock-in.",
      },
    },
    {
      '@type': 'Question',
      name: 'What does a typical onboarding look like?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'Onboarding starts read-only: you connect Cloud Decoded to your existing CI/CD, Kubernetes, and infrastructure tools, and it begins triaging incidents and proposing fixes without permission to execute. Once you trust the proposals, you enable the approval gate so fixes can be applied with one click. Most teams are reviewing real proposed fixes within the first day.',
      },
    },
    {
      '@type': 'Question',
      name: 'Is it safe to connect Cloud Decoded to production infrastructure?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: "Yes. Cloud Decoded connects read-only by default and can't execute any change to production until a human approves it. Every proposed and approved action is recorded in a full audit trail, and access is scoped with SSO and role-based controls. You decide what it can touch, and nothing happens at 2am without a person in the loop.",
      },
    },
  ],
}

const FINDING_ROWS = [
  {
    id: 'FINDING 01',
    severity: 'SEV · HIGH',
    sevColor: '#f5a623',
    sevBorder: 'rgba(245,166,35,.4)',
    sevBg: 'rgba(245,166,35,.08)',
    noteColor: 'rgba(245,166,35,.85)',
    title: '2am pages for issues that never needed a human.',
    detail:
      "A transient pod restart self-heals before anyone reads the alert — but someone still got woken to confirm it. The signal that matters drowns in the noise that doesn't.",
    note: 'human paged · no human action required',
  },
  {
    id: 'FINDING 02',
    severity: 'SEV · HIGH',
    sevColor: '#f5a623',
    sevBorder: 'rgba(245,166,35,.4)',
    sevBg: 'rgba(245,166,35,.08)',
    noteColor: 'rgba(245,166,35,.85)',
    title: 'Alert fatigue is eroding trust in the monitoring itself.',
    detail:
      'When most pages are noise, on-call engineers start muting, snoozing, and second-guessing the dashboard. The one real incident lands in a channel nobody believes anymore.',
    note: 'monitoring credibility · declining',
  },
  {
    id: 'FINDING 03',
    severity: 'SEV · MED',
    sevColor: '#9fc2ff',
    sevBorder: 'rgba(120,160,255,.35)',
    sevBg: 'rgba(47,111,230,.08)',
    noteColor: 'rgba(159,194,255,.85)',
    title: 'Root-cause triage eats senior engineering time.',
    detail:
      'Your most expensive engineers spend their nights paging through logs to reconstruct what already happened, instead of building what comes next.',
    note: 'senior hours · spent on archaeology',
  },
  {
    id: 'FINDING 04',
    severity: 'SEV · MED',
    sevColor: '#9fc2ff',
    sevBorder: 'rgba(120,160,255,.35)',
    sevBg: 'rgba(47,111,230,.08)',
    noteColor: 'rgba(159,194,255,.85)',
    title: "Vendor lock-in forces every workflow through one cloud's tooling.",
    detail:
      "Ops capability gets bolted to a single provider's runtime and billing, whether or not it fits the stack you actually run.",
    note: 'tooling choice · not yours',
  },
]

function FindingRow({ f }: { f: (typeof FINDING_ROWS)[number] }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '150px 1fr 200px',
        gap: 28,
        alignItems: 'start',
        padding: '26px 22px',
        borderBottom: '1px solid rgba(255,255,255,.05)',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, color: 'rgba(232,236,242,.5)' }}>
          {f.id}
        </span>
        <span
          style={{
            alignSelf: 'flex-start',
            fontFamily: "'JetBrains Mono',monospace",
            fontSize: 9.5,
            fontWeight: 700,
            letterSpacing: '.08em',
            color: f.sevColor,
            border: `1px solid ${f.sevBorder}`,
            background: f.sevBg,
            borderRadius: 5,
            padding: '3px 8px',
          }}
        >
          {f.severity}
        </span>
      </div>
      <div>
        <div
          style={{
            fontFamily: "'Space Grotesk',sans-serif",
            fontWeight: 500,
            fontSize: 21,
            lineHeight: 1.3,
            letterSpacing: '-.01em',
            color: '#f0f3f8',
            marginBottom: 9,
          }}
        >
          {f.title}
        </div>
        <p style={{ fontSize: 14, lineHeight: 1.6, color: 'rgba(232,236,242,.55)', margin: 0, maxWidth: 520 }}>
          {f.detail}
        </p>
      </div>
      <div style={{ borderLeft: `2px solid ${f.sevColor}`, paddingLeft: 14 }}>
        <div
          style={{
            fontFamily: "'JetBrains Mono',monospace",
            fontSize: 9,
            letterSpacing: '.08em',
            color: 'rgba(232,236,242,.35)',
            marginBottom: 5,
          }}
        >
          REDLINE
        </div>
        <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11.5, lineHeight: 1.5, color: f.noteColor }}>
          {f.note}
        </div>
      </div>
    </div>
  )
}

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
            height: 780,
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
              <a href="#how-it-works" style={{ color: 'rgba(232,236,242,.62)', textDecoration: 'none' }}>
                Product
              </a>
              <a href="#workflows" style={{ color: 'rgba(232,236,242,.62)', textDecoration: 'none' }}>
                Workflows
              </a>
              <a href="#pricing" style={{ color: 'rgba(232,236,242,.62)', textDecoration: 'none' }}>
                Pricing
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
                Start free trial
              </a>
            </div>
          </nav>

          <div style={{ position: 'absolute', zIndex: 4, left: 40, top: 200, width: 500 }}>
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
              DETECT → PROPOSE → YOU APPROVE → EXECUTE
            </div>
            <h1
              style={{
                fontFamily: "'Space Grotesk',sans-serif",
                fontWeight: 600,
                fontSize: 58,
                lineHeight: 1.02,
                letterSpacing: '-.025em',
                color: '#fff',
                margin: '0 0 22px',
              }}
            >
              Your 2am incident,
              <br />
              <span style={{ color: '#5a96ff' }}>already triaged.</span>
            </h1>
            <p
              style={{
                fontSize: 17,
                lineHeight: 1.6,
                color: 'rgba(232,236,242,.66)',
                margin: '0 0 30px',
                maxWidth: 400,
              }}
            >
              Your infra. <span style={{ color: '#f0f3f8' }}>Your call.</span> Less guessing.
            </p>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <a
                href="/signup"
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
                Start free trial
              </a>
              <a
                href="#demo"
                style={{
                  textDecoration: 'none',
                  fontSize: 14,
                  fontWeight: 500,
                  color: '#e8ecf2',
                  border: '1px solid rgba(255,255,255,.16)',
                  padding: '13px 22px',
                  borderRadius: 10,
                }}
              >
                See it run
              </a>
            </div>
            <p
              style={{
                fontFamily: "'JetBrains Mono',monospace",
                fontSize: 11,
                color: 'rgba(232,236,242,.42)',
                margin: '14px 0 0',
              }}
            >
              14-day free trial · connect read-only first · cancel before it bills
            </p>
          </div>

          {/* Dimmed background decoration -- static approximation of the app's
              real IncidentConsole, not the live authenticated component */}
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
                Incident Console
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
                K8s Alerts
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
                PROPOSED FIX · AWAITING HUMAN GATE
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
              5 workflows
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
              CI/CD · K8S · DRIFT · LOGS · FINOPS
            </div>
          </div>
        </header>

        {/* ================= PROBLEM ================= */}
        <section
          id="problem"
          style={{
            position: 'relative',
            width: '100%',
            padding: '96px 40px 104px',
            boxSizing: 'border-box',
            background: '#070910',
            fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 1100, margin: '0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 26 }}>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 11,
                  letterSpacing: '.12em',
                  color: 'rgba(245,166,35,.9)',
                  border: '1px solid rgba(245,166,35,.32)',
                  borderRadius: 5,
                  padding: '4px 9px',
                }}
              >
                DIAGNOSIS
              </span>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 11,
                  letterSpacing: '.06em',
                  color: 'rgba(232,236,242,.4)',
                }}
              >
                on-call ops · industry audit · 2026
              </span>
              <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,.12),transparent)' }} />
            </div>

            <h2
              style={{
                fontFamily: "'Space Grotesk',sans-serif",
                fontWeight: 600,
                fontSize: 42,
                lineHeight: 1.08,
                letterSpacing: '-.025em',
                color: '#fff',
                margin: '0 0 18px',
                maxWidth: 780,
              }}
            >
              Alert fatigue and on-call burnout are an industry-wide failure — not a personal one.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 0 56px', maxWidth: 680 }}>
              Most 2am pages never needed a human. The few that do are buried under the ones that don&apos;t — and
              that backlog is what erodes on-call morale, drains senior engineering time, and quietly trains teams to
              ignore their own monitoring.
            </p>

            <div
              style={{
                border: '1px solid rgba(255,255,255,.08)',
                borderRadius: 14,
                overflow: 'hidden',
                background: 'linear-gradient(180deg,rgba(255,255,255,.018),rgba(255,255,255,0))',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 14,
                  padding: '13px 22px',
                  borderBottom: '1px solid rgba(255,255,255,.07)',
                  background: 'rgba(255,255,255,.02)',
                }}
              >
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, fontWeight: 700, letterSpacing: '.08em', color: '#fff' }}>
                  FINDINGS
                </span>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)' }}>
                  4 open · 0 mitigated
                </span>
                <span
                  style={{
                    marginLeft: 'auto',
                    fontFamily: "'JetBrains Mono',monospace",
                    fontSize: 10,
                    letterSpacing: '.1em',
                    color: 'rgba(245,166,35,.7)',
                  }}
                >
                  ● UNRESOLVED
                </span>
              </div>

              {FINDING_ROWS.map(f => (
                <FindingRow key={f.id} f={f} />
              ))}

              <div
                style={{
                  padding: '18px 22px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  background: 'rgba(255,255,255,.015)',
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f5a623', boxShadow: '0 0 8px #f5a623' }} />
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 12, color: 'rgba(232,236,242,.55)' }}>
                  Net effect: humans paged for work humans shouldn&apos;t be doing.
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* ================= HOW IT WORKS ================= */}
        <section
          id="how-it-works"
          style={{
            position: 'relative',
            width: '100%',
            padding: '96px 40px 110px',
            boxSizing: 'border-box',
            background: 'linear-gradient(180deg,#070910,#090c16 50%,#070910)',
            fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 1140, margin: '0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 26 }}>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  fontSize: 11,
                  letterSpacing: '.12em',
                  color: 'rgba(159,194,255,.9)',
                  border: '1px solid rgba(120,160,255,.32)',
                  borderRadius: 5,
                  padding: '4px 9px',
                }}
              >
                HOW IT WORKS
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.06em', color: 'rgba(232,236,242,.4)' }}>
                detect → propose → you approve → execute
              </span>
              <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,.12),transparent)' }} />
            </div>

            <h2
              style={{
                fontFamily: "'Space Grotesk',sans-serif",
                fontWeight: 600,
                fontSize: 42,
                lineHeight: 1.08,
                letterSpacing: '-.025em',
                color: '#fff',
                margin: '0 0 18px',
                maxWidth: 760,
              }}
            >
              Four steps. One of them is you.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 0 60px', maxWidth: 700 }}>
              Cloud Decoded detects the incident, finds the root cause, and proposes a fix — then stops. Nothing
              touches your infrastructure until a human approves it. The approval gate is a hard step in the flow,
              not a setting you can quietly switch off.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1.12fr 1fr', gap: 0, alignItems: 'stretch' }}>
              {/* STEP 01 DETECT */}
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
                <div style={{ border: '1px solid rgba(255,255,255,.08)', borderRadius: 13, background: 'rgba(255,255,255,.02)', padding: '20px 18px', height: 228, boxSizing: 'border-box' }}>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: 'rgba(159,194,255,.85)', marginBottom: 12 }}>
                    STEP 01 · DETECT
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: 1.2, color: '#fff', margin: '0 0 10px' }}>
                    Catches it the moment it fires.
                  </h3>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.6)', margin: '0 0 16px' }}>
                    Pipeline failure, K8s event, IaC drift, cost spike — picked up from the tools you already run.
                  </p>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: "'JetBrains Mono',monospace", fontSize: 10.5, color: 'rgba(232,236,242,.7)', border: '1px solid rgba(255,255,255,.1)', borderRadius: 6, padding: '5px 9px' }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#f5a623', boxShadow: '0 0 7px #f5a623' }} />
                    signal received
                  </div>
                </div>
              </div>

              {/* STEP 02 PROPOSE */}
              <div style={{ position: 'relative', padding: '0 18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 18 }}>
                  <span
                    style={{
                      width: 34, height: 34, borderRadius: 9, border: '1px solid rgba(120,160,255,.35)',
                      background: 'rgba(47,111,230,.1)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 15, color: '#9fc2ff',
                    }}
                  >
                    2
                  </span>
                  <div style={{ flex: 1, height: 1, background: 'rgba(120,160,255,.5)' }} />
                  <span style={{ color: 'rgba(245,166,35,.8)', fontSize: 16, marginRight: -4 }}>→</span>
                </div>
                <div style={{ border: '1px solid rgba(255,255,255,.08)', borderRadius: 13, background: 'rgba(255,255,255,.02)', padding: '20px 18px', height: 228, boxSizing: 'border-box' }}>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: 'rgba(159,194,255,.85)', marginBottom: 12 }}>
                    STEP 02 · PROPOSE
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: 1.2, color: '#fff', margin: '0 0 10px' }}>
                    Finds root cause, writes the fix.
                  </h3>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.6)', margin: '0 0 16px' }}>
                    Not the alert restated — a concrete, reviewable change: the rollback, the command, the config diff.
                  </p>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10.5, color: 'rgba(159,194,255,.85)', background: '#0a0d16', border: '1px solid rgba(255,255,255,.08)', borderRadius: 6, padding: '7px 9px' }}>
                    rollback → v2.4.1 · limit 768Mi
                  </div>
                </div>
              </div>

              {/* STEP 03 YOU APPROVE — THE GATE */}
              <div style={{ position: 'relative', padding: '0 18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 18 }}>
                  <span
                    style={{
                      width: 34, height: 34, borderRadius: 9, border: '2px solid #f5a623',
                      background: 'rgba(245,166,35,.16)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: "'Space Grotesk',sans-serif", fontWeight: 700, fontSize: 15, color: '#f5a623',
                      boxShadow: '0 0 18px -2px rgba(245,166,35,.6)',
                    }}
                  >
                    3
                  </span>
                  <div style={{ flex: 1, height: 2, background: 'repeating-linear-gradient(90deg,rgba(245,166,35,.7) 0 6px,transparent 6px 12px)' }} />
                  <span style={{ color: 'rgba(245,166,35,.9)', fontSize: 16, marginRight: -4 }}>→</span>
                </div>
                <div
                  style={{
                    position: 'relative', border: '1.5px solid rgba(245,166,35,.55)', borderRadius: 13,
                    background: 'linear-gradient(180deg,rgba(245,166,35,.09),rgba(20,16,8,.4))', padding: '20px 18px',
                    height: 228, boxSizing: 'border-box',
                    boxShadow: '0 0 0 1px rgba(245,166,35,.12),0 24px 60px -24px rgba(245,166,35,.4)',
                    transform: 'translateY(-10px)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: '#f5a623', fontWeight: 700 }}>
                      STEP 03 · YOU APPROVE
                    </span>
                    <span style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 8.5, letterSpacing: '.1em', color: '#06101f', background: '#f5a623', borderRadius: 4, padding: '2px 6px', fontWeight: 700 }}>
                      HUMAN GATE
                    </span>
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: 1.2, color: '#fff', margin: '0 0 10px' }}>
                    Nothing runs until you click.
                  </h3>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.72)', margin: '0 0 16px' }}>
                    The fix waits at the gate. Approve it, edit it, or reject it — no action reaches production
                    without a human.
                  </p>
                  <div style={{ display: 'flex', gap: 7 }}>
                    <span style={{ fontSize: 11.5, fontWeight: 600, color: '#06101f', background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: '7px 12px', borderRadius: 7 }}>
                      Approve &amp; Execute
                    </span>
                    <span style={{ fontSize: 11.5, fontWeight: 500, color: 'rgba(232,236,242,.8)', border: '1px solid rgba(255,255,255,.18)', padding: '7px 11px', borderRadius: 7 }}>
                      Reject
                    </span>
                  </div>
                </div>
              </div>

              {/* STEP 04 EXECUTE */}
              <div style={{ position: 'relative', padding: '0 18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 18 }}>
                  <span
                    style={{
                      width: 34, height: 34, borderRadius: 9, border: '1px solid rgba(63,209,122,.4)',
                      background: 'rgba(63,209,122,.1)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 15, color: '#3fd17a',
                    }}
                  >
                    4
                  </span>
                  <div style={{ flex: 1, height: 1, background: 'rgba(63,209,122,.4)' }} />
                </div>
                <div style={{ border: '1px solid rgba(255,255,255,.08)', borderRadius: 13, background: 'rgba(255,255,255,.02)', padding: '20px 18px', height: 228, boxSizing: 'border-box' }}>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: 'rgba(63,209,122,.85)', marginBottom: 12 }}>
                    STEP 04 · EXECUTE
                  </div>
                  <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 20, lineHeight: 1.2, color: '#fff', margin: '0 0 10px' }}>
                    Applies it, logs everything.
                  </h3>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.6)', margin: '0 0 16px' }}>
                    Runs exactly what you approved, then writes a full audit trail — who approved what, and when.
                  </p>
                  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: "'JetBrains Mono',monospace", fontSize: 10.5, color: 'rgba(63,209,122,.9)', border: '1px solid rgba(63,209,122,.25)', background: 'rgba(63,209,122,.06)', borderRadius: 6, padding: '5px 9px' }}>
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#3fd17a', boxShadow: '0 0 7px #3fd17a' }} />
                    resolved · human-approved
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ================= FIVE WORKFLOWS ================= */}
        <section
          id="workflows"
          style={{
            position: 'relative', width: '100%', padding: '96px 40px 110px', boxSizing: 'border-box',
            background: '#070910', fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        >
          <div style={{ position: 'relative', zIndex: 2, maxWidth: 1140, margin: '0 auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 26 }}>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.12em', color: 'rgba(159,194,255,.9)', border: '1px solid rgba(120,160,255,.32)', borderRadius: 5, padding: '4px 9px' }}>
                WORKFLOWS
              </span>
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.06em', color: 'rgba(232,236,242,.4)' }}>
                5 shipping · more in private beta
              </span>
              <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,.12),transparent)' }} />
            </div>

            <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 42, lineHeight: 1.08, letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px', maxWidth: 780 }}>
              Five workflows for the incidents that page you most.
            </h2>
            <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: '0 0 56px', maxWidth: 720 }}>
              Cloud Decoded ships with five production workflows: CI/CD failure triage, Kubernetes alert response,
              IaC drift detection, log summarization, and FinOps cost monitoring. Each one detects, triages, and
              proposes — and waits for your approval before it acts.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 18 }}>
              <article style={{ gridColumn: 'span 2', border: '1px solid rgba(255,255,255,.08)', borderRadius: 14, background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))', padding: 20, display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.45)' }}>WF·01</span>
                  <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: "'JetBrains Mono',monospace", fontSize: 9, letterSpacing: '.06em', color: '#f5a623', border: '1px solid rgba(245,166,35,.35)', background: 'rgba(245,166,35,.08)', borderRadius: 5, padding: '3px 7px' }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#f5a623' }} />ACTION REQ
                  </span>
                </div>
                <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 18, lineHeight: 1.22, color: '#fff', margin: '0 0 9px' }}>
                  CI/CD Pipeline Failure Triage
                </h3>
                <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.58)', margin: '0 0 16px' }}>
                  Detects failed pipeline runs, surfaces the root-cause step, and proposes the exact config fix
                  before you&apos;ve finished reading the alert.
                </p>
                <div style={{ marginTop: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 11, lineHeight: 1.7, background: '#080b13', border: '1px solid rgba(255,255,255,.07)', borderRadius: 9, padding: '11px 12px' }}>
                  <div style={{ color: '#ff8a7a' }}>✗ build · step 14/22 failed</div>
                  <div style={{ color: 'rgba(232,236,242,.6)' }}>ERESOLVE webpack@4 ⨯ webpack@5</div>
                  <div style={{ color: '#9fc2ff', marginTop: 4 }}>→ pin webpack@5.91.0 · lockfile</div>
                </div>
              </article>

              <article style={{ gridColumn: 'span 2', border: '1px solid rgba(255,255,255,.08)', borderRadius: 14, background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))', padding: 20, display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.45)' }}>WF·02</span>
                  <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: "'JetBrains Mono',monospace", fontSize: 9, letterSpacing: '.06em', color: '#f5a623', border: '1px solid rgba(245,166,35,.35)', background: 'rgba(245,166,35,.08)', borderRadius: 5, padding: '3px 7px' }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#f5a623' }} />ACTION REQ
                  </span>
                </div>
                <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 18, lineHeight: 1.22, color: '#fff', margin: '0 0 9px' }}>
                  Kubernetes Alert Response
                </h3>
                <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.58)', margin: '0 0 16px' }}>
                  Cuts through alert noise to decide whether a K8s event needs action, a watch, or a dismiss — then
                  drafts the remediation command for your approval.
                </p>
                <div style={{ marginTop: 'auto' }}>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 9 }}>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9.5, color: '#06101f', background: '#f5a623', borderRadius: 5, padding: '4px 8px', fontWeight: 700 }}>ACT</span>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9.5, color: 'rgba(232,236,242,.5)', border: '1px solid rgba(255,255,255,.12)', borderRadius: 5, padding: '4px 8px' }}>WATCH</span>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 9.5, color: 'rgba(232,236,242,.5)', border: '1px solid rgba(255,255,255,.12)', borderRadius: 5, padding: '4px 8px' }}>DISMISS</span>
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: '#9fc2ff', background: '#080b13', border: '1px solid rgba(255,255,255,.07)', borderRadius: 9, padding: '10px 12px' }}>
                    kubectl rollout undo deploy/checkout-api
                  </div>
                </div>
              </article>

              <article style={{ gridColumn: 'span 2', border: '1px solid rgba(255,255,255,.08)', borderRadius: 14, background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))', padding: 20, display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.45)' }}>WF·03</span>
                  <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: "'JetBrains Mono',monospace", fontSize: 9, letterSpacing: '.06em', color: '#f5a623', border: '1px solid rgba(245,166,35,.35)', background: 'rgba(245,166,35,.08)', borderRadius: 5, padding: '3px 7px' }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#f5a623' }} />ACTION REQ
                  </span>
                </div>
                <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 18, lineHeight: 1.22, color: '#fff', margin: '0 0 9px' }}>
                  IaC Drift Detection
                </h3>
                <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.58)', margin: '0 0 16px' }}>
                  Compares deployed infrastructure against your Terraform / Bicep source of truth and flags every
                  untracked change before it becomes an incident.
                </p>
                <div style={{ marginTop: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 11, lineHeight: 1.7, background: '#080b13', border: '1px solid rgba(255,255,255,.07)', borderRadius: 9, padding: '11px 12px' }}>
                  <div style={{ color: 'rgba(232,236,242,.6)' }}>~ aws_security_group.api</div>
                  <div style={{ color: '#ff8a7a' }}>+ ingress tcp:5432 0.0.0.0/0</div>
                  <div style={{ color: '#f5a623', marginTop: 4 }}>drift · 3 untracked resources</div>
                </div>
              </article>

              <article style={{ gridColumn: 'span 3', border: '1px solid rgba(255,255,255,.08)', borderRadius: 14, background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))', padding: 22, display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.45)' }}>WF·04</span>
                  <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: "'JetBrains Mono',monospace", fontSize: 9, letterSpacing: '.06em', color: '#3fd17a', border: '1px solid rgba(63,209,122,.3)', background: 'rgba(63,209,122,.07)', borderRadius: 5, padding: '3px 7px' }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#3fd17a' }} />SUMMARY READY
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 22, alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 18, lineHeight: 1.22, color: '#fff', margin: '0 0 9px' }}>
                      Log Summarizer
                    </h3>
                    <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.58)', margin: 0 }}>
                      Parses multi-service log output during an incident and returns a ranked, human-readable
                      summary of what actually happened — and in what order.
                    </p>
                  </div>
                  <div style={{ flex: 1, fontFamily: "'JetBrains Mono',monospace", fontSize: 11, lineHeight: 1.6, background: '#080b13', border: '1px solid rgba(255,255,255,.07)', borderRadius: 9, padding: '12px 13px' }}>
                    <div style={{ color: 'rgba(232,236,242,.4)', fontSize: 9, letterSpacing: '.08em', marginBottom: 7 }}>RANKED · ROOT → SYMPTOM</div>
                    <div style={{ color: 'rgba(232,236,242,.75)' }}><span style={{ color: '#3fd17a' }}>1</span> 01:52 payment-svc OOMKilled</div>
                    <div style={{ color: 'rgba(232,236,242,.75)' }}><span style={{ color: '#9fc2ff' }}>2</span> 01:52 checkout 503 ×214</div>
                    <div style={{ color: 'rgba(232,236,242,.75)' }}><span style={{ color: '#9fc2ff' }}>3</span> 01:53 retry pool saturated</div>
                  </div>
                </div>
              </article>

              <article style={{ gridColumn: 'span 3', border: '1px solid rgba(255,255,255,.08)', borderRadius: 14, background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))', padding: 22, display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                  <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.45)' }}>WF·05</span>
                  <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: "'JetBrains Mono',monospace", fontSize: 9, letterSpacing: '.06em', color: '#3fd17a', border: '1px solid rgba(63,209,122,.3)', background: 'rgba(63,209,122,.07)', borderRadius: 5, padding: '3px 7px' }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#3fd17a' }} />4 RECOMMENDATIONS
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 22, alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <h3 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 18, lineHeight: 1.22, color: '#fff', margin: '0 0 9px' }}>
                      FinOps Cost Monitor
                    </h3>
                    <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.58)', margin: 0 }}>
                      Identifies cloud spend anomalies and idle resources, then produces a prioritized savings
                      recommendation — not just a raw cost report.
                    </p>
                  </div>
                  <div style={{ flex: 1, fontFamily: "'JetBrains Mono',monospace", fontSize: 11, lineHeight: 1.6, background: '#080b13', border: '1px solid rgba(255,255,255,.07)', borderRadius: 9, padding: '12px 13px' }}>
                    <div style={{ color: '#f5a623' }}>▲ nat-gateway +$1,240/mo</div>
                    <div style={{ color: 'rgba(232,236,242,.6)' }}>idle · 6 volumes, 2 RDS</div>
                    <div style={{ color: '#3fd17a', marginTop: 5, fontWeight: 700 }}>→ save ~$3,180/mo</div>
                  </div>
                </div>
              </article>
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
              See all five workflows handle a live incident — from detection to human approval — in under four minutes.
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
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#9fc2ff' }}>PROPOSE</span>
                    <span style={{ flex: 1, height: 1, background: 'rgba(120,160,255,.4)', margin: '0 10px' }} />
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#f5a623' }}>YOU APPROVE</span>
                    <span style={{ flex: 1, height: 1, background: 'repeating-linear-gradient(90deg,rgba(245,166,35,.6) 0 5px,transparent 5px 10px)', margin: '0 10px' }} />
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#3fd17a' }}>EXECUTE</span>
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
                Start free trial
              </a>
              <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.42)', margin: 0 }}>
                14-day free trial · connect read-only first · cancel before it bills
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
                  For a single team putting its first workflows behind a human gate.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginBottom: 26 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>2 active workflows — pick any two from CI/CD, K8s, Drift, Logs, FinOps</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Core integrations — GitHub Actions, Azure DevOps, Kubernetes</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>HITL approval console — full gate UI, audit log, diff view</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Up to 3 team members</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Community support</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.38)' }}><span style={{ color: 'rgba(255,255,255,.28)' }}>✕</span>No SSO</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.38)' }}><span style={{ color: 'rgba(255,255,255,.28)' }}>✕</span>No RBAC</div>
                </div>
                <a href="/signup" style={{ marginTop: 'auto', textAlign: 'center', display: 'block', textDecoration: 'none', fontSize: 14, fontWeight: 500, color: '#e8ecf2', border: '1px solid rgba(255,255,255,.18)', padding: 12, borderRadius: 10 }}>
                  Start free trial
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
                  For engineering orgs running all five workflows across multiple services.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginBottom: 26 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>All 5 workflows active — CI/CD, K8s, Drift, Logs, FinOps</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>All integrations — GitHub, Azure DevOps, AWS, PagerDuty, Slack</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>HITL console + full audit log — 90-day history, exportable</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>Up to 15 team members</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>SSO (SAML/OIDC)</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.85)' }}><span style={{ color: '#5a96ff' }}>▸</span>Priority email support — 1 business day response</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.4)' }}><span style={{ color: 'rgba(255,255,255,.28)' }}>✕</span>No custom SLA</div>
                </div>
                <a href="/signup" style={{ marginTop: 'auto', textAlign: 'center', display: 'block', textDecoration: 'none', fontSize: 14, fontWeight: 600, color: '#06101f', background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 12, borderRadius: 10, boxShadow: '0 12px 30px -10px rgba(61,125,255,.7)' }}>
                  Start free trial
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
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Unlimited workflows — all 5 now, private beta workflows as they ship</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Custom integrations — bespoke connectors for your stack</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Full audit log + RBAC — 1-year history, role-scoped approvals, exportable for compliance</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>Unlimited team members</div>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: 'rgba(232,236,242,.78)' }}><span style={{ color: '#5a96ff' }}>▸</span>SSO + SCIM provisioning</div>
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
              Agentic ops capability for mid-market engineering teams — without handing your infrastructure, your
              runtime, or your judgment to a single vendor.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 16, marginBottom: 44, textAlign: 'left' }}>
              <div style={{ border: '1px solid rgba(255,255,255,.1)', borderRadius: 13, background: 'rgba(255,255,255,.025)', padding: '18px 18px' }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, border: '1px solid rgba(120,160,255,.35)', background: 'rgba(47,111,230,.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 13, color: '#9fc2ff', fontFamily: "'JetBrains Mono',monospace", fontSize: 14 }}>⌁</div>
                <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff', marginBottom: 6 }}>No runtime lock-in</div>
                <p style={{ fontSize: 13, lineHeight: 1.5, color: 'rgba(232,236,242,.58)', margin: 0 }}>
                  No dependency on a single cloud vendor&apos;s runtime or billing. Your ops capability isn&apos;t
                  bolted to anyone&apos;s platform.
                </p>
              </div>
              <div style={{ border: '1px solid rgba(245,166,35,.3)', borderRadius: 13, background: 'rgba(245,166,35,.05)', padding: '18px 18px' }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, border: '1px solid rgba(245,166,35,.45)', background: 'rgba(245,166,35,.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 13, color: '#f5a623', fontFamily: "'JetBrains Mono',monospace", fontSize: 14 }}>⏻</div>
                <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff', marginBottom: 6 }}>No action without you</div>
                <p style={{ fontSize: 13, lineHeight: 1.5, color: 'rgba(232,236,242,.58)', margin: 0 }}>
                  Nothing executes against your infrastructure until a human approves it. The gate is built in, not
                  a toggle.
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
                Start free trial
              </a>
            </div>
            <p style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)', margin: '20px 0 0' }}>
              14-day free trial · connect read-only first · cancel before it bills
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
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18 }}>
                <div style={{ position: 'relative', width: 24, height: 24, borderRadius: 7, background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 12px rgba(61,125,255,.5)' }}>
                  <div style={{ width: 12, height: 12, background: '#fff', clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)' }} />
                </div>
                <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 15, color: '#fff' }}>Cloud Decoded</span>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)' }}>by THD Agentic Systems LLC</span>
                <nav style={{ marginLeft: 'auto', display: 'flex', gap: 22, fontSize: 12.5 }}>
                  <a href="#problem" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>Problem</a>
                  <a href="#how-it-works" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>How it Works</a>
                  <a href="#workflows" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>Workflows</a>
                  <a href="#pricing" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>Pricing</a>
                  <a href="#faq" style={{ color: 'rgba(232,236,242,.6)', textDecoration: 'none' }}>FAQ</a>
                </nav>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, paddingTop: 14, borderTop: '1px solid rgba(255,255,255,.05)' }}>
                <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)' }}>© 2026 · Built for the 2am page</span>
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
