"""Rate limiting enforcement — Law 3 (ADR-017).

Fixed-window counter per (rate_class, client_id) stored in Redis.

Key design:
    Key:    rate:{rate_class}:{client_id}:{window_bucket}
    Bucket: int(time.time()) // window_seconds  — changes once per window.
    On each request:
        count = INCR key
        if count == 1: EXPIRE key window_seconds   (set TTL only on first hit)
        if count > limit: return 429

Rate limits (v1.4):

    rate_class          limit  window
    ─────────────────   ─────  ──────
    catalog-read         200    60 s
    reservation-write      5    60 s   ← spam prevention (INV-4 risk)
    payment-write          3   300 s   ← single-shot per session
    order-read            60    60 s
    webhook              100    60 s   ← separate from payment-write (Moyasar retries
                                         must not be throttled by the payment counter)
    admin-write           20    60 s
    ops                    ∞     —     ← never throttled

Client identity (v1.4):
    Trusted-hop extraction from X-Forwarded-For (configurable via TRUSTED_PROXY_HOPS).
    Default: 1 trusted proxy (our load balancer).

    With N trusted hops: ips[-N] is the real client IP (appended by our LB).
        ips[-1] = what our LB appended = trustworthy
        ips[:-1] = client-supplied, attacker-controlled = ignored

    With 0 trusted hops: XFF ignored; use request.client.host (direct connection).

    CGNAT caveat (v1.4 known limitation):
        Saudi mobile networks place many users behind shared IPs (CGNAT). A per-IP
        key of 5/min for reservation-write may block legitimate customers during
        peak hours. Mitigation path (v1.5): key = IP + guest session token (JWT sub
        when authenticated). Before any tightening, monitor 429 counter by rate_class
        to distinguish CGNAT false-positives from actual spam.

Redis interface:
    RedisClient is a structural protocol — any object with incr(key) and
    expire(key, seconds) satisfies it. Use FakeRedis in tests/dev and
    redis.Redis in production.

Production requirement:
    REDIS_URL must be set when COMMERCE_ENV=production. See main.py
    _check_production_redis_config() — the app refuses to start without it.
    FakeRedis is per-worker and resets on restart; it provides no cross-process
    protection and must never be used as a silent production fallback.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from yasargold_commerce.security import ROUTE_SECURITY

# ---------------------------------------------------------------------------
# Rate limit config
# ---------------------------------------------------------------------------

# (limit, window_seconds); limit=0 means unlimited
RATE_LIMITS: dict[str, tuple[int, int]] = {
    "catalog-read":      (200,  60),
    "reservation-write": (5,    60),
    "payment-write":     (3,   300),
    "order-read":        (60,   60),
    "webhook":           (100,  60),
    "admin-write":       (20,   60),
    # pos-write: ERP → Commerce machine-to-machine; one claim per sale.
    # A single showroom terminal makes at most a handful of claims per minute.
    # 60/min is generous; deliberate burst limit keeps the window tight.
    "pos-write":         (60,   60),
    "ops":               (0,     1),   # 0 = unlimited sentinel
}

# ---------------------------------------------------------------------------
# Trusted proxy hops for X-Forwarded-For
# ---------------------------------------------------------------------------

# Number of proxy hops between the client and this service that we trust.
# Set to 0 to ignore XFF entirely and use the direct connection IP.
# Set to 1 (default) when there is exactly one trusted load balancer in front.
# Read at import time; tests can patch yasargold_commerce.rate_limiter.TRUSTED_PROXY_HOPS.
TRUSTED_PROXY_HOPS: int = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))

# ---------------------------------------------------------------------------
# Redis protocol + test double
# ---------------------------------------------------------------------------

class RedisClient(Protocol):
    def incr(self, key: str) -> int: ...
    def expire(self, key: str, seconds: int) -> None: ...


@dataclass
class FakeRedis:
    """In-memory Redis substitute for tests and development.

    Uses (key → [count, expiry_epoch]) so expiry is honoured even within a
    single test that calls time.time() multiple times.

    NOT for production — see module docstring.
    """
    _store: dict[str, list[int]] = field(default_factory=dict)

    def incr(self, key: str) -> int:
        now = int(time.time())
        entry = self._store.get(key)
        if entry is not None and entry[1] > 0 and now >= entry[1]:
            del self._store[key]
            entry = None
        if key not in self._store:
            self._store[key] = [0, 0]
        self._store[key][0] += 1
        return self._store[key][0]

    def expire(self, key: str, seconds: int) -> None:
        if key in self._store:
            self._store[key][1] = int(time.time()) + seconds

    def reset(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# Path-template → regex compilation
# ---------------------------------------------------------------------------

_PARAM_RE = re.compile(r"\{[^}]+\}")


def _template_to_pattern(template: str) -> re.Pattern[str]:
    parts = _PARAM_RE.split(template)
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in parts) + "$")


def _build_route_index() -> list[tuple[str, re.Pattern[str], str]]:
    """Return [(http_method, path_pattern, rate_class), ...] from ROUTE_SECURITY."""
    return [
        (method.upper(), _template_to_pattern(template), entry.rate_class)
        for (method, template), entry in ROUTE_SECURITY.items()
    ]


# Pre-compiled at import time so middleware dispatch pays no compilation cost.
_ROUTE_INDEX: list[tuple[str, re.Pattern[str], str]] = _build_route_index()


def _resolve_rate_class(method: str, path: str) -> str | None:
    """Return the rate_class for this (method, path), or None if unregistered."""
    for m, pattern, rate_class in _ROUTE_INDEX:
        if m == method.upper() and pattern.match(path):
            return rate_class
    return None


# ---------------------------------------------------------------------------
# Client identity — XFF forge-resistant extraction
# ---------------------------------------------------------------------------

def _client_id(request: Request) -> str:
    """Extract client identity for rate limiting.

    With TRUSTED_PROXY_HOPS=N (default 1):
        X-Forwarded-For contains: client_ip, proxy1, ..., our_lb_appended_ip
        Our load balancer appends the actual connection IP as the last entry.
        With N=1: real client IP = ips[-1] (our LB appended this; it's trustworthy).
        Entries before ips[-N] are client-controlled and ignored.

    With TRUSTED_PROXY_HOPS=0:
        XFF is ignored entirely — use request.client.host (direct connection).
        Appropriate when no trusted proxy sits in front.

    Forge resistance: a client sending X-Forwarded-For: forged_ip, forged_ip2
        will still be counted by the IP our LB appended (ips[-1]), not by their
        forged entries. Different forge values on the same real IP stay throttled.
    """
    hops = TRUSTED_PROXY_HOPS
    if hops == 0:
        return request.client.host if request.client else "unknown"

    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        ips = [ip.strip() for ip in forwarded.split(",")]
        if len(ips) >= hops:
            return ips[-hops]
        # Fewer IPs in XFF than trusted hops — fall through to direct IP
        # (likely a request that bypassed the proxy; use most conservative identity)

    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Rate limit enforcement
# ---------------------------------------------------------------------------

def _rate_key(rate_class: str, client_id: str, window_seconds: int) -> str:
    bucket = int(time.time()) // window_seconds
    return f"rate:{rate_class}:{client_id}:{bucket}"


def check_rate_limit(
    rate_class: str,
    client_id: str,
    redis: RedisClient,
) -> bool:
    """Return True if request is within the limit, False if it should be throttled.

    Side effect: increments the counter in Redis.
    """
    limit, window = RATE_LIMITS.get(rate_class, (0, 1))
    if limit == 0:
        return True  # unlimited

    key = _rate_key(rate_class, client_id, window)
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, window)
    return count <= limit


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces ROUTE_SECURITY rate classes via Redis.

    Wire up in main.py:
        app.add_middleware(RateLimitMiddleware, redis=_RATE_REDIS)

    Routes with an unregistered (method, path) are allowed through — the
    CI scan (Law 1 / Law 3) ensures every registered route is classified,
    so an unregistered path is either the Prometheus /metrics mount or a 404.
    """

    def __init__(self, app, redis: RedisClient) -> None:
        super().__init__(app)
        self._redis = redis

    async def dispatch(self, request: Request, call_next):
        rate_class = _resolve_rate_class(request.method, request.url.path)
        if rate_class is None:
            return await call_next(request)

        cid = _client_id(request)
        if not check_rate_limit(rate_class, cid, self._redis):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests — rate limit exceeded"},
                headers={"Retry-After": str(RATE_LIMITS[rate_class][1])},
            )

        return await call_next(request)
