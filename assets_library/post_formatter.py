"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
LinkedIn Asset Vault — post_formatter.py

# INTEGRATION: MKT-LI1 raw output -> post_formatter.py -> formatted post
# -> LinkedIn API payload. Always runs before the post is submitted.
# Formatter output is what goes to LinkedIn, never the raw MKT-LI1 output.

Enforces the LinkedIn post structure rules: one sentence per line, blank
line between every line, arrow/bullet markers (-> - the em-dash reads as
"-" in some fonts but the actual character used throughout is an em-dash,
not a hyphen, and the bullet characters accepted are limited to the
approved set: -> em-dash) preserved as atomic (never sentence-split),
hook-line checks (length, emoji presence -- flagged only, never
auto-added, per this repo's explicit human-judgment rule for emoji
choice), hashtag block extraction + trim-to-5, and credit-line
appending for non-original images.

Normalizes spacing by design rather than conditionally detecting it:
every content line ends up separated by exactly one blank line
regardless of how the raw input was spaced, which satisfies "don't
double-double-space" without needing to special-case already-spaced
input.
"""

import argparse
import re
import sys

_TEXT_LIMIT = 3000
_HOOK_LIMIT = 150
_MAX_HASHTAGS = 5
_MAX_EMOJIS = 3

# Only these count as list/contrast markers -- an atomic line is never
# split into sentences if it starts with one of these.
_MARKER_CHARS = ("→", "—", "⚡", "✅", "❌")  # -> ; -- (em dash) ; lightning ; check ; cross

_APPROVED_EMOJIS = [
    "⚡", "\U0001f527", "\U0001f680", "\U0001f6e0", "\U0001f4e1", "\U0001f50d",   # technical
    "✅", "❌", "\U0001f525", "\U0001f4a1",                                    # contrast
    "\U0001f447", "\U0001f446", "\U0001f449",                                          # pointing
]

# Not exhaustive, just a reasonable baseline for the "keep the most
# specific hashtags" heuristic -- broad/generic tags are dropped first
# when trimming, specific ones are kept, matching the "one broad + one
# specific + one career" mix intent without needing true topical NLP.
_BROAD_HASHTAGS = {
    "#ai", "#tech", "#technology", "#cloudcomputing", "#cloud", "#devops",
    "#business", "#innovation", "#career", "#careers", "#futureofwork",
}

_HASHTAG_BLOCK_RE = re.compile(r"(?:#\w+\s*)+$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_hashtags(text: str) -> tuple[str, list[str]]:
    match = _HASHTAG_BLOCK_RE.search(text)
    if not match:
        return text, []
    hashtags = re.findall(r"#\w+", match.group())
    body = text[: match.start()].rstrip()
    return body, hashtags


def _split_into_lines(body: str) -> list[str]:
    raw_lines = [l.strip() for l in body.splitlines() if l.strip()]
    if not raw_lines:
        raw_lines = [body.strip()] if body.strip() else []

    lines: list[str] = []
    for raw_line in raw_lines:
        if raw_line.startswith(_MARKER_CHARS):
            lines.append(raw_line)
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(raw_line):
            sentence = sentence.strip()
            if sentence:
                lines.append(sentence)
    return lines


def _looks_like_emoji_start(line: str) -> bool:
    """Crude heuristic, not a full emoji-detection library: a hook that
    starts with a letter or digit has no emoji; anything else (a symbol,
    emoji, or other non-alphanumeric character) counts as one for this
    warning's purposes. Imperfect by design -- this is a soft warning a
    human reviews, not an auto-fix, so false positives/negatives here are
    an acceptable tradeoff against pulling in a full emoji-data dependency."""
    if not line:
        return False
    first = line[0]
    return not (first.isalpha() or first.isdigit())


def _trim_hashtags(hashtags: list[str], warnings: list[str]) -> list[str]:
    if len(hashtags) <= _MAX_HASHTAGS:
        return hashtags
    warnings.append(f"Hashtag count ({len(hashtags)}) exceeds {_MAX_HASHTAGS} -- trimmed, keeping the most specific")
    specific = [h for h in hashtags if h.lower() not in _BROAD_HASHTAGS]
    broad = [h for h in hashtags if h.lower() in _BROAD_HASHTAGS]
    return (specific + broad)[:_MAX_HASHTAGS]


def format_post(
    raw_text: str,
    credit_line: str | None = None,
    is_original: bool = False,
) -> tuple[str, list[str]]:
    """
    Formats raw MKT-LI1 post text per the LinkedIn structure rules.

    Returns (formatted_text, warnings) -- warnings are informational
    only, never block the formatted text from being returned. Callers
    (e.g. a HITL review step) decide what to do with them.
    """
    warnings: list[str] = []
    body, hashtags = _split_hashtags(raw_text.strip())
    lines = _split_into_lines(body)

    if lines:
        hook = lines[0]
        if len(hook) > _HOOK_LIMIT:
            warnings.append(f"Hook line exceeds {_HOOK_LIMIT} characters ({len(hook)} chars)")
        if "?" in hook:
            warnings.append("Hook line contains a question mark -- statements perform better as hooks")
        if not _looks_like_emoji_start(hook):
            warnings.append("Hook line has no emoji -- consider adding one (not auto-added, requires human judgment)")

    joined_lines = "\n".join(lines)
    emoji_count = sum(joined_lines.count(e) for e in _APPROVED_EMOJIS)
    if emoji_count > _MAX_EMOJIS:
        warnings.append(f"Post uses {emoji_count} emojis -- maximum is {_MAX_EMOJIS}")

    hashtags = _trim_hashtags(hashtags, warnings)

    output_parts = ["\n\n".join(lines)]
    if hashtags:
        output_parts.append(" ".join(hashtags))
    if not is_original and credit_line:
        output_parts.append(credit_line)

    formatted = "\n\n".join(part for part in output_parts if part)

    if len(formatted) > _TEXT_LIMIT:
        warnings.append(f"Formatted post exceeds {_TEXT_LIMIT} characters ({len(formatted)} chars) -- LinkedIn max is {_TEXT_LIMIT}")

    return formatted, warnings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default=None, help="Raw post text. Reads stdin if omitted.")
    parser.add_argument("--credit-line", default=None)
    parser.add_argument("--is-original", action="store_true")
    args = parser.parse_args()

    raw_text = args.text if args.text is not None else sys.stdin.read()
    formatted, warnings = format_post(raw_text, credit_line=args.credit_line, is_original=args.is_original)

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(formatted)


if __name__ == "__main__":
    main()
