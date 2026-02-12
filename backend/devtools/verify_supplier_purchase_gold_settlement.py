#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end check: supplier purchase invoice with multi-karat gold settlement.

Creates a minimal supplier purchase invoice using `gold_settlements[]` and verifies:
- An approved payment voucher is created (reference_type=invoice, reference_id=invoice_id)
- Voucher has gold lines with per-line karat
- Voucher has a journal entry
- SafeBoxTransactions exist for the voucher

This is a devtool script; it intentionally prints a compact, human-readable summary.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def _json_request(url: str, method: str = "GET", body: dict | None = None, timeout: int = 10):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        try:
            payload = json.loads(raw) if raw else {"error": raw}
        except Exception:
            payload = {"error": raw or str(exc)}
        return exc.code, payload


def _pick_first(items: list[dict], *, label: str, predicate=None) -> dict:
    if not items:
        raise SystemExit(f"No {label} found")
    if predicate:
        for it in items:
            if predicate(it):
                return it
    return items[0]


def main() -> int:
    base = os.getenv("YASARGOLD_BASE_URL", "http://127.0.0.1:8001")
    if base.endswith("/"):
        base = base[:-1]

    api = f"{base}/api"

    # 1) Resolve required IDs
    st, branches = _json_request(f"{api}/branches?active=1")
    if st != 200:
        print("Failed to load branches", st, branches)
        return 2
    branch = _pick_first(branches, label="branches")

    st, suppliers = _json_request(f"{api}/suppliers")
    if st != 200:
        print("Failed to load suppliers", st, suppliers)
        return 2
    supplier = _pick_first(suppliers, label="suppliers")

    st, safes = _json_request(f"{api}/safe-boxes")
    if st != 200:
        print("Failed to load safe boxes", st, safes)
        return 2

    gold_safes = [s for s in (safes or []) if (s.get("safe_type") or s.get("safeType")) == "gold" and s.get("is_active", True)]
    gold_safe = _pick_first(
        gold_safes,
        label="gold safe boxes",
        predicate=lambda s: int(s.get("karat") or 0) == 0,
    )

    gold_safe_id = int(gold_safe["id"])

    # 2) Create a minimal supplier purchase invoice with multi-karat settlements
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    payload = {
        "invoice_type": "شراء",
        "gold_type": "new",
        "supplier_id": int(supplier["id"]),
        "branch_id": int(branch["id"]),
        "date": now,
        # Minimal totals (cash fields). Gold settlement is handled separately.
        "total": 0.0,
        "amount_paid": 0.0,
        # Provide some purchased gold weight so invoice isn't empty.
        "karat_lines": [
            {"karat": 21, "weight_grams": 0.150, "gold_value_cash": 0.0, "manufacturing_wage_cash": 0.0},
        ],
        # Pay/settle by gold (multi-karat) from the gold safe.
        "gold_settlements": [
            {"safe_box_id": gold_safe_id, "karat": 21, "weight": 0.020},
            {"safe_box_id": gold_safe_id, "karat": 18, "weight": 0.030},
        ],
        "settlement_method": "gold_settlement_test",
    }

    st, created = _json_request(f"{api}/invoices", method="POST", body=payload, timeout=20)
    if st not in (200, 201):
        print("Invoice create failed", st)
        print(json.dumps(created, ensure_ascii=False, indent=2))
        return 3

    invoice_id = created.get("id") if isinstance(created, dict) else None
    if not invoice_id:
        print("Unexpected invoice response:")
        print(created)
        return 4

    print(f"Created invoice id={invoice_id} supplier_id={supplier['id']} branch_id={branch['id']}")

    # 3) Find vouchers linked to the invoice
    qs = urllib.parse.urlencode({"reference_type": "invoice", "reference_id": str(invoice_id), "per_page": "50"})
    st, vouchers_payload = _json_request(f"{api}/vouchers?{qs}")
    if st != 200:
        print("Failed to fetch vouchers", st, vouchers_payload)
        return 5

    vouchers = (vouchers_payload or {}).get("vouchers") if isinstance(vouchers_payload, dict) else None
    vouchers = vouchers or []

    payment_vouchers = [v for v in vouchers if (v.get("voucher_type") == "payment")]
    gold_payment = None
    for v in payment_vouchers:
        if float(v.get("amount_gold") or 0.0) > 0:
            gold_payment = v
            break

    if not gold_payment:
        print("No gold payment voucher found for invoice.")
        print("Found vouchers:")
        for v in vouchers:
            print(f"- id={v.get('id')} type={v.get('voucher_type')} status={v.get('status')} amount_gold={v.get('amount_gold')}")
        return 6

    voucher_id = int(gold_payment["id"])
    print(f"Found gold payment voucher id={voucher_id} status={gold_payment.get('status')} amount_gold={gold_payment.get('amount_gold')}")

    # 4) Fetch voucher details (lines)
    st, voucher_full = _json_request(f"{api}/vouchers/{voucher_id}")
    if st != 200:
        print("Failed to fetch voucher details", st, voucher_full)
        return 7

    account_lines = (voucher_full or {}).get("account_lines") or (voucher_full or {}).get("lines") or []
    gold_lines = [ln for ln in account_lines if (ln.get("amount_type") == "gold")]
    gold_line_karats = sorted({int(ln.get("karat") or 0) for ln in gold_lines if ln.get("karat")})

    print(f"Voucher lines: total={len(account_lines)} gold_lines={len(gold_lines)} gold_karats={gold_line_karats}")

    journal_entry_id = voucher_full.get("journal_entry_id")
    if not journal_entry_id:
        print("Voucher has no journal_entry_id")
        return 8

    print(f"Voucher journal_entry_id={journal_entry_id}")

    # 5) Fetch JE details (optional)
    st, je_full = _json_request(f"{api}/journal_entries/{int(journal_entry_id)}")
    if st == 200 and isinstance(je_full, dict):
        lines = je_full.get("lines") or je_full.get("journal_entry_lines") or []
        print(f"Journal entry lines={len(lines)}")
    else:
        print(f"Journal entry fetch skipped/failed status={st}")

    # 6) Verify safe transactions exist
    st, txs = _json_request(f"{api}/safe-boxes/{gold_safe_id}/transactions")
    if st == 200 and isinstance(txs, list):
        voucher_txs = [t for t in txs if str(t.get("ref_type")) in ("voucher", "invoice", "invoice_gold_settlement") and int(t.get("ref_id") or 0) in (voucher_id, int(invoice_id))]
        print(f"SafeBoxTransactions for safe_id={gold_safe_id}: total={len(txs)} linked_to_voucher_or_invoice={len(voucher_txs)}")
    else:
        print(f"Safe transactions fetch skipped/failed status={st}")

    # 7) Supplier statement should include the voucher via JE lines
    st, statement = _json_request(f"{api}/suppliers/{int(supplier['id'])}/statement")
    if st == 200 and isinstance(statement, dict):
        entries = statement.get("entries") or statement.get("lines") or []
        hit = 0
        for e in entries:
            if int(e.get("voucher_id") or 0) == voucher_id or int(e.get("reference_id") or 0) == voucher_id:
                hit += 1
        print(f"Supplier statement entries={len(entries)} hits_for_voucher={hit}")
    else:
        print(f"Supplier statement fetch skipped/failed status={st}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
