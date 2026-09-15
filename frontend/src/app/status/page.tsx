import type { Metadata } from 'next'
import { MarketingHead, MarketingNav, MarketingFooter, PAGE_BG, BODY_FONT, HEAD_FONT, MONO_FONT } from '@/components/marketing/SiteChrome'

// Placeholder status page -- linked from the footer per the landing-page
// revamp. Real incident history / uptime feed is a follow-up; this page
// exists so the footer link resolves to something real rather than a 404.

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
          <div
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: MONO_FONT, fontSize: 12,
              letterSpacing: '.06em', color: '#3fd17a', border: '1px solid rgba(63,209,122,.35)',
              background: 'rgba(63,209,122,.08)', padding: '8px 16px', borderRadius: 99, marginBottom: 28,
            }}
          >
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#3fd17a', boxShadow: '0 0 8px #3fd17a' }} />
            ALL SYSTEMS OPERATIONAL
          </div>
          <h1
            style={{
              fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 36, lineHeight: 1.15,
              letterSpacing: '-.02em', color: '#fff', margin: '0 0 16px',
            }}
          >
            Cloud Decoded system status
          </h1>
          <p style={{ fontSize: 15.5, lineHeight: 1.65, color: 'rgba(232,236,242,.62)', margin: 0 }}>
            A full incident history and uptime feed for this page is on the way. For an active issue affecting
            your workspace, contact <a href="mailto:hello@theclouddecoded.com" style={{ color: '#9fc2ff' }}>hello@theclouddecoded.com</a>.
          </p>
        </section>

        <MarketingFooter />
      </div>
    </>
  )
}
