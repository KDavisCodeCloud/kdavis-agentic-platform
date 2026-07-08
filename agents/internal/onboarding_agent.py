"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
onboarding_agent — handles inviting a new internal team member (the
pattern CLAUDE.md alludes to: "when your son comes on board"). Not
speced anywhere in CLAUDE.md's BUILD SEQUENCE or EXECUTION_ORDER.md —
built per this session's explicit request. If a later session reconciles
it against a real spec, treat this docstring as the design record to
diff against, not as authoritative.

Two-phase by design, matching the platform's own non-negotiable #2
("HITL gates before any execution that touches external systems ...
No exceptions"): prepare_invite() only builds a decision card — it
touches no filesystem and no Supabase. execute_invite() is the one that
copies the template folder and fires the Supabase invite, and it should
only ever be called after that card is approved.

Supabase's admin invite call (auth.admin.inviteUserByEmail-equivalent)
isn't wired anywhere in this repo yet, and the "personal folder" template
this is meant to copy from doesn't exist on disk yet either — both are
injected (supabase_invite_fn, template_dir) rather than hardcoded, so
this module is fully testable before either exists for real.
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

VALID_ROLES = {"owner", "operator", "team_member"}


class InvalidRoleError(ValueError):
    pass


@dataclass(frozen=True)
class TeamMemberInvite:
    email: str
    name: str
    role: str

    def __post_init__(self):
        if self.role not in VALID_ROLES:
            raise InvalidRoleError(f"role must be one of {sorted(VALID_ROLES)}, got '{self.role}'")


@dataclass
class InviteDecisionCard:
    email: str
    name: str
    role: str
    message: str
    options: list[str] = field(default_factory=lambda: ["send_invite", "hold", "cancel"])

    def to_row(self) -> dict:
        return {"email": self.email, "name": self.name, "role": self.role, "message": self.message, "options": self.options}


@dataclass
class OnboardingResult:
    email: str
    folder_path: Optional[str]
    invite_status: str  # "sent" | "not_wired" | "failed"
    invite_detail: Optional[str] = None

    def to_row(self) -> dict:
        return {
            "email": self.email, "folder_path": self.folder_path,
            "invite_status": self.invite_status, "invite_detail": self.invite_detail,
        }


def _slugify(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


class OnboardingAgent:
    def prepare_invite(self, invite: TeamMemberInvite) -> InviteDecisionCard:
        """Builds the approval card. No side effects."""
        return InviteDecisionCard(
            email=invite.email, name=invite.name, role=invite.role,
            message=f"Invite {invite.name} <{invite.email}> as {invite.role}? "
                    f"This will create their personal folder and send a Supabase invite email.",
        )

    def execute_invite(
        self,
        invite: TeamMemberInvite,
        template_dir: Path,
        target_root: Path,
        supabase_invite_fn: Optional[Callable[[str, dict], dict]] = None,
    ) -> OnboardingResult:
        """Only call after the card from prepare_invite() has been
        approved. Copies template_dir -> target_root/{slug} and, if
        supabase_invite_fn is provided, fires it. Raises
        FileNotFoundError with a descriptive message if template_dir
        doesn't exist rather than silently skipping folder creation —
        matching the platform's "no silent failures" rule."""
        if not template_dir.exists():
            raise FileNotFoundError(
                f"Personal folder template not found at {template_dir}. "
                "Create it before running onboarding — see this module's "
                "docstring; no template folder exists in this repo yet."
            )

        slug = _slugify(invite.name) or _slugify(invite.email)
        destination = target_root / slug
        shutil.copytree(template_dir, destination, dirs_exist_ok=False)

        if supabase_invite_fn is None:
            return OnboardingResult(
                email=invite.email, folder_path=str(destination), invite_status="not_wired",
                invite_detail="No supabase_invite_fn provided — folder created, invite email not sent.",
            )

        response = supabase_invite_fn(invite.email, {"name": invite.name, "role": invite.role})
        return OnboardingResult(
            email=invite.email, folder_path=str(destination), invite_status="sent",
            invite_detail=str(response.get("id", response)) if isinstance(response, dict) else str(response),
        )
