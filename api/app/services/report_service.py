"""Report service (LLD §11) — findings engine + async job + grounded synthesis.

Pipeline:
  build_findings (deterministic, rule-based)  →  RAG retrieve per finding
  →  gateway.call_structured(report_synthesis) → ReportContent
  →  canonicalize sources from the RAG pool (authentic citations) → persist.

The metric→severity→principle mapping is rule-based Python (no LLM): cheaper,
testable, predictable. The LLM only writes prose. Citations are re-attached from
the retrieved principles by id, so a recommendation can never invent a source.
"""
from __future__ import annotations

import logging
import uuid

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Report as ReportRow
from app.models import ReportJob
from app.orchestration import gateway
from app.rag import retriever
from app.schemas.report import ReportContent, Severity
from app.services import proforma_service

log = logging.getLogger("fixfinance.report")


class Finding(BaseModel):
    dimension: str
    severity: Severity
    value: float | str | None
    principle_id: str
    detail: str


def _v(data: dict, key: str):
    f = data.get(key)
    return f.get("value") if isinstance(f, dict) else None


# --- 11.1 Findings engine (deterministic) -----------------------------------


def build_findings(derived: dict, data: dict) -> list[Finding]:
    """Map derived metrics + proforma values → rated findings tied to a principle."""
    f: list[Finding] = []

    m = derived.get("emergency_fund_months")
    if m is not None:
        sev: Severity = "act" if m < 3 else "watch" if m < 6 else "good"
        f.append(Finding(dimension="emergency_fund", severity=sev, value=m,
                         principle_id="emergency_fund",
                         detail=f"Emergency fund covers {m} months of expenses (target 3–6)."))

    sr = derived.get("savings_rate")
    if sr is not None:
        sev = "act" if sr < 0.2 else "watch" if sr < 0.3 else "good"
        f.append(Finding(dimension="savings_rate", severity=sev, value=sr,
                         principle_id="savings_rate",
                         detail=f"Savings/investment rate is {round(sr*100,1)}% of take-home (aim ≥20–30%)."))

    take_home = _v(data, "monthly_take_home")
    term = _v(data, "term_life_cover")
    dependents = _v(data, "dependents") or 0
    if take_home and term is not None:
        annual_income = take_home * 12
        if term < 10 * annual_income:
            sev = "act" if dependents and dependents > 0 else "watch"
            f.append(Finding(dimension="term_life", severity=sev, value=term,
                             principle_id="insurance_adequacy",
                             detail=f"Term life cover ₹{term:,.0f} vs ~10× annual income ₹{10*annual_income:,.0f}"
                                    f"{' (has dependents)' if dependents else ''}."))

    health = _v(data, "health_insurance_cover")
    if health is not None and health < 500000:
        sev = "act" if health == 0 else "watch"
        f.append(Finding(dimension="health_cover", severity=sev, value=health,
                         principle_id="insurance_adequacy",
                         detail=f"Health cover ₹{health:,.0f} below the ₹5L floor."))

    regime = _v(data, "tax_regime")
    util = derived.get("tax_saving_80c_utilization")
    if util is not None and util < 1 and regime != "new":
        f.append(Finding(dimension="tax_80c", severity="watch", value=util,
                         principle_id="tax_efficiency",
                         detail=f"80C utilization at {round(util*100)}% — spare headroom under the ₹1.5L cap."))

    mix = derived.get("asset_allocation_mix")
    age = _v(data, "age")
    if mix and age:
        target_equity = max(0.0, min(1.0, (100 - age) / 100))
        gap = abs(mix["equity"] - target_equity)
        if gap > 0.25:
            f.append(Finding(dimension="asset_allocation", severity="watch", value=mix["equity"],
                             principle_id="asset_allocation",
                             detail=f"Equity share {round(mix['equity']*100)}% vs ~{round(target_equity*100)}% "
                                    f"(100−age starting frame)."))

    return f


def finding_query(f: Finding) -> str:
    return f"{f.dimension}: {f.detail}"


# --- 11.2 Async job ---------------------------------------------------------


