# Cloud Decoded — Setup Guide

This is the real, current connection flow — grounded directly in the
routes that exist today (`api/routes/workspace_credentials.py`, `api/routes/workspaces.py`).
No video yet; this is the written version referenced in the build order
as the thing to ship first.

## 1. Create your workspace

`POST /workspaces` with your company name returns a workspace token.
**Save it immediately — it's shown exactly once and never stored in
plaintext on our side.** Every request to Cloud Decoded after this point
authenticates with `X-Workspace-Token: <your token>`.

If you lose it, an admin-initiated token rotation is the only recovery
path — the old token stops working the moment a new one is issued.

## 2. Start your trial and connect billing

New workspaces start `pending_payment` — nothing runs until checkout
completes. From the dashboard, start checkout; every plan includes a
free trial period before the first charge.

## 3. Connect the systems your agents will touch

You only need to connect what the agents you're using actually touch.
Starter ships with CI/CD Triage, Kubernetes Alerts, and PR Review — most
teams start with GitHub (or Azure DevOps) and, if using the Kubernetes
agent, a cluster connection **and** the separate alert-source webhook
below (the cluster connection lets agents read/act on your cluster; the
webhook is what actually delivers alerts to us in the first place — you
need both for the Kubernetes Alert agent to do anything).

### GitHub (recommended path)

Install the Cloud Decoded GitHub App from your dashboard's Connections
page — this is a real GitHub App install, not a personal access token.
You get fine-grained, revocable permissions, and commits/PRs are
attributed to "Cloud Decoded," not a personal account. You can revoke
access at any time from your own GitHub organization settings.

*(Legacy PAT-based connections from before this App existed still work,
but new connections go through the App install flow.)*

### Azure DevOps

From Connections, enter your Azure DevOps organization name and a
Personal Access Token scoped to **Code (Read & Write)**. We verify the
token against your organization before storing it. A webhook secret is
minted the first time you connect — save it and register it as your
Azure DevOps service hook's Basic auth password; it's shown once.

### AWS

Click "Start AWS role setup" to get a trust policy and a permissions
policy, plus a unique external ID. In AWS IAM, create a role using that
trust policy as its trust relationship, and attach the permissions
policy as an inline policy. Paste the resulting role ARN back into
Cloud Decoded. We assume the role fresh on every call — nothing is
cached, and we never ask for a raw access key.

### Azure (Service Principal)

Create a Service Principal with **Contributor** access to the
subscription your agents should act on (not just Reader — the FinOps
and IAM agents actually apply changes, not just read). Enter the
tenant ID, client ID, client secret, and subscription ID in Connections.
We verify access before storing anything.

### Kubernetes

If you're using the Kubernetes Alert or Drift Detection agents against
your own cluster, provide the cluster's API server URL, a
service-account bearer token scoped to what the agents need, and — for
almost every real cluster (EKS and AKS both use a private CA by
default) — the cluster's CA certificate. We verify a real authenticated
call to the cluster before storing anything, and cluster access is
never shared across workspaces.

## 4. (Optional) Bring your own LLM key

By default, Cloud Decoded uses its own model access. If you'd rather use
your own Anthropic or OpenAI key — for cost control, compliance, or
model preference — save it from the dashboard. Your key is encrypted at
rest and decrypted only for the duration of the specific call that needs
it.

### Alert sources (Kubernetes and general cloud resource health)

Separate from the credential connections above -- this registers a
push-driven webhook so alerts show up automatically the moment your
cloud provider fires them, no polling needed. Register once from
Connections → the relevant card's "How to set this up" panel, which
pre-fills your real webhook URL.

**Azure Monitor (AKS pod alerts or general resource health -- Agent 02 /
Agent 11):**
1. Register the resource providers first, on the subscription:
   `Microsoft.Insights` and `Microsoft.AlertsManagement`. An
   unregistered provider is the most common reason a freshly-created
   Action Group's webhook silently never fires.
2. Create an Action Group, then add an action of type **Webhook — not
   "Secure Webhook."** Secure Webhook requires an Azure AD handshake we
   don't implement.
3. Turn the **Common Alert Schema** toggle ON for the webhook action.
   This isn't optional — the legacy schema is a different payload shape
   and is silently dropped, not an error, so it's easy to miss.
4. Paste your workspace's webhook URL (shown in Connections, already
   includes your token).
5. Test it: in the Azure Portal, open the Action Group → **Test action
   group** → sample type **Metric alert**.

**AWS CloudWatch / SNS (Agent 11):**
Subscribe your workspace's webhook URL as an HTTPS endpoint on an SNS
topic that your CloudWatch Alarms (or GuardDuty findings via
EventBridge → SNS) publish to. The subscription confirms automatically
— nothing further needed on your side. Every alert's signature is
verified against AWS's own signing certificate before it's trusted.

**Prometheus Alertmanager / Grafana unified alerting (Agent 02):**
Register the same webhook URL as a `webhook_configs` receiver
(Alertmanager) or webhook contact point (Grafana) — both are detected
automatically.

## 5. Watch the first triage happen

Once you've connected at least one system, trigger the relevant webhook
(a failed CI run, a firing Kubernetes alert) or run an agent manually
from the dashboard. You'll see a real proposal — a diagnosis and one or
more remediation options — land in your HITL queue. **Nothing executes
until you approve it.** Approve, edit, hold, or reject — every path is
logged.

## Enterprise: MCP / OAuth 2.1 access

Enterprise-tier workspaces can connect via the Model Context Protocol
server (`mcp.theclouddecoded.com`) using real OAuth 2.1, not a shared API
key. This is provisioned per named user by your Cloud Decoded contact
after your plan is active — reach out to get your team's engineers set
up with their own scoped credentials.

---

**Next:** [Agent Reference](./agent-reference.md) for what each agent
does and what it needs your approval for.
