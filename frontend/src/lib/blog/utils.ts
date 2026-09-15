import { ALL_POSTS } from './posts'
import type { BlogPost, ContentBlock } from './types'

const WORDS_PER_MINUTE = 220

function blockWordCount(block: ContentBlock): number {
  switch (block.type) {
    case 'p':
    case 'h2':
    case 'h3':
      return block.text.split(/\s+/).filter(Boolean).length
    case 'ul':
    case 'ol':
      return block.items.reduce((sum, item) => sum + item.split(/\s+/).filter(Boolean).length, 0)
    case 'code':
      return block.text.split(/\s+/).filter(Boolean).length
    default:
      return 0
  }
}

export function estimateReadTime(post: BlogPost): number {
  const words = post.content.reduce((sum, block) => sum + blockWordCount(block), 0)
  return Math.max(1, Math.round(words / WORDS_PER_MINUTE))
}

export function getAllPosts(): BlogPost[] {
  return [...ALL_POSTS].sort((a, b) => (a.publishedDate < b.publishedDate ? 1 : -1))
}

export function getPostBySlug(slug: string): BlogPost | undefined {
  return ALL_POSTS.find(p => p.slug === slug)
}

export function getAllSlugs(): string[] {
  return ALL_POSTS.map(p => p.slug)
}

export function getRelatedPosts(post: BlogPost): BlogPost[] {
  return post.relatedSlugs
    .map(slug => getPostBySlug(slug))
    .filter((p): p is BlogPost => Boolean(p))
}

export function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' })
}
