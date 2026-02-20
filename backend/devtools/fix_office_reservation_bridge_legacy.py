#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Fix legacy office-reservation postings that went through the Purchase Bridge (جسر المشتريات).

This devtool targets the specific legacy pattern observed in production:
- An office reservation JE (often entry_number like WGT-YYYY-NNNNN) posts:
  - Purchase Bridge (e.g., acc_no 1710) with cash_debit and weight_debit
  - Office supplier financial account with cash_credit and weight_credit
  - Execution lines that move some weight from bridge -> inventory
- A later "تصحيح اتجاه الوزن" adjustment might have been created incorrectly against the bridge
  (because the legacy fix script heuristics picked the cash_debit line as "inventory").

What this script does (safe & fast):
1) Cash reclass: move bridge cash_debit to inventory cash_debit:
   - Inventory: cash_debit = amount
   - Bridge:    cash_credit = amount
   This zeros the bridge cash balance for the reservation.

2) Weight correction repair (if detected): if a "تصحيح اتجاه الوزن" JE has its "inventory" line
   posted to the bridge account (weight credit), shift that weight credit from bridge -> inventory:
   - Bridge:    weight_debit  = amount
   - Inventory: weight_credit = amount

Safety
- Default is DRY RUN.
- Use --apply to write.
- Idempotent: skips if it finds prior posted adjustments with the same markers.

Usage (inside container)
  export BYPASS_AUTH_FOR_DEVELOPMENT=1
  python3 /app/backend/devtools/fix_office_reservation_bridge_legacy.py --reservation-id 4
  python3 /app/backend/devtools/fix_office_reservation_bridge_legacy.py --reservation-id 4 --apply

DB targeting
- Point at the correct DB via DATABASE_URL if needed.
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("BYPASS_AUTH_FOR_DEVELOPMENT", "1")

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from dual_system_helpers import create_dual_journal_entry, verify_dual_balance  # noqa: E402
from models import Account, JournalEntry, JournalEntryLine, OfficeReservation, db  # noqa: E402


_MARK_CASH = "تصحيح جسر المشتريات (نقد)"
_MARK_WEIGHT = "تصحيح جسر المشتريات (وزن)"
_MARK_RESIDUAL = "إقفال رصيد الجسر (وزن)"


def _as_float(v) -> float:
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def _find_account_by_id(account_id: int) -> Account | None:
    try:
        return db.session.query(Account).filter(Account.id == int(account_id)).first()
    except Exception:
        return None


def _is_bridge_account(acc: Account | None) -> bool:
    if not acc:
        return False
    code = (acc.account_number or "").strip()
    name = (acc.name or "").strip()
    if code == "1710" or code.startswith("1710"):
        return True
    if "جسر" in name:
        return True
    if "bridge" in name.lower():
        return True
    return False


def _is_inventory_account(acc: Account | None) -> bool:
    if not acc:
        return False
    code = (acc.account_number or "").strip()
    name = (acc.name or "").strip()
    # Common inventory roots in this repo: 1310, 1200, etc.
    if code in ("1310", "1200") or code.startswith("1310") or code.startswith("1200"):
        return True
    if "مخزون" in name:
        return True
    if "inventory" in name.lower():
        return True
    return False


def _has_marker(reservation_id: int, marker: str) -> bool:
    q = db.session.query(JournalEntry)
    q = q.filter(JournalEntry.is_deleted == False)  # noqa: E712
    q = q.filter(JournalEntry.reference_type == "office_reservation")
    q = q.filter(JournalEntry.reference_id == int(reservation_id))
    q = q.filter(JournalEntry.is_posted == True)  # noqa: E712
    q = q.filter(JournalEntry.description.ilike(f"%{marker}%"))
    return q.first() is not None


def _karat_amounts(line: JournalEntryLine) -> list[tuple[int, float, float]]:
    out: list[tuple[int, float, float]] = []
    for k in (18, 21, 22, 24):
        d = _as_float(getattr(line, f"debit_{k}k", 0.0))
        c = _as_float(getattr(line, f"credit_{k}k", 0.0))
        if abs(d) > 1e-9 or abs(c) > 1e-9:
            out.append((k, d, c))
    return out


