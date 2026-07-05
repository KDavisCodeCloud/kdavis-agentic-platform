# Handoff: CEO Decoded — Agentic Executive OS Dashboard

## Overview
CEO Decoded is an internal-first "cockpit" dashboard for THD Agentic Systems LLC. It runs the business: nine fixed departments (Overview, Finance, Marketing & Sales, R&D, HR, Technology, Legal, Operations, Advisory) plus Video/Creative, each showing live-feeling data about the product portfolio (Cloud Decoded, Micro SaaS Engine, GTA 6 Hub, CEO Decoded, Hustle Decoded), autonomous agents, HITL (human-in-the-loop) approvals, and exit-tracking metrics toward a CorVel acquisition.

The product is opinionated and not configurable at the department/agent-archetype level. What the operator controls: which departments/agents are active, and which human team members (Kelvin, Wife, Son) own which items.

## About the Design Files
The file in this bundle (`CEO Decoded.dc.html`) is a **design reference prototype** built in HTML/CSS/JS — it demonstrates the intended visual system, layout, department content, and component patterns. It is NOT production code to copy directly into the app. The task is to **recreate this design in the target codebase's actual environment** (React/Next.js is assumed given the Supabase/Vercel/FastAPI stack referenced in the content — confirm with the team) using that codebase's real data layer, auth, and component patterns, rather than reusing this HTML/inline-style markup as-is.

Note: all inline styles in the prototype are intentional for the design tool that produced it (it needed to stream/paint progressively). Do not carry over the "inline style on every element" approach into production — extract these into your framework's normal styling approach (CSS modules, Tailwind, styled-components, whatever the codebase already uses) and a shared design-token file per the spec below.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and component structure below are final and should be recreated pixel-for-pixel. All copy/data shown is realistic placeholder content invented for the mockup (see each department's Supabase/live-data notes below) — wire real queries in its place.

## Global Layout
- Full-viewport app shell, no page scroll on the outer frame — only the main content column scrolls.
- Three-part horizontal layout, all `100vh`:
  1. **Icon rail** — 60px fixed width, dark (`#0e1218`), right border `1px solid #1c222b`. Contains a 32×32 rounded-square brand mark ("C" on mint) plus one 34×34 rounded-square avatar per team member (initials, tinted background/text per person).
  2. **Labeled sidebar** — 196px fixed width, same background as rail, right border `1px solid #1c222b`. Contains: wordmark "CEO DECODED" (14px/700/`#eef2f5`), subtitle "THD Agentic Systems LLC" (10px mono `#5b6673`), then a vertical nav list of 10 department items.
  3. **Main content** — flexible width, `#0b0e13` background. Top bar (title + sync timestamp + avatar), then a scrollable content column with 18–24px gaps between section cards.
- Sidebar nav item: 12×12px square outline icon + label, 12.5px/{400 or 600}, padding `9px 10px`, border-radius 8px. Active item: background `#5eead41a`, text color `#5eead4`, weight 600. Inactive: transparent background, `#8b96a3`, weight 400.
- Top bar: department title 19px/700/`#eef2f5` on the left; on the right, sync timestamp (11px mono `#5b6673`) + a 30px circular avatar ("K", mint bg, dark text).

## Screens / Views (department pages, switched by sidebar click — no page reload)

### 1. Overview (home)
- 4-column metric card grid (auto-fit, min 160px): Portfolio MRR, Products Live, Open HITL Items, Stack Burn/mo. Each card has a subtle diagonal gradient tint matching its accent color.
- "All Products" card: grid of 5 product tiles (Cloud Decoded, Micro SaaS Engine, GTA 6 Hub, CEO Decoded, Hustle Decoded), each with status badge, MRR, active-agent count, open-queue count, last-run timestamp. Tiles link to that product's dashboard (not implemented in prototype — add real routing).
- Two-column grid: **Agent Activity Feed** (real-time log: agent, department, action, verdict badge, timestamp; verdict colors: pass=green, flagged=red, pending=amber) and **HITL Approval Queue** (agent, proposed action, confidence bar %, blast-radius badge, Approve/Reject buttons — batch-approve not yet built for 3+ similar items, flag for follow-up).
- "Team Ops" strip: 3 tiles (Kelvin/Wife/Son) — assignment summary, last login, pending-item count.

### 2. Finance
- 4 metric cards: Total MRR, MoM Growth, Runway (months), Stack Burn/mo.
- MRR breakdown table (5-column grid: Product / MRR / Subs / Churn / MoM Δ), one row per product.
- Operating Stack Cost tracker: itemized list of every tool (Supabase, Vercel, n8n, Anthropic API, Videomule, ElevenLabs, HeyGen, Resend) with category + active/paused status + monthly cost; total row at bottom.
- Exit Gate Tracker (green-tinted card): CorVel exit threshold math (label/value rows) — $15K MRR × 3 consecutive months, client count needed, projected MRR range, ARR/multiple required, current progress.
- Finance Agent roster: Revenue Tracker, Cash Flow Monitor, Expense Categorizer — each with status badge, last-run time, one-line output summary.

