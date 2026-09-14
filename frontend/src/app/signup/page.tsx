'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { createWorkspace, ApiError } from '@/lib/api'

// Real /signup route, recreating signup.dc.html's 2-column layout and its
// "Create account -> Add payment method -> Connect your stack" progress
// indicator (step 1 of 3) -- which now maps to the real flow exactly,
// since checkout is a required step, not optional.
//
// Collects company name + a contact email -- the two real fields
// POST /workspaces takes. Email exists so Cloud Decoded's own code has
// somewhere to send a welcome/confirmation email and an Enterprise MCP
// invite alert, and so an admin can identify a workspace without going to
// Stripe's dashboard. No first/last name or password -- there's no
// per-user account system to store them in, and the handoff's SSO buttons
// are skipped for the same reason as /login.
//
// The new workspace's token comes back locked (pending_payment) and
// useless until checkout completes, so it's carried to /checkout in
// sessionStorage rather than shown to the user here.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function SignupPage() {
  const router = useRouter()
  const [companyName, setCompanyName] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!companyName.trim()) {
      setError('Company name is required')
      return
    }
    if (!EMAIL_RE.test(contactEmail.trim())) {
      setError('A valid work email is required')
      return
    }
    if (!agreed) {
      setError('Please agree to the Terms of Service and Privacy Policy')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const result = await createWorkspace(companyName.trim(), contactEmail.trim(), agreed)
      sessionStorage.setItem('pending_workspace_token', result.workspace_token)
      router.push('/checkout')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create your account. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#070910' }}>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link
        href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap"
        rel="stylesheet"
      />
      <style>{`@keyframes cd-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}`}</style>

      {/* LEFT: brand panel */}
      <div
        style={{
          width: 400, flexShrink: 0, position: 'relative',
          background: 'linear-gradient(160deg,#0b1020,#070910)', overflow: 'hidden',
          display: 'flex', flexDirection: 'column', padding: '32px 40px',
        }}
      >
        <div
          style={{
            position: 'absolute', inset: 0,
            backgroundImage: 'linear-gradient(rgba(120,160,255,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(120,160,255,.04) 1px,transparent 1px)',
            backgroundSize: '48px 48px',
            WebkitMaskImage: 'radial-gradient(100% 100% at 80% 20%,#000,transparent 72%)',
            maskImage: 'radial-gradient(100% 100% at 80% 20%,#000,transparent 72%)',
            pointerEvents: 'none',
          }}
        />
        <div style={{ position: 'absolute', top: 40, right: -80, width: 380, height: 380, background: 'radial-gradient(circle,rgba(47,111,230,.22),transparent 65%)', pointerEvents: 'none' }} />
        <div style={{ position: 'absolute', bottom: 80, left: -80, width: 300, height: 300, background: 'radial-gradient(circle,rgba(63,209,122,.09),transparent 65%)', pointerEvents: 'none' }} />

        <a href="/" style={{ position: 'relative', zIndex: 2, display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
          <div style={{ width: 28, height: 28, borderRadius: 8, background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 14px rgba(61,125,255,.5)' }}>
            <div style={{ width: 14, height: 14, background: '#fff', clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)' }} />
          </div>
          <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff' }}>Cloud Decoded</span>
        </a>

        <div style={{ position: 'relative', zIndex: 2, flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: 'rgba(159,194,255,.75)', marginBottom: 18 }}>
            DETECT → PROPOSE → YOU APPROVE → EXECUTE
          </div>
          <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 30, lineHeight: 1.12, letterSpacing: '-.02em', color: '#fff', margin: '0 0 14px' }}>
            Start read-only.
            <br />
            Connect your stack.
            <br />
            Approve your first fix.
          </h2>
          <p style={{ fontSize: 14.5, lineHeight: 1.6, color: 'rgba(232,236,242,.55)', margin: '0 0 28px' }}>
            14 days free. No card charged until trial ends.
          </p>

          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 22, height: 22, borderRadius: '50%', background: 'rgba(90,150,255,.15)', border: '1px solid rgba(90,150,255,.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: '#9fc2ff', flexShrink: 0 }}>1</span>
              <span style={{ fontSize: 13, color: 'rgba(232,236,242,.75)', fontWeight: 500 }}>Create your account</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 22, height: 22, borderRadius: '50%', border: '1px dashed rgba(255,255,255,.18)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.3)', flexShrink: 0 }}>2</span>
              <span style={{ fontSize: 13, color: 'rgba(232,236,242,.35)' }}>Add payment method</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 22, height: 22, borderRadius: '50%', border: '1px dashed rgba(255,255,255,.18)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.3)', flexShrink: 0 }}>3</span>
              <span style={{ fontSize: 13, color: 'rgba(232,236,242,.35)' }}>Connect your stack</span>
            </div>
          </div>
        </div>

        <div style={{ position: 'relative', zIndex: 2 }}>
          <div style={{ display: 'flex', gap: 12, fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.3)', marginBottom: 8 }}>
            <span>SOC 2 ready</span><span>·</span><span>RBAC</span>
          </div>
          <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: 'rgba(232,236,242,.2)' }}>
            © 2026 THD Agentic Systems LLC
          </div>
        </div>
      </div>

      {/* RIGHT: form */}
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '48px 40px', background: '#070910', overflowY: 'auto' }}>
        <div style={{ width: '100%', maxWidth: 420 }}>
          <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 26, letterSpacing: '-.02em', color: '#fff', margin: '0 0 6px' }}>
            Create your account
          </h1>
          <p style={{ fontSize: 14, color: 'rgba(232,236,242,.5)', margin: '0 0 26px' }}>
            Start your 14-day free trial — no charge until it ends.
          </p>

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 6 }}>
                Company
              </label>
              <input
                type="text"
                value={companyName}
                onChange={e => { setCompanyName(e.target.value); setError('') }}
                placeholder="Acme Corp"
                autoComplete="organization"
                style={{
                  width: '100%', boxSizing: 'border-box', background: '#0c111c',
                  border: '1px solid rgba(255,255,255,.11)', borderRadius: 9, color: '#f0f3f8',
                  fontSize: 14, fontFamily: "'IBM Plex Sans',sans-serif", padding: '10px 13px', outline: 'none',
                }}
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 6 }}>
                Work email
              </label>
              <input
                type="email"
                value={contactEmail}
                onChange={e => { setContactEmail(e.target.value); setError('') }}
                placeholder="you@acmecorp.com"
                autoComplete="email"
                style={{
                  width: '100%', boxSizing: 'border-box', background: '#0c111c',
                  border: '1px solid rgba(255,255,255,.11)', borderRadius: 9, color: '#f0f3f8',
                  fontSize: 14, fontFamily: "'IBM Plex Sans',sans-serif", padding: '10px 13px', outline: 'none',
                }}
              />
            </div>

            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginTop: 18, marginBottom: 4, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={agreed}
                onChange={e => { setAgreed(e.target.checked); setError('') }}
                style={{ marginTop: 3 }}
              />
              <span style={{ fontSize: 11.5, lineHeight: 1.6, color: 'rgba(232,236,242,.5)' }}>
                I agree to the{' '}
                <a href="/terms" target="_blank" rel="noopener noreferrer" style={{ color: '#9fc2ff' }}>
                  Terms of Service
                </a>{' '}
                and{' '}
                <a href="/privacy" target="_blank" rel="noopener noreferrer" style={{ color: '#9fc2ff' }}>
                  Privacy Policy
                </a>.
              </span>
            </label>

            {error && <p style={{ marginTop: 10, fontSize: 12.5, color: '#ff8a7a' }}>{error}</p>}

            <button
              type="submit"
              disabled={submitting}
              style={{
                width: '100%', fontSize: 14, fontWeight: 600, color: '#06101f',
                background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 13, borderRadius: 10,
                border: 'none', boxShadow: '0 10px 28px -10px rgba(61,125,255,.65)', marginTop: 18,
                marginBottom: 16, cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1,
                fontFamily: "'IBM Plex Sans',sans-serif",
              }}
            >
              {submitting ? 'Creating account…' : 'Continue to payment →'}
            </button>
          </form>

          <p style={{ textAlign: 'center', fontSize: 13.5, color: 'rgba(232,236,242,.5)', margin: 0 }}>
            Already have an account?{' '}
            <a href="/login" style={{ color: '#9fc2ff', fontWeight: 500, textDecoration: 'none' }}>
              Sign in
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}
