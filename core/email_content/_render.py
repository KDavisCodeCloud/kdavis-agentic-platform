"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Shared HTML/text renderer for every generated marketing template
(core/email_content/*.py) -- same inline-style card shape core/email.py's
transactional templates already use (max-width ~520px, #1a1a1a text,
#2f6fe6 CTA button), so a marketing send and a transactional send from
this platform look like the same product, not two different ones.
compliance_footer_html/_text (core/marketing_email.py) is appended
separately at send time -- never call that from here.
"""

from typing import Optional


def render_html(
    heading: str, paragraphs: list[str], cta_text: Optional[str] = None, cta_url: Optional[str] = None,
) -> str:
    body = "\n  ".join(f"<p>{p}</p>" for p in paragraphs)
    cta = ""
    if cta_text and cta_url:
        cta = f"""
  <p><a href="{cta_url}"
        style="display:inline-block;background:#2f6fe6;color:#fff;padding:10px 18px;
               border-radius:8px;text-decoration:none;font-weight:600">
    {cta_text} →</a></p>"""
    return f"""\
<div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
  <h1 style="font-size:20px">{heading}</h1>
  {body}{cta}
</div>"""


def render_text(
    heading: str, paragraphs: list[str], cta_text: Optional[str] = None, cta_url: Optional[str] = None,
) -> str:
    lines = [heading, ""]
    lines.extend(paragraphs)
    if cta_text and cta_url:
        lines.append("")
        lines.append(f"{cta_text}: {cta_url}")
    return "\n\n".join(lines)


_APP_URL = "https://theclouddecoded.com/dashboard"
_SECURITY_URL = "https://theclouddecoded.com/security"
_PRICING_URL = "https://theclouddecoded.com/#pricing"
_TEN_PROBLEMS_URL = "https://theclouddecoded.com/10-problems"
_BILLING_URL = "https://theclouddecoded.com/billing"
_MEMBERS_URL = "https://theclouddecoded.com/dashboard?tab=members"
