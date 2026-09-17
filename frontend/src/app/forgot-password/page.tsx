'use client'

import { useState } from 'react'
import { getSupabaseClient, isSupabaseConfigured } from '@/lib/supabase'

// 24-gap-closure Phase 4 -- password reset request. Supabase Auth owns
// the whole flow end to end: resetPasswordForEmail sends its own email
// (configured in the Supabase dashboard's "Reset Password" template,
// separate from core/email.py which only sends this app's own outbound
// notifications) and the link it contains lands on /reset-password with
// a temporary session already established via the URL fragment, same
// mechanism /accept-invite already relies on for the invite-accept flow.
//
// Always shows the same success message whether or not the email is
// actually registered -- resetPasswordForEmail itself never reveals
// that, and neither should this page (account enumeration).

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!EMAIL_RE.test(email.trim())) {
      setError('Enter a valid email address')
      return
    }
    if (!isSupabaseConfigured()) {
      setError('Password reset is not available right now — contact your workspace admin.')
      return
    }
    setSubmitting(true)
    try {
      const supabase = getSupabaseClient()
      await supabase.auth.resetPasswordForEmail(email.trim(), {
        redirectTo: `${window.location.origin}/reset-password`,
      })
      setSent(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', alignItems: 'center', justifyContent: 'center', background: '#070910', padding: '48px 40px' }}>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link
        href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap"
        rel="stylesheet"
      />
      <div style={{ width: '100%', maxWidth: 400 }}>
        <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none', marginBottom: 40 }}>
          <div style={{ width: 28, height: 28, borderRadius: 8, background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 14px rgba(61,125,255,.5)' }}>
            <div style={{ width: 14, height: 14, background: '#fff', clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)' }} />
          </div>
          <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff' }}>Cloud Decoded</span>
        </a>

        {sent ? (
          <>
            <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 24, color: '#fff', margin: '0 0 10px' }}>
              Check your email
            </h1>
            <p style={{ fontSize: 14, color: 'rgba(232,236,242,.55)', lineHeight: 1.6 }}>
              If an account exists for {email.trim()}, we sent a link to reset your password.
              It expires shortly, so use it soon.{' '}
              <a href="/login" style={{ color: '#9fc2ff' }}>Back to sign in</a>
            </p>
          </>
        ) : (
          <>
            <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 24, color: '#fff', margin: '0 0 8px' }}>
              Reset your password
            </h1>
            <p style={{ fontSize: 14, color: 'rgba(232,236,242,.55)', margin: '0 0 28px' }}>
              We&apos;ll email you a link to set a new one.
            </p>

            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: 8 }}>
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
                {submitting ? 'Sending…' : 'Send reset link →'}
              </button>

              <p style={{ textAlign: 'center', fontSize: 13.5, color: 'rgba(232,236,242,.5)', margin: 0 }}>
                <a href="/login" style={{ color: '#9fc2ff', fontWeight: 500, textDecoration: 'none' }}>
                  Back to sign in
                </a>
              </p>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
