# Team Dashboard — Build Brief
# team.thdstack.com
# For Claude Code — not Claude Design

---

## What this is

The team dashboard for team members (son, daughter, future employees).
Same design as CEO Decoded and MSE dashboards — already built and locked.
The only difference is a slight background color shift to distinguish
context at a glance.

Do NOT redesign anything. Do NOT use Claude Design for this.
Recreate the CEO Decoded design system exactly, apply the color
overrides below, then build the simplified team-specific content.

---

## Reference files (read these first)

```
design_handoff/design_handoff_ceo_decoded/README.md
  — Full pixel-perfect spec. Every exact value is in here.
  — Read this before writing a single line of component code.

design_handoff/design_handoff_ceo_decoded/CEO Decoded.dc.html
  — Interactive prototype. Open in browser to inspect any
    component, spacing, or color not captured in README.md.
  — Do NOT copy inline styles into production.
  — Extract into CSS tokens + framework styling approach.

design_handoff/design_handoff_ceo_decoded/screenshots/
  — 01-overview.png through 10-video-creative.png
  — Visual reference per department view.
  — Relevant for team dashboard: 05-hr.png (team roster pattern)
```

---

## Color overrides (the ONLY difference from CEO Decoded)

Apply these five values. Everything else is identical.

```css
/* team.thdstack.com — override these five only */
--bg-base:     #0d1117;   /* was #0b0e13 — slight blue cast */
--bg-sidebar:  #0f1520;   /* was #0e1218 — blue-shifted */
--bg-card:     #141c28;   /* was #141a22 — blue-shifted */
--bg-tile:     #111825;   /* was #10151b — blue-shifted */
--border:      #1c2535;   /* was #1c222b — blue-shifted */
```

Everything inherited unchanged from CEO Decoded:
- Mint accent:    #5eead4
- Text primary:   #eef2f5
- Text secondary: #aab4bd
- Muted mono:     #5b6673
- All status/badge colors
- Inter + JetBrains Mono fonts
- All radius, spacing, component patterns
- Scrollbar styling
- Three-part layout (icon rail + sidebar + main)

---

## Layout (same three-part structure as CEO Decoded)

```
Icon rail: 60px fixed width
  - Brand mark: 32×32 rounded-square, #5eead4 bg, "T" dark text
  - One 34×34 avatar per team member (initials, tinted per person)
  - Background: --bg-sidebar
  - Right border: 1px solid --border

Labeled sidebar: 196px fixed width
  - Wordmark: "THD STACK" 14px/700/#eef2f5
  - Subtitle: team member name + role, 10px mono #5b6673
  - Nav items (3 only — not 10 departments):
      My Tasks
      Current Task
      Resources
  - Nav item style: identical to CEO Decoded active/inactive pattern
  - Background: --bg-sidebar
  - Right border: 1px solid --border

Main content: flex, --bg-base background
  - Top bar: current task name left, status badge + avatar right
  - Scrollable content below top bar
  - Main padding: 24px 30px 40px
  - Section gap: 18px
```

---

## Content views (sidebar nav switches these — same client-side swap)

### MY TASKS VIEW

Section card (same card pattern as CEO Decoded: --bg-card, border, 14px radius):
  Header: "MY TASKS" 13px/700/#c7cfd6

Task list rows (one per assigned task):
  Row layout: product name | task type badge | status badge |
    priority badge | due date (mono) | Submit button
  Row padding: 10px 0, border-top: 1px solid --border
  Product name: 13px/600/#eef2f5
  Submit button: only visible on in-progress tasks
    Style: mint outline, same as CEO Decoded Approve button pattern
  Active task: left border 3px #5eead4
  Completed task: all text #5b6673, no submit button

Status badges — use CEO Decoded badge pattern exactly:
  assigned:         blue   #7ea6f5  bg #5b8def22
  in_progress:      mint   #5eead4  bg #5eead422
  submitted:        amber  #e8963f  bg #e8963f22
  approved:         green  #6fce8f  bg #6fce8f22
  revision_needed:  red    #e05d5d  bg #e05d5d22
  completed:        gray   #9aa2ab  bg #2a2a2a

