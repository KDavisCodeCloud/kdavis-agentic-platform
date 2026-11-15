"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Public demo sandbox (24-gap-closure build, Phase 6). Backs GET /demo
(api/routes/demo.py) -- an unauthenticated visitor gets a scoped,
time-limited session in ONE demo workspace. Since migration 059 each
session owns its own copy of the 8 synthetic incidents
(incidents.demo_session_id), and every demo-reachable incident query in
api/routes/incidents.py is filtered to it via demo_scope_clause, so
visitors never see or change each other's state.

This module is the single source of truth for the seed data --
scripts/seed_demo_incidents.py imports DEMO_INCIDENTS and
insert_demo_incidents from here rather than duplicating them (that
script is now a thin CLI wrapper for manual/local use; the live app
never shells out to it).

Structural guarantees that real execution is impossible from the demo
workspace -- all three hold independently; any one alone would already
be sufficient:
  1. No cloud credential column is ever populated here (every
     encrypted_*/aws_*/azure_*/github_*/k8s_* column on the workspaces
     row stays NULL).
  2. aws_connection_mode / azure_connection_mode are set to 'read_only'
     at creation -- api/routes/incidents.py's _reject_if_read_only_
     connection rejects any execute-mode action for agent_05/agent_06
     before it ever reaches an agent.
  3. Every seeded incident carries is_test = true (migration 046) --
     approve_incident short-circuits is_test rows to a simulated
     'executed' result before ever calling build_agent_credentials or
     an agent's resume(), regardless of connection mode.

