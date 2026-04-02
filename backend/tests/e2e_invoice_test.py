"""
E2E test for invoice creation via HTTP — validates je_engine_v2 integration.
Tests: بيع, شراء من عميل, مرتجع بيع, مرتجع شراء

Usage: python e2e_invoice_test.py [base_url]
Default base_url: http://localhost:8001
"""
import sys
import json
import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
API = f"{BASE}/api"
PASS = "✅"
FAIL = "❌"

errors = []


def ok(msg):
    print(f"  {PASS} {msg}")


def fail(msg):
    print(f"  {FAIL} {msg}")
    errors.append(msg)


def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def post(path, payload):
    r = requests.post(f"{API}{path}", json=payload, timeout=15)
    return r


def get(path):
    r = requests.get(f"{API}{path}", timeout=10)
    return r


# ─── helpers ─────────────────────────────────────────────────────────────────

def get_gold_price():
    d = get("/gold_price").json()
    return float(d["price_main_karat"])  # SAR/g for 21k


def get_je_lines(je_id):
    """Fetch journal entry lines for a given journal_entry_id."""
    r = get(f"/journal-entries/{je_id}")
    if r.status_code != 200:
        return []
    d = r.json()
    return d.get("lines", d.get("journal_entry", {}).get("lines", []))


def check_je_balance(lines, label):
    """Verify JE lines balance: sum(cash_debit)==sum(cash_credit) and weight."""
    cd = sum(float(l.get("cash_debit") or 0) for l in lines)
    cc = sum(float(l.get("cash_credit") or 0) for l in lines)
    wd = sum(float(l.get("weight_debit") or 0) for l in lines)
    wc = sum(float(l.get("weight_credit") or 0) for l in lines)
    cash_ok = abs(cd - cc) < 0.05
    weight_ok = abs(wd - wc) < 0.01
    if cash_ok:
        ok(f"{label}: cash balanced (debit={cd:.2f}, credit={cc:.2f})")
    else:
        fail(f"{label}: cash UNBALANCED (debit={cd:.2f}, credit={cc:.2f})")
    if weight_ok:
        ok(f"{label}: weight balanced (debit={wd:.4f}, credit={wc:.4f})")
    else:
        fail(f"{label}: weight UNBALANCED (debit={wd:.4f}, credit={wc:.4f})")


def check_no_weight_on_cash_account(lines, cash_acc_ids, label):
    """Ensure no weight entries on cash/financial accounts."""
    for l in lines:
        acc_id = l.get("account_id")
        if acc_id in cash_acc_ids:
            wd = float(l.get("weight_debit") or 0)
            wc = float(l.get("weight_credit") or 0)
            if wd != 0 or wc != 0:
                fail(f"{label}: weight on financial account {acc_id} (wd={wd}, wc={wc})")
                return
    ok(f"{label}: no weight on cash/financial accounts")


def check_no_cash_on_weight_account(lines, weight_acc_ids, label):
    """Ensure no cash entries on weight/inventory accounts."""
    for l in lines:
        acc_id = l.get("account_id")
        if acc_id in weight_acc_ids:
            cd = float(l.get("cash_debit") or 0)
            cc = float(l.get("cash_credit") or 0)
            if cd != 0 or cc != 0:
                fail(f"{label}: cash on weight account {acc_id} (cd={cd}, cc={cc})")
                return
    ok(f"{label}: no cash on weight/inventory accounts")


# ─── Test 1: بيع ─────────────────────────────────────────────────────────────

section("TEST 1: فاتورة بيع")

gp = get_gold_price()
print(f"  Gold price: {gp} SAR/g (21k)")

# Item 1: خواتم, weight=11g, karat=21, wage=900
unit_price = round(gp * 11 + 900, 2)

sale_payload = {
    "invoice_type": "بيع",
    "customer_id": 1,
    "gold_price": gp,
    "items": [
        {
            "item_id": 1,
            "quantity": 1,
            "weight": 11.0,
            "karat": "21",
            "unit_price": unit_price,
            "manufacturing_wage": 900.0,
        }
    ],
    "payments": [
        {
            "payment_method_id": 1,
            "amount": unit_price,
            "safe_box_id": 1,
        }
    ],
    "total": unit_price,
    "notes": "E2E test - بيع",
}

