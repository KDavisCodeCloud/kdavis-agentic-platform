import type { BlogPost } from '../types'

export const post: BlogPost = {
  slug: 'terraform-apply-failed-diagnosis',
  title: 'Terraform Apply Failed: How to Diagnose and Fix Deploy Errors Fast',
  category: 'Incident Response',
  publishedDate: '2026-09-18',
  excerpt:
    'A failed terraform apply almost always falls into one of six failure classes — naming conflicts, IAM permission errors, capacity limits, state locks, partial applies, or provider auth failures. Here is how to identify which one you have and fix it.',
  metaDescription:
    'The six most common reasons terraform apply fails — naming conflicts, IAM errors, capacity limits, state locks, partial applies, provider auth — with exact remediation steps for each.',
  content: [
    {
      type: 'p',
      text: 'A failed `terraform apply` almost always falls into one of six failure classes: a resource naming conflict, an IAM permission error, unavailable capacity in an availability zone, a leftover state lock, a partial apply that left infrastructure half-deployed, or a provider authentication failure. Identifying which class you\'re looking at from the error message is the fast path to a fix — each one has a distinct signature and a specific remediation, and guessing wastes more time than reading the error carefully once.',
    },
    {
      type: 'h2',
      id: 'naming-conflict',
      text: '1. Resource naming conflict',
    },
    {
      type: 'p',
      text: 'What it looks like: `Error: creating S3 Bucket: BucketAlreadyExists` or `Error: A resource with the ID ... already exists`. Terraform tried to create a resource with a name or identifier that already exists in the account or region — either because someone created it manually outside Terraform, or because two workspaces are trying to manage overlapping names.',
    },
    {
      type: 'p',
      text: 'Why it happens: globally unique names (S3 buckets, some DNS zones) collide across unrelated accounts, or a resource was created out-of-band and never imported into state.',
    },
    {
      type: 'p',
      text: 'Fix: if the resource already exists and should be managed by this configuration, run `terraform import` to bring it under management instead of trying to create it fresh. If it\'s a genuine naming collision, rename the resource in your configuration to something unique — for S3 buckets specifically, that usually means adding an account ID or environment suffix to the bucket name.',
    },
    {
      type: 'h2',
      id: 'iam-permission-denied',
      text: '2. IAM permission denied during deploy',
    },
    {
      type: 'p',
      text: 'What it looks like: `Error: AccessDenied: User: arn:aws:iam::... is not authorized to perform: ec2:CreateSecurityGroup` or an Azure `AuthorizationFailed` error referencing a specific action.',
    },
    {
      type: 'p',
      text: "Why it happens: the identity running Terraform — a CI/CD service principal, an assumed role — doesn't have the specific permission the apply needs. This is especially common right after adding a new resource type to a configuration, since the deploy identity's policy was scoped to the old resource set.",
    },
    {
      type: 'p',
      text: 'Fix: read the exact action in the error (`ec2:CreateSecurityGroup`, `Microsoft.Network/networkSecurityGroups/write`) and add it to the deploy identity\'s IAM policy or Azure RBAC role — scoped to the specific resource type and, where possible, the specific resource group or account, not a blanket `*` grant to make the error go away faster.',
    },
    {
      type: 'h2',
      id: 'capacity-unavailable',
      text: '3. Capacity unavailable in an availability zone',
    },
    {
      type: 'p',
      text: 'What it looks like: `Error: InsufficientInstanceCapacity` on AWS, or an Azure `SkuNotAvailable` error for a specific VM size and region combination.',
    },
    {
      type: 'p',
      text: "Why it happens: the specific instance type or VM SKU you requested is temporarily out of capacity in that availability zone — this is a cloud-provider-side constraint, not a configuration error, and it's more common for larger or GPU-backed instance types.",
    },
    {
      type: 'p',
      text: 'Fix: retry in a different availability zone within the same region (add or change the `availability_zone` argument), fall back to a different but comparable instance type, or retry after a delay if the workload can tolerate it — capacity constraints are usually temporary.',
    },
    {
      type: 'h2',
      id: 'state-lock',
      text: '4. State lock from a previous run',
    },
    {
      type: 'p',
      text: 'What it looks like: `Error: Error acquiring the state lock` with a lock ID, "who" field, and a "created" timestamp.',
    },
    {
      type: 'p',
      text: 'Why it happens: a previous `terraform apply` or `plan` was interrupted — a CI job was cancelled, a laptop lost connectivity, a process was killed — without releasing the lock it took on the state file (commonly held in a DynamoDB table or an Azure Storage blob lease).',
    },
    {
      type: 'p',
      text: 'Fix: confirm no other apply is actually still running (check the "created" timestamp and who/what field in the error), then run `terraform force-unlock <lock-id>`. Never force-unlock while a real apply might still be in progress — that can corrupt state if two applies run concurrently.',
    },
    {
      type: 'h2',
      id: 'partial-apply',
      text: '5. Partial apply leaving infrastructure half-deployed',
    },
    {
      type: 'p',
      text: 'What it looks like: the apply exits with an error partway through, and the plan on your next run shows some resources already created and others still pending — for example, a VPC and subnets exist, but the route tables that should connect them don\'t yet.',
    },
    {
      type: 'p',
      text: "Why it happens: a mid-apply failure — a transient API error, a hit rate limit, a timeout — after some resources succeeded but before the whole graph completed. Terraform's state file accurately reflects the partial reality, but the infrastructure itself is incomplete and may not function correctly.",
    },
    {
      type: 'p',
      text: 'Fix: run `terraform plan` first to see exactly what\'s missing before touching anything manually. In most cases, simply running `terraform apply` again completes the remaining resources — Terraform is designed to be safely re-run against partial state. Avoid manually creating the missing pieces in the console; that reintroduces drift on top of an already-partial deploy.',
    },
    {
      type: 'h2',
      id: 'provider-auth-failure',
      text: '6. Provider authentication failure',
    },
    {
      type: 'p',
      text: 'What it looks like: `Error: error configuring Terraform AWS Provider: no valid credential sources found` or an Azure `Error: building AzureRM Client: obtain a token` error.',
    },
    {
      type: 'p',
      text: "Why it happens: expired or missing credentials for the provider — an OIDC token that expired mid-run, an environment variable that wasn't set in the CI runner, or a service principal secret that rotated without updating the pipeline.",
    },
    {
      type: 'p',
      text: 'Fix: confirm the credential source Terraform is actually using (environment variables, a shared credentials file, an assumed role, OIDC federation) and verify it\'s valid and current. In CI/CD specifically, check whether a recent secret rotation or OIDC trust policy change is the actual root cause before assuming it\'s a one-off flake.',
    },
    {
      type: 'h2',
      id: 'preventing-failures-in-cicd',
      text: 'How to prevent Terraform apply failures in CI/CD',
    },
    {
      type: 'p',
      text: 'Run `terraform plan` as a required, human-reviewed step before every apply so naming conflicts and permission gaps surface before they hit production. Keep deploy-identity IAM policies scoped tightly but reviewed regularly, so new resource types don\'t silently fail on missing permissions. And treat state locks and partial applies as expected operational events, not emergencies — a documented unlock and re-apply procedure turns a 45-minute panic into a 5-minute fix.',
    },
  ],
  faqs: [
    {
      q: 'Why did my Terraform apply fail?',
      a: 'Terraform apply failures almost always fall into six classes: a resource naming conflict, an IAM permission error, unavailable cloud capacity, a leftover state lock, a partial apply from a previous interrupted run, or a provider authentication failure. The exact error message tells you which one you have.',
    },
    {
      q: 'How do I fix a Terraform state lock?',
      a: 'First confirm no other apply or plan is genuinely still running by checking the "created" timestamp and "who" field in the lock error. If it\'s truly stale, run terraform force-unlock with the lock ID shown in the error. Never force-unlock while another apply might actually be in progress.',
    },
    {
      q: 'What happens when Terraform apply fails halfway through?',
      a: 'Terraform\'s state file accurately records whatever resources were successfully created before the failure, but the infrastructure is incomplete. Run terraform plan to see exactly what\'s missing, then re-run terraform apply — it is designed to safely complete a partial deployment rather than starting over.',
    },
    {
      q: 'How do I retry a failed Terraform resource without re-creating everything?',
      a: 'Just re-run terraform apply. Terraform only acts on the difference between state and your configuration, so resources that already applied successfully are left alone, and only the resources that failed or are still pending get created.',
    },
    {
      q: 'How do I prevent Terraform apply failures in CI/CD?',
      a: 'Require a reviewed terraform plan before every apply, keep the CI/CD deploy identity\'s IAM permissions scoped but current as new resource types get added, and have a documented state-lock and partial-apply recovery procedure so those failures are routine to resolve instead of emergencies.',
    },
  ],
  ctaHeading: 'Skip the log-reading when a deploy fails',
  ctaText:
    'When a deploy fails in your connected pipeline, Cloud Decoded surfaces the failure class and specific fix options automatically — no manual log-reading required.',
  ctaLinkHref: '/#how-it-works',
  ctaLinkLabel: 'See how Cloud Decoded works',
  relatedSlugs: ['terraform-drift-detection', 'reduce-mttr-cloud-infrastructure'],
}
