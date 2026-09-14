import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  // Set once here so every page inherits it -- individual pages (page.tsx,
  // features/, comparison/, problems/, security/) still each set their own
  // canonical/openGraph/title, but don't need to repeat metadataBase.
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Cloud Decoded — DevOps Agent Platform',
  description: 'Autonomous DevOps agents for mid-market engineering teams. HITL remediation for CI/CD, Kubernetes, IAM, FinOps, and more.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark h-full">
      <body className="h-full bg-zinc-950 text-zinc-100 antialiased">
        {children}
      </body>
    </html>
  )
}
