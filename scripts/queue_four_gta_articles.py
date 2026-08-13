"""
One-off script to insert 4 real, editorially-sourced news/analysis articles
into decoded-six's live `articles` table with status='pending_review' (the
real HITL gate per migration 007_articles_hitl_trigger.sql). Not imported —
run directly against decoded-six's own Supabase project.

Every factual claim below is sourced to a real, verifiable source (CNBC,
Rockstar Newswire, PlayStation Blog, Netflix Tudum) found via live web
search this session -- nothing about Take-Two's CEO, Rockstar, Sony, or
Netflix is invented. Anything not officially confirmed is labeled
speculation inline, per docs/VOICE.md's Critical Accuracy Rules.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

DECODED_SIX_ROOT = "/mnt/c/Users/Kelvin/projects/decoded-six"
load_dotenv(os.path.join(DECODED_SIX_ROOT, ".env.local"))

from supabase import create_client

SUPABASE_URL = os.environ["NEXT_PUBLIC_SUPABASE_URL"]
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ["SUPABASE_SERVICE_KEY"]
BASE_URL = "https://thedecodedsix.com"
PRODUCT_ID = "gta-hub"  # matches real live rows, not CLAUDE.md's stale "decodedsix"


def schema_article(title: str, slug: str, excerpt: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": title, "description": excerpt,
        "url": f"{BASE_URL}/news/{slug}",
        "datePublished": now, "dateModified": now,
        "author": {"@type": "Organization", "name": "DecodedSix Editorial Team"},
        "publisher": {"@type": "Organization", "name": "Decoded Six", "url": BASE_URL},
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"{BASE_URL}/news/{slug}"},
    }


def schema_faq(faq_pairs: list[dict]) -> dict:
    return {
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": p["question"],
             "acceptedAnswer": {"@type": "Answer", "text": p["answer"]}}
            for p in faq_pairs
        ],
    }


def schema_breadcrumb(title: str, slug: str) -> dict:
    return {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": BASE_URL},
            {"@type": "ListItem", "position": 2, "name": "News", "item": f"{BASE_URL}/news"},
            {"@type": "ListItem", "position": 3, "name": title, "item": f"{BASE_URL}/news/{slug}"},
        ],
    }


ARTICLES = [
    dict(
        slug="gta-online-not-coming-2026-cnbc-silence",
        title="GTA Online Isn't Coming in 2026 — Here's Why the Silence Is the Signal",
        excerpt="Take-Two's CEO just did a high-profile CNBC interview about GTA 6 and never mentioned GTA Online once. History says that silence means something.",
        article_type="news",
        featured_image_url="/images/tier1/keyart/jason-lucia-01/Jason_and_Lucia_01_landscape.jpg",
        external_citation="https://www.cnbc.com/video/2026/08/10/take-two-ceo-strauss-zelnick-on-gta-6-i-believe-we-will-exceed-expectations.html",
        internal_links=["gta-6-release-date-november-19-2026-pricing", "gta-6-online-economy-making-money"],
        content="""Take-Two CEO Strauss Zelnick sat down with CNBC's *Squawk Box* on August 10 for one of the highest-visibility interviews of the entire GTA 6 launch cycle. He talked about preorder demand, why the Ultimate Edition is outselling the standard $79.79 version at $99.99, and why Rockstar isn't cutting the price for the holidays. He did not say the words "GTA Online" once.

That's not a leak. That's not a rumor. That's what happened in a nationally broadcast interview with the person who runs the company, three months out from launch, with every incentive to hype every piece of the game he could.

## What's Actually Confirmed

Rockstar has confirmed GTA 6 launches November 19, 2026 as a single-player-only experience. No online mode ships day one. That's stated fact, not speculation — Rockstar has said it directly.

What Rockstar and Take-Two have not done is give GTA Online a release window. Not in the CNBC interview. Not anywhere else recently. One report has gone as far as saying Take-Two "has no plans to discuss GTA Online anytime soon" despite the game being months away.

## History Says This Isn't New — But the Gap Matters

GTA V released September 17, 2013. GTA Online launched October 1, 2013 — 14 days later. Rockstar has said publicly that the gap was intentional, so GTA Online would be understood as its own thing rather than a mode bolted onto the single-player game.

If GTA 6 followed that exact playbook, GTA Online would already have a firm date locked to launch week. It doesn't. That's the difference between 2013 and now: back then, the wait was measured in days and Rockstar was already talking about it. This time, three months out, the wait is undefined and the company is staying quiet.

## What Analysts Are Saying — Labeled Clearly as Speculation

Wall Street analysts covering Take-Two have floated windows ranging from a few weeks after single-player launch to as late as early 2027. None of this is confirmed by Rockstar or Take-Two. Treat every specific month you see attached to "GTA Online" between now and an actual Rockstar announcement as a guess, not a leak with inside knowledge.

