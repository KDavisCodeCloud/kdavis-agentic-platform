"""
tests/mocks/iac_fixtures.py
Mock infrastructure-as-code deploy-failure logs for Agent 01's broadened,
domain-organized diagnosis prompt -- added as part of the "IaC deploy-
failure diagnosis + live resource monitoring" build, Phase A.

One fixture per domain (IAM/RBAC/Policy, Networking, Storage, Compute) per
cloud (AWS, Azure) -- 8 total. Database-as-a-service resources are
explicitly out of scope for this build (addressed separately), so no
fixture here touches RDS/Azure SQL/Cosmos DB/DynamoDB.

These are realistic CI/CD job log excerpts as they'd appear when an IaC
deploy step runs as a pipeline step and fails -- the same shape Agent 01
already receives for npm/Docker/test failures, just from a different tool.
None contain real credentials; MOCK_IAM_AZURE_FAILURE_LOG plants a fake AWS
example key to also exercise the sanitizer on this new log category.

Usage:
    from tests.mocks.iac_fixtures import IAC_DOMAIN_FIXTURES
    # or import any MOCK_*_LOG constant directly
"""

# ── Domain: IAM / RBAC / Policy ──────────────────────────────────────────────

MOCK_IAM_AWS_FAILURE_LOG = """\
aws cloudformation deploy --template-file stack.yaml --stack-name acme-prod-pipeline

2026-09-15 03:02:11 UTC  acme-prod-pipeline  CREATE_IN_PROGRESS
2026-09-15 03:02:19 UTC  DeployRole            CREATE_FAILED   API: iam:CreateRole
  User: arn:aws:sts::123456789012:assumed-role/ci-deploy-role/GitHubActionsSession
  is not authorized to perform: iam:CreateRole because a Service Control
  Policy explicitly denies this action. Encoded authorization failure
  message available.
2026-09-15 03:02:24 UTC  acme-prod-pipeline  ROLLBACK_IN_PROGRESS
2026-09-15 03:02:41 UTC  acme-prod-pipeline  ROLLBACK_COMPLETE

Failed to deploy: stack acme-prod-pipeline rolled back.
"""

# Cross-resource auth: App Service's managed identity isn't yet propagated
# to Key Vault immediately after both resources were created in the same
# run -- the deploy itself succeeded, the post-deploy health check didn't.
MOCK_IAM_AZURE_FAILURE_LOG = """\
##[section]Starting: Post-deploy health check
GET https://acme-prod-app.azurewebsites.net/health

HTTP/1.1 500 Internal Server Error
{"error": "Failed to resolve app setting 'API_KEY_REF':
KeyVaultReference resolution failed. Status: 403 (Forbidden).
Inner error: The user, group, or application 'appid=9a8b7c6d-...' does not
have secrets get permission on key vault 'acme-prod-kv'. The managed
identity was assigned to this App Service 38 seconds ago in this same
deployment run."}

##[error]Health check failed after successful deployment. AKIAIOSFODNN7EXAMPLE
appears nowhere in this log -- planted only to prove the sanitizer still
runs on this new log category the same as any other.
##[error]Bash exited with code '1'.
"""

# ── Domain: Networking ────────────────────────────────────────────────────

MOCK_NETWORKING_AWS_FAILURE_LOG = """\
Terraform will perform the following actions:

  # aws_instance.worker will be created

aws_instance.worker: Creating...

Error: creating EC2 Instance: operation error EC2: RunInstances,
https response error StatusCode: 400, RequestID: 8f3a2b1c-...,
api error InvalidSubnetID.NoRoute: subnet-0a1b2c3d4e5f67890 has no route
to an Internet or NAT Gateway, and this instance requires outbound
internet access to reach the configured userdata bootstrap endpoint.

  with aws_instance.worker,
  on compute.tf line 8, in resource "aws_instance" "worker":
   8: resource "aws_instance" "worker" {
"""

