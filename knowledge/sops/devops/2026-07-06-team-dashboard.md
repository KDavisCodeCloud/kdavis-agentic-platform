# SOP: Team Dashboard
Date: 2026-07-06
Product: Internal — Team Operations
URL: team.thdecodedempire.com
Repo: kdavis-agentic-platform/team-dashboard
Status: Live — UI complete, real task data pending

---

## Purpose

The team dashboard is where Claude Code employees and Claude Design employees do their work. It is separate from the CEO dashboard by design — team members see only their assigned tasks and resources, never financial data, agent internals, or the owner command center.

This dashboard was built for the first wave of team members: Kelvin's son (CTO/builder role) and daughter (designer role). It scales to any future hire with the same role structure.

---

## Auth

Same Supabase instance as CEO dashboard (microsaas-prod). Magic link login at `/login`.

Role is read from `user.user_metadata.role` — team members must have this set when invited. The onboarding agent (Phase 3) handles this automatically. Until then, set manually via Supabase SQL Editor (run as postgres role):

```sql
UPDATE auth.users
SET raw_user_meta_data = raw_user_meta_data || '{"role": "builder", "name": "First Last"}'::jsonb
WHERE email = 'their@email.com';
```

---

## Layout

Mobile-first. Two layouts depending on screen width:

**Desktop (>768px):**
```
[60px icon rail] [196px sidebar] [flex main content]
```

**Mobile (≤768px):**
```
[full screen main content]
[48px bottom tab bar — My Tasks | Current Task | Resources]
```

The sidebar is hidden on mobile. Bottom tab bar replaces it. All tap targets are minimum 44px height per CLAUDE.md mobile rules.

Design tokens: blue-shifted variant of CEO Decoded system. Only the background changes — everything else (typography, accent color, status badges) is identical.

```
--bg-base:    #0d1117  (blue-shifted, vs CEO's #0b0e13)
--bg-sidebar: #0f1520
--bg-card:    #141c28
--bg-tile:    #111825
--border:     #1c2535
```

Accent: #5eead4 (mint) — same as CEO dashboard. Instant visual distinction from CEO view without a different brand.

---

## Three views

### My Tasks (`/tasks`)

Lists all tasks assigned to the logged-in team member. Data currently from `MOCK_TASKS` in `lib/types.ts` — will pull from Supabase `tasks` table when the onboarding agent is live.

Each task row shows:
- Product name
- Task type badge (BUILD / DESIGN / REVIEW)
- Status badge (ASSIGNED / IN_PROGRESS / SUBMITTED / APPROVED / REVISION_NEEDED)
- Priority badge (HIGH / NORMAL / LOW)
- Due date (mono)
- Step progress (e.g. "3 of 6 steps")
- "Open Task" button — appears only on IN_PROGRESS tasks, links to Current Task view

Active task has a 3px mint left border. Completed tasks are dimmed (opacity-50).

Mock data includes two tasks: FreightAudit (in_progress) and LeadSequencer (assigned).

### Current Task (`/current-task`)

Detail view for the active in-progress task. This is where the work actually happens.

**Task header card:** product name, task type, assigned date.

**Step list:** numbered steps for the task. Three visual states:
- Completed: green checkmark ✓, text dimmed
- Current: mint circle with step number, full opacity, left border highlight
- Upcoming: gray circle, text muted

**File checklist:** files that must be committed before submission. Each file has:
- Filename (mono)
- File path/location
- Checkbox (tap to check off)
- Minimum 44px tap target for mobile

**Submit section (sticky bottom on mobile):**
- Notes textarea — "Anything unusual to note?"
- "Submit for Review" button — full width, 48px height, mint
- Button is DISABLED until all checklist items are checked
- After submit: confirmation state shows, button becomes "Submitted — awaiting review"

This flow enforces that team members can't submit incomplete work.

### Resources (`/resources`)

Three resources always available:
1. ROLE.md — their specific role document (links to file in repo)
2. HOW_TO_USE_CLAUDE_CODE.md — plain-English guide to using Claude Code for builds
3. Slack — link to team Slack workspace

Getting Started section — 4-step numbered guide:
1. Read your ROLE.md
2. Check My Tasks for your assignment
3. Open Current Task to see your step-by-step guide
4. Submit when all checklist items are done

This page never changes per task — it's always available as a reference point.

---

## Mock data (current state)

Until the Supabase `tasks` table is seeded and the onboarding agent assigns real tasks, the dashboard uses mock data defined in `lib/types.ts`:

```
MOCK_TASKS: [
  FreightAudit — in_progress, step 3 of 6, HIGH priority, due 2026-07-10
  LeadSequencer — assigned, not started, NORMAL priority, due 2026-07-15
]

MOCK_STEPS: 6 steps for FreightAudit
  1. Read the product brief — complete
  2. Set up local dev environment — complete
  3. Build the data ingestion layer — CURRENT
  4. Build the audit logic — upcoming
  5. Build the output formatter — upcoming
  6. Write tests and submit PR — upcoming

MOCK_FILES: 3 required files
  - freight_ingestor.py
  - audit_engine.py
  - test_audit.py
```

To replace with real data: wire `app/tasks/page.tsx` and `app/current-task/page.tsx` to Supabase `tasks` table filtered by `assigned_to = current_user_id`.

---

## Adding a real task (when onboarding agent isn't live yet)

Insert directly into Supabase:

```sql
INSERT INTO tasks (product_id, assigned_to, task_type, title, description, status, priority, due_date, created_by)
VALUES (
  'freight-audit',
  '[team_member_supabase_user_id]',
  'BUILD',
  'Build freight invoice ingestion layer',
  'See brief at team/[name]/tasks/TASK_freightaudit.md',
  'assigned',
  'high',
  '2026-07-15',
  '[your_supabase_user_id]'
);
```

Then update `app/tasks/page.tsx` to query this table instead of MOCK_TASKS.

---

## If the dashboard breaks

- **Bottom tab bar not showing on mobile**: verify viewport is ≤768px and the CSS media query in the layout component is correct
- **Submit button never enables**: check that the file checklist state is being tracked correctly — all items must be checked
- **Tasks not loading**: currently using mock data — if switched to Supabase, verify the `tasks` table exists and RLS allows the user to read their own rows
- **Login redirect loop**: check that `team.thdecodedempire.com/auth/callback` is in Supabase redirect URLs list