Priority badges:
  high:    red    #e05d5d  bg #e05d5d22
  normal:  blue   #7ea6f5  bg #5b8def22
  low:     gray   #9aa2ab  bg #2a2a2a

Empty state:
  Centered text: "No tasks assigned yet"
  Color: #5b6673 mono
  No card — just centered in the main area

---

### CURRENT TASK VIEW

Task header card (--bg-card, border, 14px radius, 16px 18px padding):
  Product name: 15px/700/#eef2f5
  Task type: badge below name
  Assigned date: 11px mono #5b6673

Step list (inside a section card):
  Header: "TASK STEPS" 13px/700/#c7cfd6
  Each step row (border-top: 1px solid --border, padding 10px 0):
    Left: step number circle (20px, --bg-tile bg, mono 11px)
    Middle: step title (13px/600/#eef2f5) + description (12px/#aab4bd below)
    Right: status pill
    Current step: step circle bg #5eead4, text #0b0e13
    Completed: all text #5b6673, circle bg #6fce8f22
    Upcoming: circle bg --bg-tile, text #5b6673

File checklist (section card, same pattern):
  Header: "FILES REQUIRED BEFORE SUBMITTING"
  Each row: filename (13px/600/#eef2f5) + path (11px mono #5b6673) +
    checkbox right-aligned
  Checkbox: 16×16px, border 1.5px solid --border, radius 4px
    Checked: bg #5eead4, checkmark #0b0e13

Submit section (bottom of main, above mobile tab bar):
  Notes textarea:
    Background: --bg-tile
    Border: 1px solid --border, radius 10px
    Padding: 12px
    Placeholder: "Anything unusual to note?" color #5b6673
    Font: 12.5px Inter #aab4bd
  Submit button:
    Full width, height 48px, radius 10px
    Active: bg #5eead4, text #0b0e13, 13px/700
    Disabled (checklist incomplete): bg #1c2535, text #5b6673
    Label: "Submit for review"

---

### RESOURCES VIEW

Section card:
  Header: "RESOURCES"
  Three items:
    1. Link to their ROLE.md file (opens in new tab)
    2. Link to their HOW_TO_USE_[TOOL].md file
    3. Link to Slack (opens Slack app or web)
  Each item: 13px/600/#eef2f5 label + 11px mono #5b6673 description
    + right arrow icon, border-top between items

---

## Mobile layout (390px — team members primarily use phones)

Bottom tab bar (48px height):
  3 tabs: My Tasks | Current Task | Resources
  Active tab: #5eead4 text + 2px top border #5eead4
  Inactive: #5b6673 text
  Background: --bg-sidebar
  Border-top: 1px solid --border

Each tab: full screen, no sidebar on mobile
  Top bar stays: task name + status + avatar

Current Task mobile:
  Step checkboxes: 44px minimum tap target
  Submit button: sticky bottom, 16px margin, full width

My Tasks mobile:
  Task rows full width
  Submit button inline on each row, right-aligned
  44px minimum row height

---

## Mock data to use during build

Team member: [SON'S NAME], role: Builder
Tasks assigned: 2

Task 1 (active):
  Product: FreightAudit
  Type: CLAUDE CODE
  Status: in_progress
  Priority: high
  Due: 3 days
  Steps: 6 total, step 3 current
  Files required: agent.py, config.yaml, signup/page.tsx

Task 2 (pending):
  Product: LeadSequencer
  Type: CLAUDE CODE
  Status: assigned
  Priority: normal
  Due: 7 days

---

## What NOT to build

- No finance panel
- No revenue intelligence
- No agent roster (full version)
- No research pipeline
- No analytics charts
- No HITL queue (owner only)
- No agent chat (owner only)
- No Obsidian feed
- No banking or wealth panels

The team dashboard is intentionally minimal.
They see their work. Nothing more.

---

## File locations

Component output: dashboard/team/components/
App entry: dashboard/team/app.tsx
Design tokens: dashboard/team/tokens.css
  (import from shared base, apply overrides)

Shared token base lives at:
dashboard/internal/design/design-system.css
Team overrides: 5 lines only, don't duplicate the whole file.
```
