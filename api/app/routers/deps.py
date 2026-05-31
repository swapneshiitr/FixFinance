"""Shared router dependencies — the auth guards (LLD §12, §13).

`current_user` resolves the `Authorization: Bearer <token>` header to a user;
`require_admin` checks the `X-Admin-Key` header against the configured key. Both
raise 401/403 on failure.
"""
from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import User
from app.services import auth_service


async def current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization[7:].strip()
    user = await auth_service.user_for_token(session, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    return user


async def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    # Constant-time compare so a wrong key can't be timed character-by-character.
    if not x_admin_key or not secrets.compare_digest(x_admin_key, settings.admin_key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid admin key")