## What This Means If You're Planning Around It

If your plan for launch week was jumping into GTA Online with everyone else the way GTA V players did in 2013, that plan needs to change. Budget for single-player only at launch, and treat any GTA Online date you see online — including this article's own speculation section above — as unconfirmed until Rockstar publishes something official.

## Bottom Line

Zelnick had a national TV interview and every reason to build hype for every part of GTA 6. He built hype for preorders and pricing and said nothing about GTA Online. Combined with Take-Two's broader silence and a launch gap that already looks longer than 2013's two weeks, that's the actual signal here — not a leak, not a rumor, just what wasn't said.""",
        faq=[
            {"question": "Is GTA Online coming with GTA 6 at launch?",
             "answer": "No. Rockstar has confirmed GTA 6 launches November 19, 2026 as a single-player-only experience. No online multiplayer mode is included on day one."},
            {"question": "When did GTA Online launch after GTA V?",
             "answer": "GTA V released September 17, 2013, and GTA Online launched October 1, 2013 — 14 days later. Rockstar has said the gap was intentional so GTA Online would be seen as its own separate product."},
            {"question": "Has Take-Two given a release date for GTA 6's online mode?",
             "answer": "No official date has been given. In an August 10, 2026 CNBC interview, Take-Two CEO Strauss Zelnick discussed GTA 6 preorders and pricing at length but did not address GTA Online's release timing at all."},
            {"question": "When do analysts think GTA Online will launch for GTA 6?",
             "answer": "Estimates from Wall Street analysts covering Take-Two range from a few weeks after the November 19, 2026 single-player launch to as late as early 2027. None of these dates are confirmed by Rockstar or Take-Two — treat them as speculation."},
        ],
    ),
    dict(
        slug="gta-6-physical-edition-no-disc-code-in-box",
        title="GTA 6 Physical Edition Confirmed: No Disc, Just a Code in the Box",
        excerpt="Rockstar confirmed the GTA 6 physical edition doesn't include a disc — buyers get a box with a download code inside instead.",
        article_type="news",
        featured_image_url="/images/tier1/keyart/official-cover-art/Official_Cover_Art_landscape.jpg",
        external_citation="https://www.rockstargames.com/newswire",
        internal_links=["gta-6-ultimate-edition-vs-standard-edition", "gta-6-release-date-november-19-2026-pricing"],
        content="""Rockstar confirmed on June 24 that the GTA 6 physical edition will not contain a disc. That's official, not a leak. If you preordered a boxed copy expecting a disc, here's what's actually in the box.

## What's Confirmed

The physical edition ships as a box containing a slip of paper with a download code. Redeeming that code through your platform's digital storefront triggers the exact same download digital buyers get. Pre-load still begins November 12 ahead of the November 19 launch, whether you bought physical or digital.

The practical effect: once you redeem the code, the box itself holds no playable game. No disc to hand off, no trade-in, no lending a friend your copy the way a physical disc would let you. The code locks to your account the moment you use it.

## Why This Matters If You Weren't Watching Closely

A lot of buyers assumed "physical edition" meant a disc, the way it always has for previous GTA releases. It doesn't this time. If you bought physical specifically for the resale value or so you could lend it out later, that plan doesn't work with a code-in-box release — there's nothing left to hand over once it's redeemed.

## The Disc Rumor — Labeled Speculation

One Polish outlet, ppe.pl, has reported that an actual disc-based edition could arrive in December 2026, roughly a month after launch. Take-Two has denied planning a separate physical release after November 19, and neither Rockstar nor Take-Two has announced a disc SKU anywhere official. Treat this as an unconfirmed rumor from an outlet with a mixed track record, not a plan you should wait on.

## Bottom Line

