#!/bin/bash
# new-client.sh
# Provisions a new client environment from templates.
# Usage: bash scripts/new-client.sh <client-slug> <client-name>
# Example: bash scripts/new-client.sh acme-corp "Acme Corporation"

set -e

SLUG=$1
NAME=$2

if [ -z "$SLUG" ] || [ -z "$NAME" ]; then
  echo "Usage: bash scripts/new-client.sh <client-slug> <client-name>"
  echo "Example: bash scripts/new-client.sh acme-corp \"Acme Corporation\""
  exit 1
fi

echo "Provisioning client: $NAME ($SLUG)"

# Create client config directory
mkdir -p "clients/$SLUG"
mkdir -p "knowledge/clients/$SLUG/incidents"
mkdir -p "knowledge/clients/$SLUG/escalations"
mkdir -p "knowledge/clients/$SLUG/decisions"
mkdir -p "knowledge/clients/$SLUG/audit-trail"

# Client config
cat > "clients/$SLUG/config.yaml" << CLIENTEOF
client_slug: $SLUG
client_name: $NAME
created: $(date +"%Y-%m-%d")

# LLM preference — overrides global active_provider for this client
llm_provider: anthropic

# Cloud provider
cloud: aws  # aws | azure | gcp | multi

# Stack
kubernetes: eks  # eks | aks | gke | none
iac: terraform
cicd: github-actions
CLIENTEOF

# Onboarding note from template
cp knowledge/_templates/client-onboarding.md "knowledge/clients/$SLUG/onboarding.md"
sed -i "s/{{client_name}}/$NAME/g" "knowledge/clients/$SLUG/onboarding.md"
sed -i "s/{{client_slug}}/$SLUG/g" "knowledge/clients/$SLUG/onboarding.md"
sed -i "s/{{date}}/$(date +"%Y-%m-%d")/g" "knowledge/clients/$SLUG/onboarding.md"

echo ""
echo "Client provisioned:"
echo "  Config:     clients/$SLUG/config.yaml"
echo "  Knowledge:  knowledge/clients/$SLUG/"
echo ""
echo "Next steps:"
echo "  1. Fill in clients/$SLUG/config.yaml with their stack details"
echo "  2. Complete knowledge/clients/$SLUG/onboarding.md"
echo "  3. Deploy governance files for this client"
echo "  4. Run health check: bash scripts/health-check.sh"
