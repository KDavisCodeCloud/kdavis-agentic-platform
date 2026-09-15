import type { BlogPost } from '../types'

export const post: BlogPost = {
  slug: 'reduce-mttr-cloud-infrastructure',
  title: 'How to Reduce MTTR for Cloud Infrastructure Incidents',
  category: 'Incident Response',
  publishedDate: '2026-09-29',
  excerpt:
    'Reducing MTTR for cloud incidents means compressing root cause investigation, the single biggest time sink in most response workflows — not moving faster once you already know what broke.',
  metaDescription:
    'How to reduce MTTR for cloud infrastructure incidents: what actually inflates response time, why root cause investigation is the biggest time sink, and what elite teams do differently.',
  content: [
    {
      type: 'p',
      text: 'Reducing MTTR (mean time to resolution) for cloud infrastructure incidents means compressing root cause investigation, because that is where most of the time goes — not the fix itself. The actual remediation for a typical incident, a rollback, a config change, a resource restart, usually takes minutes. Finding out which resource, which change, and which root cause caused the alert is what eats the other 90% of the clock. Cutting MTTR means giving engineers the cause and the fix option together, at the moment the alert fires, instead of a bare notification they have to investigate from zero.',
    },
    {
      type: 'h2',
      id: 'what-mttr-measures',
      text: 'What MTTR measures and why it matters beyond the SRE team',
    },
    {
      type: 'p',
      text: 'MTTR measures the average time between an incident starting and it being resolved. It gets tracked as an SRE metric, but it is a business metric first: every minute of MTTR is a minute of degraded service, lost revenue on customer-facing systems, or a broken internal workflow blocking other teams. A platform team that halves its MTTR isn\'t just hitting an internal KPI — it\'s measurably reducing the business cost of every incident that happens from that point forward.',
    },
    {
      type: 'h2',
      id: 'what-inflates-mttr',
      text: 'What actually inflates MTTR',
    },
    {
      type: 'ul',
      items: [
        'Root cause investigation — the single biggest time sink. An alert says a service is unhealthy; it rarely says why. The engineer has to correlate logs, check recent deploys, look for infrastructure drift, and rule out dependencies before they even know what they\'re fixing.',
        'Alert context arriving without diagnosis — most alerting tools tell you something is wrong and stop there. "CPU above threshold" or "pod restarting" describes a symptom, not a cause, so the actual diagnostic work starts from scratch every time.',
        'Switching between five consoles — correlating a CloudWatch alarm, a GitHub Actions run, a Kubernetes dashboard, and a cost report means five separate logins, five separate UIs, and manually piecing together a timeline that no single tool shows in one place.',
      ],
    },
    {
      type: 'h2',
      id: 'what-actually-compresses-it',
      text: 'The workflow changes that actually compress MTTR',
    },
    {
      type: 'p',
      text: 'The lever that moves MTTR the most is removing investigation from the response loop entirely — not making investigation faster, skipping straight past it. That means the alert arrives already correlated with the likely cause: the specific deploy, the specific drifted resource, the specific config change that lines up with when the symptom started. The engineer\'s first action becomes a decision (approve this fix, or don\'t) instead of a search (what changed, and where).',
    },
    {
      type: 'h2',
      id: 'the-38-percent-stat',
      text: 'Where the real time savings comes from',
    },
    {
      type: 'p',
      text: "Automated incident response orchestration reduces MTTR by 38% on average — and the mechanism behind that number matters more than the number itself. The savings doesn't come from engineers typing commands faster or clicking through dashboards more efficiently. It comes from removing the investigation phase from the loop altogether: when the cause is already identified by the time a human looks at the alert, the entire \"figure out what happened\" phase — historically the largest single chunk of MTTR — simply doesn't happen. You can't optimize your way to that kind of reduction by speeding up the same manual investigation; you have to remove the need for it.",
    },
    {
      type: 'h2',
      id: 'what-elite-teams-do-differently',
      text: 'What elite teams do differently',
    },
    {
      type: 'p',
      text: 'Teams with consistently low MTTR share a pattern: they treat "alert plus diagnosis" as a single unit, never shipped separately. They don\'t accept a monitoring setup that pages someone with only a symptom and expects a human to reconstruct the story from five different tools under pressure. Every alert that reaches a human already carries the likely root cause and a short list of remediation options, so the on-call engineer\'s job is judgment — approve, adjust, or escalate — not archaeology.',
    },
  ],
  faqs: [
    {
      q: 'What is MTTR in cloud infrastructure?',
      a: 'MTTR (mean time to resolution) is the average time between an infrastructure incident starting and being fully resolved. It includes detection, root cause investigation, and the fix itself — with root cause investigation typically consuming the largest share of that time.',
    },
    {
      q: "What's a good MTTR for cloud incidents?",
      a: 'It varies heavily by incident severity and team maturity, but the more useful benchmark is trend, not a fixed number: teams that remove manual root cause investigation from their response loop commonly see MTTR reductions around 38% versus teams relying on alert-then-investigate workflows.',
    },
    {
      q: 'What slows down incident resolution the most?',
      a: 'Root cause investigation — correlating logs, recent deploys, infrastructure drift, and dependency health to figure out what actually caused an alert. The remediation itself, once the cause is known, is usually fast; finding the cause is what takes time.',
    },
    {
      q: 'How do I measure MTTR for my SRE team?',
      a: 'Track the timestamp an incident is detected (alert fired or first customer impact) against the timestamp it is confirmed resolved, averaged across a rolling window of incidents. Break it down by severity, since a P1 and a P4 have very different investigation depth and shouldn\'t be averaged together without that context.',
    },
    {
      q: "What's the difference between MTTR and MTTD?",
      a: 'MTTD (mean time to detection) measures how long it takes to notice an incident is happening at all. MTTR (mean time to resolution) measures how long it takes to fully resolve it once detected — MTTD ends where MTTR begins.',
    },
  ],
  ctaHeading: 'Skip the investigation, not the diagnosis',
  ctaText:
    'Cloud Decoded delivers the alert, the root cause, and specific fix options together — so your team makes a decision instead of starting an investigation.',
  ctaLinkHref: '/#how-it-works',
  ctaLinkLabel: 'See how Cloud Decoded works',
  relatedSlugs: ['better-on-call-incident-response', 'terraform-apply-failed-diagnosis'],
}
