#!/bin/bash
# new-client.sh
# Provisions a complete client environment from templates.
# Usage: bash scripts/new-client.sh <client-slug> <client-name> <tier>
# Example: bash scripts/new-client.sh acme-corp "Acme Corporation" 2

set -e

SLUG=$1
NAME=$2
TIER=$3

if [ -z "$SLUG" ] || [ -z "$NAME" ] || [ -z "$TIER" ]; then
  echo "Usage: bash scripts/new-client.sh <client-slug> <client-name> <tier>"
  echo "Example: bash scripts/new-client.sh acme-corp \"Acme Corporation\" 2"
  exit 1
fi

DATE=$(date +"%Y-%m-%d")
echo ""
echo "Provisioning client: $NAME ($SLUG) — Tier $TIER"
echo ""

# Create directory structure
mkdir -p "clients/$SLUG/environments"
mkdir -p "knowledge/clients/$SLUG/incidents"
mkdir -p "knowledge/clients/$SLUG/escalations"
mkdir -p "knowledge/clients/$SLUG/decisions"
mkdir -p "knowledge/clients/$SLUG/audit-trail"
mkdir -p "knowledge/clients/$SLUG/backups"
mkdir -p "knowledge/clients/$SLUG/dr"

echo "  [OK] Directory structure created"

# Main client config
cat > "clients/$SLUG/config.yaml" << CLIENTEOF
# ═══════════════════════════════════════════════════════════
# KDavis Agentic Platform — Proprietary & Confidential
# Copyright © 2026 Kelvin Davis. All rights reserved.
# Client: $SLUG
# ═══════════════════════════════════════════════════════════

client_slug: $SLUG
client_name: $NAME
tier: $TIER
created: $DATE
status: active

# LLM preference — overrides global active_provider
llm_provider: anthropic

# Cloud provider
cloud: aws                    # aws | azure | gcp | multi

# Stack
kubernetes: none              # eks | aks | gke | none
iac: terraform                # terraform | bicep | arm | cdk | cloudformation
cicd: github-actions          # github-actions | azure-devops | jenkins

# Escalation
escalation_channel: slack     # slack | email | pagerduty
secondary_contact: ""         # email or phone for unanswered escalations

# SLA windows
sla:
  p1_minutes: 15
  p2_minutes: 120
  p3_hours: 24
CLIENTEOF

echo "  [OK] Main config created"

# Dev environment
cat > "clients/$SLUG/environments/dev.yaml" << DEVEOF
# ═══════════════════════════════════════════════════════════
# KDavis Agentic Platform — Proprietary & Confidential
# Copyright © 2026 Kelvin Davis. All rights reserved.
# Client: $SLUG — Environment: DEV
# ═══════════════════════════════════════════════════════════

environment: dev
client_slug: $SLUG
created: $DATE

# Cloud configuration
cloud_account: ""             # AWS account ID or Azure subscription ID
region: ""                    # Primary region
resource_group: ""            # Azure RG or AWS equivalent tag

# Kubernetes (if applicable)
cluster_name: ""
namespace: dev
kubeconfig_secret: ""         # Secret name in secrets manager

# Database (if applicable)
db_host: ""
db_name: ""
db_secret: ""                 # Secret name — never plaintext

# Backup policy
backup:
  enabled: true
  schedule: "0 2 * * *"       # Daily at 2am
  retention_days: 7
  destination: ""             # S3 bucket or Azure Storage Account

# Disaster recovery
disaster_recovery:
  rto_hours: 24               # Recovery Time Objective
  rpo_hours: 4                # Recovery Point Objective
  enabled: false              # DR not required for dev

# Promotion gate
promotion_target: staging
promotion_requires_approval: true
DEVEOF

echo "  [OK] Dev environment config created"

# Staging environment
cat > "clients/$SLUG/environments/staging.yaml" << STAGEOF
# ═══════════════════════════════════════════════════════════
# KDavis Agentic Platform — Proprietary & Confidential
# Copyright © 2026 Kelvin Davis. All rights reserved.
# Client: $SLUG — Environment: STAGING
# ═══════════════════════════════════════════════════════════

environment: staging
client_slug: $SLUG
created: $DATE

# Cloud configuration
cloud_account: ""
region: ""
resource_group: ""

# Kubernetes (if applicable)
cluster_name: ""
namespace: staging
kubeconfig_secret: ""

# Database (if applicable)
db_host: ""
db_name: ""
db_secret: ""

# Backup policy
backup:
  enabled: true
  schedule: "0 1 * * *"       # Daily at 1am
  retention_days: 14
  destination: ""

