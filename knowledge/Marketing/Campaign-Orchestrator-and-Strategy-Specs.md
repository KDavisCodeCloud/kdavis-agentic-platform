# Campaign Orchestrator + Three-Strategy Definitions
**Decoded Empire / THD Agentic Systems**
Last updated: 2026-07-09

---

## KEY PRINCIPLE
Approval is the trigger. The orchestrator builds the campaign fresh from the research report at approval time — because the ICP is unknown until then. You approve copy; the system does the heavy lifting. Three strategies, three channel mixes, one orchestrator routing each product to the right one.

---

## PART 1 — MKT-ORCH: Campaign Orchestrator (THE MISSING PIECE)

### The problem it solves
Currently: Verdict approves a product → nothing happens automatically. The marketing agents exist but must be fired manually.
Fix: an orchestrator that listens for approval and fans out the full campaign.

### Repo
`kdavis-microsaas-engine` — `/mnt/c/Users/Kelvin/projects/kdavis-microsaas-engine`

### Trigger mechanism
Supabase database trigger on `mse_research_opportunities`:
- WHEN `hitl_status` changes to `'approved'`
- → fires n8n webhook
- → MKT-ORCH reads the approved product's row + linked `research_report.json`
- → orchestrator kicks off campaign build sequence

```sql
CREATE OR REPLACE FUNCTION trigger_campaign_build()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.hitl_status = 'approved' AND OLD.hitl_status != 'approved' THEN
    PERFORM net.http_post(
      url := 'https://[n8n-webhook-url]/campaign-build',
      body := json_build_object(
        'product_id', NEW.product_id,
        'research_opportunity_id', NEW.id,
        'vertical', NEW.vertical
      )::jsonb
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER on_product_approved
  AFTER UPDATE ON mse_research_opportunities
  FOR EACH ROW EXECUTE FUNCTION trigger_campaign_build();
```

### What the orchestrator fires (in order)
1. **MKT-O1** Apollo List Builder — ICP → verified lead list → HITL
2. **MKT-O2** Cold DM Sequence Writer — pain language → 2-touch DM → HITL
3. **MKT-O3** Email Sequence Loader — trial nurture → loads into systeme.io (unactivated until HITL approves)
4. **MKT-S1** SEO Content Factory — niche article stream, 2-3/week → HITL
5. **MKT-V1** Content Multiplier — optional per product, social launch posts → HITL

### Channel selection logic (routes each product to the right channels)
```python
def select_channels(research_report):
    icp_location = research_report['icp_channels']  # from MKT-R1 output schema
    channels = ['seo', 'email']  # always
    if 'linkedin' in icp_location: channels.append('linkedin_dm')
    if 'reddit' in icp_location: channels.append('reddit')
    if 'facebook_groups' in icp_location: channels.append('facebook')
    return channels
```

### State tracking table
```sql
CREATE TABLE campaign_builds (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id            UUID NOT NULL,
  research_opp_id       UUID NOT NULL,
  triggered_at          TIMESTAMPTZ DEFAULT now(),
  apollo_status         TEXT DEFAULT 'pending',
  dm_sequence_status    TEXT DEFAULT 'pending',
  email_sequence_status TEXT DEFAULT 'pending',
  seo_factory_status    TEXT DEFAULT 'pending',
  social_status         TEXT DEFAULT 'pending',
  campaign_live_at      TIMESTAMPTZ,
  overall_status        TEXT DEFAULT 'building'
                        CHECK (overall_status IN ('building','awaiting_hitl','live','paused'))
);
```

### Dashboard
New route: `/dashboard/mse/campaign-builds`
Wife sees what's awaiting approval. Kelvin sees overall pipeline health.

---

## PART 2 — STRATEGY 1: Kelvin's LinkedIn (Cloud Decoded / Agentic / Build-in-Public)

### Purpose
Build Kelvin as the authority. Warm audience → Cloud Decoded distribution channel.

### Agents
- MKT-LI1 LinkedIn Personal Brand Agent (content mix 40/30/20/10)
- MKT-CN1 Image Brief Agent → Claude Design visuals

### The funnel (GAP TO CLOSE)
```
LinkedIn post (value/journey)
  → profile visit (bio = sales page)
  → Featured section → Cloud Decoded landing page OR lead magnet PDF
  → email captured → Cloud Decoded nurture sequence begins
  → 6-12 month B2B cycle → trial → client
```

