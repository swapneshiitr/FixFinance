"""Interview routers (LLD §13) — chat over a stateless HTTP API, stateful agent.

  POST /sessions                 -> {session_id, assistant_message}
  POST /sessions/{id}/messages   -> {assistant_message, coverage_pct, phase}
  GET  /sessions/{id}            -> {transcript, coverage, phase}

`thread_id = interview_session_id`: each call invokes the compiled graph, which
resumes from the Postgres checkpoint. Pausing is just returning to the user.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import coverage as cov
from app.agent.graph import get_graph
from app.agent.state import initial_state
from app.db import get_session
from app.models import InterviewSession, User
from app.routers.deps import current_user
from app.services import proforma_service

router = APIRouter(prefix="/sessions")


class MessageRequest(BaseModel):
    text: str


def _config(session_id: uuid.UUID) -> dict:
    return {"configurable": {"thread_id": str(session_id)}}


def _assistant_reply(messages: list) -> str:
    """The trailing run of assistant messages, joined (greet+question on start)."""
    out = []
    for m in reversed(messages):
        if getattr(m, "type", "") != "ai":
            break
        out.append(m.content)
    return "\n\n".join(reversed(out))


def _serialize_transcript(messages: list) -> list[dict]:
    return [
        {"role": "user" if getattr(m, "type", "") == "human" else "assistant", "content": m.content}
        for m in messages
    ]


async def _load_owned_session(
    session_id: uuid.UUID, user: User, db: AsyncSession
) -> InterviewSession:
    row = (
        await db.execute(select(InterviewSession).where(InterviewSession.id == session_id))
    ).scalar_one_or_none()
    if row is None or row.user_id != user.id:
        # Same response for not-found and not-owned: don't leak which sessions exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return row


@router.post("")
async def start_session(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> dict:
    row = InterviewSession(user_id=user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)

    state = await get_graph().ainvoke(initial_state(), _config(row.id))
    row.phase = state.get("phase", row.phase)
    await db.commit()
    return {"session_id": str(row.id), "assistant_message": _assistant_reply(state["messages"])}


@router.post("/{session_id}/messages")
async def post_message(
    session_id: uuid.UUID,
    body: MessageRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    row = await _load_owned_session(session_id, user, db)

    state = await get_graph().ainvoke(
        {"messages": [HumanMessage(content=body.text)]}, _config(session_id)
    )
    row.phase = state.get("phase", row.phase)
    await db.commit()
    return {
        "assistant_message": _assistant_reply(state["messages"]),
        "coverage_pct": cov.coverage_pct(state.get("coverage", {})),
        "phase": state.get("phase"),
    }


@router.post("/{session_id}/build-proforma")
async def build_proforma(
    session_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Snapshot the interview's current draft as proforma version 1 (LLD §9.1)."""
    await _load_owned_session(session_id, user, db)
    snapshot = await get_graph().aget_state(_config(session_id))
    draft = (snapshot.values or {}).get("draft", {})
    if not draft:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no interview draft to build from yet")
    row = await proforma_service.finalize(db, user.id, draft)
    return {"proforma_id": str(row.id), "version": row.version}


@router.get("/{session_id}")
async def get_session_state(
    session_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await _load_owned_session(session_id, user, db)

    snapshot = await get_graph().aget_state(_config(session_id))
    values = snapshot.values or {}
    return {
        "transcript": _serialize_transcript(values.get("messages", [])),
        "coverage": values.get("coverage", {}),
        "phase": values.get("phase"),
    }
