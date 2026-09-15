import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import {
  MarketingHead, MarketingNav, MarketingFooter, PrimaryCta,
  PAGE_BG, BODY_FONT, HEAD_FONT, MONO_FONT,
} from '@/components/marketing/SiteChrome'
import { getAllSlugs, getPostBySlug, getRelatedPosts, estimateReadTime, formatDate } from '@/lib/blog/utils'
import type { ContentBlock } from '@/lib/blog/types'

export function generateStaticParams() {
  return getAllSlugs().map(slug => ({ slug }))
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const post = getPostBySlug(params.slug)
  if (!post) return {}

  const url = `https://theclouddecoded.com/blog/${post.slug}`
  return {
    metadataBase: new URL('https://theclouddecoded.com'),
    title: `${post.title} | Cloud Decoded Blog`,
    description: post.metaDescription,
    alternates: { canonical: url },
    openGraph: {
      type: 'article',
      url,
      title: post.title,
      description: post.metaDescription,
      publishedTime: post.publishedDate,
      tags: [post.category],
      // No images[] here -- this route's own opengraph-image.tsx (Next.js's
      // dynamic-segment file convention) generates a per-post image and
      // Next auto-injects it into og:image / twitter:image, same pattern
      // as the root app/opengraph-image.tsx.
    },
    twitter: {
      card: 'summary_large_image',
      title: post.title,
      description: post.metaDescription,
    },
  }
}

const CATEGORY_COLOR: Record<string, string> = {
  'Drift Detection': '#5a96ff',
  'Incident Response': '#f5a623',
  Misconfiguration: '#ff8a7a',
  Compliance: '#3fd17a',
  'Multi-Cloud': '#9fc2ff',
}

