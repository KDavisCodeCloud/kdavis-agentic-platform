'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { createCheckoutSession, ApiError } from '@/lib/api'

// Real /checkout route, recreating checkout.dc.html's top nav (step trail)
// and left-side plan-summary panel from the design handoff. The payment
// side is deliberately NOT the handoff's custom card-number/expiry/CVC
// form -- api/routes/stripe_billing.py's own architecture is Stripe-hosted
// Checkout exclusively (no custom payment UI, no card data ever touches
// our server), so this page is a thin tier selector that redirects the
// browser to Stripe's hosted checkout_url via the already-built
// createCheckoutSession(token, tier).

type Tier = 'starter' | 'growth'

const TIERS: Record<Tier, { label: string; price: string; desc: string; features: string[] }> = {
  starter: {
    label: 'STARTER',
    price: '$299',
    desc: 'For a single team putting its first workflows behind a human gate.',
    features: [
      '2 active workflows',
      'Core integrations — GitHub Actions, Azure DevOps, Kubernetes',
      'HITL approval console — full gate UI, audit log, diff view',
      'Up to 3 team members',
      'Community support',
    ],
  },
  growth: {
    label: 'GROWTH · MOST POPULAR',
    price: '$699',
    desc: 'For engineering orgs running all five workflows across multiple services.',
    features: [
      'All 5 workflows active',
      'All integrations — GitHub, Azure DevOps, AWS, PagerDuty, Slack',
      'HITL console + full audit log — 90-day history, exportable',
      'Up to 15 team members',
      'SSO (SAML/OIDC)',
    ],
  },
}

export default function CheckoutPage() {
  const router = useRouter()
  const [tier, setTier] = useState<Tier>('growth')
  const [token, setToken] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const stored = sessionStorage.getItem('pending_workspace_token')
    if (!stored) {
      router.replace('/signup')
      return
    }
    setToken(stored)
  }, [router])

  async function handleStartTrial() {
    if (!token) return
    setSubmitting(true)
    setError('')
    try {
      const checkoutUrl = await createCheckoutSession(token, tier)
      window.location.href = checkoutUrl
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start checkout. Try again.')
      setSubmitting(false)
    }
  }

  if (!token) return null

  const plan = TIERS[tier]

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: '#070910' }}>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link
        href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap"
        rel="stylesheet"
      />

      {/* top nav / step trail */}
      <div style={{ height: 56, borderBottom: '1px solid rgba(255,255,255,.06)', display: 'flex', alignItems: 'center', padding: '0 32px', background: '#070910', flexShrink: 0 }}>
        <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 9, textDecoration: 'none' }}>
          <div style={{ width: 24, height: 24, borderRadius: 6, background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ width: 12, height: 12, background: '#fff', clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)' }} />
          </div>
          <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 14, color: '#fff' }}>Cloud Decoded</span>
        </a>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontFamily: "'JetBrains Mono',monospace", fontSize: 11 }}>
          <span style={{ color: 'rgba(63,209,122,.8)' }}>Account ✓</span>
          <span style={{ color: 'rgba(255,255,255,.2)' }}>→</span>
          <span style={{ color: '#fff', fontWeight: 600 }}>Payment</span>
          <span style={{ color: 'rgba(255,255,255,.2)' }}>→</span>
          <span style={{ color: 'rgba(232,236,242,.3)' }}>Connect</span>
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', flexWrap: 'wrap' }}>
        {/* LEFT: plan summary */}
        <div style={{ width: 420, flexShrink: 0, background: 'linear-gradient(180deg,#090c18,#070910)', borderRight: '1px solid rgba(255,255,255,.07)', padding: '40px 36px', display: 'flex', flexDirection: 'column' }}>
          <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 18, color: '#fff', margin: '0 0 20px' }}>
            Choose your plan
          </h2>

          <div style={{ display: 'flex', background: '#0a0d16', border: '1px solid rgba(255,255,255,.08)', borderRadius: 10, padding: 4, marginBottom: 28, gap: 4 }}>
            {(['starter', 'growth'] as Tier[]).map(t => (
              <button
                key={t}
                onClick={() => setTier(t)}
                style={{
                  flex: 1, fontSize: 13, padding: '8px 12px', borderRadius: 7, border: 'none', cursor: 'pointer',
                  fontFamily: "'IBM Plex Sans',sans-serif", transition: 'all .15s',
                  background: tier === t ? 'linear-gradient(180deg,#5a96ff,#2f6fe6)' : 'transparent',
                  color: tier === t ? '#06101f' : 'rgba(232,236,242,.6)',
                  fontWeight: tier === t ? 600 : 400,
                }}
              >
                {t === 'starter' ? 'Starter · $299' : 'Growth · $699'}
              </button>
            ))}
          </div>

          <div style={{ border: '1px solid rgba(255,255,255,.1)', borderRadius: 14, background: 'rgba(255,255,255,.02)', padding: 22, marginBottom: 24, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 6 }}>
              <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 36, color: '#fff' }}>{plan.price}</span>
              <span style={{ fontSize: 14, color: 'rgba(232,236,242,.45)' }}>/mo</span>
              <span style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.08em', color: 'rgba(232,236,242,.45)' }}>{plan.label}</span>
            </div>
            <p style={{ fontSize: 13, lineHeight: 1.55, color: 'rgba(232,236,242,.5)', margin: '0 0 20px' }}>{plan.desc}</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {plan.features.map(f => (
                <div key={f} style={{ display: 'flex', alignItems: 'flex-start', gap: 9, fontSize: 13, color: 'rgba(232,236,242,.78)' }}>
                  <span style={{ color: '#5a96ff', flexShrink: 0, marginTop: 1 }}>▸</span>{f}
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontFamily: "'JetBrains Mono',monospace", fontSize: 10.5, color: 'rgba(232,236,242,.4)' }}>
            <span>🔒 Payment handled by Stripe — we never see your card</span>
            <span>✕ Cancel anytime before the trial ends</span>
            <span>☑ SOC 2-ready infrastructure</span>
          </div>
        </div>

        {/* RIGHT: start trial */}
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '48px 40px', minWidth: 320 }}>
          <div style={{ width: '100%', maxWidth: 420, textAlign: 'center' }}>
            <div
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 9, background: '#0c111c',
                border: '1px solid rgba(63,209,122,.4)', borderRadius: 99, padding: '9px 16px', marginBottom: 26,
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#3fd17a', boxShadow: '0 0 8px #3fd17a' }} />
              <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: '#3fd17a', fontWeight: 600 }}>
                14-day free trial starts today
              </span>
            </div>
            <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 24, color: '#fff', margin: '0 0 10px' }}>
              Ready when you are.
            </h1>
            <p style={{ fontSize: 14, lineHeight: 1.6, color: 'rgba(232,236,242,.55)', margin: '0 0 28px' }}>
              You&apos;ll enter payment details on Stripe&apos;s secure checkout page. Nothing is charged until your
              14-day trial ends, and you can cancel anytime before then.
            </p>

            {error && <p style={{ marginBottom: 14, fontSize: 12.5, color: '#ff8a7a' }}>{error}</p>}

            <button
              onClick={handleStartTrial}
              disabled={submitting}
              style={{
                width: '100%', fontSize: 15, fontWeight: 600, color: '#06101f',
                background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 15, borderRadius: 11,
                border: 'none', boxShadow: '0 12px 30px -10px rgba(61,125,255,.7)',
                cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1,
                fontFamily: "'IBM Plex Sans',sans-serif",
              }}
            >
              {submitting ? 'Redirecting to Stripe…' : `Start 14-day free trial — ${plan.price}/mo →`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
