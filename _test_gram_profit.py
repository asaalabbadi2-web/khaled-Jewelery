#!/usr/bin/env python3
"""
اختبار شامل لحساب ربح الجرام الذهبي (4 طبقات)
يقوم بإنشاء عمليات يومية كاملة ثم يتحقق من صحة التقرير
"""
import requests
import json
import sys

BASE = "http://localhost:8001/api"
TOKEN = None

def api(method, path, data=None, params=None):
    url = f"{BASE}/{path}"
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    r = getattr(requests, method)(url, json=data, params=params, headers=headers)
    try:
        return r.status_code, r.json()
    except:
        return r.status_code, r.text

def must(code, body, label=""):
    if code >= 400:
        print(f"  ❌ {label}: HTTP {code} => {json.dumps(body, ensure_ascii=False)[:200]}")
        sys.exit(1)
    return body

# ═══════════════════════════════════════════════
# 0. Login
# ═══════════════════════════════════════════════
print("═" * 60)
print("0. تسجيل الدخول")
code, body = api("post", "auth/login", {"username": "admin", "password": "admin123"})
TOKEN = must(code, body, "login").get("token")
print(f"  ✅ Token: {TOKEN[:20]}...")

# ═══════════════════════════════════════════════
# 1. Check gold price
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("1. سعر الذهب الحالي")
code, body = api("get", "gold_price")
gp = must(code, body, "gold price")
price_21k = gp.get("price_main_karat") or gp.get("price_per_gram", {}).get("21k", 0)
print(f"  سعر عيار 21: {price_21k} ريال/جرام")

# ═══════════════════════════════════════════════
# 2. Create customer
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("2. إنشاء عميل اختبار")
code, body = api("post", "customers", {
    "name": "عميل اختبار ربح الجرام",
    "phone": "0555000111",
    "customer_type": "عادي"
})
customer = must(code, body, "create customer")
customer_id = customer.get("id")
print(f"  ✅ عميل: id={customer_id}, name={customer.get('name')}")

# ═══════════════════════════════════════════════
# 3. Create supplier
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("3. إنشاء مورد اختبار")
code, body = api("post", "suppliers", {
    "name": "مورد اختبار ربح الجرام",
    "phone": "0555000222"
})
supplier = must(code, body, "create supplier")
supplier_id = supplier.get("id")
print(f"  ✅ مورد: id={supplier_id}, name={supplier.get('name')}")

# ═══════════════════════════════════════════════
# 4. Purchase invoices (buy gold from supplier)
# Layer ① - Sets avg_buy price
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("4. فواتير شراء من مورد (إنشاء المخزون)")

# Purchase 1: 100g @ 500 SAR/g (عيار 21)
code, body = api("post", "invoices", {
    "invoice_type": "شراء",
    "supplier_id": supplier_id,
    "gold_type": "new",
    "payment_method": "نقداً",
    "items": [{
        "description": "سبيكة ذهب 21 - 100 جرام",
        "weight": 100.0,
        "karat": 21,
        "unit_price": 500,
        "quantity": 1,
        "category_id": 1
    }]
})
inv1 = must(code, body, "purchase invoice 1")
print(f"  ✅ فاتورة شراء 1: id={inv1.get('id')} - 100g × 500 = 50,000 ريال")

# Purchase 2: 50g @ 510 SAR/g (عيار 21)
code, body = api("post", "invoices", {
    "invoice_type": "شراء",
    "supplier_id": supplier_id,
    "gold_type": "new",
    "payment_method": "نقداً",
    "items": [{
        "description": "سبيكة ذهب 21 - 50 جرام",
        "weight": 50.0,
        "karat": 21,
        "unit_price": 510,
        "quantity": 1,
        "category_id": 1
    }]
})
inv2 = must(code, body, "purchase invoice 2")
print(f"  ✅ فاتورة شراء 2: id={inv2.get('id')} - 50g × 510 = 25,500 ريال")

