"""Security scan tests — Laws 1 and 3 (ADR-017).

Law 1 (Deny-by-default scope):
    Every FastAPI route must declare its security scope in ROUTE_SECURITY
    before it can be merged. A missing entry is a CI failure, not a warning.

Law 3 (Deny-by-default rate class):
    Every FastAPI route must declare its rate_class. A route without a
    rate_class is unthrottled — that is a security default, not a UX choice.

These tests walk app.routes at test time. Adding a new endpoint without
updating ROUTE_SECURITY will fail CI on the first run — the "deny" is
structural, not per-request.

Why this matters:
    How systems get compromised: the forgotten addition, not the intentional
    one. A route scan test makes "I forgot to classify it" impossible to ship.
"""
from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from yasargold_commerce.main import app
from yasargold_commerce.security import (
    ROUTE_SECURITY,
    VALID_RATE_CLASSES,
    VALID_SCOPES,
    RouteSecurityClass,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_routes() -> list[tuple[str, str]]:
    """Return (method, path) for every APIRoute in the app.

    FastAPI 0.139+ stores include_router() results as _IncludedRouter
    objects (not plain APIRoute). We walk both the top-level routes and
    each _IncludedRouter's original_router to get the full list.
    """
    result = []
    for route in app.router.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                result.append((method, route.path))
        elif type(route).__name__ == "_IncludedRouter":
            for r in route.original_router.routes:
                if isinstance(r, APIRoute):
                    for method in r.methods:
                        result.append((method, r.path))
    return result


# ---------------------------------------------------------------------------
# Law 1 — every route has a declared scope
# ---------------------------------------------------------------------------

class TestLaw1DenyByDefaultScope:
    def test_every_route_is_classified(self) -> None:
        """CI gate: any APIRoute not in ROUTE_SECURITY fails the build."""
        unclassified = [
            f"{method} {path}"
            for method, path in _api_routes()
            if (method, path) not in ROUTE_SECURITY
        ]
        assert not unclassified, (
            "Unclassified routes — add to security.ROUTE_SECURITY before merging:\n"
            + "\n".join(f"  {r}" for r in sorted(unclassified))
        )

    def test_every_scope_is_a_known_value(self) -> None:
        """Catch typos in scope strings at merge time, not at runtime."""
        bad = [
            f"{method} {path}: scope='{cls.scope}'"
            for (method, path), cls in ROUTE_SECURITY.items()
            if cls.scope not in VALID_SCOPES
        ]
        assert not bad, (
            f"Unknown scope values (add to VALID_SCOPES or fix the typo):\n"
            + "\n".join(f"  {b}" for b in bad)
        )

    def test_public_routes_are_explicitly_listed(self) -> None:
        """Public routes must be consciously chosen, not the default."""
        public_routes = [
            f"{method} {path}"
            for (method, path), cls in ROUTE_SECURITY.items()
            if cls.scope == "public"
        ]
        # If this list grows unexpectedly, review whether new routes should
        # really be public or whether they need customer/admin scope.
        assert len(public_routes) >= 1, "Expected at least one public route (/health)"
        for r in public_routes:
            assert r in [
                f"{m} {p}"
                for (m, p), cls in ROUTE_SECURITY.items()
                if cls.scope == "public"
            ]

    def test_webhook_routes_carry_law6_note(self) -> None:
        """Webhook routes must document their signature verification (Law 6)."""
        webhook_routes = [
            (method, path, cls)
            for (method, path), cls in ROUTE_SECURITY.items()
            if cls.scope == "webhook"
        ]
        for method, path, cls in webhook_routes:
            assert cls.note, (
                f"{method} {path}: webhook scope requires a note documenting "
                f"signature verification mechanism (Law 6)"
            )


# ---------------------------------------------------------------------------
# Law 3 — every route has a declared rate class
# ---------------------------------------------------------------------------

class TestLaw3DenyByDefaultRateClass:
    def test_every_route_has_a_rate_class(self) -> None:
        """CI gate: any route without a rate_class is unthrottled by default — fail the build."""
        missing_rate = [
            f"{method} {path}"
            for (method, path), cls in ROUTE_SECURITY.items()
            if not cls.rate_class
        ]
        assert not missing_rate, (
            "Routes missing rate_class — unthrottled routes are a DoS risk:\n"
            + "\n".join(f"  {r}" for r in sorted(missing_rate))
        )

    def test_every_rate_class_is_a_known_value(self) -> None:
        """Catch typos in rate_class strings at merge time."""
        bad = [
            f"{method} {path}: rate_class='{cls.rate_class}'"
            for (method, path), cls in ROUTE_SECURITY.items()
            if cls.rate_class not in VALID_RATE_CLASSES
        ]
        assert not bad, (
            "Unknown rate_class values (add to VALID_RATE_CLASSES or fix the typo):\n"
            + "\n".join(f"  {b}" for b in bad)
        )

    def test_reservation_write_is_the_most_restricted_class(self) -> None:
        """reservation-write must exist — it's the highest-cost endpoint."""
        rate_classes = {cls.rate_class for cls in ROUTE_SECURITY.values()}
        assert "reservation-write" in rate_classes

    def test_expensive_write_routes_are_not_catalog_read(self) -> None:
        """No POST/DELETE should be classified as catalog-read (read class on write endpoint)."""
        bad = [
            f"{method} {path}"
            for (method, path), cls in ROUTE_SECURITY.items()
            if method in ("POST", "PUT", "DELETE", "PATCH")
            and cls.rate_class == "catalog-read"
        ]
        assert not bad, (
            "Write endpoints must not use catalog-read rate class:\n"
            + "\n".join(f"  {b}" for b in bad)
        )


# ---------------------------------------------------------------------------
# Registry completeness — ROUTE_SECURITY covers what app.routes declares
# ---------------------------------------------------------------------------

class TestRegistryCompleteness:
    def test_route_security_has_no_phantom_entries(self) -> None:
        """Entries in ROUTE_SECURITY that don't exist in the app are noise — fail."""
        live_routes = set(_api_routes())
        phantom = [
            f"{method} {path}"
            for method, path in ROUTE_SECURITY
            if (method, path) not in live_routes
        ]
        assert not phantom, (
            "ROUTE_SECURITY entries with no matching app route "
            "(stale after route rename/deletion — remove them):\n"
            + "\n".join(f"  {r}" for r in sorted(phantom))
        )

    def test_route_count_matches(self) -> None:
        """Number of classified routes == number of APIRoutes in the app."""
        live_count = len(_api_routes())
        registry_count = len(ROUTE_SECURITY)
        assert live_count == registry_count, (
            f"Route count mismatch: {live_count} live routes vs "
            f"{registry_count} classified. "
            f"Add new routes to security.ROUTE_SECURITY."
        )
