"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

MKT-LI1 — LinkedIn Personal Brand Agent v2.3.

Builds Kelvin as the authority — his personal brand is the warm
distribution channel for every product launch. Distinct from product
marketing (MKT-V1). Full spec: knowledge/Marketing/Marketing-Engine-Agent-Specs.md.
System prompt: knowledge/Marketing/MKT-LI1-System-Prompt-v2.md.

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
  Pillar 1: Cloud and AI Execution (40%) — primary authority engine
  Pillar 2: Builder's Journey (30%) — human layer, build-in-public
  Pillar 3: Philosophy, Faith, Gardening (20%) — differentiation layer
  Pillar 4: Product, Business, CTA (10%) — used sparingly

HITL tiers: Tier 2 (wife) = Pillars 1-3 with no product mention.
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

Image asset vault (added 2026-07-22): for text_post format only (carousel
posts use carousel_pdf_brief instead, untouched by this), selects an
existing curated image from assets_library/ via asset_selector.select_asset()
using this post's topic, and OVERWRITES image_brief with that selection's
payload (image_id/image_path/credit_line/is_original/selected_because) —
the old Canva concept/style/brand_colors shape is not used while the
Canva Autofill integration is parked (per Kelvin's 2026-07-22 directive:
Canva is for original-idea generation only, not in use yet). The selected
image is attached HERE, before HITL queuing, specifically so the human
reviewer sees and can reject the image choice along with the copy — never
re-selected later at publish time, which would let a different image go
live than the one actually reviewed. post_copy is also run through
post_formatter.format_post() here, using this same selection's
credit_line/is_original, so the queued row is the exact text that will be
posted — publish-time uses it verbatim, no reformatting.

