# MSE PRICING FRAMEWORK
**Decoded Empire / THD Agentic Systems**
Locked: 2026-07-08

See also: [[MASTER-Marketing-Strategy]], [[Campaign-Orchestrator-and-Strategy-Specs]]

---

## THE CORE RULE

**Paid day 1. No free trial. No free tier. Self-serve.**
Priced to the niche's willingness-to-pay — NOT one flat low price across products.

**Price floor: $29/mo minimum.** Below $29 = race to the bottom (high churn, price-shoppers, someone always undercuts). Non-negotiable.

---

## PRICING BANDS BY NICHE TYPE

| Niche type | Price band | $10K MRR needs |
|---|---|---|
| Simple horizontal tool | $29–49/mo | 204–345 customers |
| Substantial / multi-feature tool | $49–99/mo | 102–204 customers |
| Vertical (compliance / fintech / legal) | $99–299/mo | 34–102 customers |

**Default: aim $49–99.** Go higher for money / compliance / regulated verticals — structurally higher willingness to pay, lower churn.

---

## VERDICT PRICING SIGNAL

Add to research swarm output alongside existing $4K MRR score:

```json
{
  "willingness_to_pay_band": "low_29_49 | mid_49_99 | premium_99_299",
  "wtp_evidence": ["...existing paid products in niche + their pricing..."],
  "suggested_price": 49,
  "is_b2b_premium_capable": true,
  "customers_needed_4k": 82,
  "customers_needed_10k": 204
}
```

**Rule:** if `is_b2b_premium_capable = true`, price upstream ($99+). Premium niches hit $10K MRR with far fewer customers and lower churn.

---

## PITCH FRAMING

Bake into MKT-O2 (DM writer) and MKT-S1 (SEO factory) prompts:

- Lead with **"MAKE more money"** / the outcome gained, NOT "save time."
- Tie to a dollar amount: "$X in, potentially $Y out = arbitrage."
- Example: "$49/mo → recover $800/mo in [lost revenue the tool fixes]."
- The math has to be obvious and favorable to the buyer.

---

## PRODUCT SETUP TEMPLATE (same every product — don't reinvent)

| Component | Decision |
|---|---|
| Billing | Stripe subscription, monthly, single price (no complex tiers early) |
| Pricing page | Copy proven micro-SaaS layouts: one price, clear value, CTA |
| Checkout | Stripe Checkout, card required, no trial |
| UX | Copy patterns users already know from big players |
| Stack | Next.js + Supabase + Stripe + Vercel (locked — never deviate) |

Speed to market > technical perfection. Don't waste time on billing model debates.

---

## WHITE-GLOVE GATE

Human-in-the-loop / white-glove service = **ONLY after that product hits $10K+ MRR.**

Until then: pure self-serve. Rationale: multi-product operator cannot hand-hold every product. Service is added only when revenue justifies the human hours. For premium products post-$10K, HITL "expert-guided" can be SOLD as a value prop — justifies premium in an AI-saturated market.

---

## TIMELINE MATH

At $49 floor vs ~$19:
- $4K floor needs **82 customers**, not 210 — 60% fewer
- Fewer customers per milestone = faster floors = earlier stacking
- $29+ floor filters price-shoppers = lower churn = floors HOLD

Median micro-SaaS time to $10K MRR: 12–18 months from first customer (top performers 6–9 months).

**Accelerant:** research swarm validates demand BEFORE building, so you skip the failed-guess months most founders eat.