Demo sessions are NOT workspace_members rows. api/middleware/auth.py's
_get_workspace_by_demo_session resolves an X-Demo-Session-Token to a
workspace dict with member_role='approver' hardcoded in Python (never
persisted) -- Approve/Reject/Resolve-manually work, but there is no real
membership, so nothing here ever appears in workspace_members.py's
Members list. That dependency is wired into ONLY a handful of
api/routes/incidents.py routes; Settings/Members/Billing/Connections
routes never learn to parse X-Demo-Session-Token at all, so a demo
session cannot authenticate there structurally, not by a role check
that could later be loosened by mistake -- see tests/test_demo_sandbox.py.
"""

import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

log = logging.getLogger(__name__)

# A raw demo session token always starts with this prefix -- mirrors
# frontend/src/lib/api.ts's own _DEMO_SESSION_TOKEN_PREFIX constant
# (kept in sync manually; frontend/src/lib/api.ts documents the pairing).
# request() there picks X-Demo-Session-Token by this shape, exactly like
# it already picks X-Workspace-Token vs Authorization: Bearer by the
# existing 'cd_ws_' prefix.
DEMO_SESSION_TOKEN_PREFIX = "cd_demo_"

DEMO_SESSION_TTL = timedelta(hours=24)
DEMO_RESET_INTERVAL_SECONDS = 30 * 60

# This app runs 4 --workers processes per deploy (api/main.py's lifespan
# starts one _demo_reset_loop per worker), so every reset pass is guarded
# by pg_try_advisory_xact_lock, same pattern as core/retention.py's
# _RETENTION_LOCK_ID -- without it all 4 workers would redundantly wipe
# and reseed the same demo workspace on every 30-minute tick. Distinct
# constant, never collides with any other advisory lock in this codebase
# (see the full list in those other modules' own _LOCK_ID constants).
_DEMO_RESET_LOCK_ID = 305_827_961

_DEMO_COMPANY_NAME = "Cloud Decoded Demo Workspace"

# One realistic-looking synthetic incident per row -- varied agents,
# severities, and resource names so a seeded console doesn't look
# obviously copy-pasted. agent_id values are real registered agents
# (not the "system_*" sentinels used by the connection-test button)
# specifically so the demo shows off actual per-agent remediation
# option copy, even though is_test=true still blocks real execution.
#
# Every remediation_options dict below MUST carry impact + docs_url --
# db.models.RemediationOption requires both with no default. Found live
# (2026-09-27, first real GET /incidents call against seeded demo data):
# this seed data was missing both fields entirely, silently 500ing every
# list_incidents/get_incident call for any workspace seeded from it --
# a pre-existing bug in the original scripts/seed_demo_incidents.py data,
# inherited when it moved here, never caught before because nothing had
# ever actually listed incidents against seeded rows through this exact
# Pydantic-validating code path until GET /demo's live verification.
#
# Gap-table #5-#9 (2026-11-14): the four target scenarios a buyer asks about
# (k8s CrashLoopBackOff/OOMKilled, Terraform security-group drift, a CI
# deploy failing on an IAM mismatch, S3 public exposure) plus four
# supporting ones. Each incident's evidence, each option's diff, blast
# radius and execution_log tell ONE consistent story -- the log an option
# streams describes that option's change on that resource, nothing generic.
# Blast-radius "reversible" must be true to life (RDS storage growth can't
# be undone, so it says so). tests/test_demo_sandbox.py validates every
# entry against the real response models.
DEMO_INCIDENTS = [
    # ── Target scenario: Kubernetes CrashLoopBackOff / OOMKilled ──────────
    {
        "agent_id": "agent_02_k8s_alert", "severity": "critical",
        "resource_name": "checkout-service", "cloud_provider": "aws",
        "parsed_error": (
            "checkout-service pods are in CrashLoopBackOff: OOMKilled 5 times in 11 minutes. "
            "Memory limit is 512Mi; working set climbs to the limit within ~2 minutes of start "
            "since v2.14.0 was deployed."
        ),
        "evidence": [
            {"kind": "kubectl", "title": "kubectl get pods -n payments -l app=checkout-service", "lines": [
                "NAME                                READY   STATUS             RESTARTS      AGE",
                "checkout-service-7f9d8c6b5-2xkqp    0/1     CrashLoopBackOff   5 (38s ago)   11m",
                "checkout-service-7f9d8c6b5-8hn4w    0/1     CrashLoopBackOff   5 (52s ago)   11m",
                "checkout-service-7f9d8c6b5-tq7lz    1/1     Running            4 (2m ago)    11m",
            ]},
            {"kind": "kubectl", "title": "kubectl describe pod checkout-service-7f9d8c6b5-2xkqp (excerpt)", "lines": [
                "    Image:          123456789012.dkr.ecr.us-east-1.amazonaws.com/checkout-service:v2.14.0",
                "    Last State:     Terminated",
                "      Reason:       OOMKilled",
                "      Exit Code:    137",
                "    Limits:",
                "      cpu:     1",
                "      memory:  512Mi",
                "    Requests:",
                "      memory:  256Mi",
            ]},
            {"kind": "metrics", "title": "container_memory_working_set_bytes, checkout-service (p95, 1m buckets)", "lines": [
                "14:02  v2.14.0 rollout starts",
                "14:03  301Mi",
                "14:04  447Mi",
                "14:05  506Mi   <- OOMKilled at limit 512Mi",
                "14:06  289Mi   (restart)",
                "v2.13.4 steady state over the previous 7 days: 330-360Mi",
            ]},
        ],
        "remediation_options": [
            {"id": "opt_1", "title": "Raise the memory limit to 768Mi",
             "description": "Gives v2.14.0's larger working set headroom. Rolling restart, no downtime.",
             "impact": "low", "docs_url": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
             "diff": (
                 "--- a/deploy/k8s/checkout-service/deployment.yaml\n"
                 "+++ b/deploy/k8s/checkout-service/deployment.yaml\n"
                 "@@ -41,10 +41,10 @@ spec:\n"
                 "           resources:\n"
                 "             requests:\n"
                 "-              memory: \"256Mi\"\n"
                 "+              memory: \"384Mi\"\n"
                 "               cpu: \"250m\"\n"
                 "             limits:\n"
                 "-              memory: \"512Mi\"\n"
                 "+              memory: \"768Mi\"\n"
                 "               cpu: \"1\"\n"
             ),
             "blast_radius": {"scope": "1 deployment, 3 pods (rolling restart)", "change_surface": "Kubernetes API",
                              "reversible": True},
             "execution_log": [
                 "▶  kubectl context: prod-eks-us-east-1 (namespace payments)",
                 "▶  Patching deployment/checkout-service resources",
                 "✓  requests.memory 256Mi → 384Mi, limits.memory 512Mi → 768Mi",
                 "▶  Waiting for rollout (maxUnavailable 1)",
                 "✓  deployment \"checkout-service\" successfully rolled out (3/3)",
                 "▶  Watching restarts for 5 minutes",
                 "✓  0 restarts; working set steady at 512-540Mi",
                 "✓  Incident resolved",
             ]},
            {"id": "opt_2", "title": "Roll back to v2.13.4",
             "description": "Returns to the last image that ran inside 512Mi. Ships nothing from v2.14.0 until it is fixed.",
             "impact": "medium", "docs_url": "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-back-a-deployment",
             "diff": (
                 "--- a/deploy/k8s/checkout-service/deployment.yaml\n"
                 "+++ b/deploy/k8s/checkout-service/deployment.yaml\n"
                 "@@ -27,7 +27,7 @@ spec:\n"
                 "       containers:\n"
                 "         - name: checkout-service\n"
                 "-          image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/checkout-service:v2.14.0\n"
                 "+          image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/checkout-service:v2.13.4\n"
                 "           ports:\n"
             ),
             "blast_radius": {"scope": "1 deployment, 3 pods; v2.14.0 changes withdrawn", "change_surface": "Kubernetes API",
                              "reversible": True},
             "execution_log": [
                 "▶  kubectl context: prod-eks-us-east-1 (namespace payments)",
                 "▶  Setting image checkout-service:v2.14.0 → v2.13.4",
                 "✓  deployment \"checkout-service\" successfully rolled out (3/3)",
                 "▶  Watching restarts for 5 minutes",
                 "✓  0 restarts; working set steady at 340Mi",
                 "✓  Incident resolved (v2.14.0 needs a memory fix before redeploying)",
             ]},
        ],
    },
    # ── Target scenario: Terraform security-group drift ───────────────────
    {
        "agent_id": "agent_08_drift_detection", "severity": "critical",
        "resource_name": "prod-db-sg (sg-0a7c3e91d2b4f5a60)", "cloud_provider": "aws",
        "parsed_error": (
            "Security group prod-db-sg allows 0.0.0.0/0 on port 5432. The rule was added in the "
            "console 2026-11-13 and is not in Terraform; Terraform only allows the app subnets."
        ),
        "evidence": [
            {"kind": "terraform", "title": "terraform plan (modules/database), drift detected", "lines": [
                "  # aws_security_group.prod_db has changed outside of Terraform",
                "  ~ resource \"aws_security_group\" \"prod_db\" {",
                "      ~ ingress = [",
                "          - {",
                "              - cidr_blocks = [\"0.0.0.0/0\"]",
                "              - from_port   = 5432",
                "              - protocol    = \"tcp\"",
                "              - to_port     = 5432",
                "            },",
                "            # (1 unchanged element hidden: 10.20.0.0/16 on 5432)",
                "        ]",
                "    }",
                "Plan: 0 to add, 1 to change, 0 to destroy.",
            ]},
            {"kind": "log", "title": "CloudTrail: AuthorizeSecurityGroupIngress", "lines": [
                "eventTime:    2026-11-13T22:41:07Z",
                "userIdentity: arn:aws:iam::123456789012:user/jordan.k (console)",
                "groupId:      sg-0a7c3e91d2b4f5a60",
                "ipPermissions: tcp 5432 from 0.0.0.0/0",
            ]},
            {"kind": "cli", "title": "aws ec2 describe-security-group-rules --filters Name=group-id,Values=sg-0a7c3e91d2b4f5a60", "lines": [
                "sgr-0f31c8a2  ingress  tcp  5432  10.20.0.0/16   app subnets (terraform)",
                "sgr-07b9e44d  ingress  tcp  5432  0.0.0.0/0      (no description)",
            ]},
        ],
        "remediation_options": [
            {"id": "opt_1", "title": "Remove the public rule (re-apply Terraform)",
             "description": "Puts the group back to what Terraform declares: app subnets only on 5432.",
             "impact": "low", "docs_url": "https://developer.hashicorp.com/terraform/cli/commands/apply",
             "diff": (
                 "--- live: sg-0a7c3e91d2b4f5a60 (prod-db-sg)\n"
                 "+++ terraform: modules/database/security_groups.tf\n"
                 "@@ ingress tcp/5432 @@\n"
                 "-  cidr_blocks = [\"0.0.0.0/0\"]      # added in console 2026-11-13\n"
                 "   cidr_blocks = [\"10.20.0.0/16\"]   # app subnets\n"
             ),
             "blast_radius": {"scope": "1 security group rule; connections from outside 10.20.0.0/16 stop",
                              "change_surface": "AWS EC2 via terraform apply", "reversible": True},
             "execution_log": [
                 "▶  terraform init (modules/database, workspace prod-us-east-1)",
                 "▶  terraform plan",
                 "✓  Plan: 0 to add, 1 to change, 0 to destroy",
                 "▶  terraform apply (approved plan only)",
                 "✓  aws_security_group.prod_db: Modifications complete",
                 "▶  Verifying with describe-security-group-rules",
                 "✓  No 0.0.0.0/0 rule on port 5432",
                 "✓  Posted to #infra-security; incident resolved",
             ]},
            {"id": "opt_2", "title": "Keep the rule and add it to Terraform",
             "description": "Makes the public database port permanent. Only if someone needs it and has a reason on record.",
             "impact": "high", "docs_url": "https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-group-rules.html",
             "diff": (
                 "--- a/modules/database/security_groups.tf\n"
                 "+++ b/modules/database/security_groups.tf\n"
                 "@@ -18,6 +18,13 @@ resource \"aws_security_group\" \"prod_db\" {\n"
                 "     cidr_blocks = [\"10.20.0.0/16\"]\n"
                 "   }\n"
                 "+  ingress {\n"
                 "+    description = \"Public access (added from console 2026-11-13)\"\n"
                 "+    from_port   = 5432\n"
                 "+    to_port     = 5432\n"
                 "+    protocol    = \"tcp\"\n"
                 "+    cidr_blocks = [\"0.0.0.0/0\"]\n"
                 "+  }\n"
             ),
             "blast_radius": {"scope": "Production database port open to the internet, permanently",
                              "change_surface": "pull request to infra repo", "reversible": True},
             "execution_log": [
                 "▶  Opening pull request on acme/infra",
                 "✓  PR #851: codify public 5432 ingress on prod-db-sg",
                 "✓  Waiting for review; drift alert silenced for this rule",
             ]},
        ],
    },
    # ── Target scenario: CI deploy failure from an IAM mismatch ───────────
    {
        "agent_id": "agent_01_cicd_triage", "severity": "high",
        "resource_name": "deploy-assets (acme/storefront, main)", "cloud_provider": "aws",
        "parsed_error": (
            "The deploy-assets job fails with AccessDenied on s3:PutObject. The assets bucket was renamed "
            "to acme-prod-assets-v2 two days ago, but github-deploy-role still only allows the old bucket."
        ),
        "evidence": [
            {"kind": "log", "title": "GitHub Actions: deploy-assets, run #4127 (main)", "lines": [
                "Run aws s3 sync ./dist s3://acme-prod-assets-v2 --delete",
                "upload failed: dist/index.html to s3://acme-prod-assets-v2/index.html An error occurred (AccessDenied)",
                "  when calling the PutObject operation: User: arn:aws:sts::123456789012:assumed-role/github-deploy-role/",
                "  GitHubActions is not authorized to perform: s3:PutObject on resource:",
                "  \"arn:aws:s3:::acme-prod-assets-v2/index.html\" because no identity-based policy allows the s3:PutObject action",
                "Error: Process completed with exit code 1.",
            ]},
            {"kind": "cli", "title": "aws iam get-role-policy --role-name github-deploy-role --policy-name deploy-assets", "lines": [
                "\"Action\": [\"s3:PutObject\", \"s3:DeleteObject\", \"s3:ListBucket\"],",
                "\"Resource\": [",
                "  \"arn:aws:s3:::acme-prod-assets\",",
                "  \"arn:aws:s3:::acme-prod-assets/*\"",
                "]",
            ]},
            {"kind": "log", "title": "git log -1 -- infra/s3.tf", "lines": [
                "a91f3c2  infra: rename assets bucket to acme-prod-assets-v2 (#1182)   2 days ago",
            ]},
        ],
        "remediation_options": [
            {"id": "opt_1", "title": "Point the role policy at the renamed bucket",
             "description": "Pull request that swaps the two resource ARNs, then re-runs the failed job once it merges.",
             "impact": "low", "docs_url": "https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_resource.html",
             "diff": (
                 "--- a/infra/iam/github-deploy-role.json\n"
                 "+++ b/infra/iam/github-deploy-role.json\n"
                 "@@ -9,8 +9,8 @@\n"
                 "       \"Action\": [\"s3:PutObject\", \"s3:DeleteObject\", \"s3:ListBucket\"],\n"
                 "       \"Resource\": [\n"
                 "-        \"arn:aws:s3:::acme-prod-assets\",\n"
                 "-        \"arn:aws:s3:::acme-prod-assets/*\"\n"
                 "+        \"arn:aws:s3:::acme-prod-assets-v2\",\n"
                 "+        \"arn:aws:s3:::acme-prod-assets-v2/*\"\n"
                 "       ]\n"
             ),
             "blast_radius": {"scope": "1 IAM role policy, 2 resource ARNs; no new actions",
                              "change_surface": "pull request to infra repo", "reversible": True},
             "execution_log": [
                 "▶  Opening pull request on acme/infra",
                 "✓  PR #1190: point github-deploy-role at acme-prod-assets-v2",
                 "✓  CI on PR #1190 passed (policy lint, terraform plan: 1 to change)",
                 "▶  PR merged; terraform apply (approved plan only)",
                 "✓  aws_iam_role_policy.deploy_assets: Modifications complete",
                 "▶  Re-running failed job deploy-assets (run #4127)",
                 "✓  deploy-assets succeeded: 214 files synced to s3://acme-prod-assets-v2",
                 "✓  Incident resolved",
             ]},
            {"id": "opt_2", "title": "Re-run the failed job only",
             "description": "Will fail again: the policy still names the old bucket. Here so you can see why it's not the fix.",
             "impact": "low", "docs_url": "https://docs.github.com/en/actions/managing-workflow-runs/re-running-workflows-and-jobs",
             "blast_radius": {"scope": "1 workflow run", "change_surface": "GitHub Actions", "reversible": True},
             "execution_log": [
                 "▶  Re-running failed job deploy-assets (run #4127)",
                 "✗  AccessDenied on s3:PutObject (same error)",
                 "✗  Not resolved: the role policy still needs the renamed bucket",
             ]},
        ],
    },
    # ── Target scenario: S3 exposure ─────────────────────────────────────
    {
        "agent_id": "agent_08_drift_detection", "severity": "critical",
        "resource_name": "acme-customer-exports (S3)", "cloud_provider": "aws",
        "parsed_error": (
            "S3 bucket acme-customer-exports is publicly readable: Block Public Access was turned off and "
            "the bucket policy grants s3:GetObject to Principal \"*\". 214 anonymous GETs in the last 24h."
        ),
        "evidence": [
            {"kind": "cli", "title": "aws s3api get-public-access-block --bucket acme-customer-exports", "lines": [
                "BlockPublicAcls:       false",
                "IgnorePublicAcls:      false",
                "BlockPublicPolicy:     false",
                "RestrictPublicBuckets: false",
            ]},
            {"kind": "cli", "title": "aws s3api get-bucket-policy --bucket acme-customer-exports", "lines": [
                "{ \"Sid\": \"TempShare\", \"Effect\": \"Allow\", \"Principal\": \"*\",",
                "  \"Action\": \"s3:GetObject\", \"Resource\": \"arn:aws:s3:::acme-customer-exports/*\" }",
            ]},
            {"kind": "log", "title": "CloudTrail: PutPublicAccessBlock, PutBucketPolicy", "lines": [
                "2026-11-14T03:12:44Z  PutPublicAccessBlock  role/data-eng-sandbox  all four settings false",
                "2026-11-14T03:13:02Z  PutBucketPolicy       role/data-eng-sandbox  Sid TempShare added",
            ]},
            {"kind": "metrics", "title": "S3 server access logs, last 24h", "lines": [
                "214 GET requests by anonymous principal",
                "38 distinct source IPs, none in your VPCs or office ranges",
                "Objects read: exports/2026-11/customers-*.csv.gz",
            ]},
        ],
        "remediation_options": [
            {"id": "opt_1", "title": "Re-enable Block Public Access and remove the public statement",
             "description": "Closes the bucket to anonymous reads immediately. Shared public links stop working.",
             "impact": "low", "docs_url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html",
             "diff": (
                 "--- a/modules/storage/customer_exports.tf\n"
                 "+++ b/modules/storage/customer_exports.tf\n"
                 "@@ -12,10 +12,10 @@ resource \"aws_s3_bucket_public_access_block\" \"customer_exports\" {\n"
                 "   bucket                  = aws_s3_bucket.customer_exports.id\n"
                 "-  block_public_acls       = false\n"
                 "-  block_public_policy     = false\n"
                 "-  ignore_public_acls      = false\n"
                 "-  restrict_public_buckets = false\n"
                 "+  block_public_acls       = true\n"
                 "+  block_public_policy     = true\n"
                 "+  ignore_public_acls      = true\n"
                 "+  restrict_public_buckets = true\n"
                 " }\n"
                 "@@ -31,14 +31,0 @@ data \"aws_iam_policy_document\" \"customer_exports\" {\n"
                 "-  statement {\n"
                 "-    sid       = \"TempShare\"\n"
                 "-    principals { type = \"*\" identifiers = [\"*\"] }\n"
                 "-    actions   = [\"s3:GetObject\"]\n"
                 "-    resources = [\"${aws_s3_bucket.customer_exports.arn}/*\"]\n"
                 "-  }\n"
             ),
             "blast_radius": {"scope": "1 bucket; anonymous access ends, IAM-authorised access unchanged",
                              "change_surface": "AWS S3 via terraform apply", "reversible": True},
             "execution_log": [
                 "▶  terraform plan (modules/storage, workspace prod-us-east-1)",
                 "✓  Plan: 0 to add, 2 to change, 0 to destroy",
                 "▶  terraform apply (approved plan only)",
                 "✓  aws_s3_bucket_public_access_block.customer_exports: Modifications complete",
                 "✓  aws_s3_bucket_policy.customer_exports: Modifications complete",
                 "▶  Verifying with an anonymous GET",
                 "✓  403 AccessDenied for anonymous principal",
                 "✓  Incident resolved; access-log window attached for review",
             ]},
            {"id": "opt_2", "title": "Remove only the public bucket-policy statement",
             "description": "Stops the current exposure but leaves Block Public Access off, so it can happen again.",
             "impact": "medium", "docs_url": "https://docs.aws.amazon.com/AmazonS3/latest/userguide/bucket-policies.html",
             "blast_radius": {"scope": "1 bucket policy statement", "change_surface": "AWS S3 via terraform apply",
                              "reversible": True},
             "execution_log": [
                 "▶  terraform apply (approved plan only)",
                 "✓  aws_s3_bucket_policy.customer_exports: Modifications complete",
                 "✓  403 AccessDenied for anonymous principal",
                 "!  Block Public Access is still off: a new public policy would be accepted",
             ]},
        ],
    },
    # ── Supporting scenarios ─────────────────────────────────────────────
    {
        "agent_id": "agent_10_dependency_patch", "severity": "critical",
        "resource_name": "acme/storefront package.json", "cloud_provider": None,
        "parsed_error": "lodash@4.17.15 has a critical prototype-pollution CVE (CVE-2020-8203). Fixed in 4.17.21.",
        "evidence": [
            {"kind": "cli", "title": "npm audit --production", "lines": [
                "lodash  <4.17.21",
                "Severity: critical",
                "Prototype Pollution in lodash - https://github.com/advisories/GHSA-p6mc-m468-83gw",
                "fix available via `npm audit fix`",
                "node_modules/lodash",
                "1 critical severity vulnerability",
            ]},
        ],
        "remediation_options": [
            {"id": "opt_1", "title": "Patch to lodash@4.17.21",
             "description": "Pull request bumping the dependency; patch release, no API changes.",
             "impact": "low", "docs_url": "https://nvd.nist.gov/vuln/detail/CVE-2020-8203",
             "diff": (
                 "--- a/package.json\n"
                 "+++ b/package.json\n"
                 "@@ -21,7 +21,7 @@\n"
                 "     \"express\": \"^4.19.2\",\n"
                 "-    \"lodash\": \"4.17.15\",\n"
                 "+    \"lodash\": \"4.17.21\",\n"
                 "     \"pino\": \"^9.3.2\",\n"
             ),
             "blast_radius": {"scope": "1 dependency (patch release) + lockfile", "change_surface": "pull request",
                              "reversible": True},
             "execution_log": [
                 "▶  Opening pull request on acme/storefront",
                 "✓  PR #2291: bump lodash 4.17.15 → 4.17.21",
                 "✓  CI passed: 412 tests, npm audit clean",
                 "✓  Incident resolved (merge when ready)",
             ]},
        ],
    },
    {
        "agent_id": "agent_05_iam_minimizer", "severity": "medium",
        "resource_name": "role/data-pipeline-worker", "cloud_provider": "aws",
        "parsed_error": "IAM role data-pipeline-worker has s3:* on all buckets; in 90 days it only read and wrote 2 buckets.",
        "evidence": [
            {"kind": "cli", "title": "IAM Access Advisor, last 90 days", "lines": [
                "s3:GetObject   acme-raw-events        last used 2026-11-14",
                "s3:PutObject   acme-curated-events    last used 2026-11-14",
                "s3:*           (all other actions and buckets)  never used",
            ]},
        ],
        "remediation_options": [
            {"id": "opt_1", "title": "Scope down to the 2 buckets it uses",
             "description": "Replaces the wildcard with the two actions and buckets actually used.",
             "impact": "medium", "docs_url": "https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html#grant-least-privilege",
             "diff": (
                 "--- a/infra/iam/data-pipeline-worker.json\n"
                 "+++ b/infra/iam/data-pipeline-worker.json\n"
                 "@@ -4,6 +4,12 @@\n"
                 "-    { \"Effect\": \"Allow\", \"Action\": \"s3:*\", \"Resource\": \"*\" }\n"
                 "+    { \"Effect\": \"Allow\", \"Action\": \"s3:GetObject\",\n"
                 "+      \"Resource\": \"arn:aws:s3:::acme-raw-events/*\" },\n"
                 "+    { \"Effect\": \"Allow\", \"Action\": \"s3:PutObject\",\n"
                 "+      \"Resource\": \"arn:aws:s3:::acme-curated-events/*\" }\n"
             ),
             "blast_radius": {"scope": "1 IAM role; any unused S3 access it relied on would break",
                              "change_surface": "AWS IAM", "reversible": True},
             "execution_log": [
                 "▶  iam:CreatePolicyVersion on data-pipeline-worker",
                 "✓  New default version v4 (previous v3 kept for rollback)",
                 "✓  Incident resolved",
             ]},
        ],
    },
    {
        "agent_id": "agent_06_finops", "severity": "low",
        "resource_name": "i-0a1b2c3d4e5f67890 (analytics-batch-old)", "cloud_provider": "aws",
        "parsed_error": "EC2 instance analytics-batch-old has been idle (<3% CPU) for 14 days, costing about $210/month.",
        "evidence": [
            {"kind": "metrics", "title": "CloudWatch, last 14 days", "lines": [
                "CPUUtilization (max daily):  2.1% 1.8% 2.4% 1.9% 2.0% 1.7% 2.2% ...",
                "NetworkIn (daily):           < 5 MB",
                "Last SSH/SSM session:        2026-10-29",
                "On-demand m5.xlarge, us-east-1: $0.192/h ≈ $140/mo + 500 GB gp3 ≈ $70/mo",
            ]},
        ],
        "remediation_options": [
            {"id": "opt_1", "title": "Stop the instance",
             "description": "Stops (not terminates) it; the disk is kept and it can be started again.",
             "impact": "low", "docs_url": "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Stop_Start.html",
             "blast_radius": {"scope": "1 EC2 instance stopped; EBS volume kept", "change_surface": "AWS EC2 API",
                              "reversible": True},
             "execution_log": [
                 "▶  ec2:StopInstances i-0a1b2c3d4e5f67890",
                 "✓  Instance state: stopped",
                 "✓  Estimated saving: ~$140/month (EBS still billed)",
             ]},
        ],
    },
    {
        "agent_id": "agent_11_resource_health", "severity": "medium",
        "resource_name": "rds-prod-primary", "cloud_provider": "aws",
        "parsed_error": "RDS rds-prod-primary has 9% free storage and is losing ~3 GB/day: full in about 6 days.",
        "evidence": [
            {"kind": "metrics", "title": "CloudWatch FreeStorageSpace, rds-prod-primary (200 GB allocated)", "lines": [
                "2026-11-08  37 GB",
                "2026-11-10  31 GB",
                "2026-11-12  25 GB",
                "2026-11-14  18 GB   (9%)",
                "Trend: -3.1 GB/day  →  full around 2026-11-20",
            ]},
        ],
        "remediation_options": [
            {"id": "opt_1", "title": "Grow storage to 250 GB and enable autoscaling to 400 GB",
             "description": "Online modification, no downtime. RDS storage can't be shrunk afterwards.",
             "impact": "medium", "docs_url": "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIOPS.StorageTypes.html#USER_PIOPS.Autoscaling",
             "diff": (
                 "--- a/modules/database/rds.tf\n"
                 "+++ b/modules/database/rds.tf\n"
                 "@@ -14,7 +14,8 @@ resource \"aws_db_instance\" \"prod_primary\" {\n"
                 "   engine_version        = \"16.4\"\n"
                 "-  allocated_storage     = 200\n"
                 "+  allocated_storage     = 250\n"
                 "+  max_allocated_storage = 400\n"
                 "   storage_type          = \"gp3\"\n"
             ),
             "blast_radius": {"scope": "1 RDS instance, no downtime; storage can't be reduced later",
                              "change_surface": "AWS RDS via terraform apply", "reversible": False},
             "execution_log": [
                 "▶  terraform apply (modules/database, approved plan only)",
                 "✓  aws_db_instance.prod_primary: Modifying... storage-optimization started",
                 "✓  Allocated storage 250 GB, autoscaling up to 400 GB",
                 "✓  FreeStorageSpace 68 GB (27%); incident resolved",
             ]},
        ],
    },
]


def hash_demo_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_or_create_demo_workspace(conn) -> UUID:
    """
    Idempotent: returns the existing singleton demo workspace
    (workspaces.is_demo_workspace, migration 057's partial unique index)
    if one exists, otherwise creates it. The generated workspace_token is
    never handed to anyone -- demo visitors authenticate via
    demo_sessions/X-Demo-Session-Token instead (see get_workspace_or_
    member_or_demo) -- it exists only because workspace_token is
    UNIQUE NOT NULL on every workspaces row.
    """
    row = await conn.fetchrow("SELECT id FROM workspaces WHERE is_demo_workspace = true LIMIT 1")
    if row:
        return row["id"]

    raw_token = "cd_ws_" + secrets.token_urlsafe(32)
    row = await conn.fetchrow(
        """
        INSERT INTO workspaces (
            company_name, workspace_token, stripe_subscription_status,
            product_tier, is_demo_workspace, aws_connection_mode, azure_connection_mode
        ) VALUES ($1, $2, 'active', 'enterprise', true, 'read_only', 'read_only')
        RETURNING id
        """,
        _DEMO_COMPANY_NAME, hash_demo_token(raw_token),
    )
    log.info("[DemoSandbox] Created demo workspace %s", row["id"])
    return row["id"]


async def insert_demo_incidents(
    conn, workspace_id: UUID, wipe_first: bool = True, demo_session_id: Optional[UUID] = None,
) -> int:
    """Shared by the CLI script (demo_session_id=None, seeding a real
    prospect's workspace) and create_demo_session (one copy per visitor,
    migration 059). --wipe-first makes re-running this idempotent instead
    of accumulating duplicates. With a demo_session_id it wipes only that
    session's rows, never another visitor's."""
    if wipe_first:
        if demo_session_id is None:
            deleted = await conn.execute(
                "DELETE FROM incidents WHERE workspace_id = $1 AND is_test = true", workspace_id,
            )
        else:
            deleted = await conn.execute(
                "DELETE FROM incidents WHERE workspace_id = $1 AND is_test = true AND demo_session_id = $2",
                workspace_id, demo_session_id,
            )
        log.info("[DemoSandbox] Wiped existing test incidents for %s: %s", workspace_id, deleted)

    now = datetime.now(timezone.utc)
    for i, spec in enumerate(DEMO_INCIDENTS):
        created_at = now - timedelta(hours=len(DEMO_INCIDENTS) - i)
        await conn.execute(
            """
            INSERT INTO incidents (
                workspace_id, agent_id, cloud_provider, raw_log_hash,
                parsed_error, remediation_options, execution_status,
                resource_name, severity, is_test, last_seen_at, created_at,
                demo_session_id, evidence
            ) VALUES ($1, $2, $3, $4, $5, $6, 'pending_approval', $7, $8, true, $9, $9, $10, $11)
            """,
            workspace_id,
            spec["agent_id"],
            spec["cloud_provider"],
            f"demo-seed-{i}",
            spec["parsed_error"],
            json.dumps(spec["remediation_options"]),
            spec["resource_name"],
            spec["severity"],
            created_at,
            demo_session_id,
            # Native list: every caller's connection has core.db's jsonb codec
            # (the app pool, and scripts/seed_demo_incidents.py registers it).
            spec.get("evidence"),
        )
    return len(DEMO_INCIDENTS)


async def run_demo_reset(pool) -> None:
    """
    Scheduled entry point -- api/main.py's _demo_reset_loop runs this
    every DEMO_RESET_INTERVAL_SECONDS (30 min). Since migration 059 every
    visitor has their own incidents, so there is no shared baseline to
    restore: this pass only prunes expired demo_sessions rows. Their
    incidents (and those incidents' comments) go with them via
    ON DELETE CASCADE. It also removes any stray session-less test rows in
    the demo workspace, which no demo visitor can see anyway.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock($1)", _DEMO_RESET_LOCK_ID)
            if not got_lock:
                log.info("[DemoSandbox] Another worker holds the reset lock — skipping this cycle")
                return

            workspace_id = await get_or_create_demo_workspace(conn)
            pruned = await conn.execute("DELETE FROM demo_sessions WHERE expires_at < NOW()")
            orphans = await conn.execute(
                "DELETE FROM incidents WHERE workspace_id = $1 AND is_test = true AND demo_session_id IS NULL",
                workspace_id,
            )

    log.info(
        "[DemoSandbox] Pruned demo workspace %s (expired sessions: %s, session-less test incidents: %s)",
        workspace_id, pruned, orphans,
    )


async def create_demo_session(pool, attribution: Optional[dict] = None) -> tuple[str, datetime]:
    """
    GET /demo's entry point. Always creates a NEW session/token for the
    visitor (never reuses another visitor's token) in the one demo
    workspace, and seeds that session its own copy of the baseline
    incidents (migration 059). The session row and its incidents are
    written in one transaction, so a visitor never gets a token whose
    console is empty. No other visitor's incidents are read or touched.

    attribution (migration 060): optional ref/utm_* from the visitor's
    ?ref= / UTM link, validated by core.funnel_events and stored on the
    session so server-recorded demo events inherit them.
    """
    from core.funnel_events import clean_ref, clean_utm  # noqa: PLC0415 -- keeps this module's import graph unchanged

    attribution = attribution or {}
    async with pool.acquire() as conn:
        async with conn.transaction():
            workspace_id = await get_or_create_demo_workspace(conn)

            raw_token = DEMO_SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + DEMO_SESSION_TTL
            session_id = await conn.fetchval(
                """
                INSERT INTO demo_sessions (
                    workspace_id, session_token_hash, expires_at,
                    ref, utm_source, utm_medium, utm_campaign
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                workspace_id, hash_demo_token(raw_token), expires_at,
                clean_ref(attribution.get("ref")),
                clean_utm(attribution.get("utm_source")),
                clean_utm(attribution.get("utm_medium")),
                clean_utm(attribution.get("utm_campaign")),
            )
            await insert_demo_incidents(conn, workspace_id, wipe_first=False, demo_session_id=session_id)

    return raw_token, expires_at


async def resolve_demo_session(pool, raw_token: str) -> Optional[dict]:
    """
    Validates an X-Demo-Session-Token. Returns None (never raises) on
    anything wrong -- api/middleware/auth.py's
    _get_workspace_by_demo_session turns that into the appropriate HTTP
    error; this function is pure lookup logic so it's independently
    testable without a Request object.
    """
    if not raw_token or not raw_token.startswith(DEMO_SESSION_TOKEN_PREFIX):
        return None

    token_hash = hash_demo_token(raw_token)
    async with pool.acquire() as conn:
        session_row = await conn.fetchrow(
            "SELECT id, workspace_id, expires_at FROM demo_sessions WHERE session_token_hash = $1",
            token_hash,
        )
        if not session_row:
            return None
        if session_row["expires_at"] <= datetime.now(timezone.utc):
            return None

        # Deliberately only the columns get_workspace_member/get_workspace
        # already expose -- see api/middleware/auth.py's
        # _WORKSPACE_SELECT_COLUMNS. Selecting '*' here would risk a demo
        # dict silently gaining a field real sessions don't carry.
        from api.middleware.auth import _WORKSPACE_SELECT_COLUMNS  # noqa: PLC0415 -- avoids a module import cycle at load time

        workspace_row = await conn.fetchrow(
            f"SELECT {_WORKSPACE_SELECT_COLUMNS} FROM workspaces WHERE id = $1",
            session_row["workspace_id"],
        )

    if not workspace_row:
        return None

    result = dict(workspace_row)
    result["member_id"] = None
    result["member_role"] = "approver"
    result["member_email"] = "Demo Visitor"
    result["is_demo_session"] = True
    # Migration 059: api/routes/incidents.py scopes every demo-reachable
    # incident lookup to this session's own rows via demo_scope_clause.
    result["demo_session_id"] = session_row["id"]
    return result


def demo_scope_clause(workspace: dict, param_index: int, column: str = "demo_session_id") -> tuple[str, list]:
    """
    SQL fragment + params that restrict an incidents query to the calling
    demo visitor's own rows. Returns ("", []) for every real workspace or
    member session, so real-customer queries are unchanged.

    Fails closed: a demo identity without a session id raises instead of
    falling back to unscoped access to every visitor's incidents.
    """
    if not workspace.get("is_demo_session"):
        return "", []
    session_id = workspace.get("demo_session_id")
    if not session_id:
        raise RuntimeError("Demo session identity is missing demo_session_id; refusing an unscoped incidents query")
    return f" AND {column} = ${param_index}", [session_id]
