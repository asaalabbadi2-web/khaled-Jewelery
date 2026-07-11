"""
fix_av133_july_ip_misallocation.py
=====================================
تصحيح جراحي محدّد: حذف سطور SettlementLine التي تربط IPs يوليو
(2412, 2417, 2435, 2436, 2440) بسند مايو AV-2026-00133 (voucher_id=1649).

السياق:
    Phase 0 repair نفّذ repair_safe_box قبل إضافة حماية حدود التاريخ.
    النتيجة: 5 IPs تعود ليوليو (إجمالي 6,050 ريال) امتُصّت لتغطية فجوة
    AV-2026-00133 (مايو، 19,710 ريال). هذه الـ IPs أصبحت "مُسوَّاة"
    من منظور الجدولة → سندات يوليو تنشأ بفجوة 6,050 ريال.

ما يفعله هذا السكربت:
    1. يحدّد سطور SettlementLine المرتبطة بـ AV-2026-00133 AND ip_id IN (...)
    2. يتحقق أن مجموعها = 6,050 ريال (ضمن 1 هللة — أمان)
    3. يحذفها فقط (لا مساس بالسطور الصحيحة لمايو الباقية)
    4. بعد الحذف: AV-2026-00133 تعود لفجوتها الأصلية (6,050 ريال ناقصة)
       والـ IPs اليوليوية تعود للمسبح المتاح لسندات يوليو.

ما لا يفعله:
    - لا يعيد توزيع أي تخصيصات
    - لا يمس VoucherAccountLine أو JournalEntry أو amount_cash لأي سند
    - لا يصحح فجوة AV-2026-00133 الأصلية (6,050 ريال — هذه قرار محاسبي مستقل)

الخطوات بعد تطبيق هذا السكربت:
    1. شغّل reconcile_clearing_settlement_coverage.py --safe-box-id 32
       للتحقق من تحرر الـ IPs
    2. شغّل repair_safe_box() لسندات يوليو — الآن ستمتص الـ IPs المحرّرة
       بحماية حدود التاريخ (voucher.date + 2 أيام) المضافة مسبقاً
    3. فجوة AV-2026-00133: يحتاج قراراً محاسبياً (سند تصحيحي أو توثيق
       كفارق تاريخي — cash وصل البنك لكن IP المقابلة غير مسجّلة أو مرتبطة
       بطريقة دفع مختلفة)

الوضع الافتراضي: DRY RUN (لا يُحفظ شيء).

تشغيل:
    docker cp backend/fix_av133_july_ip_misallocation.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/fix_av133_july_ip_misallocation.py            # dry run
    docker exec yasargold-backend python backend/fix_av133_july_ip_misallocation.py --apply     # تطبيق فعلي
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SettlementLine, Voucher, InvoicePayment

# ── الثوابت — تحديث هذه القيم من تقرير التدقيق إن تغيّرت ─────────────────────
AV133_VOUCHER_ID = 1649                         # AV-2026-00133 (مايو)
JULY_IP_IDS = {2412, 2417, 2435, 2436, 2440}   # IPs يوليو التي امتُصّت بالخطأ
EXPECTED_TOTAL = 6050.00                        # المجموع المتوقع للسطور المحذوفة
EPS = 0.50                                      # هامش قبول (0.50 ريال)


def run(apply: bool) -> None:
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        # ── 1) التحقق من وجود السند ──────────────────────────────────────────
        voucher = Voucher.query.get(AV133_VOUCHER_ID)
        if not voucher:
            print(f"❌ توقّف: Voucher id={AV133_VOUCHER_ID} غير موجود.")
            return
        print(f"السند: {voucher.voucher_number} | amount_cash={float(voucher.amount_cash or 0):.2f}")

        # ── 2) إيجاد سطور SettlementLine المشكوك فيها ───────────────────────
        bad_lines = (
            SettlementLine.query
            .filter(
                SettlementLine.voucher_id == AV133_VOUCHER_ID,
                SettlementLine.invoice_payment_id.in_(JULY_IP_IDS),
            )
            .all()
        )

        if not bad_lines:
            print(
                f"\n✅ لا توجد سطور SettlementLine تربط AV-2026-00133 بالـ IPs "
                f"{sorted(JULY_IP_IDS)}.\n"
                f"يبدو أن الإصلاح طُبِّق مسبقاً، أو أن السند يستخدم IDs مختلفة."
            )
            return

        # ── 3) التحقق من المبلغ ──────────────────────────────────────────────
        bad_total = round(sum(sl.amount_settled for sl in bad_lines), 2)
        print(f"\nسطور SettlementLine المحدَّدة للحذف ({len(bad_lines)} سطور):")
        for sl in sorted(bad_lines, key=lambda x: x.invoice_payment_id):
            ip = InvoicePayment.query.get(sl.invoice_payment_id)
            ip_created = ip.created_at.strftime('%Y-%m-%d') if ip and ip.created_at else '؟'
            print(
                f"  SettlementLine#{sl.id:>6} | IP#{sl.invoice_payment_id} "
                f"(created_at={ip_created}) | amount_settled={sl.amount_settled:.2f}"
            )
        print(f"\nإجمالي سطور الحذف: {bad_total:.2f}")
        print(f"المتوقع:            {EXPECTED_TOTAL:.2f}")

        total_mismatch = abs(bad_total - EXPECTED_TOTAL) > EPS
        if total_mismatch:
            print(
                f"\n⚠️  تحذير: المجموع الفعلي ({bad_total:.2f}) يختلف عن المتوقع "
                f"({EXPECTED_TOTAL:.2f}) بفارق > {EPS:.2f} ريال.\n"
                f"تحقق من IDs الـ IPs — السكربت يتوقف في وضع الأمان."
            )
            return

        # ── 4) حالة AV-2026-00133 قبل وبعد ──────────────────────────────────
        all_sl_before = SettlementLine.query.filter_by(voucher_id=AV133_VOUCHER_ID).all()
        total_before = round(sum(sl.amount_settled for sl in all_sl_before), 2)
        total_after = round(total_before - bad_total, 2)
        credited = float(voucher.amount_cash or 0)

        print(f"\nحالة AV-2026-00133:")
        print(f"  amount_cash (مقيَّد على الحساب):              {credited:.2f}")
        print(f"  settlement_line_total (قبل):                  {total_before:.2f}")
        print(f"  فجوة قبل الحذف:                               {credited - total_before:.2f}")
        print(f"  settlement_line_total (بعد الحذف):            {total_after:.2f}")
        print(f"  فجوة بعد الحذف (الفجوة الأصلية الحقيقية):    {credited - total_after:.2f}")

        # ── 5) تأثير على IPs يوليو ────────────────────────────────────────────
        print(f"\nIPs يوليو التي ستُحرَّر:")
        for sl in sorted(bad_lines, key=lambda x: x.invoice_payment_id):
            ip = InvoicePayment.query.get(sl.invoice_payment_id)
            if ip:
                ip_total_covered = round(
                    sum(s.amount_settled for s in SettlementLine.query.filter_by(invoice_payment_id=ip.id).all()), 2
                )
                ip_covered_after = round(ip_total_covered - sl.amount_settled, 2)
                print(
                    f"  IP#{ip.id}: amount={float(ip.amount):.2f} | "
                    f"covered_before={ip_total_covered:.2f} | "
                    f"covered_after={ip_covered_after:.2f} | "
                    f"freed={sl.amount_settled:.2f}"
                )

        # ── 6) تطبيق أو DRY RUN ──────────────────────────────────────────────
        report = {
            'run_at': run_dt.isoformat(),
            'applied': apply,
            'voucher_id': AV133_VOUCHER_ID,
            'voucher_number': voucher.voucher_number,
            'july_ip_ids': sorted(JULY_IP_IDS),
            'lines_to_delete': [
                {
                    'settlement_line_id': sl.id,
                    'invoice_payment_id': sl.invoice_payment_id,
                    'amount_settled': sl.amount_settled,
                }
                for sl in bad_lines
            ],
            'bad_total': bad_total,
            'av133_credited': credited,
            'av133_sl_total_before': total_before,
            'av133_gap_before': round(credited - total_before, 2),
            'av133_sl_total_after': total_after,
            'av133_gap_after': round(credited - total_after, 2),
        }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        suffix = '_applied' if apply else '_dryrun'
        report_path = os.path.join(
            reports_dir,
            f"fix_av133_july_ip_misallocation_{run_dt.strftime('%Y%m%dT%H%M%SZ')}{suffix}.json",
        )

        if apply:
            for sl in bad_lines:
                db.session.delete(sl)
            db.session.commit()
            print(f"\n✅ تم حذف {len(bad_lines)} سطر SettlementLine وحفظها.")
            print(f"   IPs يوليو ({sorted(JULY_IP_IDS)}) أصبحت متاحة لسندات يوليو.")
            print(f"   AV-2026-00133 تعود لفجوتها الأصلية ({credited - total_after:.2f} ريال).")
            print(f"\nالخطوة التالية:")
            print(f"  1. شغّل reconcile_clearing_settlement_coverage.py --safe-box-id 32 للتحقق")
            print(f"  2. شغّل repair_safe_box() لإصلاح سندات يوليو (ستمتص الـ IPs المحرّرة)")
            print(f"  3. فجوة AV-2026-00133 ({credited - total_after:.2f} ريال) — قرار محاسبي مستقل")
        else:
            db.session.rollback()
            print(f"\n(DRY RUN) لا تغييرات في قاعدة البيانات.")
            print(f"لتطبيق التغيير الفعلي: أضف --apply")

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nتم كتابة التقرير: {report_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='تطبيق التغييرات الفعلية (افتراضي: dry run)')
    args = parser.parse_args()
    run(apply=args.apply)
