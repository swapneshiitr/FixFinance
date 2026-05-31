"""Auth + admin routers (LLD §13).

  POST /admin/users  (X-Admin-Key) -> {username, password}  (returned ONCE)
  POST /auth/login                 -> {token, expires_at}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.routers.deps import require_admin
from app.services import auth_service

router = APIRouter()


class ProvisionRequest(BaseModel):
    label: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/admin/users", dependencies=[Depends(require_admin)])
async def provision_user(body: ProvisionRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Admin-provision a user. The plaintext password is shown only in this response."""
    return await auth_service.provision_user(session, label=body.label)


@router.post("/auth/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)) -> dict:
    creds = await auth_service.login(session, body.username, body.password)
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    return creds
