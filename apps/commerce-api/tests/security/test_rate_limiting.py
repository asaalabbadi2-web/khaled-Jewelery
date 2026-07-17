"""Law 3 enforcement proof tests — rate limiting (ADR-017).

ADR-017 Law 3: Deny-by-Default Rate Class.
    Rate classes are declared in ROUTE_SECURITY; enforcement was deferred to v1.4.
    This file proves enforcement is live.

Test structure:
    Unit tests (TestCheckRateLimit):
        Prove `check_rate_limit()` in isolation — no HTTP, no FastAPI.
        Faster, more exhaustive, covers edge cases.

    Middleware integration tests (TestRateLimitMiddleware):
        Prove the middleware fires correctly against a real FastAPI app.
        Covers: 429 response format, Retry-After header, unlimited classes.

    Route class tests (TestRouteClassEnforcement):
        Prove specific high-risk rate classes are enforced at the HTTP layer:
            reservation-write (5/min) — INV-4 spam prevention
            payment-write (3/5min)   — single-shot per session

    XFF forge resistance (TestXFFForgeResistance):
        Prove that a client cannot bypass rate limiting by forging X-Forwarded-For.
        With TRUSTED_PROXY_HOPS=1: ips[-1] (LB-appended) is used, not ips[0] (client-set).
        With TRUSTED_PROXY_HOPS=0: XFF is ignored; request.client.host is used.

    Webhook isolation (TestWebhookPaymentIsolation):
        Prove that the webhook route uses rate_class="webhook" (100/min), not
        "payment-write" (3/5min). Moyasar retries must not be blocked by the
        payment write counter — these are independent rate class buckets.

    Production config (TestProductionRedisConfig):
        Prove that missing REDIS_URL raises at startup when COMMERCE_ENV=production.
        Consistent with SEC-001: unconfigured dependency → explicit error, not silent pass.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yasargold_commerce.rate_limiter import (
    FakeRedis,
    RateLimitMiddleware,
    check_rate_limit,
    _resolve_rate_class,
)


# ---------------------------------------------------------------------------
# Unit: check_rate_limit
# ---------------------------------------------------------------------------

class TestCheckRateLimit:
    def test_first_request_is_allowed(self) -> None:
        redis = FakeRedis()
        assert check_rate_limit("reservation-write", "192.0.2.1", redis) is True

    def test_requests_within_limit_are_allowed(self) -> None:
        redis = FakeRedis()
        for _ in range(5):  # reservation-write limit is 5/min
            assert check_rate_limit("reservation-write", "192.0.2.1", redis) is True

    def test_request_over_limit_is_denied(self) -> None:
        redis = FakeRedis()
        for _ in range(5):
            check_rate_limit("reservation-write", "192.0.2.1", redis)
        # 6th request exceeds limit=5
        assert check_rate_limit("reservation-write", "192.0.2.1", redis) is False

    def test_unlimited_class_never_denied(self) -> None:
        redis = FakeRedis()
        for _ in range(1000):
            assert check_rate_limit("ops", "192.0.2.1", redis) is True

    def test_different_clients_have_independent_counters(self) -> None:
        redis = FakeRedis()
        for _ in range(5):
            check_rate_limit("reservation-write", "192.0.2.1", redis)
        # client 192.0.2.1 is now at limit; 192.0.2.2 should still be allowed
        assert check_rate_limit("reservation-write", "192.0.2.2", redis) is True

    def test_different_rate_classes_have_independent_counters(self) -> None:
        redis = FakeRedis()
        # Exhaust reservation-write for this client
        for _ in range(5):
            check_rate_limit("reservation-write", "192.0.2.1", redis)
        check_rate_limit("reservation-write", "192.0.2.1", redis)  # denied
        # Same client, different class — catalog-read limit=200, should pass
        assert check_rate_limit("catalog-read", "192.0.2.1", redis) is True

    def test_payment_write_limit_is_3_per_window(self) -> None:
        redis = FakeRedis()
        for _ in range(3):
            assert check_rate_limit("payment-write", "192.0.2.1", redis) is True
        assert check_rate_limit("payment-write", "192.0.2.1", redis) is False

    def test_window_expiry_resets_counter(self) -> None:
        """After the window expires, the counter resets and requests are allowed again."""
        redis = FakeRedis()
        # Force the bucket into the past so expire fires
        for _ in range(5):
            check_rate_limit("reservation-write", "192.0.2.1", redis)
        # 6th is denied
        assert check_rate_limit("reservation-write", "192.0.2.1", redis) is False

        # Advance time past the window (60 seconds for reservation-write)
        future = time.time() + 61
        with patch("yasargold_commerce.rate_limiter.time") as mock_time:
            mock_time.time.return_value = future
            # Counter has expired — should be allowed again
            result = check_rate_limit("reservation-write", "192.0.2.1", redis)
        assert result is True


# ---------------------------------------------------------------------------
# Unit: path resolution
# ---------------------------------------------------------------------------

class TestResolveRateClass:
    def test_exact_path_resolved(self) -> None:
        rc = _resolve_rate_class("GET", "/api/v1/catalog/products")
        assert rc == "catalog-read"

    def test_path_with_param_resolved(self) -> None:
        rc = _resolve_rate_class("GET", "/api/v1/catalog/products/gold-ring-001")
        assert rc == "catalog-read"

    def test_admin_path_resolved(self) -> None:
        rc = _resolve_rate_class("POST", "/api/v1/orders/ord_123/shipments")
        assert rc == "admin-write"

    def test_unknown_path_returns_none(self) -> None:
        rc = _resolve_rate_class("GET", "/unknown/path")
        assert rc is None

    def test_method_mismatch_returns_none(self) -> None:
        # /health is GET; DELETE /health is not registered
        rc = _resolve_rate_class("DELETE", "/health")
        assert rc is None


# ---------------------------------------------------------------------------
# Middleware integration: minimal FastAPI app
# ---------------------------------------------------------------------------

def _make_app(limit_override: dict[str, tuple[int, int]] | None = None) -> tuple[FastAPI, FakeRedis]:
    """Return a minimal FastAPI app with RateLimitMiddleware and a FakeRedis."""
    from fastapi import FastAPI as _FastAPI
    import yasargold_commerce.rate_limiter as _rl

    fake_redis = FakeRedis()
    mini_app = _FastAPI()

    # Patch RATE_LIMITS for the duration of this factory call if override given.
    # The middleware reads RATE_LIMITS at dispatch time (not at construction),
    # so we patch the module-level dict.
    if limit_override:
        original = dict(_rl.RATE_LIMITS)
        _rl.RATE_LIMITS.update(limit_override)

    mini_app.add_middleware(RateLimitMiddleware, redis=fake_redis)

    @mini_app.get("/api/v1/catalog/products")  # rate_class=catalog-read
    def products():
        return {"items": []}

    @mini_app.post("/api/v1/reservations")  # rate_class=reservation-write
    def reserve():
        return {"id": "res_001"}

    @mini_app.get("/health")  # rate_class=ops (unlimited)
    def health():
        return {"status": "ok"}

    if limit_override:
        # Restore after app is built (middleware already captured the module ref)
        _rl.RATE_LIMITS.clear()
        _rl.RATE_LIMITS.update(original)

    return mini_app, fake_redis


class TestRateLimitMiddleware:
    def test_429_returned_when_limit_exceeded(self) -> None:
        import yasargold_commerce.rate_limiter as _rl
        original = dict(_rl.RATE_LIMITS)
        _rl.RATE_LIMITS["reservation-write"] = (2, 60)

        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)

        try:
            client.post("/api/v1/reservations", json={})
            client.post("/api/v1/reservations", json={})
            resp = client.post("/api/v1/reservations", json={})
            assert resp.status_code == 429
        finally:
            _rl.RATE_LIMITS.clear()
            _rl.RATE_LIMITS.update(original)

    def test_429_response_has_retry_after_header(self) -> None:
        import yasargold_commerce.rate_limiter as _rl
        original = dict(_rl.RATE_LIMITS)
        _rl.RATE_LIMITS["reservation-write"] = (1, 60)

        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)

        try:
            client.post("/api/v1/reservations", json={})
            resp = client.post("/api/v1/reservations", json={})
            assert resp.status_code == 429
            assert "Retry-After" in resp.headers
            assert resp.headers["Retry-After"] == "60"
        finally:
            _rl.RATE_LIMITS.clear()
            _rl.RATE_LIMITS.update(original)

    def test_ops_endpoint_never_throttled(self) -> None:
        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)
        for _ in range(500):
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_requests_within_limit_all_pass(self) -> None:
        import yasargold_commerce.rate_limiter as _rl
        original = dict(_rl.RATE_LIMITS)
        _rl.RATE_LIMITS["reservation-write"] = (5, 60)

        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)

        try:
            for _ in range(5):
                resp = client.post("/api/v1/reservations", json={})
                assert resp.status_code != 429
        finally:
            _rl.RATE_LIMITS.clear()
            _rl.RATE_LIMITS.update(original)

    def test_unregistered_path_is_allowed_through(self) -> None:
        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)
        # /docs is not in ROUTE_SECURITY — middleware must not block it
        resp = client.get("/docs")
        assert resp.status_code != 429

    def test_x_forwarded_for_used_as_client_id(self) -> None:
        """Two real client IPs get independent rate limit counters.

        With TRUSTED_PROXY_HOPS=1 (default), XFF with a single entry means
        that entry IS the real client IP (no attacker-supplied prefix).
        """
        import yasargold_commerce.rate_limiter as _rl
        original_limits = dict(_rl.RATE_LIMITS)
        original_hops = _rl.TRUSTED_PROXY_HOPS
        _rl.RATE_LIMITS["reservation-write"] = (1, 60)
        _rl.TRUSTED_PROXY_HOPS = 1

        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)

        try:
            # XFF: "10.0.0.1" — 1 entry, TRUSTED_PROXY_HOPS=1 → ips[-1] = 10.0.0.1
            client.post("/api/v1/reservations", json={}, headers={"X-Forwarded-For": "10.0.0.1"})
            r1 = client.post("/api/v1/reservations", json={}, headers={"X-Forwarded-For": "10.0.0.1"})
            assert r1.status_code == 429

            # Different real IP has its own counter
            r2 = client.post("/api/v1/reservations", json={}, headers={"X-Forwarded-For": "10.0.0.2"})
            assert r2.status_code != 429
        finally:
            _rl.TRUSTED_PROXY_HOPS = original_hops
            _rl.RATE_LIMITS.clear()
            _rl.RATE_LIMITS.update(original_limits)


# ---------------------------------------------------------------------------
# XFF forge resistance
# ---------------------------------------------------------------------------

class TestXFFForgeResistance:
    """Prove forging X-Forwarded-For does not bypass rate limiting.

    In production with 1 trusted proxy:
        Client sends:    X-Forwarded-For: <attacker-forged-ip>
        LB appends:      X-Forwarded-For: <attacker-forged-ip>, <real-client-ip>
        We read:         ips[-1] = <real-client-ip>   ← trustworthy

    The attacker can change the forged prefix on every request; the real
    IP stays the same and accumulates against the limit.
    """

    def test_forged_xff_prefix_ignored_real_ip_is_throttled(self) -> None:
        import yasargold_commerce.rate_limiter as _rl
        original_hops = _rl.TRUSTED_PROXY_HOPS
        original_limits = dict(_rl.RATE_LIMITS)
        _rl.TRUSTED_PROXY_HOPS = 1
        _rl.RATE_LIMITS["reservation-write"] = (2, 60)

        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)

        try:
            # Simulate LB-appended format: "attacker_forged, real_client_ip"
            # We read ips[-1] = "10.0.0.99" regardless of the forged prefix
            client.post("/api/v1/reservations", json={},
                        headers={"X-Forwarded-For": "forge_ip_1, 10.0.0.99"})
            client.post("/api/v1/reservations", json={},
                        headers={"X-Forwarded-For": "forge_ip_2, 10.0.0.99"})

            # Attacker changes forged prefix → real IP still throttled
            r = client.post("/api/v1/reservations", json={},
                            headers={"X-Forwarded-For": "forge_ip_3, 10.0.0.99"})
            assert r.status_code == 429
        finally:
            _rl.TRUSTED_PROXY_HOPS = original_hops
            _rl.RATE_LIMITS.clear()
            _rl.RATE_LIMITS.update(original_limits)

    def test_different_real_ips_are_independent_even_with_same_forged_prefix(self) -> None:
        import yasargold_commerce.rate_limiter as _rl
        original_hops = _rl.TRUSTED_PROXY_HOPS
        original_limits = dict(_rl.RATE_LIMITS)
        _rl.TRUSTED_PROXY_HOPS = 1
        _rl.RATE_LIMITS["reservation-write"] = (1, 60)

        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)

        try:
            # 10.0.0.1 hits limit
            client.post("/api/v1/reservations", json={},
                        headers={"X-Forwarded-For": "same-proxy-xff, 10.0.0.1"})
            r1 = client.post("/api/v1/reservations", json={},
                             headers={"X-Forwarded-For": "same-proxy-xff, 10.0.0.1"})
            assert r1.status_code == 429

            # 10.0.0.2 has its own counter — unaffected
            r2 = client.post("/api/v1/reservations", json={},
                             headers={"X-Forwarded-For": "same-proxy-xff, 10.0.0.2"})
            assert r2.status_code != 429
        finally:
            _rl.TRUSTED_PROXY_HOPS = original_hops
            _rl.RATE_LIMITS.clear()
            _rl.RATE_LIMITS.update(original_limits)

    def test_zero_trusted_hops_ignores_xff_uses_direct_connection(self) -> None:
        """With TRUSTED_PROXY_HOPS=0, XFF is completely ignored.

        All TestClient requests share the same request.client identity.
        Even with different XFF values, the counter accumulates on the
        direct connection — proving XFF is not read.
        """
        import yasargold_commerce.rate_limiter as _rl
        original_hops = _rl.TRUSTED_PROXY_HOPS
        original_limits = dict(_rl.RATE_LIMITS)
        _rl.TRUSTED_PROXY_HOPS = 0
        _rl.RATE_LIMITS["reservation-write"] = (2, 60)

        mini_app, _ = _make_app()
        client = TestClient(mini_app, raise_server_exceptions=False)

        try:
            # Different XFF values — counter is on direct connection (same for all TestClient reqs)
            client.post("/api/v1/reservations", json={},
                        headers={"X-Forwarded-For": "100.0.0.1"})
            client.post("/api/v1/reservations", json={},
                        headers={"X-Forwarded-For": "100.0.0.2"})
            # 3rd request: XFF ignored, direct connection IP hit the limit
            r = client.post("/api/v1/reservations", json={},
                            headers={"X-Forwarded-For": "100.0.0.3"})
            assert r.status_code == 429
        finally:
            _rl.TRUSTED_PROXY_HOPS = original_hops
            _rl.RATE_LIMITS.clear()
            _rl.RATE_LIMITS.update(original_limits)


# ---------------------------------------------------------------------------
# Webhook isolation from payment-write
# ---------------------------------------------------------------------------

class TestWebhookPaymentIsolation:
    """Prove the webhook route is on a separate rate class from payment-write.

    Moyasar retries a webhook on delivery failure. Those retries must NOT be
    throttled by the payment-write counter (3/5min). The two routes must have
    completely independent counters and independent limits.
    """

    def test_webhook_route_has_rate_class_webhook_not_payment_write(self) -> None:
        rc = _resolve_rate_class("POST", "/api/v1/webhooks/payment")
        assert rc == "webhook"
        assert rc != "payment-write"

    def test_payment_write_exhausted_does_not_affect_webhook_counter(self) -> None:
        redis = FakeRedis()
        # Exhaust payment-write for this client
        for _ in range(3):
            check_rate_limit("payment-write", "10.0.0.1", redis)
        assert check_rate_limit("payment-write", "10.0.0.1", redis) is False  # exhausted

        # Webhook counter is independent — still allowed
        assert check_rate_limit("webhook", "10.0.0.1", redis) is True

    def test_webhook_limit_is_100_per_minute(self) -> None:
        redis = FakeRedis()
        for _ in range(100):
            assert check_rate_limit("webhook", "10.0.0.1", redis) is True
        # 101st is denied
        assert check_rate_limit("webhook", "10.0.0.1", redis) is False

    def test_payment_write_limit_is_3_per_5_minutes(self) -> None:
        redis = FakeRedis()
        for _ in range(3):
            assert check_rate_limit("payment-write", "10.0.0.1", redis) is True
        assert check_rate_limit("payment-write", "10.0.0.1", redis) is False


# ---------------------------------------------------------------------------
# Production Redis config fail-safe
# ---------------------------------------------------------------------------

class TestProductionRedisConfig:
    """Prove missing REDIS_URL raises at startup in production mode.

    Consistent with SEC-001: unconfigured required dependency → explicit error,
    not silent degradation. FakeRedis in production is fail-open — per-worker,
    resets on restart, no cross-process coordination.
    """

    def test_production_without_redis_url_raises(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "production")
        monkeypatch.delenv("REDIS_URL", raising=False)

        from yasargold_commerce.main import _check_production_redis_config
        with pytest.raises(RuntimeError, match="REDIS_URL"):
            _check_production_redis_config()

    def test_production_with_redis_url_does_not_raise(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "production")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        from yasargold_commerce.main import _check_production_redis_config
        _check_production_redis_config()  # must not raise

    def test_non_production_without_redis_url_does_not_raise(self, monkeypatch) -> None:
        monkeypatch.delenv("COMMERCE_ENV", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)

        from yasargold_commerce.main import _check_production_redis_config
        _check_production_redis_config()  # FakeRedis is acceptable in dev/test

    def test_development_env_without_redis_url_does_not_raise(self, monkeypatch) -> None:
        monkeypatch.setenv("COMMERCE_ENV", "development")
        monkeypatch.delenv("REDIS_URL", raising=False)

        from yasargold_commerce.main import _check_production_redis_config
        _check_production_redis_config()  # not production → FakeRedis is fine
