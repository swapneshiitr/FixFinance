"""FastAPI application entrypoint (LLD §1).

Mounts the auth + interview routers (Day-1) over the /health probe. Proforma and
report routers are added Day-2. All errors are normalized to {error:{code,message}}
per the API contract (§13).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent.graph import close_agent, init_agent
from app.db import engine, health
from app.routers import auth, interview, proforma, report

log = logging.getLogger("fixfinance.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Compile the interview graph + create the checkpointer tables (idempotent).
    # Best-effort: if it fails, keep the app up so /health is reachable and the
    # failure is visible in logs (the interview router degrades with a clear error).
    try:
        await init_agent()
    except Exception:  # noqa: BLE001
        log.error("agent initialization failed at startup", exc_info=True)
    # Index the principles KB into pgvector (idempotent; best-effort).
    try:
        from app.rag.indexer import index_principles

        n = await index_principles()
        log.info("RAG: indexed %d principles", n)
    except Exception:  # noqa: BLE001
        log.error("RAG indexing failed at startup", exc_info=True)
    yield
    await close_agent()
    await engine.dispose()


app = FastAPI(title="FixFinance API", version="0.1.0", lifespan=lifespan)

# The Next.js web app (browser) calls the API cross-origin during local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Normalize HTTP errors to {error:{code, message}} (§13)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"code": 422, "message": "validation error", "detail": exc.errors()}},
    )


app.include_router(auth.router, tags=["auth"])
app.include_router(interview.router, tags=["interview"])
app.include_router(proforma.router, tags=["proforma"])
app.include_router(report.router, tags=["report"])


@app.get("/health")
async def health_check() -> dict:
    """Liveness + readiness: DB reachable, pgvector present, schema applied."""
    status = await health()
    status["status"] = "ok" if status["pgvector"] and status["public_tables"] > 0 else "degraded"
    return status
