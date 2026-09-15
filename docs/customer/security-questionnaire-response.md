# Cloud Decoded — Security Questionnaire Response (draft v1)

**Status: draft, not yet reviewed against a real customer's actual
questionnaire.** Answers below are grounded in what's actually built as
of 2026-09-14 (cross-referenced against the codebase, not aspirational).
Before sending this to a real prospect: have Kelvin confirm each answer
still matches reality (this file will go stale exactly like every other
doc in this repo has), and swap in the specific vendor's actual question
wording — most enterprise security reviews use a standard template
(SIG Lite, CAIQ, or a custom one) and this doc is written to answer the
questions those templates ask, not to replace filling one out.

Every answer below is a factual description of the architecture. None of
it is legal advice, and none of it is a compliance attestation — see the
Compliance Status section.

---

## Company & compliance status

**Legal entity:** THD Agentic Systems LLC.

**Compliance attestations held today:** None yet. The architecture is
built to SOC 2 *readiness* standards (per-tenant isolation, audit
logging, access controls, incident response process, data retention
policy) from day one — this is a statement about how the system is
built, not a claim that a SOC 2 Type I or Type II audit has been
completed. State this distinction explicitly to any prospect who asks;
don't let "SOC 2 readiness" get flattened into "SOC 2 compliant" in a
sales conversation.

**Sub-processors:** the LLM provider used for a given call (Anthropic by
default, or the customer's own BYOK provider), the cloud host running
Cloud Decoded's own infrastructure, and Stripe for billing. A full,
current sub-processor list should be maintained and kept current before
this doc goes to a real prospect — this response doesn't hardcode one
because it will drift.

## Data handling

**What data does Cloud Decoded receive?** Only what's needed for the
agents a customer has enabled to do their job: CI/CD log excerpts,
Kubernetes resource state, IaC file contents, billing export data,
dependency manifests. Customers control exactly which systems are
connected and which agents run.

**Is data sanitized before reaching an LLM?** Yes — every piece of text
sent to any LLM passes through a redaction layer first (API keys,
credentials, SSNs, card numbers, phone numbers, and custom patterns are
stripped) before it leaves the request context, regardless of provider.

**Is customer data used to train models?** No. Cloud Decoded does not
train or fine-tune models on customer data. Data sent to an LLM provider
is subject to that provider's own data-use terms for API calls — confirm
current terms with the specific provider (Anthropic, OpenAI) before
stating a blanket "never retained" claim, since provider policies can
change.

**Data retention:** audit log entries are retained indefinitely and
never modified after being written. Sanitized log/diff excerpts used for
a single triage pass are what's stored — not raw source. See the
[Security page](https://theclouddecoded.com/security) for the full
retention summary.

**Data residency:** state the actual hosting region(s) here once
confirmed — don't guess or leave implied.

## Access control & encryption

**How is customer data isolated?** Every table is scoped by workspace,
with row-level security enforced at the database layer, not just
application logic. A query without a workspace scope fails closed.

**Encryption in transit:** TLS for all connections to Cloud Decoded's
API and dashboard.

**Encryption at rest:** BYOK LLM API keys and connected cloud
credentials (AWS role ARNs, Azure Service Principal secrets, GitHub
tokens, Kubernetes cluster tokens) are encrypted at rest and decrypted
only for the duration of the specific call that needs them — never
cached in plaintext, never logged.

**Credential model for connected systems:** GitHub access is a real
GitHub App installation (fine-grained, revocable, short-lived
installation tokens) or a legacy personal access token for older
connections. AWS access is a cross-account IAM role assumed fresh per
call, with an external ID, never a stored access key. Azure access is a
customer-controlled Service Principal. Kubernetes access is a
service-account token scoped to what the enabled agents need.

**Authentication for the product itself:** a workspace token
(Starter/Growth) or, for Enterprise, real OAuth 2.1 via Supabase Auth
with per-user scoped access instead of one shared token.

## Execution model & human oversight

**Can Cloud Decoded's agents take autonomous action against customer
infrastructure?** No. Every agent's execution stops at a human-in-the-loop
approval gate before any proposed change is applied. This is not a
configurable setting — it is how every one of the eleven agents is built.
Detection and diagnosis are automated; execution requires an explicit
human approval, every time.

**What is logged?** Every agent run — approved, held, or rejected — is
written to an immutable audit log with actor, action, resource, outcome,
and timestamp.

**Is there a spend/runaway-execution safeguard?** Yes — every agent
execution has a hard token/spend cap and a call-count circuit breaker.
An execution that exceeds either stops; it does not retry silently.

## Incident response & business continuity

Fill in with the real current process before sending to a prospect:
who's on call, expected notification SLA to affected customers for a
security incident, and backup/recovery posture for the primary
database. Don't leave placeholder claims in a doc that actually ships —
better to say "documented process available on request" than to
overstate an SLA that isn't real yet.

---

**Next step for a real send:** replace every bracketed/instructional
line above with a confirmed current answer, and route through whatever
the prospect's specific questionnaire format is (SIG Lite / CAIQ /
custom). This doc is the source material, not the final deliverable.
