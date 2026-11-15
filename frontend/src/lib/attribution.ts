// First-party funnel tracking (migration 060, gap-table #12/#13). No cookies,
// no third-party scripts. Disclosed on /privacy.
//
// - visitor_id: random, per TAB (sessionStorage). An anonymous visitor is
//   never followed across tabs or visits.
// - attribution: the ?ref= outreach code and utm_* tags a visitor arrived
//   with, kept in localStorage for up to 90 days so a later signup is
//   credited to the outreach conversation that started it.
//
// Every storage access is wrapped: private windows and blocked storage just
// mean an event goes unattributed, never a broken page.

import { API_URL } from '@/lib/api'

const ATTRIBUTION_KEY = 'cd_attribution'
const VISITOR_KEY = 'cd_visitor_id'
const ATTRIBUTION_TTL_MS = 90 * 24 * 60 * 60 * 1000
// Mirrors core/funnel_events.py's _REF_RE.
const REF_RE = /^[A-Za-z0-9_-]{4,64}$/
const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign'] as const

export type ClientFunnelEvent = 'demo_opened' | 'incident_viewed' | 'signup_clicked'

export interface Attribution {
  ref?: string
  utm_source?: string
  utm_medium?: string
  utm_campaign?: string
}

interface StoredAttribution extends Attribution {
  captured_at: number
}

// Reads ?ref= / utm_* from the current URL. A new ref or campaign replaces
// any earlier one (the latest outreach link is the one that brought them
// back). The ref is then removed from the address bar so a copied or shared
// URL doesn't credit someone else's visit to this lead.
export function captureAttributionFromUrl(): void {
  try {
    const url = new URL(window.location.href)
    const ref = url.searchParams.get('ref')
    const next: StoredAttribution = { captured_at: Date.now() }
    if (ref && REF_RE.test(ref)) next.ref = ref
    for (const key of UTM_KEYS) {
      const value = url.searchParams.get(key)
      if (value) next[key] = value.slice(0, 100)
    }
    if (!next.ref && !UTM_KEYS.some(k => next[k])) return

    localStorage.setItem(ATTRIBUTION_KEY, JSON.stringify(next))
    if (url.searchParams.has('ref')) {
      url.searchParams.delete('ref')
      window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
    }
  } catch {
    // storage blocked or malformed URL: proceed unattributed
  }
}

export function getAttribution(): Attribution {
  try {
    const raw = localStorage.getItem(ATTRIBUTION_KEY)
    if (!raw) return {}
    const stored = JSON.parse(raw) as StoredAttribution
    if (!stored.captured_at || Date.now() - stored.captured_at > ATTRIBUTION_TTL_MS) {
      localStorage.removeItem(ATTRIBUTION_KEY)
      return {}
    }
    const { ref, utm_source, utm_medium, utm_campaign } = stored
    return { ref, utm_source, utm_medium, utm_campaign }
  } catch {
    return {}
  }
}

export function getVisitorId(): string | undefined {
  try {
    let id = sessionStorage.getItem(VISITOR_KEY)
    if (!id) {
      id = typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
      sessionStorage.setItem(VISITOR_KEY, id)
    }
    return id
  } catch {
    return undefined
  }
}

// Fire-and-forget. keepalive lets a click event survive the navigation it
// triggers. Never throws.
export function trackEvent(
  event: ClientFunnelEvent,
  opts: { properties?: Record<string, string | number>; demoToken?: string | null } = {},
): void {
  try {
    if (process.env.NEXT_PUBLIC_MOCK_MODE === 'true') return
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (opts.demoToken) headers['X-Demo-Session-Token'] = opts.demoToken
    void fetch(`${API_URL}/api/v1/events`, {
      method: 'POST',
      headers,
      keepalive: true,
      body: JSON.stringify({
        event,
        visitor_id: getVisitorId(),
        path: window.location.pathname,
        properties: opts.properties,
        ...getAttribution(),
      }),
    }).catch(() => {})
  } catch {
    // tracking must never affect the page
  }
}
