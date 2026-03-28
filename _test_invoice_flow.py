#!/usr/bin/env python3
"""
Diagnostic: Create a test sale invoice and watch safe-box balances + reconciliation.
"""
import json, sys, requests, datetime

BASE = "http://localhost:8001/api"
CREDS = {"username": "admin", "password": "admin123"}

# ── auth ──
r = requests.post(f"{BASE}/auth/login", json=CREDS)
token = r.json().get("access_token") or r.json().get("token", "")
if not token:
    sys.exit(f"❌ Auth failed: {r.text}")
H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print(f"✅ Logged in as admin")

# ── helpers ──
def recon():
    d = requests.get(f"{BASE}/safe-boxes/reconciliation", headers=H).json()
    rows = {r["safe_box_id"]: r for r in d.get("summary", [])}
    return rows

def show_recon(label, rows):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  {'SB':>3} | {'name':<22} | {'SBT':>12} | {'GL':>12} | {'diff':>10}")
    print(f"  {'-'*3}-+-{'-'*22}-+-{'-'*12}-+-{'-'*12}-+-{'-'*10}")
    for sid, r in sorted(rows.items()):
        diff = r['diff']
        flag = " ⚠️" if abs(diff) > 0.01 else ""
        print(f"  {sid:>3} | {str(r['safe_box_name']):<22} | {r['sb_total']:>12.2f} | {r['gl_total']:>12.2f} | {diff:>+10.2f}{flag}")

def je_detail():
    """Fetch last 10 JEs and show their is_posted flag."""
    d = requests.get(f"{BASE}/journal-entries?limit=15&sort_by=id&sort_dir=desc", headers=H)
    if d.status_code != 200:
        return []
    items = d.json().get("data") or d.json().get("items") or d.json() or []
    if isinstance(items, dict):
        items = items.get("data") or items.get("items") or []
    return items

# ── pre-state ──
pre = recon()
show_recon("BEFORE invoice", pre)

# ── find customer + item + payment method ──
customers = requests.get(f"{BASE}/customers?limit=5", headers=H).json()
if isinstance(customers, list):
    cust_list = customers
elif isinstance(customers, dict):
    cust_list = customers.get("data") or customers.get("items") or []
else:
    cust_list = []
customer_id = cust_list[0]["id"] if cust_list else None
print(f"\n  customer_id = {customer_id}")

items_resp = requests.get(f"{BASE}/items?limit=5", headers=H).json()
if isinstance(items_resp, list):
    items_list = items_resp
elif isinstance(items_resp, dict):
    items_list = items_resp.get("data") or items_resp.get("items") or []
else:
    items_list = []
item_id = items_list[0]["id"] if items_list else None
item_weight = float(items_list[0].get("weight") or 5.0) if items_list else 5.0
item_karat  = int(items_list[0].get("karat") or 21) if items_list else 21
print(f"  item_id = {item_id}  weight={item_weight}  karat={item_karat}")

pms = requests.get(f"{BASE}/payment-methods?is_active=true", headers=H).json()
if isinstance(pms, list):
    pm_list = pms
elif isinstance(pms, dict):
    pm_list = pms.get("data") or pms.get("items") or []
else:
    pm_list = []
pm_obj = next((p for p in pm_list if "نقد" in str(p.get("name",""))), pm_list[0] if pm_list else None)
pm_id = pm_obj["id"] if pm_obj else None
print(f"  payment_method_id = {pm_id}  ({pm_obj.get('name') if pm_obj else 'none'})")

# ── safe-box ──
sbs = requests.get(f"{BASE}/safe-boxes", headers=H).json()
if isinstance(sbs, list):
    sb_list = sbs
elif isinstance(sbs, dict):
    sb_list = sbs.get("data") or sbs.get("items") or []
else:
    sb_list = []
cash_sb = next((s for s in sb_list if s.get("safe_type") == "cash"), sb_list[0] if sb_list else None)
sb_id = cash_sb["id"] if cash_sb else None
print(f"  safe_box_id = {sb_id}  ({cash_sb.get('name') if cash_sb else 'none'})")

if not all([customer_id, item_id, pm_id]):
    sys.exit("❌ Missing data — cannot create test invoice")

price_per_gram = 474.0
total = round(item_weight * price_per_gram, 2)

payload = {
    "invoice_type": "بيع",
    "customer_id": customer_id,
    "date": datetime.date.today().isoformat(),
    "total": total,
    "total_weight": item_weight,
    "amount_paid": total,
    "items": [
        {
            "item_id": item_id,
            "weight": item_weight,
            "karat": item_karat,
            "price_per_gram": price_per_gram,
            "total": total,
        }
    ],
    "payments": [
        {
            "payment_method_id": pm_id,
            "amount": total,
            "safe_box_id": sb_id,
        }
    ],
    "safe_box_id": sb_id,
}

