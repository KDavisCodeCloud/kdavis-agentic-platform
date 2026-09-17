'use client'

/*
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 */

// Kelvin's item 2, 2026-09-17 -- persistent, prominent dashboard banner
// during past_due, on every tab (not just /billing). past_due already
// does not block access (confirmed unchanged -- suspended remains the
// only hard block); this banner is purely a visibility/nudge control on
// top of that existing, unchanged access decision. Clears automatically
// the moment subscription_status moves off past_due, since it simply
// won't render on the next fetch.

import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getBillingStatus, getBillingPortalUrl } from '@/lib/api'

const MOCK_MODE = process.env.NEXT_PUBLIC_MOCK_MODE === 'true'

interface PastDueBannerProps {
  token: string
}

export function PastDueBanner({ token }: PastDueBannerProps) {
  const [pastDue, setPastDue] = useState(false)
  const [portalLoading, setPortalLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    getBillingStatus(token)
      .then(status => setPastDue(status.subscription_status === 'past_due'))
      .catch(() => setPastDue(false))
  }, [token])

  async function handleUpdatePayment() {
    setPortalLoading(true)
    setError('')
    try {
      const url = await getBillingPortalUrl(token)
      window.location.href = url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not open the billing portal')
    } finally {
      setPortalLoading(false)
    }
  }

  if (!pastDue) return null

  return (
    <div className="mx-5 mt-3 flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3">
      <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" />
      <p className="flex-1 text-xs text-amber-300">
        <strong className="font-semibold">Payment past due.</strong> Your last charge failed — update your
        payment method to avoid losing access. {error && <span className="text-red-400"> {error}</span>}
      </p>
      <Button
        size="sm"
        variant="warning"
        disabled={portalLoading || MOCK_MODE}
        loading={portalLoading}
        onClick={handleUpdatePayment}
      >
        {MOCK_MODE ? 'Update payment (disabled in demo)' : 'Update payment method →'}
      </Button>
    </div>
  )
}
