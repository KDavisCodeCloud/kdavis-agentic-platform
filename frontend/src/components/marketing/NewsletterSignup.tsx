'use client'

// Newsletter signup block -- Cloud Decoded email lifecycle system
// (migration 051). Rendered once inside MarketingFooter (SiteChrome.tsx)
// so it appears on every marketing page that uses the shared footer
// (Features, Problems, Comparison, Security) without editing each page.
// Posts to the backend's public POST /email/subscribe -- no Next.js API
// route needed, this hits the FastAPI backend directly like the rest of
// this app's public forms (see lib/api.ts's API_URL convention).

import { useState } from 'react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export function NewsletterSignup() {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    setStatus('loading')
    try {
      const res = await fetch(`${API_URL}/api/v1/email/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), source: 'newsletter_signup' }),
      })
      if (!res.ok) throw new Error('subscribe failed')
      setStatus('done')
    } catch {
      setStatus('error')
    }
  }

  if (status === 'done') {
    return (
      <div style={{ padding: '18px 0', fontFamily: "'IBM Plex Sans',sans-serif", fontSize: 13, color: 'rgba(63,209,122,.9)' }}>
        You&apos;re in -- check your inbox for issue one.
      </div>
    )
  }

  return (
    <div style={{ padding: '22px 0', borderTop: '1px solid rgba(255,255,255,.07)' }}>
      <div style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 14, color: '#fff', marginBottom: 4 }}>
        Decoded Ops
      </div>
      <div style={{ fontFamily: "'IBM Plex Sans',sans-serif", fontSize: 12.5, color: 'rgba(232,236,242,.55)', marginBottom: 12, maxWidth: 420 }}>
        Production agentic operations, decoded. 16 letters. No fluff.
      </div>
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input
          type="email"
          required
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{
            background: 'rgba(255,255,255,.04)',
            border: '1px solid rgba(255,255,255,.12)',
            borderRadius: 8,
            padding: '9px 12px',
            fontSize: 13,
            color: '#eef2f5',
            minWidth: 220,
            fontFamily: "'IBM Plex Sans',sans-serif",
          }}
        />
        <button
          type="submit"
          disabled={status === 'loading'}
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: '#06101f',
            background: '#5a96ff',
            border: 'none',
            padding: '9px 16px',
            borderRadius: 8,
            cursor: status === 'loading' ? 'default' : 'pointer',
            opacity: status === 'loading' ? 0.7 : 1,
          }}
        >
          {status === 'loading' ? 'Subscribing…' : 'Subscribe'}
        </button>
      </form>
      {status === 'error' && (
        <div style={{ marginTop: 8, fontSize: 12, color: 'rgba(224,93,93,.9)' }}>
          Something went wrong -- try again in a moment.
        </div>
      )}
    </div>
  )
}
