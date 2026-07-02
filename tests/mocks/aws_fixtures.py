"""
tests/mocks/aws_fixtures.py
Drop-in mock AWS data for local testing of Cloud Decoded agents.

These constants represent realistic CloudTrail logs, GitHub Actions logs,
IAM policies, and Terraform plan output that agents would receive in production.
The GitHub Actions log intentionally contains a fake AWS key to exercise the
DataSanitizationShield credential-stripping logic.

Usage:
    from tests.mocks.aws_fixtures import MOCK_GITHUB_ACTIONS_LOG, MOCK_CLOUDTRAIL_S3_DENIED
"""

# ── CloudTrail — S3 access denied event ──────────────────────────────────────

MOCK_CLOUDTRAIL_S3_DENIED = {
    "Records": [
        {
            "eventTime": "2026-06-23T02:14:33Z",
            "eventSource": "s3.amazonaws.com",
            "eventName": "PutObject",
            "errorCode": "AccessDenied",
            "errorMessage": "Access Denied",
            "userIdentity": {
                "type": "AssumedRole",
                "arn": "arn:aws:sts::123456789012:assumed-role/github-deploy-role/GitHubActionsSession",
                "principalId": "AROAIOSFODNN7EXAMPLE:GitHubActionsSession",
            },
            "requestParameters": {
                "bucketName": "prod-assets-bucket",
                "key": "static/main.js",
            },
            "awsRegion": "us-east-1",
            "sourceIPAddress": "192.0.2.1",
        }
    ]
}

# ── GitHub Actions log — raw, with embedded fake AWS key ─────────────────────
# The key AKIAIOSFODNN7EXAMPLE is the canonical AWS documentation example key.
# It must be redacted by DataSanitizationShield before reaching the LLM.

MOCK_GITHUB_ACTIONS_LOG = """\
2026-06-23T02:14:30Z ##[group]Run deployment step
2026-06-23T02:14:31Z Setting up AWS credentials for github-deploy-role
2026-06-23T02:14:31Z AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
2026-06-23T02:14:31Z AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
2026-06-23T02:14:32Z Uploading assets to s3://prod-assets-bucket/static/
2026-06-23T02:14:33Z upload failed: ./build/main.js to s3://prod-assets-bucket/static/main.js
2026-06-23T02:14:33Z An error occurred (AccessDenied) when calling the PutObject operation: Access Denied
2026-06-23T02:14:33Z ##[error]Process completed with exit code 1.
2026-06-23T02:14:33Z ##[endgroup]
"""

# ── IAM policy — overpermissive (for Agent 04 IAM tests) ─────────────────────

MOCK_IAM_POLICY_OVERPERMISSIVE = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "s3:*",
            "Resource": "*",
            "Principal": "*",
        }
    ],
}

MOCK_IAM_POLICY_LEAST_PRIVILEGE = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject"],
            "Resource": "arn:aws:s3:::prod-assets-bucket/*",
        }
    ],
}

# ── Terraform plan — drift showing open DB port ───────────────────────────────

MOCK_TERRAFORM_DRIFT = """\
Terraform will perform the following actions:

  # aws_security_group_rule.api_server_sg_ingress will be updated in-place
  ~ resource "aws_security_group_rule" "api_server_sg_ingress" {
      ~ cidr_blocks = [
          - "10.0.0.0/8"
          + "0.0.0.0/0"
        ]
        from_port   = 5432
        protocol    = "tcp"
        to_port     = 5432
        type        = "ingress"
    }

Plan: 0 to add, 1 to change, 0 to destroy.
"""

# ── GitHub webhook payload — CI/CD failure ────────────────────────────────────

MOCK_GITHUB_WEBHOOK_FAILURE = {
    "action": "completed",
    "workflow_run": {
        "id": 99887766,
        "name": "Deploy Frontend Assets",
        "conclusion": "failure",
        "head_branch": "main",
        "html_url": "https://github.com/acme/backend/actions/runs/99887766",
        "head_commit": {
            "message": "chore: bump assets version to 2.4.1"
        },
        "pull_requests": [],
    },
    "repository": {
        "full_name": "acme/backend",
    },
}
