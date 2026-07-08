"""
investigate_av133_coverage_gap.py
===================================
تحقيق تاريخي قراءة فقط في سبب فجوة AV-2026-00133 (6,050 ريال).

السؤال المحوري:
    هل كانت InvoicePayments المؤهلة بتاريخ إنشاء AV-2026-00133 كافية
    لتغطية قيمة السند (19,710 ريال)؟ وإن لم تكن — من أين جاء الفارق؟

منهجية البحث (من الأضيق إلى الأوسع):

  الطبقة 1 — نافذة التاريخ المعتمَدة (voucher.date + 2 أيام):
      مطابقة نفس الفلتر الذي يستخدمه AllocationRepairService بعد الإصلاح.
      إذا كان الإجمالي المتاح < 19,710 فالفجوة حقيقية زمنياً.

  الطبقة 2 — النافذة الموسّعة (+ 7 أيام):
      للكشف عن دفعات قد تكون وصلت البنك قبل تسجيلها في النظام.

  الطبقة 3 — الـ IPs المُلغاة أو المحذوفة:
      هل تُوجد PaymentMethod.default_safe_box_id=32 + invoice_payment
      مرتبطة بفواتير ملغاة يمكن أن تكون "مختفت" لاحقاً؟
      → نظرة على الفواتير المرتبطة بـ IPs المستخدمة في السند.

  الطبقة 4 — مسار الصندوق الآخر:
      هل هناك PaymentMethod تُوجّه لـ safe_box_id ≠ 32 لكن يجب أن
      تكون ضمن مجدول المقاصة نفسه؟ (وسائل دفع مدى متعددة مثلاً)

  الطبقة 5 — خصائص السند نفسه:
      هل amount_cash = 19,710 منطقي كرصيد تراكمي يومي؟ أم أنه أُنشئ
      يدوياً أو بمبلغ غير مستنتج من IPs يومها؟

النتيجة:
    تقرير JSON + طباعة تشخيصية تُجيب عن السؤال المحوري وتوضح المسار.

تشغيل:
    docker cp backend/investigate_av133_coverage_gap.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/investigate_av133_coverage_gap.py
"""

from __future__ import annotations

import os
import sys
import json
import argparse
from collections import defaultdict
from datetime import datetime, date as date_type, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import (
    db, Voucher, VoucherAccountLine, SettlementLine,
    InvoicePayment, PaymentMethod, SafeBox, Invoice,
)
try:
    from models import Invoice as InvoiceModel  # alias
except ImportError:
    InvoiceModel = None

AV133_VOUCHER_ID = 1649
SAFE_BOX_ID = 32
WINDOW_DAYS_STANDARD = 2    # نفس AllocationRepairService
WINDOW_DAYS_WIDE = 7        # للفحص الموسّع
EPS = 0.005


def _dt(d) -> datetime:
    """Normalize date → datetime (end of day)."""
    if isinstance(d, datetime):
        return d
    if isinstance(d, date_type):
        return datetime(d.year, d.month, d.day, 23, 59, 59)
    return datetime.min


