# SOP: Credential Rotation (Cloud Decoded)
Date created: 2026-09-14
Product: Cloud Decoded
Status: Live

## When this applies
A customer reports (or you suspect) a leaked workspace access token or a
leaked connected-system credential (GitHub token, AWS role, Azure SP
secret, Azure DevOps PAT, K8s token).

## Workspace access token compromised
This is the credential that authenticates the customer to Cloud Decoded
itself (`X-Workspace-Token`).
1. `POST /internal/workspaces/{id}/rotate-token` — immediately invalidates
   the old token (only its hash is ever stored, so the old one stops
   matching anything the instant the new hash is written) and returns a
   new raw token **once**.
2. Send the new token to the customer through a channel you've verified
   is really them (not the email on file alone, if you suspect account
   takeover) — it will not be shown again after this call.

## Connected-system credential compromised (GitHub / AWS / Azure / ADO / K8s)
Cloud Decoded never stores a long-lived raw secret it can "rotate" on the
provider's side for you — GitHub is App-installation-token-based (minted
fresh per call, ~1hr TTL), AWS is a cross-account role assumed fresh per
call, and Azure/ADO/K8s are workspace-supplied secrets Cloud Decoded only
holds encrypted. Rotation is the customer's action on the provider side,
plus your job is to make sure Cloud Decoded picks up the new one:
1. **GitHub App**: if the concern is the App's own private key (not a
   customer's install), that's a platform-wide credential in
   `github_app_config` — this needs a real re-registration, escalate to
   Kelvin directly, don't attempt via the API.
2. **AWS**: the customer rotates/deletes the IAM role or its trust policy
   on their side. If they need to switch to an entirely new role, they
   just reconnect via the Connections tab (`AWS` card) — it overwrites
   the stored ARN.
3. **Azure Service Principal / Azure DevOps PAT / K8s token**: same
   pattern — customer regenerates the secret on their side, reconnects
   via the Connections tab, which overwrites the stored encrypted value.
4. If a customer can't reach their dashboard (lost workspace token too),
   rotate the workspace token first (above), send it to them, then have
   them reconnect the specific credential.

## If you need to fully sever a connection instead of rotating it
There's no dedicated "disconnect" endpoint per connector as of
2026-09-14 — the closest lever is `purge-data` (see
`customer-offboarding.md`), which nulls everything, but that also
requires the workspace to be cancelled/suspended first. For an active
customer who just wants one connector removed, that has to be a direct
DB update today — flag this as a real gap if it comes up (GAPS.md).
