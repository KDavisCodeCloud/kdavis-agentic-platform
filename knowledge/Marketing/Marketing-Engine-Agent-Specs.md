# Marketing Engine — Agent Specs & Session Briefs
**Decoded Empire / THD Agentic Systems**
Architecture: One Research Core → Many Outputs → Governance → Publish + Learn
Last updated: 2026-07-08

See also: [[MASTER-Marketing-Strategy]], [[Campaign-Orchestrator-and-Strategy-Specs]]

---

## Architecture Summary

One research pass feeds multiple channel outputs. Same brand voice, lower API cost, the LLM learns one pattern.

```
Layer 1: MKT-R1 Research Core (runs once per product per cycle)
           ↓ research_report.json

Layer 2: Output agents (all read research_report.json)
  - MKT-N1  Newsletter Agent
  - MKT-V1  Content Multiplier (1 input → many platforms)
  - MKT-S1  SEO Content Factory (per MSE product)
  - MKT-O2  Cold DM Sequence Writer
  - MKT-LI1 LinkedIn Personal Brand Agent

Layer 3: Governance
  MKT-10 Compliance Guard → MKT-09 HITL Queue Manager

Layer 4: Publish → track performance → feed back to Research Core (learning loop)

DEFERRED: MKT-AD1 — build ONLY when ad trigger fires (LTV > 3x CAC + proven organic conversion)
```

---

## AGENT 1 — MKT-R1: Research Core

**Wave:** 1 (foundation — everything depends on this)
**Depends on:** nothing
**Output:** `/mse/marketing/outputs/research_report.json` (per product per cycle)

### What it does
Runs once per product per cycle. Scrapes the product's niche and produces ONE structured report. No downstream agent does its own research. This is the single source of truth.

### Inputs
```python
{
  "product_id": str,
  "niche_keywords": list[str],
  "source_config": {
    "reddit_subs": list[str],
    "competitor_urls": list[str],
    "news_sources": list[str],
    "forums": list[str],
    "review_platforms": list[str]   # G2, Capterra, Product Hunt, AppSumo
  }
}
```

### Output — research_report.json
```python
{
  "product_id": str,
  "cycle_date": date,
  "trending_topics": [
    {"topic": str, "why_it_matters": str, "source_urls": list[str]}
  ],
  "pain_language": [
    {"phrase": str, "context": str, "source": str, "frequency": int}
  ],
  "competitor_moves": [
    {"competitor": str, "action": str, "source_url": str}
  ],
  "content_angles": [
    {"angle": str, "supporting_data": str}
  ],
  "proof_signals": [
    {"signal": str, "source": str}
  ],
  "icp_channels": list[str],    # where ICP actually lives — feeds MKT-ORCH channel selection
  "willingness_to_pay_band": str,
  "wtp_evidence": list[str],
  "suggested_price": int
}
```

### Cadence
Weekly per active product. Cron via n8n. Sunday excluded.

---

## AGENT 2 — MKT-N1: Newsletter Agent

**Wave:** 2
**Depends on:** MKT-R1
**Output:** newsletter draft → systeme.io draft → HITL queue

### What it does
Builds a weekly branded newsletter per product/brand from research_report.json. Purpose: owned audience that no algorithm can take away.

### Structure it produces
- Subject line (3 variants for A/B testing)
- Hook paragraph (from top trending_topic)
- 3–5 story summaries (in brand voice)
- One "builder's note" section (personal, journey-driven)
- CTA (soft — to product, waitlist, or reply)

### Inputs
```python
{
  "research_report": dict,
  "brand_voice_profile": dict,
  "list_segment": str            # systeme.io tag/segment
}
```

### Output
Draft posted to systeme.io as unsent draft + surfaced in HITL queue. **Wife approves → schedules. Never auto-sends.**

### Cadence
Weekly per brand. Tuesday or Wednesday send (best open rates).

---

## AGENT 3 — MKT-V1: Content Multiplier

**Wave:** 2
**Depends on:** MKT-R1
**Output:** platform-specific post drafts → HITL queue

