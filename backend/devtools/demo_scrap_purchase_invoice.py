#!/usr/bin/env python3
"""Demo: إنشاء فاتورة شراء كسر من عميل وعرض القيود المحاسبية الناتجة.

يُنشئ هذا السكربت فاتورة "شراء من عميل" بالكامل عبر الـ API الداخلي
ثم يطبع:
  - تفاصيل الفاتورة المُنشأة
  - القيد اليومي (JournalEntry) وجميع السطور (JournalEntryLine)
  - حركات الخزائن (SafeBoxTransaction) المُنشأة
  - متوسط تكلفة الكسر قبل وبعد

الاستخدام:
  cd backend
  source venv/bin/activate
  python devtools/demo_scrap_purchase_invoice.py            # dry-run (rollback)
  python devtools/demo_scrap_purchase_invoice.py --apply    # حفظ فعلي
  python devtools/demo_scrap_purchase_invoice.py --apply --weight 15 --karat 18 --price 170
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app
from models import db, Invoice, JournalEntry, JournalEntryLine, SafeBoxTransaction, Account
from gold_costing_service import ScrapCostingService


# ── helpers ──────────────────────────────────────────────────────────────────

def _acct_label(account_id) -> str:
    """Return 'number — name' for an account ID."""
    if not account_id:
        return "—"
    acc = Account.query.get(int(account_id))
    if not acc:
        return f"id={account_id}"
    return f"{acc.account_number} — {acc.name}"


def _print_section(title: str):
    width = 60
    print()
    print("═" * width)
    print(f"  {title}")
    print("═" * width)


def _print_je_lines(je: JournalEntry):
    """طباعة جميع سطور القيد اليومي بشكل منظم."""
    lines = (
        JournalEntryLine.query
        .filter_by(journal_entry_id=je.id)
        .order_by(JournalEntryLine.id)
        .all()
    )

    hdr = f"  {'#':>3}  {'الحساب':<38} {'مدين نقدي':>12} {'دائن نقدي':>12}  {'وزن مدين':>11} {'وزن دائن':>11} {'وزن تحليلي (21)':>16}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    total_cash_d = total_cash_c = 0.0
    total_wd = total_wc = 0.0
    for i, line in enumerate(lines, 1):
        label = _acct_label(line.account_id)[:37]
        cd = line.cash_debit or 0.0
        cc = line.cash_credit or 0.0
        wd = line.debit_weight or 0.0
        wc = line.credit_weight or 0.0
        wa = line.analytic_weight_main or 0.0
        total_cash_d += cd
        total_cash_c += cc
        total_wd += wd
        total_wc += wc
        print(f"  {i:>3}  {label:<38} {cd:>12.3f} {cc:>12.3f}  {wd:>11.4f} {wc:>11.4f} {wa:>16.4f}")

    print("  " + "-" * (len(hdr) - 2))
    print(f"  {'الإجمالي':<42} {total_cash_d:>12.3f} {total_cash_c:>12.3f}  {total_wd:>11.4f} {total_wc:>11.4f}")

    cash_diff = round(total_cash_d - total_cash_c, 4)
    weight_diff = round(total_wd - total_wc, 4)
    cash_ok = "✅" if abs(cash_diff) < 0.01 else f"⚠️ فرق={cash_diff}"
    weight_ok = "✅" if abs(weight_diff) < 0.001 else f"⚠️ فرق={weight_diff}"
    print(f"\n  التوازن النقدي : {cash_ok}")
    print(f"  التوازن الوزني: {weight_ok}")


def _print_sbt(invoice_id: int):
    rows = SafeBoxTransaction.query.filter_by(invoice_id=invoice_id).order_by(SafeBoxTransaction.id).all()
    if not rows:
        print("  (لا توجد حركات خزينة)")
        return
    for r in rows:
        direction_label = "دخول ↓" if (r.direction or 'in') == 'in' else "خروج ↑"
        weight_info = ""
        for k in ['18', '21', '22', '24']:
            w = getattr(r, f'weight_{k}k', None) or 0.0
            if w:
                weight_info += f" {k}k={w:.4f}g"
        print(
            f"  [{r.id}] خزينة={r.safe_box_id} | {direction_label} {abs(r.amount_cash or 0):.2f} ريال"
            f" | نوع={r.ref_type}{weight_info}"
        )


# ── core ──────────────────────────────────────────────────────────────────────

def run(
    weight_grams: float,
    karat: int,
    price_per_gram: float,
    customer_id: int,
    employee_id: int,
    cash_safe_box_id: int,
    payment_method_id: int,
    dry_run: bool = True,
):
    """إنشاء فاتورة شراء كسر وطباعة جميع المخرجات."""

    with app.app_context():
        # ── متوسط الكسر قبل الفاتورة ─────────────────────────────────────
        scrap_before = ScrapCostingService.snapshot()

        _print_section("بيانات الفاتورة المُدخلة")
        total_cash = round(weight_grams * price_per_gram, 2)
        print(f"  نوع الفاتورة   : شراء من عميل (كسر)")
        print(f"  العميل         : id={customer_id}")
        print(f"  الموظف الحامل  : id={employee_id}")
        print(f"  الوزن          : {weight_grams} جرام   (عيار {karat})")
        print(f"  السعر/جرام     : {price_per_gram} ريال")
        print(f"  الإجمالي       : {total_cash} ريال")
        print(f"  خزينة النقد    : id={cash_safe_box_id}")
        print(f"  وسيلة الدفع    : id={payment_method_id}")
        print(f"  الوضع          : {'محاكاة (rollback)' if dry_run else '⚡ حفظ فعلي'}")

        # ── payload للـ API ───────────────────────────────────────────────
        payload = {
            "invoice_type": "شراء من عميل",
            "gold_type": "scrap",
            "date": date.today().isoformat(),
            "customer_id": customer_id,
            "scrap_holder_employee_id": employee_id,
            "payment_method_id": payment_method_id,
            "safe_box_id": cash_safe_box_id,
            "total": total_cash,
            # karat_lines is the single weight source for scrap invoices (no items weight).
            "items": [
                {
                    "name": f"ذهب كسر عيار {karat}",
                    "karat": karat,
                    "price": price_per_gram,
                    "net": total_cash,
                    "quantity": 1,
                    # intentionally no 'weight' here — weight comes from karat_lines
                }
            ],
            "karat_lines": [
                {
                    "karat": karat,
                    "weight_grams": weight_grams,
                    "gold_value_cash": total_cash,
                    "manufacturing_wage_cash": 0.0,
                }
            ],
        }

        client = app.test_client()

        # Call the API — it commits internally. We collect data, then delete if dry-run.
        response = client.post(
            "/api/invoices",
            data=json.dumps(payload),
            content_type="application/json",
        )

        resp_data = response.get_json()

        _print_section("استجابة الـ API")
        print(f"  HTTP Status: {response.status_code}")

        if response.status_code not in (200, 201):
            print(f"  ❌ خطأ: {json.dumps(resp_data, ensure_ascii=False, indent=4)}")
            return

        invoice_id = resp_data.get("id") or (resp_data.get("invoice") or {}).get("id")
        print(f"  ✅ تم إنشاء الفاتورة  id={invoice_id}")

        # ── تفاصيل الفاتورة ───────────────────────────────────────────────
        inv = Invoice.query.get(invoice_id)
        _print_section("تفاصيل الفاتورة")
        print(f"  id            : {inv.id}")
        print(f"  نوع           : {inv.invoice_type}")
        print(f"  التاريخ       : {inv.date}")
        print(f"  الإجمالي      : {inv.total} ريال")
        print(f"  حالة الترحيل  : {'مرحّلة' if getattr(inv,'is_posted',False) else 'غير مرحّلة'}")

        # ── القيد اليومي ──────────────────────────────────────────────────
        je = (
            JournalEntry.query
            .filter_by(reference_type='invoice', reference_id=invoice_id)
            .first()
        )
        if not je:
            print("\n  ⚠️ لم يُنشأ قيد يومي لهذه الفاتورة")
        else:
            _print_section(f"القيد اليومي  (JE #{je.id})")
            print(f"  الوصف  : {je.description}")
            print(f"  التاريخ: {je.date}")
            print(f"  مرحّل  : {'نعم' if je.is_posted else 'لا'}")
            print()
            _print_je_lines(je)

        # ── حركات الخزائن ─────────────────────────────────────────────────
        _print_section("حركات الخزائن (SafeBoxTransaction)")
        _print_sbt(invoice_id)

        # ── متوسط الكسر بعد الفاتورة ─────────────────────────────────────
        _print_section("متوسط تكلفة الكسر (ScrapCostingService)")
        scrap_after = ScrapCostingService.snapshot()
        print(f"  قبل  → متوسط الإجمالي: {scrap_before.avg_total:.4f} ريال/جرام")
        print(f"  بعد  → متوسط الإجمالي: {scrap_after.avg_total:.4f} ريال/جرام")
        print(f"         متوسط الذهب   : {scrap_after.avg_gold:.4f} ريال/جرام")
        print(f"  ملاحظة: المتوسط يُحسب فعلياً عند تشغيل POST /api/gold-costing/scrap/recompute")

        # ── إتمام أو إلغاء ────────────────────────────────────────────────
        if dry_run:
            # حذف الفاتورة المُنشأة للإبقاء على DB نظيفة
            del_resp = client.delete(f"/api/invoices/{invoice_id}")
            if del_resp.status_code in (200, 204):
                print("\n  🔄 Dry-run: تم حذف الفاتورة — لم يُحفظ شيء في قاعدة البيانات")
            else:
                print(f"\n  ⚠️ Dry-run: لم يُمكن حذف الفاتورة تلقائياً (status={del_resp.status_code})")
                print(f"     يمكنك حذفها يدوياً: DELETE /api/invoices/{invoice_id}")
        else:
            print("\n  💾 تم الحفظ في قاعدة البيانات")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="إنشاء فاتورة شراء كسر من عميل وطباعة القيود المحاسبية"
    )
    parser.add_argument("--apply", action="store_true", help="حفظ فعلي (افتراضي: dry-run)")
    parser.add_argument("--weight", type=float, default=10.0, help="الوزن بالجرام (افتراضي: 10)")
    parser.add_argument("--karat", type=int, default=21, help="العيار (افتراضي: 21)")
    parser.add_argument("--price", type=float, default=180.0, help="السعر بالريال لكل جرام (افتراضي: 180)")
    parser.add_argument("--customer-id", type=int, default=1, help="معرّف العميل (افتراضي: 1)")
    parser.add_argument("--employee-id", type=int, default=2, help="معرّف الموظف الحامل (افتراضي: 2 = صامد)")
    parser.add_argument("--cash-safe-box-id", type=int, default=1, help="معرّف خزينة النقد (افتراضي: 1)")
    parser.add_argument("--payment-method-id", type=int, default=1, help="معرّف وسيلة الدفع (افتراضي: 1 = نقداً)")
    args = parser.parse_args()

    run(
        weight_grams=args.weight,
        karat=args.karat,
        price_per_gram=args.price,
        customer_id=args.customer_id,
        employee_id=args.employee_id,
        cash_safe_box_id=args.cash_safe_box_id,
        payment_method_id=args.payment_method_id,
        dry_run=not args.apply,
    )


if __name__ == "__main__":
    main()