### 3. Marketing & Sales
- Pipeline stage cards (Cold → Contacted → Demo → Trial → Paying): count + MRR potential per stage.
- Content calendar: 7-day grid (Mon–Sun), each cell shows scheduled post title, product tag, platform, status badge (draft/approved/published). Wife's approval queue should live inline here in production.
- Marketing Agent roster: LinkedIn Content, Cold Email, Conversion Tracker.
- Cold outreach tracker: sequence name, product, emails sent, open rate, meetings booked.

### 4. R&D
- Opportunity pipeline: scored list (opportunity name, vertical agent that found it, confidence %, verdict badge pass/flag/reject, date). Click-through to full agent output not built — add a drawer/detail view.
- MSE Agent Swarm roster (8 cards, auto-fit grid): Dispatch (orchestrator), Verdict (quality gate), Ledger, Anchor, Comply, Runway, Pulse, Scout — each with status, vertical focus, last-run time.
- Build pipeline: per-product progress through the 29-day build cycle (day/29, phase label, progress bar, MRR-floor enforcement note).

### 5. HR
- Team roster table: name, role, department access, permission level badge, last-active.
- Onboarding flow: 5-step numbered checklist (magic link → role → department scoping → RLS assignment → confirmation).
- HITL routing rules: action type → routes to which human.
- Approval chain diagram: Kelvin (full access) at top, branching to Wife (Marketing/Ops/HR) and Son (R&D/Tech, read-only).

### 6. Technology
- Infrastructure health tiles (5): Supabase, Vercel, FastAPI, n8n, GitHub — each with a status dot (green/amber/red) and last-checked time.
- Agent health table: agent, product, last run, status badge, error count (7-day).
- Build queue: priority badge (P1/P2/P3), item, repo, owner — filterable by repo/priority in production.
- Cost Optimizer flags: overprovisioned/underutilized service call-outs.

### 7. Legal
- Persistent disclaimer banner (amber-tinted): "This is AI-assisted information, not legal advice. Consult a licensed attorney before acting." — must appear on every view in this department.
- Document vault table: doc name, product, version, last updated (add real download links).
- Legal Agent roster: Contract Review, Entity Advisor, IP Flagging.
- Quick Q&A: prompt input + logged example response with citation and attorney caveat; all responses should be logged with timestamp in production.

### 8. Operations
- Build Order tracker: single ordered list, checkbox-style done indicator, no phases/timelines — mirrors the repo's CLAUDE.md / build-order files.
- Weekly Rhythm: Mon–Sat grid (session type + open-item count per day); Sunday rendered locked/non-editable (dimmed, "rest" label).
- GAP tracker: gap name + status badge (open/closed).
- Session log: append-only, date/product/summary — no delete affordance by design.

### 9. Advisory
- 3 advisor cards side by side (CFO, CMO, CTO), each: name (accent-colored), a conversation-thread preview bubble, a "Memory Summary" label + text, a one-line "context" note, and a "Brief this advisor" button (accent-outlined). No approve/reject actions here — counsel only. Production should make the thread scrollable/persistent and the context panel collapsible per the spec.

### 10. Video / Creative
- Script queue table: title, product, status badge (draft/approved/rendering/published).
- HeyGen render tracker: title + placeholder thumbnail (striped pattern in mockup — replace with real thumbnail) + status badge (complete/rendering/failed).
- Distribution queue: title, platform, scheduled time, status badge (Wife approves before publish in production).
- Creative Agent roster: Script Agent, HeyGen Render Agent, Distribution Agent.

## Shared Components (reuse the same markup/pattern everywhere they appear)

- **Metric card**: uppercase 11px mono muted label → 24px/800 value in accent color → 11px mono muted subtext. Background is a 150°-angle linear-gradient from `accent+24 alpha` to `#141a22` at 75%. Border `1px solid #1c222b`, radius 14px, padding `16px 18px`.
- **Section card**: `#141a22` background, `1px solid #1c222b` border, radius 14px, padding 20px, 13px/700/`#c7cfd6` header label with 14px bottom margin.
- **Agent roster card**: name (13px/700), status badge (pill, 9.5–10px mono, tinted bg/text per status), last-run timestamp (mono, muted), 1–2 line output/focus summary (mono, muted).
- **Status/verdict badge**: pill shape, `border-radius:5–6px` or `20px` for fully-rounded, mono font 9–10.5px, background = accent at ~13% alpha, text = full accent. Standard mapping: green `#6fce8f` = active/pass/healthy; blue `#7ea6f5` (bg `#5b8def22`) = building/pending/queued-ok; amber `#e8963f` = planning/flagged/queued-caution; red `#e05d5d` = error/reject/flagged-critical; gray `#9aa2ab` (bg `#2a2a2a`) = future/backlog/neutral.
- **HITL approval row**: agent name + blast-radius badge on one line, plain-language action below, confidence bar (5px track `#1c222b`, fill mint `#5eead4`) + percentage, Approve (mint outline) / Reject (gray outline) buttons.
- **Activity feed row**: colored dot (verdict color) + agent name (truncate at ~100px) + department (truncate ~70px) + action text (flex, must truncate with ellipsis — do not let this column force horizontal overflow) + verdict badge + timestamp.
- **Progress bar**: track `#1c222b`, 5–6px tall, radius 3px, fill = accent color, width = percentage.
- **Nav item** (sidebar): 12×12 outline square "icon" (placeholder — swap for real department icons in production) + label; active/inactive styling per Global Layout above.