### What it does
Takes ONE research input and fans it out to platform-specific posts. Same story, adapted per platform's format and norms.

### CRITICAL RULE: Community posts are DRAFT ONLY. Humans post. Never auto-post.

### Platforms
- **LinkedIn** (primary — text post + image brief for MKT-CN1)
- **Reddit** (value-first, non-promotional, community-appropriate — AGENT DRAFTS, HUMAN POSTS)
- **X/Twitter** (thread format) — deprioritized
- **Short-form video script** (hook/body/CTA, for later HeyGen use)

### Inputs
```python
{
  "research_report": dict,
  "brand_voice_profile": dict,
  "high_performers": list,           # past top posts to learn tone from
  "target_platforms": list[str]
}
```

### Outputs
```python
{
  "linkedin_post": {
    "body": str,                        # text post version
    "format": str,                      # "text_post" | "document_carousel"
    "image_brief": dict | None,         # populated when format = "text_post" → MKT-CN1
    "hook_variants": list,
    "carousel_slides": list[str] | None,    # slide copy, one str per slide; None if text_post
    "carousel_pdf_brief": dict | None       # design brief for Canva/Figma → PDF → document post
  },
  "reddit_post": {"subreddit": str, "body": str, "value_framing": str},
  "x_thread": list[str],
  "video_script": {"hook": str, "body": str, "cta": str}
}
```
# Agent selects format: use document_carousel when content has 3–8 discrete points
# (frameworks, step-by-step, comparisons). Native carousels removed Dec 2023 —
# PDF-as-document-post is the standard (278% more engagement than video).

Each output → MKT-10 compliance scan → HITL queue. `image_brief` passes to MKT-CN1 → Claude Design renders the visual.

### Cadence
Runs off each weekly research cycle. Target: 3–4 LinkedIn posts/week.

---

## AGENT 4 — MKT-LI1: LinkedIn Personal Brand Agent

**Wave:** 2
**Depends on:** MKT-R1, MKT-V1
**Output:** Kelvin's personal LinkedIn post calendar → HITL queue

### What it does
Builds Kelvin as the authority. His personal brand becomes the warm distribution channel for every product launch. Distinct from product marketing.

### Content mix
- 40% educational (teach one thing in cloud/agentic, with visual)
- 30% journey/build-in-public (wins, failures, lessons from the empire build)
- 20% repurposed concept graphics (redraw known concepts in Decoded brand style)
- 10% soft product/milestone (only after authority is established)

*Note: this 40/30/20/10 maps to the macro 70/20/10 ratio from MASTER strategy: 70% growth = 40% edu + 30% journey; 20% authority = 20% repurposed graphics; 10% conversion = 10% soft product.*

### The narrow lane (do not dilute)
Multi-cloud IaC, Kubernetes, agentic systems, platform engineering. Kelvin's differentiator: deep cloud/AI expertise paired with a fully human builder's life — gardening, faith, and how those shape the business, systems, and motivations behind the empire. That combination is the moat no competitor can copy. USAF service is part of the journey and can surface naturally, but it is not the headline angle — don't lead with it.

### Inputs
```python
{
  "research_report": dict,
  "kelvin_voice_profile": dict,
  "build_updates": list,             # real progress from the empire build
  "idea_reservoir": list,            # ideas from monthly batch session in [[Idea-Reservoir]]
  "content_mix_ratio": {"edu": 0.4, "journey": 0.3, "repurposed": 0.2, "product": 0.1}
}
```

### Outputs
Weekly post calendar (3–4 posts) with:
- Post copy in Kelvin's voice
- Format per post: `"text_post"` | `"document_carousel"`
  Agent selects: use document_carousel when content has 3–8 discrete points (frameworks, step-by-step, comparisons)
- If `text_post`: image_brief per post (→ MKT-CN1 → Claude Design)
- If `document_carousel`: slide_count (recommended), slide_briefs list (one brief per slide for Canva/Figma → export PDF → upload as LinkedIn document post)
- Hook variants
- Suggested post time

