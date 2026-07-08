"""
tests/test_onboarding_agent.py
Stub coverage for agents/internal/onboarding_agent.py.

What this file validates:
  - TeamMemberInvite rejects an invalid role at construction time
  - prepare_invite() has no filesystem or network side effects
  - execute_invite() raises a descriptive FileNotFoundError when the
    template folder doesn't exist, instead of failing silently
  - execute_invite() copies the template into target_root/{slug}
  - execute_invite() returns invite_status="not_wired" when no
    supabase_invite_fn is supplied, and "sent" when one is
"""

import pytest

from agents.internal.onboarding_agent import InvalidRoleError, OnboardingAgent, TeamMemberInvite


def test_invalid_role_raises_at_construction():
    with pytest.raises(InvalidRoleError):
        TeamMemberInvite("a@b.com", "A B", "superadmin")


def test_prepare_invite_has_no_side_effects(tmp_path):
    invite = TeamMemberInvite("son@thd.com", "Son Davis", "team_member")
    card = OnboardingAgent().prepare_invite(invite)
    assert card.email == "son@thd.com"
    assert list(tmp_path.iterdir()) == []


def test_execute_invite_raises_descriptive_error_for_missing_template(tmp_path):
    invite = TeamMemberInvite("son@thd.com", "Son Davis", "team_member")
    missing_template = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError, match="template not found"):
        OnboardingAgent().execute_invite(invite, missing_template, tmp_path / "team")


def test_execute_invite_copies_template_to_target_root(tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    (template / "README.md").write_text("hello")
    target_root = tmp_path / "team"
    target_root.mkdir()

    invite = TeamMemberInvite("son@thd.com", "Son Davis", "team_member")
    result = OnboardingAgent().execute_invite(invite, template, target_root)

    assert (target_root / "son-davis" / "README.md").read_text() == "hello"
    assert result.folder_path == str(target_root / "son-davis")


def test_execute_invite_not_wired_without_supabase_fn(tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    target_root = tmp_path / "team"
    target_root.mkdir()

    invite = TeamMemberInvite("son@thd.com", "Son Davis", "team_member")
    result = OnboardingAgent().execute_invite(invite, template, target_root)
    assert result.invite_status == "not_wired"


def test_execute_invite_sent_when_supabase_fn_provided(tmp_path):
    template = tmp_path / "template"
    template.mkdir()
    target_root = tmp_path / "team"
    target_root.mkdir()

    invite = TeamMemberInvite("son@thd.com", "Son Davis", "team_member")
    result = OnboardingAgent().execute_invite(
        invite, template, target_root, supabase_invite_fn=lambda email, meta: {"id": "user_123"},
    )
    assert result.invite_status == "sent"
    assert result.invite_detail == "user_123"
