'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import type { Session } from '@supabase/supabase-js'
import { ApiError, getBillingStatus } from '@/lib/api'
import { confirmTotpEnrollment, startTotpEnrollment, type TotpEnrollment } from '@/lib/mfa'
import { getSupabaseClient, isSupabaseConfigured } from '@/lib/supabase'

// Real dedicated /login route, recreating login.dc.html's 2-column brand/
// form layout from the design handoff.
//
// Owner account at signup (Kelvin, 2026-11-18): email + password is the only
// way in. The workspace token is never a login -- it's for webhooks and MCP,
// generated in Settings. After sign-in:
//   - a member with a verified TOTP factor completes the MFA challenge;
//   - otherwise, on first login, two-factor setup is offered (skippable;
//     recorded in the user's metadata so it's offered once);
//   - then the workspace's billing state decides where they land: an unpaid
//     workspace goes to /checkout to finish payment, a canceled/suspended one
//     to /billing, everything else to the dashboard.

const MOCK_MODE = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'

type Mode = 'credentials' | 'mfa_challenge' | 'mfa_offer'

const INPUT_STYLE: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', background: '#0c111c',
  border: '1px solid rgba(255,255,255,.11)', borderRadius: 9, color: '#f0f3f8',
  fontSize: 14, fontFamily: "'IBM Plex Sans',sans-serif", padding: '11px 14px', outline: 'none',
}
const CODE_INPUT_STYLE: React.CSSProperties = {
  ...INPUT_STYLE, fontSize: 18, letterSpacing: '.2em', textAlign: 'center', fontFamily: "'JetBrains Mono',monospace",
}
const LABEL_STYLE: React.CSSProperties = {
  display: 'block', fontSize: 12.5, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 7,
}
const PRIMARY_BUTTON_STYLE: React.CSSProperties = {
  width: '100%', fontSize: 14, fontWeight: 600, color: '#06101f',
  background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 13, borderRadius: 10,
  border: 'none', boxShadow: '0 10px 28px -10px rgba(61,125,255,.65)', marginTop: 20,
  marginBottom: 16, fontFamily: "'IBM Plex Sans',sans-serif",
}
const LINK_BUTTON_STYLE: React.CSSProperties = {
  background: 'none', border: 'none', color: '#9fc2ff', fontWeight: 500, cursor: 'pointer',
  fontSize: 13, fontFamily: "'IBM Plex Sans',sans-serif", padding: 0,
}
const ERROR_STYLE: React.CSSProperties = { marginTop: 6, fontSize: 12.5, color: '#ff8a7a' }
const NOTE_STYLE: React.CSSProperties = { fontSize: 12.5, lineHeight: 1.6, color: 'rgba(232,236,242,.55)', margin: '0 0 12px' }

function isUnconfirmedEmail(err: { message?: string; code?: string } | null): boolean {
  return !!err && (err.code === 'email_not_confirmed' || /email not confirmed/i.test(err.message ?? ''))
}

