'use client'

// Live status indicators for /status (Phase 5) -- fetches the real
// backend /api/status endpoint (checks: backend, database, frontend
// reachability, see api/main.py's api_status()) instead of the previous
// static "ALL SYSTEMS OPERATIONAL" placeholder. No third-party status
// dependency -- this is the whole self-hosted check.

import { useEffect, useState } from 'react'
import { getSystemStatus, type SystemStatus } from '@/lib/api'
import { MONO_FONT } from '@/components/marketing/SiteChrome'

const REFRESH_MS = 30_000

// Cloud Decoded's design system reserves amber for alerts and green for
// healthy states only (no red accent anywhere on this product) -- so
// "degraded" and "error" both render amber, distinguished by their
// detail text rather than a second alert color.
const TONE: Record<'ok' | 'degraded' | 'error', { color: string; bg: string; border: string; label: string }> = {
  ok:       { color: '#3fd17a', bg: 'rgba(63,209,122,.08)', border: 'rgba(63,209,122,.35)', label: 'OPERATIONAL' },
  degraded: { color: '#f5a623', bg: 'rgba(245,166,35,.08)', border: 'rgba(245,166,35,.35)', label: 'DEGRADED' },
  error:    { color: '#f5a623', bg: 'rgba(245,166,35,.08)', border: 'rgba(245,166,35,.35)', label: 'ISSUE DETECTED' },
}

const SERVICE_LABELS: Record<string, string> = {
  backend: 'API',
  database: 'Database',
  frontend: 'Website',
}

export default function StatusIndicators() {
  const [data, setData] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    async function load() {
      const result = await getSystemStatus()
      if (!cancelled) {
        setData(result)
        setLoading(false)
      }
    }

    load()
    const interval = setInterval(load, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  if (loading) {
    return (
      <div
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: MONO_FONT, fontSize: 12,
          letterSpacing: '.06em', color: 'rgba(232,236,242,.5)', border: '1px solid rgba(232,236,242,.15)',
          background: 'rgba(232,236,242,.04)', padding: '8px 16px', borderRadius: 99, marginBottom: 28,
        }}
      >
        CHECKING SYSTEM STATUS…
      </div>
    )
  }

  if (!data) {
    return (
      <div
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: MONO_FONT, fontSize: 12,
          letterSpacing: '.06em', color: '#f5a623', border: '1px solid rgba(245,166,35,.35)',
          background: 'rgba(245,166,35,.08)', padding: '8px 16px', borderRadius: 99, marginBottom: 28,
        }}
      >
        STATUS UNAVAILABLE — CHECK BACK SHORTLY
      </div>
    )
  }

  const overall = TONE[data.status]

  return (
    <>
      <div
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: MONO_FONT, fontSize: 12,
          letterSpacing: '.06em', color: overall.color, border: `1px solid ${overall.border}`,
          background: overall.bg, padding: '8px 16px', borderRadius: 99, marginBottom: 28,
        }}
      >
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: overall.color, boxShadow: `0 0 8px ${overall.color}` }} />
        {overall.label === 'OPERATIONAL' ? 'ALL SYSTEMS OPERATIONAL' : overall.label}
      </div>

      <div
        style={{
          display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 440, margin: '32px auto 0',
          textAlign: 'left',
        }}
      >
        {(['backend', 'database', 'frontend'] as const).map((key) => {
          const service = data.services[key]
          const tone = TONE[service.status]
          return (
            <div
              key={key}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                padding: '12px 16px', borderRadius: 10, border: '1px solid rgba(232,236,242,.1)',
                background: 'rgba(232,236,242,.03)',
              }}
            >
              <span style={{ fontFamily: MONO_FONT, fontSize: 13, color: 'rgba(232,236,242,.85)' }}>
                {SERVICE_LABELS[key] ?? key}
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: MONO_FONT, fontSize: 11.5, color: tone.color }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: tone.color }} />
                {service.status === 'ok' ? 'operational' : service.detail}
              </span>
            </div>
          )
        })}
      </div>

      <p style={{ fontFamily: MONO_FONT, fontSize: 11, color: 'rgba(232,236,242,.35)', marginTop: 16 }}>
        Last checked {new Date(data.timestamp).toLocaleTimeString()} · refreshes every 30s
      </p>
    </>
  )
}
