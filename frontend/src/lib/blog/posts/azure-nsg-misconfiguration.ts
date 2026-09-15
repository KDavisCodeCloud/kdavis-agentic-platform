import type { BlogPost } from '../types'

export const post: BlogPost = {
  slug: 'azure-nsg-misconfiguration',
  title: 'Azure NSG Misconfiguration: How to Find and Fix Rules That Block or Expose Too Much',
  category: 'Misconfiguration',
  publishedDate: '2026-10-06',
  excerpt:
    'Misconfigured Azure NSG rules either expose management ports to the internet or silently block traffic between subnets that should be able to reach each other. Here is how rule evaluation actually works and how to audit it at scale.',
  metaDescription:
    'How Azure NSG rule evaluation works, the five most dangerous NSG misconfigurations, and how to audit network security group rules across a subscription.',
  content: [
    {
      type: 'p',
      text: 'A misconfigured Azure NSG rule either exposes something to the internet that should be private, or blocks traffic between resources that should be able to reach each other. Both failure modes come from the same root cause: NSG rules are evaluated by priority order with a default-deny fallback, and a rule added without understanding that ordering can silently override an intended allow, or silently open a path nobody meant to open. Finding these rules means auditing evaluated behavior, not just reading the rule list.',
    },
    {
      type: 'h2',
      id: 'how-rule-evaluation-works',
      text: 'How NSG rule evaluation actually works',
    },
    {
      type: 'p',
      text: "Every Azure NSG evaluates rules in priority order, from lowest number to highest (100 is evaluated before 200), and stops at the first rule that matches the traffic. If no custom rule matches, Azure falls through to the default rules, which deny all inbound traffic from outside the virtual network and allow all outbound. This means two things that catch people off guard: a low-priority-number deny rule can silently block traffic that a higher-priority-number allow rule further down the list was meant to permit, and a rule you assume is redundant with the defaults might actually be the only thing permitting traffic that would otherwise fall through to deny.",
    },
    {
      type: 'h2',
      id: 'five-dangerous-nsg-misconfigurations',
      text: 'The five most dangerous NSG misconfigurations',
    },
    {
      type: 'ul',
      items: [
        'RDP/SSH open to 0.0.0.0/0 — an inbound rule allowing TCP 3389 or TCP 22 from "Any" source instead of a bastion host, VPN range, or specific IP. This is the single most commonly exploited NSG misconfiguration and the first thing automated scanners look for.',
        'Missing rules blocking inter-subnet traffic — two subnets that should communicate (an app tier and a database tier) have no explicit allow rule, and the NSG default-deny silently blocks it. This shows up as a connectivity failure that looks like an application bug, not a network config issue.',
        'Conflicting allow/deny rules — a lower-priority-number deny rule unintentionally matches traffic a higher-priority-number allow rule further down was supposed to permit, because the priority numbers were assigned without full attention to how specific each rule\'s source/destination/port scope is.',
        'Management ports exposed on production VMs — RDP or SSH left reachable on a VM that should only ever be managed through a jump box or Azure Bastion, often because the rule was added for one-time troubleshooting and never removed.',
        'Missing outbound rules for dependent services — an application VM can\'t reach an external API or a dependent Azure service because outbound rules are more restrictive than the defaults assume, causing intermittent failures that are hard to trace back to the network layer.',
      ],
    },
    {
      type: 'h2',
      id: 'auditing-nsgs-across-a-subscription',
      text: 'How to audit NSGs across a subscription',
    },
    {
      type: 'p',
      text: "Reviewing NSGs one at a time in the Azure portal doesn't scale past a handful of virtual networks. A real audit needs to evaluate effective rules — what actually applies after priority ordering and any NSGs associated at both the subnet and NIC level — across every NSG in the subscription at once, flagging any rule that allows inbound traffic from an unscoped source on a sensitive port. Azure's own Network Watcher includes an effective security rules view for exactly this reason; it's worth using per-VM before assuming a rule list is complete, because a NIC-level NSG can silently override or combine with a subnet-level one in ways the subnet view alone won't show.",
    },
    {
      type: 'h2',
      id: 'drift-from-bicep-arm',
      text: 'How NSG rules drift from Bicep and ARM definitions',
    },
    {
      type: 'p',
      text: 'The same drift pattern that affects Terraform-managed resources affects NSGs defined in Bicep or ARM templates: a rule added directly in the Azure portal during an incident — to open emergency access, or to unblock a debugging session — never gets backported into the template. From that point forward, every redeploy either fights with the manual rule or, worse, silently overwrites it and reintroduces whatever problem the manual change was fixing. Bicep and ARM have no native continuous drift detection of their own, so this kind of gap can persist indefinitely unless something else is watching for it.',
    },
    {
      type: 'h2',
      id: 'real-examples',
      text: 'Real examples',
    },
    {
      type: 'ul',
      items: [
        'RDP port 3389 open from emergency access never revoked — a support engineer needs temporary RDP access to a production VM during an incident, opens it to their own IP, and either the rule is left as "Any" by mistake or the specific IP access is never removed once the incident closes.',
        'An NSG rule added for testing blocking a production dependency — a deny rule added to isolate a resource during a load test gets a lower priority number than an existing allow rule, and inadvertently blocks legitimate production traffic that happens to match the same scope once the test rule is forgotten and left in place.',
      ],
    },
    {
      type: 'h2',
      id: 'cis-benchmark-requirements',
      text: 'CIS benchmark requirements for Azure NSGs',
    },
    {
      type: 'p',
      text: 'The CIS Microsoft Azure Foundations Benchmark includes explicit checks against exactly this class of misconfiguration: no NSG rule should allow unrestricted inbound access on RDP (3389) or SSH (22) from any source, and NSG flow logs should be enabled for visibility into what traffic rules are actually permitting in practice. Failing either check is a common, specific finding in SOC 2 and Azure security assessments — and both map directly to the "RDP/SSH open" and "management ports exposed" misconfigurations above.',
    },
  ],
  faqs: [
    {
      q: 'What is an Azure NSG misconfiguration?',
      a: 'An NSG misconfiguration is a network security group rule that either exposes a resource to more traffic than intended — like RDP or SSH open to the internet — or blocks legitimate traffic between resources that should be able to communicate, usually due to rule priority ordering or a missing rule.',
    },
    {
      q: 'How do I find open RDP/SSH rules in Azure?',
      a: 'Review effective security rules — not just the raw rule list — for every NSG in a subscription, checking for inbound rules on TCP 3389 or TCP 22 with a source of "Any" or 0.0.0.0/0. Azure Network Watcher\'s effective security rules view shows what actually applies after subnet- and NIC-level NSGs combine.',
    },
    {
      q: 'How do NSG rules get out of sync with my IaC?',
      a: 'A rule added directly in the Azure portal — often during an incident for emergency access or debugging — never gets backported into the Bicep or ARM template that\'s supposed to define the NSG, so the live rule set and the IaC definition drift apart until something explicitly reconciles them.',
    },
    {
      q: 'What are the CIS benchmark requirements for Azure NSGs?',
      a: 'The CIS Microsoft Azure Foundations Benchmark requires that no NSG rule allow unrestricted inbound access on RDP (3389) or SSH (22) from any source, and that NSG flow logs be enabled for network traffic visibility.',
    },
    {
      q: 'How do I audit NSG rules across multiple subscriptions?',
      a: 'Evaluate effective rules — accounting for priority order and both subnet- and NIC-level NSG associations — across every NSG in every subscription at once, rather than reviewing rule lists one NSG at a time in the portal, which doesn\'t scale and misses NIC-level overrides.',
    },
  ],
  ctaHeading: 'Catch NSG drift before it becomes an exposure',
  ctaText:
    'Cloud Decoded monitors your NSG rules continuously against your IaC definitions — surfacing exposures and blocked traffic before they cause an incident or a compliance finding.',
  ctaLinkHref: '/#monitor',
  ctaLinkLabel: 'See what Cloud Decoded monitors',
  relatedSlugs: ['cloud-misconfiguration-detection', 'cloud-misconfiguration-compliance-findings'],
}
