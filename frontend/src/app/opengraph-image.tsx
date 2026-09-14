import { ImageResponse } from 'next/og'

export const runtime = 'edge'
export const alt = 'Cloud Decoded — Human-gated DevOps automation'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '90px 100px',
          background: '#070910',
          backgroundImage:
            'radial-gradient(circle at 82% 18%, rgba(90,150,255,0.16), transparent 55%), ' +
            'radial-gradient(circle at 12% 88%, rgba(245,166,35,0.10), transparent 50%)',
          fontFamily: 'sans-serif',
        }}
      >
        {/* faint grid, command-center texture */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage:
              'linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), ' +
              'linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)',
            backgroundSize: '48px 48px',
            display: 'flex',
          }}
        />

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            fontSize: 15,
            fontWeight: 700,
            letterSpacing: '0.14em',
            color: '#f5a623',
            marginBottom: 34,
          }}
        >
          <div style={{ display: 'flex', width: 9, height: 9, borderRadius: 999, background: '#3fd17a' }} />
          HUMAN-GATED DEVOPS AUTOMATION
        </div>

        <div
          style={{
            display: 'flex',
            fontSize: 76,
            fontWeight: 700,
            letterSpacing: '-0.02em',
            lineHeight: 1.05,
            color: '#f0f3f8',
            marginBottom: 28,
          }}
        >
          Cloud Decoded
        </div>

        <div
          style={{
            display: 'flex',
            fontSize: 40,
            fontWeight: 500,
            letterSpacing: '-0.01em',
            color: '#5a96ff',
            marginBottom: 46,
          }}
        >
          Your 2am incident, already triaged.
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
          {[
            ['Detects', '#5a96ff'],
            ['Triages', '#5a96ff'],
            ['Proposes the fix', '#f5a623'],
            ['You approve', '#3fd17a'],
          ].map(([label, color], i) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
              {i > 0 && <div style={{ display: 'flex', color: 'rgba(240,243,248,0.25)', fontSize: 22 }}>→</div>}
              <div
                style={{
                  display: 'flex',
                  fontFamily: 'monospace',
                  fontSize: 20,
                  color,
                  border: `1px solid ${color}55`,
                  background: `${color}14`,
                  borderRadius: 8,
                  padding: '10px 18px',
                }}
              >
                {label}
              </div>
            </div>
          ))}
        </div>
      </div>
    ),
    { ...size }
  )
}
