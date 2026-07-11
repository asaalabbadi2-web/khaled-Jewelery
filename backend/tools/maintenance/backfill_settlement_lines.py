#!/usr/bin/env python3
"""Backfill SettlementLine rows for historical clearing settlement vouchers.

Strategy:
  Delegate all allocation logic (FIFO ordering, partial consumption, commission
  proration) to AllocationService. This script is responsible only for:
    1. Identifying clearing safe boxes and their IPs and vouchers.
    2. Calling AllocationService.allocate() for each unprocessed voucher.
    3. Flushing after each voucher so subsequent calls see correct prev_settled.
    4. Committing (--apply) or rolling back (dry run) at the end.

Flags:
  --apply       Persist changes (default is dry run)
  --reset       Delete ALL existing SettlementLine rows first, then re-backfill

Usage:
  DRY RUN:    python backfill_settlement_lines.py
  APPLY:      python backfill_settlement_lines.py --apply
  RE-DO:      python backfill_settlement_lines.py --reset --apply
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import (
    db, SafeBox, PaymentMethod, InvoicePayment,
    Voucher, VoucherAccountLine, SettlementLine,
)
from allocation_service import AllocationService


def _extract_fee_vat(voucher: Voucher, clearing_account_id: int) -> tuple[float, float]:
    """Extract commission and VAT amounts from voucher account lines."""
    fee = 0.0
    fee_vat = 0.0
    for vl in voucher.account_lines.all():
        if vl.line_type == 'debit' and vl.account_id != clearing_account_id:
            desc = (vl.description or '').lower()
            if 'عمولة' in desc or 'commission' in desc:
                if 'ضريبة' in desc or 'vat' in desc:
                    fee_vat += float(vl.amount or 0)
                else:
                    fee += float(vl.amount or 0)
    return fee, fee_vat


def backfill(apply: bool = False, reset: bool = False) -> None:
    with app.app_context():
        db.create_all()

        if reset:
            count = SettlementLine.query.count()
            print(f"🗑  RESET: deleting {count} existing SettlementLine rows")
            if apply:
                SettlementLine.query.delete()
                db.session.flush()
            else:
                print("   (dry run — nothing deleted)")

        clearing_sbs = SafeBox.query.filter(
            SafeBox.safe_type == 'clearing',
            SafeBox.is_active == True,
        ).all()

        if not clearing_sbs:
            print("No active clearing safe boxes found.")
            return

        svc = AllocationService()
        total_created = 0
        total_gaps = 0

        for sb in clearing_sbs:
            print(f"\n{'='*60}")
            print(f"Safe Box #{sb.id}: {sb.name}  (account_id={sb.account_id})")
            print(f"{'='*60}")

            if not sb.account_id:
                print("  ⚠ No account_id — skipping")
                continue

            # All IPs for this clearing safe, oldest-first.
            # Passing the full set lets AllocationService handle FIFO across vouchers:
            # each call to allocate() queries prev_settled (after flush) and skips
            # already-consumed IPs, naturally advancing the FIFO pointer.
            all_ips = (
                InvoicePayment.query
                .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
                .filter(PaymentMethod.default_safe_box_id == sb.id)
                .order_by(InvoicePayment.created_at.asc())
                .all()
            )
            all_ip_ids = [ip.id for ip in all_ips]
            print(f"  Total InvoicePayments: {len(all_ips)}")
            print(f"  Total IP amount: {sum(float(ip.amount or 0) for ip in all_ips):,.2f}")

            vouchers = (
                Voucher.query
                .filter(Voucher.reference_type == 'clearing_settlement')
                .join(VoucherAccountLine, VoucherAccountLine.voucher_id == Voucher.id)
                .filter(VoucherAccountLine.account_id == sb.account_id)
                .order_by(Voucher.date.asc(), Voucher.id.asc())
                .distinct()
                .all()
            )
            print(f"  Settlement vouchers: {len(vouchers)}")
            print(f"  Total voucher amount: {sum(float(v.amount_cash or 0) for v in vouchers):,.2f}")

            lines_for_sb = 0
            gaps_for_sb = 0

            for v in vouchers:
                v_gross = round(float(v.amount_cash or 0), 2)
                if v_gross <= 0:
                    continue

                if not reset and SettlementLine.query.filter_by(voucher_id=v.id).count() > 0:
                    continue

                v_fee, v_fee_vat = _extract_fee_vat(v, sb.account_id)

                try:
                    plan = svc.allocate(
                        voucher=v,
                        invoice_payment_ids=all_ip_ids,
                        gross_amount=v_gross,
                        fee_amount=v_fee,
                        fee_vat=v_fee_vat,
                    )
                except ValueError as exc:
                    print(f"    ⚠ {v.voucher_number}: {exc} — coverage gap, skipping")
                    gaps_for_sb += 1
                    continue

                # Flush so the next voucher's allocate() sees these rows in
                # prev_settled and correctly skips already-consumed IPs.
                db.session.flush()

                for line in plan.lines:
                    print(f"    V#{v.id} ({v.voucher_number}) ← IP#{line.invoice_payment_id} "
                          f"({line.amount_to_allocate:,.2f})"
                          f" [fee={line.commission:.2f}, vat={line.commission_vat:.2f}]")
                lines_for_sb += len(plan.lines)

            total_created += lines_for_sb
            total_gaps += gaps_for_sb
            print(f"  → SettlementLine rows: {lines_for_sb}")
            if gaps_for_sb:
                print(f"  → Coverage gaps: {gaps_for_sb} voucher(s) skipped")

        if apply:
            db.session.commit()
            print(f"\n✅ APPLIED: {total_created} SettlementLine rows created.")
        else:
            db.session.rollback()
            print(f"\n🔍 DRY RUN: Would create {total_created} SettlementLine rows.")
            print("   Run with --apply to save.")

        if total_gaps:
            print(f"⚠ Total coverage gaps: {total_gaps} voucher(s) — run AllocationIntegrityService to diagnose.")


if __name__ == '__main__':
    do_apply = '--apply' in sys.argv
    do_reset = '--reset' in sys.argv
    backfill(apply=do_apply, reset=do_reset)
