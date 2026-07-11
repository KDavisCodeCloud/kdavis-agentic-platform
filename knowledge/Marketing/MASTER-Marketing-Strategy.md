# MASTER MARKETING STRATEGY — Decoded Empire
**THD Agentic Systems LLC**
Last locked: 2026-07-08 — Single source of truth.

References these companion docs (also in `/Empire/Marketing/`):
- [[Marketing-Engine-Agent-Specs]]
- [[Campaign-Orchestrator-and-Strategy-Specs]]
- [[DecodedSix-MSE-Complete-Strategies]]
- [[MSE-Pricing-Framework]]
- [[DecodedSix-Content-Agent-Spec]]

---

## CORE ARCHITECTURE

```
Layer 1: MKT-R1 Research Core (once per product/brand per cycle)
           ↓ research_report.json = single source of truth

Layer 2: Output agents (all read the same research_report.json)
  - MKT-N1  Newsletter (owned audience)
  - MKT-V1  Content Multiplier (1 input → many platforms)
  - MKT-LI1 LinkedIn Personal Brand (Kelvin)
  - MKT-S1  SEO Content Factory (per product)
  - MKT-O2  Cold DM Writer
  - MKT-CN1 Image Brief (→ Claude Design / Ideogram / Gemini)

Layer 3: Governance
  MKT-10 Compliance → MKT-09 HITL queue

Layer 4: Publish → track → feed back to Research Core (learning loop)

DEFERRED: MKT-AD1 Competitor Ad Agent
Ad trigger: build ONLY when a product has proven organic conversion AND LTV > 3x CAC.
Ads amplify what works — never rescue what doesn't.
```

---

## THREE DISTINCT STRATEGIES

### Strategy 1 — Kelvin's LinkedIn (Cloud Decoded + authority)

Audience = Cloud Decoded's exact buyers (VP Eng, Platform leads).
Content IS the sales proof. Your builds demonstrate competence.

**Ratio: 70% growth (news/reach) / 20% authority (how-I-did-it) / 10% conversion**

- "How I did it" NOT "how to" — the AI-era differentiator. Your cloud/AI expertise combined with a fully human builder's life (gardening, faith, how that shapes the business/systems/motivations) is the moat no competitor can copy. USAF service is part of the journey, not the headline angle — don't lead with it.
- Profile = landing page, not CV. Featured section = deplatform to lead magnet / demo / newsletter (NOT top posts).
- Funnel: post → profile → Featured lead magnet → email → Cloud Decoded nurture (long B2B cycle). Warm inbound + warm outbound + email capture.
- **Human input: MONTHLY BATCH SESSION (30-45 min)** fills the Idea Reservoir with ideas + "how I did it" angles. Agents draw from it all month.
- 70% news content needs NO batch — research core reads the world.

### Strategy 2 — DecodedSix (gamers / GTA 6 event)

- Launch: ARTICLES ONLY. Newsletter capture LIVE at launch.
- 48+ articles indexed BEFORE Nov 19 2027. 3/week: news / evergreen / conversion.
- **CREDIBILITY RULE:** Tag every claim `CONFIRMED` / `LEAKED (unverified)` / `SPECULATION`. Honesty is the differentiator AND the E-E-A-T signal in a sea of slop.
- Community seeding from day 1: **HUMAN-POSTED** (agent drafts, human posts). 90% genuine participation / 10% relevant link. Never cross-post. Never automate the posting. Never present speculation as leak. Credibility = traffic.
- Revenue sequence: ads (Nov 19) → affiliate (Nov 19) → newsletter (Nov 19) → Ezoic (~10K pageviews) → shorts/video (post-launch) → sponsors (25K+) → Mediavine (50K+).
- Social / shorts / HeyGen = POST-LAUNCH (still in build phase).
- NOT the exit vehicle. Compounding passive asset. Base case $2-2.5K/mo mid-2027.

### Strategy 3 — MSE Products (paid, self-serve, per-product)