def run() -> None:
    with app.app_context():
        run_dt = datetime.now(timezone.utc)
        report: dict = {'generated_at': run_dt.isoformat()}

        # ── 0) السند الأساسي ─────────────────────────────────────────────────
        v = Voucher.query.get(AV133_VOUCHER_ID)
        if not v:
            print(f"❌ Voucher {AV133_VOUCHER_ID} غير موجود.")
            return

        v_date = _dt(v.date)
        v_gross = float(v.amount_cash or 0)
        cutoff_std = v_date + timedelta(days=WINDOW_DAYS_STANDARD)
        cutoff_wide = v_date + timedelta(days=WINDOW_DAYS_WIDE)

        print("=" * 70)
        print(f"AV-2026-00133 (voucher_id={AV133_VOUCHER_ID})")
        print(f"  voucher_number : {v.voucher_number}")
        print(f"  status         : {v.status}")
        print(f"  date           : {v.date}")
        print(f"  amount_cash    : {v_gross:.2f} ريال")
        print(f"  نافذة معيارية  : ≤ {cutoff_std.strftime('%Y-%m-%d')}")
        print(f"  نافذة موسّعة   : ≤ {cutoff_wide.strftime('%Y-%m-%d')}")
        print("=" * 70)

        report['voucher'] = {
            'id': AV133_VOUCHER_ID,
            'number': v.voucher_number,
            'status': v.status,
            'date': str(v.date),
            'amount_cash': v_gross,
            'cutoff_standard': cutoff_std.isoformat(),
            'cutoff_wide': cutoff_wide.isoformat(),
        }

        # ── SettlementLines الحالية لهذا السند ───────────────────────────────
        current_sl = SettlementLine.query.filter_by(voucher_id=AV133_VOUCHER_ID).all()
        current_sl_total = round(sum(s.amount_settled for s in current_sl), 2)
        current_gap = round(v_gross - current_sl_total, 2)

        print(f"\nحالة SettlementLine الراهنة:")
        print(f"  عدد السطور    : {len(current_sl)}")
        print(f"  مجموع المُسوَّى : {current_sl_total:.2f}")
        print(f"  الفجوة الراهنة : {current_gap:.2f}  "
              f"({'مكتمل' if abs(current_gap) < 0.01 else 'فجوة' if current_gap > 0 else 'تغطية زائدة'})")
        for sl in sorted(current_sl, key=lambda x: x.invoice_payment_id):
            ip = InvoicePayment.query.get(sl.invoice_payment_id)
            ip_dt = ip.created_at.strftime('%Y-%m-%d') if ip and ip.created_at else '؟'
            flag = ' ⚠️ (يوليو)' if ip and ip.created_at and ip.created_at > cutoff_std else ''
            print(f"    IP#{sl.invoice_payment_id:>6} (created={ip_dt}) "
                  f"→ settled={sl.amount_settled:.2f}{flag}")

        report['current_settlement'] = {
            'line_count': len(current_sl),
            'total': current_sl_total,
            'gap': current_gap,
            'lines': [
                {
                    'sl_id': sl.id,
                    'ip_id': sl.invoice_payment_id,
                    'amount_settled': sl.amount_settled,
                    'ip_created_at': (
                        InvoicePayment.query.get(sl.invoice_payment_id).created_at.isoformat()
                        if InvoicePayment.query.get(sl.invoice_payment_id) and
                           InvoicePayment.query.get(sl.invoice_payment_id).created_at
                        else None
                    ),
                }
                for sl in current_sl
            ],
        }

        # ── 1) كل IPs الصندوق (مُرتّبة زمنياً) ─────────────────────────────
        all_ips = (
            InvoicePayment.query
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(PaymentMethod.default_safe_box_id == SAFE_BOX_ID)
            .order_by(InvoicePayment.created_at.asc())
            .all()
        )

        # حساب المُسوَّى السابق لكل IP من السندات المعتمَدة الأقدم من AV133
        # (أي ما "استهلك" قبل أن يجيء دور AV133 في FIFO)
        sl_by_ip: dict[int, list[SettlementLine]] = defaultdict(list)
        all_sl_for_ips = (
            SettlementLine.query
            .filter(SettlementLine.invoice_payment_id.in_([ip.id for ip in all_ips]))
            .all()
        ) if all_ips else []
        for sl in all_sl_for_ips:
            sl_by_ip[sl.invoice_payment_id].append(sl)

        # الرصيد الخالي (unsettled) لكل IP بحسب الوضع الراهن
        # — هذا يتضمن تأثير Phase 0 (ستُبدي IPs يوليو كمُستهلَكة)
        # نحتاج مقارنة نظيفة: what would have been available at v_date
        # assuming ONLY settlements from vouchers dated before v_date

        # السندات الأقدم: approved + date < AV133_date
        earlier_voucher_ids: set[int] = {
            sl.voucher_id for sl in all_sl_for_ips
            if sl.voucher_id != AV133_VOUCHER_ID
        }
        earlier_voucher_dates: dict[int, datetime] = {}
        if earlier_voucher_ids:
            for ev in Voucher.query.filter(Voucher.id.in_(earlier_voucher_ids)).all():
                earlier_voucher_dates[ev.id] = _dt(ev.date)

        # لكل IP: ما المُسوَّى منها فعلياً بواسطة سندات أقدم من AV133 (approved)?
        def prev_settled_before_av133(ip_id: int) -> float:
            total = 0.0
            for sl in sl_by_ip.get(ip_id, []):
                if sl.voucher_id == AV133_VOUCHER_ID:
                    continue  # نتجاهل AV133 نفسها
                v_sl = Voucher.query.get(sl.voucher_id)
                if v_sl and v_sl.status == 'approved' and _dt(v_sl.date) < v_date:
                    total += sl.amount_settled
            return round(total, 2)

        # ── الطبقة 1: نافذة معيارية (+ 2 أيام) ──────────────────────────────
        print(f"\n{'='*70}")
        print(f"الطبقة 1: IPs مؤهلة بالنافذة المعيارية (created_at ≤ {cutoff_std.strftime('%Y-%m-%d')})")
        print(f"{'='*70}")

        def analyze_pool(cutoff: datetime, label: str) -> dict:
            pool = [ip for ip in all_ips if (ip.created_at or datetime.min) <= cutoff]
            total_gross = round(sum(float(ip.amount or 0) for ip in pool), 2)
            available_rows = []
            total_available = 0.0
            for ip in pool:
                already = prev_settled_before_av133(ip.id)
                remaining = round(float(ip.amount or 0) - already, 2)
                available_rows.append({
                    'ip_id': ip.id,
                    'created_at': ip.created_at.isoformat() if ip.created_at else None,
                    'amount': float(ip.amount or 0),
                    'settled_by_prior_vouchers': already,
                    'available_for_av133': remaining,
                })
                if remaining > EPS:
                    total_available += remaining
            total_available = round(total_available, 2)
            gap_coverage = round(v_gross - total_available, 2)

            print(f"  عدد IPs في النافذة            : {len(pool)}")
            print(f"  إجمالي قيم IPs (gross)         : {total_gross:.2f}")
            print(f"  إجمالي المُسوَّى مسبقاً          : {round(total_gross - total_available, 2):.2f}")
            print(f"  المتاح فعلاً لـ AV133          : {total_available:.2f}")
            print(f"  قيمة AV133 (amount_cash)       : {v_gross:.2f}")
            if gap_coverage <= 0:
                print(f"  ✅ التغطية كافية — كان يمكن تسوية AV133 بالكامل من هذه النافذة")
            else:
                print(f"  ❌ فجوة = {gap_coverage:.2f} ريال — التغطية غير كافية من هذه النافذة")

            return {
                'label': label,
                'cutoff': cutoff.isoformat(),
                'ip_count': len(pool),
                'total_gross': total_gross,
                'total_available': total_available,
                'gap': gap_coverage,
                'verdict': 'sufficient' if gap_coverage <= 0 else 'insufficient',
                'rows': available_rows,
            }

        layer1 = analyze_pool(cutoff_std, 'standard_window')
        report['layer1_standard_window'] = layer1

        # ── الطبقة 2: نافذة موسّعة (+ 7 أيام) ───────────────────────────────
        print(f"\n{'='*70}")
        print(f"الطبقة 2: IPs مؤهلة بالنافذة الموسّعة (created_at ≤ {cutoff_wide.strftime('%Y-%m-%d')})")
        print(f"{'='*70}")
        layer2 = analyze_pool(cutoff_wide, 'wide_window_7d')
        report['layer2_wide_window'] = layer2

        # ── الطبقة 3: وسائل دفع تُوجَّه لصناديق أخرى ────────────────────────
        print(f"\n{'='*70}")
        print("الطبقة 3: وسائل دفع (مدى) تُوجَّه لصناديق مقاصة أخرى")
        print(f"{'='*70}")
        # هل هناك PaymentMethod مماثلة (مدى) لكن default_safe_box_id ≠ 32؟
        # نبحث عن IPs في نفس الفترة على صناديق أخرى
        other_sb_pms = (
            PaymentMethod.query
            .filter(PaymentMethod.default_safe_box_id != SAFE_BOX_ID)
            .all()
        )
        other_sb_ips_in_window = []
        for pm in other_sb_pms:
            ips_pm = (
                InvoicePayment.query
                .filter(
                    InvoicePayment.payment_method_id == pm.id,
                    InvoicePayment.created_at <= cutoff_std,
                )
                .order_by(InvoicePayment.created_at.desc())
                .limit(5)
                .all()
            )
            for ip in ips_pm:
                other_sb_ips_in_window.append({
                    'pm_id': pm.id,
                    'pm_name': getattr(pm, 'name', None) or getattr(pm, 'label', None),
                    'safe_box_id': pm.default_safe_box_id,
                    'ip_id': ip.id,
                    'amount': float(ip.amount or 0),
                    'created_at': ip.created_at.isoformat() if ip.created_at else None,
                })

        if other_sb_ips_in_window:
            print(f"  وُجدت وسائل دفع على صناديق أخرى بنفس فترة AV133 ({len(other_sb_ips_in_window)} IP):")
            sb_totals: dict = defaultdict(float)
            for r in other_sb_ips_in_window:
                sb_totals[r['safe_box_id']] += r['amount']
                print(f"    IP#{r['ip_id']} | pm={r['pm_name']} | sb={r['safe_box_id']} "
                      f"| amount={r['amount']:.2f} | {r['created_at']}")
            print("  → إذا كانت وسيلة دفع مدى خُصِّصت لصندوق آخر بالخطأ، قد يكون هذا مصدر الفجوة.")
        else:
            print("  لا توجد وسائل دفع أخرى بنفس الفترة — هذا المسار مستبعَد.")
        report['layer3_other_safe_boxes'] = other_sb_ips_in_window

        # ── الطبقة 4: هل نشأ السند بمبلغ أكبر من المقبوضات الفعلية؟ ─────────
        print(f"\n{'='*70}")
        print("الطبقة 4: مقارنة amount_cash بإجمالي قبضات المجدول ليوم AV133")
        print(f"{'='*70}")

        # ما مجموع IPs التي تخص نفس يوم السند (window = يوم واحد بعد)
        day_start = v_date.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        day_end = v_date + timedelta(days=1)
        day_ips = [
            ip for ip in all_ips
            if ip.created_at and day_start <= ip.created_at <= day_end
        ]
        day_total = round(sum(float(ip.amount or 0) for ip in day_ips), 2)
        print(f"  IPs في نطاق [{day_start.date()} → {day_end.date()}]: {len(day_ips)} دفعة | مجموع={day_total:.2f}")
        print(f"  amount_cash للسند: {v_gross:.2f}")
        if abs(day_total - v_gross) < 1.0:
            print("  ✅ التطابق ممتاز — مجموع IPs اليوم = amount_cash تقريباً")
        else:
            diff = round(v_gross - day_total, 2)
            print(f"  {'⚠️' if abs(diff) > 0.01 else '✅'} الفارق = {diff:.2f} "
                  f"({'السند أكبر' if diff > 0 else 'السند أصغر'} من IPs اليوم)")

        report['layer4_daily_match'] = {
            'day_start': day_start.isoformat(),
            'day_end': day_end.isoformat(),
            'ip_count': len(day_ips),
            'day_ip_total': day_total,
            'voucher_amount_cash': v_gross,
            'diff': round(v_gross - day_total, 2),
        }

        # ── الطبقة 5: هل كان amount_cash للسند خاطئاً منذ البداية؟ ──────────
        # "voucher_amount_error": السند أُنشئ بمبلغ أكبر مما تُنتجه IPs يومه —
        # هذا مختلف عن genuine_accounting_gap (التي تعني cash وصل البنك لكن
        # IP مقابله غير مسجّل).
        # هنا: المجدول قد يكون حسب amount_cash من رصيد الحساب بدلاً من
        # مجموع IPs، مما يُنشئ سنداً أكبر من الممكن تسويته.
        print(f"\n{'='*70}")
        print("الطبقة 5: مقارنة amount_cash بما يجب أن يُنتجه المجدول من IPs")
        print(f"{'='*70}")

        # المجموع المتوقع = IPs اليوم فقط (لم تُسوَّ بسندات سابقة)
        # الفكرة: إذا شغّل المجدول بشكل صحيح، يجب أن يكون amount_cash
        # = مجموع IPs التي وصلت في نافذة التسوية (created_at بين
        # آخر سند ويوم هذا السند) وغير مُسوَّاة بعد.
        # نحسب هذا باستخدام prev_settled_before_av133 المُعرَّفة سابقاً:
        day_pool_std = [ip for ip in all_ips if (ip.created_at or datetime.min) <= cutoff_std]
        expected_gross_from_ips = round(
            sum(
                max(0.0, round(float(ip.amount or 0) - prev_settled_before_av133(ip.id), 2))
                for ip in day_pool_std
            ), 2
        )
        voucher_excess = round(v_gross - expected_gross_from_ips, 2)

        print(f"  المجموع المتاح من IPs (بعد خصم المُسوَّى مسبقاً): {expected_gross_from_ips:.2f}")
        print(f"  amount_cash للسند:                                  {v_gross:.2f}")
        if abs(voucher_excess) < 1.0:
            print(f"  ✅ amount_cash يتطابق مع IPs المتاحة — مبلغ السند صحيح")
            voucher_amount_verdict = 'amount_matches_ips'
        elif voucher_excess > 1.0:
            print(f"  ❌ amount_cash أكبر من IPs المتاحة بـ {voucher_excess:.2f} ريال")
            print(f"     → السند أُنشئ بمبلغ لا يعكس IPs مسجّلة — احتمال voucher_amount_error")
            print(f"     السبب المحتمل: المجدول استخدم رصيد الحساب بدل مجموع IPs،")
            print(f"     أو تعديل يدوي على amount_cash، أو IP لا تنتمي لهذا الصندوق.")
            voucher_amount_verdict = 'amount_exceeds_ips'
        else:
            print(f"  ⚠️  amount_cash أصغر من IPs المتاحة ({-voucher_excess:.2f} ريال زيادة) — غير متوقع")
            voucher_amount_verdict = 'amount_below_ips'

        report['layer5_voucher_amount_check'] = {
            'expected_gross_from_ips': expected_gross_from_ips,
            'voucher_amount_cash': v_gross,
            'excess': voucher_excess,
            'verdict': voucher_amount_verdict,
        }

        # ── الخلاصة التشخيصية ────────────────────────────────────────────────
        print(f"\n{'='*70}")
        print("الخلاصة التشخيصية")
        print(f"{'='*70}")
        gap = layer1['gap']  # الفجوة بالنافذة المعيارية

        # تحديد التصنيف النهائي (من الأكثر تحديداً إلى الأعم)
        verdicts = []
        final_verdict: str

        if gap <= 0:
            final_verdict = 'ip_ordering_error'
            verdicts.append(
                "✅ [L1] IPs مايو كانت كافية لتغطية AV133 كاملاً — "
                "الفجوة نتجت من خطأ في ترتيب/فلترة Phase 0 وليس من نقص حقيقي في الدفعات."
            )
            verdicts.append(
                "→ الإصلاح: بعد حذف السطور اليوليوية، شغّل repair_july_vouchers_dry_run.py —"
                " سيستخدم IPs مايو المتاحة ويسوّي AV133 بالكامل. لا قرار محاسبي مطلوب."
            )

        elif layer2['gap'] <= 0:
            final_verdict = 'timing_gap'
            verdicts.append(
                f"⚠️  [L1] IPs في النافذة المعيارية (+ 2 أيام) غير كافية (فجوة {gap:.2f})، "
                f"لكن النافذة الموسّعة (+ 7 أيام) تغطّيها."
            )
            verdicts.append(
                "→ دفعات وصلت البنك قبل تسجيلها في النظام. "
                "راجع IPs في الأيام 3-7 بعد تاريخ السند — قد يكفي توسيع حد التاريخ في AllocationRepairService."
            )

        elif voucher_amount_verdict == 'amount_exceeds_ips':
            final_verdict = 'voucher_amount_error'
            verdicts.append(
                f"❌ [L5] مبلغ السند ({v_gross:.2f}) أكبر من مجموع IPs المتاحة "
                f"({expected_gross_from_ips:.2f}) بفارق {voucher_excess:.2f} ريال."
            )
            verdicts.append(
                "→ الـ IPs موجودة وترتيبها صحيح، لكن مبلغ السند نفسه مبالَغ فيه. "
                "المجدول استخدم مصدراً مختلفاً لـ amount_cash (رصيد الحساب أو تعديل يدوي)."
            )
            verdicts.append(
                "→ التحقيق: افحص كيف حُدِّد amount_cash عند إنشاء السند "
                "(clearing_settlement_scheduler.py أو وُجد تعديل يدوي في سجل التدقيق)."
            )
            if other_sb_ips_in_window:
                verdicts.append(
                    f"→ [L3] احتمال مساهم: وسائل دفع على صناديق أخرى قد تكون جزءاً من "
                    f"amount_cash لكنها لا تُولّد IPs في الصندوق 32."
                )

        else:
            final_verdict = 'genuine_accounting_gap'
            verdicts.append(
                f"❌ [L1+L2+L5] الفجوة حقيقية ({gap:.2f} ريال) — "
                f"cash وصل البنك (مبلغ السند صحيح) لكن لا IP مقابلة في النظام."
            )
            verdicts.append(
                "→ الاحتمالات: (أ) IP محذوفة أو ملغاة بعد إنشاء السند، "
                "(ب) دفعة وردت عبر قناة خارجية لم تُسجَّل كـ InvoicePayment، "
                "(ج) وسيلة دفع مُوجَّهة لصندوق خاطئ."
            )
            if other_sb_ips_in_window:
                verdicts.append(
                    f"→ [L3] وُجدت وسائل دفع على صناديق أخرى — "
                    f"تحقق إذا كانت إحداها تخص نفس مجدول المقاصة."
                )

        print(f"  التصنيف النهائي: {final_verdict}")
        print()
        for v_line in verdicts:
            print(f"  {v_line}")

        report['diagnostic_summary'] = {
            'gap_standard_window': layer1['gap'],
            'gap_wide_window': layer2['gap'],
            'voucher_amount_excess': voucher_excess,
            'verdict': final_verdict,
            'verdicts': verdicts,
        }

        # ── كتابة التقرير ────────────────────────────────────────────────────
        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(
            reports_dir,
            f"investigate_av133_coverage_gap_{run_dt.strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

        print(f"\nتم كتابة التقرير الكامل: {path}")
        print("(قراءة فقط — لم يُعدَّل أي شيء في قاعدة البيانات)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.parse_args()
    run()
