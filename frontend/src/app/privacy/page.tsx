import type { Metadata } from 'next'
import { MarketingHead, MarketingNav, MarketingFooter, PAGE_BG, BODY_FONT, HEAD_FONT } from '@/components/marketing/SiteChrome'

export const metadata: Metadata = {
  metadataBase: new URL('https://theclouddecoded.com'),
  title: 'Privacy Policy | Cloud Decoded',
  description: 'How Cloud Decoded collects, uses, and protects your data.',
  alternates: { canonical: 'https://theclouddecoded.com/privacy' },
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

export default function PrivacyPage() {
  return (
    <>
      <MarketingHead />
      <div style={{ width: 1280, maxWidth: '100%', margin: '0 auto', background: PAGE_BG, fontFamily: BODY_FONT }}>
        <MarketingNav />

        <section style={{ padding: '56px 40px 10px', maxWidth: 760, margin: '0 auto' }}>
          <h1 style={{ fontFamily: HEAD_FONT, fontWeight: 600, fontSize: 34, color: '#fff', margin: '0 0 8px' }}>
            Privacy Policy
          </h1>
          <p style={{ fontSize: 13, color: 'rgba(232,236,242,.4)', margin: '0 0 40px' }}>
            Effective {EFFECTIVE_DATE} · THD Agentic Systems LLC
          </p>

          <Section title="1. What This Covers">
            <p>
              This Privacy Policy describes how THD Agentic Systems LLC (&ldquo;Cloud Decoded,&rdquo; &ldquo;we&rdquo;)
              collects, uses, and protects information in connection with the Cloud Decoded platform. It applies
              to workspace owners and any users they invite. It does not apply to the infrastructure data your
              agents process (CI/CD logs, IaC files, cluster state) except as described in Section 3 below.
            </p>
          </Section>

          <Section title="2. Information We Collect">
            <p>We collect:</p>
            <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
              <li><strong>Account information:</strong> company name and a contact email, collected at signup.</li>
              <li><strong>Billing information:</strong> handled directly by Stripe — we do not store your card details ourselves.</li>
              <li>
                <strong>Connected-system credentials:</strong> encrypted at rest — a GitHub App installation, an
                AWS cross-account role ARN, an Azure Service Principal, an Azure DevOps PAT, or a Kubernetes
                service-account token, depending on which connectors you choose to configure.
              </li>
              <li><strong>Usage and audit data:</strong> agent run history, HITL approval decisions, and audit log entries generated as you use the Service.</li>
              <li><strong>Anonymous visitor data:</strong> country-level location and referrer/UTM data from marketing page visits — no cookies, no individual tracking.</li>
            </ul>
          </Section>

          <Section title="3. How Connected-Infrastructure Data Is Processed">
            <p>
              When an agent runs, it processes only what&apos;s needed for that specific task — log excerpts,
              config file contents, PR diffs, or resource state from the systems you&apos;ve connected. Every piece
              of that text passes through a redaction layer before it reaches any LLM provider: API keys,
              credentials, and PII patterns are stripped first, regardless of provider. Data is sent to the LLM
              provider you configure (Anthropic or OpenAI) under that provider&apos;s own API terms — it is not
              used to train Cloud Decoded&apos;s own models, and we do not control or guarantee a specific
              provider&apos;s training-data policy beyond what that provider states for API traffic.
            </p>
          </Section>

          <Section title="4. How We Use Information">
            <p>We use the information above to:</p>
            <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
              <li>Operate and maintain your workspace and its connected agents.</li>
              <li>Process billing through Stripe and communicate about your subscription.</li>
              <li>Send account-related notifications (e.g. a security alert, a required action).</li>
              <li>Maintain the immutable audit log required for the Service&apos;s own HITL/security model.</li>
              <li>Improve the Service&apos;s reliability and security.</li>
            </ul>
          </Section>

          <Section title="5. Sub-processors">
            <p>
              We share information with a limited set of sub-processors necessary to run the Service: the LLM
              provider you configure (Anthropic or OpenAI), Stripe for billing, and our infrastructure/hosting
              providers. A current sub-processor list is available on request.
            </p>
          </Section>

          <Section title="6. Data Retention and Deletion">
            <p>
              Audit log entries are retained indefinitely and never modified once written — this is a security
              requirement, not a default we can turn off. Cancelling a subscription does not immediately delete
              your data; it archives it, so a subsequent deletion request can be honored unambiguously. To
              request deletion of your workspace&apos;s credentials and personal data, contact{' '}
              <a href="mailto:privacy@theclouddecoded.com" style={{ color: '#9fc2ff' }}>privacy@theclouddecoded.com</a>{' '}
              once your subscription is cancelled — we will confirm once your credentials and contact information
              have been purged. Billing and audit records may be retained after deletion where required for legal,
              accounting, or security-audit purposes.
            </p>
          </Section>

          <Section title="7. Security">
            <p>
              Every table in our database is scoped by workspace with row-level security enforced at the
              database layer. Connected-system credentials are encrypted at rest and decrypted only for the
              duration of the specific call that needs them. Full detail is on the{' '}
              <a href="/security" style={{ color: '#9fc2ff' }}>Security page</a>.
            </p>
          </Section>

          <Section title="8. Your Rights">
            <p>
              Depending on your location, you may have rights to access, correct, or delete your personal
              information, or to object to certain processing (for example, under GDPR or CCPA). To exercise
              any of these rights, contact{' '}
              <a href="mailto:privacy@theclouddecoded.com" style={{ color: '#9fc2ff' }}>privacy@theclouddecoded.com</a>.
              Enterprise customers with specific data-processing requirements should request a Data Processing
              Agreement.
            </p>
          </Section>

          <Section title="9. Children's Privacy">
            <p>
              The Service is intended for business use and is not directed at individuals under 18. We do not
              knowingly collect information from anyone under 18.
            </p>
          </Section>

          <Section title="10. Changes to This Policy">
            <p>
              We may update this Privacy Policy from time to time. Material changes will be reflected by an
              updated effective date on this page.
            </p>
          </Section>

          <Section title="11. Contact">
            <p>
              Questions about this policy: <a href="mailto:privacy@theclouddecoded.com" style={{ color: '#9fc2ff' }}>privacy@theclouddecoded.com</a>
            </p>
          </Section>
        </section>

        <MarketingFooter />
      </div>
    </>
  )
}
