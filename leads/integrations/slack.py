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
slack — thin wrapper around Slack's Web API for the operator/team
workspace: posting notifications, standing up channels, and managing
membership.

invite_user / remove_user call the `admin.users.*` endpoints, which
require an Enterprise Grid org with an admin-scoped token
(admin.users:write). On a standard (non-Grid) workspace, Slack's Web
API does not expose email invites — use the workspace's own Invite
People UI or a SCIM provisioning flow instead; these two methods will
fail with a permission error there, by design, not silently.
"""

import os
from typing import Any, Optional

DEFAULT_BASE_URL = "https://slack.com/api"


class SlackAPIError(RuntimeError):
    pass


class SlackClient:
    def __init__(self, bot_token: Optional[str] = None, team_id: Optional[str] = None, client: Optional[Any] = None):
        self._token = bot_token or os.environ["SLACK_BOT_TOKEN"]
        self._team_id = team_id or os.getenv("SLACK_TEAM_ID")
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                base_url=DEFAULT_BASE_URL,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=15.0,
            )
        return self._client

    def _call(self, method: str, payload: dict) -> dict:
        response = self._get_client().post(f"/{method}", json=payload)
        if response.status_code >= 400:
            raise SlackAPIError(f"Slack API {method} HTTP {response.status_code}: {response.text}")
        data = response.json()
        if not data.get("ok"):
            raise SlackAPIError(f"Slack API {method} failed: {data.get('error')}")
        return data

    def post_message(self, channel: str, text: str, blocks: Optional[list[dict]] = None) -> dict:
        payload: dict = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        return self._call("chat.postMessage", payload)

    def create_channel(self, name: str, is_private: bool = False) -> dict:
        return self._call("conversations.create", {"name": name, "is_private": is_private})

    def invite_user(self, email: str, channel_ids: Optional[list[str]] = None, resend: bool = False) -> dict:
        if not self._team_id:
            raise SlackAPIError("SLACK_TEAM_ID is required for admin.users.invite (Enterprise Grid only)")
        payload: dict = {"email": email, "team_id": self._team_id, "resend": resend}
        if channel_ids:
            payload["channel_ids"] = ",".join(channel_ids)
        return self._call("admin.users.invite", payload)

    def remove_user(self, user_id: str) -> dict:
        if not self._team_id:
            raise SlackAPIError("SLACK_TEAM_ID is required for admin.users.remove (Enterprise Grid only)")
        return self._call("admin.users.remove", {"user_id": user_id, "team_id": self._team_id})
