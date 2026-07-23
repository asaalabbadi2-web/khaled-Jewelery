# ERP Seam Ledger

**Authority:** ADR-023 M1 — The Seam Rule  
**Rule:** Every PR that touches `backend/` for integration purposes adds a row here.  
A touched ERP file with no ledger row = review rejection.

**Ratchet baseline:** `docs/architecture/.erp-seam-ratchet`  
**CI gate:** `scripts/erp_seam_ratchet.py` (runs on `backend/**` changes)

---

## How to Add a Row

1. Copy the last row as a template.
2. Fill in all columns — partial rows are not accepted.
3. "Contract Tests" must name the specific test file and count, not just ✅.
4. If no tests were added (because the touch was infrastructure-only), write ❌ and explain why in "What Was Raised".
5. After adding the row, run `scripts/erp_seam_ratchet.py` locally and update `docs/architecture/.erp-seam-ratchet` if the tested count increased.

---

## Contract-Test Coverage Standard

A route has contract tests when at least one of these is true:
- A `tests/test_*.py` file covers its happy path + idempotency + auth failure.
- An integration test covers its full request/response cycle (not just unit mocks).

---

## Ledger

| # | ERP File / Route | Date | Integration Touch | Raised to Standard | Contract Tests | PR / Sprint |
|---|-----------------|------|-------------------|--------------------|----------------|-------------|
| 1 | `backend/routes/__init__.py` | 2026-07-18 | Re-exports for test compatibility — `approve_voucher`, `update_voucher` (→ routes.vouchers); `_create_postgres_backup_to_file`, `_restore_postgres_from_backup_file`, `_is_postgres_database`, `_pg_tools_available`, `_postgres_conn_parts` (→ routes.system); `_ensure_karat_diff_expense_account` (→ routes.invoices) | Module exports made consistent with test expectations; functions that moved to submodules now re-exported so their tests can find them | ✅ 8 tests across `test_voucher_edit_and_equivalent.py`, `test_voucher_party_tagging.py`, `test_postgres_backup_restore_helpers.py` (3 previously uncollectable files now pass) | E1 / Sprint 9 |
| 2 | `backend/historical_clearing_adjustment_service.py` | 2026-07-18 | Python 3.9 compatibility — `str \| None` union syntax fails at runtime without `from __future__ import annotations` | Added `from __future__ import annotations`; annotations now lazy-evaluated (PEP 563) | ✅ Unblocked 15 tests in `tests/test_historical_clearing_adjustment.py` (were ERROR at setup; still require live-DB fixture SafeBox id=32 but no longer fail at import) | E1 / Sprint 9 |
| 3 | `backend/test_postgres_backup_restore_helpers.py` | 2026-07-18 | Patch target mismatch — `patch('routes._is_postgres_database')` patches the re-exported name in `routes/__init__`, but `_create_postgres_backup_to_file` in `routes/system.py` calls its own local reference | Fixed all patch targets to `routes.system.*` (same for `_pg_tools_available`, `_postgres_conn_parts`, `subprocess.run`, `db.session.remove`, `db.engine.dispose`) | ✅ 3 tests pass (previously `RuntimeError: PostgreSQL backend is not active`) | E1 / Sprint 9 |
| 4 | `backend/pytest.ini` | 2026-07-18 | Three test files existed but were not in `testpaths` — they passed when run explicitly but were invisible to the standard CI gate | Added `test_voucher_edit_and_equivalent.py`, `test_voucher_party_tagging.py`, `test_postgres_backup_restore_helpers.py` to `testpaths` | ✅ Suite grows from 106 → 114 passing; all 3 files now part of the standard gate | E1 / Sprint 9 |
| 5 | `backend/conftest.py` | 2026-07-18 | `tests/test_historical_clearing_adjustment.py` required SafeBox id=32 (مدى) pre-seeded — 15 tests were ERROR at setup. Root cause: fixture assumed live DB. Diagnostic: `voucher_engine.py:216` skips `supplier_id` tagging for accounts linked to a SafeBox — so SafeBox must NOT share Account 15 (cash). Fix: seed Account 1610 (خزينة مدى) as the dedicated SafeBox ledger account, then SafeBox(id=32, account_id=1610) | Added Account 1610 + SafeBox 32 to `initialize_db`; added explanatory comment documenting the safe-account constraint | ✅ 15 previously-ERRORing tests now pass; full suite: **129 passed, 0 errors** | E1 / Sprint 9 |
| 6 | `backend/internal_routes.py` | 2026-07-18 | E2 — contract tests for ERP sync internal API. Covers: C1 happy path (Invoice + stock--, 201); C2 atomicity (forced commit failure → nothing written — the real invariant test); C3a/C3b auth (absent secret → 503, wrong secret → 403, both verify no write); C4 idempotency (same commerce_order_id twice → one Invoice, stock-- once); C5 unknown item → 404; C6 out of stock → 409; C7a/C7b reconcile found/not-found | ✅ 9 tests in `tests/test_internal_routes.py`; full suite: **138 passed, 0 errors** | E2 / Sprint 9 |
| 7 | `backend/routes/invoices.py` + `backend/services/commerce_availability.py` | 2026-07-18 | E4 — Gate B POS availability check. Service-level check injected BEFORE ANY WRITE into `add_invoice()`. Calls `GET /items/{id}/availability` on Commerce API (2 s timeout). ACTIVE reservation → 409 + zero writes. Fail-open: timeout/down → sale allowed + WARNING + `gate_b_fail_open_total` counter. ADR-016 updated: INV-4 → "ENFORCED AT POS WITH BOUNDED FAIL-OPEN WINDOW". | ✅ 10 tests in `tests/test_pos_availability_check.py`: B1 reserved→409, B2 zero-writes (load-bearing), B3 available→passes, B5 timeout→fail-open; full suite: **160 passed, 0 errors** | E4 / Sprint 9 |
## Pending Rows (to be filled when the work is done)

