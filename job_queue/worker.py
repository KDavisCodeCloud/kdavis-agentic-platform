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
queue/worker — SQS long-polling consumer. Each message body is expected
to be JSON shaped {"job_type": "...", "payload": {...}}; job_type is
looked up in a HandlerRegistry and dispatched to the matching agent
handler. A message is only deleted after its handler returns
successfully — a failed handler leaves the message in the queue for
SQS's visibility timeout / redrive policy to retry or dead-letter, so a
crash never silently drops work.

Throttling: on an empty poll the worker backs off exponentially (with
jitter) up to max_backoff_seconds, resetting to the minimum the moment
a message arrives — long-polling (WaitTimeSeconds) already avoids
hammering SQS between polls, this backoff avoids hammering it during
sustained idle periods.

boto3 is imported lazily so this module (and anything that imports it)
loads without the package installed; a client is always injectable for
testing via the constructor.
"""

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

JobHandler = Callable[[dict], None]


class HandlerNotFoundError(RuntimeError):
    pass


class HandlerRegistry:
    def __init__(self):
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> Optional[JobHandler]:
        return self._handlers.get(job_type)

    def dispatch(self, job_type: str, payload: dict) -> None:
        handler = self._handlers.get(job_type)
        if handler is None:
            raise HandlerNotFoundError(f"No handler registered for job_type={job_type!r}")
        handler(payload)


default_registry = HandlerRegistry()


def register_handler(job_type: str) -> Callable[[JobHandler], JobHandler]:
    """Decorator: @register_handler("accounting_agent.process_receipt")"""

    def decorator(handler: JobHandler) -> JobHandler:
        default_registry.register(job_type, handler)
        return handler

    return decorator


def _get_sqs_client() -> Any:
    import boto3

    return boto3.client("sqs", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))


@dataclass
class SQSWorker:
    queue_url: Optional[str] = None
    client: Optional[Any] = None
    registry: HandlerRegistry = field(default_factory=lambda: default_registry)
    max_messages: int = 10
    wait_time_seconds: int = 20
    visibility_timeout: int = 30
    min_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0

    def __post_init__(self):
        self.queue_url = self.queue_url or os.getenv("SQS_QUEUE_URL")
        self._backoff = self.min_backoff_seconds

    def _client_or_default(self) -> Any:
        return self.client if self.client is not None else _get_sqs_client()

    def poll_once(self) -> int:
        """Receives up to max_messages, dispatches each, deletes on
        success. Returns the count successfully processed."""
        if not self.queue_url:
            raise RuntimeError("queue_url is required (pass explicitly or set SQS_QUEUE_URL)")

        client = self._client_or_default()
        response = client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=self.max_messages,
            WaitTimeSeconds=self.wait_time_seconds,
            VisibilityTimeout=self.visibility_timeout,
        )
        processed = 0
        for message in response.get("Messages", []):
            if self._process_message(client, message):
                processed += 1
        return processed

    def _process_message(self, client: Any, message: dict) -> bool:
        receipt_handle = message["ReceiptHandle"]
        try:
            body = json.loads(message["Body"])
        except (KeyError, json.JSONDecodeError) as exc:
            log.error("Malformed queue message, deleting: %s", exc)
            client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
            return False

        job_type = body.get("job_type")
        try:
            self.registry.dispatch(job_type, body.get("payload", {}))
        except Exception as exc:  # noqa: BLE001 — isolate one bad message from the rest of the batch
            log.error("Handler for job_type=%s failed, leaving message for redrive: %s", job_type, exc)
            return False

        client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
        return True

    def run_forever(self, should_continue: Callable[[], bool] = lambda: True) -> None:
        while should_continue():
            processed = self.poll_once()
            if processed > 0:
                self._backoff = self.min_backoff_seconds
                continue
            time.sleep(self._backoff + random.uniform(0, self._backoff * 0.1))
            self._backoff = min(self._backoff * 2, self.max_backoff_seconds)
