"""
trace_av133_ip_pool.py
========================
سكريبت تشخيصي قراءة فقط يُجيب عن سؤالين حاسمين:

  السؤال 1: لماذا investigate_av133 (النسخة القديمة) رأت 31,790 متاحاً
             بينما build_allocation_plan يرى 13,660 فقط؟
             → الفارق 18,130: من أين جاء؟

  السؤال 2: هل IP#1547 / 1548 / 1554 كانت مرتبطة بأي سند قبل AV-2026-00133؟
             → يحسم: هل Phase 0 أخذ IPs من سند سابق (Bug) أم كانت متاحة؟

المنهجية:
  لكل IP في نافذة AV133 (created_at ≤ 2026-05-21):
    A. prev_settled_historical = ما سوّاه approved vouchers dated < May19 (investigate القديم)
    B. prev_settled_alloc      = ما سوّاه ALL approved vouchers (build_allocation_plan)
    C. available_historical    = ip.amount - A
    D. available_alloc         = ip.amount - B
    E. الفارق (D - C)         = ما استهلكته سندات مايو19+ على هذا الـ IP

  الإجمالي: sum(C) = 31,790 | sum(D) = 13,660 | الفارق = 18,130
  القائمة التفصيلية لكل IP الذي يُسهم في الفارق + السند المسؤول عنه.

لا كتابة في قاعدة البيانات.

تشغيل:
    docker cp backend/trace_av133_ip_pool.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/trace_av133_ip_pool.py
"""

from __future__ import annotations

import os
import sys
import json
from collections import defaultdict
from datetime import datetime, date as date_type, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import (
    db, Voucher, SettlementLine,
    InvoicePayment, PaymentMethod, SafeBox,
)

AV133_VOUCHER_ID = 1649
AV133_DATE_STR   = '2026-05-19'      # تاريخ إنشاء AV133
SAFE_BOX_ID      = 32
CUTOFF_DAYS      = 2                  # نافذة AllocationRepairService المعيارية
FOCUS_IP_IDS     = {1547, 1548, 1554} # IPs التي أضافها Phase 0 لـ AV133
EPS              = 0.005


def _dt(d) -> datetime:
    if isinstance(d, datetime):
        return d
    if isinstance(d, date_type):
        return datetime(d.year, d.month, d.day, 23, 59, 59)
    return datetime.min


