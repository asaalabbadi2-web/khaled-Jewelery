"""Gate B: POS claim protocol against the Commerce API (T2.2 — INV-4 ENFORCED).

Called by the POS sale route BEFORE any DB write (E4.0).

T2.2 (Sprint 11): `request_pos_claim()` replaced `check_item_online_reservation()`.
Commerce holds an exclusive row lock for the duration of the ERP sale, closing the
TOCTOU window documented in ADR-016 §H1 (previously MITIGATED, now ENFORCED).

Legacy: `check_item_online_reservation()` is retained for its unit tests; it is no
longer on the write path. Do not reintroduce it into add_invoice().

Fail-open policy (E4.1):
  Commerce API timeout ≤ 2 s or any network error → sale is ALLOWED + WARNING
  logged + metric incremented. The showroom must not freeze because the
  online service is slow or down; the race window is documented in ADR-016.

H3 — Distinct metrics (ADR-016 §H-series):
  TIMEOUT events   → gate_b_timeout_total
  UNREACHABLE events → gate_b_unreachable_total
  UX merges both as fail-open; metrics keep them separate for signal fidelity.
  Rising TIMEOUT rate is an early degradation signal before UNREACHABLE spikes.

H2 — Fail-open ceiling (ADR-016 §H-series):
  Beyond FAIL_OPEN_CEILING events in FAIL_OPEN_WINDOW_SECONDS, emit CRITICAL:
  both layers fail-open simultaneously → zero barriers during a Commerce outage.
  Showroom POS continues; this event must page the on-call operator to decide
  whether to manually halt the online sales channel until Commerce recovers.
  The ceiling does NOT change fail-open behaviour — it is an observable signal,
  not a killswitch. A killswitch requires operator consent (ADR decision).

H4 — Timeout budget (ADR-016 §H-series):
  _TIMEOUT_SECONDS = 2.0 (back-end, on the write path — must not hold the
  Flask DB session open longer than necessary; 2 s is tight but acceptable).
  Front-end budget = 5 s (PosAvailabilityGateConnected Promise.race) — the UI
  check is NOT on the write path, so it can afford to wait longer for Commerce
  to respond before falling back to fail-open. Different budgets for different
  stakes; both document their rationale where they are defined.

Trade-off is explicit: we prefer availability (showroom can always sell)
over strict consistency. The compensation path (ERP sync + reconciliation)
handles the rare case where both a POS sale and an online reservation commit
the same item during the fail-open window.

H1 — TOCTOU status (ADR-016 §H-series):
  This check is a PRE-TRANSACTION HTTP call. The ERP and Commerce API use
  SEPARATE databases (ERP: SQLite in dev / PostgreSQL in production via
  DATABASE_URL; Commerce: its own PostgreSQL via its own DATABASE_URL).
  A true in-transaction row lock spanning both databases is architecturally
  impossible without a shared database instance or a distributed lock (Redis)
  or a Commerce-side "claim for POS" API endpoint.

  INV-4 status: MITIGATED (not ENFORCED).
    — Pre-transaction check narrows the TOCTOU window to the route processing
      time (~100 ms at P95). A reservation created in that window is not caught.
    — Compensation path: ERPSyncWorker + ReconciliationWorker.
    — Terminal fix: Commerce adds POST /items/{id}/pos-claim that atomically
      claims the item for POS; ERP confirms or abandons on commit/rollback.
      This closes the window without requiring a shared database.
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock

import requests

log = logging.getLogger(__name__)

# ── Timeout budget ────────────────────────────────────────────────────────────
# 2 s: on the write path — keep the Flask DB session waiting as short as
# possible. See H4 note in module docstring; front-end uses 5 s (different stake).
_TIMEOUT_SECONDS = 2.0

# ── Metric keys ───────────────────────────────────────────────────────────────
# H3: distinct keys for signal fidelity (rising TIMEOUT ≠ rising UNREACHABLE).
_METRIC_TIMEOUT     = "gate_b_timeout_total"
_METRIC_UNREACHABLE = "gate_b_unreachable_total"

# ── H3: per-cause counters ─────────────────────────────────────────────────────
_timeout_count     = 0
_unreachable_count = 0

# ── H2: sliding-window circuit-breaker state ──────────────────────────────────
# Count fail-open events in the last FAIL_OPEN_WINDOW_SECONDS seconds.
# When the count exceeds FAIL_OPEN_CEILING, emit CRITICAL (one log per crossing;
# suppressed while the condition persists to avoid log spam).
FAIL_OPEN_WINDOW_SECONDS: int  = int(os.environ.get("GATE_B_WINDOW_SECONDS", "600"))   # 10 min
FAIL_OPEN_CEILING:        int  = int(os.environ.get("GATE_B_CEILING", "10"))

_window_events: deque[float] = deque()   # timestamps of recent fail-open events
_window_lock   = Lock()
_ceiling_tripped = False   # suppresses repeated CRITICAL per crossing


@dataclass(frozen=True)
class AvailabilityResult:
    allowed:        bool
    blocked_reason: str | None = None
    reserved_until: str | None = None
    reservation_id: str | None = None


def _commerce_api_base_url() -> str:
    return os.environ.get("COMMERCE_API_URL", "http://localhost:8001")


def _record_fail_open(cause: str) -> None:
    """Increment the appropriate counter and run the H2 sliding-window check."""
    global _timeout_count, _unreachable_count, _ceiling_tripped

    if cause == "timeout":
        _timeout_count += 1
        log.warning(
            "gate_b: Commerce API timeout — failing open; sale allowed. "
            "metric=%s=%d",
            _METRIC_TIMEOUT, _timeout_count,
        )
    else:
        _unreachable_count += 1
        log.warning(
            "gate_b: Commerce API unreachable (%s) — failing open; sale allowed. "
            "metric=%s=%d",
            cause, _METRIC_UNREACHABLE, _unreachable_count,
        )

    now = time.monotonic()
    with _window_lock:
        _window_events.append(now)
        cutoff = now - FAIL_OPEN_WINDOW_SECONDS
        while _window_events and _window_events[0] < cutoff:
            _window_events.popleft()
        count_in_window = len(_window_events)

    if count_in_window > FAIL_OPEN_CEILING:
        if not _ceiling_tripped:
            _ceiling_tripped = True
            log.critical(
                "gate_b: FAIL-OPEN CEILING BREACHED — %d fail-open events in the "
                "last %d s (ceiling=%d). Both UI and backend Gate B layers are failing "
                "open simultaneously. Zero barriers against selling online-reserved items. "
                "ACTION REQUIRED: verify Commerce API health; consider halting the online "
                "sales channel until Commerce recovers. "
                "metric=%s+%s",
                count_in_window, FAIL_OPEN_WINDOW_SECONDS, FAIL_OPEN_CEILING,
                _METRIC_TIMEOUT, _METRIC_UNREACHABLE,
            )
    else:
        # Window dropped back below ceiling — reset trip so next crossing logs again.
        _ceiling_tripped = False


def check_item_online_reservation(item_id: int) -> AvailabilityResult:
    """Return whether a POS sale of item_id is allowed given online reservation state.

    Returns:
        AvailabilityResult.allowed=True  → no active reservation; proceed with sale
        AvailabilityResult.allowed=False → ACTIVE reservation exists; block the sale

    On Commerce API timeout or network error: returns allowed=True (fail-open)
    and logs a WARNING. The caller is responsible for propagating the warning
    to the POS response so staff are aware.

    See module docstring for H1 (TOCTOU / MITIGATED status).
    """
    base = _commerce_api_base_url()
    url = f"{base}/items/{item_id}/availability"

    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        body = resp.json()
    except requests.Timeout:
        _record_fail_open("timeout")
        return AvailabilityResult(allowed=True)
    except Exception as exc:
        _record_fail_open(str(exc))
        return AvailabilityResult(allowed=True)

    if body.get("available", True):
        return AvailabilityResult(allowed=True)

    reserved_until = body.get("reserved_until")
    reservation_id = body.get("reservation_id")
    return AvailabilityResult(
        allowed=False,
        blocked_reason=(
            f"هذا المنتج محجوز إلكترونياً حتى {reserved_until}. "
            f"يرجى انتظار انتهاء الحجز أو إلغائه من لوحة الإدارة."
        ),
        reserved_until=reserved_until,
        reservation_id=reservation_id,
    )


# ── Observable accessors ──────────────────────────────────────────────────────

def get_timeout_count() -> int:
    """H3: fail-open events caused by Commerce API timeout."""
    return _timeout_count


def get_unreachable_count() -> int:
    """H3: fail-open events caused by Commerce API unreachable."""
    return _unreachable_count


def get_fail_open_count() -> int:
    """Total fail-open events (timeout + unreachable). Backward-compatible."""
    return _timeout_count + _unreachable_count


def get_window_event_count() -> int:
    """H2: number of fail-open events inside the current sliding window."""
    now = time.monotonic()
    with _window_lock:
        cutoff = now - FAIL_OPEN_WINDOW_SECONDS
        while _window_events and _window_events[0] < cutoff:
            _window_events.popleft()
        return len(_window_events)


def reset_fail_open_count() -> None:
    """Reset all counters and sliding-window state. Call in test teardown only."""
    global _timeout_count, _unreachable_count, _ceiling_tripped
    _timeout_count = 0
    _unreachable_count = 0
    _ceiling_tripped = False
    with _window_lock:
        _window_events.clear()


# ── POS Claim protocol (T2.2 — INV-4 ENFORCED) ───────────────────────────────
#
# Replaces the pre-transaction check_item_online_reservation() read with an
# atomic claim request.  Commerce holds the row lock for the duration of the
# ERP sale; the ERP confirms (on commit) or releases (on rollback).
#
# Flow:
#   1. ERP calls request_pos_claim(item_id) — BEFORE any DB write.
#   2. On GRANTED: proceed with invoice.
#   3. On committed: call confirm_pos_claim(item_id, claim_id).
#   4. On rollback:  call release_pos_claim(item_id, claim_id).
#
# Confirm and release are best-effort: they never block the ERP response.
# If Commerce is unreachable, the claim expires naturally after TTL seconds.

from dataclasses import dataclass as _dc


@_dc(frozen=True)
class PosClaimResult:
    granted:        bool
    denied:         bool       = False
    fail_open:      bool       = False
    claim_id:       str | None = None
    item_id:        int | None = None
    block_type:     str | None = None
    blocked_reason: str | None = None
    reserved_until: str | None = None


def _format_claim_block_reason(block_type: str | None, reserved_until: str | None) -> str:
    if block_type == "online_reservation":
        until = f" حتى {reserved_until}" if reserved_until else ""
        return f"هذا المنتج محجوز إلكترونياً{until}. يرجى انتظار انتهاء الحجز."
    if block_type == "pos_claim":
        until = f" حتى {reserved_until}" if reserved_until else ""
        return f"هذا المنتج قيد البيع في نقطة البيع الأخرى{until}."
    return "هذا المنتج غير متاح للبيع حالياً."


def request_pos_claim(item_id: int, ttl_seconds: int = 30) -> PosClaimResult:
    """Request an exclusive POS claim from Commerce API.

    Returns:
        PosClaimResult.granted=True, claim_id set  → proceed with sale
        PosClaimResult.denied=True                 → item reserved/claimed; block sale
        PosClaimResult.fail_open=True              → Commerce unreachable; sale allowed

    On fail-open: the TOCTOU window that was present before T2.2 is reintroduced
    temporarily.  This is the same trade-off as the original Gate B.  The claim
    expires via TTL, so no long-lived resource is leaked.
    """
    base = _commerce_api_base_url()
    url = f"{base}/api/v1/items/{item_id}/pos-claim"
    secret = os.environ.get("POS_API_SECRET", "")

    try:
        resp = requests.post(
            url,
            json={"ttl_seconds": ttl_seconds},
            headers={"X-POS-Secret": secret},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        _record_fail_open("timeout")
        return PosClaimResult(granted=True, fail_open=True, item_id=item_id)
    except Exception as exc:
        _record_fail_open(str(exc))
        return PosClaimResult(granted=True, fail_open=True, item_id=item_id)

    if resp.status_code == 201:
        body = resp.json()
        return PosClaimResult(granted=True, claim_id=body["claim_id"], item_id=item_id)

    if resp.status_code == 409:
        detail = resp.json().get("detail") or {}
        if isinstance(detail, str):
            detail = {}
        block_type     = detail.get("type")
        reserved_until = detail.get("reserved_until") or detail.get("expires_at")
        return PosClaimResult(
            granted=False,
            denied=True,
            item_id=item_id,
            block_type=block_type,
            blocked_reason=_format_claim_block_reason(block_type, reserved_until),
            reserved_until=reserved_until,
            claim_id=detail.get("claim_id"),
        )

    # Unexpected HTTP status → fail-open (do not block the sale on API oddity)
    _record_fail_open(f"HTTP {resp.status_code}")
    return PosClaimResult(granted=True, fail_open=True, item_id=item_id)


def confirm_pos_claim(item_id: int, claim_id: str) -> bool:
    """Confirm a POS claim after the ERP invoice commit. Best-effort; never raises."""
    base = _commerce_api_base_url()
    url = f"{base}/api/v1/items/{item_id}/pos-claim/{claim_id}/confirm"
    secret = os.environ.get("POS_API_SECRET", "")
    try:
        resp = requests.post(url, headers={"X-POS-Secret": secret}, timeout=_TIMEOUT_SECONDS)
        if resp.status_code == 200:
            return True
        log.warning(
            "pos_claim: confirm %s (item %d) returned HTTP %d",
            claim_id, item_id, resp.status_code,
        )
        return False
    except Exception as exc:
        log.warning("pos_claim: confirm %s (item %d) failed: %s", claim_id, item_id, exc)
        return False


def release_pos_claim(item_id: int, claim_id: str) -> bool:
    """Release a POS claim when the ERP sale is rolled back. Best-effort; never raises."""
    base = _commerce_api_base_url()
    url = f"{base}/api/v1/items/{item_id}/pos-claim/{claim_id}"
    secret = os.environ.get("POS_API_SECRET", "")
    try:
        resp = requests.delete(url, headers={"X-POS-Secret": secret}, timeout=_TIMEOUT_SECONDS)
        if resp.status_code == 204:
            return True
        log.warning(
            "pos_claim: release %s (item %d) returned HTTP %d",
            claim_id, item_id, resp.status_code,
        )
        return False
    except Exception as exc:
        log.warning("pos_claim: release %s (item %d) failed: %s", claim_id, item_id, exc)
        return False


def _release_pos_claims_best_effort(claims: list[tuple[int, str]]) -> None:
    """Release multiple pos-claims; swallows all errors (best-effort)."""
    for item_id, claim_id in claims:
        release_pos_claim(item_id, claim_id)


def _confirm_pos_claims_best_effort(claims: list[tuple[int, str]]) -> None:
    """Confirm multiple pos-claims; swallows all errors (best-effort)."""
    for item_id, claim_id in claims:
        confirm_pos_claim(item_id, claim_id)
