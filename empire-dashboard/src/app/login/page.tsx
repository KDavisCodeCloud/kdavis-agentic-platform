'use client'

export const dynamic = 'force-dynamic'

import { useState } from 'react'
import { supabase } from '@/lib/supabase'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    setLoading(true)
    setError('')
    const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || window.location.origin
    const { error: err } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: { emailRedirectTo: `${siteUrl}/dashboard` },
    })
    if (err) {
      setError(err.message)
    } else {
      setSent(true)
    }
    setLoading(false)
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-title">Decoded Empire</div>
        <div className="login-sub">Command center — authorized users only</div>

        {sent ? (
          <div className="login-success">
            Check your email for the magic link. You can close this tab.
          </div>
        ) : (
          <form onSubmit={handleLogin}>
            <label className="login-label" htmlFor="email">Email address</label>
            <input
              id="email"
              type="text"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="you@example.com"
              style={{ width: '100%', marginBottom: '12px' }}
              autoFocus
            />
            {error && (
              <div style={{ fontSize: 12, color: 'var(--danger)', marginBottom: 10 }}>{error}</div>
            )}
            <button className="btn" type="submit" disabled={loading} style={{ width: '100%' }}>
              {loading ? 'Sending…' : 'Send magic link'}
            </button>
            <div className="login-note">No password needed. We&apos;ll email you a secure link.</div>
          </form>
        )}
      </div>
    </div>
  )
}
