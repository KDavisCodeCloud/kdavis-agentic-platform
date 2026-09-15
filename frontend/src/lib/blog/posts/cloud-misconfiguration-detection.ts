import type { BlogPost } from '../types'

export const post: BlogPost = {
  slug: 'cloud-misconfiguration-detection',
  title: 'Why Cloud Misconfigurations Go Undetected — And What to Do About It',
  category: 'Misconfiguration',
  publishedDate: '2026-09-22',
  excerpt:
    'Cloud misconfigurations are common because they never throw an error — a loosened bucket policy or an overpermissive IAM role works perfectly right up until someone finds it. Here is why manual audits miss them and what continuous checking looks like.',
  metaDescription:
    'Why cloud misconfigurations are so common, the five most dangerous types across AWS and Azure, and how to catch them with continuous checking instead of periodic manual audits.',
  content: [
    {
      type: 'p',
      text: "Cloud misconfigurations are common because they don't generate errors. A public S3 bucket, an overpermissive IAM role, or an open management port all work exactly as configured — nothing crashes, nothing alerts, nothing tells you it's wrong. The gap sits quietly until a scanner, an attacker, or an auditor finds it. Catching misconfigurations before that happens means checking continuously across compute, storage, networking, and identity, not relying on a periodic audit to catch what accumulated since the last one.",
    },
    {
      type: 'h2',
      id: 'the-invisibility-problem',
      text: 'The invisibility problem',
    },
    {
      type: 'p',
      text: 'A misconfiguration is, by definition, a valid configuration — just not the one you intended. AWS will not stop you from attaching a policy with `"Action": "*"` to a production role. Azure will not stop you from leaving RDP open to 0.0.0.0/0 on a network security group. These are syntactically correct, fully functional settings. Nothing in the platform is designed to tell you they\'re dangerous, because from the platform\'s point of view, they\'re not wrong — they\'re just permissive. The danger is contextual, and context is exactly what an automated system without continuous checking doesn\'t have.',
    },
    {
      type: 'h2',
      id: 'five-dangerous-types',
      text: 'The five most dangerous misconfiguration types',
    },
    {
      type: 'ul',
      items: [
        'IAM wildcard permissions — a role or policy using `*` for actions or resources instead of a scoped list. One compromised credential with a wildcard policy has the run of the account, not just the one service it was supposed to touch.',
        'Public storage buckets — an S3 bucket or Azure Blob container with public read (or worse, write) access, usually set during testing or file-sharing and never locked back down.',
        'Open management ports — SSH (22) or RDP (3389) reachable from 0.0.0.0/0 instead of a bastion host or VPN range, often left open after a one-time debugging session.',
        'Disabled encryption — storage volumes, databases, or buckets provisioned without encryption at rest, frequently because the default in a Terraform module or a console wizard was never overridden.',
        'Overpermissive NSG or security group rules — a rule scoped to "any/any" instead of specific ports and source ranges, usually added under time pressure during an incident and never tightened afterward.',
      ],
    },
    {
      type: 'h2',
      id: 'why-manual-audits-miss-them',
      text: 'Why manual audits miss them',
    },
    {
      type: 'p',
      text: 'A manual audit is a snapshot. It tells you the state of your environment on the day someone ran it — quarterly, at renewal time, or right before a customer\'s security questionnaire is due. Everything that changed in the weeks or months between audits is invisible until the next one. And audits sample: nobody manually reviews every IAM policy and every NSG rule across a production account with hundreds of resources, so the review focuses on what looks suspicious at a glance, which is exactly the wrong filter for a misconfiguration that looks completely ordinary.',
    },
    {
      type: 'h2',
      id: 'what-continuous-checking-looks-like',
      text: 'What continuous checking looks like',
    },
    {
      type: 'p',
      text: "Continuous checking evaluates your actual configuration against a known-bad pattern list on an ongoing basis — every time a policy, bucket setting, or network rule changes, not once a quarter. The check runs the moment the config changes, so a wildcard permission or an open port is flagged within minutes of being created, while it's still fresh in whoever made the change's memory and before it's had time to become someone else's load-bearing dependency.",
    },
    {
      type: 'h2',
      id: 'real-examples',
      text: 'Real examples of misconfigurations that started as one-offs',
    },
    {
      type: 'ul',
      items: [
        'An S3 bucket policy loosened for a debugging session — an engineer sets a bucket to public-read to quickly share a file with a contractor, intending to revert it that afternoon. The afternoon gets busy. The bucket stays public for months.',
        'An IAM role granted broad access for a one-time task — a migration script needs to touch several services, so someone attaches `AdministratorAccess` "just for the migration." The migration finishes. The role keeps the access.',
        'An NSG rule added during an incident and left open — a production VM needs an unusual inbound port opened to receive a diagnostic tool\'s traffic during an outage. The outage resolves. The rule is never part of anyone\'s cleanup checklist.',
      ],
    },
    {
      type: 'h2',
      id: 'preventing-misconfigurations',
      text: 'How to prevent cloud misconfigurations going forward',
    },
    {
      type: 'p',
      text: 'Prevention has two layers that both matter. The first is process: route infrastructure changes through code review and IaC (Terraform, Bicep, ARM, or CloudFormation) so a second person sees a permission change before it ships, instead of a console click that nobody else reviews. The second is detection: even disciplined teams make exceptions during incidents, so continuous checking against known-bad patterns catches what process alone will miss — the emergency change nobody circled back to fix.',
    },
  ],
  faqs: [
    {
      q: 'What is a cloud misconfiguration?',
      a: "A cloud misconfiguration is a setting that is technically valid but unintentionally insecure — a public storage bucket, an overpermissive IAM role, an open management port, or disabled encryption. It doesn't produce an error because it's not invalid, just dangerous.",
    },
    {
      q: 'What are the most common cloud misconfigurations?',
      a: 'IAM wildcard permissions, publicly accessible storage buckets, open management ports like SSH or RDP exposed to the internet, disabled encryption at rest, and overpermissive network security group or security group rules are the five most common and most dangerous.',
    },
    {
      q: 'How do misconfigurations cause security incidents?',
      a: 'A misconfiguration widens the attack surface without anyone intending it to — a public bucket exposes data directly, a wildcard IAM policy turns one compromised credential into full account access, and an open management port gives an attacker a direct path into a production resource.',
    },
    {
      q: 'How do I find misconfigurations in Azure and AWS?',
      a: 'Check IAM policies and Azure RBAC assignments for wildcard or overly broad grants, audit storage buckets and blob containers for public access settings, review network security group and security group rules for overly permissive source ranges, and confirm encryption is enabled on storage and database resources — ideally continuously, not as a one-time pass.',
    },
    {
      q: 'How do I prevent cloud misconfigurations?',
      a: 'Route infrastructure changes through code review and IaC so permission and network changes get a second set of eyes before they ship, and pair that with continuous automated checking so exceptions made during incidents or one-off tasks get caught even when the process gets skipped under pressure.',
    },
  ],
  ctaHeading: 'Catch misconfigurations before they become incidents',
  ctaText:
    'Cloud Decoded runs continuous misconfiguration checks across compute, storage, networking, and identity — surfacing issues before they become incidents.',
  ctaLinkHref: '/#monitor',
  ctaLinkLabel: 'See what Cloud Decoded monitors',
  relatedSlugs: ['aws-iam-misconfiguration', 'azure-nsg-misconfiguration'],
}
