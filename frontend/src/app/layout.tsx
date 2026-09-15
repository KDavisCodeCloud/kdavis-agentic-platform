import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  // Set once here so every page inherits it -- individual pages (page.tsx,
  // features/, comparison/, problems/, security/) still each set their own
  // canonical/openGraph/title, but don't need to repeat metadataBase.
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Cloud Decoded — Infrastructure Monitoring & Remediation for Azure and AWS',
  description: 'Cloud Decoded monitors Azure and AWS, surfaces every issue with a clear diagnosis, and gives your team fix options — nothing executes until you approve.',
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
