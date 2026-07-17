"""Commerce API — FastAPI application entry point.

Physical boundary from the ERP (Flask):
- Different framework  → different process, different port
- import-linter CI check: yasargold_domain must not import flask/fastapi/redis
- Reads from the same PostgreSQL DB; all writes go through ERP service layer
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import redis as _redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from yasargold_commerce.rate_limiter import FakeRedis, RateLimitMiddleware
from yasargold_commerce.routers import catalog, orders, payments, reservations, shipments

_log = logging.getLogger(__name__)


def _check_production_redis_config() -> None:
    """Raise if REDIS_URL is absent in production — fails startup, not per-request.

    Consistent with SEC-001: unconfigured dependency → explicit error, not silent
    degradation. FakeRedis in production is fail-open: it is per-worker, resets on
    restart, and provides no cross-instance coordination — rate limiting would appear
    to work in metrics while being trivially bypassed in practice.

    Set COMMERCE_ENV=production in the deployment environment.
    Set REDIS_URL=redis://<host>:6379/0 (or Redis Cloud URL) alongside it.
    """
    if os.environ.get("COMMERCE_ENV") == "production" and not os.environ.get("REDIS_URL"):
        raise RuntimeError(
            "REDIS_URL is required when COMMERCE_ENV=production. "
            "Rate limiting with in-process FakeRedis is per-worker, resets on restart, "
            "and provides no cross-process protection — this violates the fail-safe "
            "principle established in ADR-017. Set REDIS_URL or do not start."
        )


def _build_redis():
    """Return a real Redis client when REDIS_URL is set, else FakeRedis.

    Acceptable environments for FakeRedis: development, test.
    Production requires REDIS_URL — see _check_production_redis_config().
    """
    url = os.environ.get("REDIS_URL", "")
    if url:
        return _redis.Redis.from_url(url, decode_responses=True)
    _log.warning(
        "rate_limiter: REDIS_URL not set — using in-process FakeRedis. "
        "Acceptable in development/test. NOT acceptable in production "
        "(set COMMERCE_ENV=production to enforce this at startup)."
    )
    return FakeRedis()


# Module-level singleton so tests can call _RATE_REDIS.reset() between runs.
_RATE_REDIS = _build_redis()

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _check_production_redis_config()
    yield


app = FastAPI(
    title="YasarGold Commerce API",
    version="0.1.0",
    description="Public-facing catalog and reservation API for the gold store",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=_lifespan,
)

app.add_middleware(RateLimitMiddleware, redis=_RATE_REDIS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production via ALLOWED_ORIGINS env var
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(catalog.router)
app.include_router(reservations.router)
app.include_router(payments.router)
app.include_router(orders.router)
app.include_router(shipments.router)

# Prometheus metrics endpoint — scraped by Prometheus at /metrics
app.mount("/metrics", make_asgi_app())


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}
