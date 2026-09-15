import type { MetadataRoute } from 'next'
import { getAllPosts } from '@/lib/blog/utils'

const BASE_URL = 'https://theclouddecoded.com'

// No sitemap existed before this file -- Next.js's app/sitemap.ts
// convention generates /sitemap.xml automatically at build time. Blog
// post entries are generated from the same ALL_POSTS data the blog
// pages render from, so a new post added to src/lib/blog/posts/ is
// picked up here with no manual sitemap edit required.
export default function sitemap(): MetadataRoute.Sitemap {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: `${BASE_URL}/`, changeFrequency: 'weekly', priority: 1 },
    { url: `${BASE_URL}/features`, changeFrequency: 'monthly', priority: 0.8 },
    { url: `${BASE_URL}/problems`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${BASE_URL}/comparison`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${BASE_URL}/security`, changeFrequency: 'monthly', priority: 0.7 },
    { url: `${BASE_URL}/blog`, changeFrequency: 'weekly', priority: 0.9 },
    { url: `${BASE_URL}/signup`, changeFrequency: 'monthly', priority: 0.6 },
    { url: `${BASE_URL}/login`, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${BASE_URL}/status`, changeFrequency: 'daily', priority: 0.3 },
    { url: `${BASE_URL}/privacy`, changeFrequency: 'yearly', priority: 0.2 },
    { url: `${BASE_URL}/terms`, changeFrequency: 'yearly', priority: 0.2 },
  ]

  const postRoutes: MetadataRoute.Sitemap = getAllPosts().map(post => ({
    url: `${BASE_URL}/blog/${post.slug}`,
    lastModified: post.publishedDate,
    changeFrequency: 'monthly',
    priority: 0.8,
  }))

  return [...staticRoutes, ...postRoutes]
}
