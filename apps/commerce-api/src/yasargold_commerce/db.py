"""SQLAlchemy engine and session factory for the Commerce API.

Uses the same PostgreSQL database as the ERP (read-only access for catalog queries).
Session is request-scoped via FastAPI dependency injection.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    return url


def _make_engine():
    return create_engine(
        _database_url(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


# Lazy singletons — created on first request, not at import time.
_engine = None
_SessionLocal = None


def _get_session_factory():
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = _make_engine()
        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
    return _SessionLocal


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a DB session and closes it after the request."""
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()