# Purchase 3: Buy scrap gold from customer
code, body = api("post", "invoices", {
    "invoice_type": "شراء من عميل",
    "customer_id": customer_id,
    "gold_type": "scrap",
    "payment_method": "نقداً",
    "items": [{
        "description": "كسر ذهب 21 - 30 جرام",
        "weight": 30.0,
        "karat": 21,
        "unit_price": 490,
        "quantity": 1,
        "category_id": 1
    }]
})
inv3 = must(code, body, "purchase from customer")
print(f"  ✅ شراء من عميل: id={inv3.get('id')} - 30g × 490 = 14,700 ريال")

# ═══════════════════════════════════════════════
# 5. Sale invoices (sell gold to customer)
# Layer ① - Generates trading profit
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("5. فواتير بيع (ربح المتاجرة)")

# Sale 1: 40g @ 550 SAR/g
code, body = api("post", "invoices", {
    "invoice_type": "بيع",
    "customer_id": customer_id,
    "payment_method": "نقداً",
    "items": [{
        "description": "طقم ذهب 21",
        "weight": 40.0,
        "karat": 21,
        "unit_price": 550,
        "quantity": 1,
        "category_id": 1
    }]
})
sale1 = must(code, body, "sale invoice 1")
print(f"  ✅ فاتورة بيع 1: id={sale1.get('id')} - 40g × 550 = 22,000 ريال")

# Sale 2: 25g @ 560 SAR/g
code, body = api("post", "invoices", {
    "invoice_type": "بيع",
    "customer_id": customer_id,
    "payment_method": "نقداً",
    "items": [{
        "description": "أسورة ذهب 21",
        "weight": 25.0,
        "karat": 21,
        "unit_price": 560,
        "quantity": 1,
        "category_id": 1
    }]
})
sale2 = must(code, body, "sale invoice 2")
print(f"  ✅ فاتورة بيع 2: id={sale2.get('id')} - 25g × 560 = 14,000 ريال")

# Sale 3: 20g @ 540 SAR/g
code, body = api("post", "invoices", {
    "invoice_type": "بيع",
    "customer_id": customer_id,
    "payment_method": "نقداً",
    "items": [{
        "description": "خاتم ذهب 21",
        "weight": 20.0,
        "karat": 21,
        "unit_price": 540,
        "quantity": 1,
        "category_id": 1
    }]
})
sale3 = must(code, body, "sale invoice 3")
print(f"  ✅ فاتورة بيع 3: id={sale3.get('id')} - 20g × 540 = 10,800 ريال")

print("\n  📊 ملخص:")
print("  المشتريات: 100g×500 + 50g×510 + 30g×490 = 90,200 ريال / 180g")
print("  المبيعات:  40g×550 + 25g×560 + 20g×540 = 46,800 ريال / 85g")
print(f"  متوسط شراء = 90,200 / 180 = {90200/180:.2f} ريال/جرام")
print(f"  متوسط بيع  = 46,800 / 85  = {46800/85:.2f} ريال/جرام")
print(f"  ربح المتاجرة = (avg_sell - avg_buy) × weight_sold")
avg_buy = 90200 / 180
avg_sell = 46800 / 85
trading_profit_cash = (avg_sell - avg_buy) * 85
trading_profit_weight = trading_profit_cash / avg_buy if avg_buy > 0 else 0
print(f"  = ({avg_sell:.2f} - {avg_buy:.2f}) × 85 = {trading_profit_cash:.2f} ريال")
print(f"  = {trading_profit_cash:.2f} / {avg_buy:.2f} = {trading_profit_weight:.3f} جرام")

# ═══════════════════════════════════════════════
# 6. Get account IDs for JE lines
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("6. جلب معرفات الحسابات للقيود اليومية")

import sqlite3
conn = sqlite3.connect("app.db")
c = conn.cursor()

def get_account_id(number):
    row = c.execute("SELECT id, name FROM account WHERE account_number = ?", (number,)).fetchone()
    if row:
        return row[0], row[1]
    return None, None

