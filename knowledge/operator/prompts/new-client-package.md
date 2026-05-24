# PROMPT: new-client-package
# Usage: Paste this entire block into a new Claude conversation
# to generate a complete client deployment package.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

BUILD A CLIENT DEPLOYMENT PACKAGE:

Client name:       [full name]
Client slug:       [slug — lowercase, hyphens only]
Tier:              [1 | 2 | 3]
Cloud:             [aws | azure | gcp | multi]
Kubernetes:        [eks | aks | gke | none]
IaC:               [terraform | bicep | arm | cdk | cloudformation]
CI/CD:             [github-actions | azure-devops | jenkins]
Environments:      [dev only | dev+staging | dev+staging+prod]
Special needs:     [compliance requirements, air-gapped, on-prem, etc.]

STACK DETAILS:
[Describe exactly what the client runs — app services, functions,
databases, queues, storage, APIs, etc. Be specific.]

BUILD THE FOLLOWING — IN ORDER:
1. bash scripts/new-client.sh [slug] "[name]" [tier]
2. Fill all environment configs for their specific stack
3. Select agents relevant to their stack only
4. Select workflows relevant to their stack only
5. Generate client-facing README
6. Generate client SOPs for their specific stack:
   - SOP-[Slug]-Getting-Started.docx
   - SOP-[Slug]-Escalation-Handling.docx
   - SOP-[Slug]-Disaster-Recovery.docx
   - SOP-[Slug]-Environment-Promotion.docx
7. Generate compressed package manifest
8. License key placeholder for package builder
9. Client quote

PACKAGE CONSTRAINTS:
- Include only agents and workflows for their cloud and stack
- No operator files — no vault contents, no pricing, no your notes
- No agents for clouds they don't use
- Target size: Tier 1 < 2MB | Tier 2 < 5MB | Tier 3 < 10MB
- Every file stamped with client slug and license key header
- Proprietary notice in every file

QUOTE FORMAT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLIENT QUOTE
Client:       [Client Name]
Date:         [Date]
Prepared by:  Kelvin Davis — KDavis Agentic Platform
Quote ref:    [SLUG-YYYYMMDD-001]

SCOPE OF WORK
[What the client is getting — plain business language.
What problems it solves. What it replaces.]

LINE ITEMS
Initial Build Fee
Platform deployment and configuration    $[X]
Environment setup (dev/staging/prod)     $[X]
Agent configuration for their stack      $[X]
Governance walkthrough and sign-off      $[X]
Documentation and SOPs                   $[X]
Testing and validation                   $[X]
                             Subtotal:   $[X]

Monthly Retainer
Platform operations                      $[X]/mo
24/7 monitoring and alerting             $[X]/mo
Incident response (< [X]hr SLA)          $[X]/mo
Monthly cost optimization review         $[X]/mo
                             Subtotal:   $[X]/mo

Optional Add-Ons
Disaster recovery setup                  $[X]
Additional environment                   $[X]
Custom agent development                 $[X]/agent
                             Subtotal:   $[X]

TOTAL
One-time build:     $[X]
Monthly retainer:   $[X]/mo
First month total:  $[X]

ROI REFERENCE
One senior DevOps engineer:   $[loaded_cost]/mo
This platform (Tier [X]):     $[retainer]/mo
Monthly savings:              $[delta]/mo
Breakeven:                    [X] months

VALIDITY: 30 days from date above.
To proceed: sign license agreement and return with
50% deposit of build fee.

NOTES:
[Client-specific assumptions or exclusions]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
