# Cloud Decoded — DPA Outline (NOT a legal document)

**This is a structural checklist for briefing an attorney, not a
Data Processing Agreement.** Do not send this to a customer, and do not
treat any sentence below as binding contract language. A real DPA has to
be drafted (or at minimum reviewed line-by-line) by a licensed attorney
who knows your actual data flows, your actual sub-processors, and the
specific jurisdictions your customers are in (GDPR, CCPA, and other
regimes impose different mandatory clauses). This file exists so that
conversation starts from an accurate picture of what the product
actually does, instead of a generic template that doesn't match reality.

Per Build-Order.md: "DPA template (shared with MSE legal)" — that's the
right next step. Bring this outline to that conversation, not a
signed-ready document.

---

## What an attorney will need from you to draft the real thing

1. **The actual data flows** — this outline lists them below, but
   confirm against the live codebase before the attorney relies on it;
   this repo changes.
2. **Full current sub-processor list** — every service that ever
   receives customer data. As of 2026-09-14: the active LLM provider per
   call (Anthropic by default, or a customer's own BYOK provider),
   Stripe (billing data only), the database/hosting provider. Confirm
   this list is current before handing it over — it will have changed
   by the time this is read.
3. **Which jurisdictions your customers are actually in** — determines
   whether GDPR Standard Contractual Clauses, CCPA terms, or other
   region-specific language is required.
4. **Your actual incident notification capability** — don't let a DPA
   promise a notification SLA the team can't actually meet.
5. **Data deletion mechanics** — confirm what "delete my data" actually
   does today (workspace archival vs. hard deletion) before promising a
   specific deletion timeline in writing.

## Sections a real Cloud Decoded DPA will likely need

Standard DPA structure, for the attorney's reference — not drafted here:

- **Definitions** (controller, processor, personal data, sub-processor)
- **Scope and duration of processing** — tied to the underlying MSA/ToS
- **Nature and purpose of processing** — what Cloud Decoded's agents
  actually do with connected-system data (CI/CD logs, IaC state,
  billing exports, dependency manifests — see the security questionnaire
  response doc for the current factual list)
- **Sub-processor authorization and notification** — general vs. specific
  authorization, and the process for adding a new sub-processor
- **Security measures (Article 32 GDPR-style annex)** — this can lean on
  the factual content already in `security-questionnaire-response.md`
- **International transfer mechanism** (SCCs, or another valid basis) if
  any sub-processor is outside the customer's region
- **Data subject rights assistance** — how Cloud Decoded helps a
  customer respond to an access/deletion/portability request
- **Breach notification** — timeline and method, must match what
  operations can actually deliver
- **Audit rights** — what a customer can request and how
- **Deletion/return of data on termination** — must match the actual
  archival-vs-deletion mechanics in the product today
- **Liability and indemnification** — attorney-drafted, no substitute

## What NOT to do with this file

- Do not fill in the bracketed sections above and send it as-is.
- Do not let this file's existence create the impression a real DPA is
  ready — it isn't, until an attorney has actually produced one.
- Do not promise a specific breach-notification SLA or deletion
  timeline in a customer-facing doc until this file's contents have been
  through real legal review.