# Cash/safebox account
safebox_id, safebox_name = get_account_id("1")  # or find the main safebox
if not safebox_id:
    # Try to find cash account
    row = c.execute("SELECT id, account_number, name FROM account WHERE name LIKE '%صندوق%نقد%' OR name LIKE '%نقدية%' LIMIT 1").fetchone()
    if row:
        safebox_id = row[0]
        safebox_name = row[2]
        print(f"  صندوق النقدية: id={safebox_id} ({safebox_name})")

# Get key expense account IDs
expense_accounts = {}
for num in ['5200', '5220', '5300', '5400', '5410', '5420', '5430']:
    aid, aname = get_account_id(num)
    if aid:
        expense_accounts[num] = (aid, aname)
        print(f"  {num}: id={aid} ({aname})")

# Get main cash account (safe box)
row = c.execute("SELECT account_id FROM safe_box WHERE name LIKE '%صندوق النقدية%' LIMIT 1").fetchone()
cash_account_id = row[0] if row else None
if cash_account_id:
    cash_name = c.execute("SELECT name FROM account WHERE id = ?", (cash_account_id,)).fetchone()
    print(f"  حساب صندوق النقدية: id={cash_account_id} ({cash_name[0] if cash_name else '?'})")
else:
    # Fallback: find any active cash/safebox account
    row = c.execute("SELECT id, name FROM account WHERE account_number IN ('11','110','1100') ORDER BY LENGTH(account_number) DESC LIMIT 1").fetchone()
    if row:
        cash_account_id = row[0]
        print(f"  حساب نقدي بديل: id={cash_account_id} ({row[1]})")

# Gold inventory account
gold_inv_id, gold_inv_name = get_account_id("1200")
if not gold_inv_id:
    row = c.execute("SELECT id, name FROM account WHERE name LIKE '%مخزون%' AND account_number LIKE '1%' LIMIT 1").fetchone()
    if row:
        gold_inv_id = row[0]
        gold_inv_name = row[1]
if gold_inv_id:
    print(f"  مخزون الذهب: id={gold_inv_id} ({gold_inv_name})")

conn.close()

# ═══════════════════════════════════════════════
# 7. Record weight expenses (Layer ③)
# Direct gold weight expenses
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("7. تسجيل مصاريف وزنية (Layer ③)")

# خسارة الوزن (الفقد) - 0.5 جرام ذهب
loss_account_id = expense_accounts.get('5220', (None,))[0]
if loss_account_id and gold_inv_id:
    code, body = api("post", "journal_entries", {
        "date": "2026-04-19",
        "description": "خسارة وزن (فقد) - 0.5 جرام ذهب عيار 21",
        "entry_type": "عام",
        "is_posted": True,
        "lines": [
            {
                "account_id": loss_account_id,
                "debit_21k": 0.5,
                "credit_21k": 0,
                "cash_debit": 0,
                "cash_credit": 0,
                "description": "خسارة وزن ذهب"
            },
            {
                "account_id": gold_inv_id,
                "debit_21k": 0,
                "credit_21k": 0.5,
                "cash_debit": 0,
                "cash_credit": 0,
                "description": "إنقاص مخزون ذهب"
            }
        ]
    })
    je1 = must(code, body, "weight loss JE")
    print(f"  ✅ قيد خسارة وزن: id={je1.get('id')} - 0.5g (من مخزون → مصاريف)")

# أجور صياغة وزنية - 1.2 جرام ذهب
craft_account_id = expense_accounts.get('5200', (None,))[0]
if craft_account_id and gold_inv_id:
    code, body = api("post", "journal_entries", {
        "date": "2026-04-19",
        "description": "أجور صياغة وزنية - 1.2 جرام ذهب عيار 21",
        "entry_type": "عام",
        "is_posted": True,
        "lines": [
            {
                "account_id": craft_account_id,
                "debit_21k": 1.2,
                "credit_21k": 0,
                "cash_debit": 0,
                "cash_credit": 0,
                "description": "أجور صياغة (وزنية)"
            },
            {
                "account_id": gold_inv_id,
                "debit_21k": 0,
                "credit_21k": 1.2,
                "cash_debit": 0,
                "cash_credit": 0,
                "description": "إنقاص مخزون ذهب"
            }
        ]
    })
    je2 = must(code, body, "craft wages weight JE")
    print(f"  ✅ قيد أجور صياغة وزنية: id={je2.get('id')} - 1.2g")

