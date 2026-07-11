# Build Runbook

How to resume a Claude session and pick up exactly where things left off.

---

## Starting a Claude Session

**Always do this first:**
1. Open Claude Code in the project directory
2. Run: `cat EXECUTION_ORDER.md` — this is the authoritative status file
3. Tell Claude: "Read EXECUTION_ORDER.md and CLAUDE.md, then tell me where we are"
4. Claude picks up from there — no recap needed

**Active project path:**  
`/mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine`

**Empire dashboard path:**  
`/mnt/c/Users/Kelvin/projects/kdavis-agentic-platform/empire-dashboard/`

---

## Starting the API (FastAPI)

```bash
cd /mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine
source venv/bin/activate  # or use global pip3 install if no venv
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Verify: `curl http://localhost:8000/health` → `{"status": "healthy"}`

---

## Starting n8n

```bash
cd /mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine
bash n8n/start-n8n.sh
```

**First run only:**
1. Go to `http://localhost:5678`
2. Complete owner account setup
3. Settings → Credentials → Add new → Supabase
   - Name: `microsaas-supabase`
   - URL: your Supabase project URL
   - Service role key: from `.env`
4. Activate both workflows (weekly-digest-001, reengagement-001)

**n8n requires Node v22** — if wrong version:
```bash
nvm use 22
```

---

## Starting the Frontend (Next.js)

```bash
cd /mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine/frontend
npm run dev
```

Frontend at: `http://localhost:3000`  
API must be running at `:8000` for data to load.

---

## Updating the Empire Dashboard

At the end of every productive session:

1. Claude writes a new migration file: `empire-dashboard/supabase/migrations/00N_update_YYYY_MM_DD.sql`
2. Open Supabase dashboard → empire-dashboard project → SQL Editor
3. Paste the migration contents → Run
4. Confirm: "Applied migration" message

---

## Pushing to GitHub

```bash
cd /mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine
git add -p  # review what's being staged
git commit -m "feat: [what was built]"
git push origin main
```

---

## Checking Open Gaps

```bash
cat /mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine/EXECUTION_ORDER.md
```

The Open Gaps table at the bottom lists everything pending by owner and priority.

---

## Security Rules (Non-Negotiable)

- Never share API keys in chat — paste directly into `.env`
- Each product has its own dedicated Stripe account — never share billing
- `service_role` key never used in frontend or exposed in browser
- `DataSanitizationShield` before every LLM call
- RLS on every Supabase table — no temporary bypasses

---

## If Something Is Broken

1. Check `.env` — most failures are missing env vars
2. Check `api/middleware/tenant_context.py` — PUBLIC_PATHS set correctly
3. Check n8n is running on Node v22 (`node --version`)
4. Check Supabase migration applied: open Supabase → Table Editor → confirm tables exist
5. Check `EXECUTION_ORDER.md` for notes on known issues
