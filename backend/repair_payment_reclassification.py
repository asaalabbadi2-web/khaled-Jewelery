"""
repair_payment_reclassification.py
====================================
إصلاح تاريخي محافظ لحالة ناتجة عن غياب إعداد الخزينة عند تنفيذ
correct_invoice_payment_method (split). يُستخدم حصراً لعمليات إعادة
التصنيف التي اكتُشف بعدها أن النظام أنجز طبقة الـSBT جزئياً (عدّل SBT
وسيلة المصدر) لكنه لم يُنشئ:
  1. Cash SBT لوسيلة الهدف (غياب default_safe_box_id وقت التنفيذ).
  2. قيد GL لإعادة التصنيف (Dr هدف / Cr مصدر).

هذا ليس أداة محاسبية عامة. كل عملية يُحكم عليها بالحواجز أدناه قبل
أي كتابة، والتنفيذ ذري (Transaction واحدة) مع تحقق كامل قبل Commit.

المبدأ: Single Source of Truth + Single Writer + Atomic Transaction
         (انظر PAYMENT_LIFECYCLE_ARCHITECTURE.md)

الوضع الافتراضي: DRY RUN — يطبع فقط ولا يكتب شيئاً.
للتنفيذ الفعلي: أضف --apply.

مثال:
    python repair_payment_reclassification.py \\
        --invoice-payment 2325 --amount 8850 --from-payment-method 10
    python repair_payment_reclassification.py \\
        --invoice-payment 2325 --amount 8850 --from-payment-method 10 --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, InvoicePayment, PaymentMethod, SafeBox, Account
from models import SafeBoxTransaction, JournalEntry, JournalEntryLine, AuditLog
from routes import _generate_journal_entry_number

EPSILON = 0.005


# ── Helpers ───────────────────────────────────────────────────────────────────

def _label(obj, id_attr='id', name_attr='name') -> str:
    if obj is None:
        return '(?)'
    return f"#{getattr(obj, id_attr, '?')} {getattr(obj, name_attr, '')}"


def _gl_balance(account_id: int) -> float:
    """إجمالي مدين - دائن للحساب من جميع سطور القيود."""
    from sqlalchemy import func
    row = (
        db.session.query(
            func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0),
            func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0),
        )
        .filter(
            JournalEntryLine.account_id == account_id,
            JournalEntryLine.is_deleted == False,
        )
        .one()
    )
    return round(float(row[0]) - float(row[1]), 2)


def _has_cash_sbt(ip_id: int, to_safe_box_id: int) -> bool:
    return SafeBoxTransaction.query.filter_by(
        invoice_payment_id=ip_id,
        safe_box_id=to_safe_box_id,
        direction='in',
    ).count() > 0


def _has_repair_log(ip_id: int) -> bool:
    return AuditLog.query.filter_by(
        action='historical_reclassification_repair',
        entity_type='InvoicePayment',
        entity_id=ip_id,
    ).count() > 0


# ── Core logic ────────────────────────────────────────────────────────────────

def run(ip_id: int, amount: float, from_pm_id: int, apply: bool) -> int:
    with app.app_context():
        mode = 'APPLY' if apply else 'DRY RUN'
        sep = '=' * 65
        print(sep)
        print(f"repair_payment_reclassification — {mode}")
        print(sep)

        errors: list[str] = []

        # ── 1. تحقق من إعدادات النظام ──────────────────────────────────────
        print("\n[1] فحص الإعدادات:")

        ip = InvoicePayment.query.get(ip_id)
        if ip is None:
            errors.append(f"InvoicePayment #{ip_id} غير موجودة.")
        else:
            print(f"  ✓ IP #{ip_id}: amount={ip.amount}, invoice_id={ip.invoice_id}")

        pm_to = PaymentMethod.query.get(ip.payment_method_id) if ip else None
        if pm_to is None:
            errors.append("وسيلة الدفع الهدف (To) غير موجودة.")
        else:
            print(f"  ✓ وسيلة الهدف:  {_label(pm_to)}")

        if pm_to and not pm_to.default_safe_box_id:
            errors.append(f"وسيلة الدفع '{pm_to.name}' لا تملك خزينة مرتبطة. أضف default_safe_box_id أولاً.")

        sb_to = SafeBox.query.get(pm_to.default_safe_box_id) if pm_to and pm_to.default_safe_box_id else None
        if sb_to is None:
            errors.append("خزينة وسيلة الهدف غير موجودة.")
        else:
            print(f"  ✓ خزينة الهدف:  {_label(sb_to)}")

        if sb_to and not sb_to.account_id:
            errors.append(f"خزينة الهدف '{sb_to.name}' لا تملك حساباً محاسبياً مرتبطاً.")

        acc_to = Account.query.get(sb_to.account_id) if sb_to and sb_to.account_id else None
        if acc_to:
            print(f"  ✓ حساب الهدف:   {_label(acc_to)} (Dr في قيد التصحيح)")

        pm_from = PaymentMethod.query.get(from_pm_id)
        if pm_from is None:
            errors.append(f"وسيلة الدفع المصدر (From) #{from_pm_id} غير موجودة.")
        else:
            print(f"  ✓ وسيلة المصدر: {_label(pm_from)}")

        if pm_from and not pm_from.default_safe_box_id:
            errors.append(f"وسيلة الدفع المصدر '{pm_from.name}' لا تملك خزينة مرتبطة.")

        sb_from = SafeBox.query.get(pm_from.default_safe_box_id) if pm_from and pm_from.default_safe_box_id else None
        acc_from = Account.query.get(sb_from.account_id) if sb_from and sb_from.account_id else None
        if acc_from is None:
            errors.append("حساب وسيلة المصدر غير موجود أو لا يملك account_id.")
        else:
            print(f"  ✓ حساب المصدر:  {_label(acc_from)} (Cr في قيد التصحيح)")

        if errors:
            _print_errors(errors)
            return 1

        # ── 2. تحقق من الحالة قبل الكتابة ──────────────────────────────────
        print("\n[2] فحص حالة البيانات:")

        if abs(float(ip.amount) - amount) > EPSILON:
            errors.append(
                f"مبلغ IP #{ip_id} الفعلي ({ip.amount}) لا يطابق --amount ({amount}). "
                "تحقق من أن الـIP صحيح."
            )

        if ip.payment_method_id != pm_to.id:
            errors.append(
                f"IP #{ip_id} وسيلة دفعه الحالية ({ip.payment_method_id}) "
                f"لا تطابق وسيلة الهدف ({pm_to.id})."
            )

        if _has_cash_sbt(ip_id, sb_to.id):
            errors.append(
                f"يوجد بالفعل Cash SBT في خزينة {_label(sb_to)} "
                f"لـIP #{ip_id}. ربما نُفِّذ هذا الإصلاح مسبقاً."
            )

        if _has_repair_log(ip_id):
            errors.append(
                f"يوجد AuditLog action='historical_reclassification_repair' "
                f"لـIP #{ip_id}. تأكد من عدم التكرار."
            )

        bal_from_before = _gl_balance(acc_from.id)
        bal_to_before = _gl_balance(acc_to.id)
        print(f"  رصيد {_label(acc_from)} قبل:  {bal_from_before:,.2f}")
        print(f"  رصيد {_label(acc_to)}  قبل:  {bal_to_before:,.2f}")

        if bal_from_before < amount - EPSILON:
            errors.append(
                f"رصيد حساب المصدر {_label(acc_from)} ({bal_from_before:,.2f}) "
                f"أقل من المبلغ المطلوب ({amount:,.2f})."
            )

        if errors:
            _print_errors(errors)
            return 1

        # ── 3. عرض الخطة ────────────────────────────────────────────────────
        print("\n[3] الخطة (ما سيُنفَّذ):")
        print(f"  Cash SBT:  direction='in'  safe_box={_label(sb_to)}  amount={amount:,.2f}")
        print(f"  GL Dr:     {_label(acc_to)}   +{amount:,.2f}")
        print(f"  GL Cr:     {_label(acc_from)}  +{amount:,.2f}")
        print(f"  AuditLog:  action='historical_reclassification_repair'  ip={ip_id}")

        if not apply:
            print(f"\n{'='*65}")
            print("DRY RUN: لا تغييرات. أضف --apply للتنفيذ الفعلي.")
            return 0

        # ── 4. تنفيذ داخل Transaction واحدة ─────────────────────────────────
        print("\n[4] تنفيذ...")
        try:
            # Cash SBT
            sbt = SafeBoxTransaction(
                safe_box_id=sb_to.id,
                ref_type='invoice_payment',
                ref_id=ip.id,
                invoice_id=ip.invoice_id,
                invoice_payment_id=ip.id,
                payment_method_id=ip.payment_method_id,
                direction='in',
                amount_cash=float(amount),
                notes=(
                    f"historical_reclassification_repair: IP#{ip_id} "
                    f"from {pm_from.name} to {pm_to.name}"
                ),
                created_by='repair_payment_reclassification',
            )
            db.session.add(sbt)

            # GL Journal Entry
            je = JournalEntry(
                entry_number=_generate_journal_entry_number('ADJ'),
                date=datetime.now(),
                description=(
                    f"إصلاح تاريخي: إعادة تصنيف IP#{ip_id} "
                    f"من {pm_from.name} إلى {pm_to.name} — {amount:,.2f}"
                ),
                entry_type='تصحيح',
                reference_type='historical_reclassification',
                reference_id=ip.id,
                created_by='repair_payment_reclassification',
                is_posted=True,
                posted_at=datetime.now(),
                posted_by='repair_payment_reclassification',
            )
            db.session.add(je)
            db.session.flush()

            db.session.add(JournalEntryLine(
                journal_entry_id=je.id,
                account_id=acc_to.id,
                cash_debit=float(amount),
                cash_credit=0.0,
            ))
            db.session.add(JournalEntryLine(
                journal_entry_id=je.id,
                account_id=acc_from.id,
                cash_debit=0.0,
                cash_credit=float(amount),
            ))

            # AuditLog
            import json
            AuditLog.log_action(
                user_name='repair_payment_reclassification',
                action='historical_reclassification_repair',
                entity_type='InvoicePayment',
                entity_id=ip.id,
                entity_number=str(ip.invoice_id),
                details=json.dumps({
                    'invoice_payment_id': ip.id,
                    'amount': amount,
                    'from_payment_method_id': pm_from.id,
                    'from_payment_method_name': pm_from.name,
                    'to_payment_method_id': pm_to.id,
                    'to_payment_method_name': pm_to.name,
                    'cash_sbt_safe_box_id': sb_to.id,
                    'gl_journal_entry_id': je.id,
                    'reason': (
                        'correct_invoice_payment_method split was executed when '
                        'target payment method had no safe box; GL and Cash SBT '
                        'were not created at that time.'
                    ),
                }, ensure_ascii=False),
                success=True,
            )

            db.session.flush()

            # ── 5. تحقق بعد التنفيذ قبل Commit ─────────────────────────────
            print("\n[5] تحقق ما بعد التنفيذ:")
            post_errors: list[str] = []

            if not _has_cash_sbt(ip_id, sb_to.id):
                post_errors.append("❌ Cash SBT لم يُنشأ!")
            else:
                print(f"  ✓ Cash SBT موجود في {_label(sb_to)}")

            mada_sbt_new = SafeBoxTransaction.query.filter_by(
                invoice_payment_id=ip_id,
                safe_box_id=sb_from.id,
            ).count() if sb_from else 0
            if mada_sbt_new > 0:
                post_errors.append(
                    f"❌ تم إنشاء SBT في خزينة المصدر {_label(sb_from)} — غير متوقع!"
                )
            else:
                print(f"  ✓ لا SBT جديد في خزينة المصدر {_label(sb_from)}")

            bal_from_after = _gl_balance(acc_from.id)
            bal_to_after = _gl_balance(acc_to.id)
            expected_from = round(bal_from_before - amount, 2)
            expected_to = round(bal_to_before + amount, 2)

            if abs(bal_from_after - expected_from) > EPSILON:
                post_errors.append(
                    f"❌ رصيد {_label(acc_from)}: متوقع {expected_from:,.2f}، فعلي {bal_from_after:,.2f}"
                )
            else:
                print(f"  ✓ رصيد {_label(acc_from)}: {bal_from_before:,.2f} → {bal_from_after:,.2f}")

            if abs(bal_to_after - expected_to) > EPSILON:
                post_errors.append(
                    f"❌ رصيد {_label(acc_to)}: متوقع {expected_to:,.2f}، فعلي {bal_to_after:,.2f}"
                )
            else:
                print(f"  ✓ رصيد {_label(acc_to)}: {bal_to_before:,.2f} → {bal_to_after:,.2f}")

            if post_errors:
                db.session.rollback()
                print(f"\n{'='*65}")
                print("❌ Rollback — فشل التحقق بعد التنفيذ:")
                for e in post_errors:
                    print(f"   {e}")
                return 1

            db.session.commit()
            print(f"\n{'='*65}")
            print("✅ Commit ناجح — جميع الفحوصات اجتازت.")
            return 0

        except Exception as exc:
            db.session.rollback()
            print(f"\n❌ خطأ غير متوقع — Rollback: {exc}")
            return 1


def _print_errors(errors: list[str]) -> None:
    print(f"\n{'='*65}")
    print("❌ توقف — فحوصات فاشلة قبل أي كتابة:")
    for e in errors:
        print(f"   • {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='إصلاح تاريخي: إنشاء Cash SBT + قيد GL لدفعة مُعاد تصنيفها'
    )
    parser.add_argument('--invoice-payment', type=int, required=True,
                        help='ID لـInvoicePayment الهدف (وسيلة الدفع الجديدة)')
    parser.add_argument('--amount', type=float, required=True,
                        help='المبلغ المراد إصلاحه')
    parser.add_argument('--from-payment-method', type=int, required=True,
                        help='ID لوسيلة الدفع الأصلية (المصدر، مثلاً مدى=10)')
    parser.add_argument('--apply', action='store_true', default=False,
                        help='تنفيذ فعلي (الافتراضي: DRY RUN)')
    args = parser.parse_args()
    sys.exit(run(args.invoice_payment, args.amount, args.from_payment_method, args.apply))
