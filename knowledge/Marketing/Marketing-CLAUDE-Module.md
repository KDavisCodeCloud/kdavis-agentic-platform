# CLAUDE.md — Marketing Module
**Load this at the start of every marketing-related Claude Code session.**
Last updated: 2026-07-08

---

## DOCS TO LOAD FOR MARKETING WORK

Load in this order:
1. [[MASTER-Marketing-Strategy]] — source of truth
2. [[MSE-Pricing-Framework]] — pricing at Verdict + product setup
3. [[Campaign-Orchestrator-and-Strategy-Specs]] — approval → campaign
4. Marketing-Engine-Agent-Specs.md — agent specs (pending)
5. DecodedSix-MSE-Complete-Strategies.md — per-strategy detail (pending)
6. DecodedSix-Content-Agent-Spec.md — DSX-CA1 spec (pending)

---

## MARKETING AGENT REGISTRY

| Code | Agent | Wave | Notes |
|---|---|---|---|
| MKT-R1 | Research Core | 1 | everything reads its output |
| MKT-ORCH | Campaign Orchestrator | 1 | fires on Verdict approval |
| MKT-N1 | Newsletter (+ DSX variant) | 2 | owned audience |
| MKT-V1 | Content Multiplier | 2 | 1 input → many platforms |
| MKT-LI1 | LinkedIn Personal Brand | 2 | 70/20/10, monthly reservoir |
| MKT-CN1 | Image Brief | 2 | → Claude Design / Ideogram / Gemini |
| MKT-S1 | SEO Content Factory | 3 | per product, GEO-dense |
| MKT-O1 | Apollo List Builder | 3 | fired by ORCH |
| MKT-O2 | Cold DM Writer | 3 | "make money" framing |
| MKT-O3 | Email Sequence Loader | 3 | fired by ORCH, purchase-nurture |
| MKT-O4 | Outreach Monitor | 3 | perf → learning loop |
| MKT-PR1 | Proof Collector | 3 | testimonials |
| DSX-CA1 | DecodedSix Content Agent | 2 | 3/wk, credibility-labeled |
| MKT-AD1 | Competitor Ad Agent | DEFER | ad trigger only |

---

## HARD RULES FOR MARKETING CODE

1. **MSE = paid day 1, no free tier.** Stripe Checkout, card required, no trial.
2. **Community posting agents DRAFT ONLY. Humans post.** Never auto-post to Reddit / Discord / forums. This is a ban risk.
3. **All content agents output: SEO + AEO + GEO + SXO.** AI crawlers unblocked. Citation-dense. Entity-based writing. First 40 words = direct answer.
4. **GTA 6 / DecodedSix content:** label CONFIRMED / LEAKED / SPECULATION.
5. **MKT-ORCH fires the campaign on `hitl_status='approved'` DB trigger.**
6. **Pricing set at Verdict** per willingness-to-pay band ($29 floor).
7. **Every output → MKT-10 compliance → MKT-09 HITL queue.** Nothing auto-sends.
8. **Pitch copy leads with "make more money" + dollar amount**, not "save time."
9. **Don't reinvent billing / pricing / UX** — copy proven patterns, same template every product.

---

## IDEA RESERVOIR (LinkedIn personal brand fuel)

- Stored: Claude Project + Obsidian [[Idea-Reservoir]]
- Kelvin fills **MONTHLY** (30–45 min): ideas + "how I did it" angles + conviction posts
- Agents pull unused ideas continuously. Track used / unused in the file.
- 70% news content needs NO reservoir — research core reads the world.
- Sunday is protected — batch session is NOT a Sunday task.

---

## VISUAL PRODUCTION

| Type | Tool |
|---|---|
| Concept diagrams | Claude Design (SVG, brand colors) |
| Hand-drawn / sketchnote | Ideogram or Gemini Nano Banana — locked house-style prompt + reference image |
| Polished infographics | Canva Pro brand kit |

**Workflow:** Claude writes image prompt → Gemini / Ideogram renders → HITL before publish.

Lock house-style in Obsidian: [[Visual-Production-Style]]

---

## COMPANION DOCS STILL PENDING (create in future sessions)

These are referenced by MASTER-Marketing-Strategy but not yet written:
- `Marketing-Engine-Agent-Specs.md` — detailed spec per MKT-* agent
- `DecodedSix-MSE-Complete-Strategies.md` — per-strategy deep detail
- `DecodedSix-Content-Agent-Spec.md` — DSX-CA1 full spec
- `Idea-Reservoir.md` — monthly idea bank for LinkedIn
- `Visual-Production-Style.md` — locked house-style prompt for Ideogram/Gemini