function renderBlock(block: ContentBlock, key: number) {
  switch (block.type) {
    case 'p':
      return (
        <p key={key} style={{ fontSize: 16, lineHeight: 1.75, color: 'rgba(232,236,242,.78)', margin: '0 0 20px' }}>
          {block.text}
        </p>
      )
    case 'h2':
      return (
        <h2
          key={key}
          id={block.id}
          style={{
            fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 28, lineHeight: 1.2,
            letterSpacing: '-.02em', color: '#fff', margin: '44px 0 18px', scrollMarginTop: 100,
          }}
        >
          {block.text}
        </h2>
      )
    case 'h3':
      return (
        <h3
          key={key}
          id={block.id}
          style={{
            fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 20, lineHeight: 1.3,
            color: '#fff', margin: '32px 0 14px', scrollMarginTop: 100,
          }}
        >
          {block.text}
        </h3>
      )
    case 'ul':
      return (
        <ul key={key} style={{ margin: '0 0 20px', padding: '0 0 0 22px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {block.items.map((item, i) => (
            <li key={i} style={{ fontSize: 16, lineHeight: 1.7, color: 'rgba(232,236,242,.78)' }}>
              {item}
            </li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol key={key} style={{ margin: '0 0 20px', padding: '0 0 0 22px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {block.items.map((item, i) => (
            <li key={i} style={{ fontSize: 16, lineHeight: 1.7, color: 'rgba(232,236,242,.78)' }}>
              {item}
            </li>
          ))}
        </ol>
      )
    case 'code':
      return (
        <pre
          key={key}
          style={{
            fontFamily: MONO_FONT, fontSize: 13, lineHeight: 1.6, color: '#9fc2ff',
            background: '#0a0d16', border: '1px solid rgba(255,255,255,.08)', borderRadius: 9,
            padding: '14px 16px', margin: '0 0 20px', overflowX: 'auto',
          }}
        >
          {block.text}
        </pre>
      )
    default:
      return null
  }
}

export default function BlogPostPage({ params }: { params: { slug: string } }) {
  const post = getPostBySlug(params.slug)
  if (!post) notFound()

  const readTime = estimateReadTime(post)
  const related = getRelatedPosts(post)
  const color = CATEGORY_COLOR[post.category] ?? '#5a96ff'
  const url = `https://theclouddecoded.com/blog/${post.slug}`

  const faqJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: post.faqs.map(faq => ({
      '@type': 'Question',
      name: faq.q,
      acceptedAnswer: { '@type': 'Answer', text: faq.a },
    })),
  }

  const breadcrumbJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://theclouddecoded.com' },
      { '@type': 'ListItem', position: 2, name: 'Blog', item: 'https://theclouddecoded.com/blog' },
      { '@type': 'ListItem', position: 3, name: post.title, item: url },
    ],
  }

  return (
    <>
      <MarketingHead />
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
      />
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }}
      />

      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT }}>
        <MarketingNav />

        <article style={{ padding: '48px 40px 100px', maxWidth: 760, margin: '0 auto' }}>
          {/* Breadcrumb */}
          <nav aria-label="Breadcrumb" style={{ marginBottom: 26 }}>
            <ol
              style={{
                display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, margin: 0, padding: 0,
                listStyle: 'none', fontFamily: MONO_FONT, fontSize: 11.5, color: 'rgba(232,236,242,.45)',
              }}
            >
              <li><a href="/" style={{ color: 'rgba(232,236,242,.45)', textDecoration: 'none' }}>Home</a></li>
              <li aria-hidden="true">/</li>
              <li><a href="/blog" style={{ color: 'rgba(232,236,242,.45)', textDecoration: 'none' }}>Blog</a></li>
              <li aria-hidden="true">/</li>
              <li style={{ color: 'rgba(232,236,242,.7)' }}>{post.title}</li>
            </ol>
          </nav>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
            <span
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontFamily: MONO_FONT, fontSize: 9.5, letterSpacing: '.06em', color,
                border: `1px solid ${color}55`, background: `${color}14`, borderRadius: 5, padding: '3px 8px',
              }}
            >
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: color }} />
              {post.category.toUpperCase()}
            </span>
            <span style={{ fontFamily: MONO_FONT, fontSize: 11.5, color: 'rgba(232,236,242,.42)' }}>
              {readTime} min read
            </span>
          </div>

          <h1
            style={{
              fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 38, lineHeight: 1.15,
              letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px',
            }}
          >
            {post.title}
          </h1>

          <div
            style={{
              display: 'flex', alignItems: 'center', gap: 10, fontFamily: MONO_FONT, fontSize: 12,
              color: 'rgba(232,236,242,.5)', marginBottom: 44, paddingBottom: 24,
              borderBottom: '1px solid rgba(255,255,255,.08)',
            }}
          >
            <span>Cloud Decoded Team</span>
            <span>·</span>
            <time dateTime={post.publishedDate}>{formatDate(post.publishedDate)}</time>
          </div>

          {/* Body content */}
          <div>{post.content.map((block, i) => renderBlock(block, i))}</div>

          {/* FAQ */}
          <section style={{ marginTop: 56 }}>
            <h2
              style={{
                fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 26, lineHeight: 1.2,
                color: '#fff', margin: '0 0 22px',
              }}
            >
              Frequently asked questions
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {post.faqs.map(faq => (
                <div
                  key={faq.q}
                  style={{
                    border: '1px solid rgba(255,255,255,.08)', borderRadius: 12,
                    background: 'rgba(255,255,255,.018)', padding: '20px 22px',
                  }}
                >
                  <h3 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 16.5, color: '#fff', margin: '0 0 9px' }}>
                    {faq.q}
                  </h3>
                  <p style={{ fontSize: 14.5, lineHeight: 1.6, color: 'rgba(232,236,242,.65)', margin: 0 }}>
                    {faq.a}
                  </p>
                </div>
              ))}
            </div>
          </section>

          {/* CTA */}
          <section
            style={{
              marginTop: 56, padding: '32px 34px', borderRadius: 16,
              border: '1px solid rgba(120,160,255,.25)',
              background: 'linear-gradient(135deg, rgba(90,150,255,.08), rgba(7,9,16,0))',
              display: 'flex', flexDirection: 'column', gap: 16,
            }}
          >
            <div>
              <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 21, color: '#fff', margin: '0 0 8px' }}>
                {post.ctaHeading}
              </h2>
              <p style={{ fontSize: 14.5, lineHeight: 1.6, color: 'rgba(232,236,242,.65)', margin: 0 }}>
                {post.ctaText}
              </p>
            </div>
            <div>
              <PrimaryCta href={post.ctaLinkHref}>{post.ctaLinkLabel}</PrimaryCta>
            </div>
          </section>

          {/* Related posts */}
          {related.length > 0 && (
            <section style={{ marginTop: 56 }}>
              <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 20, color: '#fff', margin: '0 0 18px' }}>
                Related guides
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
                {related.map(r => (
                  <a
                    key={r.slug}
                    href={`/blog/${r.slug}`}
                    style={{
                      textDecoration: 'none', display: 'block',
                      border: '1px solid rgba(255,255,255,.08)', borderRadius: 12,
                      background: 'rgba(255,255,255,.018)', padding: '18px 20px',
                    }}
                  >
                    <div style={{ fontFamily: MONO_FONT, fontSize: 10, letterSpacing: '.06em', color: 'rgba(232,236,242,.4)', marginBottom: 8 }}>
                      {r.category.toUpperCase()}
                    </div>
                    <div style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 15, lineHeight: 1.3, color: '#fff' }}>
                      {r.title}
                    </div>
                  </a>
                ))}
              </div>
            </section>
          )}
        </article>

        <MarketingFooter />
      </div>
    </>
  )
}
