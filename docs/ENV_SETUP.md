# Environment Variable Setup Guide

## Before First Build Session

### Brevo (replaces Systeme.io, 2026-09-16)
Systeme.io is no longer used anywhere in this platform — its public API
never actually exposed a campaigns/sequences endpoint (confirmed 404 on
every plausible path, both here and independently in the sibling
kdavis-microsaas-engine repo). Brevo replaces it for all contact sync
and nurture-sequence automation. See leads/integrations/brevo_client.py's
module docstring for the full integration shape.

1. Log into Brevo (app.brevo.com)
2. Go to Contacts → Settings → Contact Attributes and create two custom
   attributes: `PRODUCT_ID` (text) and `LEAD_STAGE` (text) — these are
   what this codebase writes on every contact sync
   (leads/capture/signup_handler.py's `_sync_to_brevo`), replacing the
   old per-stage Systeme.io tags
3. Go to Settings → SMTP & API → API Keys, generate a new key
4. Copy the key into `BREVO_API_KEY` in .env
5. (Optional, per product that wants Brevo-driven nurture automation)
   Create a contact list for that product in Brevo, then build the
   nurture automation by hand in Brevo's UI, triggered off contact
   attribute values or list membership — Brevo has no API for creating
   the automation/sequence itself, only for adding/updating contacts and
   list membership. There is nothing to configure in .env per product —
   unlike the old Systeme.io tag-ID-per-stage model, Brevo automations
   key off the `LEAD_STAGE`/`PRODUCT_ID` attribute values directly.
6. (Optional) Set `BREVO_WEBHOOK_SECRET` in .env and configure a webhook
   in Brevo pointing at this platform's webhook receiver
   (leads/integrations/webhook_receiver.py) if you want unsubscribe/
   contact-update events reconciled back onto the `leads` table.

### Apollo
1. Log into apollo.io
2. Go to Settings → Integrations → API
3. Generate API key
4. Copy into APOLLO_API_KEY in .env
