// Shared nav + footer for the marketing pages added alongside the
// homepage (app/page.tsx) -- Features, Comparison, Problems (AEO),
// Security. Extracted rather than pasted into all four (CLAUDE.md: "every
// duplicated pattern spotted: extract to shared utility immediately").
// The homepage itself is intentionally left untouched/un-refactored here --
// it's already live and hand-tuned; these pages just match its visual
// language (same fonts, same #070910/#5a96ff/#f5a623/#3fd17a tokens).

import { NewsletterSignup } from './NewsletterSignup'

const LINK: React.CSSProperties = { color: 'rgba(232,236,242,.62)', textDecoration: 'none' }

export function MarketingHead() {
  return (
    <>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link
        href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap"
        rel="stylesheet"
      />
    </>
  )
}

export function MarketingNav() {
  return (
    <nav
      style={{
        position: 'relative',
        zIndex: 5,
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '22px 40px',
        maxWidth: 1280,
        margin: '0 auto',
      }}
    >
      <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 14, textDecoration: 'none' }}>
        <div
          style={{
            position: 'relative',
            width: 26,
            height: 26,
            borderRadius: 8,
            background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 14px rgba(61,125,255,.55)',
          }}
        >
          <div
            style={{
              width: 13,
              height: 13,
              background: '#fff',
              clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)',
            }}
          />
        </div>
        <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 16, color: '#fff', letterSpacing: '-.01em' }}>
          Cloud Decoded
        </span>
      </a>
      <div style={{ marginLeft: 34, display: 'flex', gap: 26, fontSize: 13 }}>
        <a href="/features" style={LINK}>Features</a>
        <a href="/#pricing" style={LINK}>Pricing</a>
        <a href="/problems" style={LINK}>Why Cloud Decoded</a>
        <a href="/comparison" style={LINK}>Comparison</a>
        <a href="/security" style={LINK}>Security</a>
        <a href="/blog" style={LINK}>Blog</a>
      </div>
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 16 }}>
        <a href="/login" style={{ fontSize: 13, color: 'rgba(232,236,242,.7)', textDecoration: 'none' }}>
          Sign in
        </a>
        <a
          href="/signup"
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: '#06101f',
            background: '#e8ecf2',
            padding: '8px 15px',
            borderRadius: 8,
            textDecoration: 'none',
          }}
        >
          Start free trial
        </a>
      </div>
    </nav>
  )
}

export function MarketingFooter() {
  return (
    <footer style={{ maxWidth: 1280, margin: '0 auto', padding: '30px 40px 60px', borderTop: '1px solid rgba(255,255,255,.07)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <div
          style={{
            position: 'relative', width: 24, height: 24, borderRadius: 7,
            background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)', display: 'flex',
            alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 12px rgba(61,125,255,.5)',
          }}
        >
          <div style={{ width: 12, height: 12, background: '#fff', clipPath: 'polygon(46% 0,16% 56%,44% 56%,30% 100%,84% 40%,54% 40%,68% 0)' }} />
        </div>
        <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 15, color: '#fff' }}>Cloud Decoded</span>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)' }}>by THD Agentic Systems LLC</span>
        <nav style={{ marginLeft: 'auto', display: 'flex', gap: 22, fontSize: 12.5, flexWrap: 'wrap' }}>
          <a href="/features" style={LINK}>Features</a>
          <a href="/problems" style={LINK}>Why Cloud Decoded</a>
          <a href="/comparison" style={LINK}>Comparison</a>
          <a href="/security" style={LINK}>Security</a>
          <a href="/blog" style={LINK}>Blog</a>
          <a href="/#pricing" style={LINK}>Pricing</a>
          <a href="/#faq" style={LINK}>FAQ</a>
        </nav>
      </div>
      <NewsletterSignup />
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, paddingTop: 14, borderTop: '1px solid rgba(255,255,255,.05)' }}>
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.4)' }}>© 2026 · Built for the 2am page</span>
        <nav style={{ display: 'flex', gap: 16, fontFamily: "'JetBrains Mono',monospace", fontSize: 11 }}>
          <a href="/terms" style={{ color: 'rgba(232,236,242,.4)', textDecoration: 'none' }}>Terms</a>
          <a href="/privacy" style={{ color: 'rgba(232,236,242,.4)', textDecoration: 'none' }}>Privacy</a>
          <a href="/status" style={{ color: 'rgba(232,236,242,.4)', textDecoration: 'none' }}>Status</a>
        </nav>
        <a
          href="mailto:hello@theclouddecoded.com?subject=Enterprise%20inquiry"
          style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: 'rgba(232,236,242,.32)', textDecoration: 'none' }}
        >
          Enterprise inquiry →
        </a>
      </div>
    </footer>
  )
}

export function Eyebrow({ label, sub }: { label: string; sub?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 26, flexWrap: 'wrap' }}>
      <span
        style={{
          fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.12em',
          color: 'rgba(159,194,255,.9)', border: '1px solid rgba(120,160,255,.32)', borderRadius: 5, padding: '4px 9px',
        }}
      >
        {label}
      </span>
      {sub && (
        <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, letterSpacing: '.06em', color: 'rgba(232,236,242,.4)' }}>
          {sub}
        </span>
      )}
      <span style={{ flex: 1, height: 1, background: 'linear-gradient(90deg,rgba(255,255,255,.12),transparent)' }} />
    </div>
  )
}

export function PrimaryCta({ children = 'Start free trial', href = '/signup' }: { children?: React.ReactNode; href?: string }) {
  return (
    <a
      href={href}
      style={{
        textDecoration: 'none', fontSize: 15, fontWeight: 600, color: '#06101f',
        background: 'linear-gradient(180deg,#5a96ff,#2f6fe6)', padding: '15px 30px',
        borderRadius: 11, boxShadow: '0 14px 34px -10px rgba(61,125,255,.75)', display: 'inline-block',
      }}
    >
      {children}
    </a>
  )
}

export const PAGE_BG = '#070910'
export const BODY_FONT = "'IBM Plex Sans',sans-serif"
export const HEAD_FONT = "'Space Grotesk',sans-serif"
export const MONO_FONT = "'JetBrains Mono',monospace"
