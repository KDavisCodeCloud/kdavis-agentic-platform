# Cloud Decoded — What Access Does Cloud Decoded Need, and Why

This page names the exact actions each agent's connected credential can
take — grounded directly in the code, not a general description. It's
the manifest produced by a live execution-path audit of all 11 agents
(2026-09-17): every AWS API call and every Azure ARM call any agent
makes, read or write, cited to the exact file. If an action isn't listed
here, no agent calls it — your role/Service Principal doesn't need it.

Two independent guarantees, both explained in full on the
[security page](https://theclouddecoded.com/security):

1. **Nothing executes without your approval.** Every agent pauses at a
   human approval gate before any write happens — this is a fact about
   the code (verified: `POST /incidents/{id}/approve` is the only path
   to execution for all 11 agents), not a setting you could turn off.
2. **Read-Only mode.** For the two agents that call AWS/Azure directly
   to change something (05 — IAM Policy Minimization, 06 — FinOps), you
   can additionally restrict the *connection itself* to read-only in
   Settings → Connections. In Read-Only mode, no write API call is ever
   attempted, regardless of what you approve — the incident card steers
   you to manual resolution instead.

---

## Per-agent access, in plain language

| # | Agent | Reads | Writes |
|---|-------|-------|--------|
| 01 | CI/CD Pipeline Triage | Workflow run logs (GitHub/Azure DevOps) | Re-runs a failed workflow/pipeline, posts a PR comment |
| 02 | Kubernetes Alert Remediation | Deployment/HPA state (your cluster's own API) | Patches a deployment's resources, applies an HPA, opens a GitOps PR |
| 03 | PR Review | PR file diffs (GitHub) | Posts a review comment — never merges or blocks |
| 04 | Legacy Code & Infra Migration | — | Opens a migration PR, files a tracking issue |
| 05 | IAM Policy Minimization | IAM policy versions, role/instance-profile/Lambda metadata (AWS); role assignments, managed identities (Azure) | Publishes a new minimized IAM policy version, or a new Azure role assignment |
| 06 | FinOps Cost Optimization | Cost and usage data (AWS Cost Explorer, Azure Cost Management) | Stops idle EC2 instances, deletes unattached EBS volumes/Elastic IPs, deallocates idle Azure VMs, deletes unattached Azure disks |
| 07 | Interactive Runbook Automation | Whatever the runbook itself reads | Whatever the runbook itself does (shell/HTTP/kubectl steps you defined) — never AWS/Azure APIs directly |
| 08 | Drift Detection & Auto-Correction | CloudFormation stack resources, S3 bucket config, security groups, route tables (AWS); App Service/Blob Storage/NSG/route table config (Azure); live cluster state (Kubernetes) | Opens a remediation PR, or applies a Kubernetes manifest directly — never a direct AWS/Azure API write |
| 09 | Onboarding & On-Call Buddy | Your repo's docs/runbooks (GitHub search) | Opens a knowledge-gap issue, posts a Slack message |
| 10 | Dependency & Vulnerability Patching | Manifest files (GitHub/Azure DevOps), public OSV.dev vulnerability data | Opens a patch PR, files a vulnerability tracking issue |
| 11 | Cloud Resource Health Monitoring | Nothing beyond the alert payload itself | Opens an investigation PR or files an issue — never a live cloud API call |

**Only agents 05 and 06 ever call an AWS or Azure API to change
something.** Every other agent's write path is a pull request, a git
commit, or (agent 02/08) a call to your own Kubernetes cluster's API —
none of those are affected by the Read-Only/Execute connection mode
described below, which is scoped to AWS/Azure specifically.

---

## AWS setup

### Read-Only mode

Attach AWS's own managed **`ReadOnlyAccess`** policy to the role you
create for Cloud Decoded. It's broader than strictly necessary but
requires no maintenance as this manifest evolves. If you'd rather grant
exactly what's used today, attach this instead:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iam:ListPolicyVersions",
        "iam:GetPolicyVersion",
        "iam:ListEntitiesForPolicy",
        "iam:ListInstanceProfiles",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
        "iam:GetRolePolicy",
        "lambda:ListFunctions",
        "ce:GetCostAndUsage",
        "cloudformation:DescribeStackResources",
        "s3:GetBucketVersioning",
        "s3:GetEncryptionConfiguration",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketPolicy",
        "s3:GetReplicationConfiguration",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeRouteTables"
      ],
      "Resource": "*"
    }
  ]
}
```

### Execute mode

The exact policy your Connections page already generates for you when
you start AWS role setup (`core/workspace_credentials.py`'s
`build_permissions_policy()`) — the read actions above, plus:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iam:CreatePolicyVersion",
        "iam:DeletePolicyVersion",
        "ec2:StopInstances",
        "ec2:DeleteVolume",
        "ec2:ReleaseAddress"
      ],
      "Resource": "*"
    }
  ]
}
```

