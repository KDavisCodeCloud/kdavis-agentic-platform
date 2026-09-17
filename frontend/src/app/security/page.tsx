import type { Metadata } from 'next'
import { MarketingHead, MarketingNav, MarketingFooter, Eyebrow, PrimaryCta, PAGE_BG, BODY_FONT, HEAD_FONT, MONO_FONT } from '@/components/marketing/SiteChrome'

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Security — SOC 2 Readiness, Tenant Isolation, Full Audit Trail | Cloud Decoded',
  description:
    'How Cloud Decoded protects your infrastructure and data: per-tenant isolation, an approval step that can’t be silently disabled, full audit logging, and a SOC 2 readiness posture built in from day one.',
  alternates: { canonical: 'https://theclouddecoded.com/security' },
  openGraph: {
    type: 'website',
    url: 'https://theclouddecoded.com/security',
    title: 'Security — Cloud Decoded',
    description: 'SOC 2 readiness posture, tenant isolation, a full audit trail, and data retention — stated plainly.',
  },
}

const PILLARS = [
  {
    title: 'Human approval, not a configuration option',
    body: 'Every capability stops at a hard approval step before any proposed fix executes against your infrastructure. This isn’t a setting you can turn off; it’s how the platform is built. Detection and diagnosis are automatic. Action never happens without your team.',
  },
  {
    title: 'Per-tenant isolation, enforced at the database layer',
    body: 'Every table is scoped by workspace, with row-level security enforced at the Postgres layer — not just application logic. A query without a workspace scope fails closed, not open. One customer’s data is never reachable from another’s workspace, by construction.',
  },
  {
    title: 'Data sanitization before anything leaves your workspace context',
    body: 'Every piece of text used for diagnosis — log excerpts, config content, PR diffs — passes through a redaction layer first: API keys, credentials, and PII patterns are stripped before the data ever leaves your workspace context, regardless of which provider is handling that request.',
  },
  {
    title: 'Full audit trail, every action, win or lose',
    body: 'Every run — created, approved, rejected, held, or resolved manually — is written to your own per-tenant audit record: actor, action, resource, outcome, and timestamp. Nothing is deleted from it, and it’s scoped to your workspace the same way every other table is — queryable by you, not just visible in a dashboard summary. If a fix was proposed, you can see exactly what it proposed and what happened to that proposal.',
  },
  {
    title: 'Customer-controlled credentials, least-privilege manifests published',
    body: 'AWS access is a cross-account role assumed with an external ID — never a stored access key. Azure access is a Service Principal you create and can revoke at any time. GitHub access is a real GitHub App installation with fine-grained, revocable permissions — not a personal access token tied to one person’s account. Every AWS action and Azure action any agent can take is published, per-agent, read vs. write — not described in general terms. A Read-Only mode is available per AWS/Azure connection: no write API call is ever attempted, regardless of what you approve.',
  },
  {
    title: 'A circuit breaker on every run',
    body: 'Every execution has a hard spend cap and a call-count limit. If a run exceeds either, it stops — it doesn’t retry, and it doesn’t silently keep going. Runaway cost or a stuck loop can’t turn into a surprise bill or an unbounded action.',
  },
]

export default function SecurityPage() {
  return (
    <>
      <MarketingHead />
      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT }}>
        <MarketingNav />

        <section style={{ padding: '64px 40px 20px', maxWidth: 900, margin: '0 auto' }}>
          <Eyebrow label="SECURITY" sub="SOC 2 readiness, not attestation" />
          <h1
            style={{
              fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 44, lineHeight: 1.1,
              letterSpacing: '-.025em', color: '#fff', margin: '0 0 18px',
            }}
          >
            Your data never leaves your infrastructure without your approval.
          </h1>
          <p style={{ fontSize: 17, lineHeight: 1.65, color: 'rgba(232,236,242,.66)', margin: '0 0 8px', maxWidth: 740 }}>
            Cloud Decoded is SOC 2-ready by design, not retrofitted — per-tenant isolation, sanitization, and
            audit logging were built in from the first line of code, not added after a customer asked. This page
            states plainly what that means. If you need more than this page covers, the security questionnaire
            response is one email away.
          </p>
          <p style={{ fontSize: 13, lineHeight: 1.6, color: 'rgba(232,236,242,.4)', margin: 0, maxWidth: 740 }}>
            SOC 2 <em>readiness</em> describes the architecture and controls in place. It is not a claim of a
            completed SOC 2 Type I or Type II attestation — ask us directly about current attestation status.
          </p>
        </section>

        <section style={{ padding: '30px 40px 20px', maxWidth: 1140, margin: '0 auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 20 }}>
            {PILLARS.map((p) => (
              <article
                key={p.title}
                style={{
                  border: '1px solid rgba(255,255,255,.08)', borderRadius: 14,
                  background: 'linear-gradient(180deg,rgba(255,255,255,.022),rgba(255,255,255,0))',
                  padding: 24,
                }}
              >
                <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 17, lineHeight: 1.3, color: '#fff', margin: '0 0 10px' }}>
                  {p.title}
                </h2>
                <p style={{ fontSize: 13.5, lineHeight: 1.6, color: 'rgba(232,236,242,.6)', margin: 0 }}>
                  {p.body}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section style={{ padding: '20px 40px 30px', maxWidth: 900, margin: '0 auto' }}>
          <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 22, color: '#fff', margin: '0 0 14px' }}>
            Data retention and deletion
          </h2>
          <ul style={{ margin: 0, padding: '0 0 0 20px', fontSize: 14.5, lineHeight: 1.9, color: 'rgba(232,236,242,.66)' }}>
            <li>Audit log entries are retained indefinitely and are never modified after being written.</li>
            <li>Log excerpts and diffs used for a single diagnostic pass are not retained by Cloud Decoded beyond that run’s record — the sanitized excerpt is what’s stored, not the raw source.</li>
            <li>Closing a workspace archives its data rather than immediately deleting it, so a full account deletion request can be honored on request without ambiguity about what still exists.</li>
            <li>Bring-your-own API keys and cloud credentials are encrypted at rest and decrypted only for the duration of the specific call that needs them — never cached in plaintext.</li>
          </ul>
        </section>

        <section style={{ padding: '20px 40px 100px', maxWidth: 900, margin: '0 auto' }}>
          <div
            style={{
              padding: '38px 40px', borderRadius: 16,
              border: '1px solid rgba(245,166,35,.3)',
              background: 'linear-gradient(135deg, rgba(245,166,35,.08), rgba(7,9,16,0))',
              display: 'flex', alignItems: 'center', gap: 28, flexWrap: 'wrap',
            }}
          >
            <div style={{ flex: 1, minWidth: 260 }}>
              <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 22, color: '#fff', margin: '0 0 8px' }}>
                Security questionnaire available on request.
              </h2>
              <p style={{ fontSize: 14.5, lineHeight: 1.6, color: 'rgba(232,236,242,.62)', margin: 0, maxWidth: 480 }}>
                For a formal security review, architecture diagram, or DPA — email us and we’ll send the full
                package.
              </p>
            </div>
            <a
              href="mailto:security@theclouddecoded.com?subject=Security%20questionnaire%20request"
              style={{
                textDecoration: 'none', fontSize: 15, fontWeight: 600, color: '#06101f',
                background: '#e8ecf2', padding: '15px 30px', borderRadius: 11, display: 'inline-block',
              }}
            >
              Request security questionnaire
            </a>
          </div>
          <div style={{ marginTop: 22 }}>
            <PrimaryCta>Start free trial</PrimaryCta>
          </div>
        </section>

        <MarketingFooter />
      </div>
    </>
  )
}
