import type { MetadataRoute } from 'next'

// No robots.txt existed before this file -- Next.js's app/robots.ts
// convention generates /robots.txt automatically. /blog and /blog/* are
// explicitly crawlable; the authenticated app surface (dashboard, billing,
// checkout, onboarding, accept-invite) is disallowed since it's not
// meant to be indexed and has nothing for a crawler to usefully see
// without a session.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: ['/', '/blog', '/blog/'],
      disallow: ['/dashboard', '/billing', '/checkout', '/onboarding', '/accept-invite'],
    },
    sitemap: 'https://theclouddecoded.com/sitemap.xml',
  }
}
