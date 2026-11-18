"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

HTTP front for runner.py. One endpoint, bearer-token auth, no database.

POST /check  {"files": {path: content}, "workdir": "aws",
              "edited_path": "aws/main.tf", "original": "<file before edit>"}
          -> runner.CheckResult as JSON (200 even when the check fails;
             4xx only for a bad request or bad token)
GET  /healthz
"""

import asyncio
import hmac
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from runner import RequestError, check

app = FastAPI(title="terraform-runner", docs_url=None, redoc_url=None)
_CONCURRENCY = asyncio.Semaphore(int(os.environ.get("TERRAFORM_RUNNER_CONCURRENCY", "2")))


class CheckRequest(BaseModel):
    files: dict[str, str]
    workdir: str = "."
    edited_path: str
    original: str = ""


def _authorize(authorization: str) -> None:
    token = os.environ.get("TERRAFORM_RUNNER_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="TERRAFORM_RUNNER_TOKEN not configured")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/check")
async def run_check(body: CheckRequest, authorization: str = Header("")) -> dict:
    _authorize(authorization)
    async with _CONCURRENCY:
        try:
            result = await asyncio.to_thread(check, body.files, body.workdir, body.edited_path, body.original)
        except RequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_dict()
