"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.

Phase 6, scale-readiness build. Durability for webhook-triggered agent
runs -- see db/migrations/030_alert_ingestion_log.sql for why this table
exists (FastAPI BackgroundTasks aren't durable; this makes "alert
received" survive a process restart between the 202 and the background
task finishing).

Usage in a webhook route:
    log_id = await log_alert_received(conn, workspace_id, payload_bytes)
    background_tasks.add_task(_run_agent, ..., ingestion_log_id=log_id)

Usage in the background task's `finally` block:
    await mark_alert_processed(conn, log_id)

mark_alert_processed runs regardless of whether the agent run itself
succeeded or raised -- "processed" here means "the system took the
delivery to completion" (including a handled failure, now visible via
Sentry/audit_events per Phase 5's earlier work this session), not
"succeeded." Only a genuine process death mid-execution leaves
processed_at unset, which is exactly the recoverable case
find_unprocessed_older_than() surfaces.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Union
from uuid import UUID

log = logging.getLogger(__name__)


async def log_alert_received(conn, workspace_id: str, raw_payload: Union[bytes, dict]) -> str:
    """Persist 'alert received' before the webhook route returns 202.
    Returns the log row's id (str) to pass through to the background task."""
    if isinstance(raw_payload, (bytes, bytearray)):
        try:
            payload_json = json.loads(raw_payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload_json = {"_raw_base64_unparseable": True}
    else:
        payload_json = raw_payload

    row = await conn.fetchrow(
        """
        INSERT INTO alert_ingestion_log (workspace_id, raw_payload)
        VALUES ($1, $2)
        RETURNING id
        """,
        UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id,
        json.dumps(payload_json),
    )
    return str(row["id"])


async def mark_alert_processed(conn, log_id: str, worker_id: Optional[str] = None) -> None:
    """Mark a logged alert as processed -- called in a `finally` block so
    it runs whether the agent run succeeded or raised."""
    await conn.execute(
        """
        UPDATE alert_ingestion_log
        SET processed_at = $2, worker_id = COALESCE($3, worker_id)
        WHERE id = $1
        """,
        UUID(str(log_id)),
        datetime.now(timezone.utc),
        worker_id,
    )


async def find_unprocessed_older_than(conn, older_than_minutes: int = 5) -> list[dict]:
    """The recovery set on restart: rows still processed_at IS NULL after
    longer than a normal agent run should ever take -- these are the
    alerts a dead process never finished handling."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    rows = await conn.fetch(
        """
        SELECT id, workspace_id, raw_payload, received_at
        FROM alert_ingestion_log
        WHERE processed_at IS NULL AND received_at < $1
        ORDER BY received_at ASC
        """,
        cutoff,
    )
    return [dict(row) for row in rows]
