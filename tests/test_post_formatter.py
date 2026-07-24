"""
Coverage for assets_library/post_formatter.py's LinkedIn structure rules:
sentence-per-line splitting, blank-line normalization, marker-line
preservation, hook checks (length/question-mark/emoji -- warn only,
never auto-add), hashtag extraction + trim-to-5, credit-line appending,
and the 3000-char ceiling.
"""
from assets_library.post_formatter import format_post


def test_splits_run_on_sentences_onto_separate_double_spaced_lines():
    raw = "Most engineers think Kubernetes is complex. It's not. The complexity is in understanding what problem it solves."
    formatted, _ = format_post(raw)
    assert formatted == (
        "Most engineers think Kubernetes is complex.\n\n"
        "It's not.\n\n"
        "The complexity is in understanding what problem it solves."
    )


def test_numbered_list_marker_stays_on_the_same_line_as_its_statement():
    # Found 2026-07-25 in a real drafted post: the sentence-splitter
    # treated "1." as a sentence-ending period, same as a real ".", and
    # split the list number onto its own line, separate from its
    # statement. "1." must never count as a sentence boundary on its own.
    raw = (
        "1. Are you Azure-only now and in 18 months? "
        "2. Who's maintaining this? "
        "3. What's your blast radius?"
    )
    formatted, _ = format_post(raw)
    assert formatted == (
        "1. Are you Azure-only now and in 18 months?\n\n"
        "2. Who's maintaining this?\n\n"
        "3. What's your blast radius?"
    )
    assert "1.\n\n" not in formatted
    assert "2.\n\n" not in formatted


def test_preserves_arrow_marker_lines_as_atomic_not_sentence_split():
    raw = "In 2024 you did this manually.\n→ Writing Terraform line by line.\n→ Reviewing every PR yourself."
    formatted, _ = format_post(raw)
    assert "→ Writing Terraform line by line." in formatted.split("\n\n")
    assert "→ Reviewing every PR yourself." in formatted.split("\n\n")


def test_never_auto_adds_an_emoji_to_a_hook_missing_one():
    raw = "Most companies are still treating AI like a search engine. They ask it questions."
    formatted, warnings = format_post(raw)
    assert not formatted.startswith(("⚡", "🔥", "✅"))
    assert any("no emoji" in w for w in warnings)


def test_hook_with_emoji_does_not_trigger_the_missing_emoji_warning():
    raw = "🔥 Most companies are still treating AI like a search engine. They ask it questions."
    _, warnings = format_post(raw)
    assert not any("no emoji" in w for w in warnings)


def test_question_mark_hook_gets_flagged():
    raw = "Is Kubernetes really that complex? It depends on your workload."
    _, warnings = format_post(raw)
    assert any("question mark" in w for w in warnings)


def test_hook_over_150_chars_gets_flagged():
    raw = ("This is a very long hook line that goes on and on well past the one hundred and fifty character "
           "limit that LinkedIn hooks are supposed to respect for best performance. More text after.")
    _, warnings = format_post(raw)
    assert any("exceeds 150" in w for w in warnings)


def test_hashtags_extracted_onto_their_own_final_block():
    raw = "This is the post body. #AI #AgenticAI #DevOps"
    formatted, _ = format_post(raw)
    parts = formatted.split("\n\n")
    assert parts[-1] == "#AI #AgenticAI #DevOps"
    assert "#AI" not in parts[0]


def test_more_than_five_hashtags_gets_trimmed_to_five(monkeypatch):
    raw = "Post body here. #AI #Tech #AgenticAI #Kubernetes #DevOps #TechCareers #CloudComputing"
    formatted, warnings = format_post(raw)
    hashtag_line = formatted.split("\n\n")[-1]
    assert len(hashtag_line.split()) == 5
    assert any("exceeds 5" in w for w in warnings)


def test_trimming_keeps_specific_hashtags_over_broad_ones():
    # 7 tags: 3 broad (#ai #tech #devops), 4 specific -- trimming to 5
    # should drop broad ones first, keeping all 4 specific + 1 broad.
    raw = "Post body. #AI #Tech #AgenticAI #Kubernetes #DevOps #PromptEngineering #MultiAgentSystems"
    formatted, _ = format_post(raw)
    hashtag_line = formatted.split("\n\n")[-1]
    for specific in ["#AgenticAI", "#Kubernetes", "#PromptEngineering", "#MultiAgentSystems"]:
        assert specific in hashtag_line


def test_credit_line_appended_as_final_line_for_non_original_image():
    raw = "Post body here."
    formatted, _ = format_post(raw, credit_line="Visual credit: @aloksharan", is_original=False)
    assert formatted.endswith("Visual credit: @aloksharan")


def test_credit_line_never_appended_for_original_image():
    raw = "Post body here."
    formatted, _ = format_post(raw, credit_line="Visual credit: @aloksharan", is_original=True)
    assert "Visual credit" not in formatted


def test_over_3000_chars_gets_flagged():
    raw = "This is one sentence. " * 200
    _, warnings = format_post(raw)
    assert any("exceeds 3000" in w for w in warnings)


def test_credit_line_and_hashtags_ordered_hashtags_then_credit():
    raw = "Post body. #AI #DevOps"
    formatted, _ = format_post(raw, credit_line="Visual credit: @aloksharan", is_original=False)
    parts = formatted.split("\n\n")
    assert parts[-2] == "#AI #DevOps"
    assert parts[-1] == "Visual credit: @aloksharan"
