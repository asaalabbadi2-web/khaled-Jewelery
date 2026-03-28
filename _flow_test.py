"""
فاتورة بيع + سند صرف — مراقبة الأثر على الخزائن والأستاذ العام
"""
import requests, json, sqlite3, textwrap

BASE = "http://localhost:8001/api"
DB   = "/Users/salehalabbadi/yasargold/app.db"

# ────────────────────────────────────────────────
def login():
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": "admin", "password": "admin123"})
    d = r.json()
    return d.get("access_token") or d.get("token", "")

def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# ────────────────────────────────────────────────
def snapshot(label, token):
    """جلب لقطة من الخزائن + الأستاذ العام للحساب 15"""
    con = sqlite3.connect(DB)
    cur = con.cursor()

    # الخزائن
    cur.execute("""
        SELECT sb.id, sb.name, sb.account_id,
               COALESCE(SUM(CASE WHEN t.direction='in'  THEN t.amount_cash
                                 ELSE -t.amount_cash END),0) AS sbt_net
        FROM safe_box sb
        LEFT JOIN safe_box_transaction t ON t.safe_box_id = sb.id
        WHERE sb.safe_type='cash'
        GROUP BY sb.id, sb.name, sb.account_id
        ORDER BY sb.id
    """)
    safes = {}
    for row in cur.fetchall():
        sb_id, sb_name, acct_id, sbt = row
        # رصيد الأستاذ العام للحساب
        cur.execute("""
            SELECT COALESCE(SUM(COALESCE(jl.cash_debit,0)-COALESCE(jl.cash_credit,0)),0)
            FROM journal_entry_line jl
            JOIN journal_entry je ON jl.journal_entry_id=je.id
            WHERE jl.account_id=? AND je.is_posted=1 AND COALESCE(jl.is_deleted,0)=0
        """, (acct_id,))
        gl = cur.fetchone()[0] or 0
        safes[sb_id] = {"name": sb_name, "account_id": acct_id,
                        "sbt": round(sbt, 4), "gl": round(gl, 4),
                        "diff": round(sbt - gl, 4)}
    con.close()

    # عدد SBTs وJournalLines
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM safe_box_transaction")
    total_sbt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM journal_entry_line")
    total_jl  = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM journal_entry WHERE is_posted=1")
    posted_je = cur.fetchone()[0]
    con.close()

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  {'SB':>3} | {'الاسم':<28} | {'SBT':>12} | {'GL':>12} | {'فرق':>10}")
    print(f"  {'-'*3}-+-{'-'*28}-+-{'-'*12}-+-{'-'*12}-+-{'-'*10}")
    for sid, d in safes.items():
        flag = " ⚠️" if abs(d["diff"]) > 0.01 else " ✅"
        print(f"  {sid:>3} | {d['name']:<28} | {d['sbt']:>12,.2f} | {d['gl']:>12,.2f} | {d['diff']:>+10,.2f}{flag}")
    print(f"\n  إجمالي SBTs={total_sbt}  JournalLines={total_jl}  JEs مرحّلة={posted_je}")
    return safes

# ────────────────────────────────────────────────
def delta(before, after, label):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    print(f"  {'SB':>3} | {'الاسم':<28} | {'ΔSBT':>12} | {'ΔGL':>12} | {'Δفرق':>10}")
    print(f"  {'-'*3}-+-{'-'*28}-+-{'-'*12}-+-{'-'*12}-+-{'-'*10}")
    ids = sorted(set(before) | set(after))
    any_change = False
    for sid in ids:
        b = before.get(sid, {"sbt": 0, "gl": 0, "diff": 0, "name": "?"})
        a = after.get(sid, {"sbt": 0, "gl": 0, "diff": 0, "name": b["name"]})
        dsbt  = round(a["sbt"]  - b["sbt"],  4)
        dgl   = round(a["gl"]   - b["gl"],   4)
        ddiff = round(a["diff"] - b["diff"],  4)
        if abs(dsbt) > 0.001 or abs(dgl) > 0.001:
            any_change = True
            flag = " ✅" if abs(ddiff) < 0.01 else " ❌"
            print(f"  {sid:>3} | {b['name']:<28} | {dsbt:>+12,.2f} | {dgl:>+12,.2f} | {ddiff:>+10,.2f}{flag}")
    if not any_change:
        print("  (لا تغيير في الخزائن النقدية)")

