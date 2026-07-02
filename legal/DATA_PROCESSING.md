# Data Processing Disclosure
# THD Agentic Systems LLC — Cloud Decoded Platform

## BYOK Data Handling Policy

Version: 1.0 | Effective: 2026-01-01

### What Data We Process

When you use the Cloud Decoded platform, the following data flows through our systems:

| Data Type | How It's Handled |
|-----------|-----------------|
| LLM API Keys (BYOK) | Encrypted at rest (AES-256/Fernet), never logged in plain text, used only for your workspace incidents |
| CI/CD Pipeline Logs | Sanitized by DataSanitizationShield before LLM processing — PII and credentials are redacted |
| Kubernetes Event Logs | Sanitized before processing; raw logs are not stored — only the SHA-256 hash |
| IAM Policies | Read-only access only; policy documents are processed in-memory and not persisted beyond the incident |
| Infrastructure Config | Scrubbed for secrets before LLM transmission; originals never stored on our servers |
| Incident Records | Stored in your workspace's isolated database partition; includes parsed (sanitized) error text and remediation options only |

### What We Do NOT Store

- Raw (unsanitized) log files
- LLM API keys in plain text
- Connection strings or database credentials
- AWS/Azure access keys
- Bearer tokens or session tokens
- Contents of .env files

### Data Isolation

Each workspace (customer) operates in a fully isolated partition:
- All database records are scoped by `workspace_id` with row-level security
- One workspace cannot access another workspace's incidents, logs, or configuration
- BYOK keys are stored per-workspace and never shared across workspaces

### Data Retention

| Record Type | Retention Period |
|-------------|-----------------|
| Incident records | 90 days (configurable for Enterprise) |
| Audit logs | 1 year |
| Workspace config | Until account deletion |
| LLM call logs | 30 days |

### Your Rights

You may request:
- Export of all incident records for your workspace (JSON format)
- Deletion of all workspace data upon account cancellation
- Audit log access for your workspace's agent activity

Contact: privacy@kdavisagentic.com

### Sub-processors

| Sub-processor | Purpose | Data Shared |
|---------------|---------|-------------|
| Supabase | Database hosting | Incident records, workspace config |
| Stripe | Billing | Email, payment method, subscription status |
| Your LLM Provider (BYOK) | AI inference | Sanitized log excerpts only |

### BYOK Security Guarantee

Your LLM API key is:
1. Encrypted using Fernet (AES-128-CBC with PKCS7 padding + HMAC-SHA256) before storage
2. Decrypted in-memory only at the moment of the API call
3. Never written to log files, audit trails, or incident records
4. Automatically revoked from our systems upon subscription cancellation

The encryption key (`ENCRYPTION_KEY` env var) is held by the platform operator and never
shared with sub-processors.
