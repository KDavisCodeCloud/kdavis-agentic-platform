import type { Metadata } from 'next'
import {
  MarketingHead, MarketingNav, MarketingFooter, Eyebrow,
  PAGE_BG, BODY_FONT, HEAD_FONT, MONO_FONT,
} from '@/components/marketing/SiteChrome'
import { getAllPosts, estimateReadTime, formatDate } from '@/lib/blog/utils'

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Cloud Decoded Blog | Infrastructure Reliability Guides',
  description:
    'Practical guides on Terraform drift, cloud misconfigurations, incident response, compliance, and multi-cloud monitoring across Azure and AWS.',
  alternates: { canonical: 'https://theclouddecoded.com/blog' },
  openGraph: {
    type: 'website',
    url: 'https://theclouddecoded.com/blog',
    title: 'Cloud Decoded Blog | Infrastructure Reliability Guides',
    description:
      'Practical guides on Terraform drift, cloud misconfigurations, incident response, compliance, and multi-cloud monitoring across Azure and AWS.',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Cloud Decoded Blog | Infrastructure Reliability Guides',
    description:
      'Practical guides on Terraform drift, cloud misconfigurations, incident response, compliance, and multi-cloud monitoring across Azure and AWS.',
  },
}

const CATEGORY_COLOR: Record<string, string> = {
  'Drift Detection': '#5a96ff',
  'Incident Response': '#f5a623',
  Misconfiguration: '#ff8a7a',
  Compliance: '#3fd17a',
  'Multi-Cloud': '#9fc2ff',
}

export default function BlogIndexPage() {
  const posts = getAllPosts()

  return (
    <>
      <MarketingHead />
      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT }}>
        <MarketingNav />

        <section style={{ padding: '64px 40px 20px', maxWidth: 1140, margin: '0 auto' }}>
          <Eyebrow label="BLOG" sub={`${posts.length} guides`} />
          <h1
            style={{
              fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 46, lineHeight: 1.08,
              letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px', maxWidth: 780,
            }}
          >
            Infrastructure reliability guides.
          </h1>
          <p style={{ fontSize: 18, lineHeight: 1.6, color: 'rgba(232,236,242,.66)', margin: 0, maxWidth: 700 }}>
            Practical, specific guides on drift detection, misconfigurations, incident response, compliance, and
            multi-cloud monitoring across Terraform, Bicep, ARM, CloudFormation, Azure, and AWS.
          </p>
        </section>

        <section style={{ padding: '30px 40px 100px', maxWidth: 1140, margin: '0 auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 20 }}>
            {posts.map(post => {
              const color = CATEGORY_COLOR[post.category] ?? '#5a96ff'
              const readTime = estimateReadTime(post)
              return (
                <a
                  key={post.slug}
                  href={`/blog/${post.slug}`}
                  style={{
                    textDecoration: 'none', display: 'flex', flexDirection: 'column',
                    border: '1px solid rgba(255,255,255,.08)', borderRadius: 14,
                    background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))',
                    padding: 22,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                    <span
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 6,
                        fontFamily: MONO_FONT, fontSize: 9, letterSpacing: '.06em', color,
                        border: `1px solid ${color}55`, background: `${color}14`, borderRadius: 5, padding: '3px 7px',
                      }}
                    >
                      <span style={{ width: 5, height: 5, borderRadius: '50%', background: color }} />
                      {post.category.toUpperCase()}
                    </span>
                  </div>
                  <h2
                    style={{
                      fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 19, lineHeight: 1.28,
                      color: '#fff', margin: '0 0 10px',
                    }}
                  >
                    {post.title}
                  </h2>
                  <p style={{ fontSize: 13.5, lineHeight: 1.55, color: 'rgba(232,236,242,.6)', margin: '0 0 18px', flex: 1 }}>
                    {post.excerpt}
                  </p>
                  <div
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10, fontFamily: MONO_FONT,
                      fontSize: 11, color: 'rgba(232,236,242,.42)', borderTop: '1px solid rgba(255,255,255,.06)',
                      paddingTop: 12,
                    }}
                  >
                    <time dateTime={post.publishedDate}>{formatDate(post.publishedDate)}</time>
                    <span>·</span>
                    <span>{readTime} min read</span>
                  </div>
                </a>
              )
            })}
          </div>
        </section>

        <MarketingFooter />
      </div>
    </>
  )
}