- Model: **PAID DAY 1. NO free trial. NO free tier. Self-serve.**
- Cold start: COMMUNITY (human-posted, credible) + APOLLO (warm DM). Search built INTO the product (SEO/AEO/GEO/SXO from launch).
- NO Product Hunt / AppSumo dependency (those suit freemium volume, not paid).
- White-glove / human-in-loop service: ONLY after a product hits $10K+ MRR. Until then, pure self-serve.
- Campaign fires on Verdict approval via MKT-ORCH (see [[Campaign-Orchestrator-and-Strategy-Specs]]).
- **Pitch framing: "MAKE more money" not "save time." Tie to a dollar amount.**
- Don't reinvent the wheel: copy proven billing / pricing / UX. Speed > perfection.
- Solve real holes in mediocre existing tools. Vertical-specific gaps = green-light.

---

## THE SEARCH STACK (all products, integrated)

| Layer | What it does |
|-------|-------------|
| SEO | Rank in traditional search (foundation) |
| AEO | Win featured snippets / answer boxes — first 40 words = direct answer |
| GEO | Get cited inside AI answers (ChatGPT / Perplexity / Claude / AI Overviews) |
| SXO | Post-click experience — fast pages, low bounce = ranking factor |
| AIO | Entity-based writing — name things clearly, no vague pronouns |

### GEO-specific requirements
- **UNBLOCK AI CRAWLERS:** robots.txt + CDN allow GPTBot, ClaudeBot, PerplexityBot, Google-Extended. (73% of sites invisible to AI because they're blocked.)
- **CITATION DENSITY:** Multiple cited sources + hard stats + quotable data per article (lifts AI citation 30-40%). Not one citation.
- Community presence (Reddit / YouTube / LinkedIn) = LLMs cite these heavily.
- DON'T volume-dump: 10 entity-rich pieces beat 100 thin ones for AI.

### Timeline compression (target 3 months, not 6)
1. Borrow audiences day 1 (Reddit / LinkedIn / community) — doesn't wait for organic
2. Pre-seed full content cluster BEFORE launch event (skip discovery phase)
3. Long-tail keywords first (rank in weeks, build authority)
4. Get cited on high-authority sites (borrowed authority = speed + GEO)
5. Fix technical + SXO (fast sites index faster)
6. Publish consistently (algorithm decides "are you serious" early)

---

## POST-LAUNCH VIDEO PHASE

Trigger: after DecodedSix articles live + traffic flowing.

- HeyGen avatar: one for DecodedSix (news/leak recaps), optionally one for Kelvin
- DecodedSix shorts: top articles → 60-90 sec scripts → YouTube Shorts + TikTok. "Confirmed vs rumor" angle feeds GEO (YT cited by LLMs).
- Kelvin brand shorts: authority posts → "how I built X" 60-sec (secondary)
- All scripts from EXISTING content. No net-new. HeyGen $29/mo, 2-min cap.
- Sequence: DecodedSix shorts first, Kelvin second if bandwidth.

---

## NON-NEGOTIABLES

1. Community posting = **HUMAN, never bot** (ban + reputation risk)
2. Honesty labeling on all GTA 6 content (CONFIRMED / LEAKED / SPECULATION)
3. HITL on all outreach and community touches. MKT-10 compliance first.
4. Paid day 1 for MSE. No free trial. No exceptions.
5. White-glove only after $10K MRR on that product.
6. Ad spend only after organic proven + LTV > 3x CAC.
7. Sunday protected. Idea reservoir batch is NOT a Sunday task.
8. 70/20/10 LinkedIn ratio — don't over-index on selling.

---

## MANUAL TASKS (do now, no agent needed)

- [ ] Affiliate signups: Amazon Associates, Fanatical, CDKeys, Green Man Gaming
- [ ] Unblock AI crawlers on DecodedSix (+ every MSE product at launch): allow GPTBot, ClaudeBot, PerplexityBot, Google-Extended in robots.txt
- [ ] AdSense application at 15 articles (not 20)
- [ ] Newsletter lead magnet: "GTA 6 Confirmed vs Rumored master list"
- [ ] Cloud Decoded lead magnet + nurture sequence (ICP already known, build now)
- [ ] Canva Brand Kit (lock palette, 2 fonts, logo)
- [ ] Set up Idea Reservoir (Claude Project + Obsidian → [[Idea-Reservoir]])
- [ ] Pick + lock hand-drawn house-style prompt + reference image for Ideogram/Gemini (save in [[Visual-Production-Style]])
