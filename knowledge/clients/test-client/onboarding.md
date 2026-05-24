# Client Onboarding — {{client_name}}

**Date:** {{date}}
**Tier:** {{tier}} <!-- Tier 1 | Tier 2 | Tier 3 -->
**Primary Contact:** {{contact}}
**MRR:** {{mrr}}

## Stack
- **Cloud:** {{cloud}} <!-- AWS | Azure | GCP | Multi -->
- **Kubernetes:** {{k8s}} <!-- EKS | AKS | GKE | None -->
- **IaC:** {{iac}} <!-- Terraform | Bicep | CDK | CloudFormation -->
- **CI/CD:** {{cicd}}
- **LLM Provider:** {{llm_provider}}

## Access Granted
- [ ] Cloud console read access
- [ ] Kubernetes cluster access (kubeconfig)
- [ ] GitHub/ADO repository access
- [ ] Monitoring platform access
- [ ] Secrets manager access (scoped)

## Agent Configuration
- Provider override: {{llm_provider}}
- Config location: clients/{{client_slug}}/config.yaml
- Secrets location: clients/{{client_slug}}/secrets.enc

## Governance Files Deployed
- [ ] MISSION.md reviewed with client
- [ ] FACTORY_RULES.md approved
- [ ] ESCALATION_PROTOCOL.md walkthrough complete
- [ ] AUDIT_POLICY.md signed off

## First 30 Days
<!-- What gets built, configured, and validated in the first month. -->