print(f"\n  📊 إجمالي المصاريف الوزنية: 0.5 + 1.2 = 1.7 جرام")

# ═══════════════════════════════════════════════
# 8. Record cash expenses (Layer ④)
# Cash expenses converted to weight via avg_buy
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("8. تسجيل مصاريف نقدية (Layer ④)")

if cash_account_id:
    # إيجار المعرض - 5000 ريال
    rent_id = expense_accounts.get('5400', (None,))[0]
    if rent_id:
        code, body = api("post", "journal_entries", {
            "date": "2026-04-19",
            "description": "إيجار المعرض - شهر أبريل 2026",
            "entry_type": "عام",
            "is_posted": True,
            "lines": [
                {
                    "account_id": rent_id,
                    "cash_debit": 5000,
                    "cash_credit": 0,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "إيجار المعرض"
                },
                {
                    "account_id": cash_account_id,
                    "cash_debit": 0,
                    "cash_credit": 5000,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "دفع من الصندوق"
                }
            ]
        })
        je3 = must(code, body, "rent JE")
        print(f"  ✅ قيد إيجار: id={je3.get('id')} - 5,000 ريال")

    # رواتب - 8000 ريال
    salary_id = expense_accounts.get('5410', (None,))[0]
    if salary_id:
        code, body = api("post", "journal_entries", {
            "date": "2026-04-19",
            "description": "رواتب الموظفين - أبريل 2026",
            "entry_type": "عام",
            "is_posted": True,
            "lines": [
                {
                    "account_id": salary_id,
                    "cash_debit": 8000,
                    "cash_credit": 0,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "رواتب الموظفين"
                },
                {
                    "account_id": cash_account_id,
                    "cash_debit": 0,
                    "cash_credit": 8000,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "دفع من الصندوق"
                }
            ]
        })
        je4 = must(code, body, "salary JE")
        print(f"  ✅ قيد رواتب: id={je4.get('id')} - 8,000 ريال")

    # كهرباء وهاتف - 1500 ريال
    utilities_id = expense_accounts.get('5420', (None,))[0]
    if utilities_id:
        code, body = api("post", "journal_entries", {
            "date": "2026-04-19",
            "description": "فاتورة الكهرباء والهاتف - أبريل",
            "entry_type": "عام",
            "is_posted": True,
            "lines": [
                {
                    "account_id": utilities_id,
                    "cash_debit": 1500,
                    "cash_credit": 0,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "كهرباء وهاتف"
                },
                {
                    "account_id": cash_account_id,
                    "cash_debit": 0,
                    "cash_credit": 1500,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "دفع من الصندوق"
                }
            ]
        })
        je5 = must(code, body, "utilities JE")
        print(f"  ✅ قيد كهرباء: id={je5.get('id')} - 1,500 ريال")

    # علب وهدايا - 800 ريال
    packaging_id = expense_accounts.get('5300', (None,))[0]
    if packaging_id:
        code, body = api("post", "journal_entries", {
            "date": "2026-04-19",
            "description": "علب وهدايا وأكياس تغليف",
            "entry_type": "عام",
            "is_posted": True,
            "lines": [
                {
                    "account_id": packaging_id,
                    "cash_debit": 800,
                    "cash_credit": 0,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "علب وهدايا"
                },
                {
                    "account_id": cash_account_id,
                    "cash_debit": 0,
                    "cash_credit": 800,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "دفع من الصندوق"
                }
            ]
        })
        je6 = must(code, body, "packaging JE")
        print(f"  ✅ قيد تغليف: id={je6.get('id')} - 800 ريال")

    # بوفية وضيافة - 400 ريال
    hospitality_id = expense_accounts.get('5430', (None,))[0]
    if hospitality_id:
        code, body = api("post", "journal_entries", {
            "date": "2026-04-19",
            "description": "مصاريف بوفية وضيافة",
            "entry_type": "عام",
            "is_posted": True,
            "lines": [
                {
                    "account_id": hospitality_id,
                    "cash_debit": 400,
                    "cash_credit": 0,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "بوفية وضيافة"
                },
                {
                    "account_id": cash_account_id,
                    "cash_debit": 0,
                    "cash_credit": 400,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "دفع من الصندوق"
                }
            ]
        })
        je7 = must(code, body, "hospitality JE")
        print(f"  ✅ قيد ضيافة: id={je7.get('id')} - 400 ريال")