### What needs to be built
- Cloud Decoded lead magnet PDF ("Agentic DevOps Playbook" — high value, gated)
- Cloud Decoded nurture email sequence (~12 touches over 90 days, long B2B cycle)
- LinkedIn Featured section wired to funnel links
- Profile bio rewritten as value prop, not resume

**Note:** This is the ONLY sequence that can be built NOW — Cloud Decoded ICP is already defined. All MSE product sequences must wait for approval (ICP unknown until then).

---

## PART 3 — STRATEGY 2: DecodedSix (Gamers / Enthusiasts)

### Purpose
Capture the GTA 6 traffic wave. SEO + event traffic → ads + affiliate + sponsorship.

### Covered
- DSX-CA1 Content Agent (3 articles/week, schema, E-E-A-T)
- SEO/AEO baked into content output

### Gaps to close

**Gap 1 — Community seeding (pre-launch)**
- Targets: r/GTA6, r/GTAVI, GTAForums, Discord servers
- Approach: genuine value-first presence, NOT promotion (communities ban promoters)
- Start now — compounds before Nov 19 2027
- Optional: MKT-V1 variant for Reddit-appropriate value posts

**Gap 2 — Email capture**
- Weekly newsletter: "GTA 6 Leonida News Digest"
- Lead magnet: "GTA 6 Launch Guide" or "Leonida Map PDF"
- Agent: MKT-N1 DecodedSix variant
- This list survives algorithm changes — don't be 100% dependent on Google

**Gap 3 — Affiliate programs (DO BEFORE FIRST CONVERSION ARTICLE)**
- Amazon Associates (instant approval)
- Fanatical (instant)
- CDKeys (instant)
- Green Man Gaming (instant)
- Without these live, conversion articles earn nothing

---

## PART 4 — STRATEGY 3: MSE Products (ICP Outreach + SEO/AEO + Facebook)

### Purpose
Validated product → targeted cold outreach + organic → first customers fast.

### How it works
1. MKT-R1 research validates product + produces research_report.json with ICP
2. Verdict issues STRONG_PASS → HITL approval
3. MKT-ORCH fires on approval, reads research_report, routes to correct channels
4. All agents build fresh for this product's specific ICP
5. Copy lands in HITL queue for wife's review
6. Approved → outreach sends, sequences arm, SEO articles publish

### Facebook strategy per product
- MKT-C1 Community Scout identifies whether ICP is Facebook-heavy
- If yes: MKT-ORCH fires Facebook presence task alongside other agents
- Consumer lifestyle MSE → Facebook + SEO + email
- Developer tool MSE → LinkedIn + Reddit + SEO

---

## PART 5 — GAPS SUMMARY

| Gap | Fix | Priority |
|-----|-----|----------|
| Approval → campaign disconnect | MKT-ORCH orchestrator + DB trigger | CRITICAL |
| MSE channel selection | Logic in MKT-ORCH reading ICP channels | HIGH |
| LinkedIn → Cloud Decoded funnel | Lead magnet + nurture sequence + Featured setup | HIGH (build now) |
| DecodedSix email capture | MKT-N1 variant + signup form + lead magnet | MEDIUM |
| DecodedSix community seeding | Manual Reddit/Discord presence + optional Reddit agent | MEDIUM (start now) |
| Affiliate signups | Manual — Amazon, Fanatical, CDKeys, GMG | HIGH (do today) |
| Facebook per-product | MKT-C1 identifies + MKT-ORCH fires | MEDIUM (per product) |

---

## PART 6 — SESSION WAVE MAP

### Wave 1 — Foundation (build first)
- MKT-R1 Research Core (may already exist as research swarm in MSE repo)
- **MKT-ORCH** Campaign Orchestrator ← NEW, critical keystone

### Wave 2 — Output agents (can build simultaneously, wire into ORCH after)
- MKT-N1 Newsletter (Cloud Decoded + DecodedSix variants)
- MKT-V1 Content Multiplier
- MKT-LI1 LinkedIn Personal Brand Agent
- MKT-CN1 Image Brief Agent

### Wave 3 — Outreach agents (fired by ORCH, built in parallel)
- MKT-O1 Apollo List Builder
- MKT-O2 Cold DM Sequence Writer
- MKT-O3 Email Sequence Loader (systeme.io)
- MKT-S1 SEO Content Factory

### Manual (no agent needed)
- Affiliate signups (Amazon, Fanatical, CDKeys, Green Man Gaming)
- Cloud Decoded lead magnet PDF
- LinkedIn bio + Featured section
- Reddit/Discord community presence
- Canva Brand Kit
- Apollo.io account
- systeme.io account
