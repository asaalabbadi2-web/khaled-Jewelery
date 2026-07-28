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
from yasargold_commerce.routers import catalog, internal, orders, payments, pos_claims, reservations, shipments

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


def _build_refund_gateway():
    """Return the configured RefundGateway. No try/except — no silent fallback.

    Production: MoyasarRefundGateway when MOYASAR_SECRET_KEY is set.
    Dev/test:   LogRefundGateway with a loud WARNING.

    The absence of a try/except is deliberate: if MoyasarRefundGateway() raises
    (malformed key, config error), the error propagates and the app refuses to
    start. Silent downgrade to LogRefundGateway is more dangerous than a boot
    failure — a refund silently dropped is invisible; a boot failure is not.

    Set COMMERCE_ENV=production to enforce this at startup via
    _check_production_refund_gateway_config().
    """
    from yasargold_commerce.infra.log_refund_gateway import LogRefundGateway
    from yasargold_commerce.infra.moyasar_refund_gateway import MoyasarRefundGateway

    key = os.environ.get("MOYASAR_SECRET_KEY", "")
    if key:
        return MoyasarRefundGateway(api_key=key)

    _log.warning(
        "refund_gateway: MOYASAR_SECRET_KEY not set — using LogRefundGateway. "
        "Refunds will be LOGGED ONLY, not actually issued to Moyasar. "
        "Acceptable in development/test. NOT acceptable in production "
        "(set COMMERCE_ENV=production to enforce this at startup)."
    )
    return LogRefundGateway()


def _check_production_refund_gateway_config(gateway: object) -> None:
    """Raise if the refund gateway is unsafe for production.

    Law 7 — Financial Adapter Law: No Financial Adapter may silently downgrade
    in Production. Any NonProductionFinancialAdapter subclass logs or stubs
    financial operations — real transactions are silently skipped.
    Misconfiguration must fail at boot, not at the first customer refund.

    Covers all NonProductionFinancialAdapter subclasses — not just LogRefundGateway:
      • MOYASAR_SECRET_KEY absent → _build_refund_gateway() returns LogRefundGateway
      • Any future LogPaymentGateway / LogPayoutAdapter inheriting the marker
      • Any NonProductionFinancialAdapter wired explicitly in the call graph

    The isinstance check on the marker is the sole enforcement mechanism —
    no class-name whack-a-mole.
    """
    from yasargold_commerce.infra.financial_adapter import NonProductionFinancialAdapter

    if os.environ.get("COMMERCE_ENV") != "production":
        return

    if isinstance(gateway, NonProductionFinancialAdapter):
        raise RuntimeError(
            f"{type(gateway).__name__} is a NonProductionFinancialAdapter — "
            "not permitted when COMMERCE_ENV=production. "
            "This class of adapter logs or stubs financial operations; real transactions "
            "are silently skipped. "
            "Fix: configure a production-ready gateway (e.g. set MOYASAR_SECRET_KEY). "
            "Law 7 (security-overview.md): No Financial Adapter may silently downgrade "
            "in Production."
        )


# Module-level singleton — built once at import time; validated in lifespan.
# Tests that need a specific gateway bypass this by calling _build_refund_gateway()
# directly with monkeypatched env vars.
_REFUND_GATEWAY = _build_refund_gateway()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _check_production_redis_config()
    _check_production_refund_gateway_config(_REFUND_GATEWAY)
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
app.include_router(pos_claims.router)
app.include_router(internal.router)

# Prometheus metrics endpoint — scraped by Prometheus at /metrics
app.mount("/metrics", make_asgi_app())


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}
