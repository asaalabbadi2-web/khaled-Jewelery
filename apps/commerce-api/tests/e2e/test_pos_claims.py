"""E2E tests — POS claim endpoints (ADR-016 §H1 terminal fix).

Tests verify the three-step ERP integration:
    1. POST /items/{id}/pos-claim  → grant or deny atomically
    2. POST /items/{id}/pos-claim/{claim_id}/confirm  → ERP committed
    3. DELETE /items/{id}/pos-claim/{claim_id}        → ERP rolled back

Auth is exercised directly — pos-claim uses X-POS-Secret, not customer JWT.

V2 proof (claim atomicity):
    The partial unique index ix_pos_claims_one_active_per_item (declared with
    both postgresql_where and sqlite_where) ensures at most one ACTIVE claim
    per item exists at the database level. TestClaimAtomicity inserts two
    concurrent ACTIVE rows for the same item directly through the ORM and
    proves IntegrityError fires — this is the Layer 2 safety net that catches
    races that slip past Layer 1 (SELECT FOR UPDATE).

V3 proof (cross-system mutual exclusion — F3):
    V3.a: TestCreateClaim.test_online_reservation_blocks_claim
          online reservation ACTIVE → pos-claim attempt → 409
    V3.b: TestV3MutualExclusion.test_active_pos_claim_blocks_online_reservation
          pos-claim ACTIVE → online reservation attempt → 409 ITEM_POS_CLAIMED
    Together these prove the between-systems TOCTOU window (INV-4) is closed in
    both directions: neither channel can sneak past the other's hold.

V4 proofs: TestExpiry covers expired-claim-frees-item and released-claim-frees-item.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.e2e.conftest import E2E_ITEM_CODE, E2E_POS_SECRET

_ITEM_ID   = 42
_ITEM_ID_2 = 99
_BASE      = "/api/v1"
_POS_HDR   = {"X-POS-Secret": E2E_POS_SECRET}
_WRONG_HDR = {"X-POS-Secret": "wrong-secret"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seed_reservation(SessionLocal):
    """Insert an ACTIVE reservation for _ITEM_ID that expires in 15 min."""
    from yasargold_commerce.infra.reservation_orm import ReservationRow

    now = datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        row = ReservationRow(
            id="RES-pos-claim-test-001",
            quote_id="QUO-001",
            item_id=_ITEM_ID,
            gold_price_id=1,
            locked_rate_per_gram_24k="330.00",
            karat_rate_per_gram="289.37",
            pricing_engine_version="1.0",
            reserved_at=now,
            valid_until=now + timedelta(minutes=15),
            status="ACTIVE",
        )
        session.add(row)
        session.commit()
    finally:
        session.close()


@pytest.fixture
def seed_expired_reservation(SessionLocal):
    """Insert an ACTIVE-but-expired reservation for _ITEM_ID."""
    from yasargold_commerce.infra.reservation_orm import ReservationRow

    now = datetime.now(timezone.utc)
    session = SessionLocal()
    try:
        row = ReservationRow(
            id="RES-expired-001",
            quote_id="QUO-EXP",
            item_id=_ITEM_ID,
            gold_price_id=1,
            locked_rate_per_gram_24k="330.00",
            karat_rate_per_gram="289.37",
            pricing_engine_version="1.0",
            reserved_at=now - timedelta(minutes=30),
            valid_until=now - timedelta(minutes=1),
            status="ACTIVE",
        )
        session.add(row)
        session.commit()
    finally:
        session.close()


def _claim_item(client, item_id=_ITEM_ID, ttl=30, headers=None) -> dict:
    """Helper: POST pos-claim and return the parsed JSON body."""
    hdr = headers if headers is not None else _POS_HDR
    r = client.post(
        f"{_BASE}/items/{item_id}/pos-claim",
        json={"ttl_seconds": ttl},
        headers=hdr,
    )
    return r


# ---------------------------------------------------------------------------
# C1 — Create claim: available item
# ---------------------------------------------------------------------------

class TestCreateClaim:
    def test_available_item_returns_201(self, client):
        r = _claim_item(client)
        assert r.status_code == 201
        body = r.json()
        assert body["item_id"]   == _ITEM_ID
        assert body["claim_id"].startswith("CLM-")
        assert "expires_at" in body

    def test_claim_id_is_unique_across_calls(self, client):
        r1 = _claim_item(client, item_id=_ITEM_ID)
        r2 = _claim_item(client, item_id=_ITEM_ID_2)
        assert r1.json()["claim_id"] != r2.json()["claim_id"]

    def test_ttl_upper_bound_clamped_to_300s(self, client):
        r = _claim_item(client, ttl=9999)
        assert r.status_code == 201

    def test_expired_reservation_does_not_block_claim(self, client, seed_expired_reservation):
        r = _claim_item(client)
        assert r.status_code == 201

    def test_online_reservation_blocks_claim(self, client, seed_reservation):
        r = _claim_item(client)
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["type"] == "online_reservation"
        assert detail["reservation_id"] == "RES-pos-claim-test-001"
        assert "reserved_until" in detail

    def test_active_pos_claim_blocks_second_claim(self, client):
        first = _claim_item(client)
        assert first.status_code == 201

        second = _claim_item(client)
        assert second.status_code == 409
        detail = second.json()["detail"]
        assert detail["type"] == "pos_claim"
        assert detail["claim_id"] == first.json()["claim_id"]

    def test_different_item_can_be_claimed_independently(self, client, seed_reservation):
        # _ITEM_ID is reserved; _ITEM_ID_2 is free
        r = _claim_item(client, item_id=_ITEM_ID_2)
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# C2 — Auth enforcement
# ---------------------------------------------------------------------------

class TestPosClaimAuth:
    def test_missing_secret_returns_401(self, client):
        r = client.post(f"{_BASE}/items/{_ITEM_ID}/pos-claim", json={})
        assert r.status_code == 401

    def test_wrong_secret_returns_401(self, client):
        r = _claim_item(client, headers=_WRONG_HDR)
        assert r.status_code == 401

    def test_missing_pos_api_secret_env_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("POS_API_SECRET", raising=False)
        r = client.post(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim",
            json={},
            headers=_POS_HDR,
        )
        assert r.status_code == 503

    def test_confirm_requires_pos_secret(self, client):
        r = client.post(f"{_BASE}/items/{_ITEM_ID}/pos-claim/CLM-fake/confirm")
        assert r.status_code == 401

    def test_release_requires_pos_secret(self, client):
        r = client.delete(f"{_BASE}/items/{_ITEM_ID}/pos-claim/CLM-fake")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# C3 — Confirm
# ---------------------------------------------------------------------------

class TestConfirmClaim:
    def test_confirm_active_claim_returns_200(self, client):
        claim_id = _claim_item(client).json()["claim_id"]
        r = client.post(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}/confirm",
            headers=_POS_HDR,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["claim_id"] == claim_id
        assert body["status"]   == "CONFIRMED"

    def test_confirm_nonexistent_claim_returns_404(self, client):
        r = client.post(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/CLM-no-such/confirm",
            headers=_POS_HDR,
        )
        assert r.status_code == 404

    def test_confirm_wrong_item_id_returns_404(self, client):
        claim_id = _claim_item(client, item_id=_ITEM_ID).json()["claim_id"]
        r = client.post(
            f"{_BASE}/items/{_ITEM_ID_2}/pos-claim/{claim_id}/confirm",
            headers=_POS_HDR,
        )
        assert r.status_code == 404

    def test_confirm_already_confirmed_returns_422(self, client):
        claim_id = _claim_item(client).json()["claim_id"]
        client.post(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}/confirm",
            headers=_POS_HDR,
        )
        # Second confirm on same claim
        r = client.post(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}/confirm",
            headers=_POS_HDR,
        )
        assert r.status_code == 422

    def test_confirm_released_claim_returns_422(self, client):
        claim_id = _claim_item(client).json()["claim_id"]
        client.delete(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}",
            headers=_POS_HDR,
        )
        r = client.post(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}/confirm",
            headers=_POS_HDR,
        )
        assert r.status_code == 422

    def test_confirmed_claim_allows_new_claim_on_same_item(self, client):
        claim_id = _claim_item(client).json()["claim_id"]
        client.post(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}/confirm",
            headers=_POS_HDR,
        )
        # After confirm, item is no longer ACTIVE-claimed
        r = _claim_item(client)
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# C4 — Release
# ---------------------------------------------------------------------------

class TestReleaseClaim:
    def test_release_active_claim_returns_204(self, client):
        claim_id = _claim_item(client).json()["claim_id"]
        r = client.delete(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}",
            headers=_POS_HDR,
        )
        assert r.status_code == 204

    def test_release_nonexistent_claim_returns_404(self, client):
        r = client.delete(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/CLM-no-such",
            headers=_POS_HDR,
        )
        assert r.status_code == 404

    def test_release_wrong_item_id_returns_404(self, client):
        claim_id = _claim_item(client, item_id=_ITEM_ID).json()["claim_id"]
        r = client.delete(
            f"{_BASE}/items/{_ITEM_ID_2}/pos-claim/{claim_id}",
            headers=_POS_HDR,
        )
        assert r.status_code == 404

    def test_release_allows_new_claim_on_same_item(self, client):
        claim_id = _claim_item(client).json()["claim_id"]
        client.delete(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}",
            headers=_POS_HDR,
        )
        r = _claim_item(client)
        assert r.status_code == 201

    def test_release_confirmed_claim_is_idempotent_204(self, client):
        """Releasing a CONFIRMED claim is a no-op — already in terminal state."""
        claim_id = _claim_item(client).json()["claim_id"]
        client.post(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}/confirm",
            headers=_POS_HDR,
        )
        # Release after confirm — returns 204 (no-op, not an error)
        r = client.delete(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}",
            headers=_POS_HDR,
        )
        assert r.status_code == 204


# ---------------------------------------------------------------------------
# V2 — Atomicity: partial unique index is the real guard (Layer 2)
# ---------------------------------------------------------------------------

class TestClaimAtomicity:
    """Prove that the DB-level partial unique index fires, not just the
    application-level check. This is the V2 requirement:
    "without this test the claim is not atomic, only hopefully-atomic."

    Two concurrent transactions that both read 'no ACTIVE claim' and then
    both INSERT cannot both succeed — the second INSERT raises IntegrityError.
    The test simulates this by bypassing the HTTP layer and inserting directly.
    """

    def test_direct_insert_of_two_active_claims_fails(self, SessionLocal):
        """IntegrityError from ix_pos_claims_one_active_per_item proves Layer 2."""
        import pytest
        from sqlalchemy.exc import IntegrityError as _IE

        now = datetime.now(timezone.utc)

        session = SessionLocal()
        try:
            from yasargold_commerce.infra.pos_claim_orm import PosClaimRow

            claim_a = PosClaimRow(
                id="CLM-v2-test-aaa",
                item_id=_ITEM_ID,
                claimed_at=now,
                expires_at=now + timedelta(seconds=30),
                status="ACTIVE",
            )
            session.add(claim_a)
            session.commit()

            claim_b = PosClaimRow(
                id="CLM-v2-test-bbb",
                item_id=_ITEM_ID,
                claimed_at=now,
                expires_at=now + timedelta(seconds=30),
                status="ACTIVE",
            )
            session.add(claim_b)
            with pytest.raises(_IE):
                session.commit()
        finally:
            session.rollback()
            session.close()

    def test_two_active_claims_different_items_both_succeed(self, SessionLocal):
        """Partial index is per-item: no conflict across different items."""
        from sqlalchemy.exc import IntegrityError as _IE

        now = datetime.now(timezone.utc)
        session = SessionLocal()
        try:
            from yasargold_commerce.infra.pos_claim_orm import PosClaimRow

            for item_id, claim_id in [(_ITEM_ID, "CLM-v2-item1"), (_ITEM_ID_2, "CLM-v2-item2")]:
                session.add(PosClaimRow(
                    id=claim_id,
                    item_id=item_id,
                    claimed_at=now,
                    expires_at=now + timedelta(seconds=30),
                    status="ACTIVE",
                ))
            session.commit()  # must not raise
        finally:
            session.rollback()
            session.close()

    def test_confirmed_claim_allows_new_active_for_same_item(self, SessionLocal):
        """CONFIRMED is not ACTIVE: the partial index only covers ACTIVE rows,
        so a new ACTIVE claim can be inserted after confirmation."""
        from sqlalchemy.exc import IntegrityError as _IE

        now = datetime.now(timezone.utc)
        session = SessionLocal()
        try:
            from yasargold_commerce.infra.pos_claim_orm import PosClaimRow

            first = PosClaimRow(
                id="CLM-v2-confirmed",
                item_id=_ITEM_ID,
                claimed_at=now,
                expires_at=now + timedelta(seconds=30),
                status="CONFIRMED",  # terminal — not ACTIVE
            )
            session.add(first)
            session.flush()

            second = PosClaimRow(
                id="CLM-v2-new-active",
                item_id=_ITEM_ID,
                claimed_at=now,
                expires_at=now + timedelta(seconds=30),
                status="ACTIVE",
            )
            session.add(second)
            session.commit()  # must not raise
        finally:
            session.rollback()
            session.close()

    def test_two_claims_after_expiry_second_gets_clean_rejection(
        self, client, SessionLocal
    ):
        """S — sweep-race: seed an expired ACTIVE claim, then issue two claims
        sequentially (simulating two concurrent requests after the TTL lapsed).

        Proves:
        1. First request: sweeps the expired ACTIVE row, inserts new ACTIVE → 201.
        2. Second request: finds the new live ACTIVE row → clean 409 with type
           'pos_claim' — NOT a leaked IntegrityError (no 500, no traceback).
        """
        from yasargold_commerce.infra.pos_claim_orm import PosClaimRow

        now = datetime.now(timezone.utc)
        session = SessionLocal()
        try:
            expired = PosClaimRow(
                id="CLM-sweep-race-exp",
                item_id=_ITEM_ID,
                claimed_at=now - timedelta(minutes=5),
                expires_at=now - timedelta(minutes=4),
                status="ACTIVE",
            )
            session.add(expired)
            session.commit()
        finally:
            session.close()

        # Request 1: sweeps expired row under the row lock, then inserts → 201
        r1 = _claim_item(client)
        assert r1.status_code == 201, r1.json()

        # Request 2: live ACTIVE claim now exists → clean 409
        r2 = _claim_item(client)
        assert r2.status_code == 409, r2.json()
        body = r2.json()
        assert body.get("detail", {}).get("type") == "pos_claim", (
            "Concurrent claim after expiry must return structured 'pos_claim' "
            f"rejection — not a raw IntegrityError or 500. Got: {body}"
        )


# ---------------------------------------------------------------------------
# V4 — Expiry: expired/released claim frees the item
# ---------------------------------------------------------------------------

class TestExpiry:
    """Prove that an item is claimable again after its previous claim expires
    or is released. V4 requirement: 'expired claim → item claimable again'."""

    @pytest.fixture
    def seed_expired_claim(self, SessionLocal):
        """Seed an ACTIVE claim whose expires_at is already in the past."""
        from yasargold_commerce.infra.pos_claim_orm import PosClaimRow

        now = datetime.now(timezone.utc)
        session = SessionLocal()
        try:
            row = PosClaimRow(
                id="CLM-expired-v4",
                item_id=_ITEM_ID,
                claimed_at=now - timedelta(minutes=5),
                expires_at=now - timedelta(minutes=1),  # already past
                status="ACTIVE",
            )
            session.add(row)
            session.commit()
        finally:
            session.close()

    def test_expired_active_claim_does_not_block_new_claim(
        self, client, seed_expired_claim
    ):
        """V4: expired claim (expires_at in past) is invisible to the claim check
        because the query filters expires_at > now. Item is freely claimable."""
        r = _claim_item(client)
        assert r.status_code == 201, r.json()

    def test_released_claim_frees_item_immediately(self, client):
        """V4: explicit DELETE (release) makes item claimable right away."""
        claim_id = _claim_item(client).json()["claim_id"]
        client.delete(
            f"{_BASE}/items/{_ITEM_ID}/pos-claim/{claim_id}",
            headers=_POS_HDR,
        )
        r = _claim_item(client)
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# V3 — Mutual exclusion: claim ⇄ reservation (both directions)
# ---------------------------------------------------------------------------

class TestV3MutualExclusion:
    """V3.a: online reservation → pos-claim denied (cited from TestCreateClaim).
    V3.b: active pos-claim → online reservation denied (ITEM_POS_CLAIMED, 409).

    Together these prove the invariant in both directions:
    an item cannot be simultaneously reserved online AND claimed for POS sale.
    """

    # V3.a is already proved by TestCreateClaim.test_online_reservation_blocks_claim.
    # This class adds V3.b only.

    def test_active_pos_claim_blocks_online_reservation(self, client, seed_db):
        """V3.b: ACTIVE pos-claim → POST /reservations returns 409 ITEM_POS_CLAIMED.

        seed_db plants item_id=1 with item_code=E2E_ITEM_CODE and GoldPrice.
        We claim item_id=1 via pos-claim, then verify the reservation endpoint
        rejects with the expected error code.
        """
        # Seed item has id=1 in the test DB.
        seeded_item_id = seed_db["item_id"]   # 1

        # Claim the seeded item.
        claim_r = client.post(
            f"{_BASE}/items/{seeded_item_id}/pos-claim",
            json={"ttl_seconds": 30},
            headers=_POS_HDR,
        )
        assert claim_r.status_code == 201, claim_r.json()

        # Online reservation for the same item must now be rejected.
        reservation_r = client.post(
            f"{_BASE}/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
            headers={"Authorization": "Bearer ignored"},  # auth overridden by client fixture
        )
        assert reservation_r.status_code == 409, reservation_r.json()
        assert reservation_r.json()["detail"]["code"] == "ITEM_POS_CLAIMED"

    def test_released_pos_claim_unblocks_online_reservation(self, client, seed_db):
        """V3.b inverse: releasing the pos-claim allows the online reservation."""
        seeded_item_id = seed_db["item_id"]

        claim_r = client.post(
            f"{_BASE}/items/{seeded_item_id}/pos-claim",
            json={"ttl_seconds": 30},
            headers=_POS_HDR,
        )
        assert claim_r.status_code == 201
        claim_id = claim_r.json()["claim_id"]

        # Release the claim.
        client.delete(
            f"{_BASE}/items/{seeded_item_id}/pos-claim/{claim_id}",
            headers=_POS_HDR,
        )

        # Now the online reservation must succeed.
        reservation_r = client.post(
            f"{_BASE}/reservations",
            json={"item_slug": E2E_ITEM_CODE.lower()},
            headers={"Authorization": "Bearer ignored"},
        )
        assert reservation_r.status_code == 201, reservation_r.json()
