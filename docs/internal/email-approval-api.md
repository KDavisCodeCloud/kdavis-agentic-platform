# Email Campaign Approval API — Cloud Decoded

Backend contract for the CEO Decoded dashboard's Email Campaign HITL queue
(`ceo-dashboard/`, a separate build). This document is the source of truth
for the response shape — the MSE repo's equivalent build documents its own
`/marketing/internal/*` API to match these field names wherever the concepts
overlap, so the dashboard can render both feeds with one component.

`product` is always the literal string `"cloud-decoded"` in every response
from this API — it's how the dashboard tells this feed apart from the MSE
feed once both are merged into one queue.

## Auth

Every endpoint below requires `Authorization: Bearer <token>`, validated by
`api/middleware/internal_auth.py`'s `get_internal_user` — **the same
Supabase project ceo-dashboard's own login already authenticates against**.
This means the dashboard's server-side proxy route does **not** need a
separate static API key for this feed: forward the signed-in admin's own
Supabase session JWT from the incoming request straight through as the
Bearer token. (Contrast with the MSE feed, a genuinely different backend/
Supabase project, which does need its own service credential.)

`get_internal_user` currently only recognizes `user_metadata.role == "admin"`
— there is no `"hitl"` role in this backend yet. Every endpoint below is
effectively admin-only until that role is added (see GAPS.md). Do not assume
a `hitl`-role user can call these endpoints today.

Base path: `{API_BASE_URL}/api/v1/internal/email` (e.g.
`https://api.theclouddecoded.com/api/v1/internal/email`).

## Endpoints

### `GET /templates`

Query params: `status_filter` (`pending_approval` | `approved` | `retired`,
optional), `sequence_key` (optional).

Returns a list of:

```json
{
  "template_key": "onboarding_step1_connect_stack",
  "sequence_key": "onboarding",
  "step_number": 1,
  "delay_days": 1,
  "subject": "Still time to connect your stack",
  "preheader": "Nothing runs until at least one system is connected.",
  "status": "pending_approval",
  "origin": "generated",
  "source_script": null,
  "cta_url": "https://theclouddecoded.com/dashboard?tab=connections",
  "skip_if": "connected_anything",
  "approved_at": null,
  "approved_by": null,
  "product": "cloud-decoded"
}
```

`origin` is always `"generated"` in this build (no source scripts existed to
adapt from — Phase 0 recon, confirmed with Kelvin). The field and
`source_script` are kept for contract stability with the MSE feed, which
does use `adapted_from_script` rows.

### `GET /templates/{key}`

Same shape as above, plus `body_html`, `body_text`, `rendered_html`,
`rendered_text` — the last two are the exact HTML/text a real recipient
would get, compliance footer and unsubscribe link included (rendered
against a placeholder address, not a real send).

### `PUT /templates/{key}`

Body: any of `subject`, `preheader`, `body_html`, `body_text`, `cta_url`.
Always resets `status` to `pending_approval` and clears `approved_at`/
`approved_by` — an edited template must always be re-approved, there is no
path to edit an already-approved template in place.

### `POST /templates/{key}/approve`

No body. Sets `status='approved'`, stamps `approved_at`/`approved_by` (the
calling admin's email).

### `POST /templates/{key}/retire`

No body. Sets `status='retired'`. Admin-only in spirit (no separate role
check exists yet — see the auth note above).

### `POST /sequences/{key}/activate`

Refuses with `400` if any `step_number` in that sequence has no `approved`
template (lists the missing step numbers in the error detail). Sets
`active=true` on success — the scheduler only ever advances enrollments in
`active` sequences.

### `POST /sequences/{key}/deactivate`

Sets `active=false`. No restrictions.

### `GET /metrics`

Query param: `sequence_key` (optional). Returns per-sequence:

```json
{
  "sequence_key": "onboarding",
  "sends": 42,
  "clicks": 11,
  "unsubscribes": 3,
  "conversions": 2,
  "revenue_usd_estimate": 598,
  "product": "cloud-decoded"
}
```

`unsubscribes` is a **platform-wide** count attached to every row, not
sequence-scoped (suppression isn't sequence-scoped — one email can be
enrolled in several sequences). `revenue_usd_estimate` is a directional
estimate from static list pricing (`starter=299, growth=699,
enterprise=2499`), not a Stripe-accurate figure — a workspace's real price
can differ (promo codes, grandfathering). No open-rate metric exists
anywhere in this API by design (click tracking only, per the build spec).

## Click tracking

Every marketing email's HTML links are rewritten at send time to
`GET {API_BASE_URL}/api/v1/e/c/{signed_token}`, which records a
`cd_email_clicks` row and 302s to the real destination with
`utm_source=email&utm_medium={sequence_key}&utm_campaign={template_key}`
attached. Not part of the approval API surface, but relevant context for
anyone reading the metrics endpoint.

## What's NOT wired yet (see GAPS.md for full detail)

- `expansion_agent_ceiling` and `expansion_enterprise_upsell` templates exist
  and can be approved/activated, but nothing enrolls a subscriber into them —
  no trigger call site was built this session for either.
- The `hitl` role does not exist in this backend's auth model — every
  endpoint above is admin-only in practice today.
