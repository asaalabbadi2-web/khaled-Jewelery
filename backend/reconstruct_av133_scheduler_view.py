"""
reconstruct_av133_scheduler_view.py  (v2)
==========================================
يُعيد بناء قائمة الـ IPs التي استخدمها الـ scheduler عند إنشاء AV-2026-00133.

الاكتشاف من قراءة الكود (v1):
    الـ scheduler — سواء 'days' أو 'weekday' — يحسب gross_amount عبر:
        _get_unsettled_ip_ids_up_to(safe_box_id, cutoff_dt)
    أي: بدون lower bound على التاريخ. الخطأ في v1: استخدمنا نافذة مايو19
    فقط فرأينا 8,630 بدلاً من 19,710 — والفارق 11,080 = IPs من قبل مايو19.

المنهجية الصحيحة (v2):
    لكل cutoff مقترح، نحسب:
        pool = IPs لـ safe_box 32 مع created_at ≤ cutoff
               التي لم تُسوَّ بعد (لا SettlementLine من سند approved قبل AV133)
        ثم _trim_ip_ids_to_gross(pool, 19710)
    ونقارن النتيجة بـ amount_cash=19710 للتحقق من أي cutoff يُنتج القائمة الصحيحة.

    نجرب ثلاثة cutoffs:
      C1 = 2026-05-17 23:59  (2 days delay من مايو19)
      C2 = 2026-05-18 23:59  (1 day delay — الأكثر احتمالاً)
      C3 = 2026-05-19 23:59  (نفس اليوم — بدون delay)

    الـ cutoff الذي ينتج مجموعاً ≥ 19,710 مع trim يُعطي 19,710 هو الصحيح.

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
from datetime import datetime, date as date_type, timezone, timedelta, time

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import (
    db, Voucher, SettlementLine,
    InvoicePayment, PaymentMethod,
)

AV133_VOUCHER_ID = 1649
AV133_AMOUNT     = 19710.00
SAFE_BOX_ID      = 32
EPS              = 0.005

WATCH_VOUCHER_NUMBERS = {
    'AV-2026-00133', 'AV-2026-00134', 'AV-2026-00135',
    'AV-2026-00136', 'AV-2026-00137', 'AV-2026-00138',
}

# Cutoffs مقترحة (بدون lower bound — نفس منطق _get_unsettled_ip_ids_up_to)
CUTOFF_LABELS = [
    ('C1 - delay=2d', datetime(2026, 5, 17, 23, 59, 59)),
    ('C2 - delay=1d', datetime(2026, 5, 18, 23, 59, 59)),
    ('C3 - delay=0d', datetime(2026, 5, 19, 23, 59, 59)),
]


def _get_pool_up_to(cutoff_dt: datetime) -> list[InvoicePayment]:
    """كل IPs للصندوق 32 مع created_at ≤ cutoff — نفس منطق _get_unsettled_ip_ids_up_to."""
    return (
        InvoicePayment.query
        .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
        .filter(
            PaymentMethod.default_safe_box_id == SAFE_BOX_ID,
            InvoicePayment.created_at <= cutoff_dt,
        )
        .order_by(InvoicePayment.created_at.asc(), InvoicePayment.id.asc())
        .all()
    )


def _prev_settled_before_av133(ip_ids: list[int]) -> dict[int, float]:
    """ما سوّته السندات المعتمدة قبل AV133 (voucher_id < 1649)."""
    if not ip_ids:
        return {}
    rows = (
        SettlementLine.query
        .filter(
            SettlementLine.invoice_payment_id.in_(ip_ids),
            SettlementLine.voucher_id < AV133_VOUCHER_ID,
        )
        .join(Voucher, Voucher.id == SettlementLine.voucher_id)
        .filter(Voucher.status == 'approved')
        .all()
    )
    result: dict[int, float] = defaultdict(float)
    for sl in rows:
        result[sl.invoice_payment_id] += sl.amount_settled
    return dict(result)


def _trim_to_gross(pool: list[InvoicePayment], prev_settled: dict[int, float],
                   gross: float) -> list[dict]:
    """
    محاكاة _trim_ip_ids_to_gross: FIFO أقدم أولاً، يتوقف عند gross.
    يعيد قائمة بـ {ip, available_at_time, taken} لكل IP مُختار.
    """
    result = []
    remaining = round(gross, 2)
    for ip in pool:
        if remaining <= EPS:
            break
        ip_amt = round(float(ip.amount or 0), 2)
        prior  = round(prev_settled.get(ip.id, 0.0), 2)
        avail  = round(ip_amt - prior, 2)
        if avail <= EPS:
            continue
        take = round(min(avail, remaining), 2)
        result.append({'ip': ip, 'available': avail, 'taken': take})
        remaining = round(remaining - take, 2)
    return result


def run() -> None:
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        # ── السند المرجعي ─────────────────────────────────────────────────────
        v133 = Voucher.query.get(AV133_VOUCHER_ID)
        if not v133:
            print(f"❌ Voucher {AV133_VOUCHER_ID} غير موجود.")
            return

        print("=" * 72)
        print(f"AV-2026-00133 | date={v133.date} | amount_cash={AV133_AMOUNT:.2f}")
        print("=" * 72)

        # ── السندات ذات الصلة ─────────────────────────────────────────────────
        watch_vouchers = (
            Voucher.query
            .filter(Voucher.voucher_number.in_(WATCH_VOUCHER_NUMBERS))
            .all()
        )
        voucher_by_num = {v.voucher_number: v for v in watch_vouchers}
        voucher_by_id  = {v.id: v for v in watch_vouchers}

        all_touched_v_ids = {v.id for v in watch_vouchers}
        all_sl_for_watch = (
            SettlementLine.query
            .filter(SettlementLine.voucher_id.in_(all_touched_v_ids))
            .all()
        ) if all_touched_v_ids else []
        sl_by_v: dict[int, list[SettlementLine]] = defaultdict(list)
        for sl in all_sl_for_watch:
            sl_by_v[sl.voucher_id].append(sl)

        print(f"\n── السندات ذات الصلة ──")
        for vn in sorted(WATCH_VOUCHER_NUMBERS):
            vv = voucher_by_num.get(vn)
            if vv:
                sl_total = round(sum(s.amount_settled for s in sl_by_v.get(vv.id, [])), 2)
                print(f"  {vn}: id={vv.id}, date={str(vv.date)[:10]}, "
                      f"amount_cash={float(vv.amount_cash or 0):.2f}, "
                      f"SL_total={sl_total:.2f}")

        # ── إعادة البناء لكل cutoff ───────────────────────────────────────────
        best_cutoff_label = None
        best_trimmed = None
        best_pool_total = None

        print(f"\n{'='*72}")
        print("البحث عن الـ cutoff الصحيح (الذي يُنتج gross ≥ 19,710 قبل الـ trim)")
        print(f"{'='*72}")

        for label, cutoff_dt in CUTOFF_LABELS:
            pool = _get_pool_up_to(cutoff_dt)
            pool_ids = [ip.id for ip in pool]
            prev_settled = _prev_settled_before_av133(pool_ids)
            pool_avail = round(sum(
                max(0.0, float(ip.amount or 0) - prev_settled.get(ip.id, 0.0))
                for ip in pool
            ), 2)
            trimmed = _trim_to_gross(pool, prev_settled, AV133_AMOUNT)
            trim_total = round(sum(d['taken'] for d in trimmed), 2)

            status = '✅' if abs(trim_total - AV133_AMOUNT) < 0.01 else f"⚠️  trim={trim_total:.2f}"
            print(f"  {label} (≤ {cutoff_dt.date()}): pool={len(pool)} IPs, "
                  f"pool_avail={pool_avail:.2f}, trim_total={trim_total:.2f}  {status}")

            if best_trimmed is None and pool_avail >= AV133_AMOUNT - EPS:
                best_cutoff_label = label
                best_trimmed = trimmed
                best_pool_total = pool_avail

        # إذا لم نجد cutoff يُغطي 19,710، نأخذ الأكبر
        if best_trimmed is None:
            _, last_cutoff = CUTOFF_LABELS[-1]
            pool = _get_pool_up_to(last_cutoff)
            pool_ids = [ip.id for ip in pool]
            prev_settled = _prev_settled_before_av133(pool_ids)
            best_trimmed = _trim_to_gross(pool, prev_settled, AV133_AMOUNT)
            best_pool_total = round(sum(
                max(0.0, float(ip.amount or 0) - prev_settled.get(ip.id, 0.0))
                for ip in pool
            ), 2)
            best_cutoff_label = CUTOFF_LABELS[-1][0] + ' (أوسع متاح)'

        print(f"\nالـ cutoff المستخدم للتحليل: {best_cutoff_label}")
        print(f"المجموع المتاح من الـ pool: {best_pool_total:.2f}")

        # ── عرض الـ IPs المُختارة (بعد الـ trim) ─────────────────────────────
        trimmed_ip_ids = [d['ip'].id for d in best_trimmed]
        trim_total = round(sum(d['taken'] for d in best_trimmed), 2)

        print(f"\n── قائمة الـ IPs المُجدوَلة لـ AV133 (بعد trim إلى 19,710) ──")
        print(f"{'IP':>8} {'تاريخ الإنشاء':>22} {'gross':>8} {'متاح قبل AV133':>16} {'مُجدوَل':>10}")
        print("-" * 75)
        for d in best_trimmed:
            partial = ' ← جزئي' if abs(d['taken'] - d['available']) > EPS else ''
            print(f"  IP#{d['ip'].id:>5}  {str(d['ip'].created_at)[:19]:>22} "
                  f"{float(d['ip'].amount or 0):>8.2f} {d['available']:>16.2f} "
                  f"{d['taken']:>10.2f}{partial}")
        print("-" * 75)
        print(f"  {'المجموع المُجدوَل':>50}: {trim_total:.2f} / {AV133_AMOUNT:.2f}")

        # ── مصير كل IP مُجدوَل ───────────────────────────────────────────────
        all_sl_for_trimmed = (
            SettlementLine.query
            .filter(SettlementLine.invoice_payment_id.in_(trimmed_ip_ids))
            .all()
        ) if trimmed_ip_ids else []

        all_v_ids_for_trimmed = {sl.voucher_id for sl in all_sl_for_trimmed}
        all_v_map: dict[int, Voucher] = {}
        if all_v_ids_for_trimmed:
            for vv in Voucher.query.filter(Voucher.id.in_(all_v_ids_for_trimmed)).all():
                all_v_map[vv.id] = vv

        sl_by_ip: dict[int, list[SettlementLine]] = defaultdict(list)
        for sl in all_sl_for_trimmed:
            sl_by_ip[sl.invoice_payment_id].append(sl)

        print(f"\n── مصير كل IP مُجدوَل (أين انتهى؟) ──")
        print(f"{'IP':>8} {'مُجدوَل':>10}  {'في AV133':>10}  {'سُرق':>8}  {'السارق'}")
        print("-" * 80)

        total_in_av133 = 0.0
        total_stolen   = 0.0
        stolen_ips: list[dict] = []
        recovered_ips: list[dict] = []

        for d in best_trimmed:
            ip    = d['ip']
            sched = d['taken']
            sls   = sl_by_ip.get(ip.id, [])

            in_av133 = 0.0
            in_other: dict[str, float] = {}
            for sl in sls:
                vv = all_v_map.get(sl.voucher_id)
                if not vv or vv.status != 'approved':
                    continue
                if sl.voucher_id == AV133_VOUCHER_ID:
                    in_av133 += sl.amount_settled
                else:
                    vn = vv.voucher_number or str(sl.voucher_id)
                    in_other[vn] = round(in_other.get(vn, 0.0) + sl.amount_settled, 2)

            in_av133 = round(in_av133, 2)
            stolen = round(max(0.0, sched - in_av133), 2)
            other_str = ', '.join(f"{vn}(-{a:.0f})" for vn, a in sorted(in_other.items()))

            marker = '✅' if stolen < EPS else '🔴'
            print(f"  {marker} IP#{ip.id:>5} {sched:>10.2f}  {in_av133:>10.2f}  "
                  f"{stolen:>8.2f}  {other_str or '—'}")

            total_in_av133 = round(total_in_av133 + in_av133, 2)
            total_stolen   = round(total_stolen + stolen, 2)
            if stolen > EPS:
                stolen_ips.append({'ip_id': ip.id, 'scheduled': sched,
                                   'in_av133': in_av133, 'stolen': stolen,
                                   'to': list(in_other.keys())})
            else:
                recovered_ips.append({'ip_id': ip.id, 'amount': in_av133})

        print("-" * 80)
        print(f"  {'المُجدوَل':>30}: {trim_total:.2f}")
        print(f"  {'دخل AV133 (Phase 0 أو أصلي)':>30}: {total_in_av133:.2f}")
        print(f"  {'سُرق لسندات أخرى':>30}: {total_stolen:.2f}")
        print(f"  {'فجوة AV133 الحالية':>30}: {round(AV133_AMOUNT - total_in_av133, 2):.2f}")

        # ── الخلاصة النهائية ──────────────────────────────────────────────────
        print(f"\n{'='*72}")
        print("الخلاصة: الـ IPs التي كانت حق AV133 والتي سُرقت")
        print(f"{'='*72}")
        if stolen_ips:
            for s in stolen_ips:
                partial_note = f" (جزئي: {s['scheduled']:.0f} من IP بقيمة أكبر)" \
                    if abs(s['scheduled'] - s.get('available', s['scheduled'])) > EPS else ''
                print(f"  IP#{s['ip_id']:>5} | مُجدوَل={s['scheduled']:.2f} "
                      f"| دخل AV133={s['in_av133']:.2f} "
                      f"| سُرق={s['stolen']:.2f} → {', '.join(s['to'])}"
                      f"{partial_note}")
        else:
            print("  لا توجد IPs مسروقة من ضمن الـ trimmed pool")

        if recovered_ips:
            print(f"\n  IPs استردّها Phase 0 بنجاح ({len(recovered_ips)}):")
            for r in recovered_ips:
                print(f"    IP#{r['ip_id']:>5} → {r['amount']:.2f} ريال في AV133 ✅")

        # ── هل IP1555 كان جزئياً في الـ trim؟ ───────────────────────────────
        ip1555_entry = next((d for d in best_trimmed if d['ip'].id == 1555), None)
        if ip1555_entry:
            print(f"\n{'='*72}")
            print("IP#1555 — السؤال الحاسم")
            print(f"{'='*72}")
            ip1555_full = round(float(ip1555_entry['ip'].amount or 0), 2)
            ip1555_taken = ip1555_entry['taken']
            print(f"  IP#1555 الإجمالي:    {ip1555_full:.2f}")
            print(f"  مُجدوَل لـ AV133:     {ip1555_taken:.2f}")
            if abs(ip1555_taken - ip1555_full) > EPS:
                print(f"  الفرق (جزئي):       {ip1555_full - ip1555_taken:.2f} كان سيذهب لـ AV134 بشكل طبيعي")
                print(f"  → لكن البق جعل AV134 يأخذ الـ IP كاملاً ({ip1555_full:.2f})")
                print(f"    بدلاً من {ip1555_taken:.2f} فقط")
            else:
                print(f"  → IP#1555 كان مُجدوَلاً بالكامل لـ AV133")

        # ── تقرير JSON ────────────────────────────────────────────────────────
        report = {
            'generated_at': run_dt.isoformat(),
            'av133_amount_cash': AV133_AMOUNT,
            'best_cutoff': best_cutoff_label,
            'pool_total_available': best_pool_total,
            'trim_total': trim_total,
            'trimmed_ips': [
                {'ip_id': d['ip'].id, 'created_at': str(d['ip'].created_at),
                 'available': d['available'], 'taken': d['taken']}
                for d in best_trimmed
            ],
            'total_in_av133': total_in_av133,
            'total_stolen': total_stolen,
            'av133_gap': round(AV133_AMOUNT - total_in_av133, 2),
            'stolen_ips': stolen_ips,
            'recovered_ips': recovered_ips,
        }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(
            reports_dir,
            f"reconstruct_av133_v2_{run_dt.strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        print(f"\n{'='*72}")
        print(f"التقرير: {path}")
        print("(قراءة فقط — لا تغييرات في قاعدة البيانات)")


if __name__ == '__main__':
    run()
