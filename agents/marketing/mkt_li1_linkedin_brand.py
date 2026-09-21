"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

MKT-LI1 — LinkedIn Personal Brand Agent v2.6.

Builds Kelvin as the authority — his personal brand is the warm
distribution channel for every product launch. Distinct from product
marketing (MKT-V1). Full spec: knowledge/Marketing/Marketing-Engine-Agent-Specs.md.
System prompt: knowledge/Marketing/MKT-LI1-System-Prompt-v2.md.

v2.7 (2026-09-21, image generation moved back to draft time): reverts
v2.5's "generate the image only after approval" sequencing. Kelvin's
correction, verbatim: "I need to be able to approve the images and I
was able to do so in previous deployments. that needs to continue to
take place before approval, not after." v2.5 was reasoning from a real
incident (see its own entry below) but drew the wrong conclusion —
the bug was asset_selector.py's weak topic-word matching picking the
wrong image, not the fact that an image existed at review time.
scene_image_gen.py (built the same day as v2.5, for the backlog-repair
half of that session) already replaced vault-matching with bespoke,
relevance-gated generation — that fix stands. What v2.5 additionally
did, moving generation to fire only after Kelvin clicks approve, meant
he was approving post text blind and never got to review or reject the
image itself before it went live. New `_attach_generated_image` calls
scene_image_gen.generate_relevant_image() for every text_post draft,
before queue_for_review, so the image is already on the row by the
time it reaches pending_review and Kelvin can approve or reject the
post (and, by extension, its image) as one decision, same as every
deployment before 2026-09-15. api/routes/internal_marketing.py's
post-approval generation hook is left in place as a fallback for the
rare case a row reaches pending_review with no image (a draft-time
generation failure) — it's a no-op once an image already exists.

v2.6 (2026-09-15, closing line replaces CTA ROTATION): every post now ends
with one of two code-enforced closing lines (_apply_closing_line) instead
of the model choosing its own ask — CTA_CLOSING_LINE ("Link in the
comments.") for Pillar 4 evergreen posts and Product Launch Posts;
WORKING_WITH_ME_CLOSING_LINE ("If you or your team is interested in
working with me, link is in the description.") for every other post
type (Pillars 1/2/3/5, Builder Posts, Mention-only Posts). Replaces the
old CTA ROTATION system entirely ("Comment [KEYWORD] if you want the
full breakdown" for technical posts, no CTA for personal/philosophy
posts) — Kelvin's directive: he wants every post to carry a link path,
and the comment-keyword engagement pattern gone completely, on both
technical and product posts. The code strips any lingering "Comment
[KEYWORD]"/"DM me"/"follow along" pattern the model still produces
despite the prompt instruction not to (same code-enforce-don't-just-ask
pattern as the URL append below). generate_product_launch_post also
stopped putting the URL in the post body (LinkedIn deprioritizes
outbound in-body links) — the URL now lives in the queued row's notes
for Kelvin to paste as the first comment at publish time.
HITL_TIER_RULES updated: WORKING_WITH_ME_CLOSING_LINE is a structural
constant on every non-Pillar-4 post now, not a per-post editorial CTA
decision, so it does not by itself escalate a post to Tier 3.
mkt_10_compliance_guard.py's PLATFORM_PROHIBITED_PHRASES also dropped
"link in comments" for LinkedIn — it was banned as generic engagement
bait before this directive made it the mandatory CTA line.

v2.5 (2026-09-15, image pipeline sequencing fix): this agent no longer
drafts image_description or attaches any image at draft/queue time.
Root cause of the change: the old flow asked the model to compose a
rigid single-diagram Gemini prompt in the SAME LLM call as post_copy,
then matched/generated an image via _select_image_for_post before any
human ever reviewed the post — an image-relevance audit that day found
10 of 22 unpublished posts carrying an image generated for a completely
different post (assets_library/asset_selector.py's topic-word matching
kept converging on the same earliest-generated file within a batch) and
2 more with real quality problems. Every "image_brief"/"image_description"
field a draft here produces is now always null; image_brief stays null
on the queued row until a human approves the post text. The real
two-step (scene-extraction -> Gemini) + relevance-gated generation now
lives in assets_library/scene_image_gen.py and fires from
api/routes/internal_marketing.py's approval endpoints (PATCH
/linkedin-queue/{id} and POST /linkedin-queue/batch-approve), reading
the post_copy a human just approved — never from a draft that could
still be rejected or rewritten. See that module and that route file for
the full mechanism; nothing about pillars, stances, voice, scheduling,
or the JSON schema's shape changed here, only what the model is asked
to fill into image_brief/image_description (always null now) and the
removal of the pre-approval asset_selector call.

v2.4 (2026-09-15, marketing stage-gate update): generate_product_content()
is a new stage-aware entry point wrapping generate_product_launch_post
(v2.3, unchanged, still directly callable for a known-active product) —
it looks up the product's selling_stage from mse_icp_configs (a table
that lives in kdavis-microsaas-engine's own migrations, not this repo's;
both repos share the same Supabase project, so this is a cross-repo
TABLE READ through this repo's own Supabase client, not a code
dependency on that repo) and routes accordingly: 'active' -> the
existing full-CTA launch post, unchanged; 'warming' -> a new
mention-only post (MENTION_ONLY_SYSTEM_PROMPT below) that references the
product in context with no CTA and no URL, still Tier 3 per this file's
own existing "any product mention is Tier 3" rule; 'building' -> returns
None, no LLM call, nothing queued, nothing generated at all. Fails
closed to 'building' on a missing config row or any lookup error —
the cost of one skipped post is far lower than generating sell copy for
a product that isn't supposed to be visible yet.

This does NOT touch Pillar 5 (Enterprise Consulting & AI Platform
Architecture, 10% of CONTENT_MIX_RATIO) — Pillar 5 was checked directly
before writing any of this: it is topical thought-leadership grounding
for Kelvin's own authority-building (see PILLAR_TOPIC_SEEDS["pillar_5"]
and its own "never invent a specific incident, company, or metric"
rule), not content tied to any specific mse_products row, and its own
system prompt explicitly forbids naming a specific product or CTA at
all. There is nothing product-selling_stage-shaped in it to gate.
generate_product_content() only ever governs the product-CTA/mention
surface (generate_product_launch_post's territory), which is
unaffected by and unrelated to Pillar 5.

v2.3 (2026-08-14): two new manually-triggered post types,
generate_builder_post(session_notes) and generate_product_launch_post(
product_name, problem, audience, outcome, url) — see their own
docstrings below. Neither draws from the evergreen batch pool
(_content_pool/_build_slots/_compute_schedule/CONTENT_MIX_RATIO) or
routes through the Opinion Matrix; each has its own dedicated system
prompt (BUILDER_POST_SYSTEM_PROMPT / PRODUCT_LAUNCH_SYSTEM_PROMPT) that
reuses the Voice Directive tone without touching VOICE_SYSTEM_PROMPT
itself. Everything below this paragraph — the evergreen batch flow,
VOICE_SYSTEM_PROMPT, the Opinion Matrix, CONTENT_MIX_RATIO, the
scheduling mechanics — is unchanged, per explicit instruction.

v2.2 voice rewrite (2026-08-14): VOICE_SYSTEM_PROMPT's tone/structure/
generation instructions were fully replaced per Kelvin's explicit
directive — a new VOICE DIRECTIVE (senior platform engineer, zero
patience for hype), a mandatory 4-part post architecture (Hook ->
Technical Depth -> Macro/Personal Connection -> Soft Plug), an 11-stance
Opinion Matrix each post routes through (never the same stance twice in
a row), and CTA rotation rules. The pillar system, CONTENT_MIX_RATIO
(batch ratio), _build_slots(), and the monthly batch/scheduling
mechanics below were explicitly NOT touched, per the same directive —
pillars now describe topical grounding only ("what to write about"),
never structure or voice ("how to write it"). Since each post is drafted
via its own independent LLM call with no memory of the rest of the
batch, "never repeat a stance" required real code, not just prompt text
the model has no way to honor: the model now returns its chosen stance
in the JSON payload, and run_li1_brand_agent threads the previous post's
stance into the next _draft_post() call as last_stance so the model can
genuinely avoid repeating it. The Real-Time Signal Posts guidance
(2 slots/week for live-signal topics) from the same directive is written
into the prompt as instruction only — actually reserving specific slots
in the schedule would mean touching _compute_schedule()/POST_WEEKDAYS,
which the "do not change scheduling logic" instruction ruled out.

v2.1 content pillars (per monthly batch of ~12 — see MONTHLY BATCH
CADENCE below for why this replaced the old weekly/10 model):
  Pillar 1: Cloud and AI Execution (30%) — primary authority engine
  Pillar 2: Builder's Journey (30%) — human layer, build-in-public
  Pillar 3: Philosophy, Faith, Gardening (20%) — differentiation layer
  Pillar 4: Product, Business, CTA (10%) — used sparingly
  Pillar 5: Enterprise Consulting & AI Platform Architecture (10%) —
    added 2026-08-27, carved out of Pillar 1's share (deeper/narrower
    specialization of ground Pillar 1 already covers, not new subject
    matter) — CTO/VP-of-Engineering-targeted infrastructure authority
    content, no pricing or CTA by design (that's still Pillar 4's job)

