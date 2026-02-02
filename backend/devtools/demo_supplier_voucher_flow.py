#!/usr/bin/env python3
"""Demo: apply COA (upsert), create supplier, create + approve a cash+gold payment voucher.

This is intended to validate the end-to-end flow requested:
- Adjust chart of accounts from exports/accounts_updated_20260130.json
- Create a supplier (with auto-created financial + memo accounts)
- Create a payment voucher (cash + gold) in the supplier name
- Approve the voucher so it generates a journal entry and affects statements

Usage:
  cd backend
  ./venv/bin/python devtools/demo_supplier_voucher_flow.py \
    --coa ../exports/accounts_updated_20260130.json \
    --supplier-name "مورد اختبار" \
    --cash 100 \
    --gold 1.25 \
    --karat 21

Notes:
- This writes to the current configured DB (e.g. backend/app.db).
- It tries to pick safe-box accounts from Settings; falls back to common COA numbers.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app import app, db
from models import Account, SafeBox, Settings, Supplier, Voucher, VoucherAccountLine
from party_account_service import ensure_supplier_accounts
from code_generator import generate_supplier_code

from devtools.upsert_accounts_from_json import _load_accounts_rows, _normalize_rows, upsert_accounts
from routes import approve_voucher  # reuse posting logic


def _find_account_by_number(account_number: str) -> Account | None:
    return Account.query.filter_by(account_number=str(account_number)).first()


def _resolve_cash_safe_account_id() -> int:
    settings = Settings.query.first()
    if settings and getattr(settings, "main_cash_safe_box_id", None):
        sb = SafeBox.query.get(settings.main_cash_safe_box_id)
        if sb and sb.account_id:
            return int(sb.account_id)

    # Fallback: common COA cash safe
    for n in ("1100000", "1100", "15"):
        acc = _find_account_by_number(n)
        if acc:
            return int(acc.id)

    raise ValueError("Could not resolve a cash safe account")


def _resolve_gold_safe_account_id(karat: int) -> int:
    settings = Settings.query.first()

    # Prefer sale_gold_safe_box_id, then scrap safe.
    safe_candidates = []
    if settings and getattr(settings, "sale_gold_safe_box_id", None):
        safe_candidates.append(int(settings.sale_gold_safe_box_id))
    if settings and getattr(settings, "main_scrap_gold_safe_box_id", None):
        safe_candidates.append(int(settings.main_scrap_gold_safe_box_id))

    for safe_id in safe_candidates:
        sb = SafeBox.query.get(safe_id)
        if not sb or not sb.account_id:
            continue
        # If safe box is fixed to a karat, match it.
        sb_karat = getattr(sb, "karat", None)
        if sb_karat is None:
            return int(sb.account_id)
        try:
            if int(sb_karat) == int(karat):
                return int(sb.account_id)
        except Exception:
            return int(sb.account_id)

    # Fallback to any gold safe box matching karat.
    for sb in SafeBox.query.filter_by(safe_type="gold").all():
        if not sb.account_id:
            continue
        if getattr(sb, "karat", None) is None:
            return int(sb.account_id)
        try:
            if int(sb.karat) == int(karat):
                return int(sb.account_id)
        except Exception:
            return int(sb.account_id)

    # COA fallback: try likely inventory/scrap boxes.
    for n in ("1310000", "1300", "1220", "1200"):
        acc = _find_account_by_number(n)
        if acc:
            return int(acc.id)

    raise ValueError("Could not resolve a gold safe account")


def _get_or_create_supplier(name: str) -> Supplier:
    existing = Supplier.query.filter(Supplier.name == name).order_by(Supplier.id.desc()).first()
    if existing:
        # Ensure accounts exist
        ensure_supplier_accounts(existing)
        return existing

    supplier = Supplier(
        supplier_code=generate_supplier_code(),
        name=name,
        balance_cash=0.0,
        balance_gold_18k=0.0,
        balance_gold_21k=0.0,
        balance_gold_22k=0.0,
        balance_gold_24k=0.0,
    )
    db.session.add(supplier)
    db.session.flush()

    ensure_supplier_accounts(supplier)
    return supplier


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coa", required=True, help="Path to COA export JSON")
    parser.add_argument("--supplier-name", required=True)
    parser.add_argument("--cash", type=float, default=100.0)
    parser.add_argument("--gold", type=float, default=1.0)
    parser.add_argument("--karat", type=int, default=21)
    args = parser.parse_args()

    coa_path = Path(args.coa).expanduser().resolve()
    if not coa_path.exists():
        raise SystemExit(f"COA file not found: {coa_path}")

    with app.app_context():
        # 1) Upsert COA from JSON
        rows = _load_accounts_rows(coa_path)
        normalized = _normalize_rows(rows)
        coa_stats = upsert_accounts(normalized)

        # 2) Create supplier + ensure accounts
        supplier = _get_or_create_supplier(args.supplier_name)
        db.session.flush()

        if not supplier.account_id:
            raise ValueError("Supplier has no linked financial account_id after ensure_supplier_accounts")

        supplier_account_id = int(supplier.account_id)
        cash_safe_account_id = _resolve_cash_safe_account_id()
        gold_safe_account_id = _resolve_gold_safe_account_id(args.karat)

        # 3) Create voucher + lines (balanced separately for cash and gold)
        voucher = Voucher(
            voucher_number="TEMP",  # will be overwritten
            voucher_type="payment",
            date=datetime.now(),
            party_type="supplier",
            supplier_id=supplier.id,
            party_name=None,
            amount_cash=float(args.cash),
            amount_gold=float(args.gold),
            description=f"سند صرف تجريبي للمورد {supplier.name}",
            created_by="devtools",
            status="pending",
        )
        # Use the same generator the API uses.
        from routes import generate_voucher_number

        voucher.voucher_number = generate_voucher_number(voucher.voucher_type)

        db.session.add(voucher)
        db.session.flush()

        lines = [
            # Cash: debit supplier, credit cash safe
            VoucherAccountLine(
                voucher_id=voucher.id,
                account_id=supplier_account_id,
                line_type="debit",
                amount_type="cash",
                amount=float(args.cash),
                description="تسديد نقدي للمورد",
            ),
            VoucherAccountLine(
                voucher_id=voucher.id,
                account_id=cash_safe_account_id,
                line_type="credit",
                amount_type="cash",
                amount=float(args.cash),
                description="صرف نقد من الخزنة",
            ),
            # Gold: debit supplier, credit gold safe
            VoucherAccountLine(
                voucher_id=voucher.id,
                account_id=supplier_account_id,
                line_type="debit",
                amount_type="gold",
                amount=float(args.gold),
                karat=float(args.karat),
                description=f"تسديد ذهب عيار {args.karat}",
            ),
            VoucherAccountLine(
                voucher_id=voucher.id,
                account_id=gold_safe_account_id,
                line_type="credit",
                amount_type="gold",
                amount=float(args.gold),
                karat=float(args.karat),
                description=f"صرف ذهب من الخزنة عيار {args.karat}",
            ),
        ]
        for l in lines:
            db.session.add(l)

        db.session.commit()

        # 4) Approve voucher to post JE + safebox tx
        # approve_voucher reads request.get_json() so we call the underlying logic directly via app.test_request_context.
        with app.test_request_context(json={"approved_by": "devtools"}):
            resp = approve_voucher(voucher.id)

        # approve_voucher returns (json, status) tuple in some cases; normalize
        if isinstance(resp, tuple):
            body, status = resp
        else:
            body, status = resp, 200

        db.session.commit()

        output = {
            "success": True,
            "coa": {"file": str(coa_path), **coa_stats},
            "supplier": {
                "id": supplier.id,
                "name": supplier.name,
                "account_id": supplier.account_id,
            },
            "voucher": {
                "id": voucher.id,
                "voucher_number": voucher.voucher_number,
                "status": voucher.status,
                "journal_entry_id": voucher.journal_entry_id,
            },
            "approve_result": getattr(body, "json", None) if hasattr(body, "json") else None,
            "http_status": status,
            "picked_accounts": {
                "supplier_account_id": supplier_account_id,
                "cash_safe_account_id": cash_safe_account_id,
                "gold_safe_account_id": gold_safe_account_id,
            },
        }

        print(json.dumps(output, ensure_ascii=False, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
