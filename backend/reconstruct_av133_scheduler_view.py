"""
reconstruct_av133_scheduler_view.py
=====================================
يُعيد بناء قائمة day_ip_ids التي استخدمها الـ scheduler عند إنشاء AV-2026-00133.

السؤال الجوهري:
    ما هي الـ IPs التي خرجت فعلاً من:
        _get_unsettled_ip_ids_for_day(32, 2026-05-19 00:00, 2026-05-19 23:59)
    ثم طُبِّق عليها:
        _trim_ip_ids_to_gross(day_ip_ids, 19710)
    في اللحظة التي أنشأ فيها الـ scheduler AV-2026-00133؟

المنهجية:
    "حالة قاعدة البيانات قبل AV133" = SettlementLines من سندات approved
    مع id < AV133_VOUCHER_ID (1649) — بروكسي زمني للحالة قبل الإنشاء.

    بعد تحديد قائمة الـ IPs المُجدوَلة لـ AV133:
        → أي منها انتهى في AV133 فعلاً؟ (SettlementLines حالية)
        → أي منها "سُرق" بواسطة AV134/AV135/...؟
        → ما هي الـ 6,050 ريال الأخيرة (الفجوة) من تلك القائمة؟

    السؤال الإضافي:
        هل AV134 لنفس الـ safe_box (32)؟
        → يكشف إذا كان الـ scheduler أنشأ سنداً ثانياً لنفس اليوم/الصندوق.

قراءة فقط — لا كتابة في قاعدة البيانات.

تشغيل:
    docker cp backend/reconstruct_av133_scheduler_view.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/reconstruct_av133_scheduler_view.py
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
from sqlalchemy import func

AV133_VOUCHER_ID = 1649
AV133_AMOUNT     = 19710.00
SAFE_BOX_ID      = 32

# نافذة مايو19 (يوم كامل)
DAY_START = datetime(2026, 5, 19, 0, 0, 0)
DAY_END   = datetime(2026, 5, 19, 23, 59, 59)

# السندات التي تريد تتبعها (AV133 والسندات التي قد تكون "أخذت" IPs)
WATCH_VOUCHER_NUMBERS = {
    'AV-2026-00133', 'AV-2026-00134', 'AV-2026-00135',
    'AV-2026-00136', 'AV-2026-00137', 'AV-2026-00138',
}

EPS = 0.005


def _dt(d) -> datetime:
    if isinstance(d, datetime):
        return d
    if isinstance(d, date_type):
        return datetime(d.year, d.month, d.day, 23, 59, 59)
    return datetime.min


def run() -> None:
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        # ── 0) السند المرجعي ─────────────────────────────────────────────────
        v133 = Voucher.query.get(AV133_VOUCHER_ID)
        if not v133:
            print(f"❌ Voucher {AV133_VOUCHER_ID} غير موجود.")
            return

        print("=" * 72)
        print(f"AV-2026-00133 | date={v133.date} | amount_cash={AV133_AMOUNT:.2f}")
        print(f"نافذة اليوم: {DAY_START.date()} 00:00 → 23:59")
        print("=" * 72)

        # ── 1) السندات ذات الصلة ─────────────────────────────────────────────
        watch_vouchers = (
            Voucher.query
            .filter(Voucher.voucher_number.in_(WATCH_VOUCHER_NUMBERS))
            .all()
        )
        voucher_by_num = {v.voucher_number: v for v in watch_vouchers}
        voucher_by_id  = {v.id: v for v in watch_vouchers}

        # معلومات AV134: هل هو نفس الـ safe_box؟
        av134 = voucher_by_num.get('AV-2026-00134')
        print(f"\n── السندات ذات الصلة ──")
        for vn in sorted(WATCH_VOUCHER_NUMBERS):
            vv = voucher_by_num.get(vn)
            if vv:
                print(f"  {vn}: id={vv.id}, date={str(vv.date)[:10]}, "
                      f"amount_cash={float(vv.amount_cash or 0):.2f}, "
                      f"status={vv.status}, "
                      f"clearing_safe_box={getattr(vv, 'clearing_safe_box_id', '?')}")
            else:
                print(f"  {vn}: غير موجود")

        # ── 2) IPs مايو19 للصندوق 32 ─────────────────────────────────────────
        day_ips = (
            InvoicePayment.query
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(
                PaymentMethod.default_safe_box_id == SAFE_BOX_ID,
                InvoicePayment.created_at >= DAY_START,
                InvoicePayment.created_at <= DAY_END,
            )
            .order_by(InvoicePayment.created_at.asc(), InvoicePayment.id.asc())
            .all()
        )
        day_ip_ids = [ip.id for ip in day_ips]

        print(f"\n── IPs مايو19 للصندوق {SAFE_BOX_ID} ──")
        print(f"  العدد: {len(day_ips)}")
        print(f"  المجموع الإجمالي: {sum(float(ip.amount or 0) for ip in day_ips):.2f} ريال")

        # ── 3) حالة التسوية قبل إنشاء AV133 ─────────────────────────────────
        # "قبل AV133" = SettlementLines من سندات approved مع voucher_id < 1649
        if day_ip_ids:
            pre_sl = (
                SettlementLine.query
                .filter(
                    SettlementLine.invoice_payment_id.in_(day_ip_ids),
                    SettlementLine.voucher_id < AV133_VOUCHER_ID,
                )
                .join(Voucher, Voucher.id == SettlementLine.voucher_id)
                .filter(Voucher.status == 'approved')
                .all()
            )
        else:
            pre_sl = []

        pre_settled_map: dict[int, float] = defaultdict(float)
        for sl in pre_sl:
            pre_settled_map[sl.invoice_payment_id] += sl.amount_settled

        # ── 4) حساب المتاح لكل IP يوم مايو19 ────────────────────────────────
        ip_data = []
        for ip in day_ips:
            gross  = round(float(ip.amount or 0), 2)
            prior  = round(pre_settled_map.get(ip.id, 0.0), 2)
            avail  = round(gross - prior, 2)
            ip_data.append({
                'ip': ip,
                'gross': gross,
                'prior_settled': prior,
                'available_at_av133_time': avail,
            })

        # IPs التي كانت متاحة فعلاً (unsettled) عند إنشاء AV133
        available_data = [d for d in ip_data if d['available_at_av133_time'] > EPS]
        total_available = round(sum(d['available_at_av133_time'] for d in available_data), 2)

        print(f"\n── حالة يوم مايو19 عند إنشاء AV133 ──")
        print(f"  IPs غير مُسوَّاة بعد: {len(available_data)} من {len(day_ips)}")
        print(f"  المجموع المتاح:       {total_available:.2f} ريال")
        print(f"  amount_cash (AV133):  {AV133_AMOUNT:.2f} ريال")

        # ── 5) محاكاة _trim_ip_ids_to_gross(day_ip_ids, 19710) ──────────────
        # FIFO: oldest first (مرتَّبة بالفعل)
        trimmed: list[dict] = []
        running = 0.0
        for d in available_data:
            if running >= AV133_AMOUNT - EPS:
                break
            take = min(d['available_at_av133_time'], AV133_AMOUNT - running)
            take = round(take, 2)
            trimmed.append({**d, 'scheduled_amount': take})
            running = round(running + take, 2)

        print(f"\n── قائمة day_ip_ids المُعاد بناؤها (بعد _trim_ip_ids_to_gross) ──")
        print(f"{'IP':>8} {'created_at':>20} {'gross':>8} {'prior':>8} "
              f"{'avail':>8} {'scheduled':>10}  {'ملاحظة'}")
        print("-" * 90)
        total_scheduled = 0.0
        for d in trimmed:
            ip = d['ip']
            partial = '← جزئي' if abs(d['scheduled_amount'] - d['available_at_av133_time']) > EPS else ''
            print(f"  IP#{ip.id:>5} {str(ip.created_at)[:19]:>20} {d['gross']:>8.2f} "
                  f"{d['prior_settled']:>8.2f} {d['available_at_av133_time']:>8.2f} "
                  f"{d['scheduled_amount']:>10.2f}  {partial}")
            total_scheduled = round(total_scheduled + d['scheduled_amount'], 2)
        print("-" * 90)
        print(f"{'المجموع المُجدوَل':>60}: {total_scheduled:.2f}")
        print(f"{'amount_cash AV133':>60}: {AV133_AMOUNT:.2f}")
        print(f"{'الفارق (carry-forward أو فارق تقريب)':>60}: {round(AV133_AMOUNT - total_scheduled, 2):.2f}")

        # ── 6) مصير كل IP مُجدوَل: أين انتهى؟ ──────────────────────────────
        trimmed_ip_ids = [d['ip'].id for d in trimmed]

        all_sl_for_trimmed = (
            SettlementLine.query
            .filter(SettlementLine.invoice_payment_id.in_(trimmed_ip_ids))
            .all()
        ) if trimmed_ip_ids else []

        # معلومات جميع السندات التي مسّت هذه الـ IPs
        all_voucher_ids = {sl.voucher_id for sl in all_sl_for_trimmed}
        all_vouchers_map: dict[int, Voucher] = {}
        if all_voucher_ids:
            for vv in Voucher.query.filter(Voucher.id.in_(all_voucher_ids)).all():
                all_vouchers_map[vv.id] = vv

        sl_by_ip: dict[int, list[SettlementLine]] = defaultdict(list)
        for sl in all_sl_for_trimmed:
            sl_by_ip[sl.invoice_payment_id].append(sl)

        print(f"\n── مصير كل IP مُجدوَل لـ AV133 ──")
        print(f"{'IP':>8} {'scheduled':>10}  {'في AV133':>10}  {'في سند آخر':>12}  {'السرقة':>8}  {'المسروق لـ'}")
        print("-" * 90)

        total_in_av133   = 0.0
        total_stolen     = 0.0
        stolen_breakdown = []  # (ip_id, amount, voucher_number)

        for d in trimmed:
            ip     = d['ip']
            sched  = d['scheduled_amount']
            ip_sls = sl_by_ip.get(ip.id, [])

            in_av133 = 0.0
            in_other = {}   # voucher_number → amount

            for sl in ip_sls:
                vv = all_vouchers_map.get(sl.voucher_id)
                if not vv or vv.status != 'approved':
                    continue
                if sl.voucher_id == AV133_VOUCHER_ID:
                    in_av133 += sl.amount_settled
                else:
                    vn = vv.voucher_number or str(sl.voucher_id)
                    in_other[vn] = round(in_other.get(vn, 0.0) + sl.amount_settled, 2)

            in_av133 = round(in_av133, 2)
            in_other_total = round(sum(in_other.values()), 2)

            # الجزء المُجدوَل الذي لم يدخل AV133
            stolen = round(max(0.0, sched - in_av133), 2)
            other_str = ', '.join(f"{vn}(-{amt:.0f})" for vn, amt in sorted(in_other.items()))

            print(f"  IP#{ip.id:>5} {sched:>10.2f}  {in_av133:>10.2f}  {in_other_total:>12.2f}  "
                  f"{stolen:>8.2f}  {other_str}")

            total_in_av133 = round(total_in_av133 + in_av133, 2)
            total_stolen   = round(total_stolen + stolen, 2)
            if stolen > EPS:
                stolen_breakdown.append({
                    'ip_id': ip.id,
                    'scheduled': sched,
                    'in_av133': in_av133,
                    'stolen': stolen,
                    'stolen_to': list(in_other.keys()),
                })

        print("-" * 90)
        print(f"{'المجدوَل':>20}: {total_scheduled:.2f}")
        print(f"{'دخل AV133 فعلاً':>20}: {total_in_av133:.2f}")
        print(f"{'سُرق لسندات أخرى':>20}: {total_stolen:.2f}")
        print(f"{'فجوة AV133 الحالية':>20}: {round(AV133_AMOUNT - total_in_av133, 2):.2f}")

        # ── 7) الملخص: من أين جاءت الـ 6,050؟ ───────────────────────────────
        print(f"\n{'='*72}")
        print("الـ IPs التي تُشكّل فجوة AV133 (المسروقة أو غير المغطاة):")
        print(f"{'='*72}")
        if stolen_breakdown:
            for s in stolen_breakdown:
                print(f"  IP#{s['ip_id']:>5} | مُجدوَل={s['scheduled']:.2f} | "
                      f"دخل AV133={s['in_av133']:.2f} | "
                      f"سُرق={s['stolen']:.2f} → {', '.join(s['stolen_to'])}")
        else:
            print("  لا توجد IPs مسروقة — الفجوة من عدم كفاية الـ pool")

        # ── 8) كشف AV134: هل هو لنفس الـ safe_box؟ ─────────────────────────
        print(f"\n{'='*72}")
        print("AV-2026-00134: هل هو لنفس الصندوق 32؟")
        print(f"{'='*72}")
        if av134:
            csb = getattr(av134, 'clearing_safe_box_id', None)
            print(f"  AV134 id={av134.id} | date={str(av134.date)[:10]} | "
                  f"amount_cash={float(av134.amount_cash or 0):.2f} | "
                  f"clearing_safe_box_id={csb}")
            if csb == SAFE_BOX_ID:
                print(f"  ⚠️  نعم — نفس الصندوق ({SAFE_BOX_ID})")
                print(f"  → الـ scheduler أنشأ سنداً ثانياً لنفس اليوم/الصندوق")
                print(f"  → السبب: AV133 أنشئ بفجوة (SettlementLines = 0) → الجدولة لم تتوقف")
            elif csb is None:
                print(f"  ❓ clearing_safe_box_id = None — تحقق من اسم الحقل في نموذج Voucher")
            else:
                print(f"  ✅ لا — صندوق مختلف ({csb})")
                print(f"  → AV133 وAV134 لصندوقَين مختلفَين → الـ IPs المشتركة عبر pool مختلف")
        else:
            print(f"  ❓ AV-2026-00134 غير موجود في قاعدة البيانات")

        # ── 9) تقرير JSON ─────────────────────────────────────────────────────
        report = {
            'generated_at': run_dt.isoformat(),
            'av133_voucher_id': AV133_VOUCHER_ID,
            'av133_amount_cash': AV133_AMOUNT,
            'safe_box_id': SAFE_BOX_ID,
            'day_window': {'start': str(DAY_START), 'end': str(DAY_END)},
            'day_pool_size': len(day_ips),
            'day_pool_total_gross': round(sum(float(ip.amount or 0) for ip in day_ips), 2),
            'available_at_av133_time': total_available,
            'total_scheduled': total_scheduled,
            'total_entered_av133': total_in_av133,
            'total_stolen': total_stolen,
            'av133_gap': round(AV133_AMOUNT - total_in_av133, 2),
            'trimmed_ip_ids': trimmed_ip_ids,
            'stolen_breakdown': stolen_breakdown,
            'av134_safe_box_id': getattr(av134, 'clearing_safe_box_id', None) if av134 else None,
        }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(
            reports_dir,
            f"reconstruct_av133_scheduler_{run_dt.strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n{'='*72}")
        print(f"تم كتابة التقرير: {path}")
        print("(قراءة فقط — لا تغييرات في قاعدة البيانات)")


if __name__ == '__main__':
    run()