print(f"\n{'='*60}")
print(f"  Creating invoice: بيع  total={total}  weight={item_weight}g")
print(f"{'='*60}")

resp = requests.post(f"{BASE}/invoices", json=payload, headers=H)
print(f"  HTTP {resp.status_code}")

if resp.status_code not in (200, 201):
    print(f"  ❌ Failed: {resp.text[:800]}")
    sys.exit(1)

inv = resp.json()
inv_id = inv.get("id")
print(f"  ✅ Invoice created: id={inv_id}  is_posted={inv.get('is_posted')}  status={inv.get('status')}")
print(f"     approval_required={inv.get('approval_required')}  approval_reason={inv.get('approval_reason')}")

# ── Journal Entries ──
print(f"\n--- Journal Entries linked to invoice #{inv_id} ---")
jes = requests.get(f"{BASE}/journal-entries?reference_type=invoice&reference_id={inv_id}&limit=20", headers=H)
if jes.status_code == 200:
    je_data = jes.json()
    je_list = je_data.get("data") or je_data.get("items") or je_data if isinstance(je_data, list) else []
    if isinstance(je_data, dict):
        je_list = je_data.get("data") or je_data.get("items") or []
    for je in je_list:
        print(f"  JE #{je['id']}  ref={je.get('reference_type')}/{je.get('reference_id')}  is_posted={je.get('is_posted')}  type={je.get('entry_type','?')}")
else:
    print(f"  (journal-entries query returned {jes.status_code})")

# ── Vouchers ──
print(f"\n--- Vouchers linked to invoice #{inv_id} ---")
vch = requests.get(f"{BASE}/vouchers?reference_type=invoice&reference_id={inv_id}&limit=20", headers=H)
if vch.status_code == 200:
    vch_data = vch.json()
    vch_list = vch_data.get("data") or vch_data.get("items") or vch_data if isinstance(vch_data, list) else []
    if isinstance(vch_data, dict):
        vch_list = vch_data.get("data") or vch_data.get("items") or []
    for v in vch_list:
        print(f"  Voucher #{v['id']}  status={v.get('status')}  journal_entry_id={v.get('journal_entry_id')}")
        # Fetch voucher JE
        if v.get("journal_entry_id"):
            vje = requests.get(f"{BASE}/journal-entries/{v['journal_entry_id']}", headers=H)
            if vje.status_code == 200:
                vd = vje.json()
                print(f"    └─ Voucher JE #{vd['id']}  is_posted={vd.get('is_posted')}  is_draft={vd.get('is_draft')}")
                for ln in (vd.get("lines") or []):
                    print(f"       line: acct={ln.get('account_id')}  dr={ln.get('cash_debit',0)}  cr={ln.get('cash_credit',0)}")
elif vch.status_code == 404:
    print(f"  (no voucher endpoint or 404)")
else:
    print(f"  (vouchers query returned {vch.status_code}: {vch.text[:200]})")

# ── SafeBoxTransactions ──
print(f"\n--- SafeBoxTransactions for invoice #{inv_id} ---")
import sqlite3, os
db_path = os.path.expanduser("~/yasargold/app.db")
if os.path.exists(db_path):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT id, safe_box_id, direction, amount_cash, ref_type, ref_id, invoice_id FROM safe_box_transaction WHERE invoice_id=? OR ref_id=?", (inv_id, inv_id))
    rows = cur.fetchall()
    if rows:
        for row in rows:
            print(f"  SBT #{row[0]}  safe={row[1]}  dir={row[2]}  amt={row[3]}  ref_type={row[4]}  ref_id={row[5]}  invoice_id={row[6]}")
    else:
        print("  ⚠️  NO SafeBoxTransactions found for this invoice!")
    con.close()
else:
    print(f"  DB not found at {db_path}")

# ── post-state ──
import time
time.sleep(1)
post = recon()
show_recon("AFTER invoice", post)

# ── diff ──
print(f"\n{'='*60}")
print(f"  DELTA (after - before)")
print(f"{'='*60}")
all_ids = set(pre) | set(post)
for sid in sorted(all_ids):
    b = pre.get(sid, {})
    a = post.get(sid, {})
    dsbt = (a.get("sb_total",0) or 0) - (b.get("sb_total",0) or 0)
    dgl  = (a.get("gl_total",0) or 0) - (b.get("gl_total",0) or 0)
    ddiff = (a.get("diff",0) or 0) - (b.get("diff",0) or 0)
    if abs(dsbt) > 0.001 or abs(dgl) > 0.001:
        flag = " ⚠️  MISMATCH" if abs(ddiff) > 0.01 else " ✅"
        print(f"  SB {sid:>3}: ΔSBT={dsbt:+.2f}  ΔGL={dgl:+.2f}  Δdiff={ddiff:+.2f}{flag}")
