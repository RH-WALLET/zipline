"""FastAPI dependencies: DB session per request, admin bearer auth."""

from __future__ import annotations

import secrets
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from zipline_engine.config import Settings, get_settings
from zipline_engine.db.base import get_sessionmaker


def db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def settings() -> Settings:
    return get_settings()


def require_admin(
    authorization: str | None = Header(default=None), cfg: Settings = Depends(settings)
) -> None:
    token = cfg.admin_token.get_secret_value()
    if not token:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "admin endpoints are disabled: ADMIN_TOKEN is not set"
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    presented = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(presented, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid admin token")
