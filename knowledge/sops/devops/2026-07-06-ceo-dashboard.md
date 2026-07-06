# SOP: CEO Decoded Dashboard
Date: 2026-07-06
Product: CEO Decoded (internal)
URL: ceo.thdecodedempire.com
Repo: kdavis-agentic-platform/ceo-dashboard
Status: Live — skeleton complete, agent backends pending

---

## Purpose

The CEO Decoded dashboard is the internal command center for Kelvin Davis (owner/CEO). It provides a single view across all products, agents, team members, the HITL approval queue, and department-specific operations. It is not customer-facing.

---

## Auth

- Method: Supabase magic link (email only)
- Login page: `/login` — enter email, receive magic link, click to land in dashboard
- Callback: `/auth/callback` — Supabase redirects here after link click, sets session cookie
- Session: managed by `@supabase/ssr` via middleware — all `/dashboard/*` routes are protected
- If not authenticated: redirected to `/login` automatically

### Role assignment

The dashboard has a role system with three roles: `admin`, `marketing`, `rnd`.

The owner email (`kdav2k5@gmail.com`) is hardcoded to receive `admin` role in `app/dashboard/layout.tsx`. This bypasses the need for user metadata to be set in Supabase.

Future team members get their role from `user.user_metadata.role`, which should be set when inviting them via the onboarding agent (Phase 3). Default fallback is `rnd` (most restricted).

Role controls which sidebar departments are visible — admins see all 10.

---

## Layout

Three-panel layout matching the CEO Decoded design handoff:

```
[60px icon rail] [196px labeled sidebar] [flex main content]
```

- **Icon rail** (`components/shell/IconRail.tsx`): brand mark "C" at top, section icons, team member initials (K/W/S) pulled from Supabase, user avatar at bottom
- **Sidebar** (`components/shell/Sidebar.tsx`): CEO DECODED wordmark + THD Agentic Systems LLC, nav items filtered by role
- **Main**: scrollable content area per department

Design tokens: dark theme, mint accent (#5eead4). Full token spec in `CLAUDE.md` → Dashboard Design System.

---

## Department pages

All routes live under `/dashboard/[department]`.

| Department | Path | Status | Data source |
|---|---|---|---|
| Overview | /dashboard/overview | Live | Supabase (products, team_members, hitl_queue, agent_events) |
| Finance | /dashboard/finance | Stub | Needs accounting_agent |
| Marketing & Sales | /dashboard/marketing | Stub | Needs content_agent + lead data |
| R&D | /dashboard/rnd | Stub | Needs research_agent pipeline |
| HR | /dashboard/hr | Live (read-only) | Supabase team_members table |
| Technology | /dashboard/tech | Stub | Needs code_quality_agent |
| Legal | /dashboard/legal | Stub — UI built, not wired | Needs legal agent + LLM endpoint |
| Operations | /dashboard/ops | Stub | Needs portfolio_monitor |
| Advisory | /dashboard/advisory | Live | LLM via Supabase advisory_threads table |
| Video / Creative | /dashboard/video | Stub | Needs content_agent video module |

"Stub" = page renders with empty state message, no live data. Not broken — waiting for the agent backend that feeds it.

---

## Overview page features

All data pulls live from Supabase on every page load (server components, no caching).

**Metric cards (top row):**
- Portfolio MRR — sum of all active product revenue (currently $0, updates as Stripe events come in)
- Products Live — count of products with status = 'live' in products table
- Open HITL Items — count of unresolved records in hitl_queue
- Stack Burn / Mo — static estimate (~$225) of monthly infra cost

**All Products section:**
- Reads from `products` table in Supabase
- Shows each product name, status badge (BUILDING/PLANNING/LIVE), agent count, queue count
- Status badge colors: BUILDING = blue, PLANNING = amber, LIVE = green

**Agent Activity feed:**
- Reads from `agent_events` table
- Empty state: "Fire the research swarm to populate this feed"
- Will auto-populate when agents start running

**HITL Approval Queue:**
- Reads from `hitl_queue` table
- Empty state: "Queue is clear. No pending approvals."
- Will show decision cards when agents surface items needing approval

**Team Ops section:**
- Reads from `team_members` table
- Shows name, title, access scope, pending item count
- Currently static seed data (Kelvin/Wife/Son)

---

## Advisory page features

The most functional department page. Allows direct conversation with three AI advisors:

- **CFO** (gold accent) — financial decisions, burn rate, pricing
- **CMO** (purple accent) — marketing strategy, messaging, positioning
- **CTO** (blue accent) — technical architecture, build decisions

Each advisor has a separate conversation thread stored in Supabase `advisory_threads` table. Conversations persist across sessions.

How it works:
1. Select advisor tab
2. Type message in input
3. Message saved to Supabase → API call to LLM (Anthropic via providers/router.py)
4. Response streamed back, saved to thread
5. Thread renders chronologically

Note: if the API backend is not running, advisor chat will fail silently. The LLM call goes through the FastAPI backend, not directly from the Next.js frontend.

---

## HR page features

Read-only team roster from `team_members` table. Shows:
- Name, role, email
- Permission level badge (admin/marketing/rnd)
- Status (active/invited/pending)
- Pending items count

No editing from this page — team management actions go through the onboarding agent (Phase 3).

There is a note visible on the page: "Assign role in user_metadata" — this is a placeholder reminder that was left in during build. It will be removed when the onboarding agent handles role assignment automatically.

---

## Legal page

UI is built but not wired to a live backend. Shows:
- Legal Q&A interface (input + response area)
- Placeholder legal documents section

Will become functional when the legal agent is built (Phase 2). The legal agent will handle contract Q&A, compliance questions, and document storage — routed through the LLM with legal-specific prompting.

---

## Adding a new department page

1. Add route to `DEPT_ROUTES` in `lib/types.ts` with appropriate roles
2. Create `app/dashboard/[new-dept]/page.tsx`
3. Page should be a server component that pulls data from Supabase
4. Use `SectionCard` and `MetricCard` components from `components/ui/`
5. Follow the design token spec in `CLAUDE.md`

---

## If the dashboard breaks

- **Blank page after login**: check browser console for Supabase fetch errors — likely the anon key env var is missing or expired session
- **Only 3 sidebar items showing**: role fallback kicked in — check that the logged-in email matches `OWNER_EMAIL` in `app/dashboard/layout.tsx`
- **Products/team data not loading**: check Supabase → Table Editor → verify `products` and `team_members` tables have rows and RLS policies allow reads
- **Vercel deployment failing**: check Next.js version — pin to latest `next-15-X` patch tag on npm
