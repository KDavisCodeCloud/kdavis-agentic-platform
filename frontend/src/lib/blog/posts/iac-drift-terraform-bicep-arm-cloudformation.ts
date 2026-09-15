import type { BlogPost } from '../types'

export const post: BlogPost = {
  slug: 'iac-drift-terraform-bicep-arm-cloudformation',
  title: "IaC Drift Across Terraform, Bicep, ARM, and CloudFormation: What's Different and What's the Same",
  category: 'Drift Detection',
  publishedDate: '2026-10-13',
  excerpt:
    'Terraform, CloudFormation, Bicep, and ARM each represent desired state differently, and drift manifests differently in each — but no single guide covers detection across all four, which is exactly the gap most multi-cloud teams fall into.',
  metaDescription:
    'How infrastructure drift manifests differently in Terraform, CloudFormation, Bicep, and ARM, and what a unified drift detection workflow looks like across all four IaC tools.',
  content: [
    {
      type: 'p',
      text: 'Infrastructure drift happens in every IaC tool, but it manifests differently depending on how that tool represents desired state. Terraform tracks a separate state file that can diverge from both the code and reality. CloudFormation has native drift detection, but with real limitations on what it can see. Bicep and ARM have no built-in continuous drift detection at all. A team running more than one of these — which is most teams working across Azure and AWS — ends up with a different blind spot for each tool, and no single view of drift across all of them.',
    },
    {
      type: 'h2',
      id: 'terraform-state-vs-live',
      text: 'Terraform: state file vs. live cloud state',
    },
    {
      type: 'p',
      text: "Terraform's model has three layers: your `.tf` configuration files, the state file that records what Terraform believes it deployed, and the actual live resources in your cloud account. Drift is a gap between the state file and live reality — and because Terraform only checks that gap when you explicitly run `terraform plan`, the gap can persist indefinitely between runs. A resource changed in the console diverges from state immediately, but nothing about that divergence is visible until the next plan.",
    },
    {
      type: 'h2',
      id: 'cloudformation-drift-detection-limits',
      text: "CloudFormation's native drift detection — and its limitations",
    },
    {
      type: 'p',
      text: "CloudFormation has a built-in drift detection feature that AWS added specifically because this is a well-known problem: you can trigger a drift check against a stack, and it will report which resources have changed outside of CloudFormation. That's a real advantage over Bicep and ARM. But it has real limits — drift detection has to be triggered manually or on a schedule (it's not continuous by default), it doesn't cover every resource type, and it can't tell you why a resource drifted or automatically reconcile it. It tells you something changed; the investigation and the fix are still manual.",
    },
    {
      type: 'h2',
      id: 'bicep-arm-no-native-detection',
      text: 'Bicep and ARM: no native continuous drift detection',
    },
    {
      type: 'p',
      text: 'Neither Bicep nor ARM templates have an equivalent to CloudFormation\'s drift detection feature. Azure will happily redeploy a Bicep template and either overwrite a manual change or, depending on the resource, leave it alone and let the mismatch persist silently — and there\'s no built-in Azure feature that proactively tells you which resources have diverged from their template definitions. For teams standardized on Bicep or ARM, this means drift is invisible unless something outside the native tooling is specifically watching for it.',
    },
    {
      type: 'h2',
      id: 'the-compounding-problem',
      text: 'The compounding problem for multi-tool, multi-cloud teams',
    },
    {
      type: 'p',
      text: "Most platform teams past a certain size aren't using one IaC tool exclusively — Terraform for AWS, Bicep for Azure, maybe a legacy CloudFormation stack nobody has migrated yet. Each tool has a different detection story, a different way of surfacing drift (or not surfacing it at all), and a different remediation workflow. That means the team either builds and maintains three separate drift-checking processes, or — far more commonly — only really watches the tool someone happened to prioritize, and the other two accumulate drift with nobody watching.",
    },
    {
      type: 'h2',
      id: 'own-the-gap',
      text: 'No single guide covers all four — that gap is worth naming directly',
    },
    {
      type: 'p',
      text: "Search for drift detection guidance and you'll find plenty of Terraform-specific content, a smaller amount on CloudFormation's native feature, and very little that treats Bicep or ARM drift as a first-class problem at all — let alone a guide that covers detection across all four tools in one place. That gap exists because most teams and most tooling vendors pick a lane: Terraform-first, or AWS-first, or Azure-first. Teams running genuinely mixed IaC don't get a unified answer from any of them.",
    },
    {
      type: 'h2',
      id: 'unified-detection-workflow',
      text: 'What a unified detection workflow looks like',
    },
    {
      type: 'p',
      text: "A unified workflow treats drift as a property of your live infrastructure relative to whatever source of truth defines it — Terraform state, a CloudFormation stack, or a Bicep/ARM template — and checks all of them the same way: continuously, not on a manual trigger, with the specific delta surfaced regardless of which tool originally deployed the resource. That means one dashboard shows drift across an AWS RDS instance managed by Terraform, an Azure Storage account defined in Bicep, and a legacy CloudFormation stack side by side, instead of three separate places to check — or worse, two of the three with no detection at all.",
    },
  ],
  faqs: [
    {
      q: 'What is IaC drift?',
      a: 'IaC drift is any gap between what your infrastructure-as-code definition says should be deployed — in Terraform, Bicep, ARM, or CloudFormation — and what is actually running. It happens when resources change outside of the IaC tool\'s normal deploy path.',
    },
    {
      q: 'Does CloudFormation detect drift automatically?',
      a: 'CloudFormation has a native drift detection feature, but it must be triggered manually or on a schedule — it is not continuous by default, doesn\'t cover every resource type, and reports that drift exists without diagnosing why or offering automatic reconciliation.',
    },
    {
      q: 'How is Bicep drift different from Terraform drift?',
      a: 'Terraform tracks a separate state file and can detect drift against it via terraform plan. Bicep has no equivalent state file or native drift detection feature at all — Azure will redeploy a template without proactively telling you which live resources have diverged from it.',
    },
    {
      q: 'How do I detect ARM template drift in Azure?',
      a: 'ARM has no built-in continuous drift detection. Detecting drift means comparing the live resource configuration against the ARM template definition on an ongoing basis using a tool built for that purpose, since Azure itself won\'t proactively flag the divergence.',
    },
    {
      q: 'How do I manage drift across multiple IaC tools?',
      a: 'Use a single detection workflow that checks live cloud state against whichever source of truth defines each resource — Terraform state, a CloudFormation stack, or a Bicep/ARM template — continuously and in one place, rather than relying on each tool\'s own (often absent) native detection separately.',
    },
  ],
  ctaHeading: 'One dashboard for drift, regardless of IaC tool',
  ctaText:
    'Cloud Decoded monitors drift across Terraform, Bicep, ARM, and CloudFormation in a single dashboard — one place regardless of which IaC tool your team uses.',
  ctaLinkHref: '/#monitor',
  ctaLinkLabel: 'See what Cloud Decoded monitors',
  relatedSlugs: ['terraform-drift-detection', 'multi-cloud-infrastructure-monitoring'],
}
