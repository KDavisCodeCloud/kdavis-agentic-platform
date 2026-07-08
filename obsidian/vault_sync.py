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
vault_sync — writes SOP markdown directly into the local Obsidian vault
filesystem at OBSIDIAN_VAULT_PATH. This is the interactive/local-session
path; the CI-side push from a Supabase `sops` row INSERT
(.github/workflows/sop-sync.yml) goes over the Obsidian Local REST API
instead, since a GitHub Actions runner has no filesystem access to
Kelvin's vault — that path is out of scope here.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

VAULT_SUBPATH = ("KDavis Platform", "SOPs")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def push_sop(content: str, agent_name: str, task_summary: str) -> str:
    """Write SOP markdown to {vault}/KDavis Platform/SOPs/{agent_name}/{date}-{task}.md.

    Returns the absolute file path written.
    """
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if not vault_path:
        raise EnvironmentError("OBSIDIAN_VAULT_PATH not set — cannot push SOP to vault")

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = Path(vault_path).joinpath(*VAULT_SUBPATH, agent_name)
    folder.mkdir(parents=True, exist_ok=True)

    file_path = folder / f"{date_str}-{_slugify(task_summary)}.md"
    file_path.write_text(content)
    return str(file_path)