# ────────────────────────────────────────────────
def show_je_lines(je_id, token=None):
    """عرض سطور قيد محاسبي مباشرة من DB"""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT je.id, je.reference_type, je.reference_id, je.is_posted, je.is_draft
        FROM journal_entry je WHERE je.id=?
    """, (je_id,))
    je_row = cur.fetchone()
    if not je_row:
        print(f"    [JE #{je_id} : غير موجود]")
        con.close()
        return
    print(f"    JE #{je_row[0]}  reference={je_row[1]}/{je_row[2]}  "
          f"is_posted={'✅' if je_row[3] else '⚠️ غير مرحّل'}  is_draft={je_row[4]}")
    cur.execute("""
        SELECT jl.account_id, a.name, jl.cash_debit, jl.cash_credit
        FROM journal_entry_line jl
        LEFT JOIN account a ON a.id=jl.account_id
        WHERE jl.journal_entry_id=? AND COALESCE(jl.is_deleted,0)=0
    """, (je_id,))
    for ln in cur.fetchall():
        dr = ln[2] or 0
        cr = ln[3] or 0
        side = f"مدين  {dr:>12,.2f}" if dr else f"دائن  {cr:>12,.2f}"
        print(f"      | حساب {ln[0]:>5} ({(ln[1] or '')[:25]:<25}) → {side}")
    con.close()

# ────────────────────────────────────────────────
def show_sbts_for_invoice(inv_id):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT t.id, t.safe_box_id, sb.name, t.ref_type, t.ref_id,
               t.direction, t.amount_cash
        FROM safe_box_transaction t
        JOIN safe_box sb ON sb.id=t.safe_box_id
        WHERE t.invoice_id=?
        ORDER BY t.id
    """, (inv_id,))
    rows = cur.fetchall()
    con.close()
    if rows:
        print(f"    SBTs لفاتورة #{inv_id}:")
        for r in rows:
            print(f"      SBT#{r[0]}  خزينة {r[1]}({r[2][:20]})  "
                  f"ref={r[3]}/{r[4]}  {r[5]}  {r[6]:,.2f}")
    else:
        print(f"    (لا SBTs لفاتورة #{inv_id})")

