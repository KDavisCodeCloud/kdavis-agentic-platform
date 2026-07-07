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
document_store — concrete DocumentStorage backends for
finance.accounting.document_organizer (structural typing — no import of
that module needed here, keeping the dependency direction one-way).

LocalFileSystemStore is stdlib-only and fully functional — use it for
local runs and tests. S3Store uses boto3, already a platform dependency
(requirements.txt), imported lazily so this module has no import-time
dependency on it. GoogleDriveStore is a stub: the googleapiclient package
is not a platform dependency yet, so instantiating it raises a clear
error until that's added with explicit instruction.
"""

import os
from pathlib import Path


class LocalFileSystemStore:
    """Writes documents under a local base directory, mirroring the
    IRS folder structure exactly as document_organizer resolves it."""

    def __init__(self, base_dir: str | Path):
        self._base_dir = Path(base_dir)

    def save(self, relative_path: str, content: bytes) -> str:
        target = self._base_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return str(target.resolve())


class S3Store:
    """Writes documents to an S3 bucket under an optional key prefix.
    Credentials are resolved by boto3's standard chain (env vars, IAM
    role, ~/.aws/credentials) — never hardcoded here."""

    def __init__(self, bucket: str, prefix: str = "", client=None):
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for S3Store but is not installed.") from exc
        self._client = boto3.client("s3")
        return self._client

    def save(self, relative_path: str, content: bytes) -> str:
        key = f"{self._prefix}/{relative_path}" if self._prefix else relative_path
        client = self._get_client()
        client.put_object(Bucket=self._bucket, Key=key, Body=content)
        return f"s3://{self._bucket}/{key}"


class GoogleDriveStore:
    """Stub — googleapiclient is not a declared platform dependency.
    Do not add it without explicit instruction (see CLAUDE.md Stack —
    Never Deviate). Raises until that dependency and OAuth/service
    account wiring are added in an explicit follow-up session."""

    def __init__(self, root_folder_id: str, credentials=None):
        self._root_folder_id = root_folder_id
        self._credentials = credentials

    def save(self, relative_path: str, content: bytes) -> str:
        raise NotImplementedError(
            "GoogleDriveStore.save is not implemented. Requires adding "
            "google-api-python-client to requirements.txt and wiring service "
            "account credentials — needs explicit instruction before adding "
            "a new dependency. Use LocalFileSystemStore or S3Store for now."
        )


def default_store() -> LocalFileSystemStore:
    """Local filesystem store rooted at FINANCE_DOCS_ROOT env var, or
    ./finance_documents if unset. Swap for S3Store/GoogleDriveStore in
    production via explicit configuration, not by editing this default."""
    return LocalFileSystemStore(os.getenv("FINANCE_DOCS_ROOT", "./finance_documents"))
