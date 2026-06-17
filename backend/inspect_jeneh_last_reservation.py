"""
inspect_jeneh_last_reservation.py
====================================
يبحث عن آخر حجز لـ "شركة الجنيه العربي" (مكتب أو مورد)، ويتحقق لماذا
لم يتم تسجيل الذهب: هل يوجد purchase_invoice_id؟ هل الفاتورة مُرحَّلة؟
هل أسطر القيد تحتوي على أوزان؟

قراءة فقط.

تشغيل:
    docker exec yasargold-backend python backend/inspect_jeneh_last_reservation.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import (
    db, Office, OfficeReservation, Invoice, InvoiceItem,
    JournalEntry, JournalEntryLine, Account, Supplier
)
from routes import convert_to_main_karat

KARATS = (18, 21, 22, 24)


def print_je_lines(je):
    lines = (
        JournalEntryLine.query
        .filter_by(journal_entry_id=je.id, is_deleted=False)
        .all()
    )
    if not lines:
        print("      (لا توجد أسطر)")
        return
    for l in lines:
        acc = Account.query.get(l.account_id)
        acc_name = f"{acc.account_number} {acc.name}" if acc else f"id={l.account_id}"
        cash_d = l.cash_debit or 0
        cash_c = l.cash_credit or 0
        weight_parts = []
        for k in KARATS:
            d = getattr(l, f'debit_{k}k') or 0
            c = getattr(l, f'credit_{k}k') or 0
            if d or c:
                weight_parts.append(f"{k}k: D={d:,.3f} C={c:,.3f}")
        print(f"      [{l.id}] {acc_name}")
        if cash_d or cash_c:
            print(f"            نقد: D={cash_d:,.2f} C={cash_c:,.2f}")
        if weight_parts:
            print(f"            وزن: {' | '.join(weight_parts)}")


def run():
    with app.app_context():
        # ابحث عن المكتب
        offices = Office.query.filter(Office.name.like('%الجنيه العربي%')).all()
        if not offices:
            # جرب البحث في الموردين
            suppliers = Supplier.query.filter(Supplier.name.like('%الجنيه العربي%')).all()
            if not suppliers:
                print("لم يتم العثور على مكتب أو مورد باسم 'الجنيه العربي'.")
                print("الحجوزات المتاحة (آخر 5):")
                for r in OfficeReservation.query.order_by(OfficeReservation.id.desc()).limit(5).all():
                    office = Office.query.get(r.office_id)
                    print(f"  [{r.id}] {r.reservation_code} - {office.name if office else '?'} | {r.karat}k {r.weight_grams}g | status={r.status} inv={r.purchase_invoice_id}")
                return
            for s in suppliers:
                print(f"\nمورد: [{s.id}] {s.name}")
                # البحث عن مكتب مرتبط
                office = Office.query.filter_by(supplier_id=s.id).first()
                if office:
                    offices.append(office)
                else:
                    print("  لا يوجد مكتب مرتبط بهذا المورد - لا توجد حجوزات.")

        for office in offices:
            print(f"\n=== مكتب [{office.id}] {office.name} ===")
            sup = Supplier.query.get(office.supplier_id) if office.supplier_id else None
            if sup:
                print(f"  مورد: [{sup.id}] {sup.name}")

            reservations = (
                OfficeReservation.query
                .filter_by(office_id=office.id)
                .order_by(OfficeReservation.id.desc())
                .limit(5)
                .all()
            )

            if not reservations:
                print("  لا توجد حجوزات لهذا المكتب.")
                continue

            print(f"  آخر {len(reservations)} حجوزات:")
            for r in reservations:
                print(f"\n  --- حجز [{r.id}] {r.reservation_code} ---")
                print(f"      التاريخ     : {r.reservation_date}")
                print(f"      العيار/الوزن: {r.karat}k = {r.weight_grams:,.3f}g (main={r.weight_main_karat:,.3f}g)")
                print(f"      الحالة      : {r.status}  دفع={r.payment_status}")
                print(f"      تنفيذات     : {r.executions_created}  مستهلك={r.weight_consumed_main_karat:,.3f}  متبقي={r.weight_remaining_main_karat:,.3f}")
                print(f"      purchase_invoice_id: {r.purchase_invoice_id}")

                if not r.purchase_invoice_id:
                    print("      ⚠️  لا توجد فاتورة شراء مرتبطة بهذا الحجز — هذا يفسر غياب تسجيل الذهب.")
                    continue

                inv = Invoice.query.get(r.purchase_invoice_id)
                if not inv:
                    print(f"      ⚠️  الفاتورة id={r.purchase_invoice_id} غير موجودة في قاعدة البيانات!")
                    continue

                print(f"\n      فاتورة [{inv.id}] {inv.invoice_number} | نوع={inv.invoice_type} | ذهب={inv.gold_type}")
                print(f"      is_posted={inv.is_posted}  is_deleted={getattr(inv,'is_deleted',None)}")
                print(f"      الإجمالي={inv.total_amount:,.2f}")

                items = InvoiceItem.query.filter_by(invoice_id=inv.id).all()
                print(f"      أصناف الفاتورة ({len(items)}):")
                for it in items:
                    print(f"        [{it.id}] عيار={it.karat}  وزن={it.weight:,.3f}g  سعر={it.price_per_unit:,.2f}")

                # قيود الفاتورة
                jes = (
                    JournalEntry.query
                    .filter_by(reference_type='invoice', reference_id=inv.id, is_deleted=False)
                    .order_by(JournalEntry.id.asc())
                    .all()
                )
                print(f"\n      قيود محاسبية ({len(jes)}):")
                for je in jes:
                    print(f"        قيد [{je.id}] {je.date} is_posted={je.is_posted} is_draft={getattr(je,'is_draft',None)}")
                    print_je_lines(je)

                if not jes:
                    print("      ⚠️  لا توجد قيود محاسبية مرتبطة بهذه الفاتورة!")

                if not inv.is_posted:
                    print("      ⚠️  الفاتورة غير مُرحَّلة (is_posted=False) — لن تُحتسب في الأرصدة.")


if __name__ == '__main__':
    run()
