"""
Coverage for MKT-LI1's stage-aware product content entry point
(generate_product_content, agents/marketing/mkt_li1_linkedin_brand.py,
marketing stage-gate update, session 2026-09-15).

mse_icp_configs.selling_stage lives in kdavis-microsaas-engine's own
migrations, not this repo's -- both repos share the same Supabase
project, so _get_product_selling_stage reads that table through this
repo's own Supabase client. Tests here fake that client directly (a
minimal MagicMock chain matching the real supabase-py query-builder
shape: .table().select().eq().maybe_single().execute() -> an object
with a .data attribute) rather than hitting a live database, matching
this file's existing convention of mocking get_anthropic_client/
run_compliance_guard/queue_for_review rather than a real LLM or DB.
"""
import json
from unittest.mock import MagicMock, patch

import agents.marketing.mkt_li1_linkedin_brand as li1


def _fake_response(payload: dict):
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    return response


def _no_compliance_flags():
    return {"revised_content": None, "flags": []}


def _fake_supabase_with_stage(stage):
    """stage=None simulates zero rows in mse_icp_configs (real
    supabase-py's .maybe_single().execute() returns .data=None, not a
    bare None response, when nothing matches)."""
    client = MagicMock()
    chain = client.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = MagicMock(data=None if stage is None else {"selling_stage": stage})
    return client


PRODUCT_KWARGS = dict(
    product_id="prod-showing-signal",
    product_name="Showing Signal",
    problem="Buyer's agents lose deals to showings nobody followed up on",
    audience="independent buyer's agents",
    outcome="automatic follow-up on every showing",
    url="https://showingsignal.thdstack.com",
)


# ── _get_product_selling_stage ───────────────────────────────────────

class TestGetProductSellingStage:
    def test_returns_the_configured_stage(self):
        fake_db = _fake_supabase_with_stage("warming")
        assert li1._get_product_selling_stage("prod-1", supabase_client=fake_db) == "warming"

    def test_queries_the_right_table_and_product_id(self):
        fake_db = _fake_supabase_with_stage("active")
        li1._get_product_selling_stage("prod-xyz", supabase_client=fake_db)
        fake_db.table.assert_called_once_with("mse_icp_configs")
        fake_db.table.return_value.eq.assert_called_once_with("product_id", "prod-xyz")

    def test_no_config_row_fails_closed_to_building(self):
        fake_db = _fake_supabase_with_stage(None)
        assert li1._get_product_selling_stage("prod-unknown", supabase_client=fake_db) == "building"

    def test_query_error_fails_closed_to_building(self):
        fake_db = MagicMock()
        fake_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = RuntimeError("network down")
        assert li1._get_product_selling_stage("prod-1", supabase_client=fake_db) == "building"


# ── generate_product_content ─────────────────────────────────────────

class TestGenerateProductContentBuildingStage:
    def test_building_stage_returns_none_and_generates_nothing(self):
        fake_db = _fake_supabase_with_stage("building")
        fake_client = MagicMock()

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "queue_for_review") as mock_queue, \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert result is None
        fake_client.messages.create.assert_not_called()
        mock_queue.assert_not_called()

    def test_building_stage_is_audited_as_skipped(self):
        fake_db = _fake_supabase_with_stage("building")

        with patch.object(li1, "get_anthropic_client"), \
             patch.object(li1, "queue_for_review"), \
             patch.object(li1, "write_audit_log") as mock_audit, \
             patch.object(li1, "emit_event") as mock_emit:
            li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["outcome"] == "skipped: selling_stage=building"
        mock_emit.assert_called_once_with(
            li1.AGENT_ID, "product_content_skipped",
            {"product_id": "prod-showing-signal", "selling_stage": "building"},
        )

    def test_no_config_row_at_all_also_generates_nothing(self):
        """No mse_icp_configs row -> fails closed to 'building' -> same
        zero-generation behavior, not silently treated as active."""
        fake_db = _fake_supabase_with_stage(None)
        fake_client = MagicMock()

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "queue_for_review") as mock_queue, \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert result is None
        fake_client.messages.create.assert_not_called()
        mock_queue.assert_not_called()