export default function LoginPage() {
  const router = useRouter()
  const [mode, setMode] = useState<Mode>('credentials')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [mfaFactorId, setMfaFactorId] = useState('')
  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null)
  const [pendingToken, setPendingToken] = useState('')
  const [unconfirmed, setUnconfirmed] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (MOCK_MODE) {
      router.replace('/dashboard')
      return
    }
    if (new URLSearchParams(window.location.search).get('verified') === '1') {
      setNotice('Email verified. Sign in to continue.')
    }
    if (!isSupabaseConfigured()) return
    // The verification link signs the user in (supabase-js reads the session
    // from the URL); carry on from there instead of asking for the password.
    getSupabaseClient().auth.getSession().then(({ data }) => {
      if (data.session) afterSignIn(data.session)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router])

  // Where a signed-in member lands depends on their workspace's billing state.
  async function finishSignIn(accessToken: string) {
    localStorage.removeItem('workspace_token')
    localStorage.setItem('member_session_token', accessToken)
    try {
      const billing = await getBillingStatus(accessToken)
      if (billing.subscription_status === 'pending_payment') return router.push('/checkout')
      if (['canceled', 'suspended'].includes(billing.subscription_status)) return router.push('/billing?locked=1')
      router.push('/dashboard')
    } catch (err) {
      localStorage.removeItem('member_session_token')
      setMode('credentials')
      setError(err instanceof ApiError && err.status === 403
        ? 'This account isn\'t a member of any workspace yet.'
        : err instanceof Error ? err.message : 'Sign in failed')
    }
  }

  async function afterSignIn(session: Session) {
    const supabase = getSupabaseClient()
    const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
    const { data: factors } = await supabase.auth.mfa.listFactors()
    const verified = factors?.totp?.find(f => f.status === 'verified')
    if (aal && aal.nextLevel === 'aal2' && aal.currentLevel !== 'aal2') {
      if (!verified) {
        setError('Two-factor verification is required but no factor was found. Contact your admin.')
        return
      }
      setMfaFactorId(verified.id)
      setMode('mfa_challenge')
      return
    }
    if (!verified && !session.user.user_metadata?.mfa_offered) {
      setPendingToken(session.access_token)
      setMode('mfa_offer')
      return
    }
    await finishSignIn(session.access_token)
  }

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setUnconfirmed(false)
    if (!email.trim() || !password) {
      setError('Email and password are required')
      return
    }
    if (!isSupabaseConfigured()) {
      setError('Sign-in is not available right now. Please try again later.')
      return
    }
    setSubmitting(true)
    try {
      const { data, error: signInError } = await getSupabaseClient().auth.signInWithPassword({
        email: email.trim(), password,
      })
      if (isUnconfirmedEmail(signInError)) {
        setUnconfirmed(true)
        setError('Verify your email first — open the link we sent you.')
        return
      }
      if (signInError || !data.session) {
        setError(signInError?.message || 'Sign in failed')
        return
      }
      await afterSignIn(data.session)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleResend() {
    setError('')
    const { error: resendError } = await getSupabaseClient().auth.resend({
      type: 'signup', email: email.trim(),
      options: { emailRedirectTo: `${window.location.origin}/login?verified=1` },
    })
    setNotice(resendError ? '' : `We sent a new verification link to ${email.trim()}.`)
    if (resendError) setError(resendError.message)
  }

  async function handleMfaChallenge(e: React.FormEvent) {
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
        factorId: mfaFactorId, challengeId: challenge.id, code: mfaCode.trim(),
      })
      if (verifyError || !verify) {
        setError(verifyError?.message || 'Incorrect code')
        return
      }
      await finishSignIn(verify.access_token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed')
    } finally {
      setSubmitting(false)
    }
  }

  async function markMfaOffered() {
    await getSupabaseClient().auth.updateUser({ data: { mfa_offered: true } })
  }

  async function handleStartEnrollment() {
    setError('')
    setSubmitting(true)
    try {
      setEnrollment(await startTotpEnrollment())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start two-factor setup')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleConfirmEnrollment(e: React.FormEvent) {
    e.preventDefault()
    if (!enrollment) return
    setError('')
    setSubmitting(true)
    try {
      const upgraded = await confirmTotpEnrollment(enrollment.factorId, mfaCode)
      await markMfaOffered()
      await finishSignIn(upgraded)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not verify code')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleSkipMfa() {
    setSubmitting(true)
    try {
      await markMfaOffered()
      const { data } = await getSupabaseClient().auth.getSession()
      await finishSignIn(data.session?.access_token ?? pendingToken)
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
            {mode === 'mfa_offer' ? 'Protect your account' : 'Sign in'}
          </h1>
          <p style={{ fontSize: 14, color: 'rgba(232,236,242,.5)', margin: '0 0 28px' }}>
            {mode === 'mfa_offer'
              ? 'Add a second factor with an authenticator app. You can also do this later in Members & Security.'
              : 'Welcome back. Your queue is waiting.'}
          </p>
          {notice && (
            <p style={{ ...NOTE_STYLE, color: '#7fe0a8' }}>{notice}</p>
          )}

          {mode === 'credentials' && (
            <form onSubmit={handleSignIn}>
              <div style={{ marginBottom: 14 }}>
                <label style={LABEL_STYLE}>Email</label>
                <input
                  type="email" value={email} placeholder="you@company.com" autoComplete="email" style={INPUT_STYLE}
                  onChange={e => { setEmail(e.target.value); setError('') }}
                />
              </div>
              <div style={{ marginBottom: 8 }}>
                <label style={LABEL_STYLE}>Password</label>
                <input
                  type="password" value={password} placeholder="••••••••••••" autoComplete="current-password"
                  style={{ ...INPUT_STYLE, fontFamily: "'JetBrains Mono',monospace" }}
                  onChange={e => { setPassword(e.target.value); setError('') }}
                />
                {error && <p style={ERROR_STYLE}>{error}</p>}
                {unconfirmed && (
                  <p style={{ marginTop: 6, fontSize: 12.5 }}>
                    <button type="button" onClick={handleResend} style={LINK_BUTTON_STYLE}>Resend verification email</button>
                  </p>
                )}
              </div>
              <p style={{ textAlign: 'right', fontSize: 12.5, margin: '0 0 4px' }}>
                <a href="/forgot-password" style={{ color: '#9fc2ff', textDecoration: 'none' }}>Forgot password?</a>
              </p>
              <button
                type="submit" disabled={submitting}
                style={{ ...PRIMARY_BUTTON_STYLE, cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1 }}
              >
                {submitting ? 'Signing in…' : 'Sign in →'}
              </button>
            </form>
          )}

          {mode === 'mfa_challenge' && (
            <form onSubmit={handleMfaChallenge}>
              <div style={{ marginBottom: 8 }}>
                <label style={LABEL_STYLE}>6-digit code</label>
                <p style={NOTE_STYLE}>Enter the code from your authenticator app.</p>
                <input
                  type="text" inputMode="numeric" maxLength={6} value={mfaCode} placeholder="123456"
                  autoComplete="one-time-code" style={CODE_INPUT_STYLE}
                  onChange={e => { setMfaCode(e.target.value.replace(/\D/g, '')); setError('') }}
                />
                {error && <p style={ERROR_STYLE}>{error}</p>}
              </div>
              <button
                type="submit" disabled={submitting}
                style={{ ...PRIMARY_BUTTON_STYLE, cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1 }}
              >
                {submitting ? 'Verifying…' : 'Verify →'}
              </button>
            </form>
          )}

          {mode === 'mfa_offer' && !enrollment && (
            <div>
              {error && <p style={ERROR_STYLE}>{error}</p>}
              <button
                type="button" disabled={submitting} onClick={handleStartEnrollment}
                style={{ ...PRIMARY_BUTTON_STYLE, cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1 }}
              >
                Set up two-factor authentication →
              </button>
              <p style={{ textAlign: 'center', margin: '0 0 20px' }}>
                <button type="button" disabled={submitting} onClick={handleSkipMfa} style={LINK_BUTTON_STYLE}>
                  Skip for now
                </button>
              </p>
            </div>
          )}

          {mode === 'mfa_offer' && enrollment && (
            <form onSubmit={handleConfirmEnrollment}>
              <p style={NOTE_STYLE}>Scan this with your authenticator app, then enter the 6-digit code it shows.</p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={enrollment.qrCode} alt="Authenticator QR code" width={168} height={168}
                style={{ display: 'block', margin: '0 auto 10px', background: '#fff', borderRadius: 8, padding: 6 }} />
              <p style={{ ...NOTE_STYLE, textAlign: 'center', fontFamily: "'JetBrains Mono',monospace", fontSize: 11.5, wordBreak: 'break-all' }}>
                {enrollment.secret}
              </p>
              <input
                type="text" inputMode="numeric" maxLength={6} value={mfaCode} placeholder="123456"
                autoComplete="one-time-code" style={CODE_INPUT_STYLE}
                onChange={e => { setMfaCode(e.target.value.replace(/\D/g, '')); setError('') }}
              />
              {error && <p style={ERROR_STYLE}>{error}</p>}
              <button
                type="submit" disabled={submitting}
                style={{ ...PRIMARY_BUTTON_STYLE, cursor: submitting ? 'default' : 'pointer', opacity: submitting ? 0.7 : 1 }}
              >
                {submitting ? 'Verifying…' : 'Turn on two-factor →'}
              </button>
            </form>
          )}

          {mode === 'credentials' && (
            <p style={{ textAlign: 'center', fontSize: 13.5, color: 'rgba(232,236,242,.5)', margin: 0 }}>
              No account?{' '}
              <a href="/signup" style={{ color: '#9fc2ff', fontWeight: 500, textDecoration: 'none' }}>Create one</a>
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
