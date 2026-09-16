# SOP: Systeme.io Replaced With Brevo for Email/Lead Nurture
Date: 2026-09-16
Status: Live — committed, pushed, deploying to Railway

---

## What changed and why

Kelvin's directive: "not using systeme.io. using brevo for emails. that needs to change." Systeme.io was never actually a working integration in this repo — `leads/integrations/systeme_io.py`'s own docstring admitted its endpoint paths were "best-effort... verify against current docs," never confirmed working. The sibling `kdavis-microsaas-engine` repo already made this exact same provider swap on 2026-08-14, after confirming directly against a live account that Systeme.io's public API has **no campaigns/sequences endpoint at all** — every plausible path 404s. This session ported that proven, working pattern into this repo rather than building a fresh Brevo integration from scratch.

## What was built

- `leads/integrations/brevo_client.py` (new) — direct port of MSE's `core/brevo_client.py`. Uses the real installed `brevo-python==5.0.2` package (confirmed against the identical version already in production use in MSE). `create_or_update_contact`, `get_contact`, `add_to_list`, `remove_from_list`, `get_lists`.
- `leads/integrations/systeme_io.py` — **deleted** (this repo's convention: delete unused code, never leave a "removed" shim).
- `leads/capture/signup_handler.py` / `trial_handler.py` — Systeme.io's tag-based sync (`product_{id}_trial_active`, etc.) replaced with Brevo custom contact attributes (`PRODUCT_ID`, `LEAD_STAGE`) — Brevo has no freeform-tag concept; its automations trigger off attribute values or list membership instead.
- `leads/integrations/webhook_receiver.py` — event handling updated to Brevo's real webhook event types (`contact_updated`, `unsubscribed`); two Systeme.io-specific event types with no Brevo equivalent were dropped rather than faked.
- `.env.example` — 11 unused `SYSTEME_TAG_*` vars removed (confirmed dead — never read by any code) in favor of `BREVO_API_KEY`/`BREVO_WEBHOOK_SECRET`.
- `.github/workflows/email-sequence-deploy.yml` — converted to an explicit, well-documented no-op. Brevo has no "deploy a sequence" API — automations are built once, by hand, per product, in the Brevo UI. The workflow file's header explains exactly what a real future equivalent action would need to do (nothing to Brevo itself; just mark the row `deployed` and ensure the per-signup code path uses the right `list_id`), so a future session doesn't have to re-derive this.
- `CLAUDE.md` — every Systeme.io-era passage in the Lead Capture section is left in place as historical build-order narrative, under one clear correction banner at the top of that section (matching the file's own existing precedent for marking superseded content), rather than rewritten line-by-line into something that never actually happened.
- `finance/accounting/expense_categorizer.py` — added "brevo" as a recognized vendor keyword; kept "systeme.io" (a real historical expense receipt might still reference it).

## Test coverage

`tests/test_brevo_client.py` (new, 10 tests, same SDK-mocking pattern as MSE's own Brevo test suite) + `tests/test_leads_capture.py` rewritten for Brevo (Systeme.io-specific tests removed). Full suite: **1780 passed, 4 failed** — confirmed the 4 failures are the pre-existing baseline (`test_diagnose_node_returns_three_options` + 3 secret-redaction tests) already documented as unrelated in prior sessions' commits (e.g. the ServiceNow integration commit's own "1768 passed, 4 failed — same pre-existing baseline" note). Zero regressions from this change.

## Still open

- **`BREVO_API_KEY` is not actually set anywhere yet** — Kelvin needs to sign up for Brevo (free tier: 300 emails/day, 100K contacts) and add the real key. Every code path fails closed with a clear `ConfigurationError` until then, same as Systeme.io's old unconfigured state — no regression, just not yet live.
- **No Brevo contact list or automation workflow exists for any product yet** — those are built by hand, per product, in Brevo's own UI (see MSE's `BREVO_SETUP.md` for the exact steps to mirror), not something code can create.
- This session's separate email-sequence-persistence work (`db/migrations/039_email_sequences.sql`, `email_sequence_agent`) does not call Brevo at all yet — it only drafts and persists for HITL review. Wiring an approved sequence to actually add a contact to the right Brevo list is real future work, not done here.

---

## If this breaks again

- **A lead signup silently doesn't sync to Brevo:** check for a logged `ConfigurationError` — `BREVO_API_KEY` not being set fails closed by design, same as every other not-yet-configured integration in this repo. Not a bug.
- **"Attribute not found" errors from Brevo:** custom attributes (`PRODUCT_ID`, `LEAD_STAGE`) must already exist in the Brevo account's contact attribute schema before `create_or_update_contact` can set them — this is a one-time manual setup step in Brevo's UI, not something the code can create on the fly.
- **Someone asks why `email-sequence-deploy.yml` "does nothing":** that's intentional — read the workflow file's own header comment for the full explanation before assuming it's broken.
