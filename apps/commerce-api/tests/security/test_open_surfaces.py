"""Open surface witnesses — Law 0 applied to Known Gaps.

Every documented open surface carries an xfail test that attempts the attack
and expects it to SUCCEED (i.e., the protection is NOT yet in place).

When a gap is closed, its xfail test starts passing unexpectedly (pytest
marks it XPASS). CI is configured to treat XPASS as a failure
(xfail_strict=true in pyproject.toml). This forces the PR that closes the
gap to also update this file and the documentation — drift in either
direction becomes CI-fatal.

Convention:
    @pytest.mark.xfail(strict=True, reason="SURFACE-ID: gap description · fix: what closes it")

Adding a test here does NOT make a gap acceptable — it makes it observable.

── Closed surfaces (remove witness when gap is closed) ────────────────────────
BOLA-shipments (closed Sprint 10):
    GET /api/v1/orders/{order_id}/shipments now enforces ownership via
    OrderService.find_order_for_customer() before any shipment query.
    Proof: tests/security/test_shipment_bola.py (4 tests).
    ADR-017 §5 updated. security-overview.md §8 updated.
"""