def show_sbts_for_voucher(v_id):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        SELECT t.id, t.safe_box_id, sb.name, t.ref_type, t.ref_id,
               t.invoice_id, t.direction, t.amount_cash
        FROM safe_box_transaction t
        JOIN safe_box sb ON sb.id=t.safe_box_id
        WHERE t.ref_id=? AND t.ref_type='voucher'
        ORDER BY t.id
    """, (v_id,))
    rows = cur.fetchall()
    con.close()
    if rows:
        print(f"    SBTs لسند #{v_id}:")
        for r in rows:
            print(f"      SBT#{r[0]}  خزينة {r[1]}({r[2][:20]})  "
                  f"ref={r[3]}/{r[4]}  inv={r[5]}  {r[6]}  {r[7]:,.2f}")
    else:
        print(f"    (لا SBTs بـ ref_type=voucher و ref_id={v_id})")

# ────────────────────────────────────────────────
def get_ids_for_invoice(inv_id, token):
    """نجلب JE IDs + voucher IDs المرتبطة بالفاتورة مباشرةً من DB"""
    con = sqlite3.connect(DB)
    cur = con.cursor()
    # Journal entries
    cur.execute("SELECT id, reference_type, is_posted, is_draft FROM journal_entry WHERE reference_type='invoice' AND reference_id=?", (inv_id,))
    jes_inv = cur.fetchall()
    # Vouchers
    cur.execute("SELECT id, voucher_type, status, amount_cash, journal_entry_id FROM voucher WHERE reference_type='invoice' AND reference_id=?", (inv_id,))
    vouchers = cur.fetchall()
    v_ids = [v[0] for v in vouchers]
    # Journal entries for vouchers
    cur.execute(f"SELECT id, reference_type, is_posted, is_draft FROM journal_entry WHERE reference_type='voucher' AND reference_id IN ({','.join('?'*len(v_ids)) if v_ids else 'NULL'})", v_ids if v_ids else [])
    jes_voucher = cur.fetchall()
    con.close()
    return jes_inv, vouchers, jes_voucher

# ────────────────────────────────────────────────
def first_customer(token):
    """API returns a plain list"""
    r = requests.get(f"{BASE}/customers?per_page=1", headers=hdr(token))
    d = r.json()
    lst = d if isinstance(d, list) else d.get("customers", d.get("items", []))
    return lst[0]["id"] if lst else 1

def first_item(token):
    """API returns a plain list"""
    r = requests.get(f"{BASE}/items?per_page=1", headers=hdr(token))
    d = r.json()
    lst = d if isinstance(d, list) else d.get("items", [])
    if lst:
        it = lst[0]
        return it["id"], float(it.get("weight") or 5.0), int(it.get("karat") or 21)
    return 1, 5.0, 21

def first_cash_payment_method(token):
    """API returns plain list; safe_box_id resolved from safe_boxes list"""
    r = requests.get(f"{BASE}/payment-methods", headers=hdr(token))
    d = r.json()
    pms = d if isinstance(d, list) else d.get("payment_methods", [])
    # Pick first active PM
    for pm in pms:
        if pm.get("is_active", True):
            return pm["id"], None  # safe_box resolved separately
    return 1, None

def first_cash_safe(token):
    """API returns plain list"""
    r = requests.get(f"{BASE}/safe-boxes", headers=hdr(token))
    d = r.json()
    sbs = d if isinstance(d, list) else d.get("safe_boxes", [])
    for sb in sbs:
        if sb.get("safe_box_type", sb.get("safe_type", "")) == "cash" and sb.get("id"):
            return sb["id"]
    return sbs[0]["id"] if sbs else 1

def first_expense_account(token):
    """Find an expense-type account from the chart of accounts (plain list)"""
    r = requests.get(f"{BASE}/accounts?per_page=200", headers=hdr(token))
    d = r.json()
    lst = d if isinstance(d, list) else d.get("accounts", [])
    for a in lst:
        if (a.get("type") or a.get("account_type") or "").lower() == "expense":
            return a["id"]
    # Fallback: look for any account with '5xxx' pattern
    for a in lst:
        an = str(a.get("account_number", ""))
        if an.startswith("5"):
            return a["id"]
    return None

# ════════════════════════════════════════════════
def main():
    token = login()
    assert token, "فشل تسجيل الدخول"
    print("✅ تسجيل الدخول ناجح (admin)")

    # ── اختيار بيانات الاختبار ──────────────────
    customer_id             = first_customer(token)
    item_id, weight, karat  = first_item(token)
    pm_id, _                = first_cash_payment_method(token)
    sb_id                   = first_cash_safe(token)

    # الحصول على سعر الذهب
    gp_r = requests.get(f"{BASE}/gold_price", headers=hdr(token))
    gold_price = gp_r.json().get("price_per_gram", 200.0)
    invoice_total = round(weight * gold_price * (karat / 24), 2)

    print(f"\n  العميل #{customer_id}  |  بند #{item_id} وزن={weight}g عيار={karat}")
    print(f"  طريقة الدفع #{pm_id}  |  خزينة #{sb_id}  |  سعر الذهب={gold_price:,.2f}")
    print(f"  قيمة الفاتورة المتوقعة ≈ {invoice_total:,.2f}")

    # ─── لقطة قبل ─────────────────────────────
    before = snapshot("قبل الفاتورة والسند", token)

    # ════ خطوة 1: إنشاء فاتورة بيع ═══════════
    print(f"\n{'─'*70}")
    print(f"  خطوة 1 — إنشاء فاتورة بيع")
    print(f"{'─'*70}")

    from datetime import datetime as _dt
    inv_payload = {
        "customer_id": customer_id,
        "invoice_type": "sell",
        "date": _dt.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "items": [{"item_id": item_id, "quantity": 1,
                   "weight": weight, "karat": karat,
                   "unit_price": invoice_total}],
        "payments": [{"payment_method_id": pm_id, "amount": invoice_total}],
        "safe_box_id": sb_id,
        "notes": "فاتورة اختبار تدفق"
    }
    r = requests.post(f"{BASE}/invoices", json=inv_payload, headers=hdr(token))
    print(f"  HTTP {r.status_code}")
    if r.status_code not in (200, 201):
        print(f"  ❌ فشل: {r.text[:300]}")
        return
    inv = r.json().get("invoice", r.json())
    inv_id = inv["id"]
    print(f"  ✅ فاتورة #{inv_id}  is_posted={inv.get('is_posted')}  "
          f"status={inv.get('status')}  total={inv.get('total_amount', invoice_total):,.2f}")

    # القيود والسندات المرتبطة
    jes_inv, vouchers, jes_voucher = get_ids_for_invoice(inv_id, token)

    print(f"\n  📒 قيود محاسبية للفاتورة #{inv_id}:")
    for je in jes_inv:
        posted_lbl = "مرحّل ✅" if je[2] else "غير مرحّل ⚠️"
        print(f"    JE #{je[0]}  ref={je[1]}  {posted_lbl}")
        show_je_lines(je[0])

    print(f"\n  🧾 سندات مرتبطة بالفاتورة #{inv_id}:")
    if vouchers:
        for v in vouchers:
            print(f"    سند #{v[0]}  نوع={v[1]}  حالة={v[2]}  مبلغ={v[3]:,.2f}  JE={v[4]}")
        print(f"\n  📒 قيود محاسبية للسندات:")
        for je in jes_voucher:
            posted_lbl = "مرحّل ✅" if je[2] else "غير مرحّل ⚠️"
            print(f"    JE #{je[0]}  ref={je[1]}  {posted_lbl}")
            show_je_lines(je[0])
    else:
        print("    (لا سندات آلية)")

    print(f"\n  🏦 حركات الخزينة (SBT) للفاتورة #{inv_id}:")
    show_sbts_for_invoice(inv_id)

    after_invoice = snapshot("بعد الفاتورة (قبل السند اليدوي)", token)
    delta(before, after_invoice, "التغيير بعد الفاتورة")

    # ════ خطوة 2: إنشاء سند صرف يدوي ══════════
    print(f"\n{'─'*70}")
    print(f"  خطوة 2 — إنشاء سند صرف يدوي (خزينة #{sb_id})")
    print(f"{'─'*70}")

    voucher_amount = 500.0

    # نجلب حسابات المصروفات
    expense_acct = first_expense_account(token)

    # حساب الخزينة من DB
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("SELECT account_id FROM safe_box WHERE id=?", (sb_id,))
    safe_account_id = cur.fetchone()[0]
    con.close()

    if not expense_acct:
        print("  ⚠️  لم يوجد حساب مصروفات — سيتخطى هذه الخطوة")
    else:
        from datetime import datetime as _dt2
        voucher_payload = {
            "voucher_type": "payment",
            "date": _dt2.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "description": "سند صرف اختبار تدفق",
            "notes": "مراقبة الأثر على الخزائن",
            "account_lines": [
                {
                    "account_id": expense_acct,
                    "line_type": "debit",
                    "amount_type": "cash",
                    "amount": voucher_amount,
                    "description": "مصروف اختبار"
                },
                {
                    "account_id": safe_account_id,
                    "line_type": "credit",
                    "amount_type": "cash",
                    "amount": voucher_amount,
                    "description": "صرف من الخزينة"
                }
            ]
        }
        rv = requests.post(f"{BASE}/vouchers", json=voucher_payload, headers=hdr(token))
        print(f"  HTTP {rv.status_code}")
        if rv.status_code not in (200, 201):
            print(f"  ❌ فشل السند: {rv.text[:300]}")
        else:
            v_data = rv.json().get("voucher", rv.json())
            v_id   = v_data["id"]
            print(f"  ✅ سند صرف #{v_id}  حالة={v_data.get('status')}  "
                  f"مبلغ={voucher_amount:,.2f}")

            # اعتماد السند ────────────────────────────────
            print(f"\n  خطوة 2b — اعتماد السند #{v_id}")
            ra = requests.post(f"{BASE}/vouchers/{v_id}/approve",
                               json={}, headers=hdr(token))
            print(f"  HTTP {ra.status_code}  → {ra.json().get('message','') or ra.json().get('status','')}")

            # القيد المرتبط بالسند
            con = sqlite3.connect(DB)
            cur = con.cursor()
            cur.execute("SELECT id, is_posted, is_draft FROM journal_entry WHERE reference_type='voucher' AND reference_id=?", (v_id,))
            je_rows = cur.fetchall()
            con.close()

            print(f"\n  📒 قيود محاسبية للسند #{v_id}:")
            for je in je_rows:
                posted_lbl = "مرحّل ✅" if je[1] else "غير مرحّل ⚠️"
                print(f"    JE #{je[0]}  {posted_lbl}")
                show_je_lines(je[0])

            print(f"\n  🏦 حركات الخزينة (SBT) للسند #{v_id}:")
            show_sbts_for_voucher(v_id)

    after_payment_voucher = snapshot("بعد سند الصرف المستقل", token)
    delta(after_invoice, after_payment_voucher, "تأثير سند الصرف")

    # ════ خطوة 3: سند قبض مستقل ════════════════
    print(f"\n{'─'*70}")
    print(f"  خطوة 3 — سند قبض مستقل (خزينة #{sb_id})")
    print(f"{'─'*70}")

    receipt_amount = 750.0
    # نستخدم حساب العملاء كطرف مقابل
    con2 = sqlite3.connect(DB)
    cur2 = con2.cursor()
    cur2.execute("SELECT account_id FROM customer LIMIT 1")
    row2 = cur2.fetchone()
    customer_acct = row2[0] if row2 else None
    con2.close()

    if not customer_acct:
        print("  ⚠️  لم يوجد حساب عميل — سيتخطى")
    else:
        from datetime import datetime as _dt3
        receipt_payload = {
            "voucher_type": "receipt",
            "date": _dt3.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "description": "سند قبض مستقل اختبار",
            "account_lines": [
                {"account_id": safe_account_id, "line_type": "debit",
                 "amount_type": "cash", "amount": receipt_amount},
                {"account_id": customer_acct, "line_type": "credit",
                 "amount_type": "cash", "amount": receipt_amount},
            ]
        }
        rr = requests.post(f"{BASE}/vouchers", json=receipt_payload, headers=hdr(token))
        print(f"  HTTP {rr.status_code}")
        if rr.status_code not in (200, 201):
            print(f"  ❌ فشل: {rr.text[:200]}")
        else:
            vr = rr.json().get("voucher", rr.json())
            vr_id = vr["id"]
            ra2 = requests.post(f"{BASE}/vouchers/{vr_id}/approve", json={}, headers=hdr(token))
            print(f"  ✅ سند قبض #{vr_id}  اعتماد HTTP {ra2.status_code}")
            con3 = sqlite3.connect(DB)
            cur3 = con3.cursor()
            cur3.execute("SELECT id, is_posted FROM journal_entry WHERE reference_type='voucher' AND reference_id=?", (vr_id,))
            je3 = cur3.fetchone()
            con3.close()
            if je3:
                show_je_lines(je3[0])
            show_sbts_for_voucher(vr_id)

    after_receipt = snapshot("بعد سند القبض المستقل", token)
    delta(after_payment_voucher, after_receipt, "تأثير سند القبض المستقل")

    # ════ خطوة 4: سند تسوية مستقل ══════════════
    print(f"\n{'─'*70}")
    print(f"  خطوة 4 — سند تسوية (adjustment) مستقل")
    print(f"{'─'*70}")

    adj_amount = 200.0
    if not expense_acct:
        print("  ⚠️  لم يوجد حساب مصروفات — سيتخطى")
    else:
        from datetime import datetime as _dt4
        adj_payload = {
            "voucher_type": "adjustment",
            "date": _dt4.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "description": "سند تسوية اختبار",
            "account_lines": [
                {"account_id": expense_acct, "line_type": "debit",
                 "amount_type": "cash", "amount": adj_amount},
                {"account_id": safe_account_id, "line_type": "credit",
                 "amount_type": "cash", "amount": adj_amount},
            ]
        }
        radj = requests.post(f"{BASE}/vouchers", json=adj_payload, headers=hdr(token))
        print(f"  HTTP {radj.status_code}")
        if radj.status_code not in (200, 201):
            print(f"  ❌ فشل: {radj.text[:200]}")
        else:
            vadj = radj.json().get("voucher", radj.json())
            vadj_id = vadj["id"]
            ra3 = requests.post(f"{BASE}/vouchers/{vadj_id}/approve", json={}, headers=hdr(token))
            print(f"  ✅ سند تسوية #{vadj_id}  اعتماد HTTP {ra3.status_code}")
            con4 = sqlite3.connect(DB)
            cur4 = con4.cursor()
            cur4.execute("SELECT id, is_posted FROM journal_entry WHERE reference_type='voucher' AND reference_id=?", (vadj_id,))
            je4 = cur4.fetchone()
            con4.close()
            if je4:
                show_je_lines(je4[0])
            show_sbts_for_voucher(vadj_id)

    # ─── لقطة نهائية ──────────────────────────
    after_all = snapshot("بعد جميع العمليات", token)
    delta(before,        after_all, "الفرق الإجمالي (فاتورة + 3 سندات)")
    delta(after_invoice, after_all, "الفرق من السندات وحدها")

    print(f"\n{'='*70}")
    print("  ملخص المتوقع مقابل الفعلي — كل خزينة")
    print(f"{'='*70}")
    for sid, d in after_all.items():
        if abs(d["diff"]) < 0.01:
            print(f"  SB#{sid} ({d['name'][:25]}) → متوازن ✅")
        else:
            print(f"  SB#{sid} ({d['name'][:25]}) → فرق = {d['diff']:+,.2f} ⚠️")

if __name__ == "__main__":
    main()