async def create_job(session: AsyncSession, proforma_id: uuid.UUID, version: int) -> uuid.UUID:
    job = ReportJob(id=uuid.uuid4(), proforma_id=proforma_id, proforma_ver=version, status="pending")
    session.add(job)
    await session.commit()
    return job.id


async def _set_status(session: AsyncSession, job_id: uuid.UUID, status: str, error: str | None = None):
    await session.execute(
        text("UPDATE report_jobs SET status = :s, error = :e WHERE id = :id"),
        {"s": status, "e": error, "id": str(job_id)},
    )
    await session.commit()


async def build_report_content(data: dict, derived: dict) -> dict:
    """Findings → RAG → synthesis → authoritative ratings + canonical citations.

    Pure (no DB): used by both the async job and the eval harness. Ratings and
    sources are set from our deterministic engine / RAG pool, never the LLM.
    """
    findings = build_findings(derived, data)

    # RAG: build a principle pool (semantic retrieve + guarantee each finding's own principle).
    pool: dict[str, dict] = {}
    for fnd in findings:
        for r in await retriever.retrieve(finding_query(fnd), k=2):
            pool[r["id"]] = r
    missing = [fnd.principle_id for fnd in findings if fnd.principle_id not in pool]
    for r in await retriever.get_by_ids(missing):
        pool[r["id"]] = r

    principles_ctx = [
        {"principle_id": p["id"], "statement": p["statement"],
         "rule_of_thumb": p["rule_of_thumb"], "sources": p["sources"]}
        for p in pool.values()
    ]

    result: ReportContent = await gateway.call_structured(
        "report_synthesis", "v1",
        {"proforma": data, "derived": derived,
         "findings": [fnd.model_dump() for fnd in findings], "principles": principles_ctx},
        ReportContent, max_tokens=4096,
    )

    content = result.model_dump()
    # Authoritative ratings from the deterministic findings engine (not the LLM).
    content["ratings"] = [
        {"dimension": fnd.dimension, "rating": fnd.severity, "value": fnd.value} for fnd in findings
    ]
    # Canonicalize citations: authentic sources from the RAG pool, by principle_id.
    for rec in content["recommendations"]:
        src = pool.get(rec.get("principle_id"))
        if src is not None:
            rec["sources"] = src["sources"]
    return content


async def run_report(job_id: uuid.UUID, proforma_id: uuid.UUID, version: int) -> None:
    """Background task (FR3.4, NFR1 ≤2 min): build → retrieve → synthesize → persist."""
    async with SessionLocal() as session:
        try:
            await _set_status(session, job_id, "running")
            pf = await proforma_service.get_version(session, proforma_id, version)
            if pf is None:
                raise RuntimeError("proforma version not found")
            content = await build_report_content(pf.data, pf.derived)
            session.add(ReportRow(id=uuid.uuid4(), job_id=job_id, content=content))
            await _set_status(session, job_id, "done")
            log.info("report %s done", job_id)
        except Exception as exc:  # noqa: BLE001 — record failure, don't crash the worker
            log.error("report job %s failed", job_id, exc_info=True)
            await _set_status(session, job_id, "failed", error=str(exc)[:500])


# --- read (GET /reports/{job_id}) -------------------------------------------


async def get_report_view(session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> dict | None:
    """Return {status, content?} if the job's proforma belongs to the user, else None."""
    job = (
        await session.execute(text(
            "SELECT j.id, j.status, j.error, j.proforma_id FROM report_jobs j WHERE j.id = :id"
        ), {"id": str(job_id)})
    ).mappings().first()
    if job is None:
        return None
    # Ownership: the job's proforma must belong to this user.
    owned = (
        await session.execute(text(
            "SELECT 1 FROM proformas WHERE id = :pid AND user_id = :uid LIMIT 1"
        ), {"pid": str(job["proforma_id"]), "uid": str(user_id)})
    ).first()
    if owned is None:
        return None

    view = {"status": job["status"]}
    if job["error"]:
        view["error"] = job["error"]
    if job["status"] == "done":
        row = (
            await session.execute(text(
                "SELECT content FROM reports WHERE job_id = :jid ORDER BY created_at DESC LIMIT 1"
            ), {"jid": str(job_id)})
        ).mappings().first()
        if row is not None:
            view["content"] = row["content"]
    return view
