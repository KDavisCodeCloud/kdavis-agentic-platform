import { ImageResponse } from 'next/og'
import { getPostBySlug, getAllSlugs } from '@/lib/blog/utils'

// Dynamic per-post OG image -- extends the same ImageResponse approach
// app/opengraph-image.tsx already uses for the homepage, parameterized by
// the [slug] route segment (Next.js's opengraph-image file convention
// receives the same `params` a page.tsx in the same segment would).

export const runtime = 'edge'
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

export function generateStaticParams() {
  return getAllSlugs().map(slug => ({ slug }))
}

const CATEGORY_COLOR: Record<string, string> = {
  'Drift Detection': '#5a96ff',
  'Incident Response': '#f5a623',
  Misconfiguration: '#ff8a7a',
  Compliance: '#3fd17a',
  'Multi-Cloud': '#9fc2ff',
}

export default function BlogOgImage({ params }: { params: { slug: string } }) {
  const post = getPostBySlug(params.slug)
  const title = post?.title ?? 'Cloud Decoded Blog'
  const category = post?.category ?? 'Infrastructure Reliability'
  const color = CATEGORY_COLOR[category] ?? '#5a96ff'

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
            color,
            marginBottom: 34,
          }}
        >
          <div style={{ display: 'flex', width: 9, height: 9, borderRadius: 999, background: color }} />
          {category.toUpperCase()}
        </div>

        <div
          style={{
            display: 'flex',
            fontSize: title.length > 60 ? 52 : 64,
            fontWeight: 700,
            letterSpacing: '-0.02em',
            lineHeight: 1.1,
            color: '#f0f3f8',
            marginBottom: 40,
            maxWidth: 980,
          }}
        >
          {title}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div
            style={{
              display: 'flex',
              width: 26,
              height: 26,
              borderRadius: 7,
              background: 'linear-gradient(150deg,#4a8bff,#1f5fe0)',
            }}
          />
          <div style={{ display: 'flex', fontSize: 20, fontWeight: 600, color: '#f0f3f8' }}>Cloud Decoded</div>
        </div>
      </div>
    ),
    { ...size }
  )
}