class TestGenerateProductContentWarmingStage:
    def test_warming_stage_generates_no_cta_or_url(self):
        fake_db = _fake_supabase_with_stage("warming")
        payload = {
            "post_copy": (
                "Most solo builders ship the feature and skip the follow-up system entirely.\n\n"
                "Building Showing Signal alongside the rest of the portfolio taught me why that's backwards — "
                "the follow-up system is the actual product, the feature is just the trigger.\n\n"
                "Still early, still shaping it."
            ),
            "hook_variants": ["a", "b", "c"],
            "notes": "",
        }
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_response(payload)

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
             patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-warm-1"}) as mock_queue, \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert result is not None
        assert PRODUCT_KWARGS["url"] not in result["post_copy"]

        no_cta_markers = ["sign up", "sign-up", "try it", "link in comments", "check it out", "join the waitlist"]
        lowered = result["post_copy"].lower()
        for marker in no_cta_markers:
            assert marker not in lowered

        assert result["hitl_tier"] == 3
        assert mock_queue.call_args.kwargs["tier"] == 3
        assert fake_client.messages.create.call_args.kwargs["system"] == li1.MENTION_ONLY_SYSTEM_PROMPT

    def test_warming_stage_strips_url_even_if_model_includes_it(self):
        """Defense in depth -- the prompt says no URL, but this is a
        code-enforced guarantee independent of what the model actually did."""
        fake_db = _fake_supabase_with_stage("warming")
        payload = {
            "post_copy": f"Building this right now: {PRODUCT_KWARGS['url']} — more soon.",
            "hook_variants": [],
            "notes": "",
        }
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_response(payload)

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
             patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-warm-2"}), \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert PRODUCT_KWARGS["url"] not in result["post_copy"]

    def test_warming_stage_records_selling_stage_on_the_post(self):
        fake_db = _fake_supabase_with_stage("warming")
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_response(
            {"post_copy": "Context post, no CTA.", "hook_variants": [], "notes": ""}
        )

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
             patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-warm-3"}), \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert result["selling_stage"] == "warming"

    def test_warming_stage_mkt10_flag_still_escalates(self):
        """Already Tier 3 by default for a product mention, but the flag
        path must not crash / must still surface hitl_notes."""
        fake_db = _fake_supabase_with_stage("warming")
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_response(
            {"post_copy": "Context post.", "hook_variants": [], "notes": ""}
        )

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "run_compliance_guard", return_value={"revised_content": None, "flags": ["flagged term"]}), \
             patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-warm-4"}) as mock_queue, \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert result["hitl_tier"] == 3
        assert mock_queue.call_args.kwargs["tier"] == 3
        assert "hitl_notes" in result


class TestGenerateProductContentActiveStage:
    def test_active_stage_generates_explicit_cta_via_launch_post(self):
        # 2026-09-15 directive: the URL lives in notes now, not the post
        # body -- post_copy closes with the standard "Link in the comments." line.
        fake_db = _fake_supabase_with_stage("active")
        payload = {
            "post_copy": (
                "Buyer's agents lose deals to showings nobody followed up on.\n\n"
                "Built for independent buyer's agents juggling more showings than they can personally track.\n\n"
                "Showing Signal watches every showing and fires the right follow-up automatically."
            ),
            "hook_variants": ["a", "b", "c"],
            "notes": "",
        }
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_response(payload)

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
             patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-active-1"}) as mock_queue, \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert result is not None
        assert PRODUCT_KWARGS["url"] not in result["post_copy"]
        assert result["post_copy"].endswith(li1.CTA_CLOSING_LINE)
        assert PRODUCT_KWARGS["url"] in result["notes"]
        assert result["hitl_tier"] == 3
        assert mock_queue.call_args.kwargs["tier"] == 3
        # Routed through the real, unchanged launch-post system prompt --
        # not the mention-only one.
        assert fake_client.messages.create.call_args.kwargs["system"] == li1.PRODUCT_LAUNCH_SYSTEM_PROMPT

    def test_active_stage_strips_url_and_closes_with_cta_line_if_model_includes_it(self):
        """generate_product_content delegates to the existing
        generate_product_launch_post for 'active' -- proven still wired
        through the new entry point, including the 2026-09-15 URL-out-of-
        body change."""
        fake_db = _fake_supabase_with_stage("active")
        payload = {"post_copy": f"Built for solo agents. {PRODUCT_KWARGS['url']}", "hook_variants": [], "notes": ""}
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_response(payload)

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
             patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-active-2"}), \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert PRODUCT_KWARGS["url"] not in result["post_copy"]
        assert result["post_copy"].endswith(li1.CTA_CLOSING_LINE)
        assert PRODUCT_KWARGS["url"] in result["notes"]


class TestGenerateProductContentDoesNotTouchEvergreenPoolOrPillar5:
    def test_never_touches_evergreen_batch_pool(self, monkeypatch):
        fake_db = _fake_supabase_with_stage("active")
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_response(
            {"post_copy": f"Built for solo agents. {PRODUCT_KWARGS['url']}", "hook_variants": [], "notes": ""}
        )

        def _boom(*a, **k):
            raise AssertionError("generate_product_content must not touch the evergreen batch pool")

        monkeypatch.setattr(li1, "_build_slots", _boom)
        monkeypatch.setattr(li1, "_content_pool", _boom)
        monkeypatch.setattr(li1, "_compute_schedule", _boom)

        with patch.object(li1, "get_anthropic_client", return_value=fake_client), \
             patch.object(li1, "run_compliance_guard", return_value=_no_compliance_flags()), \
             patch.object(li1, "queue_for_review", side_effect=lambda item, **kw: {"id": "queued-x"}), \
             patch.object(li1, "write_audit_log"), \
             patch.object(li1, "emit_event"):
            result = li1.generate_product_content(supabase_client=fake_db, **PRODUCT_KWARGS)

        assert result is not None

    def test_pillar_5_seed_has_no_product_reference_to_gate(self):
        """Confirms the documented reasoning directly: PILLAR_TOPIC_SEEDS
        for pillar_5 names no specific mse_products-style product, so
        there is nothing selling_stage-shaped in it for
        generate_product_content to have needed to touch."""
        pillar_5_seed = li1.PILLAR_TOPIC_SEEDS["pillar_5"].lower()
        for kwarg_value in (PRODUCT_KWARGS["product_name"], PRODUCT_KWARGS["url"]):
            assert kwarg_value.lower() not in pillar_5_seed