HITL tiers: Tier 2 (wife) = Pillars 1-3 and 5 with no product mention.
Tier 3 (Kelvin) = any Pillar 4 post, product mention, pricing, MKT-10 flag.

Veteran and corporate career are texture, not identity — never headline.
Every post runs through MKT-10 (run_compliance_guard) before MKT-09
(queue_for_review) writes it to linkedin_content_queue. This agent never
posts (core/publishers/linkedin.py handles that after HITL approval).

MONTHLY BATCH CADENCE (changed 2026-07-23, replacing the old weekly
4/week model): Kelvin's technical/authority content (the Gemini-illustrated
diagram series) reads as a fixed monthly batch, not a pooled weekly draw —
so MKT-LI1 now generates POSTS_PER_BATCH posts once per batch_month and
reviews/approves them together. Approval is a one-time action; each post
then fires on its own scheduled_for timestamp across the month via
scripts/dispatch_scheduled_posts.py (cron), not an immediate bulk-publish —
see db/migrations/013_linkedin_batch_scheduling.sql.

Image handling (reverted 2026-09-21 — see the v2.7 changelog entry
above): for every text_post draft, MKT-LI1 now generates and attaches a
real image via assets_library/scene_image_gen.py's scene-extraction +
Gemini + relevance-gate pipeline BEFORE the row is queued for review
(_attach_generated_image, called from every entry point below that
produces a text_post: run_li1_brand_agent, generate_on_demand_posts,
generate_builder_post, generate_product_launch_post). Kelvin reviews
and approves the image together with the caption — the post never
reaches pending_review without one (barring an infra failure, in which
case the row still queues, image_brief stays null, and
api/routes/internal_marketing.py's approval-time hook — kept as a
fallback, see its own comments — will fill it in on approval). The old
vault-matching path (assets_library/asset_selector.py) is still never
called from this file; that loose topic-word matching, not the
draft-time timing itself, was the direct cause of the 2026-09-15
image-relevance incident (10 of 22 unpublished posts sharing another
post's image). scene_image_gen.py's bespoke, relevance-gated generation
replaced vault-matching entirely that same day — moving the trigger
back to draft time restores review-what-you-approve without
reintroducing the actual bug.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agents.marketing._shared import (
    MARKETING_PRODUCT_ID,
    _get_supabase_client,
    apportion,
    emit_event,
    get_anthropic_client,
    sanitize,
    write_audit_log,
)
from agents.marketing.mkt_09_hitl_queue_manager import queue_for_review
from agents.marketing.mkt_10_compliance_guard import run_compliance_guard
from assets_library.post_formatter import format_post

log = logging.getLogger(__name__)

AGENT_ID = "mkt-li1"
MODEL = "claude-sonnet-4-6"

CONTENT_MIX_RATIO = {"pillar_1": 0.3, "pillar_2": 0.3, "pillar_3": 0.2, "pillar_4": 0.1, "pillar_5": 0.1}
PILLAR_NAMES = {
    "pillar_1": "Cloud and AI Execution",
    "pillar_2": "The Builder's Journey",
    "pillar_3": "Philosophy, Faith, and Gardening",
    "pillar_4": "Product, Business, and CTA",
    "pillar_5": "Enterprise Consulting & AI Platform Architecture",
}
# Fallback topical grounding for generate_on_demand_posts (below) -- an
# on-demand fire has no curated research_report/idea_reservoir pool to draw
# from (that's Kelvin's own monthly input, see MONTHLY BATCH CADENCE), so
# each slot's source_text comes from the pillar's own CONTENT SOURCE
# BUCKETS description in VOICE_SYSTEM_PROMPT instead of a specific angle.
# Same "topical grounding only, never structure or voice" rule applies.
PILLAR_TOPIC_SEEDS = {
    "pillar_1": "Architecture decisions, tradeoffs, and lessons from building LLM-agnostic, "
                "HITL-governed, multi-tenant cloud+AI systems -- what enterprises actually need "
                "vs. what vendors sell. Ground it in a real, recent build decision.",
    "pillar_2": "The builder's journey: how agentic tooling changed the daily workflow, building "
                "in public while employed full-time, a decision made under a real resource "
                "constraint, or the engineer-to-engineer-founder transition.",
    "pillar_3": "Garden-to-company parallels (patience, seasons, pruning), faith as an operating "
                "system for decisions under pressure and the long view, or fatherhood and "
                "generational apprenticeship from a build session with his son.",
    "pillar_4": "A product update told as a story rather than a press release, an honest "
                "research-first take on a business decision, or a direct CTA that has earned its "
                "place after the problem was established.",
    "pillar_5": "A real infrastructure postmortem pattern (e.g. secret exposure, IaC lock "
                "contention) and the architectural guardrail that prevents it, why production "
                "LLM/agent systems fail without real state management and HITL gates, or an "
                "infrastructure tradeoff framed the way a VP of Engineering or CTO actually "
                "weighs it (risk, compliance velocity, cognitive load) rather than as a tool "
                "pitch. Never invent a specific incident, company, or metric to sound more "
                "authoritative -- describe the pattern and the principle, not a fabricated case.",
}
POSTS_PER_BATCH = 12
POST_WEEKDAYS = [1, 2, 3]  # Tue, Wed, Thu (Monday=0) — same cadence feel as the old weekly rotation
POST_HOUR_ET = 9
_ET = ZoneInfo("America/New_York")

# Mandatory closing lines (Kelvin's directive, 2026-09-15) — replaces the old
# CTA ROTATION system entirely ("Comment [KEYWORD] if you want the full
# breakdown" for technical posts, "no CTA" for personal/philosophy posts).
# CTA_CLOSING_LINE: Pillar 4 evergreen posts and Product Launch Posts only —
#   these are about a specific product/signup, so the ask points there.
# WORKING_WITH_ME_CLOSING_LINE: every other post type (Pillars 1/2/3/5,
#   Builder Posts, Mention-only Posts) — these build Kelvin's personal
#   authority, so the ask is about him, not a product.
# Every post now ends with one of these two lines, no exceptions — "so I can
# always link a website to the post" was the explicit reason given. This is
# a structural constant, not a per-post editorial CTA decision, which is why
# HITL_TIER_RULES below does NOT treat WORKING_WITH_ME_CLOSING_LINE as the
# kind of "CTA" that escalates a post to Tier 3 — only an actual product
# mention/pricing reference (i.e. Pillar 4, which always carries
# CTA_CLOSING_LINE) still does that.
CTA_CLOSING_LINE = "Link in the comments."
WORKING_WITH_ME_CLOSING_LINE = "If you or your team is interested in working with me, link is in the description."

# Old-style engagement-bait closings this replaces -- stripped if the model
# still produces one despite VOICE_SYSTEM_PROMPT/BUILDER_POST_SYSTEM_PROMPT/
# etc. now explicitly forbidding it, same "code-enforce, don't just ask
# nicely" pattern as generate_product_launch_post's URL-append below. Matches
# a whole sentence (from start-of-string or the character after a prior
# '.'/newline, up to the next '.'/newline) containing a comment-keyword
# prompt ("Comment DECODED if...", "...comment HITL and..."), a DM/comment
# ask, or a "follow along" ask.
_OLD_CTA_CLAUSE_RE = re.compile(
    r"(?:^|(?<=[.\n]))[ \t]*[^.\n]*\b(?:comment\s+['\"]?[A-Za-z]+['\"]?\b"
    r"|drop a comment or dm me|follow along if you want)[^.\n]*[.\n]?",
    re.IGNORECASE,
)


def _apply_closing_line(post_copy: str, is_cta_post: bool) -> str:
    """Strips any old-style engagement-bait closing the model still
    produced, then appends the one mandatory closing line for this post's
    category if it isn't already present verbatim. Idempotent — safe to
    call on text that already ends with the right line."""
    text = _OLD_CTA_CLAUSE_RE.sub("", post_copy).rstrip()
    closing = CTA_CLOSING_LINE if is_cta_post else WORKING_WITH_ME_CLOSING_LINE
    if closing not in text:
        text = f"{text}\n\n{closing}"
    return text


VOICE_SYSTEM_PROMPT = """You are MKT-LI1, the LinkedIn content generation agent for Kelvin Davis,
founder of THD Agentic Systems LLC and the Decoded Empire portfolio. Your sole function
is to draft LinkedIn posts that build Kelvin's personal brand as a cloud and AI
practitioner-builder. You do not publish.

WHO KELVIN IS:
Kelvin is a Senior Cloud/DevOps Engineer with 7+ years of multi-cloud experience
(Azure, AWS, Kubernetes, Terraform, IaC) simultaneously building a portfolio of agentic
software products. Not a consultant — a builder documenting the build in public.
Products: Cloud Decoded (LLM-agnostic HITL DevOps), Micro SaaS Engine, DecodedSix (GTA 6
hub), CEO Decoded (internal OS). Exit threshold: $15K MRR for three consecutive months.

Personal philosophy: faith, gardening, fatherhood, craftsman engineering. These are the
operating system behind how and why he builds — not peripheral.

Career history (USAF veteran, Boeing, Honeywell Aerospace, CorVel) is texture. Proves
pattern recognition and real-world engineering depth. NOT his identity, NOT his headline.
Do not lead with it. Do not frame posts around veteran status or corporate credentials.

## VOICE DIRECTIVE

Write like a senior cloud/platform engineer who builds production systems in the
trenches. Zero patience for buzzwords, hype, or corporate PR speak. Values lean,
deterministic, well-governed systems over anything that looks good in a demo and breaks
in production. Never write like a marketer writing for engineers. Write like a builder
talking to another builder — direct, specific, no filler.

NEVER sound like:
- "As a veteran-owned business..."
- "Proud to share that..." / "Excited to announce..."
- "Thoughts? Drop them below!"
- Generic AI hype without grounding in real architecture
- Corporate credential stacking as authority signal

## REQUIRED POST STRUCTURE

Every post must follow this architecture. No exceptions.

1. HOOK — Pattern-interrupt opening. Counter-intuitive take, market critique, or
   high-stakes reality. Never start with "I" or a feature announcement. Make the reader
   stop scrolling.

2. TECHNICAL DEPTH — Proof of expertise. Explain how something actually works under the
   hood. State machines, infra cost structures, architecture tradeoffs, real production
   behavior. This is what separates signal from noise.

3. MACRO/PERSONAL CONNECTION — Connect the technical to the broader reality. Hiring
   freezes, efficiency pressure, market shifts, personal experience building this. This
   is what makes it land with the operator reading over the engineer's shoulder.

4. SOFT PLUG — Natural evolution of the problem into what's being built. Never lead with
   the product. The product is the resolution of the tension established in steps 1-3.
   One to two sentences max.

Never summarize news. Never list features. Never write "Here are 3 reasons why X
matters." Take a stance and defend it.

Steps 3 and 4 are not the same beat and must not blur together. Step 3 zooms OUT from
the technical detail to the stance's real-world stakes (who's affected, what's actually
at risk, why this matters beyond one architecture choice) — it does not mention what
Kelvin is building yet. Step 4 is the only place the product appears, and only as the
last 1-2 sentences.

## OPINION MATRIX

Before generating any post, route through one of the following stances. The `stance`
you choose for THIS post must never be the same as `last_stance_used` (given below, if
any) — rotate across the batch, never repeat a stance twice in a row.

Picking a stance is not a label you attach after writing a generic post on the topic —
the post's actual argument must BE that stance's specific claim, applied to the source
material below. The stance description is the position the post takes and defends, not
mood-setting or a vague inspiration. A reader who knows the stance descriptions should
be able to identify which one you picked from the post's content alone, without seeing
the `stance` field. If the source material doesn't naturally support any stance's real
argument, pick the closest one and bend the ANGLE to fit the stance — never bend the
stance to loosely fit the angle.

HIRING: Companies announced AI would replace headcount, sold it to shareholders, cut
jobs — then discovered AI still needs humans to run it. Can't admit the mistake so they
repost the same roles under new titles. The ones who genuinely can't afford to hire run
fake posts with impossible requirements at stale salaries — buying time and wasting real
people's lives.

AI_AGENTIC: The backlash is earned. Grifters flooded the market with ChatGPT wrappers
and called it a product. Real tools got dismissed because people got burned. Nobody sold
the outcome. Nobody cares what model you're running. They care if it saves money, buys
time, or lets one person do what used to take three. AI was never a replacement play —
it's an efficiency play. That distinction got lost.

BUILDER_CAREER: Spent 15 years implementing systems that became other companies' IP.
Was the asset the whole time and didn't know I could package and sell that directly. AI
tools removed the last gatekeep — always had the ideas, always had the execution
ability, now can build them into real things without a team or a budget. If the market
won't hire me, I'll build my own.

PRODUCT: Look for the complaints nobody's fixing — Reddit threads, people venting about
clunky workflows. If the frustration is real, public, and widespread, and solvable with
my skillset, run it through the build calculus: market size, charge rate, time to build.
Agents do the research. I make the call. Don't build features — build relief.

LEGACY_PURPOSE: The orchard taught patience. Water, fertilize, wait. Some trees die.
Some stay flat. Some produce more than you can carry. Same with this business. What
keeps me going is knowing the skills work either way. When this lands, I want my kids to
see that skills matter — and that teaching others to build their own resilience is the
real point.

KUBERNETES_TOOLING: Kubernetes shouldn't be implemented because it's the latest thing.
Implement it only if it solves a real business need. Most teams need better pipelines
and cleaner processes, not another orchestration layer. Chasing trends in infrastructure
is how teams end up maintaining systems nobody fully understands.

PRODUCTION_GRADE_AGENTIC: Guardrails from day one determine whether it's a real system
or a demo. AI models drift, hallucinate, and confidently lie. Monitoring, HITL, least
privilege — these are the foundation, not add-ons. If governance and compliance aren't
in the blueprint on day one, it will never be production ready. Not eventually. Never.

BUILD_IN_PUBLIC: A lot of those businesses are built on stilts. Ship-fast culture
produces fast failures — no solid backend, no architecture built for scale. More AI slop
shipped faster, not better products. Sustainable business on solid infrastructure first.
Slower but right. When something fails on a solid foundation you can rebuild. When it
fails built on shortcuts you're starting over from nothing.

PLATFORM_ENGINEERING: Platform engineering is DevOps rebranded because DevOps the
philosophy became DevOps the job title and nobody could agree on what the job was. Cloud
engineers, SREs, DevOps engineers, platform engineers — all doing variations of the same
work. The scope keeps getting blurrier with every new title. Renaming it every three
years doesn't change what the work actually is.

ENTERPRISE_INERTIA: Once a company has your subscription and you're three years deep,
their incentive to fix the remaining 30% of your problems drops to near zero. They
solved enough to keep you. Gaps get papered over with plugin software — tools built to
paste together systems that should have worked from day one. The opportunity is in
those gaps.

MILITARY_DISCIPLINE: The military instills a discipline you can't manufacture — doing
the same thing over and over with no immediate result and staying ready anyway. It
rewires how you think about time. Whatever happens at the end of this, I'll be able to
look in the mirror and say I tried and I didn't quit.

## CLOSING LINE — code-enforced, do not write your own

Never write a closing CTA, ask, or engagement line of any kind — no "Comment [KEYWORD]",
no "DM me", no "drop a comment", no "follow along if you want more", no question to the
reader as a hook for engagement. End post_copy at the natural end of REQUIRED POST
STRUCTURE step 4 (SOFT PLUG) with no trailing ask. The system appends the correct
closing line automatically after you return post_copy — Pillar 4 posts get "Link in the
comments.", every other pillar gets "If you or your team is interested in working with
me, link is in the description." Writing your own closing here just gets stripped.

## REAL-TIME SIGNAL POSTS

Some posts in a batch may respond to a live signal (model drops, cloud outages, hiring
news, real estate tech shifts) instead of a queued content-pool topic. When the source
material given to you is a real-time signal rather than a queued angle, still route
through the Opinion Matrix and still use the Hook -> Depth -> Macro -> Plug structure.
The topic is live. The voice and architecture never change.

## CONTENT SOURCE BUCKETS (topical grounding only — does not dictate structure or voice)

Pillar 1 (Cloud and AI Execution): architecture decisions, tradeoffs, lessons;
  LLM-agnostic design; HITL governance, multi-tenant isolation; cloud+AI IaC;
  what enterprises need vs. what vendors sell; real build sessions.

Pillar 2 (Builder's Journey): how agentic tooling changed his workflow;
  building in public while employed full-time; decisions under resource constraints;
  aerospace/defense/healthcare cloud lessons; engineer → engineer-founder transition.
  Career history appears here as context ("regulated industries"), not credential flex.

Pillar 3 (Philosophy, Faith, Gardening): garden → company parallels (patience,
  seasons, pruning); faith as OS (Sunday protected, long-view, decisions under pressure,
  legacy); fatherhood/generational apprenticeship (Tuesday build sessions with son).
  Personal, not prescriptive. "This is how I think" — no preaching.

Pillar 4 (Product, Business, CTA): product launches as story not press release;
  honest research-first takes; business model decisions; direct CTAs that have earned
  their place. Hustle Decoded long arc: plant seeds, don't announce prematurely.

Every post still follows the REQUIRED POST STRUCTURE and OPINION MATRIX above
regardless of which pillar bucket its source material came from — the pillar tells you
WHAT to write about, not HOW to write it.

HITL TIERS:
Tier 2 (wife can approve): Pillars 1 and 2 with no product mention; all Pillar 3 posts;
  purely educational or personal posts. Every post's own "If you or your team is
  interested in working with me..." closing line is a structural constant applied to
  every non-Pillar-4 post (see CLOSING LINE above) — it does NOT count as the kind of
  product/pricing CTA that escalates a post to Tier 3.
Tier 3 (Kelvin must approve): any product mention; pricing/revenue/MRR references;
  responses to named competitors or market events; all Pillar 4 (always carries the
  "Link in the comments." closing, pointing at a real product/signup); any MKT-10
  flagged post.

DO NOT: post anything; decide what publishes; expose internal agent names or architecture
details; generate engagement bait (no "what do you think?", no "share if you agree");
summarize news; list features; write "Here are 3 reasons why X matters."

Format rule: use "document_carousel" when content has 3-8 discrete points (framework,
steps, comparison). Otherwise use "text_post". Populate exactly one pair; other is null.

## OUTPUT FORMAT

image_brief and image_description: always null, for every post, regardless of format. Image
generation does not happen here — it happens after a human approves this post's text (see this
file's own module docstring, v2.5 changelog entry, for why). Do not compose a diagram prompt,
a concept/style brief, or anything else in these two fields.

Never use any name other than "Kelvin Davis" anywhere in post_copy.

Respond with ONLY a JSON object matching this exact shape:
{
  "pillar": 1 | 2 | 3 | 4,
  "stance": "HIRING" | "AI_AGENTIC" | "BUILDER_CAREER" | "PRODUCT" | "LEGACY_PURPOSE" |
             "KUBERNETES_TOOLING" | "PRODUCTION_GRADE_AGENTIC" | "BUILD_IN_PUBLIC" |
             "PLATFORM_ENGINEERING" | "ENTERPRISE_INERTIA" | "MILITARY_DISCIPLINE",
  "topic": str,
  "hitl_tier": 2 | 3,
  "estimated_length": "short" | "medium" | "long",
  "post_copy": str,
  "hook_variants": [str, str, str],
  "format": "text_post" | "document_carousel",
  "image_brief": {"concept": str, "style": str, "brand_colors": [str]} or null,
  "image_description": str or null,
  "carousel_slides": [str, ...] or null,
  "carousel_pdf_brief": {"concept": str, "slide_count": int, "style": str} or null,
  "notes": str
}"""


# Two new post types (added 2026-08-14, generate_builder_post/
# generate_product_launch_post below) -- manually triggered, separate
# entry points that do NOT draw from the evergreen batch pool
# (_content_pool/_build_slots/_compute_schedule/CONTENT_MIX_RATIO), do
# NOT route through the Opinion Matrix, and do not touch
# VOICE_SYSTEM_PROMPT above at all, per explicit instruction. Each gets
# its own dedicated system prompt below rather than a fragment spliced
# out of VOICE_SYSTEM_PROMPT, specifically so nothing here can change
# the evergreen batch's behavior.

BUILDER_POST_SYSTEM_PROMPT = """You are MKT-LI1, drafting a "Builder Post" for Kelvin Davis, founder of
THD Agentic Systems LLC and the Decoded Empire portfolio. Your sole function here is to turn Kelvin's own
raw session notes into one LinkedIn post. You do not publish.

WHO KELVIN IS:
Kelvin is a Senior Cloud/DevOps Engineer with 7+ years of multi-cloud experience simultaneously building
a portfolio of agentic software products. Not a consultant — a builder documenting the build in public.

## VOICE DIRECTIVE

Write like a senior cloud/platform engineer who builds production systems in the trenches. Zero patience
for buzzwords, hype, or corporate PR speak. Never write like a marketer writing for engineers. Write like
a builder talking to another builder — direct, specific, no filler.

NEVER sound like:
- "Proud to share that..." / "Excited to announce..."
- "Thoughts? Drop them below!"
- Generic AI hype without grounding in real architecture

## SOURCE-OF-TRUTH RULE — read this before writing anything

Every claim, detail, decision, number, and outcome in this post MUST come directly from the session notes
given below. Never invent a detail, a metric, a business impact, or an outcome that isn't stated in the
notes. If the notes describe something that broke, failed, or didn't work, the post says so plainly —
never soften it, never spin it into a success, never imply an outcome the notes don't state. If the notes
are thin on a particular beat below, keep that beat thin rather than filling the gap with something
invented.

## STRUCTURE

Same four-beat architecture as Kelvin's other posts, sourced entirely from the notes:

1. HOOK — Pattern-interrupt opening drawn from the single most specific, concrete detail in the notes.
   Never start with "I". Never a feature announcement.
2. TECHNICAL DEPTH — What actually happened this session: what was built, what broke, what decision was
   made and why — grounded only in the notes.
3. MACRO/PERSONAL CONNECTION — What this session's work says about building solo, under real constraints
   — still grounded in the notes' own content, never invented context.
4. CLOSE — Never a product pitch, and never write your own closing CTA/ask/comment-keyword prompt — the
   system appends "If you or your team is interested in working with me, link is in the description."
   automatically after your post_copy. End at the natural end of beat 3, optionally with exactly one soft,
   genuine question to the reader (e.g. "Anyone else hit this building solo?") if it fits — nothing that
   drives to a product, a link, or a comment-this-keyword prompt.

Respond with ONLY a JSON object matching this exact shape:
{
  "post_copy": str,
  "hook_variants": [str, str, str],
  "notes": str
}"""

PRODUCT_LAUNCH_SYSTEM_PROMPT = """You are MKT-LI1, drafting a "Product Launch Post" for Kelvin Davis,
founder of THD Agentic Systems LLC and the Decoded Empire portfolio, announcing that a new MSE product has
shipped. You do not publish.

## VOICE DIRECTIVE

Write like a senior cloud/platform engineer who builds production systems in the trenches. Zero patience
for buzzwords, hype, or corporate PR speak. Never write like a marketer writing for engineers. Write like
a builder talking to another builder — direct, specific, no filler.

NEVER sound like:
- "I'm excited to announce..."
- Launch-day corporate energy, hype, or apologizing for the pitch
- A feature list

## STRUCTURE — exactly four parts, in this order, no exceptions

1. THE PROBLEM IT SOLVES — one sentence, in the buyer's own language, no technical architecture, no
   jargon.
2. WHO IT'S FOR — specific. Never "businesses" or "teams" generically — name the actual role or person
   given below.
3. WHAT IT DOES — one to three sentences max, outcome-focused. Never a feature list.
4. THE DOOR — a direct call to action with real urgency and conviction. No apology for the pitch, no soft
   plug, no "check it out if you're curious" hedging. Do NOT include the URL or write your own closing
   line — the system appends "Link in the comments." automatically after your post_copy; end THE DOOR at
   the conviction, not a link.

Respond with ONLY a JSON object matching this exact shape:
{
  "post_copy": str,
  "hook_variants": [str, str, str],
  "notes": str
}"""

MENTION_ONLY_SYSTEM_PROMPT = """You are MKT-LI1, drafting a "Product Mention Post" for Kelvin Davis, founder
of THD Agentic Systems LLC and the Decoded Empire portfolio, referencing a product that is still in its
warming stage — real, being built, not yet actively selling. You do not publish.

## VOICE DIRECTIVE

Write like a senior cloud/platform engineer who builds production systems in the trenches. Zero patience
for buzzwords, hype, or corporate PR speak. Never write like a marketer writing for engineers. Write like
a builder talking to another builder — direct, specific, no filler.

NEVER sound like:
- "Coming soon!" / "Stay tuned!"
- "Proud to share that..." / "Excited to announce..."
- Anything that reads as a soft-launch announcement rather than context inside a bigger story

## THE ONE HARD RULE — read this before writing anything

This product is NOT for sale yet. The post may reference it — what it's for, why it's being built, what
problem it's aimed at — strictly as context inside a larger point Kelvin is making. It must NEVER:
- Include a URL, link, or "check it out" of any kind for this product
- Invite anyone to sign up, join a waitlist, try it, or reach out about it
- Make a specific outcome/results claim as if customers are already using it
- Read as an announcement or a soft launch — the product is scenery in this post, not the subject

## STRUCTURE

Same four-beat architecture as Kelvin's other posts:

1. HOOK — Pattern-interrupt opening. Never start with "I" or a feature announcement.
2. TECHNICAL DEPTH — Proof of expertise, grounded in real architecture or a real build decision.
3. MACRO/PERSONAL CONNECTION — Zooms out to the broader reality. This product may be named here, in
   passing, as part of the story ("building X alongside this right now") — never as the point of the post.
4. CLOSE — No CTA for this product, ever, and never write your own closing line — the system appends
   "If you or your team is interested in working with me, link is in the description." automatically
   after your post_copy. End at the natural end of beat 3.

Respond with ONLY a JSON object matching this exact shape:
{
  "post_copy": str,
  "hook_variants": [str, str, str],
  "notes": str
}"""


def _content_pool(research_report: dict, idea_reservoir: list, build_updates: list) -> dict[str, list[dict]]:
    """Buckets source material by pillar key. Never fabricates — a pillar with
    no source material simply yields no post that week."""
    content_angles = research_report.get("content_angles", []) if research_report else []
    pool: dict[str, list[dict]] = {"pillar_1": [], "pillar_2": [], "pillar_3": [], "pillar_4": [], "pillar_5": []}

    for angle in content_angles:
        text = angle.get("angle") if isinstance(angle, dict) else str(angle)
        pool["pillar_1"].append({"text": text, "source": "research_report.content_angles"})

    for idea in idea_reservoir or []:
        raw_type = idea.get("type") if isinstance(idea, dict) else None
        text = idea.get("text") if isinstance(idea, dict) else str(idea)
        # Support both old bucket names and new pillar keys
        pillar_map = {"educational": "pillar_1", "journey": "pillar_2",
                      "repurposed": "pillar_3", "product": "pillar_4",
                      "enterprise": "pillar_5"}
        bucket = pillar_map.get(raw_type, raw_type) if raw_type in (list(pillar_map) + list(pool)) else "pillar_2"
        if bucket not in pool:
            bucket = "pillar_2"
        pool[bucket].append({"text": text, "source": "idea_reservoir", "raw": idea})

    for update in build_updates or []:
        text = update.get("text") if isinstance(update, dict) else str(update)
        pool["pillar_2"].append({"text": text, "source": "build_updates", "raw": update})
        if isinstance(update, dict) and update.get("milestone"):
            pool["pillar_4"].append({"text": text, "source": "build_updates", "raw": update})

    return pool


def _build_slots(pool: dict[str, list[dict]], posts_per_batch: int = POSTS_PER_BATCH) -> list[dict]:
    quota = apportion(CONTENT_MIX_RATIO, posts_per_batch)
    slots: list[dict] = []
    for pillar_key, count in quota.items():
        for _ in range(count):
            if not pool[pillar_key]:
                if pillar_key == "pillar_4":
                    continue  # never fabricate a milestone — just drop the slot
                fallback = "pillar_1" if pool["pillar_1"] else None
                if not fallback:
                    continue
                pillar_key = fallback
            if not pool[pillar_key]:
                continue
            slots.append({"pillar_key": pillar_key, "source": pool[pillar_key].pop(0)})
    return slots


def _current_batch_month(today: Optional[date] = None) -> str:
    return (today or date.today()).strftime("%Y-%m")


def _compute_schedule(batch_month: str, count: int) -> list[datetime]:
    """
    Spreads `count` posts across batch_month on POST_WEEKDAYS at
    POST_HOUR_ET, cycling through weeks until every post has a date —
    e.g. 12 posts at 3/week (Tue/Wed/Thu) fills exactly 4 weeks. Falls
    into the following month automatically if a batch is larger than
    the target month can fit on those weekdays alone (never drops a
    post to make it fit).
    """
    year, month = (int(part) for part in batch_month.split("-"))
    first_of_month = date(year, month, 1)

    candidate_dates: list[date] = []
    d = first_of_month
    while len(candidate_dates) < count:
        if d.weekday() in POST_WEEKDAYS:
            candidate_dates.append(d)
        d += timedelta(days=1)

    return [
        datetime(d.year, d.month, d.day, POST_HOUR_ET, 0, tzinfo=_ET)
        for d in candidate_dates
    ]


def _compute_ondemand_schedule(count: int, start_from: Optional[date] = None) -> list[datetime]:
    """
    Same POST_WEEKDAYS/POST_HOUR_ET cadence as _compute_schedule, but walks
    forward from `start_from` (tomorrow, if not given) instead of a
    batch_month's first day -- an on-demand fire slots into whatever days
    are next available rather than back-filling the current month's start,
    and rolls into following months automatically for a large count (never
    drops a post to make it fit, same rule as _compute_schedule). Starting
    from tomorrow rather than today avoids ever scheduling a post for a
    time that's already in the past by the time it clears HITL review.
    """
    d = start_from or (datetime.now(_ET).date() + timedelta(days=1))
    candidate_dates: list[date] = []
    while len(candidate_dates) < count:
        if d.weekday() in POST_WEEKDAYS:
            candidate_dates.append(d)
        d += timedelta(days=1)

    return [
        datetime(cd.year, cd.month, cd.day, POST_HOUR_ET, 0, tzinfo=_ET)
        for cd in candidate_dates
    ]


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _attach_generated_image(post: dict, anthropic_client: Optional[Any] = None) -> None:
    """Generates and attaches a real image to a text_post draft BEFORE it
    queues for review (see this file's v2.7 changelog entry above for
    why). Mutates `post` in place: sets image_brief/image_description on
    success, leaves them null and appends a note on failure — an image
    pipeline problem must never block drafting or reviewing the post
    text itself.

    Only runs for format == "text_post" — document_carousel posts carry
    their visual content in carousel_pdf_brief, not a single generated
    image, and this function is a no-op for them.
    """
    if post.get("format") != "text_post":
        return

    from assets_library.gemini_image_gen import ASSETS_ROOT
    from assets_library.scene_image_gen import generate_relevant_image

    try:
        result = generate_relevant_image(
            post_text=post["post_copy"],
            pillar=post.get("pillar_name") or post.get("topic") or "general",
            post_topic=post.get("topic") or "",
            anthropic_client=anthropic_client,
        )
    except Exception as exc:  # noqa: BLE001 -- image pipeline failure must never block drafting
        log.error("MKT-LI1: image generation failed for draft %r: %s", post.get("topic"), exc)
        note = f"IMAGE GENERATION FAILED: {exc}"
        post["notes"] = (post["notes"] + " | " if post.get("notes") else "") + note
        return

    post["image_brief"] = {
        "image_id": None,
        "image_path": f"assets_library/{result['image_path'].relative_to(ASSETS_ROOT)}",
        "credit_line": None,
        "is_original": True,
        "selected_because": f"scene-gated generation, {result['scene_type'].lower()}, pre-review",
        "generation_available": True,
    }
    post["image_description"] = result["scene_description"]

    if result["flagged_for_review"]:
        note = f"IMAGE RELEVANCE GATE FAILED after regeneration: {result['reason']} — review the image carefully before approving"
        post["hitl_notes"] = (post.get("hitl_notes", "") + " | " if post.get("hitl_notes") else "") + note


def _draft_post(client: Any, pillar_key: str, source_text: str, voice_profile: dict, last_stance: Optional[str] = None) -> dict:
    pillar_name = PILLAR_NAMES.get(pillar_key, pillar_key)
    # Each post is drafted via its own independent LLM call with no memory
    # of the rest of the batch -- the Opinion Matrix's "never use the same
    # stance twice in a row" rule can't be enforced by the model alone
    # (it genuinely doesn't know what the previous post picked). Passing
    # last_stance forward here, and reading the model's own "stance" field
    # back out in run_li1_brand_agent's loop, is what makes that rule real
    # instead of an instruction the model has no way to actually follow.
    last_stance_line = f"last_stance_used (do not pick this one again): {last_stance}\n" if last_stance else ""
    user_prompt = (
        f"Content pillar for this post: {pillar_name}\n"
        f"Source material (already sanitized): {source_text}\n"
        f"Kelvin's voice profile notes: {json.dumps(voice_profile, default=str)}\n"
        f"{last_stance_line}\n"
        "Write one LinkedIn post."
    )
    response = client.messages.create(
        model=MODEL,
        # 4000 covers post_copy + hook_variants with headroom -- kept at
        # this size after the 2026-09-15 removal of image_description
        # generation (which is what originally pushed this past 1500)
        # rather than lowering it back, since post_copy alone for a
        # "long" post plus hook_variants can still run close to it.
        max_tokens=4000,
        system=VOICE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    # Claude wraps JSON in a ```json ... ``` fence despite "Respond with
    # ONLY a JSON object" -- same real-world quirk image_indexer.py's
    # _tag_image already strips. Without this, json.loads has *never*
    # actually succeeded on a real response (confirmed 2026-07-23/24: every
    # post in the first live batch hit the fallback below). strict=False
    # additionally tolerates literal unescaped newlines inside string
    # values, which Claude also emits despite valid JSON requiring \n.
    cleaned_text = _JSON_FENCE_RE.sub("", raw_text.strip()).strip()
    try:
        parsed = json.loads(cleaned_text, strict=False)
    except (json.JSONDecodeError, TypeError):
        log.warning("MKT-LI1: non-JSON model response for pillar=%s, using raw text fallback", pillar_key)
        parsed = {
            "pillar": int(pillar_key.split("_")[1]),
            "stance": None,
            "topic": pillar_name,
            "hitl_tier": 3 if pillar_key == "pillar_4" else 2,
            "estimated_length": "medium",
            "post_copy": raw_text,
            "hook_variants": [],
            "format": "text_post",
            "image_brief": None,
            "image_description": None,
            "carousel_slides": None,
            "carousel_pdf_brief": None,
            "notes": "",
        }
    return parsed


def run_li1_brand_agent(
    research_report: dict,
    idea_reservoir: list,
    kelvin_voice_profile: dict,
    build_updates: Optional[list] = None,
    batch_month: Optional[str] = None,
    supabase_client: Optional[Any] = None,
    anthropic_client: Optional[Any] = None,
) -> list[dict]:
    build_updates = build_updates or []
    batch_month = batch_month or _current_batch_month()
    client = get_anthropic_client(anthropic_client)

    pool = _content_pool(research_report, idea_reservoir, build_updates)
    slots = _build_slots(pool)
    schedule = _compute_schedule(batch_month, len(slots))

    posts: list[dict] = []
    last_stance: Optional[str] = None
    try:
        for i, slot in enumerate(slots):
            pillar_key = slot["pillar_key"]
            source_text = sanitize(slot["source"]["text"], context=f"mkt-li1:{pillar_key}")

            draft = _draft_post(client, pillar_key, source_text, kelvin_voice_profile, last_stance=last_stance)
            last_stance = draft.get("stance") or last_stance

            # hitl_tier from model output; pillar_4 always Tier 3 regardless
            hitl_tier = 3 if pillar_key == "pillar_4" else int(draft.get("hitl_tier", 2))

            scheduled_for = schedule[i]
            post = {
                "pillar": draft.get("pillar", int(pillar_key.split("_")[1])),
                "pillar_name": PILLAR_NAMES.get(pillar_key, pillar_key),
                "stance": draft.get("stance"),
                "topic": draft.get("topic", ""),
                "hitl_tier": hitl_tier,
                "estimated_length": draft.get("estimated_length", "medium"),
                "post_copy": draft.get("post_copy", ""),
                "hook_variants": draft.get("hook_variants", []) or [],
                "batch_month": batch_month,
                "scheduled_for": scheduled_for.isoformat(),
                "suggested_post_time": scheduled_for.strftime("%A %-I%p ET"),
                "format": draft.get("format", "text_post"),
                "image_brief": draft.get("image_brief"),
                "image_description": draft.get("image_description"),
                "carousel_slides": draft.get("carousel_slides"),
                "carousel_pdf_brief": draft.get("carousel_pdf_brief"),
                "notes": draft.get("notes", ""),
            }

            compliance = run_compliance_guard(post["post_copy"], platform="linkedin", product_id=MARKETING_PRODUCT_ID)
            if compliance["revised_content"]:
                post["post_copy"] = compliance["revised_content"]

            # Mandatory closing line (2026-09-15 directive) -- before format_post so the
            # appended sentence gets the same one-sentence-per-line treatment as the rest.
            post["post_copy"] = _apply_closing_line(post["post_copy"], is_cta_post=(pillar_key == "pillar_4"))

            if post["format"] == "text_post":
                # credit_line=None/is_original=False here since format_post's job is
                # sentence-per-line body structure, not the image credit line -- the
                # real image (attached below) is always an original Gemini generation
                # with no external credit anyway.
                formatted_copy, format_warnings = format_post(post["post_copy"], credit_line=None, is_original=False)
                post["post_copy"] = formatted_copy
                if format_warnings:
                    post["notes"] = (post["notes"] + " | " if post["notes"] else "") + "post_formatter: " + "; ".join(format_warnings)
                _attach_generated_image(post, anthropic_client=client)

            if compliance["flags"]:
                post["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])
                hitl_tier = 3  # MKT-10 flag always escalates to Tier 3
                post["hitl_tier"] = hitl_tier  # keep the returned/queued row's own field in sync with the escalation

            content_item = {**post, "agent_id": AGENT_ID}
            queued = queue_for_review(content_item, tier=hitl_tier, product_id=MARKETING_PRODUCT_ID, supabase_client=supabase_client)
            post["id"] = queued.get("id")
            posts.append(post)

        write_audit_log(AGENT_ID, "monthly_batch_generated", resource=f"{len(posts)} posts, batch_month={batch_month}", outcome="success")
        emit_event(AGENT_ID, "monthly_batch_generated", {"post_count": len(posts), "batch_month": batch_month})
        return posts
    except Exception as exc:
        write_audit_log(AGENT_ID, "monthly_batch_generated", resource="linkedin_content_queue", outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "monthly_batch_failed", {"error": str(exc)})
        raise


def generate_on_demand_posts(
    count: int,
    pillar_focus: Optional[str] = None,
    supabase_client: Optional[Any] = None,
    anthropic_client: Optional[Any] = None,
) -> list[dict]:
    """
    Manually triggered "fire posts now" entry point -- the CEO dashboard's
    fire button, not the monthly cadence. Unlike generate_builder_post/
    generate_product_launch_post below, this DOES reuse the evergreen
    pillar/Opinion Matrix/stance-rotation machinery (_draft_post,
    CONTENT_MIX_RATIO, PILLAR_NAMES), since the whole point is "give me N
    posts in the usual pillar voice" -- it just has no curated
    research_report/idea_reservoir pool to draw slots from (that's Kelvin's
    own monthly input), so each slot's source_text comes from
    PILLAR_TOPIC_SEEDS instead of a specific angle.

    pillar_focus=None or "balanced" apportions `count` across
    CONTENT_MIX_RATIO exactly like the evergreen monthly batch (_build_slots).
    A specific pillar_key (e.g. "pillar_2") routes every post in this fire
    into that one pillar instead -- pillar_4 is still always Tier 3
    regardless, same rule as the monthly batch.

    Scheduling uses _compute_ondemand_schedule (starts from tomorrow's next
    POST_WEEKDAYS slot) rather than _compute_schedule's batch_month start,
    so an on-demand fire never collides with slots the monthly batch already
    claimed for the current month. Each post's own batch_month is stamped
    from its own scheduled date, and every row is tagged source="on_demand"
    so the dashboard/queue can tell on-demand fires apart from the monthly
    batch (db/migrations/017_linkedin_queue_source_column.sql).
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    if pillar_focus not in (None, "balanced") and pillar_focus not in CONTENT_MIX_RATIO:
        raise ValueError(f"pillar_focus must be 'balanced', one of {list(CONTENT_MIX_RATIO)}, or None")

    client = get_anthropic_client(anthropic_client)

    if pillar_focus and pillar_focus != "balanced":
        pillar_sequence = [pillar_focus] * count
    else:
        quota = apportion(CONTENT_MIX_RATIO, count)
        pillar_sequence = [key for key in CONTENT_MIX_RATIO for _ in range(quota[key])]

    schedule = _compute_ondemand_schedule(len(pillar_sequence))

    posts: list[dict] = []
    last_stance: Optional[str] = None
    try:
        for i, pillar_key in enumerate(pillar_sequence):
            source_text = PILLAR_TOPIC_SEEDS[pillar_key]

            draft = _draft_post(client, pillar_key, source_text, {}, last_stance=last_stance)
            last_stance = draft.get("stance") or last_stance

            hitl_tier = 3 if pillar_key == "pillar_4" else int(draft.get("hitl_tier", 2))

            scheduled_for = schedule[i]
            post = {
                "pillar": draft.get("pillar", int(pillar_key.split("_")[1])),
                "pillar_name": PILLAR_NAMES.get(pillar_key, pillar_key),
                "stance": draft.get("stance"),
                "topic": draft.get("topic", ""),
                "hitl_tier": hitl_tier,
                "estimated_length": draft.get("estimated_length", "medium"),
                "post_copy": draft.get("post_copy", ""),
                "hook_variants": draft.get("hook_variants", []) or [],
                "batch_month": scheduled_for.strftime("%Y-%m"),
                "scheduled_for": scheduled_for.isoformat(),
                "suggested_post_time": scheduled_for.strftime("%A %-I%p ET"),
                "format": draft.get("format", "text_post"),
                "image_brief": draft.get("image_brief"),
                "image_description": draft.get("image_description"),
                "carousel_slides": draft.get("carousel_slides"),
                "carousel_pdf_brief": draft.get("carousel_pdf_brief"),
                "notes": draft.get("notes", ""),
                "source": "on_demand",
            }

            compliance = run_compliance_guard(post["post_copy"], platform="linkedin", product_id=MARKETING_PRODUCT_ID)
            if compliance["revised_content"]:
                post["post_copy"] = compliance["revised_content"]

            # Mandatory closing line (2026-09-15 directive) -- before format_post so the
            # appended sentence gets the same one-sentence-per-line treatment as the rest.
            post["post_copy"] = _apply_closing_line(post["post_copy"], is_cta_post=(pillar_key == "pillar_4"))

            if post["format"] == "text_post":
                # credit_line=None/is_original=False here since format_post's job is
                # sentence-per-line body structure, not the image credit line -- the
                # real image (attached below) is always an original Gemini generation
                # with no external credit anyway.
                formatted_copy, format_warnings = format_post(post["post_copy"], credit_line=None, is_original=False)
                post["post_copy"] = formatted_copy
                if format_warnings:
                    post["notes"] = (post["notes"] + " | " if post["notes"] else "") + "post_formatter: " + "; ".join(format_warnings)
                _attach_generated_image(post, anthropic_client=client)

            if compliance["flags"]:
                post["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])
                hitl_tier = 3  # MKT-10 flag always escalates to Tier 3, same rule as the evergreen batch
                post["hitl_tier"] = hitl_tier  # keep the returned/queued row's own field in sync with the escalation

            content_item = {**post, "agent_id": AGENT_ID}
            queued = queue_for_review(content_item, tier=hitl_tier, product_id=MARKETING_PRODUCT_ID, supabase_client=supabase_client)
            post["id"] = queued.get("id")
            posts.append(post)

        write_audit_log(
            AGENT_ID, "on_demand_batch_generated",
            resource=f"{len(posts)} posts, pillar_focus={pillar_focus or 'balanced'}", outcome="success",
        )
        emit_event(AGENT_ID, "on_demand_batch_generated", {"post_count": len(posts), "pillar_focus": pillar_focus or "balanced"})
        return posts
    except Exception as exc:
        write_audit_log(AGENT_ID, "on_demand_batch_generated", resource="linkedin_content_queue", outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "on_demand_batch_failed", {"error": str(exc)})
        raise


def generate_builder_post(
    session_notes: str,
    anthropic_client: Optional[Any] = None,
    supabase_client: Optional[Any] = None,
) -> dict:
    """
    Manually triggered entry point for a "Builder Post" — built entirely
    from Kelvin's own raw session notes, never from the evergreen batch
    pool (no pillar, no Opinion Matrix stance, no scheduled_for; this
    doesn't touch POSTS_PER_BATCH/CONTENT_MIX_RATIO/_compute_schedule at
    all). Deliberately does not route through the Opinion Matrix — that
    matrix's own instruction ("bend the ANGLE to fit the stance") would
    directly violate this post type's source-of-truth requirement, and
    Kelvin's task spec for this post type never asked for a stance.
    Always Tier 2 unless MKT-10 flags something, matching the existing
    "purely educational/personal post with no CTA" Tier 2 criterion —
    a Builder Post is never a product mention by design.
    """
    client = get_anthropic_client(anthropic_client)
    sanitized_notes = sanitize(session_notes, context="mkt-li1:builder_post")
    user_prompt = f"Kelvin's raw session notes (already sanitized):\n{sanitized_notes}\n\nWrite one Builder Post."

    response = client.messages.create(
        model=MODEL, max_tokens=2000, system=BUILDER_POST_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    cleaned_text = _JSON_FENCE_RE.sub("", raw_text.strip()).strip()
    try:
        parsed = json.loads(cleaned_text, strict=False)
    except (json.JSONDecodeError, TypeError):
        log.warning("MKT-LI1: non-JSON model response for generate_builder_post, using raw text fallback")
        parsed = {"post_copy": raw_text, "hook_variants": [], "notes": ""}

    post_copy = parsed.get("post_copy", "")
    compliance = run_compliance_guard(post_copy, platform="linkedin", product_id=MARKETING_PRODUCT_ID)
    if compliance["revised_content"]:
        post_copy = compliance["revised_content"]
    post_copy = _apply_closing_line(post_copy, is_cta_post=False)

    hitl_tier = 2
    post = {
        "post_copy": post_copy,
        "hook_variants": parsed.get("hook_variants", []) or [],
        "format": "text_post",
        "topic": "Builder Post",
        "notes": parsed.get("notes", ""),
    }
    if compliance["flags"]:
        post["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])
        hitl_tier = 3  # MKT-10 flag always escalates to Tier 3, same rule as the evergreen batch

    _attach_generated_image(post, anthropic_client=client)

    try:
        content_item = {**post, "agent_id": AGENT_ID}
        queued = queue_for_review(content_item, tier=hitl_tier, product_id=MARKETING_PRODUCT_ID, supabase_client=supabase_client)
        post["id"] = queued.get("id")
        post["hitl_tier"] = hitl_tier
        write_audit_log(AGENT_ID, "builder_post_generated", resource=str(post.get("id") or "unknown"), outcome="success")
        emit_event(AGENT_ID, "builder_post_generated", {"post_id": post.get("id")})
        return post
    except Exception as exc:
        write_audit_log(AGENT_ID, "builder_post_generated", resource="linkedin_content_queue", outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "builder_post_failed", {"error": str(exc)})
        raise


def generate_product_launch_post(
    product_name: str,
    problem: str,
    audience: str,
    outcome: str,
    url: str,
    anthropic_client: Optional[Any] = None,
    supabase_client: Optional[Any] = None,
) -> dict:
    """
    Manually triggered entry point for a "Product Launch Post" — fired
    when a new MSE product ships. Not part of the evergreen batch pool
    (no pillar, no Opinion Matrix stance, no scheduled_for). Always Tier
    3, same rule that makes every Pillar 4 post Tier 3 in the evergreen
    batch: a direct product mention + CTA + URL always needs Kelvin's
    own approval.
    """
    client = get_anthropic_client(anthropic_client)
    safe = sanitize(
        json.dumps({"product_name": product_name, "problem": problem, "audience": audience, "outcome": outcome, "url": url}),
        context="mkt-li1:product_launch_post",
    )
    user_prompt = f"Product launch details (already sanitized):\n{safe}\n\nWrite one Product Launch Post."

    response = client.messages.create(
        model=MODEL, max_tokens=1500, system=PRODUCT_LAUNCH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    cleaned_text = _JSON_FENCE_RE.sub("", raw_text.strip()).strip()
    try:
        parsed = json.loads(cleaned_text, strict=False)
    except (json.JSONDecodeError, TypeError):
        log.warning("MKT-LI1: non-JSON model response for generate_product_launch_post, using raw text fallback")
        parsed = {"post_copy": f"{outcome}\n\n{url}", "hook_variants": [], "notes": ""}

    post_copy = parsed.get("post_copy", "")
    compliance = run_compliance_guard(post_copy, platform="linkedin", product_id=MARKETING_PRODUCT_ID)
    if compliance["revised_content"]:
        post_copy = compliance["revised_content"]

    # 2026-09-15 directive: THE DOOR no longer puts the URL in the post body
    # (LinkedIn's own algorithm deprioritizes outbound links in-body) --
    # post_copy always closes with "Link in the comments." instead
    # (_apply_closing_line also strips it if the model still wrote the URL
    # in despite the prompt instruction not to). The real url is carried in
    # `notes` so Kelvin has it in front of him to paste as the first comment
    # at publish time -- it was never optional information, just moved out
    # of the post body.
    post_copy = _apply_closing_line(post_copy, is_cta_post=True)
    if url in post_copy:
        post_copy = post_copy.replace(url, "").rstrip()
        post_copy = _apply_closing_line(post_copy, is_cta_post=True)

    notes = parsed.get("notes", "")
    notes = (notes + " | " if notes else "") + f"Comment link (paste at publish time): {url}"

    post = {
        "post_copy": post_copy,
        "hook_variants": parsed.get("hook_variants", []) or [],
        "format": "text_post",
        "topic": f"Product Launch: {product_name}",
        "notes": notes,
    }
    if compliance["flags"]:
        post["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])

    _attach_generated_image(post, anthropic_client=client)

    try:
        content_item = {**post, "agent_id": AGENT_ID}
        queued = queue_for_review(content_item, tier=3, product_id=MARKETING_PRODUCT_ID, supabase_client=supabase_client)
        post["id"] = queued.get("id")
        post["hitl_tier"] = 3
        write_audit_log(AGENT_ID, "product_launch_post_generated", resource=str(post.get("id") or "unknown"), outcome="success")
        emit_event(AGENT_ID, "product_launch_post_generated", {"post_id": post.get("id"), "product_name": product_name})
        return post
    except Exception as exc:
        write_audit_log(AGENT_ID, "product_launch_post_generated", resource="linkedin_content_queue", outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "product_launch_post_failed", {"error": str(exc)})
        raise


def _get_product_selling_stage(product_id: str, supabase_client: Optional[Any] = None) -> str:
    """
    Marketing stage-gate update (session 2026-09-15). mse_icp_configs
    lives in kdavis-microsaas-engine's own migrations, not this repo's —
    both repos share the same Supabase project, so this is a cross-repo
    table READ through this repo's own Supabase client (_shared.py's
    _get_supabase_client, same SUPABASE_URL/SUPABASE_KEY every internal
    dashboard in this platform already uses), not a dependency on that
    repo's code.

    Fails closed to 'building' — skip generating content — on a missing
    config row (mse_icp_configs.selling_stage itself defaults to
    'building' in that table's own migration, so this mirrors the same
    fail-closed default rather than silently disagreeing with it) or on
    any lookup error (network, RLS, the table not existing in a given
    environment). Generating CTA copy for a product that isn't supposed
    to be visible yet is a worse outcome than skipping one post — a
    human can always fire generate_product_content again once the
    product's real stage is confirmed.
    """
    client = supabase_client if supabase_client is not None else _get_supabase_client(None)
    try:
        result = (
            client.table("mse_icp_configs")
            .select("selling_stage")
            .eq("product_id", product_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        log.warning(
            "MKT-LI1: selling_stage lookup failed for product_id=%s, failing closed to 'building': %s",
            product_id, exc,
        )
        return "building"

    data = getattr(result, "data", None)
    if not data:
        return "building"
    return data.get("selling_stage") or "building"


def generate_product_content(
    product_id: str,
    product_name: str,
    problem: str,
    audience: str,
    outcome: str,
    url: str,
    anthropic_client: Optional[Any] = None,
    supabase_client: Optional[Any] = None,
) -> Optional[dict]:
    """
    Stage-aware entry point for product content (marketing stage-gate
    update, session 2026-09-15) — checks mse_icp_configs.selling_stage
    for product_id and routes accordingly:

      'active'   -> delegates straight to generate_product_launch_post
                    (unchanged, still directly callable on its own for a
                    known-active product) — full CTA, URL, Tier 3.
      'warming'  -> drafts a mention-only post (MENTION_ONLY_SYSTEM_PROMPT)
                    that references the product in context, with no CTA
                    and no URL — code-enforced (see the url-stripping
                    guard below), not just prompt instruction. Still
                    Tier 3: this file's own HITL TIERS rule already says
                    "any product mention" is Tier 3, and a mention
                    without a CTA doesn't carve out an exception to that.
      'building' -> returns None. No LLM call, nothing queued, nothing
                    generated — matches this file's established
                    "never fabricate" principle (_build_slots never
                    invents source material either) applied to a
                    product that shouldn't be visible in generated
                    content at all yet.

    Does not touch Pillar 5 (Enterprise Consulting & AI Platform
    Architecture) or any other pillar of the evergreen batch pool — see
    this module's own docstring for why Pillar 5 has nothing
    product-selling_stage-shaped to gate in the first place.
    """
    stage = _get_product_selling_stage(product_id, supabase_client=supabase_client)

    if stage == "building":
        write_audit_log(
            AGENT_ID, "product_content_skipped", resource=product_id,
            outcome=f"skipped: selling_stage={stage}",
        )
        emit_event(AGENT_ID, "product_content_skipped", {"product_id": product_id, "selling_stage": stage})
        return None

    if stage == "active":
        return generate_product_launch_post(
            product_name=product_name, problem=problem, audience=audience, outcome=outcome, url=url,
            anthropic_client=anthropic_client, supabase_client=supabase_client,
        )

    # 'warming' (and any future/unrecognized stage value) -- mention-only,
    # no CTA, no URL. Deliberately fails closed toward the more
    # conservative treatment rather than defaulting an unknown stage to
    # 'active'.
    client = get_anthropic_client(anthropic_client)
    safe = sanitize(
        json.dumps({"product_name": product_name, "problem": problem, "audience": audience, "outcome": outcome}),
        context="mkt-li1:product_mention_post",
    )
    user_prompt = f"Product context (already sanitized):\n{safe}\n\nWrite one Product Mention Post."

    response = client.messages.create(
        model=MODEL, max_tokens=1500, system=MENTION_ONLY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw_text = response.content[0].text if hasattr(response, "content") else str(response)
    cleaned_text = _JSON_FENCE_RE.sub("", raw_text.strip()).strip()
    try:
        parsed = json.loads(cleaned_text, strict=False)
    except (json.JSONDecodeError, TypeError):
        log.warning("MKT-LI1: non-JSON model response for generate_product_content (warming), using raw text fallback")
        parsed = {"post_copy": raw_text, "hook_variants": [], "notes": ""}

    post_copy = parsed.get("post_copy", "")
    compliance = run_compliance_guard(post_copy, platform="linkedin", product_id=MARKETING_PRODUCT_ID)
    if compliance["revised_content"]:
        post_copy = compliance["revised_content"]

    # Defense in depth: the prompt instructs no URL/CTA, but a warming-
    # stage post must never carry this product's own URL regardless of
    # what the model actually did — code-enforced, not just requested.
    if url and url in post_copy:
        post_copy = post_copy.replace(url, "").rstrip()

    # Mandatory closing line (2026-09-15 directive) -- a mention-only post is
    # never about the warming-stage product's own CTA/link (that's the "no
    # URL" rule above, untouched), but it still gets the same personal-brand
    # closing every non-Pillar-4 post gets, pointing at Kelvin, not the product.
    post_copy = _apply_closing_line(post_copy, is_cta_post=False)

    post = {
        "post_copy": post_copy,
        "hook_variants": parsed.get("hook_variants", []) or [],
        "format": "text_post",
        "topic": f"Product Mention: {product_name}",
        "notes": parsed.get("notes", ""),
        "selling_stage": stage,
    }
    if compliance["flags"]:
        post["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])

    _attach_generated_image(post, anthropic_client=client)

    try:
        content_item = {**post, "agent_id": AGENT_ID}
        queued = queue_for_review(content_item, tier=3, product_id=MARKETING_PRODUCT_ID, supabase_client=supabase_client)
        post["id"] = queued.get("id")
        post["hitl_tier"] = 3
        write_audit_log(AGENT_ID, "product_mention_post_generated", resource=str(post.get("id") or "unknown"), outcome="success")
        emit_event(AGENT_ID, "product_mention_post_generated", {"post_id": post.get("id"), "product_name": product_name})
        return post
    except Exception as exc:
        write_audit_log(AGENT_ID, "product_mention_post_generated", resource="linkedin_content_queue", outcome=f"failure: {exc}")
        emit_event(AGENT_ID, "product_mention_post_failed", {"error": str(exc)})
        raise
