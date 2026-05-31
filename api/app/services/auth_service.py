"""Auth — temporary, admin-provisioned (LLD §12, FR4.6).

No self-serve signup: an admin calls `provision_user` (guarded by `X-Admin-Key`)
and shares the one-time credentials out of band. Login exchanges them for a bearer
token backed by a `sessions` row.

This module is deliberately **isolated** — swap it for a real auth flow later
without touching product code. Nothing here knows about proformas or interviews.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, User

SESSION_TTL = timedelta(days=7)
_PASSWORD_BYTES = 12  # secrets.token_urlsafe length hint
_TOKEN_BYTES = 32


def _slug(label: str | None) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (label or "user").lower()).strip("-")
    return base or "user"


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


async def provision_user(session: AsyncSession, label: str | None = None) -> dict:
    """Create a user with a generated password; return creds **once** (plaintext)."""
    password = secrets.token_urlsafe(_PASSWORD_BYTES)
    base = _slug(label)
    # Retry on the rare username collision (username is UNIQUE).
    for _ in range(5):
        username = f"{base}-{secrets.token_hex(3)}"
        exists = (
            await session.execute(select(User.id).where(User.username == username))
        ).first()
        if exists is None:
            break
    else:
        raise RuntimeError("could not allocate a unique username")

    user = User(username=username, password_hash=_hash_password(password))
    session.add(user)
    await session.commit()
    return {"username": username, "password": password}


async def login(session: AsyncSession, username: str, password: str) -> dict | None:
    """Verify credentials; on success mint a bearer token. None on failure."""
    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None or not _verify_password(password, user.password_hash):
        return None

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    session.add(Session(token=token, user_id=user.id, expires_at=expires_at))
    await session.commit()
    return {"token": token, "expires_at": expires_at}


async def user_for_token(session: AsyncSession, token: str) -> User | None:
    """Resolve a non-expired bearer token to its user (None if invalid/expired)."""
    now = datetime.now(timezone.utc)
    row = (
        await session.execute(
            select(User)
            .join(Session, Session.user_id == User.id)
            .where(Session.token == token, Session.expires_at > now)
        )
    ).scalar_one_or_none()
    return row
