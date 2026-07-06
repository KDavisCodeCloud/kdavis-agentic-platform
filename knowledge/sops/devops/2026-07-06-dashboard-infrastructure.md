# SOP: Dashboard Infrastructure Setup
Date: 2026-07-06
Product: kdavis-agentic-platform
Status: Complete

---

## What was done

Deployed all three internal dashboards to production with custom domains, SSL, and Supabase auth.

---

## Domains

| Dashboard | URL | Vercel Project | Repo |
|---|---|---|---|
| CEO Decoded | ceo.thdecodedempire.com | ceo-decoded-dashboard | kdavis-agentic-platform |
| Team | team.thdecodedempire.com | team-dashboard | kdavis-agentic-platform |
| MSE | mse.thdecodedempire.com | kdavis-microsaas-engine | kdavis-microsaas-engine |

`thdecodedempire.com` = internal dashboards (not public-facing)
`thdstack.com` = micro-SaaS products (public-facing, future)

---

## Vercel project settings

### CEO Dashboard
- Root Directory: `ceo-dashboard`
- Install Command: `npm install --legacy-peer-deps`
- Framework: Next.js

### Team Dashboard
- Root Directory: `team-dashboard`
- Install Command: `npm install --legacy-peer-deps`
- Framework: Next.js

### MSE Dashboard
- Root Directory: `kdavis-microsaas-engine/frontend`
- Install Command: `npm install --legacy-peer-deps`
- Framework: Next.js
- Note: Root is two levels deep because the git repo at /projects/ level tracks `kdavis-microsaas-engine/` as a subdirectory. The Next.js app lives at `kdavis-microsaas-engine/frontend/` within that.

---

## Environment variables (all 3 projects)

```
NEXT_PUBLIC_SUPABASE_URL = https://gjezchcoyytxcpsbvkrg.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY = [anon key from Supabase → Settings → API]
```

CEO dashboard additionally:
```
NEXT_PUBLIC_MSE_API_URL = [MSE backend API URL when live]
```

MSE dashboard additionally:
```
NEXT_PUBLIC_API_URL = [MSE backend API URL when live]
```

After adding env vars, always redeploy: Vercel project → Deployments → latest → ... → Redeploy.

---

## DNS (Namecheap)

Registrar: Namecheap
Domain: thdecodedempire.com
DNS type: Advanced DNS

| Type | Host | Value | TTL |
|---|---|---|---|
| CNAME Record | ceo | cname.vercel-dns.com | Automatic |
| CNAME Record | team | cname.vercel-dns.com | Automatic |
| CNAME Record | mse | cname.vercel-dns.com | Automatic |

Host = subdomain prefix only. Namecheap appends the root domain automatically.
Vercel handles SSL provisioning automatically once CNAME resolves.

To verify propagation:
```bash
dig ceo.thdecodedempire.com CNAME +short
# Should return: cname.vercel-dns.com.
```

---

## Supabase auth setup

Project: microsaas-prod (https://gjezchcoyytxcpsbvkrg.supabase.co)
Auth method: Magic link (email only — no password)

Redirect URLs (Authentication → URL Configuration → Redirect URLs):
```
https://ceo.thdecodedempire.com/auth/callback
https://team.thdecodedempire.com/auth/callback
https://mse.thdecodedempire.com/auth/callback
https://ceo-decoded-dashboard.vercel.app/auth/callback
```

Without redirect URLs added here, magic links will redirect to a Supabase error page instead of back into the dashboard.

---

## Git repo structure

Both CEO and Team dashboards live in the same repo (`kdavis-agentic-platform`) as subdirectories. One push deploys both if both are connected to Vercel — Vercel detects the root directory change and only rebuilds the affected project.

MSE dashboard lives in `kdavis-microsaas-engine` which is tracked by the parent git repo at `/mnt/c/Users/Kelvin/projects/`. The parent repo's remote points to `github.com/KDavisCodeCloud/kdavis-microsaas-engine.git`. Running git commands for MSE must be done from `/mnt/c/Users/Kelvin/projects/` not from inside `kdavis-microsaas-engine/`.

---

## Security notes

- Next.js pinned to exact version `15.3.9` in all dashboards (CVE-2025-29927, CVE-2025-66478 patched)
- `.env.local` files are gitignored — never commit them
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` is safe to expose client-side (Supabase RLS enforces access)
- `service_role` key is NEVER used on the frontend — only in server-side admin scripts
- All repos are public on GitHub — do not commit secrets

---

## If Vercel deployment is blocked

1. Check Next.js version — Vercel scans for CVEs. Always pin to latest patch: `npm view next dist-tags` → use `next-15-3` tag value.
2. Never add `Co-Authored-By` lines to commits — Vercel Hobby blocks deploys from repos with unrecognized co-authors.
3. If repo doesn't appear in Vercel import: GitHub → Settings → Applications → Vercel → Configure → add repo to allowed list.
