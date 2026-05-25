# PROMPT: new-client-package
# Usage: Paste this entire block into a new Claude conversation
# to generate a complete client deployment package.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

BUILD A CLIENT DEPLOYMENT PACKAGE:

Client name:            [full name]
Client slug:            [slug — lowercase, hyphens only]
Cloud:                  [aws | azure | gcp | multi]
Kubernetes:             [eks | aks | gke | none]
IaC:                    [terraform | bicep | arm | cdk | cloudformation]
CI/CD:                  [github-actions | azure-devops | jenkins]
Environments:           [dev only | dev+staging | dev+staging+prod]
Special needs:          [compliance, air-gapped, on-prem, etc.]

STACK DETAILS:
[Describe exactly what the client runs — app services, functions,
databases, queues, storage, APIs, microservices, etc. Be specific.]

SCALE PROFILE:
Applications to monitor:      [X]
Expected daily incidents:     [X]
Peak concurrent incidents:    [X]
Growth projection 12 months:  [X apps]

Based on scale inputs determine automatically:
- Scaling model:
    1-20 apps     → vertical (single threaded, no queue)
    20-100 apps   → horizontal (worker pool, SQS/Service Bus)
    100+ apps     → queue-based (autoscaled, distributed locking,
                    batch escalation)
- Tier recommendation (1 | 2 | 3)
- Whether lock manager is included
- Whether queue infrastructure is included
- Worker pool size (1 | up to 10 | autoscaled)
- Whether batch escalation aggregation is needed
- Global daily LLM budget cap value
- Queue type (SQS for AWS | Service Bus for Azure)

PACKAGE CONSTRAINTS:
- Include only agents relevant to their cloud and stack
- Include only workflows relevant to their environment
- Include scale infrastructure components only if needed
- No operator files — no vault contents, no pricing, no personal notes
- No agents for clouds they don't use
- Target compressed size:
    Tier 1 (vertical):      < 2MB
    Tier 2 (horizontal):    < 5MB
    Tier 3 (queue-based):   < 10MB
- Every file stamped with client slug and license key header
- Proprietary copyright notice in every file

BUILD THE FOLLOWING — IN ORDER:
1. Run: bash scripts/new-client.sh [slug] "[name]" [tier]
2. Fill all environment configs for their specific stack
3. Scale assessment document for this client
4. Select agents relevant to their stack:
   - Always include: triage, validate, docs, backup, fix-dispatcher
   - Include if applicable: monitoring, storage, iac, deployment,
     security, rbac, pipeline, networking, migration, dr, finops
   - Include if Tier 2+: lock-manager
   - Include if Tier 3: queue-manager, worker-pool, batch-escalation
5. Select workflows relevant to their stack
6. Generate scale infrastructure configs if needed:
   - SQS queue Terraform (AWS Tier 2+)
   - Service Bus Terraform (Azure Tier 2+)
   - Lambda worker Terraform (AWS Tier 2+)
   - Azure Functions worker Terraform (Azure Tier 2+)
   - Autoscaling config (Tier 3 only)
7. Generate client-facing README
8. Generate client SOPs for their specific stack:
   - SOP-[Slug]-Getting-Started.docx
   - SOP-[Slug]-Escalation-Handling.docx
   - SOP-[Slug]-Disaster-Recovery.docx
   - SOP-[Slug]-Environment-Promotion.docx
   - SOP-[Slug]-Scale-Architecture.docx (Tier 2+ only)
9. Generate compressed package manifest
10. License key placeholder for package builder
11. Client quote using generate-quote format with scale assessment
