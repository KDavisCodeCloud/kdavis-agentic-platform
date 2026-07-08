"""
tests/test_queue_worker.py
Tests for job_queue/worker.py — HandlerRegistry and SQSWorker.

What this file validates:
  - HandlerRegistry dispatches to the registered handler and raises a
    descriptive error for an unknown job_type
  - SQSWorker.poll_once: happy path deletes the message after a
    successful handler call, a malformed message is discarded, and a
    handler exception leaves the message in the queue (no delete —
    left for SQS redrive) rather than swallowing the failure
  - queue_url is required before polling
  - run_forever's exponential backoff resets on a non-empty poll and
    grows (capped) on empty polls, without ever sleeping for real

No real boto3/SQS calls happen — the client is always a mock.
"""

import json

import pytest
from unittest.mock import MagicMock

from job_queue.worker import HandlerNotFoundError, HandlerRegistry, SQSWorker


# ──────────────────────────────────────────────────────────────────────────────
# HandlerRegistry
# ──────────────────────────────────────────────────────────────────────────────

class TestHandlerRegistry:
    def test_dispatch_calls_registered_handler(self):
        registry = HandlerRegistry()
        received = {}
        registry.register("job.a", lambda payload: received.update(payload))

        registry.dispatch("job.a", {"x": 1})

        assert received == {"x": 1}

    def test_dispatch_unknown_job_type_raises(self):
        registry = HandlerRegistry()
        with pytest.raises(HandlerNotFoundError, match="job.missing"):
            registry.dispatch("job.missing", {})


# ──────────────────────────────────────────────────────────────────────────────
# SQSWorker.poll_once
# ──────────────────────────────────────────────────────────────────────────────

def _sqs_message(job_type="job.a", payload=None, receipt_handle="rh-1", body_override=None):
    body = body_override if body_override is not None else json.dumps({"job_type": job_type, "payload": payload or {}})
    return {"MessageId": "m1", "ReceiptHandle": receipt_handle, "Body": body}


class TestSQSWorkerPollOnce:
    def test_requires_queue_url(self):
        worker = SQSWorker(queue_url=None, client=MagicMock())
        with pytest.raises(RuntimeError, match="queue_url"):
            worker.poll_once()

    def test_successful_handler_deletes_message(self):
        client = MagicMock()
        client.receive_message.return_value = {"Messages": [_sqs_message(payload={"x": 1})]}
        registry = HandlerRegistry()
        handler = MagicMock()
        registry.register("job.a", handler)

        worker = SQSWorker(queue_url="https://sqs.example/q", client=client, registry=registry)
        processed = worker.poll_once()

        handler.assert_called_once_with({"x": 1})
        client.delete_message.assert_called_once_with(QueueUrl="https://sqs.example/q", ReceiptHandle="rh-1")
        assert processed == 1

    def test_malformed_message_is_discarded(self):
        client = MagicMock()
        client.receive_message.return_value = {"Messages": [_sqs_message(body_override="not json")]}
        worker = SQSWorker(queue_url="https://sqs.example/q", client=client, registry=HandlerRegistry())

        processed = worker.poll_once()

        client.delete_message.assert_called_once()
        assert processed == 0

    def test_handler_failure_leaves_message_for_redrive(self):
        client = MagicMock()
        client.receive_message.return_value = {"Messages": [_sqs_message()]}
        registry = HandlerRegistry()
        registry.register("job.a", MagicMock(side_effect=RuntimeError("boom")))

        worker = SQSWorker(queue_url="https://sqs.example/q", client=client, registry=registry)
        processed = worker.poll_once()

        client.delete_message.assert_not_called()
        assert processed == 0

    def test_no_messages_returns_zero(self):
        client = MagicMock()
        client.receive_message.return_value = {}
        worker = SQSWorker(queue_url="https://sqs.example/q", client=client, registry=HandlerRegistry())

        assert worker.poll_once() == 0


# ──────────────────────────────────────────────────────────────────────────────
# SQSWorker.run_forever backoff
# ──────────────────────────────────────────────────────────────────────────────

class TestRunForeverBackoff:
    def test_backoff_grows_on_empty_polls_and_resets_on_success(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("job_queue.worker.time.sleep", lambda seconds: sleeps.append(seconds))
        monkeypatch.setattr("job_queue.worker.random.uniform", lambda a, b: 0.0)

        worker = SQSWorker(queue_url="https://sqs.example/q", client=MagicMock(), min_backoff_seconds=1.0, max_backoff_seconds=8.0)
        # empty, empty, non-empty, empty — then stop
        poll_results = iter([0, 0, 1, 0])
        worker.poll_once = MagicMock(side_effect=lambda: next(poll_results))

        counter = {"n": 0}

        def should_continue():
            counter["n"] += 1
            return counter["n"] <= 4

        worker.run_forever(should_continue)

        # two empty polls before the success: backoff 1.0 -> 2.0
        # one empty poll after the reset: backoff back to 1.0 (min)
        assert sleeps == [1.0, 2.0, 1.0]

    def test_backoff_caps_at_max(self, monkeypatch):
        monkeypatch.setattr("job_queue.worker.time.sleep", lambda seconds: None)
        monkeypatch.setattr("job_queue.worker.random.uniform", lambda a, b: 0.0)

        worker = SQSWorker(queue_url="https://sqs.example/q", client=MagicMock(), min_backoff_seconds=1.0, max_backoff_seconds=3.0)
        worker.poll_once = MagicMock(return_value=0)

        counter = {"n": 0}

        def should_continue():
            counter["n"] += 1
            return counter["n"] <= 5

        worker.run_forever(should_continue)

        assert worker._backoff == 3.0
