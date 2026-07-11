"""
accounting_review_av045_av133.py
==================================
تقرير مراجعة محاسبية - قراءة فقط بالكامل - لحالتين تاريخيتين مؤكَّدتين من
فجوة الاتساق الذاتي لسندات تسوية مدى (وُجدتا عبر
reconcile_clearing_settlement_coverage.py --safe-box-id 32):

  AV-2026-00045 (voucher_id=991): SettlementLine المُنشأة = 3670، المُقيَّد
  فعلياً على الحساب = 1070 (فجوة -2600 — تغطية زائدة).

  AV-2026-00133 (voucher_id=1649): المُقيَّد فعلياً = 19710، SettlementLine
  المُنشأة = 13660 (فجوة +6050 — تغطية ناقصة / ghost credit).

لا يُعدّل أي بيانات إطلاقاً. الهدف تزويد المراجعة المحاسبية البشرية بحقائق
دقيقة لاتخاذ القرار (حذف سطر SettlementLine زائد لـ045، إنشاء سطر مفقود أو
سند تصحيحي لـ133) دون أي تنفيذ تلقائي لأي تصحيح.

تشغيل:
    docker cp backend/accounting_review_av045_av133.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/accounting_review_av045_av133.py
"""

import os
import sys
import json
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, SettlementLine, Voucher, InvoicePayment, PaymentMethod

AV045_VOUCHER_IDS = (990, 991)  # AV-2026-00044, AV-2026-00045
AV045_IP_ID = 1003
AV133_VOUCHER_ID = 1649  # AV-2026-00133
SAFE_BOX_ID = 32


