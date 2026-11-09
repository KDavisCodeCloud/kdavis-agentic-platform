"""
agents/marketing/invented_metrics.py

Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Code-enforced "no invented metrics" check for LinkedIn copy (2026-11-09).

The MKT-LI1 voice prompt already says "use a number only if it is in the
source material". Prompts are not enforcement: the 2026-11-08 buyer-pain
samples still carried vignette specifics such as "four months" and "2am".
This module finds metric-shaped figures in a draft that the source material
does not contain, so the caller can retry the draft and, failing that, flag
it for the human reviewer.

Ported from kdavis-microsaas-engine's outreach_copy.unsourced_metrics and
extended to spelled-out numbers ("four months") and clock times ("2am").
"""

import json
import re
from typing import Optional

_NUMBER_WORDS = {
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
    "fifteen": "15", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
    "sixty": "60", "ninety": "90", "hundred": "100", "thousand": "1000",
}
# "one" is left out on purpose: "one thing", "one day" and "one team" are
# idiom far more often than they are a claimed figure.

_UNITS = (
    r"(?:hours?|hrs?|days?|weeks?|months?|quarters?|years?|minutes?|mins?|"
    r"engineers?|people|customers?|clients?|teams?|incidents?|outages?|alerts?|"
    r"pages?|tickets?|deploys?|deployments?|servers?|clusters?|accounts?)"
)
_WORD_ALT = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))

_METRIC_RE = re.compile(
    r"\$\s?\d[\d,.]*\s?(?:[kKmMbB]\b)?"
    r"|\b\d[\d,.]*\s?(?:%|percent\b|x\b)"
    rf"|\b\d[\d,.]*[\s-]?{_UNITS}\b"
    r"|\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)(?=\W|$)"
    rf"|\b(?:{_WORD_ALT})[\s-]{_UNITS}\b",
    re.IGNORECASE,
)

_DIGITS_RE = re.compile(r"\d[\d,.]*")
_WORD_RE = re.compile(rf"\b(?:{_WORD_ALT})\b", re.IGNORECASE)


def _numbers_in(text: str) -> set[str]:
    """Every number in `text`, digits and number words alike, normalised to digits."""
    found = {n.rstrip(".,").replace(",", "") for n in _DIGITS_RE.findall(text)}
    found |= {_NUMBER_WORDS[w.lower()] for w in _WORD_RE.findall(text)}
    return found


# The CTA itself may carry a duration ("a 15-minute call").
_ALLOWED_CTA_RE = re.compile(r"\b(?:15|20|30)[-\s]?min(?:ute)?s?\b", re.IGNORECASE)


def _normalise(phrase: str) -> str:
    """'Three  Years' and '3-years' compare equal."""
    words = re.split(r"[\s-]+", phrase.lower().strip())
    return " ".join(_NUMBER_WORDS.get(w, w) for w in words if w)


def unsourced_metrics(text: Optional[str], context: object, stock_phrases: str = "") -> list[str]:
    """Metric-shaped figures in `text` whose number appears nowhere in `context`.

    `context` is the material the post is about (source text, voice profile);
    a dict or list is JSON-encoded first, and any number in it counts as
    sourced, so "four months" passes if the context says "four" or "4".

    `stock_phrases` is fixed text such as the system prompt, which is full of
    structural numbers ("step 4", "3 reasons"). Only the metric phrases it
    states outright ("15 years") are allowed from it, never its bare numbers.

    Returns the offending phrases in order; an empty list means clean.
    """
    if not isinstance(text, str) or not text:
        return []
    blob = context if isinstance(context, str) else json.dumps(context, default=str)
    allowed = _numbers_in(blob)
    stock = {_normalise(m.group(0)) for m in _METRIC_RE.finditer(stock_phrases or "")}
    hits: list[str] = []
    for match in _METRIC_RE.finditer(_ALLOWED_CTA_RE.sub(" ", text)):
        phrase = match.group(0).strip()
        if _normalise(phrase) in stock:
            continue
        if not _numbers_in(phrase) <= allowed:
            hits.append(phrase)
    return hits
