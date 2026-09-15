# 2026-09-15 (continued) — MCP TLS: root cause found, fixed, live-verified

Product: Cloud Decoded
Continues [[2026-09-15-migration-runner-dbaas-domain-and-observability]].
Closes GAPS.md #11's long-open TLS half (the OAuth provisioning half was
already closed earlier the same day).

## What prompted this

Kelvin: "MCP TLS... investigate further just to make sure" — this had
been flagged repeatedly across sessions (2026-09-12 audit: "still
provisioning, up to 72 hours"; this session's operational readiness audit:
"crossed from still-provisioning into actually stuck"), always with the
same passive diagnosis and never a root cause.

## What was found

Direct TLS handshake against `mcp.theclouddecoded.com` showed the server
presenting Railway's own generic `CN=*.up.railway.app` wildcard cert —
not a cert for the custom domain at all. Railway's `domain-status` API
confirmed: `certificate.status: CERTIFICATE_STATUS_TYPE_VALIDATING_OWNERSHIP`,
`verified: false`, despite the CNAME DNS record showing `PROPAGATED` with
`currentValue == requiredValue`. DNS was never the problem. `railway
domain certificate retry` refused outright: *"Certificate retry is only
available after certificate issuance fails. Current status:
CERTIFICATE_STATUS_TYPE_VALIDATING_OWNERSHIP."* — the domain had never
reached a `FAILED` state Railway's own tooling considers retryable. This
is what separates a genuinely wedged validation job from "still
provisioning": there was no automated recovery path, and none was ever
going to appear on its own.

## The fix

Deleted and re-added the custom domain in Railway (`railway domain
delete` / `railway domain mcp.theclouddecoded.com --port 8001`) to force
a completely fresh validation attempt. This surfaced the actual root
cause: the re-created domain required a `_railway-verify.mcp` TXT
ownership-verification record that the original domain object — created
before Railway added this requirement — never had and had no way to
retroactively satisfy. A new CNAME target also came with it
(`z7trcyh4.up.railway.app`, replacing the stale `y11fpv8e.up.railway.app`).

Updated both DNS records directly via the Namecheap API — Kelvin supplied
an API key and account username (`kdav2k5`) after saying "you have access
to do this on your own." Recalling memory (this project's + the wider
portfolio's) surfaced the registrar — Namecheap, documented in this
repo's own `CLOUD_DECODED_AUDIT_2026-08-09.md` and in cross-project
memory — but no stored credential anywhere; the key had to come from
Kelvin directly, same pattern as the GitHub PAT earlier this session (see
[[../lessons-learned/004-github-pat-in-chat-when-gh-auth-breaks]]).

**Process, since `setHosts` replaces Namecheap's entire zone, not one
record:** fetched the complete existing host set first
(`namecheap.domains.dns.getHosts` — only 3 records total: `@`/`www` A
records to `76.76.21.21`, plus the stale `mcp` CNAME; `EmailType=FWD`).
Dry-ran the exact `setHosts` payload before sending it (printed every
param except the key). Resubmitted the full set: the two A records
untouched byte-for-byte, `mcp`'s CNAME updated to the new target, the new
TXT record added, `EmailType=FWD` passed through explicitly so domain
email forwarding wasn't silently reset to `NONE`. `IsSuccess="true"`, no
warnings, confirmed via an immediate `getHosts` re-read.

## Verification (live, not assumed)

DNS propagation polled directly against Google (8.8.8.8) and Cloudflare
(1.1.1.1) resolvers — both correct within ~2 minutes. The actual served
TLS certificate polled via `openssl s_client` in a bounded until-loop —
switched from Railway's `*.up.railway.app` wildcard to a real Let's
Encrypt cert (`CN=mcp.theclouddecoded.com`, SAN exactly
`mcp.theclouddecoded.com`, valid Sep 15 – Dec 14 2026) within ~4 minutes
of the DNS write. Railway's `domain-status` confirmed
`CERTIFICATE_STATUS_TYPE_VALID` / `verified: true`.
`curl https://mcp.theclouddecoded.com/health` → `200
{"status":"ok","service":"cloud-decoded-mcp"}`.

## Not yet done

The final live SSE MCP tool-call verification (queued since the
2026-09-12 audit) and an end-to-end test of the Enterprise OAuth invite
flow (built earlier this session, GAPS.md #11's other half) are both
unblocked by this fix but not separately exercised in this pass — TLS was
the blocker for both, not the only remaining step.

## Credential handling

Namecheap API key used via an environment variable scoped to the
individual script invocations only — never written to any file, never
committed, confirmed absent from disk after use (same discipline as the
GitHub PAT: use ephemerally when Kelvin supplies it directly, don't
persist into Claude's own memory system regardless of his explicit
override on ephemeral use).