def run() -> None:
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        # ── السند المرجعي ────────────────────────────────────────────────────
        v133 = Voucher.query.get(AV133_VOUCHER_ID)
        if not v133:
            print(f"❌ Voucher {AV133_VOUCHER_ID} غير موجود.")
            return

        v133_date = _dt(v133.date)
        cutoff_std = v133_date + timedelta(days=CUTOFF_DAYS)
        v_gross = float(v133.amount_cash or 0)

        print("=" * 72)
        print(f"AV-2026-00133 | date={v133.date} | amount_cash={v_gross:.2f}")
        print(f"نافذة IP المعيارية: created_at ≤ {cutoff_std.strftime('%Y-%m-%d')}")
        print("=" * 72)

        # ── 1) كل IPs الصندوق في النافذة ────────────────────────────────────
        pool_ips = (
            InvoicePayment.query
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(
                PaymentMethod.default_safe_box_id == SAFE_BOX_ID,
                InvoicePayment.created_at <= cutoff_std,
            )
            .order_by(InvoicePayment.created_at.asc())
            .all()
        )
        pool_ids = [ip.id for ip in pool_ips]
        print(f"\nعدد IPs في النافذة: {len(pool_ids)}\n")

        # ── 2) كل SettlementLines لهذه الـ IPs مع السندات المرتبطة ──────────
        all_sl = (
            SettlementLine.query
            .filter(SettlementLine.invoice_payment_id.in_(pool_ids))
            .all()
        ) if pool_ids else []

        sl_by_ip: dict[int, list[SettlementLine]] = defaultdict(list)
        for sl in all_sl:
            sl_by_ip[sl.invoice_payment_id].append(sl)

        # معلومات السندات (status, date, number)
        voucher_ids_touched = {sl.voucher_id for sl in all_sl}
        voucher_map: dict[int, Voucher] = {}
        if voucher_ids_touched:
            for vv in Voucher.query.filter(Voucher.id.in_(voucher_ids_touched)).all():
                voucher_map[vv.id] = vv

        # ── 3) حساب الفارقين لكل IP ──────────────────────────────────────────
        rows = []
        total_available_historical = 0.0   # طريقة investigate القديمة
        total_available_alloc      = 0.0   # طريقة build_allocation_plan

        for ip in pool_ips:
            ip_amt = round(float(ip.amount or 0), 2)
            ip_sls = sl_by_ip.get(ip.id, [])

            # A. prev_settled_historical: approved + dated < AV133_date (investigate قديم)
            prev_hist = 0.0
            for sl in ip_sls:
                vv = voucher_map.get(sl.voucher_id)
                if not vv or vv.status != 'approved':
                    continue
                if vv.id == AV133_VOUCHER_ID:
                    continue   # نستبعد AV133 نفسها
                if _dt(vv.date) < v133_date:
                    prev_hist += sl.amount_settled
            prev_hist = round(prev_hist, 2)

            # B. prev_settled_alloc: ALL approved (build_allocation_plan) بعد unallocate
            #    بعد حذف سطور AV133 (محاكاة unallocate): نستبعد AV133 فقط
            prev_alloc = 0.0
            for sl in ip_sls:
                vv = voucher_map.get(sl.voucher_id)
                if not vv or vv.status != 'approved':
                    continue
                if vv.id == AV133_VOUCHER_ID:
                    continue   # مُحاكاة الـ unallocate
                prev_alloc += sl.amount_settled
            prev_alloc = round(prev_alloc, 2)

            avail_hist  = round(ip_amt - prev_hist, 2)
            avail_alloc = round(ip_amt - prev_alloc, 2)
            diff        = round(avail_hist - avail_alloc, 2)   # موجب = سندات مايو19+ استهلكته

            if avail_hist > EPS:
                total_available_historical += avail_hist
            if avail_alloc > EPS:
                total_available_alloc += avail_alloc

            # السندات التي استهلكت هذا الـ IP بعد مايو19 (سبب الفارق)
            consuming_vouchers_post_av133 = []
            for sl in ip_sls:
                vv = voucher_map.get(sl.voucher_id)
                if not vv or vv.status != 'approved':
                    continue
                if vv.id == AV133_VOUCHER_ID:
                    continue
                if _dt(vv.date) >= v133_date:
                    consuming_vouchers_post_av133.append({
                        'voucher_number': vv.voucher_number,
                        'voucher_date': str(vv.date)[:10],
                        'amount_settled': round(sl.amount_settled, 2),
                    })

            rows.append({
                'ip_id':               ip.id,
                'created_at':          ip.created_at.strftime('%Y-%m-%d') if ip.created_at else '؟',
                'amount':              ip_amt,
                'prev_hist':           prev_hist,
                'prev_alloc':          prev_alloc,
                'avail_hist':          avail_hist,
                'avail_alloc':         avail_alloc,
                'diff':                diff,
                'is_focus_ip':         ip.id in FOCUS_IP_IDS,
                'consuming_post_av133':consuming_vouchers_post_av133,
                'all_settlements':     [
                    {
                        'sl_id':     sl.id,
                        'voucher_number': voucher_map[sl.voucher_id].voucher_number if sl.voucher_id in voucher_map else '؟',
                        'voucher_date':   str(voucher_map[sl.voucher_id].date)[:10] if sl.voucher_id in voucher_map else '؟',
                        'voucher_status': voucher_map[sl.voucher_id].status if sl.voucher_id in voucher_map else '؟',
                        'amount_settled': round(sl.amount_settled, 2),
                        'is_av133':      sl.voucher_id == AV133_VOUCHER_ID,
                    }
                    for sl in sorted(ip_sls, key=lambda s: s.id)
                ],
            })

        total_available_historical = round(total_available_historical, 2)
        total_available_alloc      = round(total_available_alloc, 2)
        total_diff                 = round(total_available_historical - total_available_alloc, 2)

        # ── 4) طباعة الملخص ──────────────────────────────────────────────────
        print(f"{'='*72}")
        print("ملخص الفارق بين طريقتي الحساب")
        print(f"{'='*72}")
        print(f"  investigate (dated < May19):  {total_available_historical:>10.2f} ريال")
        print(f"  build_allocation_plan:         {total_available_alloc:>10.2f} ريال")
        print(f"  الفارق المفسَّر:               {total_diff:>10.2f} ريال")
        print(f"  فجوة AV133:                    {v_gross - total_available_alloc:>10.2f} ريال")

        # IPs التي تُسهم في الفارق
        diff_rows = [r for r in rows if r['diff'] > EPS]
        print(f"\nIPs التي تُسهم في الفارق ({len(diff_rows)} IP — استهلكتها سندات ≥ مايو19):")
        print(f"{'IP':>8} {'created':>12} {'gross':>8} {'avail_hist':>12} {'avail_alloc':>12} "
              f"{'diff':>8}  {'السند/السندات المُستهلِكة'}")
        print("-" * 100)
        for r in diff_rows:
            consuming = ', '.join(
                f"{c['voucher_number']} ({c['voucher_date']}) -{c['amount_settled']:.0f}"
                for c in r['consuming_post_av133']
            )
            print(f"  IP#{r['ip_id']:>5} {r['created_at']:>12} {r['amount']:>8.2f} "
                  f"{r['avail_hist']:>12.2f} {r['avail_alloc']:>12.2f} {r['diff']:>8.2f}  {consuming}")

        # ── 5) IPs التي أضافها Phase 0 لـ AV133 ─────────────────────────────
        print(f"\n{'='*72}")
        print(f"IP#1547 / 1548 / 1554 — هل كانت مرتبطة بسند سابق لـ AV133؟")
        print(f"{'='*72}")
        for r in rows:
            if not r['is_focus_ip']:
                continue
            has_prior = any(
                s['voucher_date'] < AV133_DATE_STR and not s['is_av133']
                for s in r['all_settlements']
            )
            print(f"\nIP#{r['ip_id']} (created={r['created_at']}, amount={r['amount']:.2f})")
            if r['all_settlements']:
                for s in r['all_settlements']:
                    marker = '← AV133 (Phase 0)' if s['is_av133'] else ''
                    prior_flag = ' ⚠️ سند سابق!' if (s['voucher_date'] < AV133_DATE_STR and not s['is_av133']) else ''
                    print(f"  SL#{s['sl_id']:>5}: {s['voucher_number']:>18} "
                          f"({s['voucher_date']}, {s['voucher_status']}) "
                          f"→ {s['amount_settled']:>9.2f} {marker}{prior_flag}")
            else:
                print("  لا توجد SettlementLines — لم تُستخدم في أي سند")

            print(f"  → avail_hist={r['avail_hist']:.2f} | avail_alloc={r['avail_alloc']:.2f}")
            if has_prior:
                print(f"  ⚠️  نعم — كانت مرتبطة بسند سابق قبل AV133 → Phase 0 أخذها بالخطأ")
            else:
                print(f"  ✅  لا — لم تكن في أي سند سابق → Phase 0 استخدمها بشكل منطقي (FIFO)")

        # ── 6) كتابة التقرير الكامل ──────────────────────────────────────────
        report = {
            'generated_at': run_dt.isoformat(),
            'av133_voucher_id': AV133_VOUCHER_ID,
            'av133_amount_cash': v_gross,
            'cutoff': cutoff_std.isoformat(),
            'pool_size': len(pool_ids),
            'summary': {
                'total_available_historical': total_available_historical,
                'total_available_build_plan': total_available_alloc,
                'difference': total_diff,
                'av133_gap': round(v_gross - total_available_alloc, 2),
                'ips_contributing_to_diff': len(diff_rows),
            },
            'diff_ips': [
                {k: v for k, v in r.items() if k != 'all_settlements'}
                for r in diff_rows
            ],
            'focus_ips': [r for r in rows if r['is_focus_ip']],
        }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(
            reports_dir,
            f"trace_av133_ip_pool_{run_dt.strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n{'='*72}")
        print(f"تم كتابة التقرير الكامل: {path}")
        print("(قراءة فقط — لم يُعدَّل أي شيء في قاعدة البيانات)")


if __name__ == '__main__':
    run()
