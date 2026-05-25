# PROMPT: generate-quote
# Usage: Paste this entire block into a new Claude conversation
# to generate a client quote and invoice-ready document.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

GENERATE A CLIENT QUOTE:

Client name:            [full name]
Client slug:            [slug]
Quote type:             [new engagement | expansion | renewal | ad-hoc]
Scope:                  [describe exactly what is being quoted]
Special terms:          [discounts, payment terms, or conditions]

CLIENT CONTEXT:
Cloud:                  [aws | azure | gcp | multi]
Stack:                  [what they run — be specific]
Team size:              [number of engineers]
Current DevOps setup:   [what they have today]
Primary pain points:    [what is costing them time or money]

SCALE PROFILE:
Applications to monitor:      [X]
Expected daily incidents:     [X]
Peak concurrent incidents:    [X]
Growth projection 12 months:  [X apps]

Based on scale inputs determine automatically:
- Scaling model: vertical (1-20 apps) | horizontal (20-100 apps) |
  queue-based (100+ apps)
- Whether lock manager is included
- Whether queue infrastructure is included (SQS or Service Bus)
- Worker pool size (1 | up to 10 | autoscaled)
- Whether batch escalation aggregation is needed
- Tier recommendation (1 | 2 | 3)

PRICING REFERENCE:
Tier 1: $15-25k build + $6-10k/month  (up to 20 apps, vertical)
Tier 2: $50-85k build + $18-28k/month (20-100 apps, horizontal)
Tier 3: $120-250k build + $30-50k/month (100+ apps, queue-based)

ROI BASELINE:
Senior DevOps engineer loaded cost: $180-250k/year ($15-21k/month)

BUILD THE FOLLOWING:
1. Scale assessment with recommended model and justification
2. Full quote in standard format below
3. ROI calculation specific to their situation and app count
4. Comparison to their current setup cost
5. .docx quote document ready to send
6. Follow-up email to send with the quote

QUOTE FORMAT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLIENT QUOTE
Client:       [Client Name]
Date:         [Date]
Prepared by:  Kelvin Davis — KDavis Agentic Platform
Quote ref:    [SLUG-YYYYMMDD-001]

SCOPE OF WORK
[What the client is getting — plain business language.
What problems it solves. What it replaces.]

SCALE ASSESSMENT
Applications to monitor:      [X]
Estimated daily incidents:    [X]
Peak concurrent incidents:    [X]
Scaling model:                [vertical | horizontal | queue-based]
Queue infrastructure:         [not required | SQS | Service Bus]
Worker pool size:             [1 | up to 10 | autoscaled]
Conflict detection:           [not required | lock manager included]
Escalation model:             [individual | aggregated batch]
Global daily LLM budget cap:  $[X]/day estimated

Why this model:
[Plain language — why this scale fits their situation
and what happens if they grow beyond it.]

Growth path:
If application count grows beyond [X], the package upgrades
to [next tier]. Migration is a configuration change —
no rebuild required.

LINE ITEMS
Initial Build Fee
Core platform deployment              $[X]
Environment setup (dev/staging/prod)  $[X]
Agent configuration for their stack   $[X]
Governance walkthrough and sign-off   $[X]
Documentation and SOPs                $[X]

Scale infrastructure (if applicable)
  Priority queue setup                $[X]
  Worker pool configuration           $[X]
  Lock manager deployment             $[X]
  Autoscaling configuration           $[X]
  Batch escalation setup              $[X]

Testing and validation
  Single workflow validation          $[X]
  Concurrent workflow stress test     $[X]
  Scale simulation ([X] apps)         $[X]
                          Subtotal:   $[X]

Monthly Retainer
Platform operations                   $[X]/mo
Monitoring ([X] applications)         $[X]/mo
Incident response (< [X]hr SLA)       $[X]/mo
Queue infrastructure hosting          $[X]/mo
Worker pool hosting                   $[X]/mo
Monthly cost optimization review      $[X]/mo
                          Subtotal:   $[X]/mo

Cloud Infrastructure (passed through at cost)
  Queue service (SQS/Service Bus)     ~$[X]/mo
  Serverless workers (Lambda/Functions)~$[X]/mo
  Additional compute if needed        ~$[X]/mo
                          Subtotal:   ~$[X]/mo

TOTAL
One-time build:                       $[X]
Monthly retainer:                     $[X]/mo
Cloud infrastructure (est.):          ~$[X]/mo
First month total:                    $[X]

ROI REFERENCE
To monitor [X] apps manually:
  Engineers needed:         [X] FTE
  Loaded cost:              $[X]/month
  On-call burden:           [X] engineers on rotation

This platform at Tier [X]:
  Monthly retainer:         $[X]/month
  Apps monitored:           [X] simultaneously
  Concurrent incidents:     up to [X] at once
  On-call reduction:        [X]% fewer pages to humans

Monthly savings:            $[X]/month
Breakeven:                  [X] months

VALIDITY: 30 days from date above.
To proceed: sign license agreement and return with
50% deposit of build fee.

NOTES:
[Client-specific assumptions or exclusions]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
