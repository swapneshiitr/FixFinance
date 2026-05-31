"""Proforma routers (LLD §13).

  GET   /proformas/{id}   -> {version, data, derived}   (latest version)
  PATCH /proformas/{id}   {field: value, ...} -> {version, data, derived}  (new version)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.routers.deps import current_user
from app.services import proforma_service

router = APIRouter(prefix="/proformas")


def _view(row) -> dict:
    return {"version": row.version, "data": row.data, "derived": row.derived}


@router.get("/{proforma_id}")
async def get_proforma(
    proforma_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    row = await proforma_service.get_latest(db, proforma_id, user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proforma not found")
    return _view(row)


@router.patch("/{proforma_id}")
async def patch_proforma(
    proforma_id: uuid.UUID,
    edits: dict = Body(..., description="{field_path: value, ...}"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        row = await proforma_service.apply_edit(db, proforma_id, user.id, edits)
    except proforma_service.ProformaNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proforma not found")
    except proforma_service.InvalidEdit as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid edit: {e}")
    return _view(row)