MOCK_NETWORKING_AZURE_FAILURE_LOG = """\
##[section]Starting: Deploy ARM Template
az deployment group create --resource-group acme-prod-rg --template-file appservice.bicep

Deployment failed. Correlation ID: 2b3c4d5e-6f7a-8b9c-0d1e-2f3a4b5c6d7e.
{
  "status": "Failed",
  "error": {
    "code": "DeploymentFailed",
    "details": [{
      "code": "HealthProbeFailure",
      "message": "The health probe for backend pool 'acme-app-pool' on
      Application Gateway 'acme-appgw' failed: NSG rule 'DenyAllInbound'
      on subnet 'appgw-subnet' is blocking traffic on port 443 from the
      Application Gateway's own subnet, which the health probe requires."
    }]
  }
}
##[error]Bash exited with code '1'.
"""

# ── Domain: Storage ────────────────────────────────────────────────────────

MOCK_STORAGE_AWS_FAILURE_LOG = """\
Terraform will perform the following actions:

  # aws_s3_bucket.assets will be created

aws_s3_bucket.assets: Creating...

Error: creating S3 Bucket (acme-prod-assets): BucketAlreadyExists: The
requested bucket name is not available. The bucket namespace is shared by
all AWS accounts. Please select a different name and try again.
  status code: 409, request id: 7C3D9E1F2A4B5C6D, host id: (none)

  with aws_s3_bucket.assets,
  on storage.tf line 3, in resource "aws_s3_bucket" "assets":
   3: resource "aws_s3_bucket" "assets" {
"""

MOCK_STORAGE_AZURE_FAILURE_LOG = """\
##[section]Starting: Deploy ARM Template
az deployment group create --resource-group acme-prod-rg --template-file storage.bicep

Deployment failed. Correlation ID: 9d8c7b6a-5f4e-3d2c-1b0a-9f8e7d6c5b4a.
{
  "status": "Failed",
  "error": {
    "code": "StorageAccountAlreadyTaken",
    "message": "The storage account named acmeprodassets is already taken.
    Storage account names must be globally unique across all of Azure."
  }
}
##[error]Bash exited with code '1'.
"""

# ── Domain: Compute ────────────────────────────────────────────────────────

MOCK_COMPUTE_AWS_FAILURE_LOG = """\
Terraform will perform the following actions:

  # aws_instance.app will be created

aws_instance.app: Creating...

Error: creating EC2 Instance: operation error EC2: RunInstances,
https response error StatusCode: 500, RequestID: 3a4b5c6d-...,
api error InsufficientInstanceCapacity: We currently do not have
sufficient c6g.4xlarge capacity in the Availability Zone you requested
(us-east-1c). Our system will be working on provisioning additional
capacity.

  with aws_instance.app,
  on compute.tf line 5, in resource "aws_instance" "app":
   5: resource "aws_instance" "app" {
"""

MOCK_COMPUTE_AZURE_FAILURE_LOG = """\
##[section]Starting: Deploy ARM Template
az deployment group create --resource-group acme-prod-rg --template-file appserviceplan.bicep

Deployment failed. Correlation ID: 1f2e3d4c-5b6a-7c8d-9e0f-1a2b3c4d5e6f.
{
  "status": "Failed",
  "error": {
    "code": "ServerFarmQuotaExceeded",
    "message": "The maximum number of Free App Service Plans allowed in
    a Subscription is 10. Currently there are 10 Free App Service Plans
    in Subscription 'acme-prod'."
  }
}
##[error]Bash exited with code '1'.
"""

# ── Grouped for iteration in tests ───────────────────────────────────────────

IAC_DOMAIN_FIXTURES = {
    "iam_aws": MOCK_IAM_AWS_FAILURE_LOG,
    "iam_azure": MOCK_IAM_AZURE_FAILURE_LOG,
    "networking_aws": MOCK_NETWORKING_AWS_FAILURE_LOG,
    "networking_azure": MOCK_NETWORKING_AZURE_FAILURE_LOG,
    "storage_aws": MOCK_STORAGE_AWS_FAILURE_LOG,
    "storage_azure": MOCK_STORAGE_AZURE_FAILURE_LOG,
    "compute_aws": MOCK_COMPUTE_AWS_FAILURE_LOG,
    "compute_azure": MOCK_COMPUTE_AZURE_FAILURE_LOG,
}
