"""
reconcile_clearing_settlement_coverage.py
==========================================
تقرير "truth reconciliation" قراءة فقط بين ما دخل فعلياً عبر دفعات وسيلة دفع
معيّنة (InvoicePayment) وما تمت تسويته فعلياً (SettlementLine)، لخزينة مقاصة
محدّدة. لا يحسب رصيداً جارياً متراكماً، ولا يصدر حكماً نهائياً (bug / legacy /
timing) — فقط mapping + diff خام على ثلاث طبقات:

  1. per_invoice_payment: لكل دفعة، المبلغ، المُغطّى عبر SettlementLine،
     المتبقي، وتصنيف تغطية ميكانيكي بحت (full / partial / none) + أي سندات
     غطّتها فعلياً.
  2. per_day: تجميع نفس البيانات على مستوى يوم إنشاء الدفعة (created_at).
  3. per_voucher: لكل سند تسوية لمس حساب هذه الخزينة، المبلغ المُقيَّد فعلياً
     (amount_cash) مقابل إجمالي SettlementLine التي أنشأها هو نفسه — أي فرق
     هنا يعني سنداً سحب نقداً أكثر مما وثّقه عبر SettlementLine (self-consistency
     gap)، بصرف النظر عن أي يوم أو رصيد متراكم.

لا تعديل بيانات إطلاقاً (لا commit، لا rollback لأي تغيير لأنه لا يوجد تغيير).

تشغيل (على نفس الحاوية التي تشغّل قاعدة بيانات الإنتاج):
    docker cp backend/reconcile_clearing_settlement_coverage.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/reconcile_clearing_settlement_coverage.py --safe-box-id 32
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, InvoicePayment, PaymentMethod, SettlementLine, Voucher, VoucherAccountLine, SafeBox

EPS = 0.005


def run(safe_box_id: int):
    with app.app_context():
        run_dt = datetime.now(timezone.utc)

        safe_box = SafeBox.query.get(safe_box_id)
        if not safe_box:
            print(f"لم يُعثر على صندوق مقاصة بمعرّف {safe_box_id}")
            return

        account_id = getattr(safe_box, 'account_id', None)

        # ── 1) كل الدفعات الموجّهة لهذه الخزينة عبر default_safe_box_id ──────
        ips = (
            InvoicePayment.query
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(PaymentMethod.default_safe_box_id == safe_box_id)
            .order_by(InvoicePayment.created_at.asc())
            .all()
        )
        ip_ids = [ip.id for ip in ips]

        sl_rows_for_ips = (
            SettlementLine.query.filter(SettlementLine.invoice_payment_id.in_(ip_ids)).all()
            if ip_ids else []
        )
        sl_by_ip = defaultdict(list)
        for sl in sl_rows_for_ips:
            sl_by_ip[sl.invoice_payment_id].append(sl)

        # حالة كل سند لمس أي IP هنا — سطر SettlementLine تابع لسند ملغى/مرفوض
        # لا يُحسَب كتغطية حقيقية، يطابق نفس فلتر status='approved' المُضاف
        # حديثاً لـ _prev_settled داخل _create_clearing_settlement_voucher.
        _touched_voucher_ids = {sl.voucher_id for sl in sl_rows_for_ips}
        voucher_status_by_id = {
            v.id: v.status
            for v in Voucher.query.filter(Voucher.id.in_(_touched_voucher_ids)).all()
        } if _touched_voucher_ids else {}

        ip_report = []
        for ip in ips:
            all_sl = sl_by_ip.get(ip.id, [])
            approved_sl = [sl for sl in all_sl if voucher_status_by_id.get(sl.voucher_id) == 'approved']
            covered = round(sum(sl.amount_settled for sl in approved_sl), 2)
            excluded_non_approved = round(
                sum(sl.amount_settled for sl in all_sl) - sum(sl.amount_settled for sl in approved_sl), 2
            )
            amount = round(float(ip.amount or 0), 2)
            remaining = round(amount - covered, 2)
            if remaining <= EPS:
                status = 'full'
            elif covered <= EPS:
                status = 'none'
            else:
                status = 'partial'
            ip_report.append({
                'invoice_payment_id': ip.id,
                'invoice_id': ip.invoice_id,
                'created_at': ip.created_at.isoformat() if ip.created_at else None,
                'amount': amount,
                'covered_by_settlement_line': covered,
                'excluded_non_approved_settlement_amount': excluded_non_approved,
                'remaining': remaining,
                'coverage_status': status,
                'covering_voucher_ids': sorted({sl.voucher_id for sl in all_sl}),
                'covering_voucher_ids_approved_only': sorted({sl.voucher_id for sl in approved_sl}),
            })

        # ── 2) تجميع يومي (بحسب يوم إنشاء الدفعة) ────────────────────────────
        day_buckets = defaultdict(lambda: {'gross': 0.0, 'covered': 0.0, 'ip_ids': [],
                                            'none': 0, 'partial': 0, 'full': 0})
        for r in ip_report:
            d = (r['created_at'] or 'unknown')[:10]
            b = day_buckets[d]
            b['gross'] += r['amount']
            b['covered'] += r['covered_by_settlement_line']
            b['ip_ids'].append(r['invoice_payment_id'])
            b[r['coverage_status']] += 1

        day_report = []
        for d in sorted(day_buckets.keys()):
            b = day_buckets[d]
            day_report.append({
                'day': d,
                'expected_gross': round(b['gross'], 2),
                'covered_by_settlement_line': round(b['covered'], 2),
                'gap': round(b['gross'] - b['covered'], 2),
                'ip_count': len(b['ip_ids']),
                'coverage_counts': {'full': b['full'], 'partial': b['partial'], 'none': b['none']},
                'invoice_payment_ids': b['ip_ids'],
            })

        # ── 3) كل سند تسوية لمس حساب هذه الخزينة: مقارنة ذاتية الاتساق ───────
        voucher_ids_for_account = set()
        if account_id:
            voucher_ids_for_account = {
                row[0] for row in (
                    db.session.query(VoucherAccountLine.voucher_id)
                    .filter(VoucherAccountLine.account_id == account_id)
                    .distinct()
                    .all()
                )
            }

        vouchers = (
            Voucher.query
            .filter(Voucher.id.in_(voucher_ids_for_account))
            .order_by(Voucher.date.asc())
            .all()
            if voucher_ids_for_account else []
        )

        # المبلغ والاتجاه الفعليان على *هذا الحساب بالتحديد* (لا amount_cash
        # الكُلّي للسند، الذي قد يمتد لحسابات أخرى أيضاً).
        lines_on_account = defaultdict(lambda: {'debit': 0.0, 'credit': 0.0})
        if account_id and vouchers:
            for l in VoucherAccountLine.query.filter(
                VoucherAccountLine.voucher_id.in_([v.id for v in vouchers]),
                VoucherAccountLine.account_id == account_id,
            ).all():
                lines_on_account[l.voucher_id][l.line_type] += float(l.amount or 0.0)

        sl_total_by_voucher = defaultdict(float)
        if vouchers:
            for sl in SettlementLine.query.filter(
                SettlementLine.voucher_id.in_([v.id for v in vouchers])
            ).all():
                sl_total_by_voucher[sl.voucher_id] += sl.amount_settled

        # سندات التسوية الحقيقية (يُفترض أن تُنشئ SettlementLine مطابقة لما
        # تقيّده على هذا الحساب) — مقابل أي نشاط آخر على نفس الحساب (سندات
        # قبض/تحويل/تصحيح) لم يكن من المتوقع أصلاً أن تُنشئ SettlementLine.
        settlement_voucher_report = []
        other_account_activity = []
        for v in vouchers:
            line_amounts = lines_on_account.get(v.id, {'debit': 0.0, 'credit': 0.0})
            debit = round(line_amounts['debit'], 2)
            credit = round(line_amounts['credit'], 2)
            sl_total = round(sl_total_by_voucher.get(v.id, 0.0), 2)
            row = {
                'voucher_id': v.id,
                'voucher_number': v.voucher_number,
                'voucher_type': v.voucher_type,
                'status': v.status,
                'date': v.date.isoformat() if v.date else None,
                'created_at': v.created_at.isoformat() if v.created_at else None,
                'reference_type': v.reference_type,
                'reference_number': v.reference_number,
                'debit_on_this_account': debit,
                'credit_on_this_account': credit,
                'notes': v.notes,
            }
            if v.reference_type == 'clearing_settlement':
                row['settlement_line_total'] = sl_total
                row['self_consistency_gap'] = round(credit - sl_total, 2)
                settlement_voucher_report.append(row)
            else:
                other_account_activity.append(row)

        report = {
            'generated_at': run_dt.isoformat(),
            'safe_box_id': safe_box_id,
            'safe_box_name': getattr(safe_box, 'name', None),
            'account_id': account_id,
            'totals': {
                'total_ip_gross': round(sum(r['amount'] for r in ip_report), 2),
                'total_settlement_line_covered': round(sum(r['covered_by_settlement_line'] for r in ip_report), 2),
                'total_remaining': round(sum(r['remaining'] for r in ip_report), 2),
                'settlement_vouchers': {
                    'total_credited': round(sum(vr['credit_on_this_account'] for vr in settlement_voucher_report), 2),
                    'total_settlement_line': round(sum(vr['settlement_line_total'] for vr in settlement_voucher_report), 2),
                    'total_self_consistency_gap': round(sum(vr['self_consistency_gap'] for vr in settlement_voucher_report), 2),
                },
                'other_account_activity': {
                    'count': len(other_account_activity),
                    'total_debit': round(sum(vr['debit_on_this_account'] for vr in other_account_activity), 2),
                    'total_credit': round(sum(vr['credit_on_this_account'] for vr in other_account_activity), 2),
                },
            },
            'per_day': day_report,
            'per_invoice_payment': ip_report,
            'per_settlement_voucher': settlement_voucher_report,
            'other_account_activity': other_account_activity,
        }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(
            reports_dir,
            f"reconcile_clearing_coverage_sb{safe_box_id}_{run_dt.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"صندوق المقاصة: {report['safe_box_name']} (id={safe_box_id}, account_id={account_id})")
        print(f"عدد الدفعات: {len(ip_report)}  |  عدد سندات التسوية: {len(settlement_voucher_report)}  |  نشاط آخر على الحساب: {len(other_account_activity)}")
        print(f"إجمالي الدفعات: {report['totals']['total_ip_gross']:.2f}")
        print(f"إجمالي المُغطّى عبر SettlementLine: {report['totals']['total_settlement_line_covered']:.2f}")
        print(f"إجمالي المتبقي (remaining): {report['totals']['total_remaining']:.2f}")
        st = report['totals']['settlement_vouchers']
        print(f"سندات التسوية فقط — مقيَّد على الحساب: {st['total_credited']:.2f} | SettlementLine المُنشَأة: {st['total_settlement_line']:.2f} | فجوة الاتساق الذاتي: {st['total_self_consistency_gap']:.2f}")
        oa = report['totals']['other_account_activity']
        print(f"نشاط آخر على الحساب (سندات قبض/تحويل/تصحيح، غير سندات تسوية): عدد={oa['count']} | مدين={oa['total_debit']:.2f} | دائن={oa['total_credit']:.2f}")
        print()
        gap_vouchers = [vr for vr in settlement_voucher_report if abs(vr['self_consistency_gap']) > EPS]
        print(f"عدد سندات التسوية التي لها فجوة اتساق ذاتي (credited_on_account != settlement_line_total): {len(gap_vouchers)}")
        for vr in gap_vouchers[:30]:
            print(f"  {vr['voucher_number']:>14s} | date={vr['date']} | credited={vr['credit_on_this_account']:>10.2f} "
                  f"| settlement_line={vr['settlement_line_total']:>10.2f} | gap={vr['self_consistency_gap']:>10.2f}")
        print()
        gap_days = [d for d in day_report if d['gap'] > EPS]
        print(f"عدد الأيام التي فيها gap > 0 (expected_gross > covered_by_settlement_line): {len(gap_days)}")
        for d in gap_days[:30]:
            print(f"  {d['day']} | expected={d['expected_gross']:>10.2f} | covered={d['covered_by_settlement_line']:>10.2f} "
                  f"| gap={d['gap']:>10.2f} | coverage={d['coverage_counts']}")

        print(f"\nتم كتابة التقرير الكامل: {report_path}")
        print("(قراءة فقط — لم يُحفظ أو يُعدَّل أي شيء في قاعدة البيانات)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--safe-box-id', type=int, default=32)
    args = parser.parse_args()
    run(safe_box_id=args.safe_box_id)