r = post("/invoices", sale_payload)
if r.status_code in (200, 201):
    inv = r.json()
    inv_id = inv.get("id") or inv.get("invoice", {}).get("id")
    ok(f"Invoice created: ID={inv_id}, total={unit_price}")
    
    # Fetch JE lines
    je_id = inv.get("journal_entry_id") or inv.get("invoice", {}).get("journal_entry_id")
    if je_id:
        lines = get_je_lines(je_id)
        if lines:
            print(f"  JE ID={je_id}, {len(lines)} lines:")
            for l in lines:
                print(f"    acc={l.get('account_id'):>5}  cd={float(l.get('cash_debit') or 0):>10.2f}  cc={float(l.get('cash_credit') or 0):>10.2f}  wd={float(l.get('weight_debit') or 0):>8.4f}  wc={float(l.get('weight_credit') or 0):>8.4f}  type={l.get('entry_type','')}")
            check_je_balance(lines, "بيع JE")
        else:
            fail("بيع: could not fetch JE lines")
    else:
        fail("بيع: no journal_entry_id in response")
    
    SALE_INVOICE_ID = inv_id
    SALE_CUSTOMER_ID = 1
else:
    fail(f"بيع failed: {r.status_code} — {r.text[:300]}")
    SALE_INVOICE_ID = None
    SALE_CUSTOMER_ID = 1

# ─── Test 2: شراء من عميل ────────────────────────────────────────────────────

section("TEST 2: فاتورة شراء من عميل")

buy_price = round(gp * 0.9, 2)  # buy at 90% of market
buy_weight = 8.5
buy_total = round(buy_price * buy_weight, 2)

cust_buy_payload = {
    "invoice_type": "شراء من عميل",
    "customer_id": 1,
    "gold_price": gp,
    "gold_type": "scrap",
    "items": [
        {
            "weight": buy_weight,
            "karat": "21",
            "unit_price": buy_price,
            "quantity": 1,
            "name": "ذهب مستعمل E2E",
        }
    ],
    "payments": [
        {
            "payment_method_id": 1,
            "amount": buy_total,
            "safe_box_id": 1,
        }
    ],
    "total": buy_total,
    "notes": "E2E test - شراء من عميل",
}

r = post("/invoices", cust_buy_payload)
if r.status_code in (200, 201):
    inv = r.json()
    inv_id2 = inv.get("id") or inv.get("invoice", {}).get("id")
    ok(f"Invoice created: ID={inv_id2}, total={buy_total}")
    je_id2 = inv.get("journal_entry_id") or inv.get("invoice", {}).get("journal_entry_id")
    if je_id2:
        lines2 = get_je_lines(je_id2)
        if lines2:
            print(f"  JE ID={je_id2}, {len(lines2)} lines:")
            for l in lines2:
                print(f"    acc={l.get('account_id'):>5}  cd={float(l.get('cash_debit') or 0):>10.2f}  cc={float(l.get('cash_credit') or 0):>10.2f}  wd={float(l.get('weight_debit') or 0):>8.4f}  wc={float(l.get('weight_credit') or 0):>8.4f}  type={l.get('entry_type','')}")
            check_je_balance(lines2, "شراء من عميل JE")
        else:
            fail("شراء من عميل: could not fetch JE lines")
    else:
        fail("شراء من عميل: no journal_entry_id")
    CUST_BUY_INVOICE_ID = inv_id2
else:
    fail(f"شراء من عميل failed: {r.status_code} — {r.text[:300]}")
    CUST_BUY_INVOICE_ID = None

# ─── Test 3: مرتجع بيع ───────────────────────────────────────────────────────

section("TEST 3: مرتجع بيع")

