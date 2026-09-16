"""
Coverage for agents/marketing/mkt_li1_linkedin_brand.py's _apply_closing_line
(added 2026-09-15, Kelvin's directive): replaces the old CTA ROTATION system
("Comment [KEYWORD] if you want the full breakdown" for technical posts, "no
CTA" for personal/philosophy posts) with two mandatory closing lines --
"Link in the comments." for Pillar 4/Product Launch posts, "If you or your
team is interested in working with me, link is in the description." for
every other post type -- so Kelvin can always attach a link to any post.
"""
import agents.marketing.mkt_li1_linkedin_brand as li1


def test_appends_cta_line_for_cta_posts():
    result = li1._apply_closing_line("Some post body.", is_cta_post=True)
    assert result == "Some post body.\n\nLink in the comments."


def test_appends_working_with_me_line_for_other_posts():
    result = li1._apply_closing_line("Some post body.", is_cta_post=False)
    assert result == "Some post body.\n\nIf you or your team is interested in working with me, link is in the description."


def test_strips_comment_keyword_pattern_before_appending():
    text = "The judgment isn't.\n\nComment DECODED if you want the full breakdown on how it works."
    result = li1._apply_closing_line(text, is_cta_post=True)
    assert "DECODED" not in result
    assert result == "The judgment isn't.\n\nLink in the comments."


def test_strips_comment_keyword_mid_sentence():
    text = "I'm building the thing.\n\nIf that's the gap you're sitting in, comment DECODED and I'll share where it stands."
    result = li1._apply_closing_line(text, is_cta_post=True)
    assert "comment DECODED" not in result.lower()
    assert result.endswith("Link in the comments.")


def test_strips_drop_a_comment_or_dm_me_pattern():
    text = "I'm building this for you.\n\nDrop a comment or DM me and I'll get you on the early access list."
    result = li1._apply_closing_line(text, is_cta_post=True)
    assert "DM me" not in result
    assert result.endswith("Link in the comments.")


def test_strips_follow_along_pattern():
    text = "Some weeks it's this.\n\nFollow along if you want the unedited version."
    result = li1._apply_closing_line(text, is_cta_post=False)
    assert "Follow along" not in result
    assert result.endswith(li1.WORKING_WITH_ME_CLOSING_LINE)


def test_preserves_content_before_the_stripped_cta_clause():
    text = "Early access is open.\n\nComment DECODED and I'll send the details."
    result = li1._apply_closing_line(text, is_cta_post=True)
    assert "Early access is open." in result
    assert result == "Early access is open.\n\nLink in the comments."


def test_idempotent_when_closing_line_already_present():
    text = "Some post body.\n\nLink in the comments."
    result = li1._apply_closing_line(text, is_cta_post=True)
    assert result == text
    # No double closing line
    assert result.count("Link in the comments.") == 1
