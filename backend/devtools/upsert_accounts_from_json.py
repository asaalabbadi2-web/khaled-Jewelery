#!/usr/bin/env python3
"""Upsert chart-of-accounts from an exported JSON file (NON-DESTRUCTIVE).

This applies the same semantics as POST /api/accounts/import:
- Upserts by account_number
- Updates core fields (name/type/transaction_type/tracks_weight, optional bank fields)
- Relinks parent/memo relationships in a second pass

Usage:
  cd backend
  ./venv/bin/python devtools/upsert_accounts_from_json.py --file ../exports/accounts_updated_20260130.json

Notes:
- This does NOT wipe accounts or balances.
- It will fail fast if the JSON references missing parent/memo accounts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from app import app, db
from account_pair_service import link_accounts, unlink_account
from models import Account


def _load_accounts_rows(file_path: Path) -> List[Dict[str, Any]]:
    raw = json.loads(file_path.read_text(encoding="utf-8"))

    # API export format
    if isinstance(raw, dict) and isinstance(raw.get("accounts"), list):
        return list(raw["accounts"])

    # Some exports nest under "data"
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        return list(raw["data"])

    # Legacy dict keyed by account_number
    if isinstance(raw, dict) and all(isinstance(v, dict) for v in raw.values()):
        return [dict(v) for v in raw.values()]

    # Legacy list
    if isinstance(raw, list):
        return [dict(v) for v in raw]

    raise ValueError("Unsupported JSON format for accounts")


def _normalize_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Invalid row type at index {idx}")

        account_number = str(row.get("account_number") or "").strip()
        if not account_number:
            raise ValueError(f"account_number is required (index {idx})")

        name = str(row.get("name") or "").strip()
        if not name:
            raise ValueError(f"name is required (account {account_number})")

        acc_type = str(row.get("type") or "").strip()
        if not acc_type:
            raise ValueError(f"type is required (account {account_number})")

        transaction_type = row.get("transaction_type")
        if not isinstance(transaction_type, str) or not transaction_type.strip():
            transaction_type = "both"
        transaction_type = transaction_type.strip() or "both"

        normalized.append(
            {
                "account_number": account_number,
                "name": name,
                "type": acc_type,
                "transaction_type": transaction_type,
                "tracks_weight": bool(row.get("tracks_weight", False)),
                "bank_name": row.get("bank_name"),
                "account_number_external": row.get("account_number_external"),
                "account_type": row.get("account_type"),
                "parent_account_number": (
                    str(row.get("parent_account_number")).strip()
                    if row.get("parent_account_number") is not None
                    else None
                ),
                "memo_account_number": (
                    str(row.get("memo_account_number")).strip()
                    if row.get("memo_account_number") is not None
                    else None
                ),
            }
        )

    present = {r["account_number"] for r in normalized}
    missing_refs = []
    for r in normalized:
        p = r.get("parent_account_number")
        m = r.get("memo_account_number")
        if p and p not in present:
            missing_refs.append((r["account_number"], "parent_account_number", p))
        if m and m not in present:
            missing_refs.append((r["account_number"], "memo_account_number", m))
    if missing_refs:
        details = "\n".join([f"- {a} missing {k}={v}" for a, k, v in missing_refs[:50]])
        raise ValueError(f"Missing references in import payload (showing up to 50):\n{details}")

    return normalized


def upsert_accounts(normalized: List[Dict[str, Any]]) -> Dict[str, int]:
    numbers = [r["account_number"] for r in normalized]

    existing = Account.query.filter(Account.account_number.in_(numbers)).all()
    existing_by_number = {acc.account_number: acc for acc in existing}

    created = 0
    updated = 0

    # Pass 1: upsert core fields
    for row in normalized:
        acc = existing_by_number.get(row["account_number"])
        if acc is None:
            acc = Account(
                account_number=row["account_number"],
                name=row["name"],
                type=row["type"],
                transaction_type=row["transaction_type"],
                tracks_weight=row["tracks_weight"],
            )
            created += 1
        else:
            acc.name = row["name"]
            acc.type = row["type"]
            acc.transaction_type = row["transaction_type"]
            acc.tracks_weight = row["tracks_weight"]
            updated += 1

        acc.bank_name = row["bank_name"]
        acc.account_number_external = row["account_number_external"]
        acc.account_type = row["account_type"]

        db.session.add(acc)

    db.session.flush()

    imported_accounts = Account.query.filter(Account.account_number.in_(numbers)).all()
    number_to_id = {acc.account_number: acc.id for acc in imported_accounts}
    accounts_by_number = {acc.account_number: acc for acc in imported_accounts}

    relinked = 0
    for row in normalized:
        acc = accounts_by_number[row["account_number"]]

        parent_num = row.get("parent_account_number")
        memo_num = row.get("memo_account_number")

        new_parent_id = number_to_id.get(parent_num) if parent_num else None
        new_memo_id = number_to_id.get(memo_num) if memo_num else None

        memo_changed = acc.memo_account_id != new_memo_id
        if acc.parent_id != new_parent_id or memo_changed:
            relinked += 1

        acc.parent_id = new_parent_id
        db.session.add(acc)

        # الربط/الفسخ عبر الخدمة المركزية فقط -- انظر account_pair_service.py.
        if memo_changed:
            if new_memo_id is None:
                unlink_account(acc, created_by='upsert_accounts_from_json')
            else:
                memo_acc = accounts_by_number.get(memo_num)
                if memo_acc:
                    link_accounts(acc, memo_acc, created_by='upsert_accounts_from_json')

    return {"created": created, "updated": updated, "relinked": relinked, "count": len(normalized)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to COA export JSON")
    args = parser.parse_args()

    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    with app.app_context():
        rows = _load_accounts_rows(file_path)
        normalized = _normalize_rows(rows)
        stats = upsert_accounts(normalized)
        db.session.commit()

    print(json.dumps({"success": True, "file": str(file_path), **stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
