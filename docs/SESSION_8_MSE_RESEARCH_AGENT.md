# Session 8 — MSE Research Agent

Paste this prompt into Claude Code from `/mnt/c/Users/Kelvin/projects/kdavis-agentic-platform`.
Walk away — no input needed.

---

Read CLAUDE.md and EXECUTION_ORDER.md.

Task: Build the Micro SaaS Engine research agent that discovers and validates
micro SaaS opportunities. Output goes to Supabase for CEO dashboard review.

**Context:**
- Micro SaaS Engine (MSE) is the software factory product — it identifies
  underserved niches, validates demand, and outputs product specs.
- `agents/` directory has many agents already. This adds `agents/mse/`.
- The core engine in `core/engine.py` handles sanitization, HITL, audit.
- LLM routing: `claude-haiku-4-5` for web scraping, `claude-sonnet-4-6` for analysis.

---

**Step 1 — Create directory structure:**
```
agents/mse/__init__.py
agents/mse/opportunity_finder.py
agents/mse/demand_validator.py
agents/mse/product_spec_writer.py
agents/mse/pipeline.py
```

**Step 2 — opportunity_finder.py:**
Class `OpportunityFinder`:
- Method: `async def find(self, niche_hint: str = '') -> list[dict]`
- Uses `anthropic` client with model `claude-haiku-4-5-20251001`
- DataSanitizationShield on `niche_hint` before LLM call
- Prompt: analyze SaaS market gaps in the {niche_hint or 'productivity/workflow'} space.
  Return 5 opportunities as JSON: `[{"name", "problem", "target_user", "estimated_arr", "competition_level"}]`
- Parses JSON response, validates schema
- Writes to `audit_log`: `action='mse_opportunity_scan'`, `agent_id='mse_opportunity_finder'`
- Returns list of opportunity dicts

Read `ANTHROPIC_API_KEY` from `os.getenv()`. No hardcoded values.

**Step 3 — demand_validator.py:**
Class `DemandValidator`:
- Method: `async def validate(self, opportunity: dict) -> dict`
- Uses `claude-sonnet-4-6` (this is deeper analysis, not high-volume scraping)
- DataSanitizationShield on opportunity dict
- Prompt: Given this micro SaaS concept `{opportunity}`, evaluate:
  1. Search demand signals (what would you search for)
  2. Willingness to pay evidence
  3. Build complexity (1-10)
  4. Time to first revenue estimate (weeks)
  5. go/no-go recommendation with reason
  Return JSON: `{"demand_score": int, "build_complexity": int, "weeks_to_revenue": int, "go": bool, "reason": str}`
- On `go=true`: inserts into `mse_opportunities` Supabase table (upsert by name)
- Writes audit_log entry
- Returns the validation dict merged with original opportunity

**Step 4 — product_spec_writer.py:**
Class `ProductSpecWriter`:
- Method: `async def write_spec(self, validated_opportunity: dict) -> dict`
- Uses `claude-sonnet-4-6`
- Only called when `validated_opportunity['go'] == True`
- DataSanitizationShield before LLM call
- Prompt: Write a 1-page product spec for this micro SaaS:
  - Product name (short, memorable, .com available likely)
  - Problem statement (1 sentence)
  - ICP (ideal customer profile)
  - Core features (5 bullets, MVP only)
  - Pricing ($X/month, why)
  - Stack (from CLAUDE.md stack — Next.js 15, FastAPI, Supabase, Stripe)
  - First 3 milestones to $1K MRR
  Return as JSON: `{"product_name", "problem", "icp", "features": [], "price_monthly": int, "stack_notes", "milestones": []}`
- Inserts spec into `mse_product_specs` table (links to opportunity by name)
- Writes audit_log entry
- Returns spec dict

**Step 5 — pipeline.py:**
```python
import argparse
import asyncio

async def run_pipeline(niche_hint: str = ''):
    finder = OpportunityFinder()
    validator = DemandValidator()
    writer = ProductSpecWriter()

    opportunities = await finder.find(niche_hint)
    results = []
    for opp in opportunities:
        validated = await validator.validate(opp)
        if validated['go']:
            spec = await writer.write_spec(validated)
            results.append({**validated, 'spec': spec})
        else:
            results.append(validated)
    return results

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--niche', default='')
    args = parser.parse_args()
    results = asyncio.run(run_pipeline(args.niche))
    print(f"Pipeline complete. {len([r for r in results if r.get('go')])} opportunities validated.")
```

**Step 6 — SQL migration for MSE tables:**
Create `db/migrations/005_mse_opportunities.sql` (or 006 if 005 already exists — check first):
```sql
CREATE TABLE IF NOT EXISTS mse_opportunities (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id        text NOT NULL DEFAULT 'mse',
  tenant_id         uuid,
  name              text NOT NULL,
  problem           text,
  target_user       text,
  estimated_arr     text,
  competition_level text,
  demand_score      int,
  build_complexity  int,
  weeks_to_revenue  int,
  go                boolean NOT NULL DEFAULT false,
  reason            text,
  created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE mse_opportunities ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON mse_opportunities
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE TABLE IF NOT EXISTS mse_product_specs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id      text NOT NULL DEFAULT 'mse',
  opportunity_id  uuid REFERENCES mse_opportunities(id) ON DELETE CASCADE,
  product_name    text NOT NULL,
  problem         text,
  icp             text,
  features        jsonb DEFAULT '[]',
  price_monthly   int,
  stack_notes     text,
  milestones      jsonb DEFAULT '[]',
  created_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE mse_product_specs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON mse_product_specs
  FOR ALL TO service_role USING (true) WITH CHECK (true);
```

**Step 7 — Smoke test:**
```
python -c "from agents.mse.pipeline import run_pipeline; print('OK')"
```
Fix any import errors.

Do NOT run the pipeline (it makes real API calls).
Do NOT modify any files outside `agents/mse/` and `db/migrations/`.

Output ✅ DONE or 🚫 BLOCKED then stop.
