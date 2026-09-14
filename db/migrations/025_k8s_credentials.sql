-- Migration 025: per-workspace Kubernetes cluster credentials (Phase 4,
-- connectivity gap roadmap).
--
-- Replaces the global stopgap -- one KUBECONFIG_YAML env var + one shared
-- kubeconfig file for the WHOLE platform (api/main.py's
-- _write_kubeconfig_from_env, core/workspace_credentials.py's
-- resolve_k8s_context mapping cloud_provider -> a K8S_CONTEXT_AWS/AZURE env
-- var) -- with a real per-workspace credential, mirroring the AWS
-- (cross-account role) / Azure (Service Principal) / Azure DevOps (PAT)
-- shape already proven in this same table.
--
-- Two agents read this:
--   Agent 02 (K8sTools) already made direct K8s REST API calls shaped
--     exactly like this (k8s_api_url + bearer token) -- it just had no
--     per-workspace storage, silently falling back to a shared
--     os.environ["K8S_API_URL"]/["K8S_TOKEN"] (the same class of gap
--     GAPS.md #7 found and fixed for agents 04/10).
--   Agent 08 (DriftTools) uses kubectl as a subprocess, not the REST API
--     directly -- core.workspace_credentials.build_kubeconfig() turns
--     these same three fields into a minimal single-cluster kubeconfig
--     for kubectl to use via --kubeconfig, replacing the global-file +
--     --context model for any workspace that has its own credentials
--     configured. resolve_k8s_context/the global KUBECONFIG_YAML stay as
--     the fallback for workspaces that haven't connected their own
--     cluster yet (today's only real customer).
--
-- k8s_ca_cert_encrypted is optional: a cluster fronted by a publicly-
-- trusted cert (e.g. behind an ALB with an ACM cert) doesn't need one --
-- both verify_k8s_connection (httpx) and build_kubeconfig (kubectl) fall
-- back to standard system CA trust when it's absent. Never silently skip
-- TLS verification either way.

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS k8s_api_url TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS k8s_token_encrypted TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS k8s_ca_cert_encrypted TEXT;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS k8s_verified_at TIMESTAMPTZ;