If you want a disc for GTA 6, buying the "physical edition" as currently sold won't get you one — it gets you a code in a box, same download as everyone else. Confirmed by Rockstar directly on June 24. Everything about a future disc version beyond that is rumor.""",
        faq=[
            {"question": "Does the GTA 6 physical edition come with a disc?",
             "answer": "No. Rockstar confirmed on June 24, 2026 that the GTA 6 physical edition contains a download code, not a disc. Redeeming the code triggers the same digital download that buying the game digitally would."},
            {"question": "Can you resell or trade in a physical GTA 6 copy?",
             "answer": "Once the download code from a physical GTA 6 box is redeemed, it locks to that account. There is no disc to trade in, resell, or lend afterward, unlike a traditional disc-based physical copy."},
            {"question": "Is a disc version of GTA 6 coming later?",
             "answer": "This is unconfirmed. One outlet, ppe.pl, has reported a possible disc edition arriving around December 2026, but Take-Two has denied plans for a separate physical release after the November 19, 2026 launch, and neither Rockstar nor Take-Two has officially announced a disc SKU."},
        ],
    ),
    dict(
        slug="sony-disc-warning-2028-gta-6-physical-copy",
        title="Sony Just Put an Expiration Date on Physical Games — GTA 6 Already Showed You Where This Is Going",
        excerpt="Sony is printing warning labels on PS5 boxes about the end of physical game discs in 2028. GTA 6's own code-in-a-box release already got there first.",
        article_type="news",  # live DB constraint only accepts news/evergreen/conversion, not 'analysis' (migration 001 file is stale)
        featured_image_url="/images/tier1/keyart/jason-lucia-02/Jason_and_Lucia_02_landscape.jpg",
        external_citation="https://blog.playstation.com/2026/07/01/physical-disc-production-ending-in-january-2028-for-new-games-releasing-on-playstation-consoles/",
        internal_links=["gta-6-physical-edition-no-disc-code-in-box"],
        content="""Sony announced on the official PlayStation Blog on July 1 that physical disc production for new PlayStation games ends in January 2028. Now every disc-based PS5 console being sold carries a printed warning about it. GTA 6 players already saw a preview of this shift back in June.

## What Sony Actually Announced

Starting January 2028, newly released PlayStation games will be available for purchase only in digital format through the PlayStation Store and at retailers — no new discs. Sony has started placing a sticker directly on PS5 console boxes that reads: "IMPORTANT NOTICE: From Jan. 2028, newly released games on PlayStation will be available for purchase on PlayStation Store and at retailers in digital format only. Discs for games released before Jan. 2028 can continue to be played on this console."

Sony's stated reasoning: digital already dominates. The company's own Q1 FY2026 earnings data shows roughly 82% of full-game sales across PS4 and PS5 in the quarter ending June 30, 2026 were digital downloads.

## Where GTA 6 Already Fits This Pattern

![GTA 6 key art](/images/tier1/keyart/jason-lucia-02/Jason_and_Lucia_02_landscape.jpg)
*Image credit: Rockstar Games*

Rockstar confirmed in June that GTA 6's own "physical edition" isn't a disc at all — it's a code in a box, redeemed through the same digital storefront a fully digital purchase uses. That's not Sony's 2028 policy in effect early. It's Rockstar's own packaging decision. But it lands in the same direction Sony just made official for the whole platform: the box on the shelf increasingly isn't what's actually running the game.

![GTA 6 key art](/images/tier1/keyart/official-cover-art/Official_Cover_Art_landscape.jpg)
*Image credit: Rockstar Games*

## What This Means Going Forward

If you've been holding onto physical collecting as a reason to buy boxed copies, the runway on that is now dated: January 2028 for new PS5 releases, full stop, per Sony's own announcement. GTA 6 buying a code-in-a-box release in 2026 isn't the cause of that shift — it's an early data point inside a move the entire industry is already making.

## Bottom Line

Sony has now put an actual date on the end of new physical game discs: January 2028. GTA 6's own box-with-a-code release this November didn't wait for that deadline to arrive early. Different companies, same direction.""",
        faq=[
            {"question": "When is Sony ending physical game discs for PlayStation?",
             "answer": "Sony announced on July 1, 2026 that starting in January 2028, newly released PlayStation games will be sold only in digital format. Games released before that date will still be playable on disc-compatible consoles."},
            {"question": "Why is Sony ending physical discs?",
             "answer": "Sony cited its own sales data: approximately 82% of full-game sales across PS4 and PS5 in the quarter ending June 30, 2026 were digital downloads, which it framed as reflecting a general consumer preference for digital media."},
            {"question": "Is GTA 6's lack of a disc related to Sony's announcement?",
             "answer": "Not directly. Rockstar confirmed GTA 6's physical edition ships as a code in a box, not a disc, in June 2026 — a packaging decision made independently of Sony's July 2026 platform-wide disc phase-out announcement, though both moves point in the same direction."},
        ],
    ),
    dict(
        slug="gta-6-netflix-premiere-signals-gaming-push",
        title="GTA 6 Just Got a Netflix Premiere No Game Has Ever Had — Here's What It Signals",
        excerpt="Netflix is premiering GTA 6's extended look six hours before anyone else gets it. For a platform whose game catalog is mostly Boggle and FIFA, that's a real signal.",
        article_type="news",
        featured_image_url="/images/tier1/keyart/jason-lucia-03/Jason_and_Lucia_03_landscape.jpg",
        external_citation="https://www.netflix.com/tudum/articles/grand-theft-auto-6-extended-first-look",
        internal_links=["gta-6-extended-look-netflix-august-27"],
        content="""On August 27, Netflix premieres an extended look at GTA 6 six hours before it hits YouTube or the official GTA 6 site. Netflix itself is calling it a "first-of-its-kind partnership." Given what's actually been in Netflix's game catalog so far, that description checks out.

## What's Confirmed

*Grand Theft Auto VI: An Extended Look* airs on Netflix at 3pm ET on August 27, with the same footage going up on Rockstar's YouTube channel and the official GTA 6 site six hours later at 9pm ET. This is a video premiere — an extended trailer-style look at the game, not a playable version of GTA 6 on Netflix. Nothing about the game itself being available to play through Netflix has been announced by Rockstar, Take-Two, or Netflix.

## Why This Is Actually Unusual for Netflix

Netflix's gaming push to date has been built around its own catalog: Boggle, Pictionary, LEGO Party, a reimagined FIFA, and a title called Unhinged — casual, TV-based, cloud-streamed games Netflix names as its most successful cloud debuts. That's the lane Netflix has been building in.

Hosting the exclusive premiere of promotional footage for the single biggest game launch of the year — one it doesn't own, publish, or have any game-catalog stake in — is a different kind of move. It's not Netflix expanding its own games. It's Netflix positioning itself as a venue the biggest publisher in the industry wants to premiere through.

## What This Might Signal — Labeled Clearly as Speculation

Netflix's co-CEO has called gaming a "$150 billion opportunity" outside China and Russia and confirmed cloud gaming is expanding to more members and regions through 2026. Whether the GTA 6 partnership is a one-off marketing arrangement or an early sign Netflix wants to become a premiere venue for major publisher content beyond its own catalog is not something Netflix, Rockstar, or Take-Two has said directly — that's speculation based on the pattern, not a confirmed strategy.

Whether Rockstar and Take-Two do anything further with Netflix beyond this one premiere is equally unconfirmed. Nothing has been announced about GTA 6 content, playable or otherwise, appearing on Netflix again after August 27.

## Bottom Line

Netflix is premiering GTA 6 footage six hours ahead of everyone else, and Netflix's own language calls it a first for the platform. Its actual game catalog so far is casual, TV-based titles it owns outright. Whether this is a one-time marketing moment or the start of Netflix hosting content for publishers it doesn't own is an open question — not one anyone involved has answered yet.""",
        faq=[
            {"question": "Is GTA 6 playable on Netflix?",
             "answer": "No. The Netflix premiere on August 27, 2026 is an extended look video — promotional footage of GTA 6, not a playable version of the game. Nothing about GTA 6 being playable through Netflix has been announced."},
            {"question": "When does the GTA 6 Netflix extended look air?",
             "answer": "The GTA 6 Extended Look premieres on Netflix at 3pm ET on August 27, 2026, six hours before the same footage goes live on Rockstar's YouTube channel and the official GTA 6 website at 9pm ET."},
            {"question": "Has Netflix hosted a game premiere like this before?",
             "answer": "Netflix itself describes the GTA 6 extended look as a first-of-its-kind partnership. Netflix's existing game catalog consists mostly of casual, cloud-streamed titles it owns or licenses directly, such as Boggle, Pictionary, LEGO Party, and a reimagined FIFA — not premiere content for a major publisher's flagship release."},
        ],
    ),
]