if SALE_INVOICE_ID:
    ret_sale_payload = {
        "invoice_type": "مرتجع بيع",
        "customer_id": SALE_CUSTOMER_ID,
        "original_invoice_id": SALE_INVOICE_ID,
        "gold_price": gp,
        "items": [
            {
                "item_id": 1,
                "original_invoice_item_id": None,
                "quantity": 1,
                "weight": 11.0,
                "karat": "21",
                "unit_price": unit_price,
                "manufacturing_wage": 900.0,
            }
        ],
        "payments": [
            {
                "payment_method_id": 1,
                "amount": unit_price,
                "safe_box_id": 1,
            }
        ],
        "total": unit_price,
        "notes": "E2E test - مرتجع بيع",
    }
    r = post("/invoices", ret_sale_payload)
    if r.status_code in (200, 201):
        inv = r.json()
        inv_id3 = inv.get("id") or inv.get("invoice", {}).get("id")
        ok(f"Invoice created: ID={inv_id3}")
        je_id3 = inv.get("journal_entry_id") or inv.get("invoice", {}).get("journal_entry_id")
        if je_id3:
            lines3 = get_je_lines(je_id3)
            if lines3:
                print(f"  JE ID={je_id3}, {len(lines3)} lines:")
                for l in lines3:
                    print(f"    acc={l.get('account_id'):>5}  cd={float(l.get('cash_debit') or 0):>10.2f}  cc={float(l.get('cash_credit') or 0):>10.2f}  wd={float(l.get('weight_debit') or 0):>8.4f}  wc={float(l.get('weight_credit') or 0):>8.4f}  type={l.get('entry_type','')}")
                check_je_balance(lines3, "مرتجع بيع JE")
    else:
        fail(f"مرتجع بيع failed: {r.status_code} — {r.text[:300]}")
else:
    print("  ⏭  Skipped (no sale invoice ID)")

# ─── Test 4: مرتجع شراء ──────────────────────────────────────────────────────

section("TEST 4: مرتجع شراء (من عميل)")

if CUST_BUY_INVOICE_ID:
    ret_buy_payload = {
        "invoice_type": "مرتجع شراء",
        "customer_id": 1,
        "original_invoice_id": CUST_BUY_INVOICE_ID,
        "gold_price": gp,
        "gold_type": "scrap",
        "items": [
            {
                "weight": buy_weight,
                "karat": "21",
                "unit_price": buy_price,
                "quantity": 1,
                "name": "ذهب مستعمل E2E",
            }
        ],
        "payments": [
            {
                "payment_method_id": 1,
                "amount": buy_total,
                "safe_box_id": 1,
            }
        ],
        "total": buy_total,
        "notes": "E2E test - مرتجع شراء",
    }
    r = post("/invoices", ret_buy_payload)
    if r.status_code in (200, 201):
        inv = r.json()
        inv_id4 = inv.get("id") or inv.get("invoice", {}).get("id")
        ok(f"Invoice created: ID={inv_id4}")
        je_id4 = inv.get("journal_entry_id") or inv.get("invoice", {}).get("journal_entry_id")
        if je_id4:
            lines4 = get_je_lines(je_id4)
            if lines4:
                print(f"  JE ID={je_id4}, {len(lines4)} lines:")
                for l in lines4:
                    print(f"    acc={l.get('account_id'):>5}  cd={float(l.get('cash_debit') or 0):>10.2f}  cc={float(l.get('cash_credit') or 0):>10.2f}  wd={float(l.get('weight_debit') or 0):>8.4f}  wc={float(l.get('weight_credit') or 0):>8.4f}  type={l.get('entry_type','')}")
                check_je_balance(lines4, "مرتجع شراء JE")
    else:
        fail(f"مرتجع شراء failed: {r.status_code} — {r.text[:300]}")
else:
    print("  ⏭  Skipped (no cust-buy invoice ID)")

# ─── Summary ──────────────────────────────────────────────────────────────────

section("SUMMARY")
if not errors:
    print(f"  {PASS} All E2E checks passed!")
else:
    for e in errors:
        print(f"  {FAIL} {e}")
    print(f"\n  Total failures: {len(errors)}")
    sys.exit(1)