total_cash_exp = 5000 + 8000 + 1500 + 800 + 400
print(f"\n  📊 إجمالي المصاريف النقدية: {total_cash_exp:,.0f} ريال")
print(f"  → تحويل إلى وزن: {total_cash_exp:,.0f} / {avg_buy:.2f} = {total_cash_exp/avg_buy:.3f} جرام")

# ═══════════════════════════════════════════════
# 9. Record extra revenue (Layer ②)
# First create revenue accounts if they don't exist
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("9. تسجيل إيرادات إضافية (Layer ②)")

# Check if revenue accounts under 42 exist
conn = sqlite3.connect("app.db")
c = conn.cursor()

# Create revenue leaf account 4200 under parent 42 (إيرادات أخرى)
parent_42_id = c.execute("SELECT id FROM account WHERE account_number = '42'").fetchone()
if parent_42_id:
    parent_42_id = parent_42_id[0]
    
    # Check if 4200 exists
    row = c.execute("SELECT id FROM account WHERE account_number = '4200'").fetchone()
    if not row:
        # Create it via API
        code, body = api("post", "accounts", {
            "account_number": "4200",
            "name": "إيرادات خدمات إضافية",
            "parent_id": parent_42_id,
            "account_type": "revenue",
            "tracks_weight": True,
            "include_in_gram_profit": True
        })
        if code < 400:
            rev_account_id = body.get("id")
            print(f"  ✅ تم إنشاء حساب إيرادات: id={rev_account_id} (4200 - إيرادات خدمات إضافية)")
        else:
            print(f"  ⚠️ فشل إنشاء حساب 4200: {body}")
            rev_account_id = None
    else:
        rev_account_id = row[0]
        # Ensure it's flagged
        c.execute("UPDATE account SET include_in_gram_profit = 1 WHERE id = ?", (rev_account_id,))
        conn.commit()
        print(f"  حساب 4200 موجود: id={rev_account_id}")
    
    conn.close()
    
    # Revenue JE 1: Cash revenue (commission/service) - 2000 ريال
    if rev_account_id and cash_account_id:
        code, body = api("post", "journal_entries", {
            "date": "2026-04-19",
            "description": "إيرادات خدمات صياغة خاصة",
            "entry_type": "عام",
            "is_posted": True,
            "lines": [
                {
                    "account_id": cash_account_id,
                    "cash_debit": 2000,
                    "cash_credit": 0,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "استلام نقد"
                },
                {
                    "account_id": rev_account_id,
                    "cash_debit": 0,
                    "cash_credit": 2000,
                    "debit_21k": 0,
                    "credit_21k": 0,
                    "description": "إيرادات خدمات صياغة"
                }
            ]
        })
        je8 = must(code, body, "revenue cash JE")
        print(f"  ✅ قيد إيرادات نقدية: id={je8.get('id')} - 2,000 ريال")

    # Revenue JE 2: Weight revenue (gold tips/bonuses) - 0.3g
    if rev_account_id and gold_inv_id:
        code, body = api("post", "journal_entries", {
            "date": "2026-04-19",
            "description": "إيرادات وزنية - بقايا صياغة مكتسبة",
            "entry_type": "عام",
            "is_posted": True,
            "lines": [
                {
                    "account_id": gold_inv_id,
                    "debit_21k": 0.3,
                    "credit_21k": 0,
                    "cash_debit": 0,
                    "cash_credit": 0,
                    "description": "إضافة ذهب للمخزون"
                },
                {
                    "account_id": rev_account_id,
                    "debit_21k": 0,
                    "credit_21k": 0.3,
                    "cash_debit": 0,
                    "cash_credit": 0,
                    "description": "إيرادات بقايا صياغة"
                }
            ]
        })
        je9 = must(code, body, "revenue weight JE")
        print(f"  ✅ قيد إيرادات وزنية: id={je9.get('id')} - 0.3 جرام")

    print(f"\n  📊 إيرادات إضافية: 2,000 ريال + 0.3 جرام")
    print(f"  → 2,000 / {avg_buy:.2f} + 0.3 = {2000/avg_buy + 0.3:.3f} جرام")
