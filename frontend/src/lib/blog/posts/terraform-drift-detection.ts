import type { BlogPost } from '../types'

export const post: BlogPost = {
  slug: 'terraform-drift-detection',
  title: 'How to Detect and Fix Terraform Drift Before It Becomes an Incident',
  category: 'Drift Detection',
  publishedDate: '2026-09-15',
  excerpt:
    'Terraform drift is any gap between what your state file says is deployed and what is actually running. Here is what causes it, why it stays invisible, and how to catch it continuously instead of finding out during an outage.',
  metaDescription:
    'Terraform drift explained: what causes it, why nightly plan runs miss it, and how to detect infrastructure drift continuously across Terraform, Bicep, ARM, and CloudFormation.',
  content: [
    {
      type: 'p',
      text: 'Terraform drift is any difference between what your Terraform state file says should be deployed and what is actually running in your cloud account. It happens when a resource is changed outside of Terraform — through the AWS or Azure console, a manual CLI command, or another automation tool — so the live infrastructure no longer matches your code. The fix is to detect that gap continuously, not just during a scheduled `terraform plan`, and reconcile it before the mismatch causes an outage or a compliance finding.',
    },
    {
      type: 'h2',
      id: 'what-causes-drift',
      text: 'What actually causes Terraform drift',
    },
    {
      type: 'p',
      text: 'Drift almost never comes from a single dramatic event. It accumulates from a handful of ordinary, well-intentioned actions that nobody thinks to route back through the state file.',
    },
    {
      type: 'ul',
      items: [
        'Emergency console changes — an engineer opens the AWS console during an incident, flips a setting to stop the bleeding, and moves on once the page clears. The change works. It also never touches Terraform again.',
        'Multi-team environments — two teams share a VPC or a subscription, and one team modifies a security group or an NSG rule the other team\'s module also manages, without either side knowing.',
        'Partial apply failures — a `terraform apply` creates six of eight resources, then hits a rate limit or a timeout. The state file and the real infrastructure now disagree about the other two.',
        'Module sprawl — a shared module gets patched directly in one environment to unblock a deploy, with the intent to "backport the fix to the module later." Later rarely comes.',
      ],
    },
    {
      type: 'h2',
      id: 'why-invisible',
      text: 'Why drift is invisible by default',
    },
    {
      type: 'p',
      text: 'Terraform only knows what it wrote down. It has no built-in mechanism that watches your AWS or Azure account for out-of-band changes — it only compares state against reality when you explicitly ask it to, by running `terraform plan`. Between plan runs, drift is completely silent: no error, no alert, no log line. The infrastructure just quietly stops matching the code that supposedly describes it, and the only signal that something changed is whatever breaks downstream of it.',
    },
    {
      type: 'h2',
      id: 'how-teams-detect-drift-today',
      text: 'How teams currently detect drift — and why it falls short',
    },
    {
      type: 'p',
      text: 'Most teams rely on one of two approaches, and both leave a real gap.',
    },
    {
      type: 'ul',
      items: [
        'Nightly plan runs — a scheduled CI job runs `terraform plan` against every workspace and posts the diff to Slack. This catches drift, but only once every 24 hours. A security group opened at 9am is exposed for up to a full day before anyone sees the plan output — and if the channel gets noisy, that output gets skimmed, not read.',
        'Manual checks — an engineer spot-checks a handful of resources when something looks off. This only works if someone already suspects drift exists, which defeats the purpose of detection in the first place.',
      ],
    },
    {
      type: 'p',
      text: 'Both approaches treat drift detection as a periodic chore instead of a continuous property of the system. Neither one tells you the moment a resource stops matching its definition — both tell you sometime after, if you happen to be looking.',
    },
    {
      type: 'h2',
      id: 'continuous-detection-workflow',
      text: 'What a continuous drift detection workflow looks like',
    },
    {
      type: 'p',
      text: 'A continuous workflow compares live cloud state against your IaC definitions on an ongoing basis, not on a schedule you have to remember to run. When a resource changes outside of Terraform, the gap surfaces immediately, with the exact delta — which resource, which attribute, old value versus new value — rather than a full plan output you have to read line by line to find the one thing that actually changed.',
    },
    {
      type: 'p',
      text: 'That means three things in practice: drift is detected within minutes of happening, not within a day; the delta is scoped to the specific attribute that changed, not buried in a plan for the entire workspace; and the detection covers every resource Terraform manages, not just the ones an engineer remembered to check.',
    },
    {
      type: 'h2',
      id: 'real-examples',
      text: 'Real examples of drift that nightly plans miss for hours',
    },
    {
      type: 'ul',
      items: [
        'S3 bucket replication toggled off in the console — someone disables cross-region replication to debug a sync issue, fixes the underlying problem, and forgets to re-enable it. Terraform still thinks replication is on. It stays off until the next plan run — or until a compliance audit asks why a bucket that should be replicated isn\'t.',
        'A security group rule added during an incident — an engineer opens port 5432 to 0.0.0.0/0 to let a debugging tool reach a database during an outage. The incident resolves. The rule doesn\'t get removed, because removing it isn\'t part of anyone\'s post-incident checklist, and Terraform has no idea the rule exists.',
        'A Terraform module patched directly in production — a hotfix goes straight into the deployed resource to unblock a release, with a ticket filed to "update the module properly." The ticket sits in the backlog. The module and the live resource now permanently disagree.',
      ],
    },
    {
      type: 'h2',
      id: 'fixing-drift-safely',
      text: 'How to fix drift without breaking production',
    },
    {
      type: 'p',
      text: 'The instinct when you find drift is to run `terraform apply` and let it reconcile everything back to the state file. That is often the wrong move. If the drifted change was intentional — an emergency fix that turned out to be the correct long-term configuration — applying blindly reverts a good change back to a stale definition, which can reintroduce the exact problem the manual change fixed.',
    },
    {
      type: 'p',
      text: 'The safer sequence is: identify the specific delta, decide whether the live state or the code is correct, and only then choose a direction — either update the Terraform definition to match what\'s actually running (if the manual change was correct and should stay), or apply the plan to revert the live resource back to code (if the manual change was a stopgap that should never have been permanent). Reconciling in the wrong direction is how drift-detection tools cause their own incidents.',
    },
    {
      type: 'h2',
      id: 'plan-vs-drift-detection',
      text: "Drift detection vs. terraform plan: what's actually different",
    },
    {
      type: 'p',
      text: '`terraform plan` is a point-in-time comparison you have to manually trigger — it tells you the drift that exists at the exact moment you run it, and says nothing about what happens the second after. Drift detection, done continuously, is an ongoing property: it tells you the moment a resource changes, not the moment someone remembers to check. `terraform plan` is a tool. Continuous drift detection is a standing practice built on top of it.',
    },
  ],
  faqs: [
    {
      q: 'What is Terraform drift?',
      a: 'Terraform drift is any difference between what your Terraform state file says is deployed and what is actually running in your cloud account — caused by manual console changes, other automation tools, or partial apply failures that leave state and reality out of sync.',
    },
    {
      q: 'How do I detect infrastructure drift automatically?',
      a: 'Automatic drift detection compares your live cloud resources against your IaC definitions continuously, rather than only when you manually run terraform plan — surfacing the exact resource and attribute that changed within minutes instead of waiting for a scheduled check.',
    },
    {
      q: 'What causes Terraform state to drift?',
      a: 'The most common causes are emergency console changes made during an incident, multiple teams modifying shared resources outside Terraform, partial apply failures that leave some resources unreconciled, and module patches applied directly to production instead of the source module.',
    },
    {
      q: 'How do I fix drift without breaking production?',
      a: 'First identify the exact delta and determine whether the live infrastructure or the Terraform code reflects the correct, intended state. If the manual change was correct, update your code to match it. If it was a stopgap, apply your plan to revert the resource back to code. Applying blindly in the wrong direction can undo a legitimate fix.',
    },
    {
      q: "What's the difference between drift detection and terraform plan?",
      a: 'terraform plan is a manual, point-in-time check you have to remember to run. Drift detection, when continuous, monitors live state against your IaC definitions on an ongoing basis and surfaces changes as they happen, not just whenever someone next runs a plan.',
    },
  ],
  ctaHeading: 'Stop finding drift during an incident',
  ctaText:
    'Cloud Decoded continuously compares your live state against your Terraform, Bicep, ARM, and CloudFormation definitions — surfacing the exact delta without a manual plan run.',
  ctaLinkHref: '/#monitor',
  ctaLinkLabel: 'See what Cloud Decoded monitors',
  relatedSlugs: ['iac-drift-terraform-bicep-arm-cloudformation', 'terraform-apply-failed-diagnosis'],
}
