"""
repair_july_vouchers_dry_run.py
=================================
غلاف آمن لـ AllocationRepairService.repair_safe_box() مع وضع Dry Run كامل.

المشكلة التي يعالجها:
    بعد تحرير الـ 5 IPs اليوليوية من AV-2026-00133 (الخطوة 1)، تصبح
    سندات يوليو ناقصة التغطية بمقدار 6,050 ريال. هذا السكربت يُعيد
    التخصيص بحماية حد التاريخ (voucher.date + 2 أيام) الموجودة في
    AllocationRepairService.repair_safe_box().

تسلسل الاستخدام:
    1. (dry run) — تحليل + عرض الخطة دون أي كتابة
    2. مراجعة بشرية للنتائج
    3. (apply) — تنفيذ الإصلاح الفعلي

الوضع الافتراضي: Dry Run (لا يُحفظ شيء في قاعدة البيانات).

تشغيل:
    docker cp backend/repair_july_vouchers_dry_run.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/repair_july_vouchers_dry_run.py            # dry run
    docker exec yasargold-backend python backend/repair_july_vouchers_dry_run.py --apply     # تطبيق فعلي
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SafeBox, Voucher, SettlementLine, InvoicePayment, PaymentMethod
from sqlalchemy import func
from allocation_service import AllocationService
from allocation_repair_service import AllocationRepairService, _extract_fee_vat, _get_clearing_account_id

SAFE_BOX_ID = 32
EPS = 0.005


# ---------------------------------------------------------------------------
# Dry-run preview — يُحاكي repair_safe_box() بدون أي DB writes
# ---------------------------------------------------------------------------

def _build_dry_run_preview(safe_box: SafeBox) -> list[dict]:
    """
    يُحاكي repair_safe_box بدون كتابة فعلية.

    المشكلة التي حُلّت:
        النسخة الأولى كانت تستدعي build_allocation_plan() مباشرة بدون
        محاكاة unallocate — فتظهر SettlementLines الموجودة للسند كـ prev_settled
        وتُعطي نتيجة "0 IPs متاحة" رغم وجود تغطية كافية.

    الحل — savepoint يُحاكي repair_voucher بدقة:
        لكل سند:
          1. begin_nested() → savepoint
          2. حذف SettlementLines الحالية (unallocate) + flush
          3. build_allocation_plan() — يرى نفس الـ prev_settled التي
             سيراها repair_voucher الحقيقي بعد الـ unallocate
          4. rollback إلى الـ savepoint → قاعدة البيانات تعود كما كانت

    هذا يضمن أن الـ dry run يستخدم نفس منطق build_allocation_plan
    تماماً كما سيفعل الـ apply، بلا أي اختلاف في مصدر الحقيقة.
    """
    svc = AllocationService()

    # كل IPs الصندوق مُرتَّبة زمنياً
    all_ips = (
        InvoicePayment.query
        .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
        .filter(PaymentMethod.default_safe_box_id == safe_box.id)
        .order_by(InvoicePayment.created_at.asc())
        .all()
    )
    ip_date_map: dict[int, datetime] = {
        ip.id: (ip.created_at or datetime.min) for ip in all_ips
    }
    all_ip_ids = [ip.id for ip in all_ips]

    # السندات الناقصة
    repair_svc = AllocationRepairService()
    incomplete = repair_svc.find_incomplete_vouchers(safe_box=safe_box)
    incomplete_sorted = sorted(incomplete, key=lambda x: (x.date or datetime.min, x.id))

    previews = []
    for v in incomplete_sorted:
        v_gross = round(float(v.amount_cash or 0), 2)

        # نفس فلتر التاريخ المستخدم في repair_safe_box
        if v.date:
            v_dt = v.date if isinstance(v.date, datetime) else datetime(
                v.date.year, v.date.month, v.date.day, 23, 59, 59
            )
            cutoff = v_dt + timedelta(days=2)
            ip_pool = [ip_id for ip_id in all_ip_ids
                       if ip_date_map.get(ip_id, datetime.min) <= cutoff]
        else:
            ip_pool = all_ip_ids

        # الحالة الراهنة (SettlementLines الموجودة)
        current_sl_total = (
            db.session.query(
                func.coalesce(func.sum(SettlementLine.amount_settled), 0.0)
            )
            .filter(SettlementLine.voucher_id == v.id)
            .scalar()
        ) or 0.0
        current_gap = round(v_gross - float(current_sl_total), 2)

        # محاكاة unallocate داخل savepoint ثم rollback
        # → build_allocation_plan يرى نفس الـ prev_settled الذي سيراه
        #   repair_voucher الحقيقي بعد حذف السطور الحالية
        clearing_account_id = _get_clearing_account_id(v)
        fee_amount, fee_vat = _extract_fee_vat(v, clearing_account_id)

        sp = db.session.begin_nested()
        try:
            SettlementLine.query.filter_by(voucher_id=v.id).delete(
                synchronize_session=False
            )
            db.session.flush()
            plan = svc.build_allocation_plan(
                voucher=v,
                invoice_payment_ids=ip_pool,
                gross_amount=v_gross,
                fee_amount=fee_amount,
                fee_vat=fee_vat,
            )
        finally:
            sp.rollback()  # يُعيد SettlementLines كما كانت — لا تغيير دائم

        previews.append({
            'voucher_id': v.id,
            'voucher_number': v.voucher_number or str(v.id),
            'date': str(v.date),
            'amount_cash': v_gross,
            'current_settlement_total': round(float(current_sl_total), 2),
            'current_gap': current_gap,
            'ip_pool_size': len(ip_pool),
            'cutoff_date': cutoff.strftime('%Y-%m-%d') if v.date else None,
            'plan_lines': [
                {
                    'ip_id': line.invoice_payment_id,
                    'amount_to_allocate': line.amount_to_allocate,
                }
                for line in plan.lines
            ],
            'plan_total_allocated': plan.total_allocated,
            'plan_remainder': plan.unallocated_remainder,
            'plan_fully_covered': plan.is_fully_covered,
            'verdict': (
                'will_be_fully_covered' if plan.is_fully_covered
                else 'will_remain_partial'
            ),
        })

    return previews


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(apply: bool) -> None:
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        safe_box = SafeBox.query.get(SAFE_BOX_ID)
        if not safe_box:
            print(f"❌ SafeBox id={SAFE_BOX_ID} غير موجود.")
            return

        print("=" * 70)
        print(f"{'تطبيق فعلي' if apply else 'DRY RUN — لن يُحفظ شيء في قاعدة البيانات'}")
        print(f"الصندوق: {getattr(safe_box, 'name', SAFE_BOX_ID)} (id={SAFE_BOX_ID})")
        print("=" * 70)

        # ── Dry Run Preview ──────────────────────────────────────────────────
        previews = _build_dry_run_preview(safe_box)

        if not previews:
            print("\n✅ لا توجد سندات ناقصة التغطية — لا شيء يحتاج إصلاحاً.")
            return

        print(f"\nالسندات الناقصة ({len(previews)} سند):")
        print(f"{'السند':<18} {'التاريخ':<12} {'amount_cash':>12} {'الفجوة الراهنة':>15} "
              f"{'بعد الإصلاح':>12} {'نتيجة':<22}")
        print("-" * 95)

        fully_covered_count = 0
        partial_count = 0
        for p in previews:
            verdict_ar = '✅ سيُغطَّى كاملاً' if p['plan_fully_covered'] else f"⚠️  فجوة {p['plan_remainder']:.2f} تبقى"
            after_total = round(p['plan_total_allocated'], 2)
            print(
                f"{p['voucher_number']:<18} {p['date'][:10]:<12} "
                f"{p['amount_cash']:>12.2f} {p['current_gap']:>15.2f} "
                f"{after_total:>12.2f} {verdict_ar:<22}"
            )
            if p['plan_fully_covered']:
                fully_covered_count += 1
            else:
                partial_count += 1

        print("-" * 95)
        print(f"سيُغطَّى كاملاً: {fully_covered_count} | سيبقى جزئياً: {partial_count}")

        # تفاصيل الـ IPs لكل سند
        print("\n── تفاصيل خطة التخصيص ──")
        for p in previews:
            if not p['plan_lines']:
                print(f"  {p['voucher_number']}: لا IPs متاحة في النافذة (≤ {p['cutoff_date']})")
                continue
            print(f"\n  {p['voucher_number']} (id={p['voucher_id']}) | نافذة ≤ {p['cutoff_date']} | "
                  f"pool={p['ip_pool_size']} IP")
            for ln in p['plan_lines']:
                print(f"    IP#{ln['ip_id']:>6} → {ln['amount_to_allocate']:.2f}")
            print(f"    المجموع: {p['plan_total_allocated']:.2f} / {p['amount_cash']:.2f} "
                  f"| متبقٍّ: {p['plan_remainder']:.2f}")

        # ── كتابة التقرير ────────────────────────────────────────────────────
        report = {
            'run_at': run_dt.isoformat(),
            'applied': apply,
            'safe_box_id': SAFE_BOX_ID,
            'preview': previews,
            'summary': {
                'total_incomplete': len(previews),
                'will_be_fully_covered': fully_covered_count,
                'will_remain_partial': partial_count,
            },
        }
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        suffix = '_applied' if apply else '_dryrun'
        report_path = os.path.join(
            reports_dir,
            f"repair_july_vouchers{suffix}_{run_dt.strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nتم كتابة التقرير: {report_path}")

        # ── تطبيق الإصلاح الفعلي ─────────────────────────────────────────────
        if not apply:
            print("\n(DRY RUN) لتطبيق الإصلاح الفعلي: أضف --apply")
            return

        print("\nتطبيق الإصلاح...")
        svc = AllocationRepairService()
        results = svc.repair_safe_box(safe_box=safe_box)

        succeeded = [r for r in results if r.is_repaired]
        failed = [r for r in results if not r.is_repaired]

        print(f"\nنتائج التطبيق ({len(results)} سند):")
        for r in results:
            status = '✅' if r.is_repaired else '❌'
            print(f"  {status} {r.voucher_number} | حُذف={r.lines_deleted} | أُنشئ={r.lines_created} "
                  f"{'| خطأ: ' + r.error if r.error else ''}")

        print(f"\nنجح: {len(succeeded)} | فشل: {len(failed)}")
        if failed:
            print("\n⚠️  السندات التي لم تُصلَح (تحتاج تحقيقاً إضافياً):")
            for r in failed:
                print(f"  {r.voucher_number}: {r.error}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    run(apply=args.apply)
