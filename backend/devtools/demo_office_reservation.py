#!/usr/bin/env python3
"""Demo: إنشاء حجز تسكير (مكتب) وتنفيذه ثم عرض المتوسط الجديد لتكلفة الكسر.

المراحل:
  1. عرض متوسط تكلفة الكسر قبل التنفيذ
  2. إنشاء الحجز (POST /api/office-reservations)
  3. تنفيذ/تسوية الحجز (POST /api/office-reservations/{id}/settle)
  4. طباعة:
       - تفاصيل الحجز والفاتورة المُنشأة
       - القيد اليومي (JournalEntry) وجميع سطوره
       - حركات الخزائن (SafeBoxTransaction)
  5. إعادة حساب متوسط الكسر (POST /api/gold-costing/scrap/recompute)
  6. عرض المتوسط الجديد مقارنةً بالسابق

الاستخدام:
  cd backend
  source venv/bin/activate
  python devtools/demo_office_reservation.py              # dry-run (rollback)
  python devtools/demo_office_reservation.py --apply      # حفظ فعلي
  python devtools/demo_office_reservation.py --apply --weight 20 --karat 21 --price 185
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
from models import db, Invoice, JournalEntry, JournalEntryLine, SafeBoxTransaction, Account, OfficeReservation, Office
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
    width = 64
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

    KARATS = [18, 21, 22, 24]
    # Determine which karat columns actually have data
    active_karats = []
    for k in KARATS:
        if any((getattr(l, f'debit_{k}k') or 0) + (getattr(l, f'credit_{k}k') or 0) for l in lines):
            active_karats.append(k)

    karat_cols = "".join(f" {'مدين '+str(k)+'k':>10} {'دائن '+str(k)+'k':>10}" for k in active_karats)
    hdr = f"  {'#':>3}  {'الحساب':<38} {'مدين نقدي':>12} {'دائن نقدي':>12}{karat_cols}"
    print(hdr)
    print("  " + "-" * max(len(hdr) - 2, 60))

    total_cash_d = total_cash_c = 0.0
    karat_totals = {k: [0.0, 0.0] for k in active_karats}
    for i, line in enumerate(lines, 1):
        label = _acct_label(line.account_id)[:37]
        cd = line.cash_debit or 0.0
        cc = line.cash_credit or 0.0
        total_cash_d += cd
        total_cash_c += cc
        karat_str = ""
        for k in active_karats:
            wd = getattr(line, f'debit_{k}k') or 0.0
            wc = getattr(line, f'credit_{k}k') or 0.0
            karat_totals[k][0] += wd
            karat_totals[k][1] += wc
            karat_str += f" {wd:>10.4f} {wc:>10.4f}"
        print(f"  {i:>3}  {label:<38} {cd:>12.3f} {cc:>12.3f}{karat_str}")

    print("  " + "-" * max(len(hdr) - 2, 60))
    karat_total_str = "".join(f" {karat_totals[k][0]:>10.4f} {karat_totals[k][1]:>10.4f}" for k in active_karats)
    print(f"  {'الإجمالي':<42} {total_cash_d:>12.3f} {total_cash_c:>12.3f}{karat_total_str}")

    cash_diff = round(total_cash_d - total_cash_c, 4)
    cash_ok = "✅" if abs(cash_diff) < 0.01 else f"⚠️  فرق={cash_diff}"
    print(f"\n  التوازن النقدي  : {cash_ok}")
    for k in active_karats:
        diff = round(karat_totals[k][0] - karat_totals[k][1], 4)
        ok = "✅" if abs(diff) < 0.001 else f"⚠️  فرق={diff}"
        print(f"  التوازن {k}k     : {ok}")


def _print_sbt(invoice_id: int):
    rows = (
        SafeBoxTransaction.query
        .filter_by(invoice_id=invoice_id)
        .order_by(SafeBoxTransaction.id)
        .all()
    )
    if not rows:
        print("  (لا توجد حركات خزينة)")
        return
    for r in rows:
        direction_label = "دخول ↓" if (r.direction or "in") == "in" else "خروج ↑"
        weight_info = ""
        for k in ("18", "21", "22", "24"):
            w = getattr(r, f"weight_{k}k", None) or 0.0
            if w:
                weight_info += f" {k}k={w:.4f}g"
        print(
            f"  [{r.id}] خزينة={r.safe_box_id} | {direction_label} {abs(r.amount_cash or 0):.2f} ريال"
            f" | نوع={r.ref_type}{weight_info}"
        )


def _print_scrap_snapshot(label: str, snap):
    print(f"  {label}")
    print(f"    متوسط الإجمالي (avg_total)      : {snap.avg_total:.4f} ريال/جرام")
    print(f"    متوسط الذهب   (avg_gold)        : {snap.avg_gold:.4f} ريال/جرام")
    print(f"    متوسط المصنعية (avg_manufacturing): {snap.avg_manufacturing:.4f} ريال/جرام")


# ── core ──────────────────────────────────────────────────────────────────────

def run(
    office_id: int,
    weight_grams: float,
    karat: int,
    price_per_gram: float,
    execution_price_per_gram: float,
    cash_safe_box_id: int,
    dry_run: bool = True,
):
    """إنشاء حجز تسكير، تنفيذه، وطباعة جميع المخرجات."""

    with app.app_context():

        # ── معلومات المكتب قبل الحجز ──────────────────────────────────────
        office = Office.query.get(office_id)
        if not office:
            print(f"❌ المكتب id={office_id} غير موجود")
            return

        # ── متوسط الكسر قبل التنفيذ ──────────────────────────────────────
        scrap_before = ScrapCostingService.snapshot()

        # ── طباعة المدخلات ────────────────────────────────────────────────
        _print_section("بيانات الحجز المُدخلة")
        total_amount = round(weight_grams * price_per_gram, 2)
        print(f"  المكتب              : {office.name} (id={office.id})")
        print(f"  الوزن               : {weight_grams} جرام  (عيار {karat})")
        print(f"  سعر الحجز/جرام      : {price_per_gram} ريال")
        print(f"  سعر التنفيذ/جرام    : {execution_price_per_gram} ريال")
        print(f"  الإجمالي المحتسب    : {total_amount} ريال")
        print(f"  دفعة مقدمة          : 0 ريال (بدون دفعة عند الحجز)")
        print(f"  الوضع               : {'محاكاة (dry-run)' if dry_run else '⚡ حفظ فعلي'}")

        client = app.test_client()

        # ══════════════════════════════════════════════════════════════════
        # المرحلة 1: إنشاء الحجز
        # ══════════════════════════════════════════════════════════════════
        create_payload = {
            "office_id": office_id,
            "weight": weight_grams,
            "karat": karat,
            "price_per_gram": price_per_gram,
            "execution_price_per_gram": execution_price_per_gram,
            "paid_amount": 0,           # بدون دفعة مقدمة — يُبسّط الـ dry-run
            "reservation_date": date.today().isoformat(),
        }

        create_resp = client.post(
            "/api/office-reservations",
            data=json.dumps(create_payload),
            content_type="application/json",
        )
        create_data = create_resp.get_json()

        _print_section("استجابة إنشاء الحجز")
        print(f"  HTTP Status: {create_resp.status_code}")

        if create_resp.status_code not in (200, 201):
            print(f"  ❌ خطأ: {json.dumps(create_data, ensure_ascii=False, indent=4)}")
            return

        reservation_id = create_data.get("id")
        res = OfficeReservation.query.get(reservation_id)
        print(f"  ✅ تم الحجز  id={reservation_id}  كود={res.reservation_code}")
        print(f"  الحالة      : {res.status}")
        print(f"  الوزن (عيار رئيسي): {res.weight_main_karat:.4f} جرام")

        # ══════════════════════════════════════════════════════════════════
        # المرحلة 2: تنفيذ الحجز (التسوية)
        # ══════════════════════════════════════════════════════════════════
        settle_payload = {
            "execution_price_per_gram": execution_price_per_gram,
            "settlement_date": date.today().isoformat(),
            "created_by": "demo_script",
        }

        settle_resp = client.post(
            f"/api/office-reservations/{reservation_id}/settle",
            data=json.dumps(settle_payload),
            content_type="application/json",
        )
        settle_data = settle_resp.get_json()

        _print_section("استجابة تنفيذ الحجز (التسوية)")
        print(f"  HTTP Status: {settle_resp.status_code}")

        if settle_resp.status_code not in (200, 201):
            print(f"  ❌ خطأ: {json.dumps(settle_data, ensure_ascii=False, indent=4)}")
            # Cleanup reservation (no invoice yet)
            if dry_run:
                try:
                    res = OfficeReservation.query.get(reservation_id)
                    db.session.delete(res)
                    db.session.commit()
                    print(f"\n  🔄 Dry-run: تم حذف الحجز {reservation_id}")
                except Exception as e:
                    print(f"\n  ⚠️ فشل حذف الحجز: {e}")
            return

        invoice_id = settle_data.get("purchase_invoice_id")
        je_info = settle_data.get("journal_entry", {})
        wc_info = settle_data.get("weight_consumption", {})

        print(f"  ✅ تم التنفيذ")
        print(f"  فاتورة الشراء id  : {invoice_id}")
        print(f"  القيد اليومي id   : {je_info.get('id')}  رقم={je_info.get('entry_number')}")
        if wc_info:
            print(f"  استهلاك وزن تسكير: {wc_info.get('weight_consumed', 0):.4f} جرام "
                  f"({wc_info.get('executions_created', 0)} تنفيذ)")
        if settle_data.get("weight_closing_warning"):
            warn = settle_data["weight_closing_warning"]
            print(f"\n  ⚠️  {warn.get('message')}")
            print(f"     المطلوب={warn.get('weight_requested'):.4f}  المستهلك={warn.get('weight_consumed'):.4f}")

        # ── تفاصيل الفاتورة ───────────────────────────────────────────────
        inv = Invoice.query.get(invoice_id)
        if inv:
            _print_section("تفاصيل فاتورة الشراء (شراء كسر)")
            print(f"  id             : {inv.id}")
            print(f"  نوع الفاتورة   : {inv.invoice_type}  |  gold_type={inv.gold_type}")
            print(f"  المورد         : {inv.supplier_id}")
            print(f"  التاريخ        : {inv.date}")
            print(f"  الإجمالي       : {inv.total} ريال")
            print(f"  حالة الدفع     : {inv.status}")
            print(f"  الوزن الكلي    : {inv.total_weight:.4f} جرام (عيار رئيسي)")

        # ── القيد اليومي ──────────────────────────────────────────────────
        je = (
            JournalEntry.query
            .filter_by(reference_type="office_reservation", reference_id=reservation_id)
            .first()
        )
        if not je:
            print("\n  ⚠️ لم يُعثر على قيد يومي لهذا الحجز")
        else:
            _print_section(f"القيد اليومي  (JE #{je.id} — {je.entry_number})")
            print(f"  الوصف  : {je.description}")
            print(f"  التاريخ: {je.date}")
            print(f"  مرحّل  : {'نعم ✅' if je.is_posted else 'لا'}")
            print()
            _print_je_lines(je)

        # ── حركات الخزائن ─────────────────────────────────────────────────
        _print_section("حركات الخزائن (SafeBoxTransaction)")
        if invoice_id:
            _print_sbt(invoice_id)
        else:
            print("  (لا توجد فاتورة — لا حركات)")

        # ══════════════════════════════════════════════════════════════════
        # المرحلة 3: إعادة حساب متوسط تكلفة الكسر
        # ══════════════════════════════════════════════════════════════════
        recompute_resp = client.post("/api/gold-costing/scrap/recompute")
        recompute_data = recompute_resp.get_json()

        _print_section("إعادة حساب متوسط تكلفة الكسر")
        print(f"  HTTP Status: {recompute_resp.status_code}")
        if recompute_resp.status_code in (200, 201):
            print("  ✅ تم إعادة الحساب")
        else:
            print(f"  ⚠️  {recompute_data}")

        scrap_after = ScrapCostingService.snapshot()

        _print_section("ملخص متوسط تكلفة الكسر")
        _print_scrap_snapshot("قبل التنفيذ ←", scrap_before)
        print()
        _print_scrap_snapshot("بعد التنفيذ  →", scrap_after)

        delta = scrap_after.avg_total - scrap_before.avg_total
        delta_str = f"{delta:+.4f} ريال/جرام"
        print(f"\n  التغيّر في المتوسط: {delta_str}")

        # ══════════════════════════════════════════════════════════════════
        # Dry-run cleanup
        # ══════════════════════════════════════════════════════════════════
        if dry_run:
            print()
            print("  🔄 Dry-run: جارٍ التراجع عن التغييرات...")

            # 1. حذف فاتورة الشراء
            if invoice_id:
                del_resp = client.delete(f"/api/invoices/{invoice_id}")
                if del_resp.status_code in (200, 204):
                    print(f"     ✅ تم حذف فاتورة الشراء id={invoice_id}")
                else:
                    print(f"     ⚠️  لم يُمكن حذف الفاتورة (status={del_resp.status_code})")

            # 2. إعادة ضبط الحجز ثم حذفه مباشرةً من قاعدة البيانات
            try:
                res_obj = OfficeReservation.query.get(reservation_id)
                if res_obj:
                    db.session.delete(res_obj)
                    db.session.commit()
                    print(f"     ✅ تم حذف الحجز id={reservation_id}")
            except Exception as exc:
                db.session.rollback()
                print(f"     ⚠️  لم يُمكن حذف الحجز: {exc}")

            # 3. إعادة حساب المتوسط بعد الحذف (لاستعادة الحالة الأصلية)
            client.post("/api/gold-costing/scrap/recompute")
            print("     ✅ تم إعادة حساب المتوسط بعد الحذف")
            print()
            print("  ─── لم يُحفظ أي شيء في قاعدة البيانات ───")
        else:
            print("\n  💾 تم الحفظ الكامل في قاعدة البيانات")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="إنشاء حجز تسكير (مكتب) وعرض القيود المحاسبية ومتوسط الكسر الجديد"
    )
    parser.add_argument("--apply", action="store_true",
                        help="حفظ فعلي في قاعدة البيانات (افتراضي: dry-run)")
    parser.add_argument("--office-id", type=int, default=5,
                        help="معرّف المكتب (افتراضي: 5 = الراقي)")
    parser.add_argument("--weight", type=float, default=10.0,
                        help="وزن الذهب بالجرام (افتراضي: 10)")
    parser.add_argument("--karat", type=int, default=21,
                        help="العيار (افتراضي: 21)")
    parser.add_argument("--price", type=float, default=180.0,
                        help="سعر الحجز بالريال/جرام (افتراضي: 180)")
    parser.add_argument("--exec-price", type=float, default=0.0,
                        help="سعر التنفيذ بالريال/جرام (افتراضي: يساوي --price)")
    parser.add_argument("--cash-safe-box-id", type=int, default=1,
                        help="معرّف خزينة النقد (مستخدم فقط إذا كان paid_amount > 0)")
    args = parser.parse_args()

    execution_price = args.exec_price if args.exec_price > 0 else args.price

    run(
        office_id=args.office_id,
        weight_grams=args.weight,
        karat=args.karat,
        price_per_gram=args.price,
        execution_price_per_gram=execution_price,
        cash_safe_box_id=args.cash_safe_box_id,
        dry_run=not args.apply,
    )


if __name__ == "__main__":
    main()
