import type { Metadata } from 'next'
import { MarketingHead, MarketingNav, MarketingFooter, PAGE_BG, BODY_FONT, HEAD_FONT } from '@/components/marketing/SiteChrome'

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Terms of Service | Cloud Decoded',
  description: 'The terms that govern use of Cloud Decoded.',
  alternates: { canonical: 'https://theclouddecoded.com/terms' },
  robots: { index: true, follow: true },
}

const EFFECTIVE_DATE = 'September 14, 2026'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 34 }}>
      <h2 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 19, color: '#fff', margin: '0 0 10px' }}>
        {title}
      </h2>
      <div style={{ fontSize: 14.5, lineHeight: 1.75, color: 'rgba(232,236,242,.68)' }}>{children}</div>
    </section>
  )
}

export default function TermsPage() {
  return (
    <>
      <MarketingHead />
      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT }}>
        <MarketingNav />

        <section style={{ padding: '56px 40px 10px', maxWidth: 760, margin: '0 auto' }}>
          <h1 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 34, color: '#fff', margin: '0 0 8px' }}>
            Terms of Service
          </h1>
          <p style={{ fontSize: 13, color: 'rgba(232,236,242,.4)', margin: '0 0 40px' }}>
            Effective {EFFECTIVE_DATE} · THD Agentic Systems LLC
          </p>

          <Section title="1. Agreement to Terms">
            <p>
              These Terms of Service (&ldquo;Terms&rdquo;) are a binding agreement between you (&ldquo;Customer,&rdquo;
              &ldquo;you&rdquo;) and THD Agentic Systems LLC (&ldquo;Cloud Decoded,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;),
              governing your access to and use of the Cloud Decoded platform, dashboard, and connected agents
              (collectively, the &ldquo;Service&rdquo;). By creating a workspace, starting a trial, or otherwise using
              the Service, you agree to these Terms. If you are accepting on behalf of an organization, you
              represent that you have authority to bind that organization.
            </p>
          </Section>

          <Section title="2. The Service">
            <p>
              Cloud Decoded provides a set of agents that monitor connected infrastructure (CI/CD pipelines,
              Kubernetes clusters, cloud accounts, and repositories you explicitly connect) and propose
              remediations. Every proposed action stops at a human-in-the-loop approval gate — the Service does
              not take autonomous action against your infrastructure. You are solely responsible for reviewing
              and approving any proposal before it executes.
            </p>
          </Section>

          <Section title="3. Accounts, Workspaces, and Credentials">
            <p>
              A workspace is created with an access token that functions as a credential to your account — you
              are responsible for keeping it secure and for all activity that occurs under it. If a token is
              compromised, contact us immediately so it can be rotated. You control which cloud accounts,
              repositories, and clusters are connected to your workspace, and can disconnect them at any time
              through the dashboard.
            </p>
          </Section>

          <Section title="4. Bring-Your-Own LLM Keys">
            <p>
              The Service uses a &ldquo;bring your own key&rdquo; model for the language model provider used to
              process your data (Anthropic or OpenAI, at your choice). You are responsible for that provider&apos;s
              own terms and any usage costs billed by them directly. Data sent to your chosen provider is subject
              to that provider&apos;s own data-use terms for API calls.
            </p>
          </Section>

          <Section title="5. Fees, Billing, and Trials">
            <p>
              Paid tiers are billed through Stripe on a subscription basis at the price shown at checkout. A free
              trial, where offered, converts to a paid subscription at the end of the trial period unless
              cancelled first. You can cancel or manage your subscription at any time through the billing portal
              in your dashboard. Fees are non-refundable except where required by law.
            </p>
          </Section>

          <Section title="6. Acceptable Use">
            <p>You agree not to:</p>
            <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
              <li>Use the Service to access or attempt to access infrastructure you are not authorized to manage.</li>
              <li>Attempt to reverse engineer, extract prompts from, or circumvent the Service&apos;s security controls.</li>
              <li>Use the Service in a way that violates any applicable law or a third party&apos;s rights.</li>
              <li>Resell or provide the Service to third parties without our written consent.</li>
            </ul>
          </Section>

          <Section title="7. Data, Privacy, and Security">
            <p>
              Our collection and use of data is described in the{' '}
              <a href="/privacy" style={{ color: '#9fc2ff' }}>Privacy Policy</a>, incorporated into these Terms by
              reference. Our security practices — tenant isolation, credential encryption, audit logging — are
              described on the <a href="/security" style={{ color: '#9fc2ff' }}>Security page</a>. Enterprise
              customers requiring a Data Processing Agreement should contact us directly.
            </p>
          </Section>

          <Section title="8. Intellectual Property">
            <p>
              Cloud Decoded and its underlying technology are owned by THD Agentic Systems LLC. These Terms grant
              you a limited, non-exclusive, non-transferable right to use the Service for your own internal
              business purposes. You retain all rights to your own data, code, and infrastructure configuration.
            </p>
          </Section>

          <Section title="9. Disclaimers and Limitation of Liability">
            <p>
              The Service is provided &ldquo;as is&rdquo; without warranties of any kind, express or implied,
              including fitness for a particular purpose. Because every proposed action requires your explicit
              approval before it executes, you are responsible for the outcome of any action you approve. To the
              maximum extent permitted by law, Cloud Decoded&apos;s total liability arising from these Terms or
              the Service will not exceed the amount you paid us in the twelve months preceding the claim.
            </p>
          </Section>

          <Section title="10. Termination">
            <p>
              You may cancel your subscription at any time through the billing portal. We may suspend or
              terminate access for a violation of these Terms, or for non-payment. On cancellation, your
              workspace and its data are retained (not immediately deleted) unless you request deletion — see
              the Privacy Policy&apos;s Data Retention and Deletion section for how that works.
            </p>
          </Section>

          <Section title="11. Changes to These Terms">
            <p>
              We may update these Terms from time to time. Material changes will be reflected by an updated
              effective date on this page. Continued use of the Service after a change constitutes acceptance
              of the revised Terms.
            </p>
          </Section>

          <Section title="12. Governing Law">
            <p>
              These Terms are governed by the laws of the United States and the state in which THD Agentic
              Systems LLC is organized, without regard to conflict-of-law principles.
            </p>
          </Section>

          <Section title="13. Contact">
            <p>
              Questions about these Terms: <a href="mailto:legal@theclouddecoded.com" style={{ color: '#9fc2ff' }}>legal@theclouddecoded.com</a>
            </p>
          </Section>
        </section>

        <MarketingFooter />
      </div>
    </>
  )
}
