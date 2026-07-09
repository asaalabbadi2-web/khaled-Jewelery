"""
rebuild_settlement_lines.py
============================
إعادة بناء جميع SettlementLines للصندوق 32 (مدى) من الصفر.

الفلسفة:
  SettlementLine = Derived Data.
  القيود المحاسبية (Voucher + JournalEntry) لا تتغير.
  الخوارزمية الحالية (AllocationService + validate()) صحيحة ومضمونة.
  ∴ نحذف جميع SettlementLines القديمة ونعيد بنائها وفق FIFO الصحيح.

الترتيب:
  1. Dry Run  — اعرض ما سيحدث دون كتابة (الوضع الافتراضي).
  2. Apply    — نفّذ إعادة البناء الفعلية (--apply).

قاعدة التاريخ (نفس repair_safe_box):
  كل سند يرى فقط IPs بـ created_at ≤ voucher.date + 2 أيام.
  يمنع "السرقة" عبر الزمن.

نتيجة متوقعة:
  AV133 تحصل على IPs الأصلية = 19,710 ✅
  أي سند يبقى ناقصاً بعد الإعادة = فجوة محاسبية حقيقية (مال وصل بلا IP).

تشغيل:
  docker exec yasargold-backend python backend/rebuild_settlement_lines.py
  docker exec yasargold-backend python backend/rebuild_settlement_lines.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import func

from app import app
from models import (
    db, InvoicePayment, PaymentMethod, SafeBox,
    SettlementLine, Voucher, VoucherAccountLine,
)
from allocation_service import AllocationService
from allocation_repair_service import _extract_fee_vat, _get_clearing_account_id

SAFE_BOX_ID = 32


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _all_clearing_vouchers(safe_box: SafeBox) -> list[Voucher]:
    """جميع سندات تسوية المقاصة المعتمدة للصندوق (كاملة + ناقصة)."""
    return (
        Voucher.query
        .filter(Voucher.reference_type == 'clearing_settlement')
        .filter(Voucher.status == 'approved')
        .join(VoucherAccountLine, VoucherAccountLine.voucher_id == Voucher.id)
        .filter(VoucherAccountLine.account_id == safe_box.account_id)
        .order_by(Voucher.date.asc(), Voucher.id.asc())
        .distinct()
        .all()
    )


def _ip_pool(v: Voucher, all_ip_ids: list[int], ip_date_map: dict[int, datetime]) -> list[int]:
    """IPs بـ created_at ≤ voucher.date + 2d — نفس حد repair_safe_box."""
    if not v.date:
        return all_ip_ids
    v_dt = (
        v.date if isinstance(v.date, datetime)
        else datetime(v.date.year, v.date.month, v.date.day, 23, 59, 59)
    )
    cutoff = v_dt + timedelta(days=2)
    return [ip_id for ip_id in all_ip_ids
            if ip_date_map.get(ip_id, datetime.min) <= cutoff]


def _sl_total(voucher_id: int) -> float:
    return float(
        db.session.query(
            func.coalesce(func.sum(SettlementLine.amount_settled), 0.0)
        ).filter(SettlementLine.voucher_id == voucher_id).scalar()
        or 0.0
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run(apply: bool) -> None:
    with app.app_context():
        run_dt = datetime.now(timezone.utc)
        mode = 'APPLY' if apply else 'DRY RUN'

        safe_box = SafeBox.query.get(SAFE_BOX_ID)
        if not safe_box:
            print(f'❌ SafeBox id={SAFE_BOX_ID} غير موجود')
            return

        print('=' * 72)
        print(f'{mode} — إعادة بناء SettlementLines | صندوق {SAFE_BOX_ID} (مدى)')
        print(f'الوقت: {run_dt.strftime("%Y-%m-%d %H:%M UTC")}')
        print('=' * 72)

        vouchers = _all_clearing_vouchers(safe_box)
        if not vouchers:
            print('لا توجد سندات تسوية مقاصة للصندوق — لا شيء يحتاج إعادة بناء.')
            return

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

        total_cash = sum(float(v.amount_cash or 0) for v in vouchers)
        total_sl_now = float(
            db.session.query(
                func.coalesce(func.sum(SettlementLine.amount_settled), 0.0)
            )
            .join(Voucher, Voucher.id == SettlementLine.voucher_id)
            .filter(Voucher.reference_type == 'clearing_settlement')
            .scalar()
            or 0.0
        )

        print(f'\nإجمالي سندات التسوية:          {len(vouchers)}')
        print(f'إجمالي InvoicePayments:         {len(all_ip_ids)}')
        print(f'إجمالي amount_cash:             {total_cash:>12.2f}')
        print(f'إجمالي SettlementLines الحالية: {total_sl_now:>12.2f}')
        print(f'الفجوة الراهنة:                 {total_cash - total_sl_now:>12.2f}')

        if apply:
            results = _apply(vouchers, all_ip_ids, ip_date_map)
        else:
            results = _dry_run(vouchers, all_ip_ids, ip_date_map)

        _report(results, applied=apply, run_dt=run_dt)


# ---------------------------------------------------------------------------
# dry run — savepoint يُحاكي الترتيب الكامل ثم Rollback
# ---------------------------------------------------------------------------

def _dry_run(
    vouchers: list[Voucher],
    all_ip_ids: list[int],
    ip_date_map: dict[int, datetime],
) -> list[dict]:
    """
    يُحاكي الإعادة الكاملة داخل savepoint واحد.
    كل سند يرى SLs السندات السابقة (التي أُنشئت في نفس الـ savepoint)،
    فيعكس بدقة ما سيراه الـ apply.
    الـ rollback في النهاية يُلغي كل شيء — لا تغيير دائم.
    """
    svc = AllocationService()
    results: list[dict] = []

    print(f'\n{"─" * 72}')
    print('DRY RUN — محاكاة كاملة (لا تغيير دائم)')
    print(f'{"─" * 72}')

    sp = db.session.begin_nested()
    try:
        for v in vouchers:
            fee_amount, fee_vat = _extract_fee_vat(v, _get_clearing_account_id(v))
            v_gross = round(float(v.amount_cash or 0), 2)
            pool = _ip_pool(v, all_ip_ids, ip_date_map)
            sl_before = _sl_total(v.id)

            inner = db.session.begin_nested()
            try:
                svc.unallocate(v)
                db.session.flush()

                plan = svc.build_allocation_plan(
                    voucher=v,
                    invoice_payment_ids=pool,
                    gross_amount=v_gross,
                    fee_amount=fee_amount,
                    fee_vat=fee_vat,
                )

                # أنشئ SLs مؤقتاً حتى يرى السند التالي prev_settled الصحيح
                for line in plan.lines:
                    db.session.add(SettlementLine(
                        voucher_id=v.id,
                        invoice_payment_id=line.invoice_payment_id,
                        amount_settled=line.amount_to_allocate,
                        commission=line.commission,
                        commission_vat=line.commission_vat,
                    ))
                db.session.flush()

                results.append(_row(v, v_gross, sl_before, plan.total_allocated,
                                    plan.unallocated_remainder, len(plan.lines)))
            except Exception as exc:
                inner.rollback()
                results.append(_row(v, v_gross, sl_before, 0.0, v_gross, 0, error=str(exc)))
    finally:
        sp.rollback()  # يُلغي كل شيء — الـ DB تعود كما كانت

    return results


# ---------------------------------------------------------------------------
# apply — تنفيذ فعلي، commit لكل سند مستقل
# ---------------------------------------------------------------------------

def _apply(
    vouchers: list[Voucher],
    all_ip_ids: list[int],
    ip_date_map: dict[int, datetime],
) -> list[dict]:
    """
    ينفّذ الإعادة الفعلية سنداً تلو الآخر.
    Commit مستقل لكل سند: فشل السند N لا يُلغي نجاح 1..N-1.
    """
    svc = AllocationService()
    results: list[dict] = []

    print(f'\n{"─" * 72}')
    print('APPLY — تنفيذ إعادة البناء')
    print(f'{"─" * 72}\n')

    for v in vouchers:
        fee_amount, fee_vat = _extract_fee_vat(v, _get_clearing_account_id(v))
        v_gross = round(float(v.amount_cash or 0), 2)
        pool = _ip_pool(v, all_ip_ids, ip_date_map)
        sl_before = _sl_total(v.id)

        try:
            svc.unallocate(v)
            db.session.flush()

            plan = svc.allocate(
                voucher=v,
                invoice_payment_ids=pool,
                gross_amount=v_gross,
                fee_amount=fee_amount,
                fee_vat=fee_vat,
            )
            db.session.flush()
            db.session.commit()

            icon = '✅' if plan.is_fully_covered else '⚠️ '
            print(f'{icon} {v.voucher_number:<22} {str(v.date)[:10]}  '
                  f'{v_gross:>9.0f}  SL={plan.total_allocated:>9.0f}  '
                  f'فجوة={plan.unallocated_remainder:>7.0f}')

            results.append(_row(v, v_gross, sl_before, plan.total_allocated,
                                plan.unallocated_remainder, len(plan.lines)))

        except Exception as exc:
            db.session.rollback()
            print(f'❌ {v.voucher_number:<22} {str(v.date)[:10]}  '
                  f'{v_gross:>9.0f}  خطأ: {exc}')
            results.append(_row(v, v_gross, sl_before, 0.0, v_gross, 0, error=str(exc)))

    return results


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _row(
    v: Voucher,
    v_gross: float,
    sl_before: float,
    sl_after: float,
    remainder: float,
    ip_count: int,
    error: str | None = None,
) -> dict:
    return {
        'voucher_id': v.id,
        'voucher_number': v.voucher_number,
        'date': str(v.date)[:10],
        'amount_cash': v_gross,
        'sl_before': round(sl_before, 2),
        'sl_after': round(sl_after, 2),
        'remainder': round(remainder, 2),
        'ip_count': ip_count,
        'fully_covered': remainder < 0.01,
        'error': error,
    }


def _report(results: list[dict], applied: bool, run_dt: datetime) -> None:
    fully = sum(1 for r in results if r['fully_covered'])
    partial = [r for r in results if not r['fully_covered'] and not r['error']]
    errors = [r for r in results if r['error']]
    total_cash = sum(r['amount_cash'] for r in results)
    total_after = sum(r['sl_after'] for r in results)

    print(f'\n{"=" * 72}')
    print('الملخص')
    print(f'{"=" * 72}')
    print(f'  مُغطَّى كاملاً:  {fully}')
    print(f'  ناقص التغطية:   {len(partial)}')
    print(f'  أخطاء:          {len(errors)}')
    print(f'  إجمالي amount_cash: {total_cash:>12.2f}')
    print(f'  إجمالي SL بعد:     {total_after:>12.2f}')
    print(f'  الفجوة الكلية:     {total_cash - total_after:>12.2f}')

    if partial:
        print(f'\n⚠️  سندات ناقصة التغطية (فجوة محاسبية حقيقية):')
        for r in partial:
            print(f'  {r["voucher_number"]} ({r["date"]}) '
                  f'| مطلوب={r["amount_cash"]:.0f} '
                  f'| مُخصَّص={r["sl_after"]:.0f} '
                  f'| فجوة={r["remainder"]:.0f}')

    if errors:
        print(f'\n❌ سندات بأخطاء:')
        for r in errors:
            print(f'  {r["voucher_number"]} ({r["date"]}) — {r["error"]}')

    if not partial and not errors:
        print('\n✅ جميع سندات التسوية مُغطَّاة بالكامل — قاعدة البيانات نظيفة')

    reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    suffix = 'applied' if applied else 'dryrun'
    path = os.path.join(
        reports_dir,
        f'rebuild_settlement_lines_{suffix}_{run_dt.strftime("%Y%m%dT%H%M%SZ")}.json',
    )
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'run_at': run_dt.isoformat(),
            'applied': applied,
            'safe_box_id': SAFE_BOX_ID,
            'summary': {
                'total_vouchers': len(results),
                'fully_covered': fully,
                'partial': len(partial),
                'errors': len(errors),
                'total_cash': total_cash,
                'total_allocated': total_after,
                'total_gap': total_cash - total_after,
            },
            'results': results,
        }, f, ensure_ascii=False, indent=2, default=str)

    print(f'\nتقرير: {path}')
    if not applied:
        print('\n(DRY RUN) لتطبيق الإعادة الفعلية: أضف --apply')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true',
                        help='نفّذ إعادة البناء الفعلية (بدونه: dry run)')
    args = parser.parse_args()
    run(apply=args.apply)
