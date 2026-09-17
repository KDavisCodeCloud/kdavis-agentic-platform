'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getSupabaseClient, isSupabaseConfigured } from '@/lib/supabase'

// Real dedicated /login route, recreating login.dc.html's 2-column brand/
// form layout from the design handoff.
//
// Membership plan, Phase A: primary sign-in is now real Supabase email +
// password (getSupabaseClient().auth.signInWithPassword) -- a genuine
// per-human identity, not a shared secret pasted into localStorage. The
// raw workspace-token flow is kept as a secondary "Use a workspace token
// instead" fallback rather than removed outright: workspace_members is a
// brand-new table with zero rows for every existing paying customer, so
// until each one is invited and accepts (POST /workspace-members/invite,
// /accept-invite), the token is still the ONLY credential that works for
// them. Removing it here would be a self-inflicted login outage for every
// current customer, not a migration.
//
// The handoff's SSO buttons (Google Workspace, Azure AD/Okta) are still
// deliberately NOT recreated here -- that's Phase D, not this one.

const MOCK_MODE = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'

// 24-gap-closure Phase 4 -- MFA challenge step, added between password
// sign-in and reaching the dashboard. 'mfa_challenge' only ever appears
// for a member who has already enrolled a verified TOTP factor (Supabase
// itself decides this via getAuthenticatorAssuranceLevel's nextLevel) --
// nothing here forces enrollment; that happens separately in the
// dashboard's Members & Security panel.
type Mode = 'member' | 'token' | 'mfa_challenge'