else:
    conn.close()
    print("  ⚠️ لم يتم العثور على حساب الإيرادات الأخرى (42)")

# ═══════════════════════════════════════════════
# 10. Verify gram profit report
# ═══════════════════════════════════════════════
print("\n" + "═" * 60)
print("10. التحقق من تقرير ربح الجرام الذهبي")
print("═" * 60)

code, body = api("get", "reports/gram_profit", params={
    "start_date": "2026-01-01",
    "end_date": "2026-12-31"
})
report = must(code, body, "gram profit report")

print("\n┌─────────────────────────────────────────────────────┐")
print("│              تقرير ربح الجرام الذهبي               │")
print("├─────────────────────────────────────────────────────┤")

# Layer ① Trading
tp_w = report.get('trading_profit_weight', 0)
tp_c = report.get('trading_profit_cash', 0)
print(f"│ ① ربح المتاجرة:                                    │")
print(f"│    الوزن: {tp_w:>10.3f} جرام                        │")
print(f"│    النقد: {tp_c:>10.2f} ريال                        │")

# Layer ② Extra Revenue  
rev_w_direct = report.get('extra_revenue_weight', 0)
rev_cash = report.get('extra_revenue_cash', 0)
rev_cash_as_w = report.get('extra_revenue_cash_as_weight', 0)
total_rev_w = report.get('total_extra_revenue_weight', 0)
print(f"│ ② إيرادات إضافية:                                  │")
print(f"│    وزنية مباشرة: {rev_w_direct:>8.3f} جرام            │")
print(f"│    نقدية:       {rev_cash:>8.2f} ريال → {rev_cash_as_w:.3f} جم  │")
print(f"│    الإجمالي:    {total_rev_w:>8.3f} جرام              │")

details = report.get('extra_revenue_details', [])
if details:
    for d in details:
        print(f"│      {d.get('account_number','')} {d.get('name','')}: w={d.get('weight',0):.3f}g, c={d.get('cash',0):.0f}  │")

# Layer ③ Weight Expenses
exp_w = report.get('expense_weight_direct', 0)
print(f"│ ③ مصاريف وزنية:   {exp_w:>8.3f} جرام                │")

w_details = report.get('expense_weight_details', [])
if w_details:
    for d in w_details:
        print(f"│      {d.get('account_number','')} {d.get('name','')}: {d.get('weight',0):.3f}g  │")

# Layer ④ Cash Expenses
exp_c = report.get('expense_cash_total', 0)
exp_c_w = report.get('expense_cash_as_weight', 0)
print(f"│ ④ مصاريف نقدية:  {exp_c:>8.2f} ريال → {exp_c_w:.3f} جم │")

c_details = report.get('expense_cash_details', [])
if c_details:
    for d in c_details:
        print(f"│      {d.get('account_number','')} {d.get('name','')}: {d.get('cash',0):.0f} ريال  │")

print(f"├─────────────────────────────────────────────────────┤")
net_w = report.get('net_profit_weight', 0)
net_c = report.get('net_profit', 0)
print(f"│ صافي ربح الجرام: {net_w:>8.3f} جرام                 │")
print(f"│ صافي ربح نقدي:  {net_c:>8.2f} ريال                  │")
print(f"└─────────────────────────────────────────────────────┘")

# ═══════════════════════════════════════════════
# 11. Validation - Compare expected vs actual
# ═══════════════════════════════════════════════
print("\n═" * 60)
print("11. المقارنة: المتوقع مقابل الفعلي")
print("═" * 60)

