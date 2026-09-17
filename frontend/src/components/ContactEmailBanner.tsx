'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// Kelvin's item 7, 2026-09-17 -- non-dismissible banner when a
// workspace has no contact_email. Most workspaces get one at self-serve
// signup (required there), but the admin/MCP-invite path
// (api/routes/internal_workspaces.py) can create one without it --
// credential-expiry (Phase 5) and payment-failure (Phase 7) emails both
// silently have nowhere to go in that case. Clears automatically the
// moment it's saved (has_contact_email flips true on the next fetch).
//
// Deliberately no dismiss/close control anywhere in this component --
// that's the "non-dismissible" part of the decision.

import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getConnectionsStatus, setContactEmail } from '@/lib/api'

interface ContactEmailBannerProps {
  token: string
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function ContactEmailBanner({ token }: ContactEmailBannerProps) {
  const [missing, setMissing] = useState(false)
  const [email, setEmail] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getConnectionsStatus(token)
      .then(status => setMissing(status.has_contact_email === false))
      .catch(() => setMissing(false))
  }, [token])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (!EMAIL_RE.test(email.trim())) {
      setError('Enter a valid email address')
      return
    }
    setSaving(true)
    try {
      await setContactEmail(token, email.trim())
      setMissing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save contact email')
    } finally {
      setSaving(false)
    }
  }

  if (!missing) return null

  return (
    <div className="mx-5 mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3">
      <div className="mb-2 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
        <p className="text-xs text-amber-300">
          <strong className="font-semibold">No contact email on file.</strong> Credential-expiry and
          payment-failure notifications have nowhere to send. Add one to enable them.
        </p>
      </div>
      <form onSubmit={handleSave} className="flex items-center gap-2">
        <input
          type="email"
          value={email}
          onChange={e => { setEmail(e.target.value); setError('') }}
          placeholder="ops@yourcompany.com"
          className="flex-1 rounded border border-amber-500/30 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 outline-none focus:border-amber-400"
        />
        <Button type="submit" size="sm" variant="warning" disabled={saving || !email.trim()} loading={saving}>
          Save
        </Button>
      </form>
      {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
    </div>
  )
}