export default function LoginPage() {
  const router = useRouter()
  const [mode, setMode] = useState<Mode>('member')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [token, setToken] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [mfaFactorId, setMfaFactorId] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (MOCK_MODE) {
      router.replace('/dashboard')
      return
    }
    if (localStorage.getItem('workspace_token') || localStorage.getItem('member_session_token')) {
      router.replace('/dashboard')
    }
  }, [router])

  async function handleMemberSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!email.trim() || !password) {
      setError('Email and password are required')
      return
    }
    if (!isSupabaseConfigured()) {
      setError('Member sign-in is not available right now — use a workspace token instead.')
      return
    }
    setSubmitting(true)
    try {
      const supabase = getSupabaseClient()
      const { data, error: signInError } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      })
      if (signInError || !data.session) {
        setError(signInError?.message || 'Sign in failed')
        return
      }

      const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
      if (aal && aal.nextLevel === 'aal2' && aal.currentLevel !== 'aal2') {
        const { data: factorsData } = await supabase.auth.mfa.listFactors()
        const factor = factorsData?.totp?.find(f => f.status === 'verified')
        if (!factor) {
          // Workspace requires MFA but this session hasn't stepped up --
          // shouldn't happen (nextLevel implied a verified factor exists),
          // but fail safe rather than silently granting aal1 access.
          setError('Two-factor verification is required but no factor was found. Contact your admin.')
          return
        }
        setMfaFactorId(factor.id)
        setMode('mfa_challenge')
        return
      }

      localStorage.setItem('member_session_token', data.session.access_token)
      router.push('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleMfaSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (mfaCode.trim().length !== 6) {
      setError('Enter the 6-digit code from your authenticator app')
      return
    }
    setSubmitting(true)
    try {
      const supabase = getSupabaseClient()
      const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({ factorId: mfaFactorId })
      if (challengeError || !challenge) {
        setError(challengeError?.message || 'Could not start verification')
        return
      }
      const { data: verify, error: verifyError } = await supabase.auth.mfa.verify({
        factorId: mfaFactorId,
        challengeId: challenge.id,
        code: mfaCode.trim(),
      })
      if (verifyError || !verify) {
        setError(verifyError?.message || 'Incorrect code')
        return
      }
      localStorage.setItem('member_session_token', verify.access_token)
      router.push('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed')
    } finally {
      setSubmitting(false)
    }
  }

  function handleTokenSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!token.trim()) {
      setError('Workspace access token is required')
      return
    }
    localStorage.setItem('workspace_token', token.trim())
    router.push('/dashboard')
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
          width: 420, flexShrink: 0, position: 'relative',
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
        <div style={{ position: 'absolute', bottom: 80, left: -80, width: 300, height: 300, background: 'radial-gradient(circle,rgba(245,166,35,.09),transparent 65%)', pointerEvents: 'none' }} />

        <div style={{ position: 'relative', zIndex: 2, display: 'flex', alignItems: 'center', gap: 10 }}>
          <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}>
            <div style={{ width: 28, height: 28, borderRadius: 8, background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 14px rgba(61,125,255,.5)' }}>
              <div style={{ width: 14, height: 14, background: '#fff', clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)' }} />
            </div>
            <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff' }}>Cloud Decoded</span>
          </a>
        </div>

        <div style={{ position: 'relative', zIndex: 2, flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, letterSpacing: '.1em', color: 'rgba(159,194,255,.75)', marginBottom: 18 }}>
            DETECT → PROPOSE → YOU APPROVE → EXECUTE
          </div>
          <h2 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 32, lineHeight: 1.1, letterSpacing: '-.02em', color: '#fff', margin: '0 0 14px' }}>
            Nothing reaches production until you approve it.
          </h2>
          <p style={{ fontSize: 15, lineHeight: 1.6, color: 'rgba(232,236,242,.55)', margin: '0 0 32px' }}>
            Your infra. Your call. Less guessing.
          </p>
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
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '48px 40px', background: '#070910' }}>
        <div style={{ width: '100%', maxWidth: 400 }}>
          <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 28, letterSpacing: '-.02em', color: '#fff', margin: '0 0 8px' }}>
            Sign in
          </h1>
          <p style={{ fontSize: 14, color: 'rgba(232,236,242,.5)', margin: '0 0 28px' }}>
            Welcome back. Your queue is waiting.
          </p>

          {mode === 'member' ? (
            <form onSubmit={handleMemberSubmit}>
              <div style={{ marginBottom: 14 }}>
                <label style={{ display: 'block', fontSize: 12.5, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 7 }}>
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={e => { setEmail(e.target.value); setError('') }}
                  placeholder="you@company.com"
                  autoComplete="email"
                  style={{
                    width: '100%', boxSizing: 'border-box', background: '#0c111c',
                    border: '1px solid rgba(255,255,255,.11)', borderRadius: 9, color: '#f0f3f8',
                    fontSize: 14, fontFamily: "'IBM Plex Sans',sans-serif", padding: '11px 14px', outline: 'none',
                  }}
                />
              </div>
              <div style={{ marginBottom: 8 }}>
                <label style={{ display: 'block', fontSize: 12.5, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 7 }}>
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={e => { setPassword(e.target.value); setError('') }}
                  placeholder="••••••••••••"
                  autoComplete="current-password"
                  style={{
                    width: '100%', boxSizing: 'border-box', background: '#0c111c',
                    border: '1px solid rgba(255,255,255,.11)', borderRadius: 9, color: '#f0f3f8',
                    fontSize: 14, fontFamily: "'JetBrains Mono',monospace", padding: '11px 14px', outline: 'none',
                  }}
                />
                {error && <p style={{ marginTop: 6, fontSize: 12.5, color: '#ff8a7a' }}>{error}</p>}
              </div>

              <p style={{ textAlign: 'right', fontSize: 12.5, margin: '0 0 4px' }}>
                <a href="/forgot-password" style={{ color: '#9fc2ff', textDecoration: 'none' }}>
                  Forgot password?
                </a>
              </p>

              <button
                type="submit"
                disabled={submitting}
                style={{
                  width: '100%', fontSize: 14, fontWeight: 600, color: '#06101f',
                  background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 13, borderRadius: 10,
                  border: 'none', boxShadow: '0 10px 28px -10px rgba(61,125,255,.65)', marginTop: 20,
                  marginBottom: 16, cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1,
                  fontFamily: "'IBM Plex Sans',sans-serif",
                }}
              >
                {submitting ? 'Signing in…' : 'Sign in →'}
              </button>

              <p style={{ textAlign: 'center', fontSize: 13, margin: '0 0 20px' }}>
                <button
                  type="button"
                  onClick={() => { setMode('token'); setError('') }}
                  style={{ background: 'none', border: 'none', color: '#9fc2ff', fontWeight: 500, cursor: 'pointer', fontSize: 13, fontFamily: "'IBM Plex Sans',sans-serif" }}
                >
                  Use a workspace access token instead
                </button>
              </p>
            </form>
          ) : mode === 'mfa_challenge' ? (
            <form onSubmit={handleMfaSubmit}>
              <div style={{ marginBottom: 8 }}>
                <label style={{ display: 'block', fontSize: 12.5, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 7 }}>
                  6-digit code
                </label>
                <p style={{ fontSize: 12.5, color: 'rgba(232,236,242,.5)', margin: '0 0 10px' }}>
                  Enter the code from your authenticator app.
                </p>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={mfaCode}
                  onChange={e => { setMfaCode(e.target.value.replace(/\D/g, '')); setError('') }}
                  placeholder="123456"
                  autoComplete="one-time-code"
                  style={{
                    width: '100%', boxSizing: 'border-box', background: '#0c111c',
                    border: '1px solid rgba(255,255,255,.11)', borderRadius: 9, color: '#f0f3f8',
                    fontSize: 18, letterSpacing: '.2em', textAlign: 'center',
                    fontFamily: "'JetBrains Mono',monospace", padding: '11px 14px', outline: 'none',
                  }}
                />
                {error && <p style={{ marginTop: 6, fontSize: 12.5, color: '#ff8a7a' }}>{error}</p>}
              </div>

              <button
                type="submit"
                disabled={submitting}
                style={{
                  width: '100%', fontSize: 14, fontWeight: 600, color: '#06101f',
                  background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 13, borderRadius: 10,
                  border: 'none', boxShadow: '0 10px 28px -10px rgba(61,125,255,.65)', marginTop: 20,
                  marginBottom: 16, cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1,
                  fontFamily: "'IBM Plex Sans',sans-serif",
                }}
              >
                {submitting ? 'Verifying…' : 'Verify →'}
              </button>
            </form>
          ) : (
            <form onSubmit={handleTokenSubmit}>
              <div style={{ marginBottom: 8 }}>
                <label style={{ display: 'block', fontSize: 12.5, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 7 }}>
                  Workspace access token
                </label>
                <input
                  type="password"
                  value={token}
                  onChange={e => { setToken(e.target.value); setError('') }}
                  placeholder="cd_ws_••••••••••••••••••••••••••••••••"
                  autoComplete="current-password"
                  style={{
                    width: '100%', boxSizing: 'border-box', background: '#0c111c',
                    border: '1px solid rgba(255,255,255,.11)', borderRadius: 9, color: '#f0f3f8',
                    fontSize: 14, fontFamily: "'JetBrains Mono',monospace", padding: '11px 14px', outline: 'none',
                  }}
                />
                {error && <p style={{ marginTop: 6, fontSize: 12.5, color: '#ff8a7a' }}>{error}</p>}
              </div>

              <button
                type="submit"
                style={{
                  width: '100%', fontSize: 14, fontWeight: 600, color: '#06101f',
                  background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 13, borderRadius: 10,
                  border: 'none', boxShadow: '0 10px 28px -10px rgba(61,125,255,.65)', marginTop: 20,
                  marginBottom: 16, cursor: 'pointer', fontFamily: "'IBM Plex Sans',sans-serif",
                }}
              >
                Sign in →
              </button>

              <p style={{ textAlign: 'center', fontSize: 13, margin: '0 0 20px' }}>
                <button
                  type="button"
                  onClick={() => { setMode('member'); setError('') }}
                  style={{ background: 'none', border: 'none', color: '#9fc2ff', fontWeight: 500, cursor: 'pointer', fontSize: 13, fontFamily: "'IBM Plex Sans',sans-serif" }}
                >
                  Sign in with email instead
                </button>
              </p>
            </form>
          )}

          <p style={{ textAlign: 'center', fontSize: 13.5, color: 'rgba(232,236,242,.5)', margin: 0 }}>
            No account?{' '}
            <a href="/signup" style={{ color: '#9fc2ff', fontWeight: 500, textDecoration: 'none' }}>
              Start 14-day free trial
            </a>
          </p>
        </div>
      </div>
    </div>
  )
}