def run():
    with app.app_context():
        report = {'generated_at': datetime.now(timezone.utc).isoformat()}

        print("=" * 70)
        print("AV-2026-00045 (voucher 991) / AV-2026-00044 (voucher 990) — IP 1003")
        print("=" * 70)

        ip1003 = InvoicePayment.query.get(AV045_IP_ID)
        if not ip1003:
            print(f"IP {AV045_IP_ID} not found — skipping AV-045 section (different DB?).")
            report['av045'] = None
        else:
            print(f"IP {AV045_IP_ID}: amount={ip1003.amount:.2f}, created_at={ip1003.created_at}")

            sl_rows = (
                SettlementLine.query
                .filter(SettlementLine.invoice_payment_id == AV045_IP_ID)
                .order_by(SettlementLine.created_at.asc())
                .all()
            )
            av045_lines = []
            for sl in sl_rows:
                v = Voucher.query.get(sl.voucher_id)
                row = {
                    'settlement_line_id': sl.id,
                    'voucher_id': sl.voucher_id,
                    'voucher_number': v.voucher_number if v else None,
                    'amount_settled': sl.amount_settled,
                    'sl_created_at': sl.created_at.isoformat() if sl.created_at else None,
                    'voucher_credited_amount_cash': v.amount_cash if v else None,
                }
                av045_lines.append(row)
                print(f"  SettlementLine#{sl.id} | voucher {row['voucher_number']} (id={sl.voucher_id}) "
                      f"| amount_settled={sl.amount_settled:.2f} | created_at={row['sl_created_at']}")

            total_settled_ip1003 = round(sum(r['amount_settled'] for r in av045_lines), 2)
            over_coverage = round(total_settled_ip1003 - ip1003.amount, 2)
            print(f"\nIP {AV045_IP_ID} amount={ip1003.amount:.2f} | total SettlementLine={total_settled_ip1003:.2f} "
                  f"| over-coverage={over_coverage:.2f}")

            print("\nPer-voucher self-consistency (across ALL their own IPs, not just 1003):")
            voucher_breakdown = {}
            for vid in AV045_VOUCHER_IDS:
                v = Voucher.query.get(vid)
                if not v:
                    continue
                all_sl = SettlementLine.query.filter_by(voucher_id=vid).all()
                sl_total = round(sum(s.amount_settled for s in all_sl), 2)
                ips_touched = [
                    {'invoice_payment_id': s.invoice_payment_id, 'amount_settled': s.amount_settled}
                    for s in all_sl
                ]
                gap = round((v.amount_cash or 0) - sl_total, 2)
                voucher_breakdown[vid] = {
                    'voucher_number': v.voucher_number,
                    'credited_amount_cash': v.amount_cash,
                    'settlement_line_total': sl_total,
                    'gap': gap,
                    'ips_touched': ips_touched,
                }
                print(f"  {v.voucher_number} (id={vid}): credited={v.amount_cash:.2f} | "
                      f"settlement_line_total={sl_total:.2f} | gap={gap:.2f}")
                for t in ips_touched:
                    print(f"      -> IP {t['invoice_payment_id']}: {t['amount_settled']:.2f}")

            report['av045'] = {
                'ip_1003_amount': ip1003.amount,
                'ip_1003_settlement_lines': av045_lines,
                'ip_1003_total_settled': total_settled_ip1003,
                'ip_1003_over_coverage': over_coverage,
                'voucher_breakdown': voucher_breakdown,
            }

        print()
        print("=" * 70)
        print("AV-2026-00133 (voucher 1649) — missing-coverage candidate search")
        print("=" * 70)

        v1649 = Voucher.query.get(AV133_VOUCHER_ID)
        if not v1649:
            print(f"Voucher {AV133_VOUCHER_ID} not found — skipping AV-133 section (different DB?).")
            report['av133'] = None
        else:
            existing_sl = SettlementLine.query.filter_by(voucher_id=AV133_VOUCHER_ID).all()
            existing_total = round(sum(s.amount_settled for s in existing_sl), 2)
            gap = round((v1649.amount_cash or 0) - existing_total, 2)
            print(f"{v1649.voucher_number}: credited={v1649.amount_cash:.2f} | "
                  f"settlement_line_total={existing_total:.2f} | unexplained_gap={gap:.2f}")
            print("Existing SettlementLine rows for this voucher:")
            for s in existing_sl:
                print(f"  IP {s.invoice_payment_id}: amount_settled={s.amount_settled:.2f}")

            cutoff_dt = v1649.date
            all_ips = (
                InvoicePayment.query
                .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
                .filter(PaymentMethod.default_safe_box_id == SAFE_BOX_ID)
                .filter(InvoicePayment.created_at < cutoff_dt)
                .order_by(InvoicePayment.created_at.asc())
                .all()
            )

            candidates = []
            for ip in all_ips:
                sl_for_ip = SettlementLine.query.filter_by(invoice_payment_id=ip.id).all()
                covered_before_cutoff = sum(
                    s.amount_settled for s in sl_for_ip
                    if s.created_at and s.created_at < cutoff_dt
                )
                remaining_at_cutoff = round(float(ip.amount or 0) - covered_before_cutoff, 2)
                if remaining_at_cutoff > 0.01:
                    candidates.append({
                        'invoice_payment_id': ip.id,
                        'invoice_id': ip.invoice_id,
                        'created_at': ip.created_at.isoformat() if ip.created_at else None,
                        'amount': ip.amount,
                        'remaining_as_of_cutoff': remaining_at_cutoff,
                    })

            print(f"\nCandidate IPs unsettled as of {cutoff_dt} (oldest-first; stop once cumulative >= gap {gap:.2f}):")
            running = 0.0
            shown = []
            for c in candidates:
                if running >= gap - 0.01:
                    break
                running = round(running + c['remaining_as_of_cutoff'], 2)
                shown.append(c)
                print(f"  IP {c['invoice_payment_id']:>6} | invoice {c['invoice_id']} | "
                      f"created_at={c['created_at']} | remaining={c['remaining_as_of_cutoff']:>9.2f} | "
                      f"cumulative={running:>9.2f}")
            print(f"({len(candidates) - len(shown)} more candidate IPs exist further back, not shown — "
                  f"cumulative already {'reached' if running >= gap - 0.01 else 'did NOT reach'} the gap)")

            report['av133'] = {
                'voucher_credited': v1649.amount_cash,
                'voucher_settlement_line_total': existing_total,
                'unexplained_gap': gap,
                'existing_settlement_lines': [
                    {'invoice_payment_id': s.invoice_payment_id, 'amount_settled': s.amount_settled}
                    for s in existing_sl
                ],
                'candidates_shown_until_cumulative_covers_gap': shown,
                'total_candidate_count_before_cutoff': len(candidates),
            }

        reports_dir = os.path.join(os.path.dirname(__file__), 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        path = os.path.join(
            reports_dir,
            f"accounting_review_av045_av133_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json",
        )
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nتم كتابة التقرير: {path}")
        print("(قراءة فقط بالكامل — لم يُعدَّل أي شيء في قاعدة البيانات)")


if __name__ == '__main__':
    run()