All → HITL queue. **Kelvin approves his own personal brand posts (Tier 3).**

---

## AGENT 5 — MKT-S1: SEO Content Factory

**Wave:** 3
**Depends on:** MKT-R1, product landing page live
**Output:** programmatic SEO articles per MSE product → HITL queue

### What it does
Mirrors DSX-CA1 but scoped to each MSE product's niche. Problem-aware long-tail content that compounds in the background while community + Apollo drive early users.

### Standards (same as DecodedSix content agent)
- Hook answers search intent in first 40 words (AEO)
- E-E-A-T: byline, internal links (3+), external citation (1+)
- FAQ section (3+ Q&A → FAQPage schema)
- Schema markup: Article + FAQPage + BreadcrumbList
- 1,200 word floor
- Conversion articles include product CTA + internal links
- AI crawlers unblocked, citation-dense for GEO

### Cadence
2–3 articles/week per MSE product once launched.

---

## DEFERRED — MKT-AD1: Competitor Ad Agent

**Do NOT build until the ad trigger fires.**

### Ad trigger condition (locked)
Build and activate paid ads ONLY when a product has:
1. Proven organic conversion rate (trial→paid measured and stable), AND
2. LTV > 3× CAC on organic acquisition

### What it will do (when triggered)
Scrape Facebook Ad Library for named competitors, identify running ads, rebuild winning creative with Decoded branding. Feeds paid campaigns — not organic.

---

## GOVERNANCE

### MKT-10: Compliance Guard
Scans every output before a human sees it:
- Platform ToS risk (spam signals, over-automation flags)
- Brand safety
- Outreach compliance (CAN-SPAM, LinkedIn limits)

Blocks non-compliant output before HITL.

### MKT-09: HITL Queue Manager
- Tier 2: Wife approves product marketing + newsletter
- Tier 3: Kelvin approves personal brand posts + escalations

Approved → publishes. Rejected → returns with notes.

---

## LEARNING LOOP

Every published output's performance feeds back to MKT-R1:

| Channel | Metrics tracked |
|---|---|
| LinkedIn | Engagement, saves, profile visits per post |
| Newsletter | Open rate, click rate, reply rate |
| SEO | Keyword rankings, organic traffic per article |
| DM | Reply rate, positive reply rate, trial conversion |

Over cycles, the research core learns which angles, hooks, and language convert for the specific audience. Brand voice becomes automatic. Approval rate rises over time = less HITL effort per post.

---

## TOOLING REFERENCE (2026 current)

| Use case | Tool |
|---|---|
| Concept / diagram graphics | Claude Design (via MKT-CN1 brief, brand colors) |
| Polished infographics | Canva Pro + saved Brand Kit |
| Hand-drawn teaching visuals | Manual (Tuesday build session with son — differentiator) |
| Post analysis / voice replication | Supergrow / Postiv (evaluate if manual repurposing bottlenecks) |
| LinkedIn carousels | Design in Canva/Figma → export PDF → upload as document post (native carousel gone in 2026; PDF-as-document is the standard, boosts dwell time) |
| Shorts avatar | HeyGen $29/mo, 2-min cap — post-launch only |
| Hand-drawn house-style | Ideogram or Gemini Nano Banana — locked prompt + reference image (see [[Visual-Production-Style]]) |

---

## BRAND KIT SETUP (one-time, before first post)

Lock a Decoded Empire visual identity in Canva Brand Kit:
- Primary palette (Decoded Empire brand colors)
- 2 fonts max (one display, one body)
- Logo lockup

Every graphic pulls from it = instant recognizability across all products.

---

## SESSION WAVE ASSIGNMENT

**Wave 1:** MKT-R1 Research Core
**Wave 2:** MKT-N1, MKT-V1, MKT-LI1, MKT-CN1
**Wave 3:** MKT-S1, MKT-O2, MKT-O3 (+ MKT-O4 Outreach Monitor, MKT-PR1 Proof Collector)
**Deferred:** MKT-AD1