def build_row(article: dict) -> dict:
    content = article["content"]
    word_count = len(content.split())
    faq_pairs = article["faq"]
    row = {
        "product_id": PRODUCT_ID,
        "slug": article["slug"],
        "title": article["title"],
        "content": content,
        "excerpt": article["excerpt"],
        "article_type": article["article_type"],
        "category": article["article_type"],
        "status": "pending_review",
        "agent_generated": True,
        "featured_image_url": article["featured_image_url"],
        "featured_image_credit": "© Rockstar Games",
        "featured_image_tier": 1,
        "external_citation": article["external_citation"],
        "internal_links_used": article["internal_links"],
        "faq_pairs": faq_pairs,
        "word_count": word_count,
        "schema_article": schema_article(article["title"], article["slug"], article["excerpt"]),
        "schema_faq": schema_faq(faq_pairs),
        "schema_breadcrumb": schema_breadcrumb(article["title"], article["slug"]),
    }
    return row


def main() -> None:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    for article in ARTICLES:
        row = build_row(article)
        existing = client.table("articles").select("id").eq("slug", row["slug"]).execute()
        if existing.data:
            print(f"SKIP (slug exists): {row['slug']}")
            continue
        result = client.table("articles").insert(row).execute()
        inserted = result.data[0]
        print(f"Inserted: {inserted['slug']} (id={inserted['id']}, {row['word_count']} words, status=pending_review)")


if __name__ == "__main__":
    main()
