# PROMPT: generate-quote
# Usage: Paste this entire block into a new Claude conversation
# to generate a client quote and invoice-ready document.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.

GENERATE A CLIENT QUOTE:

Client name:       [full name]
Client slug:       [slug]
Tier:              [1 | 2 | 3]
Quote type:        [new engagement | expansion | renewal | ad-hoc]
Scope:             [describe exactly what is being quoted]
Special terms:     [any discounts, payment terms, or conditions]

CLIENT CONTEXT:
- Cloud: [aws | azure | gcp | multi]
- Stack: [what they run]
- Team size: [number of engineers]
- Current DevOps setup: [what they have today]
- Primary pain points: [what is costing them time or money]

PRICING REFERENCE:
Tier 1: $15-25k build + $6-10k/month
Tier 2: $50-85k build + $18-28k/month
Tier 3: $120-250k build + $30-50k/month

ROI BASELINE:
Senior DevOps engineer loaded cost: $180-250k/year ($15-21k/month)

BUILD THE FOLLOWING:
1. Full quote in the standard format below
2. ROI calculation specific to their situation
3. Comparison to their current setup cost
4. .docx quote document ready to send
5. Follow-up email to send with the quote

QUOTE FORMAT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLIENT QUOTE
Client:       [Client Name]
Date:         [Date]
Prepared by:  Kelvin Davis — KDavis Agentic Platform
Quote ref:    [SLUG-YYYYMMDD-001]

[Full line items as defined in new-client-package prompt]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
