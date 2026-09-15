import type { Metadata } from 'next'
import { MarketingHead, MarketingNav, MarketingFooter, PAGE_BG, BODY_FONT, HEAD_FONT } from '@/components/marketing/SiteChrome'
import StatusIndicators from './StatusIndicators'

// Real status page (Phase 5) -- StatusIndicators fetches the live
// /api/status endpoint (backend/database/frontend, each independently
// checked -- see api/main.py's api_status()) client-side and renders
// real green/amber indicators. No third-party status-page dependency.
// A full incident history / uptime-over-time feed is still a follow-up
// (out of scope for this pass) -- this page shows current state, not
// history.

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'System Status | Cloud Decoded',
  description: 'Current operational status of Cloud Decoded.',
  alternates: { canonical: 'https://theclouddecoded.com/status' },
}

export default function StatusPage() {
  return (
    <>
      <MarketingHead />
      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT, minHeight: '100vh' }}>
        <MarketingNav />

        <section style={{ padding: '80px 40px 100px', maxWidth: 720, margin: '0 auto', textAlign: 'center' }}>
          <h1
            style={{
              fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 36, lineHeight: 1.15,
              letterSpacing: '-.02em', color: '#fff', margin: '0 0 24px',
            }}
          >
            Cloud Decoded system status
          </h1>
          <StatusIndicators />
          <p style={{ fontSize: 15.5, lineHeight: 1.65, color: 'rgba(232,236,242,.62)', margin: '24px 0 0' }}>
            Live status for the API, database, and website, checked directly — not a third-party status page.
            For an active issue affecting your workspace, contact{' '}
            <a href="mailto:hello@theclouddecoded.com" style={{ color: '#9fc2ff' }}>hello@theclouddecoded.com</a>.
          </p>
        </section>

        <MarketingFooter />
      </div>
    </>
  )
}
