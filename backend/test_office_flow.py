#!/usr/bin/env python3
"""
Comprehensive test for مكاتب التسكير (Gold Fixing Offices) flow.
Tests:
  A. Create new office → auto-creates supplier+accounts
  B. Create office linked to existing supplier (should reuse)
  C. Create reservation (booking with upfront payment from safe box)
  D. Settle reservation → purchase invoice + journal entries
  E. Additional payment voucher (سداد) from office safe box
  F. Withdrawal (صرف) from office vault
"""
import sys, json, requests
from datetime import datetime, timezone

BASE = "http://localhost:8001/api"
ISSUES = []

# ─── Auth ────────────────────────────────────────────────────────────────────
resp = requests.post(f"{BASE}/auth/login", json={"username": "admin", "password": "admin123"})
assert resp.status_code == 200, f"Login failed: {resp.text}"
TOKEN = resp.json()["token"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def ok(r, label):
    if r.status_code not in (200, 201):
        ISSUES.append(f"❌ {label}: HTTP {r.status_code} → {r.text[:300]}")
        print(f"  ❌ FAIL [{r.status_code}]: {r.text[:200]}")
        return None
    print(f"  ✅ OK  [{r.status_code}]: {label}")
    return r.json()

def err(r, label, expected_code=400):
    if r.status_code == expected_code:
        print(f"  ✅ EXPECTED ERROR [{r.status_code}]: {label}")
        return r.json()
    ISSUES.append(f"❌ Expected {expected_code} for '{label}', got {r.status_code}: {r.text[:200]}")
    print(f"  ❌ FAIL: expected {expected_code} for '{label}', got {r.status_code}")
    return None

ts = int(datetime.now(timezone.utc).timestamp())
print("=" * 65)
print("SCENARIO A: Create new office (auto supplier + account)")
print("=" * 65)

# A1 – Create a brand-new office (no existing supplier)
r = requests.post(f"{BASE}/offices", headers=HDR, json={
    "name": f"مكتب تسكير TEST-A {ts}",
    "phone": "0501234567",
    "city": "الرياض",
    "contact_person": "محمد",
    "ensure_supplier_accounts": True,
})
office_a = ok(r, "Create new office A")
if office_a:
    print(f"     office_id={office_a.get('id')}  supplier_id={office_a.get('supplier_id')}  account_category_id={office_a.get('account_category_id')}")
    if not office_a.get("supplier_id"):
        ISSUES.append("❌ A: New office created without supplier_id")
    if not office_a.get("account_category_id"):
        ISSUES.append("❌ A: New office created without account_category_id")
else:
    office_a = None

print()
print("=" * 65)
print("SCENARIO B: Create office linked to EXISTING supplier")
print("=" * 65)

# Find a supplier not already linked to an office
r = requests.get(f"{BASE}/suppliers", headers=HDR)
suppliers_raw = ok(r, "List suppliers")
suppliers = suppliers_raw if isinstance(suppliers_raw, list) else (suppliers_raw or {}).get("suppliers", [])
r2 = requests.get(f"{BASE}/offices", headers=HDR)
offices_list = r2.json() if r2.ok else []
linked_sids = {o.get("supplier_id") for o in offices_list if o.get("supplier_id")}
existing_supplier = next((s for s in suppliers if s.get("id") not in linked_sids), None)

if not existing_supplier:
    # All existing suppliers are already linked — create a fresh one for this test
    r_new = requests.post(f"{BASE}/suppliers", headers=HDR, json={
        "name": f"مورد اختبار ربط TEST-B {ts}",
        "phone": "0507654321",
    })
    if r_new.ok:
        existing_supplier = r_new.json()
        print(f"  ℹ️  Created fresh supplier for Scenario B: id={existing_supplier['id']}")
    else:
        print(f"  ⚠️  Could not create test supplier: {r_new.status_code}")

if existing_supplier:
    r = requests.post(f"{BASE}/offices", headers=HDR, json={
        "name": f"مكتب ربط TEST-B {ts}",
        "phone": "0507654321",
        "supplier_id": existing_supplier["id"],
    })
    office_b = ok(r, f"Create office B linked to supplier {existing_supplier['id']}")
    if office_b:
        print(f"     office_id={office_b.get('id')}  supplier_id={office_b.get('supplier_id')}  expected={existing_supplier['id']}")
        if office_b.get("supplier_id") != existing_supplier["id"]:
            ISSUES.append(f"❌ B: office.supplier_id={office_b.get('supplier_id')} != requested {existing_supplier['id']}")
else:
    print("  ⚠️  Skipping B: no suppliers available")
    office_b = None

# Set working office to A (or fallback to first existing)
r = requests.get(f"{BASE}/offices", headers=HDR)
offices = r.json() if r.ok else []
if not office_a:
    office_a = offices[0] if offices else None
if not office_a:
    print("❌ No office available – aborting.")
    sys.exit(1)

office_id = office_a["id"]
print(f"\n  Using office_id={office_id} for scenarios C-F")

# Get office's default safe box
supplier_safe_box_id = office_a.get("supplier_default_safe_box_id")
# Also get a general cash safe box
r = requests.get(f"{BASE}/safe-boxes", headers=HDR)
safe_boxes_raw = r.json() if r.ok else []
safe_boxes = safe_boxes_raw if isinstance(safe_boxes_raw, list) else safe_boxes_raw.get("safe_boxes", [])
cash_safes = [s for s in safe_boxes if s.get("safe_type") in ("cash", "bank") and s.get("is_active", True)]
gold_safes = [s for s in safe_boxes if s.get("safe_type") == "gold" and s.get("is_active", True)]
office_gold_safes = [s for s in gold_safes if office_id and str(office_a.get("account_category_id", "")) in str(s.get("account_id", ""))]
cash_safe_id = cash_safes[0]["id"] if cash_safes else None
gold_safe_id = supplier_safe_box_id or (gold_safes[0]["id"] if gold_safes else None)

print(f"  cash_safe_id={cash_safe_id}  gold_safe_id={gold_safe_id}")

print()
print("=" * 65)
print("SCENARIO C: Create reservation with upfront payment")
print("=" * 65)

if not cash_safe_id:
    ISSUES.append("❌ C: No cash safe box available")
    reservation_c = None
else:
    r = requests.post(f"{BASE}/office-reservations", headers=HDR, json={
        "office_id": office_id,
        "weight": 10.0,
        "karat": 21,
        "price_per_gram": 220.0,
        "execution_price_per_gram": 218.0,
        "paid_amount": 1000.0,   # partial upfront
        "safe_box_id": cash_safe_id,
        "notes": "حجز اختبار تلقائي",
    })
    reservation_c = ok(r, "Create reservation with partial upfront payment")
    if reservation_c:
        print(f"     reservation_code={reservation_c.get('reservation_code')} paid={reservation_c.get('paid_amount')} status={reservation_c.get('payment_status')}")
        print(f"     voucher_id={reservation_c.get('payment_voucher_id')}  voucher_num={reservation_c.get('payment_voucher_number')}")
        if not reservation_c.get("payment_voucher_id"):
            ISSUES.append("❌ C: paid_amount>0 but no payment_voucher_id returned")
        if reservation_c.get("payment_status") not in ("partial", "paid"):
            ISSUES.append(f"❌ C: payment_status={reservation_c.get('payment_status')} expected partial/paid")

# C2 – Reservation with ZERO upfront payment
r = requests.post(f"{BASE}/office-reservations", headers=HDR, json={
    "office_id": office_id,
    "weight": 5.0,
    "karat": 24,
    "price_per_gram": 240.0,
    "paid_amount": 0,
    "notes": "حجز بدون دفعة",
})
reservation_c2 = ok(r, "Create reservation with zero payment")
if reservation_c2:
    print(f"     reservation_code={reservation_c2.get('reservation_code')} paid={reservation_c2.get('paid_amount')} status={reservation_c2.get('payment_status')}")
    if reservation_c2.get("payment_status") != "pending":
        ISSUES.append(f"❌ C2: expected pending, got {reservation_c2.get('payment_status')}")
    if reservation_c2.get("payment_voucher_id"):
        ISSUES.append("❌ C2: zero payment but voucher was created — should not happen")

# C3 – Fully paid at creation
r = requests.post(f"{BASE}/office-reservations", headers=HDR, json={
    "office_id": office_id,
    "weight": 8.0,
    "karat": 18,
    "price_per_gram": 180.0,
    "paid_amount": 1440.0,   # = 8 * 180 (full)
    "safe_box_id": cash_safe_id,
    "notes": "حجز مدفوع بالكامل",
})
reservation_c3 = ok(r, "Create reservation fully paid")
if reservation_c3:
    print(f"     payment_status={reservation_c3.get('payment_status')}  expected=paid")
    if reservation_c3.get("payment_status") != "paid":
        ISSUES.append(f"❌ C3: fully-paid reservation shows status={reservation_c3.get('payment_status')}")

print()
print("=" * 65)
print("SCENARIO D: Settle reservation → purchase invoice")
print("=" * 65)

if reservation_c:
    res_id = reservation_c["id"]
    r = requests.post(f"{BASE}/office-reservations/{res_id}/settle", headers=HDR, json={
        "execution_price_per_gram": 218.0,
    })
    settle_d = ok(r, f"Settle reservation {res_id}")
    if settle_d:
        print(f"     invoice_id={settle_d.get('purchase_invoice_id')}  status={settle_d.get('status')}")
        print(f"     journal_entry={settle_d.get('journal_entry')}")
        wc_warn = settle_d.get("weight_closing_warning")
        if wc_warn:
            print(f"     ⚠️  weight_closing_warning: {wc_warn.get('message')}")
        if not settle_d.get("purchase_invoice_id"):
            ISSUES.append("❌ D: settle returned no purchase_invoice_id")
        if not settle_d.get("journal_entry", {}).get("id"):
            ISSUES.append("❌ D: settle returned no journal_entry")

    # D2 – Try to settle same reservation again → should return 200 (idempotent) or 400
    r2 = requests.post(f"{BASE}/office-reservations/{res_id}/settle", headers=HDR, json={})
    if r2.status_code in (200, 201):
        d2 = r2.json()
        if d2.get("purchase_invoice_id") == settle_d.get("purchase_invoice_id") if settle_d else True:
            print(f"  ✅ OK: double-settle is idempotent (200)")
        else:
            ISSUES.append("❌ D2: double settle returned different invoice_id")
    elif r2.status_code == 400:
        print(f"  ✅ OK: double-settle correctly rejected (400)")
    else:
        ISSUES.append(f"❌ D2: unexpected status {r2.status_code} for double-settle")
else:
    print("  ⚠️  Skipping D: no reservation from C")
    settle_d = None

print()
print("=" * 65)
print("SCENARIO E: Additional payment (سداد) after booking")
print("=" * 65)
print("  Note: cash-settlement endpoint is for WCO consumption, not reservation payment.")
print("  For adding payment to an existing reservation, use a supplier payment voucher.")

if reservation_c2 and cash_safe_id:
    res_id2 = reservation_c2["id"]
    supplier_id = office_a.get("supplier_id")

    # Get supplier's payable account for the voucher account_lines
    # The voucher API requires account_lines format
    r_accs = requests.get(f"{BASE}/accounts", headers=HDR)
    accounts_raw = r_accs.json() if r_accs.ok else []
    accounts = accounts_raw if isinstance(accounts_raw, list) else accounts_raw.get("accounts", [])
    # Find cash safe box account
    cash_safe_detail = next((s for s in safe_boxes if s.get("id") == cash_safe_id), {})
    cash_safe_account_id = cash_safe_detail.get("account_id")

    # Get supplier's linked payable account from the suppliers list
    supplier_account_id = None
    r_sup = requests.get(f"{BASE}/suppliers", headers=HDR)
    if r_sup.ok:
        sups_list = r_sup.json()
        sups_list = sups_list if isinstance(sups_list, list) else sups_list.get("suppliers", [])
        sup_data = next((s for s in sups_list if s.get("id") == supplier_id), {})
        supplier_account_id = sup_data.get("account_id")
    
    if cash_safe_account_id and supplier_account_id:
        # Create a payment voucher: cash_safe (credit) → supplier payable (debit)
        r_v = requests.post(f"{BASE}/vouchers", headers=HDR, json={
            "voucher_type": "payment",
            "party_type": "supplier",
            "supplier_id": supplier_id,
            "date": datetime.utcnow().date().isoformat(),
            "description": f"دفعة إضافية على حجز مكتب التسكير - {reservation_c2.get('reservation_code')}",
            "reference_type": "office_reservation",
            "reference_id": res_id2,
            "account_lines": [
                {"account_id": supplier_account_id, "line_type": "debit",  "amount_type": "cash", "amount": 500.0},
                {"account_id": cash_safe_account_id, "line_type": "credit", "amount_type": "cash", "amount": 500.0},
            ],
        })
        settle_e = ok(r_v, f"Payment voucher (سداد) for reservation {res_id2}")
        if settle_e:
            print(f"     voucher_id={settle_e.get('id')} num={settle_e.get('voucher_number')} status={settle_e.get('status')}")
    else:
        print(f"  ⚠️  Could not resolve accounts: cash_safe_account={cash_safe_account_id} supplier_account={supplier_account_id}")
        ISSUES.append("⚠️  E: Could not resolve accounts for payment voucher test")

print()
print("=" * 65)
print("SCENARIO F: Withdrawal from office gold vault (صرف من خزنة الذهب)")
print("=" * 65)

# Find office gold safe box
r = requests.get(f"{BASE}/safe-boxes", headers=HDR)
all_safes = r.json() if r.ok else []
if isinstance(all_safes, dict):
    all_safes = all_safes.get("safe_boxes", [])
office_gold_safe = next((s for s in all_safes
    if s.get("safe_type") == "gold" and
    str(office_a.get("supplier_id", "")) in str(s.get("name", "")) or
    str(office_id) in str(s.get("name", ""))), None)
if not office_gold_safe and gold_safe_id:
    office_gold_safe = next((s for s in all_safes if s.get("id") == gold_safe_id), None)

if office_gold_safe:
    print(f"  Using gold safe: id={office_gold_safe['id']} name={office_gold_safe['name']}")
    # Check balance first
    r = requests.get(f"{BASE}/safe-boxes/{office_gold_safe['id']}", headers=HDR)
    safe_detail = r.json() if r.ok else {}
    print(f"  Safe balance: cash={safe_detail.get('balance_cash', 0)} gold_21k={safe_detail.get('balance_gold_21k', 0)}")

    # Get the account_id for the office gold safe box
    office_gold_safe_account_id = office_gold_safe.get("account_id")
    
    # Get main gold inventory account for destination
    r_inv = requests.get(f"{BASE}/accounts", headers=HDR)
    all_accounts = r_inv.json() if r_inv.ok else []
    all_accounts = all_accounts if isinstance(all_accounts, list) else all_accounts.get("accounts", [])
    # Find scrap inventory account (1310 or similar)
    inv_account = next((a for a in all_accounts if str(a.get("account_number","")).startswith("131")), None)
    if not inv_account:
        inv_account = next((a for a in all_accounts if a.get("account_number") in ("1300","1310","130")), None)

    print(f"  office_gold_safe account_id={office_gold_safe_account_id}  inv account={inv_account.get('id') if inv_account else 'NOT FOUND'}")

    if office_gold_safe_account_id and inv_account:
        # Create a gold withdrawal journal entry (از خزنة المكتب → مخزون ذهب كسر)
        # NOTE: using /api/journal_entries (underscore, not dash)
        r = requests.post(f"{BASE}/journal_entries", headers=HDR, json={
            "date": datetime.utcnow().date().isoformat(),
            "description": f"صرف ذهب من خزنة مكتب TEST-A (اختبار)",
            "entry_type": "weight",
            "lines": [
                {
                    "account_id": inv_account["id"],
                    "debit_21k": 1.0,
                    "credit_21k": 0,
                    "description": "استلام ذهب من مكتب التسكير",
                },
                {
                    "account_id": office_gold_safe_account_id,
                    "debit_21k": 0,
                    "credit_21k": 1.0,
                    "description": "صرف ذهب من خزنة المكتب",
                },
            ],
        })
        withdrawal_f = ok(r, "Gold withdrawal journal entry from office vault")
        if withdrawal_f:
            print(f"     je_id={withdrawal_f.get('id')} number={withdrawal_f.get('entry_number')}")
    else:
        print(f"  ⚠️  Cannot test withdrawal: missing account mappings")
        ISSUES.append("⚠️  F: Missing account for gold withdrawal test")
else:
    print(f"  ⚠️  No office gold safe found for office {office_id}")
    ISSUES.append("⚠️  F: Could not identify office gold safe box for withdrawal test")

print()
print("=" * 65)
print("CANCEL TEST: Cancel a pending (unpaid) reservation")
print("=" * 65)

# Create a fresh reservation to cancel
r = requests.post(f"{BASE}/office-reservations", headers=HDR, json={
    "office_id": office_id,
    "weight": 3.0,
    "karat": 21,
    "price_per_gram": 220.0,
    "paid_amount": 0,
})
res_cancel = ok(r, "Create reservation to cancel")
if res_cancel:
    r2 = requests.post(f"{BASE}/office-reservations/{res_cancel['id']}/cancel", headers=HDR, json={})
    cancel_result = ok(r2, "Cancel unpaid reservation")
    if cancel_result:
        print(f"     status={cancel_result.get('status')} expected=cancelled")
        if cancel_result.get("status") != "cancelled":
            ISSUES.append(f"❌ Cancel: status={cancel_result.get('status')} != cancelled")

# Try to cancel a settled reservation
if reservation_c and settle_d:
    r3 = requests.post(f"{BASE}/office-reservations/{reservation_c['id']}/cancel", headers=HDR, json={})
    if r3.status_code == 400:
        print(f"  ✅ OK: Can't cancel settled reservation (400)")
    else:
        ISSUES.append(f"❌ Cancel-settled: expected 400, got {r3.status_code}")

# Try to cancel a paid reservation
if reservation_c3:
    r4 = requests.post(f"{BASE}/office-reservations/{reservation_c3['id']}/cancel", headers=HDR, json={})
    if r4.status_code == 400:
        print(f"  ✅ OK: Can't cancel paid reservation (400)")
    else:
        ISSUES.append(f"❌ Cancel-paid: expected 400, got {r4.status_code}")

print()
print("=" * 65)
print("EDGE CASES")
print("=" * 65)

# Missing office_id
r = requests.post(f"{BASE}/office-reservations", headers=HDR, json={"weight": 5.0, "price_per_gram": 200.0})
err(r, "Reservation with no office_id → 400")

# Zero weight
r = requests.post(f"{BASE}/office-reservations", headers=HDR, json={"office_id": office_id, "weight": 0, "price_per_gram": 200.0})
err(r, "Reservation with weight=0 → 400")

# Invalid karat
r = requests.post(f"{BASE}/office-reservations", headers=HDR, json={"office_id": office_id, "weight": 5.0, "price_per_gram": 200.0, "karat": 14})
err(r, "Reservation with karat=14 → 400")

# Settle already-settled
if reservation_c and settle_d:
    r = requests.post(f"{BASE}/office-reservations/{reservation_c['id']}/settle", headers=HDR, json={"execution_price_per_gram": 218.0})
    if r.status_code in (200, 201):
        print(f"  ✅ Idempotent settle (200)")
    elif r.status_code == 400:
        print(f"  ✅ Correctly rejects double settle (400)")
    else:
        ISSUES.append(f"❌ Double settle: unexpected {r.status_code}")

# ─── Summary ─────────────────────────────────────────────────────────────────
print()
print("=" * 65)
print("SUMMARY")
print("=" * 65)
if ISSUES:
    print(f"\n🔴 Found {len(ISSUES)} issue(s):\n")
    for i in ISSUES:
        print(f"  {i}")
else:
    print("\n🟢 All tests passed — no issues found.\n")
