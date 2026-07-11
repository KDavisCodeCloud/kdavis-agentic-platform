# Session 6 — CEO Dashboard Agent Fire Buttons

Paste this prompt into Claude Code from `/mnt/c/Users/Kelvin/projects/kdavis-agentic-platform`.
Walk away — no input needed.

---

Read CLAUDE.md and EXECUTION_ORDER.md.

Task: Wire agent fire buttons in the CEO dashboard so they actually POST to the
FastAPI `/agents/{agent_id}/run` endpoint and display the incident ID + live status.

**Context:**
- FastAPI is at `api/main.py`. The endpoint is `POST /agents/{agent_id}/run`
  defined in `api/routes/agents.py`.
- CEO dashboard is at `ceo-dashboard/`. Pages in `app/dashboard/`.
- Supabase client is at `ceo-dashboard/lib/supabase/client.ts`.
- The overview page (`app/dashboard/overview/page.tsx`) already renders product
  tiles and team rows. Check if it has fire buttons — if not, add them.

**Step 1 — Audit existing pages for fire buttons:**
Read these files and note which pages have placeholder buttons vs wired ones:
- `app/dashboard/overview/page.tsx`
- `app/dashboard/ops/page.tsx`
- `app/dashboard/tech/page.tsx`
- `app/dashboard/marketing/page.tsx`

**Step 2 — Create API utility:**
Create `ceo-dashboard/lib/api.ts`:
```ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export async function triggerAgent(
  agentId: string,
  payload: Record<string, unknown>,
  authToken: string,
): Promise<{ incident_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/agents/${agentId}/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({ payload }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? `Agent trigger failed: ${res.status}`)
  }
  return res.json()
}

export async function pollIncident(
  incidentId: string,
  authToken: string,
): Promise<{ status: string; output?: unknown }> {
  const res = await fetch(`${API_BASE}/incidents/${incidentId}`, {
    headers: { Authorization: `Bearer ${authToken}` },
  })
  if (!res.ok) throw new Error(`Poll failed: ${res.status}`)
  return res.json()
}
```

**Step 3 — Create FireButton component:**
Create `ceo-dashboard/components/ui/FireButton.tsx`:
- Props: `agentId: string`, `label: string`, `payload: Record<string, unknown>`
- State: `status: 'idle' | 'running' | 'done' | 'error'`
- On click: call `triggerAgent()`, show incident ID, then poll every 3s until
  status is 'completed' or 'failed'
- Read auth token from Supabase session: `supabase.auth.getSession()`
- Idle: dark button with agent label. Running: amber spinner + "Running..."
  Done: green checkmark + incident ID (first 8 chars). Error: red + error message.
- After done/error, reset to idle after 8 seconds.
- Never store the auth token in localStorage.

**Step 4 — Wire buttons into overview page:**
In `app/dashboard/overview/page.tsx`, import FireButton and add one per product
where agents exist. Use these agent IDs (from `agents/` directory structure):
- `research_agent` — trigger in Cloud Decoded tile
- `portfolio_monitor` — trigger in MSE tile
- `sop_gap_detector` — trigger in CEO Decoded tile

**Step 5 — Add NEXT_PUBLIC_API_URL to .env.local:**
In `ceo-dashboard/.env.local` (read first to avoid overwriting):
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```
Add to `.env.example` with empty value.

**Step 6 — TypeScript check:**
Run: `cd ceo-dashboard && npx tsc --noEmit`
Fix all errors.

Do NOT change any backend code. Do NOT add new npm packages.
Do NOT modify any files outside `ceo-dashboard/`.

Output ✅ DONE or 🚫 BLOCKED then stop.
