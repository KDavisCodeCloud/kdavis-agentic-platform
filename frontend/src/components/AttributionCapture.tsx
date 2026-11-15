'use client'

import { useEffect } from 'react'
import { captureAttributionFromUrl, trackEvent } from '@/lib/attribution'

// Mounted once in the root layout. Captures ?ref= / utm_* on whatever page a
// visitor lands on, and records signup_clicked for every link to /signup
// (homepage, nav, marketing CTAs, demo header) through one delegated
// listener instead of instrumenting each anchor. Renders nothing.
export function AttributionCapture() {
  useEffect(() => {
    captureAttributionFromUrl()

    function onClick(e: MouseEvent) {
      const target = e.target as Element | null
      const link = target?.closest?.('a[href^="/signup"]')
      if (!link) return
      let demoToken: string | null = null
      try {
        demoToken = sessionStorage.getItem('cd_demo_session_token')
      } catch {
        // storage blocked: the click is still recorded, just not joined to a demo session
      }
      trackEvent('signup_clicked', {
        properties: { cta: window.location.pathname },
        demoToken: window.location.pathname === '/demo' ? demoToken : null,
      })
    }

    document.addEventListener('click', onClick, { capture: true })
    return () => document.removeEventListener('click', onClick, { capture: true })
  }, [])

  return null
}