# Disaster recovery
disaster_recovery:
  rto_hours: 8
  rpo_hours: 2
  enabled: true
  failover_region: ""

# Promotion gate
promotion_target: prod
promotion_requires_approval: true
STAGEOF

echo "  [OK] Staging environment config created"

# Production environment
cat > "clients/$SLUG/environments/prod.yaml" << PRODEOF
# ═══════════════════════════════════════════════════════════
# KDavis Agentic Platform — Proprietary & Confidential
# Copyright © 2026 Kelvin Davis. All rights reserved.
# Client: $SLUG — Environment: PROD
# ═══════════════════════════════════════════════════════════

environment: prod
client_slug: $SLUG
created: $DATE

# Cloud configuration
cloud_account: ""
region: ""
resource_group: ""

# Kubernetes (if applicable)
cluster_name: ""
namespace: prod
kubeconfig_secret: ""

# Database (if applicable)
db_host: ""
db_name: ""
db_secret: ""

# Backup policy
backup:
  enabled: true
  schedule: "0 0 * * *"       # Daily at midnight
  retention_days: 30
  destination: ""
  cross_region_backup: true
  backup_region: ""

# Disaster recovery
disaster_recovery:
  rto_hours: 4
  rpo_hours: 1
  enabled: true
  failover_region: ""
  cross_region_failover: true
  dr_drill_schedule: "0 10 1 * *"   # Monthly drill
  notification_channel: pagerduty

# Promotion gate
promotion_target: none
promotion_requires_approval: false   # Already in prod
emergency_bypass_authority: ""       # Name and role

# License
license_key: ""               # Set by package builder
license_issued: $DATE
license_tier: $TIER
PRODEOF

echo "  [OK] Production environment config created"

# Onboarding note
cp knowledge/_templates/client-onboarding.md \
   "knowledge/clients/$SLUG/onboarding.md" 2>/dev/null || \
cat > "knowledge/clients/$SLUG/onboarding.md" << ONEOF
# Client Onboarding — $NAME

**Date:** $DATE
**Tier:** $TIER
**Slug:** $SLUG
**Status:** In Progress

## Checklist

### Access
- [ ] Cloud console read access confirmed
- [ ] Kubernetes cluster access (if applicable)
- [ ] GitHub/ADO repository access
- [ ] Monitoring platform access
- [ ] Secrets manager access (scoped)

### Governance Sign-Off
- [ ] MISSION.md reviewed with client
- [ ] FACTORY_RULES.md v1.1.0 approved
- [ ] ESCALATION_PROTOCOL.md v1.1.0 walkthrough complete
- [ ] AUDIT_POLICY.md signed off
- [ ] License agreement signed

### Environments
- [ ] Dev config completed: clients/$SLUG/environments/dev.yaml
- [ ] Staging config completed: clients/$SLUG/environments/staging.yaml
- [ ] Prod config completed: clients/$SLUG/environments/prod.yaml
- [ ] DR config verified for prod

### First Run
- [ ] Health check passing: bash scripts/health-check.sh
- [ ] Simulated issue run against dev environment
- [ ] Escalation format walkthrough with client contact
- [ ] Secondary contact confirmed for unanswered escalations

## Stack Details
- Cloud: [fill in]
- Kubernetes: [fill in]
- IaC: [fill in]
- CI/CD: [fill in]
- LLM Provider: [fill in]

## Notes
[Add client-specific notes here]
ONEOF

echo "  [OK] Onboarding checklist created"

# Log to operator registry
mkdir -p knowledge/operator
LICENSE_REGISTRY="knowledge/operator/client-registry.md"
if [ ! -f "$LICENSE_REGISTRY" ]; then
  cat > "$LICENSE_REGISTRY" << REGEOF
# Client Registry — KDavis Agentic Platform

| Date | Client | Slug | Tier | Status | License Key |
|------|--------|------|------|--------|-------------|
REGEOF
fi

echo "| $DATE | $NAME | $SLUG | T$TIER | provisioned | pending |" \
  >> "$LICENSE_REGISTRY"

echo "  [OK] Client registry updated"
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Client provisioned: $NAME"
echo ""
echo "  Next steps:"
echo "  1. Fill in clients/$SLUG/environments/*.yaml"
echo "  2. Complete knowledge/clients/$SLUG/onboarding.md"
echo "  3. Get license agreement signed"
echo "  4. Run: bash scripts/health-check.sh"
echo "  5. Run simulated issue against dev environment"
echo "═══════════════════════════════════════════════════════"
echo ""
