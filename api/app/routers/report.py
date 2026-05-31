"""Report routers (LLD §11.2, §13).

  POST /proformas/{id}/report  -> {job_id}     (schedules an async BackgroundTask)
  GET  /reports/{job_id}       -> {status, content?}   (frontend polls until done)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.routers.deps import current_user
from app.services import proforma_service, report_service

router = APIRouter()


@router.post("/proformas/{proforma_id}/report")
async def request_report(
    proforma_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Create a report job and run synthesis in the background (NFR1: ≤2 min)."""
    pf = await proforma_service.get_latest(db, proforma_id, user.id)
    if pf is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proforma not found")
    job_id = await report_service.create_job(db, proforma_id, pf.version)
    background_tasks.add_task(report_service.run_report, job_id, proforma_id, pf.version)
    return {"job_id": str(job_id)}


@router.get("/reports/{job_id}")
async def get_report(
    job_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    view = await report_service.get_report_view(db, job_id, user.id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report job not found")
    return view
