'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'

export default function NotFound() {
  const pathname = usePathname()
  const timestamp = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC'

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 40,
        position: 'relative',
        overflow: 'hidden',
        background: '#070910',
        fontFamily: "'IBM Plex Sans', sans-serif",
      }}
    >
      <style>{`
        @keyframes cd-glow { 0%, 100% { opacity: .5 } 50% { opacity: 1 } }
        @keyframes cd-flicker { 0%, 94%, 96%, 100% { opacity: 1 } 95% { opacity: .3 } }
        .cd-404-link:hover { background: rgba(255,255,255,.08) }
        .cd-404-cta:hover { opacity: .9 }
      `}</style>

      {/* background grid */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage:
            'linear-gradient(rgba(120,160,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(120,160,255,.035) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          WebkitMaskImage: 'radial-gradient(80% 80% at 50% 45%, #000, transparent 72%)',
          maskImage: 'radial-gradient(80% 80% at 50% 45%, #000, transparent 72%)',
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          top: '30%',
          left: '50%',
          transform: 'translateX(-50%)',
          width: 600,
          height: 400,
          background: 'radial-gradient(circle, rgba(47,111,230,.14), transparent 65%)',
          pointerEvents: 'none',
          animation: 'cd-glow 4s ease-in-out infinite',
        }}
      />

      <div style={{ position: 'relative', zIndex: 2, textAlign: 'center', maxWidth: 600 }}>
        <Link
          href="/"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 9,
            textDecoration: 'none',
            marginBottom: 52,
          }}
        >
          <div
            style={{
              width: 26,
              height: 26,
              borderRadius: 7,
              background: 'linear-gradient(150deg, #4a8bff, #1f5fe0)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 12px rgba(61,125,255,.45)',
            }}
          >
            <div
              style={{
                width: 13,
                height: 13,
                background: '#fff',
                clipPath: 'polygon(46% 0, 16% 56%, 44% 56%, 30% 100%, 84% 40%, 54% 40%, 68% 0)',
              }}
            />
          </div>
          <span style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 600, fontSize: 15, color: '#fff' }}>
            Cloud Decoded
          </span>
        </Link>

        <div
          style={{
            border: '1px solid rgba(255,255,255,.08)',
            borderRadius: 14,
            background: 'linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.005))',
            padding: '36px 40px',
            marginBottom: 36,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 26 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#ff5f57' }} />
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#febc2e' }} />
            <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#28c840' }} />
            <span
              style={{
                marginLeft: 10,
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                color: 'rgba(232,236,242,.35)',
              }}
            >
              cloud-decoded · incident-console · route lookup
            </span>
          </div>

          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontWeight: 700,
              fontSize: 100,
              lineHeight: 1,
              letterSpacing: '-.02em',
              color: 'rgba(255,255,255,.08)',
              marginBottom: 6,
              animation: 'cd-flicker 8s ease-in-out infinite',
            }}
          >
            404
          </div>

          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, lineHeight: 2, textAlign: 'left' }}>
            <div style={{ color: '#ff8a7a' }}>ERROR: route not matched</div>
            <div style={{ color: 'rgba(232,236,242,.45)' }}>
              path: <span style={{ color: '#9fc2ff' }}>{pathname || '/unknown-page'}</span>
            </div>
            <div style={{ color: 'rgba(232,236,242,.45)' }}>
              status: <span style={{ color: '#f5a623' }}>404 NOT_FOUND</span>
            </div>
            <div style={{ color: 'rgba(232,236,242,.45)' }}>
              timestamp: <span style={{ color: 'rgba(232,236,242,.6)' }}>{timestamp}</span>
            </div>
            <div style={{ color: 'rgba(232,236,242,.28)', marginTop: 8 }}>
              → no incident was created. no action was taken.
            </div>
          </div>
        </div>

        <h1
          style={{
            fontFamily: "'Space Grotesk', sans-serif",
            fontWeight: 600,
            fontSize: 26,
            letterSpacing: '-.02em',
            color: '#fff',
            margin: '0 0 12px',
          }}
        >
          Page not found
        </h1>
        <p style={{ fontSize: 15, lineHeight: 1.65, color: 'rgba(232,236,242,.55)', margin: '0 0 36px' }}>
          The URL you followed doesn&apos;t exist or has been moved. Nothing to approve here.
        </p>

        <div style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Link
            href="/"
            className="cd-404-link"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 7,
              fontSize: 14,
              fontWeight: 500,
              color: 'rgba(232,236,242,.7)',
              background: 'rgba(255,255,255,.04)',
              border: '1px solid rgba(255,255,255,.12)',
              padding: '11px 20px',
              borderRadius: 9,
              textDecoration: 'none',
            }}
          >
            ← Home
          </Link>
          <Link
            href="/dashboard"
            className="cd-404-cta"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 7,
              fontSize: 14,
              fontWeight: 600,
              color: '#06101f',
              background: 'linear-gradient(180deg, #5a96ff, #2f6fe6)',
              padding: '11px 20px',
              borderRadius: 9,
              boxShadow: '0 8px 22px -8px rgba(61,125,255,.65)',
              textDecoration: 'none',
            }}
          >
            Incident Console →
          </Link>
        </div>

        <div style={{ marginTop: 52, fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: 'rgba(232,236,242,.22)' }}>
          Need help?{' '}
          <a href="mailto:hello@theclouddecoded.com" style={{ color: 'rgba(159,194,255,.4)' }}>
            hello@theclouddecoded.com
          </a>
        </div>
      </div>
    </div>
  )
}
