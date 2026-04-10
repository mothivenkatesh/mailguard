"""FastAPI REST endpoint for mailguard.

Run:  uvicorn mailguard.api:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /health                    → liveness
    POST /validate                  → single email
    POST /validate/bulk             → list of emails
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field

from mailguard import __version__
from mailguard.core import validate, validate_bulk

app = FastAPI(
    title="mailguard API",
    version=__version__,
    description="Async bulk email validator with layered deliverability scoring.",
)


class ValidateRequest(BaseModel):
    email: str
    check_smtp: bool = False
    check_catchall: bool = False
    timeout: float = 10.0


class BulkRequest(BaseModel):
    emails: list[str] = Field(..., max_length=10_000)
    concurrency: int = 50
    check_smtp: bool = False
    check_catchall: bool = False
    timeout: float = 10.0


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": __version__}


@app.post("/validate")
async def validate_one(req: ValidateRequest) -> dict[str, Any]:
    result = await validate(
        req.email,
        check_smtp=req.check_smtp,
        check_catchall=req.check_catchall,
        timeout=req.timeout,
    )
    return result.to_dict()


@app.post("/validate/bulk")
async def validate_many(req: BulkRequest) -> dict[str, Any]:
    if not req.emails:
        raise HTTPException(400, "emails list is empty")
    results = await validate_bulk(
        req.emails,
        concurrency=req.concurrency,
        check_smtp=req.check_smtp,
        check_catchall=req.check_catchall,
        timeout=req.timeout,
    )
    summary = {"deliverable": 0, "risky": 0, "undeliverable": 0, "unknown": 0}
    for r in results:
        summary[r.verdict] = summary.get(r.verdict, 0) + 1
    return {
        "total": len(results),
        "summary": summary,
        "results": [r.to_dict() for r in results],
    }