| # | Expected Touch | Sprint | Who |
|---|---------------|--------|-----|
| 8 | (next integration touch) | — | — |

## Architectural Debt Register

Rows here document **coupling discovered during integration work** that is not yet fixed.
These rows are NOT counted by the ratchet (they are not integration touches requiring immediate
contract tests). Each row must carry a target milestone and owner.

| File | Line | Debt Description | Discovered | Target Milestone | Owner |
|------|------|-----------------|------------|-----------------|-------|
| `backend/voucher_engine.py` | 216 | `should_tag_party = False` for any account linked to a SafeBox — couples an accounting rule (suppress supplier_id tagging) to an infrastructure concept (SafeBox). A reviewer reading the tagging logic must know about SafeBox infrastructure to understand why some transactions are exempt. Violates domain/infrastructure boundary. | E1 / Sprint 9 | ADR-023 M2.3 (accounting strangling: ERP→Domain migration) | TBD at M2.3 kick-off |
| `backend/services/inventory_*.py`, `backend/services/journals.py` | various | **TIME-001** — 15 bare `datetime.now()` calls in ERP inventory and journal services that use wall-clock time directly in business logic (created_at, counted_at, approved_at, now= assignments). Suppressed with `# clock-guard: TIME-001`; count tracked in `docs/architecture/.clock-debt-baseline` (currently 15). Ratchet: count may only decrease; adding new suppressions fails CI. Terminal fix: inject `now: datetime` per ADR-015 on first modification of each module. See §4.6 Known Gaps. Note: `pricing/engine.py:quoted_at` was initially misclassified here — it is `record-only` (audit metadata, not a decision gate) and is NOT part of the 15-count. | Sprint 9 (clock_guard introduction) | First modification of each affected module | ADR-015 owner (next engineering touch per ADR-023 seam rule) |
| `apps/commerce-api/src/yasargold_commerce/workers/reconciliation_worker.py` | — | **LOCAL-SCHEDULER-001** — `ReconciliationWorker` has only `run_once()`, no `run_forever()`. In local staging (`run_workers.py`) it is wrapped in a manual daemon-thread polling loop. Daemon threads die with the API process — if commerce-api restarts, reconciliation stops until the workers container is also restarted. **In production, `ReconciliationWorker` MUST run in a separate container with its own restart policy and an external scheduler (cron/Celery beat/k8s CronJob), NOT as a thread inside the API process.** Reconciliation is the last-resort accounting guard (N4); losing it silently is a financial integrity risk. | Sprint 9 (local staging) | Before production deploy of reconciliation | Ops / Commerce API owner |

---

## Ratchet History

| Date | Tested | Total | % | Change |
|------|--------|-------|---|--------|
| 2026-07-18 | 4 | 4 | 100% | Initial ledger (E1 retro) |
| 2026-07-18 | 5 | 5 | 100% | conftest SafeBox fixture (E1 continuation) |
| 2026-07-18 | 6 | 6 | 100% | internal_routes.py contract tests C1–C7b (E2) |
| 2026-07-18 | 7 | 7 | 100% | Gate B POS availability check (E4) |
