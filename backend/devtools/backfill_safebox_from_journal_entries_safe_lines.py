"""Backfill SafeBoxTransaction rows from JournalEntry lines that hit SafeBox accounts.

Use case
- Reconciliation where GL (journal_entry_line) shows cash movement on a SafeBox-linked
  account, but safe_box_transaction is missing.
- Common in legacy/edge flows where JournalEntry.reference_type is invoice_payment or invoice.

Behavior
- For each selected journal entry, finds lines where `journal_entry_line.account_id` matches
  an existing `safe_box.account_id`.
- Aggregates signed cash per safe_box (debit - credit).
- Creates a SafeBoxTransaction (cash only; weights set to 0) when missing.

Reference mapping
- By default, preserves `journal_entry.reference_type/reference_id` into tx.ref_type/ref_id.
  - invoice_payment: sets invoice_payment_id and ref_id=invoice_payment_id.
  - invoice: sets invoice_id and ref_id=invoice_id.
  - voucher/voucher_reversal/...: uses ref_id=reference_id.
- If reference_type is empty/NULL, uses ref_type='journal_entry' and ref_id=journal_entry.id.

Safety
- DRY-RUN by default.
- Use --apply to commit.

Notes
- This tool is intentionally conservative: it will not create rows when it can't
  determine a valid reference id for invoice_payment/invoice.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

from flask import Flask

# Ensure backend/ is importable when running from other working directories (e.g. Docker).
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import bindparam, text

from models import db


def _signed_cash(*, direction: str | None, amount_cash: float | None) -> float:
    dir_norm = (direction or "in").strip().lower() or "in"
    amt = float(amount_cash or 0.0)
    return amt if dir_norm == "in" else -amt


def _normalize_database_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return value
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("sqlite:///") and not value.startswith("sqlite:////"):
        sqlite_path = value[len("sqlite:///") :]
        if sqlite_path and not sqlite_path.startswith("/") and "/" not in sqlite_path and "\\" not in sqlite_path:
            abs_path = os.path.abspath(os.path.join(BACKEND_DIR, sqlite_path))
            return f"sqlite:///{abs_path}"
    return value


def _create_app() -> Flask:
    app = Flask(__name__)
    default_sqlite = f"sqlite:///{os.path.join(BACKEND_DIR, 'app.db')}"
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_database_url(os.getenv("DATABASE_URL", default_sqlite))
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


@dataclass(frozen=True)
class CandidateTx:
    source_je_id: int
    source_reference_type: str | None
    source_reference_id: int | None
    safe_box_id: int
    signed_cash: float
    ref_type: str
    ref_id: int
    invoice_id: int | None
    invoice_payment_id: int | None
    created_at: datetime
    notes: str | None


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    # Accept commas/semicolons/whitespace/newlines.
    normalized = raw.replace(";", ",").replace("\n", ",").replace("\r", ",").replace("\t", ",").replace(" ", ",")
    parts = [p.strip() for p in normalized.split(",")]

    out: list[int] = []
    seen: set[int] = set()
    for p in parts:
        if not p:
            continue
        val = int(p)
        if val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _read_ids_file(path: str) -> list[int]:
    with open(path, "r", encoding="utf-8") as f:
        return _parse_ids(f.read())


def _derive_ref_fields(reference_type: str | None, reference_id: int | None, je_id: int) -> tuple[str, int, int | None, int | None]:
    rt = (reference_type or "").strip()
    rid = reference_id

    if not rt:
        return "journal_entry", int(je_id), None, None

    rt_norm = rt.lower()

    if rt_norm == "invoice_payment":
        if rid in (None, 0):
            raise ValueError("invoice_payment journal_entry is missing reference_id")
        pay_id = int(rid)
        return "invoice_payment", pay_id, None, pay_id

    if rt_norm == "invoice":
        if rid in (None, 0):
            raise ValueError("invoice journal_entry is missing reference_id")
        inv_id = int(rid)
        return "invoice", inv_id, inv_id, None

    # Default: preserve type/id.
    if rid in (None, 0):
        # No meaningful reference id => fall back to JE id.
        return rt, int(je_id), None, None

    return rt, int(rid), None, None


def _voucher_invoice_payment_id_from_notes(notes: str | None) -> int | None:
    if not notes:
        return None
    raw = str(notes).strip()
    if not raw:
        return None
    # Most of our system stores structured info in JSON.
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, dict):
            val = decoded.get("invoice_payment_id")
            if val not in (None, "", False, 0, "0"):
                return int(val)
    except Exception:
        return None
    return None


def _has_similar_invoice_payment_movement(
    *,
    safe_box_id: int,
    direction: str,
    amount_cash: float,
    anchor_ts: datetime,
) -> bool:
    """Heuristic guard against double-counting.

    If a voucher was used to implement an invoice payment, legacy data may already
    contain a SafeBoxTransaction(ref_type='invoice_payment') while the GL references
    the voucher. In that case, inserting a new SafeBoxTransaction(ref_type='voucher')
    would double-count cash.

    Strategy
    - Look for an existing invoice_payment movement with same safe_box_id, direction,
      and amount close to `amount_cash`.
    - First search within a tight window (±2 minutes).
    - If not found, search within the same day (more permissive, but still restricted
      to invoice_payment only).
    """

    try:
        direction_norm = (direction or 'in').strip().lower() or 'in'
    except Exception:
        direction_norm = 'in'

    amt = float(amount_cash or 0.0)
    if amt <= 0:
        return False

    eps = 0.01

    # 1) Tight window ±2 minutes
    from_ts = anchor_ts.replace(second=0, microsecond=0)  # normalize a bit
    to_ts = from_ts
    try:
        from_ts = from_ts - timedelta(minutes=2)
        to_ts = to_ts + timedelta(minutes=2)
    except Exception:
        pass

    row = db.session.execute(
        text(
            "SELECT 1 FROM safe_box_transaction "
            "WHERE safe_box_id = :sid "
            "  AND LOWER(TRIM(COALESCE(ref_type,''))) = 'invoice_payment' "
            "  AND direction = :dir "
            "  AND ABS(COALESCE(amount_cash,0) - :amt) < :eps "
            "  AND created_at >= :from_ts AND created_at <= :to_ts "
            "LIMIT 1"
        ),
        {
            "sid": int(safe_box_id),
            "dir": str(direction_norm),
            "amt": float(amt),
            "eps": float(eps),
            "from_ts": from_ts,
            "to_ts": to_ts,
        },
    ).first()
    if row is not None:
        return True

    # 2) Same day window
    try:
        day_start = anchor_ts.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = anchor_ts.replace(hour=23, minute=59, second=59, microsecond=999999)
    except Exception:
        return False

    row2 = db.session.execute(
        text(
            "SELECT 1 FROM safe_box_transaction "
            "WHERE safe_box_id = :sid "
            "  AND LOWER(TRIM(COALESCE(ref_type,''))) = 'invoice_payment' "
            "  AND direction = :dir "
            "  AND ABS(COALESCE(amount_cash,0) - :amt) < :eps "
            "  AND created_at >= :from_ts AND created_at <= :to_ts "
            "LIMIT 1"
        ),
        {
            "sid": int(safe_box_id),
            "dir": str(direction_norm),
            "amt": float(amt),
            "eps": float(eps),
            "from_ts": day_start,
            "to_ts": day_end,
        },
    ).first()
    return row2 is not None


def _fetch_candidates(je_ids: list[int], include_unposted: bool) -> dict[int, list[CandidateTx]]:
    if not je_ids:
        return {}

    # Fetch journal entries basic info.
    je_rows = (
        db.session.execute(
            text(
                "SELECT id, date, description, reference_type, reference_id, "
                "  COALESCE(is_deleted, FALSE) AS is_deleted, "
                "  COALESCE(is_draft, FALSE) AS is_draft, "
                "  COALESCE(is_posted, TRUE) AS is_posted "
                "FROM journal_entry WHERE id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": list({int(x) for x in je_ids})},
        )
        .mappings()
        .all()
    )

    je_map: dict[int, dict] = {int(r["id"]): dict(r) for r in je_rows if r.get("id") is not None}

    # For voucher-like journal entries, we may need to map to invoice_payment based on voucher.notes.
    voucher_ref_ids: list[int] = []
    for je in je_rows:
        rt = (je.get("reference_type") or "").strip().lower()
        if rt in ("voucher", "voucher_reversal"):
            rid = je.get("reference_id")
            if rid not in (None, 0, "", False):
                try:
                    voucher_ref_ids.append(int(rid))
                except Exception:
                    pass

    voucher_notes_by_id: dict[int, str | None] = {}
    if voucher_ref_ids:
        vrows = (
            db.session.execute(
                text("SELECT id, notes FROM voucher WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
                {"ids": list({int(x) for x in voucher_ref_ids})},
            )
            .mappings()
            .all()
        )
        for vr in vrows:
            try:
                voucher_notes_by_id[int(vr["id"])] = vr.get("notes")
            except Exception:
                continue

    # Aggregate signed cash per JE per SafeBox.
    agg_rows = (
        db.session.execute(
            text(
                "SELECT "
                "  jel.journal_entry_id AS journal_entry_id, "
                "  sb.id AS safe_box_id, "
                "  COALESCE(SUM(COALESCE(jel.cash_debit,0) - COALESCE(jel.cash_credit,0)), 0) AS signed_cash "
                "FROM journal_entry_line jel "
                "JOIN safe_box sb ON sb.account_id = jel.account_id "
                "JOIN journal_entry je ON je.id = jel.journal_entry_id "
                "WHERE jel.journal_entry_id IN :ids "
                "  AND COALESCE(jel.is_deleted, FALSE) = FALSE "
                "  AND COALESCE(je.is_deleted, FALSE) = FALSE "
                "  AND COALESCE(je.is_draft, FALSE) = FALSE "
                + ("" if include_unposted else "  AND COALESCE(je.is_posted, TRUE) = TRUE ")
                + "GROUP BY jel.journal_entry_id, sb.id"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": list({int(x) for x in je_ids})},
        )
        .mappings()
        .all()
    )

    out: dict[int, list[CandidateTx]] = {int(x): [] for x in je_ids}

    for a in agg_rows:
        je_id = int(a["journal_entry_id"])
        safe_box_id = int(a["safe_box_id"])
        signed_cash = float(a.get("signed_cash") or 0.0)
        if abs(signed_cash) <= 0.005:
            continue

        je = je_map.get(je_id)
        if not je:
            continue

        if bool(je.get("is_deleted")) or bool(je.get("is_draft")):
            continue
        if (not include_unposted) and (not bool(je.get("is_posted"))):
            continue

        try:
            reference_type = je.get("reference_type")
            reference_id = je.get("reference_id")

            # Special case: vouchers that represent invoice payments.
            rt_norm = (reference_type or "").strip().lower()
            if rt_norm in ("voucher", "voucher_reversal") and reference_id not in (None, 0, "", False):
                try:
                    voucher_id = int(reference_id)
                except Exception:
                    voucher_id = None
                if voucher_id is not None:
                    pay_id = _voucher_invoice_payment_id_from_notes(voucher_notes_by_id.get(voucher_id))
                    if pay_id is not None:
                        ref_type, ref_id, invoice_id, invoice_payment_id = ("invoice_payment", int(pay_id), None, int(pay_id))
                    else:
                        ref_type, ref_id, invoice_id, invoice_payment_id = _derive_ref_fields(reference_type, reference_id, je_id)
                else:
                    ref_type, ref_id, invoice_id, invoice_payment_id = _derive_ref_fields(reference_type, reference_id, je_id)
            else:
                ref_type, ref_id, invoice_id, invoice_payment_id = _derive_ref_fields(reference_type, reference_id, je_id)
        except Exception:
            # Conservative skip: if we can't derive a valid reference for invoice/invoice_payment.
            continue

        created_at = je.get("date") or datetime.utcnow()
        notes = je.get("description")

        out.setdefault(je_id, []).append(
            CandidateTx(
                source_je_id=je_id,
                source_reference_type=str(je.get("reference_type")) if je.get("reference_type") is not None else None,
                source_reference_id=(int(je.get("reference_id")) if je.get("reference_id") not in (None, 0, '', False) else None),
                safe_box_id=safe_box_id,
                signed_cash=signed_cash,
                ref_type=str(ref_type),
                ref_id=int(ref_id),
                invoice_id=int(invoice_id) if invoice_id is not None else None,
                invoice_payment_id=int(invoice_payment_id) if invoice_payment_id is not None else None,
                created_at=created_at,
                notes=str(notes) if notes not in (None, "") else None,
            )
        )

    return out


def _tx_exists(c: CandidateTx) -> bool:
    exists, _reason = _tx_exists_reason(c)
    return exists


def _tx_exists_reason(c: CandidateTx) -> tuple[bool, str]:
    # Global safety: if we already have a JE-derived safebox row, do not insert another
    # row under a different reference type (invoice/invoice_payment/etc) for the same JE.
    je_row = db.session.execute(
        text(
            "SELECT 1 FROM safe_box_transaction "
            "WHERE safe_box_id = :sid AND LOWER(TRIM(COALESCE(ref_type,''))) = 'journal_entry' AND ref_id = :jeid "
            "LIMIT 1"
        ),
        {"sid": int(c.safe_box_id), "jeid": int(c.source_je_id)},
    ).first()
    if je_row is not None:
        return True, "existing:journal_entry_guard"

    # Extra guard: voucher/voucher_reversal rows can represent invoice payments.
    # If we couldn't map voucher->invoice_payment via notes, try a similarity check
    # against existing invoice_payment safebox movements to avoid double counting.
    rt_norm = (c.ref_type or '').strip().lower()
    src_rt_norm = (c.source_reference_type or '').strip().lower()
    if rt_norm in ('voucher', 'voucher_reversal') and src_rt_norm in ('voucher', 'voucher_reversal'):
        direction = 'in' if float(c.signed_cash or 0.0) > 0 else 'out'
        if _has_similar_invoice_payment_movement(
            safe_box_id=int(c.safe_box_id),
            direction=direction,
            amount_cash=abs(float(c.signed_cash or 0.0)),
            anchor_ts=c.created_at,
        ):
            return True, "guard:similar_invoice_payment"

    # Match existing tx conservatively by the most specific linkage we have.
    if (c.ref_type or "").strip().lower() == "invoice_payment":
        # For invoice_payment we check both invoice_payment_id and ref_id == pay_id.
        row = (
            db.session.execute(
                text(
                    "SELECT id, direction, amount_cash, invoice_payment_id, ref_id "
                    "FROM safe_box_transaction "
                    "WHERE safe_box_id = :sid "
                    "  AND LOWER(TRIM(COALESCE(ref_type,''))) = 'invoice_payment' "
                    "  AND (invoice_payment_id = :pay OR (invoice_payment_id IS NULL AND ref_id = :pay)) "
                    "ORDER BY created_at DESC "
                    "LIMIT 1"
                ),
                {"sid": int(c.safe_box_id), "pay": int(c.ref_id)},
            )
            .mappings()
            .first()
        )
        if row is None:
            return False, "missing"

        existing_signed = _signed_cash(direction=row.get("direction"), amount_cash=row.get("amount_cash"))
        candidate_signed = float(c.signed_cash or 0.0)
        if abs(existing_signed - candidate_signed) > 0.01:
            return (
                True,
                "existing:invoice_payment(amount_mismatch id={id} existing={existing:.2f} candidate={cand:.2f} existing_ref_id={erid} existing_pay_id={epid})".format(
                    id=int(row.get("id")),
                    existing=float(existing_signed),
                    cand=float(candidate_signed),
                    erid=row.get("ref_id"),
                    epid=row.get("invoice_payment_id"),
                ),
            )

        return True, "existing:invoice_payment"

    if (c.ref_type or "").strip().lower() == "invoice":
        row = (
            db.session.execute(
                text(
                    "SELECT id, direction, amount_cash, invoice_id, ref_id "
                    "FROM safe_box_transaction "
                    "WHERE safe_box_id = :sid "
                    "  AND LOWER(TRIM(COALESCE(ref_type,''))) = 'invoice' "
                    "  AND (invoice_id = :iid OR (invoice_id IS NULL AND ref_id = :iid)) "
                    "ORDER BY created_at DESC "
                    "LIMIT 1"
                ),
                {"sid": int(c.safe_box_id), "iid": int(c.ref_id)},
            )
            .mappings()
            .first()
        )
        if row is None:
            return False, "missing"

        existing_signed = _signed_cash(direction=row.get("direction"), amount_cash=row.get("amount_cash"))
        candidate_signed = float(c.signed_cash or 0.0)
        if abs(existing_signed - candidate_signed) > 0.01:
            return (
                True,
                "existing:invoice(amount_mismatch id={id} existing={existing:.2f} candidate={cand:.2f} existing_ref_id={erid} existing_invoice_id={eid})".format(
                    id=int(row.get("id")),
                    existing=float(existing_signed),
                    cand=float(candidate_signed),
                    erid=row.get("ref_id"),
                    eid=row.get("invoice_id"),
                ),
            )

        return True, "existing:invoice"

    row = db.session.execute(
        text(
            "SELECT 1 FROM safe_box_transaction "
            "WHERE safe_box_id = :sid AND LOWER(TRIM(COALESCE(ref_type,''))) = LOWER(TRIM(:rt)) AND ref_id = :rid "
            "LIMIT 1"
        ),
        {"sid": int(c.safe_box_id), "rt": str(c.ref_type), "rid": int(c.ref_id)},
    ).first()
    return (row is not None), ("existing:ref_type_ref_id" if row is not None else "missing")


def _insert_tx(c: CandidateTx, created_by: str) -> None:
    direction = "in" if c.signed_cash > 0 else "out"
    amount_cash = abs(float(c.signed_cash))

    db.session.execute(
        text(
            "INSERT INTO safe_box_transaction "
            "(safe_box_id, ref_type, ref_id, invoice_id, invoice_payment_id, payment_method_id, direction, amount_cash, "
            " weight_18k, weight_21k, weight_22k, weight_24k, notes, created_at, created_by) "
            "VALUES "
            "(:safe_box_id, :ref_type, :ref_id, :invoice_id, :invoice_payment_id, :payment_method_id, :direction, :amount_cash, "
            " 0, 0, 0, 0, :notes, :created_at, :created_by)"
        ),
        {
            "safe_box_id": int(c.safe_box_id),
            "ref_type": str(c.ref_type),
            "ref_id": int(c.ref_id),
            "invoice_id": int(c.invoice_id) if c.invoice_id is not None else None,
            "invoice_payment_id": int(c.invoice_payment_id) if c.invoice_payment_id is not None else None,
            "payment_method_id": None,
            "direction": direction,
            "amount_cash": float(amount_cash),
            "notes": c.notes,
            "created_at": c.created_at,
            "created_by": created_by,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill SafeBoxTransaction from JournalEntry lines that hit SafeBox accounts.")
    parser.add_argument("--apply", action="store_true", help="Commit changes (default: dry-run).")
    parser.add_argument(
        "--je-ids",
        type=str,
        default=None,
        help="Comma-separated journal_entry ids (e.g. 1118,1323,1257).",
    )
    parser.add_argument(
        "--je-ids-file",
        type=str,
        default=None,
        help="Path to a text file containing journal_entry ids (comma/newline/space separated).",
    )
    parser.add_argument(
        "--include-unposted",
        action="store_true",
        help="Include unposted journal entries (default: only posted).",
    )
    parser.add_argument("--created-by", type=str, default="devtool", help="Value for safe_box_transaction.created_by")
    parser.add_argument("--verbose", action="store_true", help="Print per-entry actions.")

    args = parser.parse_args()

    je_ids: list[int] = []
    if args.je_ids_file:
        try:
            je_ids.extend(_read_ids_file(str(args.je_ids_file)))
        except Exception as exc:
            print(f"Failed reading --je-ids-file: {exc}")
            return 2
    if args.je_ids:
        je_ids.extend(_parse_ids(args.je_ids))

    # De-dup preserve order
    seen: set[int] = set()
    je_ids = [x for x in je_ids if not (x in seen or seen.add(x))]
    if not je_ids:
        print("No JE IDs provided. Use --je-ids or --je-ids-file.")
        return 2

    dry_run = not bool(args.apply)

    app = _create_app()
    with app.app_context():
        candidates_by_je = _fetch_candidates(je_ids=je_ids, include_unposted=bool(args.include_unposted))

        would_insert = 0
        inserted = 0
        skipped_existing = 0
        skipped_no_safe_lines = 0

        for je_id in je_ids:
            cands = candidates_by_je.get(int(je_id)) or []
            if not cands:
                skipped_no_safe_lines += 1
                if args.verbose:
                    print(f"je_id={je_id}: no SafeBox-linked cash lines (or filtered out)")
                continue

            for c in cands:
                if _tx_exists(c):
                    skipped_existing += 1
                    if args.verbose:
                        exists, reason = _tx_exists_reason(c)
                        print(
                            f"je_id={je_id} safe_box_id={c.safe_box_id}: skip ({reason}) ({c.ref_type}:{c.ref_id}) src=({(c.source_reference_type or '')}:{(c.source_reference_id or '')})"
                        )
                    continue

                would_insert += 1
                direction = "in" if c.signed_cash > 0 else "out"
                if args.verbose or dry_run:
                    print(
                        f"je_id={je_id} safe_box_id={c.safe_box_id}: INSERT {c.ref_type}:{c.ref_id} {direction} {abs(c.signed_cash):.2f}"
                    )

                if dry_run:
                    continue

                _insert_tx(c, created_by=str(args.created_by))
                inserted += 1

        if dry_run:
            print(
                f"[DRY RUN] would_insert={would_insert} skipped_existing={skipped_existing} skipped_no_safe_lines={skipped_no_safe_lines}"
            )
            print("Run again with --apply to commit.")
        else:
            db.session.commit()
            print(
                f"[APPLIED] inserted={inserted} skipped_existing={skipped_existing} skipped_no_safe_lines={skipped_no_safe_lines}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