def _sum_karat_amounts(lines: list[JournalEntryLine], *, field_prefix: str) -> dict[int, float]:
    """Sum karat amounts for lines.

    field_prefix: 'debit' or 'credit'
    """
    totals: dict[int, float] = {18: 0.0, 21: 0.0, 22: 0.0, 24: 0.0}
    for ln in lines:
        for k in (18, 21, 22, 24):
            v = _as_float(getattr(ln, f"{field_prefix}_{k}k", 0.0))
            totals[k] += float(v)
    # Drop zeros
    return {k: v for k, v in totals.items() if abs(v) > 1e-9}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Fix legacy office_reservation postings that went through purchase bridge")
    p.add_argument("--reservation-id", type=int, required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--posted-by", default="system")
    args = p.parse_args(argv)

    apply = bool(args.apply)

    with app.app_context():
        reservation = db.session.query(OfficeReservation).filter(OfficeReservation.id == int(args.reservation_id)).first()
        if not reservation:
            print("NOT FOUND: reservation")
            return 2

        entries = (
            db.session.query(JournalEntry)
            .filter(JournalEntry.is_deleted == False)  # noqa: E712
            .filter(JournalEntry.reference_type == "office_reservation")
            .filter(JournalEntry.reference_id == int(reservation.id))
            .filter(JournalEntry.is_posted == True)  # noqa: E712
            .filter(JournalEntry.is_draft == False)  # noqa: E712
            .order_by(JournalEntry.date.asc(), JournalEntry.id.asc())
            .all()
        )

        if not entries:
            print("NOT FOUND: no posted entries for reservation")
            return 2

        # Find involved accounts and amounts.
        bridge_line_cash: tuple[int, float] | None = None  # (bridge_account_id, cash_debit)
        inventory_account_id: int | None = None

        bridge_account_id_weight: int | None = None
        bridge_weight_debit_lines: list[JournalEntryLine] = []
        bridge_weight_credit_lines: list[JournalEntryLine] = []
        inventory_weight_debit_lines: list[JournalEntryLine] = []

        # Also locate a "weight fix" entry that incorrectly posted "inventory" to bridge.
        wrong_weight_fix: tuple[JournalEntry, JournalEntryLine] | None = None

        for je in entries:
            lines = (
                db.session.query(JournalEntryLine)
                .filter(JournalEntryLine.journal_entry_id == int(je.id))
                .filter((JournalEntryLine.is_deleted == False) | (JournalEntryLine.is_deleted.is_(None)))  # noqa: E712
                .order_by(JournalEntryLine.id.asc())
                .all()
            )

            for ln in lines:
                acc = _find_account_by_id(int(ln.account_id)) if ln.account_id else None
                if inventory_account_id is None and _is_inventory_account(acc):
                    inventory_account_id = int(ln.account_id)

                # Collect weight movements for residual bridge weight closure.
                if acc and _is_bridge_account(acc):
                    bridge_account_id_weight = int(ln.account_id)
                    if any(d > 0 for _, d, _ in _karat_amounts(ln)):
                        bridge_weight_debit_lines.append(ln)
                    if any(c > 0 for _, _, c in _karat_amounts(ln)):
                        bridge_weight_credit_lines.append(ln)

                if acc and _is_inventory_account(acc):
                    if any(d > 0 for _, d, _ in _karat_amounts(ln)):
                        inventory_weight_debit_lines.append(ln)

                if bridge_line_cash is None and _is_bridge_account(acc):
                    cd = _as_float(getattr(ln, "cash_debit", 0.0))
                    if cd > 0:
                        bridge_line_cash = (int(ln.account_id), cd)

            # Detect the known-bad pattern: "تصحيح اتجاه الوزن" entry whose first line is on bridge.
            if (je.description or "").find("تصحيح اتجاه الوزن") >= 0:
                for ln in lines:
                    acc = _find_account_by_id(int(ln.account_id)) if ln.account_id else None
                    if _is_bridge_account(acc):
                        # Must be a pure-weight line (no cash) with credit weight.
                        has_cash = _as_float(getattr(ln, "cash_debit", 0.0)) != 0.0 or _as_float(getattr(ln, "cash_credit", 0.0)) != 0.0
                        if has_cash:
                            continue
                        karats = _karat_amounts(ln)
                        if any(c > 0 and d <= 0 for _, d, c in karats):
                            wrong_weight_fix = (je, ln)
                            break

        if inventory_account_id is None:
            print("ERROR: could not determine inventory account from reservation entries")
            return 3

        # Plan/apply cash reclass.
        if bridge_line_cash is None:
            print("NOTE: no bridge cash_debit line detected; skipping cash reclass")
        else:
            bridge_account_id, cash_amount = bridge_line_cash
            if _has_marker(int(reservation.id), _MARK_CASH):
                print("SKIP: cash marker already applied")
            else:
                print(f"{'APPLY' if apply else 'PLAN'} CASH: move {cash_amount:.2f} from bridge({bridge_account_id}) -> inventory({inventory_account_id})")
                if apply:
                    adj = JournalEntry(
                        date=entries[-1].date,
                        description=f"{_MARK_CASH} - RES#{reservation.id}",
                        entry_type="تصحيح",
                        reference_type="office_reservation",
                        reference_id=int(reservation.id),
                        is_posted=True,
                        posted_at=entries[-1].date,
                        posted_by=str(args.posted_by or "system"),
                        created_by=str(args.posted_by or "system"),
                    )
                    db.session.add(adj)
                    db.session.flush()

                    create_dual_journal_entry(
                        journal_entry_id=adj.id,
                        account_id=int(inventory_account_id),
                        cash_debit=float(cash_amount),
                        description="إعادة تصنيف نقدية من الجسر إلى المخزون",
                        exclude_from_ledger=True,
                        apply_golden_rule=False,
                    )
                    create_dual_journal_entry(
                        journal_entry_id=adj.id,
                        account_id=int(bridge_account_id),
                        cash_credit=float(cash_amount),
                        description="إقفال نقدية الجسر (إعادة تصنيف)",
                        exclude_from_ledger=True,
                        apply_golden_rule=False,
                    )
                    verify_dual_balance(adj.id)

        # Plan/apply weight fix repair.
        if wrong_weight_fix is None:
            print("NOTE: no wrong weight-fix pattern detected; skipping weight repair")
        else:
            if _has_marker(int(reservation.id), _MARK_WEIGHT):
                print("SKIP: weight marker already applied")
            else:
                je_fix, ln_bridge = wrong_weight_fix
                karats = _karat_amounts(ln_bridge)
                # We only support the simple case: bridge line has credit weights, no debits.
                amounts: list[tuple[int, float]] = []
                for k, d, c in karats:
                    if c > 0 and d <= 0:
                        amounts.append((k, c))
                if not amounts:
                    print("NOTE: wrong weight-fix found but no usable credit weights")
                else:
                    summary = ", ".join([f"{k}k:{w:.3f}g" for k, w in amounts])
                    print(
                        f"{'APPLY' if apply else 'PLAN'} WEIGHT: shift [{summary}] credit from bridge({ln_bridge.account_id}) -> inventory({inventory_account_id}) "
                        f"(fix JE#{je_fix.id})"
                    )
                    if apply:
                        adj = JournalEntry(
                            date=je_fix.date,
                            description=f"{_MARK_WEIGHT} - RES#{reservation.id} - fix JE#{je_fix.id}",
                            entry_type="تصحيح",
                            reference_type="office_reservation",
                            reference_id=int(reservation.id),
                            is_posted=True,
                            posted_at=je_fix.date,
                            posted_by=str(args.posted_by or "system"),
                            created_by=str(args.posted_by or "system"),
                        )
                        db.session.add(adj)
                        db.session.flush()

                        for k, w in amounts:
                            karat_debit = f"debit_{k}k"
                            karat_credit = f"credit_{k}k"
                            create_dual_journal_entry(
                                journal_entry_id=adj.id,
                                account_id=int(ln_bridge.account_id),
                                description=f"إلغاء تصحيح وزن خاطئ على الجسر ({k}k)",
                                exclude_from_ledger=True,
                                apply_golden_rule=False,
                                **{karat_debit: float(w)},
                            )
                            create_dual_journal_entry(
                                journal_entry_id=adj.id,
                                account_id=int(inventory_account_id),
                                description=f"تطبيق تصحيح الوزن على المخزون ({k}k)",
                                exclude_from_ledger=True,
                                apply_golden_rule=False,
                                **{karat_credit: float(w)},
                            )

                        verify_dual_balance(adj.id)

        # Close residual bridge weight (e.g., 12.5g) to inventory when the reservation left a weight debit on bridge.
        if bridge_account_id_weight is None:
            print("NOTE: no bridge account detected for residual weight closure")
        else:
            if _has_marker(int(reservation.id), _MARK_RESIDUAL):
                print("SKIP: residual weight marker already applied")
            else:
                bridge_debits = _sum_karat_amounts(bridge_weight_debit_lines, field_prefix="debit")
                bridge_credits = _sum_karat_amounts(bridge_weight_credit_lines, field_prefix="credit")
                inv_debits = _sum_karat_amounts(inventory_weight_debit_lines, field_prefix="debit")

                residuals: list[tuple[int, float]] = []
                for k in sorted(set(list(bridge_debits.keys()) + list(bridge_credits.keys()))):
                    d = float(bridge_debits.get(k, 0.0))
                    c = float(bridge_credits.get(k, 0.0))
                    if d > 0 and c >= 0:
                        r = d - c
                        if r > 0.001:
                            # Heuristic safety: only auto-close if inventory debit equals bridge credit (the executed amount)
                            # which indicates the remaining balance is just a leftover on bridge.
                            inv_d = float(inv_debits.get(k, 0.0))
                            if c > 0 and abs(inv_d - c) <= 0.001:
                                residuals.append((k, r))

                if not residuals:
                    print("NOTE: no residual bridge weight detected")
                else:
                    summary = ", ".join([f"{k}k:{w:.3f}g" for k, w in residuals])
                    print(
                        f"{'APPLY' if apply else 'PLAN'} RESIDUAL: move leftover weight [{summary}] from bridge({bridge_account_id_weight}) -> inventory({inventory_account_id})"
                    )
                    if apply:
                        adj = JournalEntry(
                            date=entries[-1].date,
                            description=f"{_MARK_RESIDUAL} - RES#{reservation.id}",
                            entry_type="تصحيح",
                            reference_type="office_reservation",
                            reference_id=int(reservation.id),
                            is_posted=True,
                            posted_at=entries[-1].date,
                            posted_by=str(args.posted_by or "system"),
                            created_by=str(args.posted_by or "system"),
                        )
                        db.session.add(adj)
                        db.session.flush()

                        for k, w in residuals:
                            karat_debit = f"debit_{k}k"
                            karat_credit = f"credit_{k}k"
                            create_dual_journal_entry(
                                journal_entry_id=adj.id,
                                account_id=int(inventory_account_id),
                                description=f"إضافة وزن متبقي من الجسر للمخزون ({k}k)",
                                exclude_from_ledger=True,
                                apply_golden_rule=False,
                                **{karat_debit: float(w)},
                            )
                            create_dual_journal_entry(
                                journal_entry_id=adj.id,
                                account_id=int(bridge_account_id_weight),
                                description=f"إقفال وزن متبقي على الجسر ({k}k)",
                                exclude_from_ledger=True,
                                apply_golden_rule=False,
                                **{karat_credit: float(w)},
                            )

                        verify_dual_balance(adj.id)

        if apply:
            db.session.commit()
            print("DONE")
        else:
            db.session.rollback()
            print("DRY RUN DONE")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