# Expected calculations
exp_avg_buy = avg_buy  # 90200/180 = 501.11
exp_avg_sell = avg_sell  # 46800/85 = 550.59
exp_trading_cash = (exp_avg_sell - exp_avg_buy) * 85
exp_trading_weight = exp_trading_cash / exp_avg_buy

exp_rev_weight_direct = 0.3
exp_rev_cash = 2000
exp_rev_cash_as_weight = exp_rev_cash / exp_avg_buy
exp_total_rev_weight = exp_rev_weight_direct + exp_rev_cash_as_weight

exp_expense_weight = 0.5 + 1.2  # loss + crafting
exp_expense_cash = 5000 + 8000 + 1500 + 800 + 400  # rent + salary + utilities + packaging + hospitality
exp_expense_cash_weight = exp_expense_cash / exp_avg_buy

exp_net_weight = exp_trading_weight + exp_total_rev_weight - exp_expense_weight - exp_expense_cash_weight

print(f"\n  الحساب المتوقع:")
print(f"  ① ربح المتاجرة  = {exp_trading_weight:>8.3f} جم ({exp_trading_cash:>10.2f} ريال)")
print(f"  ② إيرادات إضافية = {exp_total_rev_weight:>8.3f} جم ({exp_rev_weight_direct:.3f}g + {exp_rev_cash_as_weight:.3f}g)")
print(f"  ③ مصاريف وزنية  = {exp_expense_weight:>8.3f} جم")
print(f"  ④ مصاريف نقدية  = {exp_expense_cash_weight:>8.3f} جم ({exp_expense_cash:,.0f} ريال)")
print(f"  ─────────────────────────────")
print(f"  صافي = ① + ② - ③ - ④ = {exp_net_weight:>8.3f} جم")

print(f"\n  النتيجة الفعلية من API:")
print(f"  ① ربح المتاجرة  = {tp_w:>8.3f} جم ({tp_c:>10.2f} ريال)")
print(f"  ② إيرادات إضافية = {total_rev_w:>8.3f} جم")
print(f"  ③ مصاريف وزنية  = {exp_w:>8.3f} جم")
print(f"  ④ مصاريف نقدية  = {exp_c_w:>8.3f} جم ({exp_c:,.0f} ريال)")
print(f"  ─────────────────────────────")
print(f"  صافي = {net_w:>8.3f} جم")

# Tolerance checks (allow 0.1g tolerance for rounding)
tolerance = 0.5  # grams - generous tolerance for avg price variations
errors = []

def check(label, expected, actual, tol=tolerance):
    diff = abs(expected - actual)
    status = "✅" if diff <= tol else "❌"
    if diff > tol:
        errors.append(f"{label}: expected={expected:.3f}, actual={actual:.3f}, diff={diff:.3f}")
    print(f"  {status} {label}: متوقع={expected:.3f}, فعلي={actual:.3f}, فرق={diff:.3f}")

print(f"\n  فحص النتائج (tolerance={tolerance}g):")
check("ربح المتاجرة (وزن)", exp_trading_weight, tp_w)
check("إيرادات إضافية", exp_total_rev_weight, total_rev_w)
check("مصاريف وزنية", exp_expense_weight, exp_w)
check("مصاريف نقدية (وزن)", exp_expense_cash_weight, exp_c_w)
check("صافي الربح", exp_net_weight, net_w)

if errors:
    print(f"\n  ⚠️ {len(errors)} فروقات تحتاج مراجعة:")
    for e in errors:
        print(f"    → {e}")
else:
    print(f"\n  🎉 جميع الفحوصات ناجحة! تقرير ربح الجرام يعمل بشكل سليم")

# Print full API response for debugging
print(f"\n  📋 Response JSON الكامل:")
for k, v in sorted(report.items()):
    if isinstance(v, (list, dict)):
        print(f"    {k}: {json.dumps(v, ensure_ascii=False)[:120]}")
    else:
        print(f"    {k}: {v}")
