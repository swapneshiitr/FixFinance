"""SQLAlchemy ORM models — typed access to the relational tables (LLD §3).

The schema itself is owned by `api/db/schema.sql` (auto-run by the Postgres image
on first boot); these models do **not** create tables (`create_all` is never
called). They exist purely for typed reads/writes from the services and gateway,
and are kept faithful to the DDL.

The two RAG tables (`principles`, `principle_chunks`) carry a pgvector column and
are added in the Day-2 RAG step (§10) alongside the `pgvector` dependency — the
vector search there uses the `<=>` operator and is mapped then, not now.
LangGraph's checkpoint tables are created/managed by `PostgresSaver`, not here.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --- Auth (temporary, admin-provisioned; FR4.6) ----------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'admin'"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class Session(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


# --- Interview --------------------------------------------------------------


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # greeting | interviewing | confirming | done
    phase: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'greeting'"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


# --- Proformas (append-only versioned; FR2.5) ------------------------------


class Proforma(Base):
    __tablename__ = "proformas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # stable logical id
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(String, nullable=False)  # ai_extracted | user_edited
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)  # validated against Proforma schema (§4)
    derived: Mapped[dict] = mapped_column(JSONB, nullable=False)  # computed metrics (§9.3)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


# --- Reports (async) --------------------------------------------------------


class ReportJob(Base):
    __tablename__ = "report_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    proforma_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    proforma_ver: Mapped[int] = mapped_column(Integer, nullable=False)
    # pending | running | done | failed
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'pending'"))
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("report_jobs.id"), nullable=False
    )
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)  # ReportContent schema (§11.4)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


# --- Observability (SG4) ----------------------------------------------------


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)  # BIGSERIAL
    prompt_name: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # success | repaired | validation_failed | error
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = [
    "Base",
    "User",
    "Session",
    "InterviewSession",
    "Proforma",
    "ReportJob",
    "Report",
    "LLMCall",
]
