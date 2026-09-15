import type { BlogPost } from '../types'

export const post: BlogPost = {
  slug: 'better-on-call-incident-response',
  title: "On-Call Shouldn't Mean Starting From a Blank Screen: A Better Incident Response Workflow",
  category: 'Incident Response',
  publishedDate: '2026-10-02',
  excerpt:
    'On-call is painful not because incidents happen, but because engineers face them with no context — an alert fires, five consoles open, and the investigation starts from zero. A better workflow starts on-call from context, not a blank screen.',
  metaDescription:
    'Why on-call incident response is exhausting, the specific time sinks that cause alert fatigue and burnout, and what a context-rich incident response workflow looks like.',
  content: [
    {
      type: 'p',
      text: 'On-call is painful because of what happens in the first five minutes after a page, not the incident itself. An alert fires, the engineer opens five different consoles, and with no context beyond "something is wrong with this service," the investigation starts from a blank screen every single time. A better workflow gives on-call engineers the alert and the diagnosis together, so the first five minutes are spent evaluating a fix instead of reconstructing what happened from scratch at 2am.',
    },
    {
      type: 'h2',
      id: 'what-makes-on-call-painful',
      text: 'What makes on-call painful today',
    },
    {
      type: 'p',
      text: "The typical on-call flow looks like this: an alert fires with a service name and a metric threshold breach. The engineer, half-awake, opens the monitoring dashboard to confirm the alert is real, then opens the logging platform to look for errors around the same timestamp, then checks the deploy history to see if anything shipped recently, then maybe checks the infrastructure state to rule out drift, then pieces together a theory. None of these tools talk to each other. All of the correlation work — which deploy, which log line, which resource — happens manually, in the engineer's head, under time pressure, at the worst possible hour.",
    },
    {
      type: 'h2',
      id: 'the-specific-time-sinks',
      text: 'The specific time sinks',
    },
    {
      type: 'ul',
      items: [
        'Correlating logs across services — a request that fails in the checkout service might have actually failed three hops upstream in a payment service, and finding that requires manually tracing a request ID across multiple log sources that don\'t share a common view.',
        'Finding the last change — "what deployed recently" means checking CI/CD history, infrastructure-as-code commits, and any manual console changes separately, since no single timeline shows all three together.',
        'Figuring out which resource is actually the problem — a symptom on one service is often caused by a dependency two or three layers away, and identifying the actual failing resource means working backward through a dependency graph that usually only exists in someone\'s memory.',
      ],
    },
    {
      type: 'h2',
      id: 'alert-fatigue',
      text: 'Alert fatigue from too many low-context notifications',
    },
    {
      type: 'p',
      text: 'Every alert that arrives with no context and turns out to be low-severity or self-resolving trains the on-call engineer to treat the next alert with a little less urgency. That erosion compounds: after enough false alarms and low-context pages, engineers start triaging by gut feeling instead of by what the alert actually says, which is exactly how a real incident gets a slower response than it deserves. The fix for alert fatigue isn\'t fewer alerts — it\'s alerts that arrive already carrying enough context to be evaluated in seconds instead of investigated from scratch.',
    },
  ],
  faqs: [
    {
      q: 'How do I reduce alert fatigue for my SRE team?',
      a: 'Reduce the number of alerts that require manual investigation to evaluate. An alert that arrives with the likely root cause already identified can be triaged in seconds, while a bare threshold-breach notification requires full investigation every time — and it\'s the repeated low-context investigations, not the volume of alerts alone, that drive fatigue.',
    },
    {
      q: 'What should an incident response workflow include?',
      a: 'At minimum: the alert itself, a likely root cause correlated from recent changes and logs, and a set of specific remediation options ready for review — not just a notification that something is wrong, which forces the responding engineer to build the entire investigation from zero.',
    },
    {
      q: 'How do I improve on-call experience for engineers?',
      a: 'Give every alert enough context that the first action is a decision, not an investigation. Reduce the number of separate tools an engineer has to open to understand what happened, and make sure alerts that turn out to be non-issues are rare enough that engineers still trust the ones that matter.',
    },
    {
      q: 'What context should an alert include?',
      a: 'The affected resource, the likely root cause (correlated against recent deploys, infrastructure changes, and related log activity), and — where possible — a specific set of remediation options, so the on-call engineer can evaluate a decision instead of starting a manual investigation.',
    },
    {
      q: 'How do I reduce on-call burnout?',
      a: 'Burnout tracks closely with how much manual investigation on-call requires, not just how often someone gets paged. Reducing the time and cognitive load of each individual page — by giving alerts more context up front — reduces burnout more reliably than reducing alert volume alone.',
    },
  ],
  ctaHeading: 'Give on-call a head start, not a blank screen',
  ctaText:
    'Cloud Decoded surfaces the alert, the diagnosis, and specific fix options together — so your on-call engineer makes a decision at 2am, not an investigation.',
  ctaLinkHref: '/#how-it-works',
  ctaLinkLabel: 'See how Cloud Decoded works',
  relatedSlugs: ['reduce-mttr-cloud-infrastructure', 'terraform-apply-failed-diagnosis'],
}
