import type { BlogPost } from '../types'

export const post: BlogPost = {
  slug: 'aws-iam-misconfiguration',
  title: 'AWS IAM Misconfiguration: The Most Common Mistakes and How to Catch Them',
  category: 'Misconfiguration',
  publishedDate: '2026-09-25',
  excerpt:
    'The most dangerous AWS IAM misconfiguration is a wildcard action on a production role — but unused access keys, missing resource constraints, and inline policies all compound into the same problem: nobody knows exactly what a role can actually do.',
  metaDescription:
    'The AWS IAM misconfiguration hierarchy from most to least dangerous, what each one enables an attacker to do, and how to audit IAM permissions across your AWS accounts.',
  content: [
    {
      type: 'p',
      text: 'The most dangerous AWS IAM misconfiguration is a wildcard action (`"Action": "*"` or a service-level wildcard like `"s3:*"`) attached to a production role, because it collapses the entire point of IAM — least privilege — into a single overpermissive grant. Behind that, missing resource constraints, cross-account trust policy errors, unused access keys, and inline policies each compound the same underlying problem: nobody in the organization has a clear, current picture of what every role can actually do, which means nobody notices when that picture gets worse.',
    },
    {
      type: 'h2',
      id: 'the-hierarchy',
      text: 'The IAM misconfiguration hierarchy, most to least dangerous',
    },
    {
      type: 'h3',
      id: 'wildcard-actions',
      text: '1. Wildcard actions on production roles',
    },
    {
      type: 'p',
      text: 'What it looks like: a policy statement with `"Action": "*"` and `"Resource": "*"`, or a narrower but still broad grant like `"Action": "s3:*"` covering every S3 operation instead of the specific ones the role actually needs.',
    },
    {
      type: 'p',
      text: 'What it enables: if the credentials for that role are ever compromised — a leaked key, an exploited application vulnerability that lets an attacker assume the role — the attacker has the full scope of that wildcard, not just the narrow operation the role was actually built for. A role that only needs `s3:GetObject` on one bucket but is granted `s3:*` on all resources turns a single leaked credential into full account-wide data access.',
    },
    {
      type: 'p',
      text: 'Fix: replace wildcards with the specific actions the role\'s code path actually calls, and scope the `Resource` field to the specific ARNs it needs — not `*`. AWS Access Analyzer can generate a least-privilege policy based on a role\'s actual CloudTrail activity, which is the fastest path to a scoped policy for an existing role.',
    },
    {
      type: 'h3',
      id: 'missing-resource-constraints',
      text: '2. Missing resource constraints on write permissions',
    },
    {
      type: 'p',
      text: 'What it looks like: an action is scoped correctly (`s3:PutObject`, not `s3:*`) but the `Resource` field is still `*`, so the role can write to any bucket in the account instead of the one it\'s meant to.',
    },
    {
      type: 'p',
      text: "What it enables: a scoped action with an unscoped resource is still a broad grant — a role that should only write to one application bucket can instead overwrite or delete objects in any bucket in the account, including ones it has no legitimate reason to touch.",
    },
    {
      type: 'p',
      text: 'Fix: scope the `Resource` field to specific ARNs or, at minimum, a resource-name prefix pattern, so a write permission only applies to the resources the role is actually meant to manage.',
    },
    {
      type: 'h3',
      id: 'cross-account-trust-errors',
      text: '3. Cross-account trust policy errors',
    },
    {
      type: 'p',
      text: 'What it looks like: a role\'s trust policy specifies a `Principal` that\'s broader than intended — an entire AWS account instead of a specific role ARN within it, or missing an `ExternalId` condition on a role meant to be assumed by a third party.',
    },
    {
      type: 'p',
      text: 'What it enables: any principal in the trusted account can assume the role, not just the specific service or role that was supposed to — turning a narrow cross-account integration into a much wider trust boundary than intended.',
    },
    {
      type: 'p',
      text: 'Fix: scope the trust policy\'s `Principal` to the exact role ARN that should be allowed to assume it, and require an `ExternalId` condition for any third-party cross-account access, which prevents the "confused deputy" problem where a different customer of the same third party could otherwise assume your role.',
    },
    {
      type: 'h3',
      id: 'unused-access-keys',
      text: '4. Unused access keys over 90 days',
    },
    {
      type: 'p',
      text: 'What it looks like: a long-lived IAM user access key that shows no API activity in the credential report for 90 or more days.',
    },
    {
      type: 'p',
      text: "What it enables: an old, unused key is a live credential with no operational reason to still exist — every day it remains active is a day it can be leaked, phished, or found in an old config file with no legitimate traffic pattern to make the misuse stand out.",
    },
    {
      type: 'p',
      text: 'Fix: pull the IAM credential report on a recurring basis, flag any key with no activity in 90 days, and deactivate (not immediately delete, in case something breaks) before removing it entirely. Where possible, replace long-lived IAM user keys with roles and temporary credentials instead.',
    },
    {
      type: 'h3',
      id: 'inline-policies',
      text: '5. Inline policies instead of managed policies',
    },
    {
      type: 'p',
      text: 'What it looks like: permissions attached directly to a role or user as an inline policy instead of a standalone managed policy that can be attached to multiple identities and reviewed independently.',
    },
    {
      type: 'p',
      text: "What it enables: nothing directly dangerous on its own, but inline policies are invisible to any review process that only checks managed policies, and they can't be versioned, reused, or audited the same way — which means they're where permission sprawl accumulates unnoticed.",
    },
    {
      type: 'p',
      text: 'Fix: migrate inline policies to managed policies (customer-managed, not just AWS-managed) so they show up in policy inventories, can be versioned, and can be attached consistently across roles that need the same permission set.',
    },
    {
      type: 'h3',
      id: 'propagation-delay',
      text: '6. Managed identity not propagated before first use',
    },
    {
      type: 'p',
      text: 'What it looks like: a deploy step that creates or updates an IAM role and immediately tries to use it, failing intermittently with an access-denied error that resolves itself on retry a few seconds later.',
    },
    {
      type: 'p',
      text: "What it enables: this isn't a security misconfiguration, it's a reliability one, but it's common enough to include here — IAM is eventually consistent, and a role's new permissions can take several seconds to propagate across AWS's infrastructure, which shows up as a flaky, hard-to-reproduce deploy failure if the pipeline doesn't account for it.",
    },
    {
      type: 'p',
      text: 'Fix: add a short retry-with-backoff around the first use of a newly created or modified role in deploy scripts, rather than treating the intermittent failure as a one-off flake to ignore.',
    },
    {
      type: 'h2',
      id: 'auditing-iam-across-accounts',
      text: 'How to audit IAM permissions across your AWS accounts',
    },
    {
      type: 'p',
      text: 'AWS IAM Access Analyzer is the right starting point — it identifies resources shared with external entities and can generate least-privilege policies from a role\'s actual CloudTrail usage. For a full inventory, pull the IAM credential report (for unused keys) and the account authorization details (for the full policy set across every role and user) on a recurring schedule, not as a one-time exercise, since new roles and policies are created continuously as teams ship.',
    },
    {
      type: 'h2',
      id: 'least-privilege',
      text: 'What least privilege means in practice — and how to enforce it',
    },
    {
      type: 'p',
      text: "Least privilege means a role can do exactly what its function requires and nothing more — not \"broad access that happens to work,\" which is how most overpermissive roles get created in the first place, usually under deadline pressure. Enforcing it in practice means starting new roles with a narrow, explicit permission set and adding to it only as a specific, justified need arises, rather than starting broad and meaning to narrow it down later — because later rarely comes, and the role ships to production exactly as overpermissive as it was on day one.",
    },
  ],
  faqs: [
    {
      q: 'What is an IAM misconfiguration?',
      a: 'An IAM misconfiguration is a permission grant that is broader than what a role or user actually needs — wildcard actions, unscoped resource fields, overly broad cross-account trust, unused long-lived credentials, or permissions that are hard to audit because they\'re defined inline instead of as managed policies.',
    },
    {
      q: 'What is the most dangerous AWS IAM mistake?',
      a: 'A wildcard action (like "Action": "*") attached to a production role. If the credentials for that role are ever compromised, the attacker inherits the full scope of the wildcard rather than the narrow set of operations the role was actually built to perform.',
    },
    {
      q: 'How do I audit IAM permissions across my AWS accounts?',
      a: 'Use AWS IAM Access Analyzer to identify externally shared resources and generate least-privilege policies from actual CloudTrail usage, and pull the IAM credential report and account authorization details on a recurring schedule to catch unused keys and permission sprawl as they accumulate.',
    },
    {
      q: 'How do I detect unused IAM access keys?',
      a: 'Pull the IAM credential report, which lists the last-used date for every access key in the account, and flag any key with no API activity in 90 or more days for deactivation and eventual removal.',
    },
    {
      q: 'What is least privilege and how do I enforce it in AWS IAM?',
      a: 'Least privilege means a role or user can perform exactly the actions their function requires, on exactly the resources it requires, and nothing broader. Enforce it by starting new roles with a narrow permission set and expanding only for specific, justified needs — not by starting broad and planning to narrow it later.',
    },
  ],
  ctaHeading: 'Catch overprivileged IAM before it ships',
  ctaText:
    'Cloud Decoded continuously checks your IAM roles and policies against your Terraform and CloudFormation definitions — flagging drift and overprivileged configurations as they appear.',
  ctaLinkHref: '/#monitor',
  ctaLinkLabel: 'See what Cloud Decoded monitors',
  relatedSlugs: ['cloud-misconfiguration-detection', 'azure-nsg-misconfiguration'],
}
