"""Tracing (LLD §6.1, SG4).

One `llm_calls` row per gateway call: prompt name+version, model, token counts,
latency, outcome, retries, session. This table powers the observability dashboard
and the eval/cost views (§14).

Tracing is best-effort: a failure to persist a trace must never fail the user's
request. We log and move on — losing a trace row is an observability gap, not a
product outage.
"""
from __future__ import annotations

import logging
import uuid

from app.db import SessionLocal
from app.models import LLMCall

log = logging.getLogger("fixfinance.tracing")


async def trace(
    *,
    prompt_name: str,
    prompt_version: str,
    model: str,
    outcome: str,  # success | repaired | validation_failed | error
    retries: int = 0,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    latency_ms: int | None = None,
    session_id: str | uuid.UUID | None = None,
) -> None:
    sid: uuid.UUID | None = None
    if session_id is not None:
        sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))

    try:
        async with SessionLocal() as session:
            session.add(
                LLMCall(
                    prompt_name=prompt_name,
                    prompt_version=prompt_version,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    outcome=outcome,
                    retries=retries,
                    session_id=sid,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — observability must not break the request
        log.warning("failed to persist llm_calls trace", exc_info=True)
