#!/usr/bin/env python3
"""Diagnose mismatches between supplier ledger vs supplier statement.

Goal:
- Identify suppliers where `/suppliers/<id>/ledger` and `/suppliers/<id>/statement`
  are inconsistent (missing lines / different closing balances).

This script runs directly against the configured DB (DATABASE_URL or local sqlite).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, or_, func

from app import app
from models import Supplier, JournalEntryLine, JournalEntry, Account


@dataclass(frozen=True)
class SupplierDiff:
    supplier_id: int
    supplier_name: str
    ledger_count: int
    statement_count: int
    ledger_cash_net: float
    statement_cash_net: float
    ledger_gold_main_net: float
    statement_gold_main_net: float
    allowed_ids: list[int]


def _get_allowed_ids(supplier: Supplier) -> list[int]:
    supplier_fin_account_id = getattr(supplier, "account_id", None)
    supplier_memo_account_id = None

    try:
        fin_acc = (
            Account.query.get(int(supplier_fin_account_id))
            if supplier_fin_account_id
            else None
        )
        supplier_memo_account_id = (
            getattr(fin_acc, "memo_account_id", None) if fin_acc else None
        )
    except Exception:
        supplier_memo_account_id = None

    allowed_ids: list[int] = []
    for value in (supplier_fin_account_id, supplier_memo_account_id):
        try:
            if value not in (None, "", 0, "0", False):
                allowed_ids.append(int(value))
        except Exception:
            pass

    # Dedupe while preserving order.
    seen: set[int] = set()
    result: list[int] = []
    for v in allowed_ids:
        if v in seen:
            continue
        seen.add(v)
        result.append(v)
    return result


def _payable_filter():
    return and_(Account.type == "Liability", Account.account_number.like("21%"))


def _account_filter(allowed_ids: list[int]):
    base = _payable_filter()
    if not allowed_ids:
        return base
    return or_(Account.id.in_(allowed_ids), base)


def _relaxed_account_filter():
    # No account restriction (used to detect when strict filtering drops tagged lines).
    return True


def _supplier_line_filter(supplier_id: int, allowed_ids: list[int], *, strict_null_style: str):
    base = (JournalEntryLine.supplier_id == supplier_id)
    if not allowed_ids:
        return base

    if strict_null_style == "is":
        null_customer = JournalEntryLine.customer_id.is_(None)
    else:
        # legacy equality style
        null_customer = (JournalEntryLine.customer_id == None)  # noqa: E711

    return or_(
        base,
        and_(JournalEntryLine.account_id.in_(allowed_ids), null_customer),
    )


def _convert_to_main_expr(main_karat: int):
    # Convert per-karat columns to main-karat equivalent.
    # main_equiv = sum(weight_k * (karat/main_karat))
    mk = float(main_karat or 21)
    return (
        (func.coalesce(JournalEntryLine.debit_18k, 0.0) - func.coalesce(JournalEntryLine.credit_18k, 0.0))
        * (18.0 / mk)
        + (func.coalesce(JournalEntryLine.debit_21k, 0.0) - func.coalesce(JournalEntryLine.credit_21k, 0.0))
        * (21.0 / mk)
        + (func.coalesce(JournalEntryLine.debit_22k, 0.0) - func.coalesce(JournalEntryLine.credit_22k, 0.0))
        * (22.0 / mk)
        + (func.coalesce(JournalEntryLine.debit_24k, 0.0) - func.coalesce(JournalEntryLine.credit_24k, 0.0))
        * (24.0 / mk)
    )


def _ledger_query(supplier_id: int, allowed_ids: list[int]):
    return (
        JournalEntryLine.query
        .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
        .join(Account, JournalEntryLine.account_id == Account.id)
        .filter(_supplier_line_filter(supplier_id, allowed_ids, strict_null_style="is"))
        .filter(JournalEntryLine.is_deleted.is_(False))
        .filter(JournalEntry.is_deleted.is_(False))
        .filter(_account_filter(allowed_ids))
    )


def _ledger_query_relaxed(supplier_id: int, allowed_ids: list[int]):
    return (
        JournalEntryLine.query
        .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
        .join(Account, JournalEntryLine.account_id == Account.id)
        .filter(_supplier_line_filter(supplier_id, allowed_ids, strict_null_style="is"))
        .filter(JournalEntryLine.is_deleted.is_(False))
        .filter(JournalEntry.is_deleted.is_(False))
        .filter(_relaxed_account_filter())
    )


def _statement_query(supplier_id: int, allowed_ids: list[int]):
    return (
        JournalEntryLine.query
        .join(JournalEntry)
        .join(Account, JournalEntryLine.account_id == Account.id)
        .filter(_supplier_line_filter(supplier_id, allowed_ids, strict_null_style="eq"))
        .filter(JournalEntryLine.is_deleted.is_(False))
        .filter(JournalEntry.is_deleted.is_(False))
        .filter(_account_filter(allowed_ids))
    )


def _statement_query_relaxed(supplier_id: int, allowed_ids: list[int]):
    return (
        JournalEntryLine.query
        .join(JournalEntry)
        .join(Account, JournalEntryLine.account_id == Account.id)
        .filter(_supplier_line_filter(supplier_id, allowed_ids, strict_null_style="eq"))
        .filter(JournalEntryLine.is_deleted.is_(False))
        .filter(JournalEntry.is_deleted.is_(False))
        .filter(_relaxed_account_filter())
    )


def _sum_cash_and_gold_main(query, main_karat: int):
    row = (
        query.with_entities(
            func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0),
            func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0),
            func.coalesce(func.sum(_convert_to_main_expr(main_karat)), 0.0),
        ).first()
    )
    if not row:
        return (0.0, 0.0)
    cash_debit, cash_credit, gold_main_net = row
    cash_net = float(cash_debit or 0.0) - float(cash_credit or 0.0)
    return (cash_net, float(gold_main_net or 0.0))


def main() -> int:
    with app.app_context():
        diffs: list[SupplierDiff] = []
        dropped_by_strict: list[tuple[int, str, int, int]] = []

        suppliers = Supplier.query.order_by(Supplier.id.asc()).all()
        for supplier in suppliers:
            allowed_ids = _get_allowed_ids(supplier)
            main_karat = 21
            try:
                # In backend config this is usually stored in settings; keeping 21 as fallback.
                pass
            except Exception:
                main_karat = 21

            q_ledger = _ledger_query(supplier.id, allowed_ids)
            q_stmt = _statement_query(supplier.id, allowed_ids)

            ledger_count = q_ledger.count()
            stmt_count = q_stmt.count()

            ledger_cash, ledger_gold = _sum_cash_and_gold_main(q_ledger, main_karat)
            stmt_cash, stmt_gold = _sum_cash_and_gold_main(q_stmt, main_karat)

            if (
                ledger_count != stmt_count
                or abs(ledger_cash - stmt_cash) > 0.0001
                or abs(ledger_gold - stmt_gold) > 0.0001
            ):
                diffs.append(
                    SupplierDiff(
                        supplier_id=supplier.id,
                        supplier_name=supplier.name,
                        ledger_count=ledger_count,
                        statement_count=stmt_count,
                        ledger_cash_net=ledger_cash,
                        statement_cash_net=stmt_cash,
                        ledger_gold_main_net=ledger_gold,
                        statement_gold_main_net=stmt_gold,
                        allowed_ids=allowed_ids,
                    )
                )

            # Detect when strict account filtering would drop supplier-tagged lines.
            # This correlates strongly with "statement missing some purchase invoices" reports.
            try:
                strict_stmt_count = stmt_count
                relaxed_stmt_count = _statement_query_relaxed(supplier.id, allowed_ids).count()
                if relaxed_stmt_count > strict_stmt_count:
                    dropped_by_strict.append(
                        (supplier.id, supplier.name, strict_stmt_count, relaxed_stmt_count)
                    )
            except Exception:
                pass

        print(f"Suppliers checked: {len(suppliers)}")
        print(f"Mismatches found: {len(diffs)}")
        for d in diffs[:50]:
            print(
                "-",
                d.supplier_id,
                repr(d.supplier_name),
                f"count ledger={d.ledger_count} stmt={d.statement_count}",
                f"cash ledger={d.ledger_cash_net:.2f} stmt={d.statement_cash_net:.2f}",
                f"gold(main) ledger={d.ledger_gold_main_net:.3f} stmt={d.statement_gold_main_net:.3f}",
                f"allowed={d.allowed_ids}",
            )

        if dropped_by_strict:
            print(f"Suppliers where strict account filter drops tagged lines: {len(dropped_by_strict)}")
            for supplier_id, supplier_name, strict_count, relaxed_count in dropped_by_strict[:50]:
                print(
                    "-",
                    supplier_id,
                    repr(supplier_name),
                    f"strict={strict_count} relaxed={relaxed_count}",
                )

        return 0


if __name__ == "__main__":
    raise SystemExit(main())