`iam:DeletePolicyVersion` is only ever called when a policy has already
hit AWS's 5-version cap — Agent 05 deletes the single oldest non-default
version before publishing the new one, never anything you didn't just
approve. The role is assumed via `sts:AssumeRole` with an external ID
(never a stored access key) — see the trust policy your Connections page
generates alongside this.

---

## Azure setup

### Read-Only mode

Assign the built-in **`Reader`** role, scoped to the resource group(s)
you want Cloud Decoded to see. If you'd rather use a custom role scoped
exactly to what's read today, use this (fill in your subscription and
resource group):

```json
{
  "Name": "Cloud Decoded – Read Only",
  "IsCustom": true,
  "Description": "Read-only access for Cloud Decoded's IAM/FinOps/Drift agents.",
  "Actions": [
    "Microsoft.Authorization/roleAssignments/read",
    "Microsoft.ManagedIdentity/userAssignedIdentities/read",
    "Microsoft.CostManagement/query/action",
    "Microsoft.Web/sites/read",
    "Microsoft.Storage/storageAccounts/read",
    "Microsoft.Network/networkSecurityGroups/read",
    "Microsoft.Network/routeTables/read"
  ],
  "NotActions": [],
  "AssignableScopes": [
    "/subscriptions/{subscriptionId}/resourceGroups/{resourceGroup}"
  ]
}
```

(App Service file/config content is read via the site's own Kudu
endpoint, which authenticates against the App Service's own publish
scope rather than a separate ARM RBAC action — `Microsoft.Web/sites/read`
covers the ARM-level discovery Agent 08 also needs.)

### Execute mode

Adds the two write actions agents 05 and 06 call — role-assignment
minimization and idle-VM/disk cleanup:

```json
{
  "Name": "Cloud Decoded – Execute",
  "IsCustom": true,
  "Description": "Read + write access for Cloud Decoded's IAM/FinOps agents.",
  "Actions": [
    "Microsoft.Authorization/roleAssignments/read",
    "Microsoft.Authorization/roleAssignments/write",
    "Microsoft.ManagedIdentity/userAssignedIdentities/read",
    "Microsoft.CostManagement/query/action",
    "Microsoft.Compute/virtualMachines/deallocate/action",
    "Microsoft.Compute/disks/delete",
    "Microsoft.Web/sites/read",
    "Microsoft.Storage/storageAccounts/read",
    "Microsoft.Network/networkSecurityGroups/read",
    "Microsoft.Network/routeTables/read"
  ],
  "NotActions": [],
  "AssignableScopes": [
    "/subscriptions/{subscriptionId}/resourceGroups/{resourceGroup}"
  ]
}
```

If a custom role isn't an option in your organization, the built-in
**`Contributor`** role (scoped to the same resource group) covers
everything above, plus more than is strictly needed — same tradeoff as
AWS's `ReadOnlyAccess`.

The Service Principal's client secret is stored encrypted and decrypted
only for the duration of the call that needs it — see the security page
for the full model.

---

## Changing your mode later

Switch a connection between Read-Only and Execute any time in
Settings → Connections — takes effect immediately, no reconnection
required. Switching to Execute shows the required-actions list again
with a copy button. Nothing here changes the human-approval requirement
described at the top of this page; Read-Only mode is an *additional*
restriction on top of it, not a replacement for it.