## Interactions & Behavior
- Sidebar department click swaps the main content column instantly (client-side state, no route change in the prototype — implement as real routes, e.g. `/dashboard/finance`, in production so departments are deep-linkable and support browser back/forward).
- HITL Approve/Reject buttons are visual only in the prototype — wire to real mutation + optimistic UI + toast confirmation.
- "Brief this advisor" button is visual only — wire to a real context-push action.
- No loading/error/empty states are designed yet — flag this as a gap; every table/list above needs a skeleton/empty/error treatment before ship.
- Layout is fluid, not fixed-width: grids use `repeat(auto-fit,minmax(Npx,1fr))` and any two-column split uses `minmax(0,Nfr)` tracks so columns actually compress at narrower widths instead of forcing horizontal scroll. Preserve this pattern — it was a deliberate fix for a real overflow bug during design (bare `Nfr` tracks and flex children without `min-width:0` will force overflow; always pair fractional grid tracks with `minmax(0, …)` and give any flexible text-truncating flex child `min-width:0` + ellipsis).
- No responsive/mobile breakpoints designed — this is treated as a desktop-only internal tool for now. Confirm with the team if mobile access is needed.

## State Management
- Active department (string enum matching the 10 nav ids: `overview, finance, marketing, rnd, hr, tech, legal, ops, advisory, video`).
- Per-department data will come from Supabase (as referenced throughout: MRR, agent runs, HITL queue, docs, session log, etc.) — real-time subscriptions recommended for the Activity Feed and HITL queue specifically since those are described as "real-time" in the spec.
- Permission scoping: Kelvin sees everything; Wife scoped to Marketing & Sales / Operations / HR (with approval-queue access); Son read-only on R&D / Technology. Gate department routes and mutation actions by this role model server-side, not just by hiding nav items client-side.

## Design Tokens

**Backgrounds**
- App/base: `#0b0e13`
- Sidebar/rail: `#0e1218`
- Section card: `#141a22`
- Nested tile (inside a card): `#10151b`
- Borders (all cards/dividers): `#1c222b`
- Exit-gate tinted card: `radial-gradient(circle at 15% 15%, #6fce8f22, #10201a 70%)`, border `#1f3d2e`
- Legal disclaimer banner: `#241a10`, border `#3d2e1f`

**Text**
- Primary heading/value: `#eef2f5`
- Section label: `#c7cfd6`
- Secondary/body: `#aab4bd`
- Muted/mono metadata: `#5b6673` (and `#8b96a3` for slightly brighter muted labels)

**Accent palette** (used for status, per-product color coding, and metric-card tints)
- Mint (primary brand accent): `#5eead4`
- Blue: `#7ea6f5` (badge bg `#5b8def22`)
- Green (success/active/pass): `#6fce8f` (badge bg `#6fce8f22`)
- Amber (warning/pending/planning): `#e8963f` (badge bg `#e8963f22` or `#332a18` solid tile)
- Red (error/flagged/reject): `#e05d5d` (badge bg `#e05d5d22`)
- Neutral/backlog gray: `#9aa2ab` on `#2a2a2a`

**Typography**
- Headings/body: **Inter** (400/500/600/700/800)
- Data, timestamps, labels, code-like values: **JetBrains Mono** (400/500/600/700)
- Scale used: 24px/800 (metric values), 19px/700 (page title), 14–15px/600–700 (card titles, names), 13px/700 (section labels), 12–12.5px/400–600 (body/table text), 10–11.5px (mono metadata/timestamps/badges)

**Radius**: cards/sections 14px, nested tiles 10–12px, badges/pills 5–6px (or 20px fully rounded), avatars 50%/10px (square-ish) depending on context.

**Spacing**: section gap 16–18px, card padding 20px (16–18px for metric cards), row padding 8–13px with `1px solid #1c222b` top divider between rows.

## Assets
No external images/icons used — all "icons" in the prototype are placeholder outline squares (nav items) or CSS-drawn dots/badges. HeyGen render thumbnails use a striped CSS gradient placeholder. Production should source real department icons (a simple line-icon set matching the mint/dark palette) and real video thumbnails.

## Files
- `CEO Decoded.dc.html` — the full interactive prototype (all 10 department views, client-side switchable via the sidebar). Open directly in a browser to review behavior and inspect exact markup/styling for any value not captured above.
- `screenshots/` — one PNG per department view (01-overview through 10-video-creative), for quick visual reference without needing to run the HTML file.
