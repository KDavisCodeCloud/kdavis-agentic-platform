'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getSupabaseClient, isSupabaseConfigured } from '@/lib/supabase'

// 24-gap-closure Phase 4 -- where /forgot-password's resetPasswordForEmail
// link lands. supabase-js's detectSessionInUrl parses the recovery link's
// URL fragment and establishes a temporary session automatically, same
// mechanism /accept-invite already relies on -- this page just waits for
// that, has the person set a new password via updateUser, then sends them
// to /login. No backend call needed at all: unlike /accept-invite (which
// must link a fresh supabase_user_id to an existing workspace_members
// row), a password reset is for someone who already has both.

type Phase = 'loading' | 'no_session' | 'set_password' | 'submitting' | 'done' | 'error'

export default function ResetPasswordPage() {
  const router = useRouter()
  const [phase, setPhase] = useState<Phase>('loading')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isSupabaseConfigured()) {
      setPhase('error')
      setError('Password reset is not configured on this deployment yet.')
      return
    }
    const supabase = getSupabaseClient()
    supabase.auth.getSession().then(({ data }) => {
      setPhase(data.session ? 'set_password' : 'no_session')
    })
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setPhase('submitting')
    try {
      const supabase = getSupabaseClient()
      const { error: updateError } = await supabase.auth.updateUser({ password })
      if (updateError) {
        setError(updateError.message)
        setPhase('set_password')
        return
      }
      setPhase('done')
      setTimeout(() => router.push('/login'), 1800)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
      setPhase('set_password')
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

        {phase === 'loading' && (
          <p style={{ fontSize: 14, color: 'rgba(232,236,242,.6)', fontFamily: "'IBM Plex Sans',sans-serif" }}>
            Checking your reset link…
          </p>
        )}

        {phase === 'no_session' && (
          <>
            <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 24, color: '#fff', margin: '0 0 10px' }}>
              Reset link expired or already used
            </h1>
            <p style={{ fontSize: 14, color: 'rgba(232,236,242,.55)', lineHeight: 1.6 }}>
              <a href="/forgot-password" style={{ color: '#9fc2ff' }}>Request a new one</a>, or{' '}
              <a href="/login" style={{ color: '#9fc2ff' }}>sign in</a> if you remember your password.
            </p>
          </>
        )}

        {phase === 'error' && (
          <>
            <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 24, color: '#fff', margin: '0 0 10px' }}>
              Something went wrong
            </h1>
            <p style={{ fontSize: 14, color: '#ff8a7a', lineHeight: 1.6 }}>{error}</p>
          </>
        )}

        {phase === 'done' && (
          <>
            <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 24, color: '#fff', margin: '0 0 10px' }}>
              Password updated
            </h1>
            <p style={{ fontSize: 14, color: 'rgba(232,236,242,.55)', lineHeight: 1.6 }}>
              Taking you to sign in…
            </p>
          </>
        )}

        {(phase === 'set_password' || phase === 'submitting') && (
          <>
            <h1 style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 24, color: '#fff', margin: '0 0 8px' }}>
              Set a new password
            </h1>
            <p style={{ fontSize: 14, color: 'rgba(232,236,242,.55)', margin: '0 0 28px' }}>
              Choose something you haven&apos;t used before.
            </p>

            <form onSubmit={handleSubmit}>
              <div style={{ marginBottom: 14 }}>
                <label style={{ display: 'block', fontSize: 12.5, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 7 }}>
                  New password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={e => { setPassword(e.target.value); setError('') }}
                  placeholder="At least 8 characters"
                  autoComplete="new-password"
                  style={{
                    width: '100%', boxSizing: 'border-box', background: '#0c111c',
                    border: '1px solid rgba(255,255,255,.11)', borderRadius: 9, color: '#f0f3f8',
                    fontSize: 14, fontFamily: "'JetBrains Mono',monospace", padding: '11px 14px', outline: 'none',
                  }}
                />
              </div>
              <div style={{ marginBottom: 8 }}>
                <label style={{ display: 'block', fontSize: 12.5, fontWeight: 500, color: 'rgba(232,236,242,.6)', marginBottom: 7 }}>
                  Confirm new password
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={e => { setConfirmPassword(e.target.value); setError('') }}
                  autoComplete="new-password"
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
                disabled={phase === 'submitting'}
                style={{
                  width: '100%', fontSize: 14, fontWeight: 600, color: '#06101f',
                  background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: 13, borderRadius: 10,
                  border: 'none', boxShadow: '0 10px 28px -10px rgba(61,125,255,.65)', marginTop: 20,
                  cursor: phase === 'submitting' ? 'default' : 'pointer', opacity: phase === 'submitting' ? 0.7 : 1,
                  fontFamily: "'IBM Plex Sans',sans-serif",
                }}
              >
                {phase === 'submitting' ? 'Updating…' : 'Update password →'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