Gemini image generation (added 2026-07-23): each drafted post now also
carries image_description — a fully-composed, single-diagram Gemini
prompt (see VOICE_SYSTEM_PROMPT's OUTPUT FORMAT section) for posts whose
topic calls for an original technical diagram rather than a vault photo.
MKT-LI1 itself never calls Gemini — at draft time, select_asset() is
still tried first against the existing vault (a my_originals/ match from
earlier in this same batch run always wins), and image_description just
rides along on the queued row unused if a match was found. When no match
exists yet, generation_available=true on image_brief signals that
assets_library/gemini_image_gen.py can still produce one — it runs after
this agent, in monthly_batch.sh's Step 1.5, and re-attaches the generated
image directly to this exact queue row by id (never by fuzzy topic
re-matching — a monthly technical diagram is bespoke to its own post, not
a shared reusable asset like the vault's other photos).
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from agents.marketing._shared import (
    MARKETING_PRODUCT_ID,
    apportion,
    emit_event,
    get_anthropic_client,
    sanitize,
    write_audit_log,
)
from agents.marketing.mkt_09_hitl_queue_manager import queue_for_review
from agents.marketing.mkt_10_compliance_guard import run_compliance_guard
from assets_library.asset_selector import select_asset
from assets_library.post_formatter import format_post

log = logging.getLogger(__name__)

AGENT_ID = "mkt-li1"
MODEL = "claude-sonnet-4-6"

CONTENT_MIX_RATIO = {"pillar_1": 0.4, "pillar_2": 0.3, "pillar_3": 0.2, "pillar_4": 0.1}
PILLAR_NAMES = {
    "pillar_1": "Cloud and AI Execution",
    "pillar_2": "The Builder's Journey",
    "pillar_3": "Philosophy, Faith, and Gardening",
    "pillar_4": "Product, Business, and CTA",
}
POSTS_PER_BATCH = 12
POST_WEEKDAYS = [1, 2, 3]  # Tue, Wed, Thu (Monday=0) — same cadence feel as the old weekly rotation
POST_HOUR_ET = 9
_ET = ZoneInfo("America/New_York")

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

## CTA ROTATION

For high-value technical posts: "Comment [KEYWORD] if you want the full breakdown" —
captures intent without a hard sell.
For product-adjacent posts: one soft mention of what's being built as the natural
resolution of the problem discussed.
For personal/philosophy posts: no CTA. Let it land.

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
  purely educational or personal posts with no CTA.
Tier 3 (Kelvin must approve): any product mention or CTA; pricing/revenue/MRR references;
  responses to named competitors or market events; all Pillar 4; any MKT-10 flagged post.

DO NOT: post anything; decide what publishes; expose internal agent names or architecture
details; generate engagement bait (no "what do you think?", no "share if you agree");
summarize news; list features; write "Here are 3 reasons why X matters."

Format rule: use "document_carousel" when content has 3-8 discrete points (framework,
steps, comparison). Otherwise use "text_post". Populate exactly one pair; other is null.

## OUTPUT FORMAT

image_description (text_post only, null for document_carousel): a fully-composed prompt
for a Gemini image-generation call that becomes this post's custom technical diagram.
One Gemini API call renders exactly one image from this string verbatim — it must
describe ONE standalone diagram only, never a grid, collage, or multi-panel composite
(that is what Gemini defaults to when a prompt implies more than one concept at once).

image_description must describe the diagram spatially and specifically:
- Name every node, box, and label
- Describe the layout (left to right, top to bottom, grid, flow)
- Specify arrow directions and what connects to what
- Include real tool/service names and logos where relevant to the post topic

Always start image_description with:
"Single standalone diagram. One concept only. No panels, no grids, no collages.
Full bleed 1080x1080px white background."

Always end image_description with:
"Navy #0A0F1E primary elements, blue #5a96ff highlights, amber #F5A623 callouts and
important labels. Clean sans-serif font. Real cloud provider logos where relevant.
Small text \"Kelvin Davis\" bottom right corner. Professional LinkedIn infographic
style similar to ByteByteGo. White background. No dark backgrounds."

Never use any name other than "Kelvin Davis" anywhere in image_description or post_copy.

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
4. CLOSE — Never a product pitch. Either end with nothing further, or exactly one soft, genuine question
   to the reader (e.g. "Anyone else hit this building solo?"). No CTA driving to a product, a link, or a
   comment-this-keyword prompt.

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
4. THE DOOR — a direct call to action that includes the URL given below verbatim. No apology for the
   pitch, no soft plug, no "check it out if you're curious" hedging.

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
    pool: dict[str, list[dict]] = {"pillar_1": [], "pillar_2": [], "pillar_3": [], "pillar_4": []}

    for angle in content_angles:
        text = angle.get("angle") if isinstance(angle, dict) else str(angle)
        pool["pillar_1"].append({"text": text, "source": "research_report.content_angles"})

    for idea in idea_reservoir or []:
        raw_type = idea.get("type") if isinstance(idea, dict) else None
        text = idea.get("text") if isinstance(idea, dict) else str(idea)
        # Support both old bucket names and new pillar keys
        pillar_map = {"educational": "pillar_1", "journey": "pillar_2",
                      "repurposed": "pillar_3", "product": "pillar_4"}
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


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


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
        # 1500 was too small once image_description's full spatial-diagram
        # prompt requirement was added 2026-07-23 -- confirmed by a real
        # call getting cut off mid-generation (found running the first
        # live batch). 4000 covers post_copy + hook_variants +
        # image_description with headroom.
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
            "image_brief": {"concept": source_text, "style": "Decoded brand", "brand_colors": ["#5a96ff", "#f5a623"]},
            "image_description": None,
            "carousel_slides": None,
            "carousel_pdf_brief": None,
            "notes": "",
        }
    return parsed


def _select_image_for_post(topic: str, image_description: Optional[str] = None) -> Optional[dict]:
    """Returns asset_selector's payload, or None if no curated image matches
    this post's topic AND no Gemini generation is possible for it either (a
    text_post is still valid with neither — MKT-LI1 never fabricates a
    match, same principle as never fabricating a milestone in _build_slots
    above). image_description is passed through only so select_asset can
    set generation_available on its output; it plays no role in matching."""
    result = select_asset(topic, image_description=image_description)
    return result if result["image_id"] or result["generation_available"] else None


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

            if post["format"] == "text_post":
                asset = _select_image_for_post(post["topic"], image_description=post["image_description"])
                post["image_brief"] = asset
                formatted_copy, format_warnings = format_post(
                    post["post_copy"],
                    credit_line=asset["credit_line"] if asset else None,
                    is_original=asset["is_original"] if asset else False,
                )
                post["post_copy"] = formatted_copy
                if format_warnings:
                    post["notes"] = (post["notes"] + " | " if post["notes"] else "") + "post_formatter: " + "; ".join(format_warnings)

            content_item = {**post, "agent_id": AGENT_ID}
            if compliance["flags"]:
                content_item["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])
                hitl_tier = 3  # MKT-10 flag always escalates to Tier 3

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

    # THE DOOR (structure step 4) is a hard requirement, not a suggestion
    # — if the model paraphrased or dropped the literal URL, append it
    # rather than silently ship a launch post with no way to reach the product.
    if url not in post_copy:
        post_copy = post_copy.rstrip() + f"\n\n{url}"

    post = {
        "post_copy": post_copy,
        "hook_variants": parsed.get("hook_variants", []) or [],
        "format": "text_post",
        "topic": f"Product Launch: {product_name}",
        "notes": parsed.get("notes", ""),
    }
    if compliance["flags"]:
        post["hitl_notes"] = "MKT-10: " + "; ".join(compliance["flags"])

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
