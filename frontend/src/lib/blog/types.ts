// Blog content schema. Posts are structured data, not MDX/markdown files
// -- this repo has no MDX dependency (@next/mdx, contentlayer, etc.) and
// the marketing pages already use structured TS data + inline-styled
// React (see AGENTS in app/features/page.tsx, ROWS in app/comparison/page.tsx)
// rather than a content pipeline, so this matches the existing convention
// instead of adding a new one.

export type BlogCategory =
  | 'Drift Detection'
  | 'Incident Response'
  | 'Misconfiguration'
  | 'Compliance'
  | 'Multi-Cloud'

export type ContentBlock =
  | { type: 'p'; text: string }
  | { type: 'h2'; text: string; id: string }
  | { type: 'h3'; text: string; id: string }
  | { type: 'ul'; items: string[] }
  | { type: 'ol'; items: string[] }
  | { type: 'code'; text: string }

export interface FaqItem {
  q: string
  a: string
}

export interface BlogPost {
  slug: string
  title: string
  category: BlogCategory
  publishedDate: string // ISO date, e.g. '2026-09-15'
  excerpt: string
  metaDescription: string
  content: ContentBlock[]
  faqs: FaqItem[]
  ctaHeading: string
  ctaText: string
  ctaLinkHref: string
  ctaLinkLabel: string
  relatedSlugs: [string, string]
}
