# SOP: Approving and Editing Email Templates (Cloud Decoded)
Date created: 2026-09-21
Product: Cloud Decoded
Status: Live

## When this applies
A template in the email lifecycle system (migration 051 — onboarding,
dunning, winback, newsletter, etc.) sits at `pending_approval` until you
approve it. Nothing at `pending_approval` or `retired` ever sends —
`core/marketing_email.py`'s `send_marketing_email` raises if the scheduler
ever reaches a non-approved template, which should never happen since the
scheduler only queries `status = 'approved'` templates in the first place.

## Where to do this
Until the CEO Decoded dashboard's Email Campaign queue ships (a separate
build), use the API directly:

```
GET  {API_BASE_URL}/api/v1/internal/email/templates?status_filter=pending_approval
GET  {API_BASE_URL}/api/v1/internal/email/templates/{key}
PUT  {API_BASE_URL}/api/v1/internal/email/templates/{key}
POST {API_BASE_URL}/api/v1/internal/email/templates/{key}/approve
POST {API_BASE_URL}/api/v1/internal/email/templates/{key}/retire
```

All require `Authorization: Bearer <your Supabase session token>` — the
same login as the CEO Decoded dashboard, `user_metadata.role == "admin"`.
Full contract in `docs/internal/email-approval-api.md`.

## Reviewing a template
1. `GET /templates/{key}` — read `rendered_html`/`rendered_text`, not
   `body_html`/`body_text` directly. The rendered fields include the exact
   compliance footer and unsubscribe link a real recipient gets.
2. Check `origin` — everything from this build is `generated` (no source
   scripts existed to adapt from). Read it as carefully as you would any
   AI-drafted customer-facing copy.
3. If it needs a change: `PUT /templates/{key}` with the fields to change.
   This resets it to `pending_approval` even if it was already approved —
   there is no "edit an approved template in place" path, by design.
4. Approve: `POST /templates/{key}/approve`.

## Activating a sequence
`POST /sequences/{key}/activate` refuses with a `400` listing which step
numbers still lack an approved template. Approve every step first, then
activate. `POST /sequences/{key}/deactivate` pauses sends immediately
(existing enrollments stay put, next-step advancement just stops until
reactivated).

## First live send (newsletter issue 1)
Newsletter issue 1 sends immediately on signup (single opt-in), so it's
the highest-stakes first approval. Verify it end-to-end before approving
anything else:

```bash
# 1. Approve issue 1
curl -X POST "{API_BASE_URL}/api/v1/internal/email/templates/newsletter_issue_1/approve" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Activate the newsletter sequence (will refuse if issue 1 isn't the
#    only approved step yet -- approve issues 2+ first, or expect the
#    400 listing which steps are still missing)
curl -X POST "{API_BASE_URL}/api/v1/internal/email/sequences/newsletter/activate" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. Subscribe your own address to trigger a real send
curl -X POST "{API_BASE_URL}/api/v1/email/subscribe" \
  -H "Content-Type: application/json" \
  -d '{"email": "kelvin@theclouddecoded.com", "source": "newsletter_signup"}'
```

Check your inbox within a few minutes (the scheduler runs every 15 min,
but a fresh signup gets `next_send_at = NOW()` so it should go out on the
very next pass).

## `hitl` role (not yet available)
The plan for your wife to review/approve templates under a `hitl` role
needs that role added to `api/middleware/internal_auth.py`'s
`get_internal_user` — not done as part of this build since it's a shared
auth dependency other `/internal/*` routes also use. Until then, template
approval is admin-only.
