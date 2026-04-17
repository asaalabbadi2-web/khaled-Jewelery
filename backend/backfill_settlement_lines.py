#!/usr/bin/env python3
"""Backfill SettlementLine rows for historical clearing settlement vouchers.

Strategy:
  1. For each clearing safe box, gather all InvoicePayments (oldest→newest).
  2. Gather all clearing_settlement vouchers for that safe box (oldest→newest).
  3. Walk vouchers in order, consuming IP amounts via FIFO.
  4. Create SettlementLine rows linking each consumed IP to its voucher.

Usage:
  DRY RUN (default):
    python backfill_settlement_lines.py

  APPLY:
    python backfill_settlement_lines.py --apply
"""
import sys
import os

# Ensure backend directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import (
    db, SafeBox, PaymentMethod, InvoicePayment, Voucher,
    VoucherAccountLine, SafeBoxTransaction, SettlementLine,
)
from sqlalchemy import func


def backfill(apply=False):
    with app.app_context():
        # Ensure table exists
        db.create_all()

        # Find clearing safe boxes
        clearing_sbs = SafeBox.query.filter(
            SafeBox.safe_type == 'clearing',
            SafeBox.is_active == True,
        ).all()

        if not clearing_sbs:
            print("No active clearing safe boxes found.")
            return

        total_created = 0

        for sb in clearing_sbs:
            print(f"\n{'='*60}")
            print(f"Safe Box #{sb.id}: {sb.name}  (account_id={sb.account_id})")
            print(f"{'='*60}")

            # All IPs for this clearing safe, oldest first
            all_ips = (
                InvoicePayment.query
                .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
                .filter(PaymentMethod.default_safe_box_id == sb.id)
                .order_by(InvoicePayment.created_at.asc())
                .all()
            )
            print(f"  Total InvoicePayments: {len(all_ips)}")
            ip_total = sum(float(ip.amount or 0) for ip in all_ips)
            print(f"  Total IP amount: {ip_total:,.2f}")

            # Already-linked IPs (skip them)
            existing_sl_ip_ids = set()
            try:
                existing = (
                    db.session.query(SettlementLine.invoice_payment_id)
                    .filter(SettlementLine.invoice_payment_id.in_([ip.id for ip in all_ips]))
                    .all()
                )
                existing_sl_ip_ids = {row[0] for row in existing}
            except Exception:
                pass

            if existing_sl_ip_ids:
                print(f"  Already linked (SettlementLine): {len(existing_sl_ip_ids)} IPs — skipping them")

            # Clearing settlement vouchers for this safe box, ordered by date
            account_id = sb.account_id
            if not account_id:
                print("  ⚠ No account_id — skipping")
                continue

            vouchers = (
                Voucher.query
                .filter(Voucher.reference_type == 'clearing_settlement')
                .join(VoucherAccountLine, VoucherAccountLine.voucher_id == Voucher.id)
                .filter(VoucherAccountLine.account_id == account_id)
                .order_by(Voucher.date.asc(), Voucher.id.asc())
                .distinct()
                .all()
            )
            print(f"  Settlement vouchers: {len(vouchers)}")
            voucher_total = sum(float(v.amount_cash or 0) for v in vouchers)
            print(f"  Total voucher amount: {voucher_total:,.2f}")

            # FIFO walk: consume IPs against vouchers
            ip_queue = [ip for ip in all_ips if ip.id not in existing_sl_ip_ids]
            ip_idx = 0
            lines_for_sb = 0

            for v in vouchers:
                v_remaining = round(float(v.amount_cash or 0), 2)
                if v_remaining <= 0:
                    continue

                # Compute per-voucher commission info
                # Read fee from voucher lines (debit to fee account)
                v_fee = 0.0
                v_fee_vat = 0.0
                for vl in v.account_lines.all():
                    if vl.line_type == 'debit' and vl.account_id != account_id:
                        desc = (vl.description or '').lower()
                        if 'عمولة' in desc or 'commission' in desc:
                            if 'ضريبة' in desc or 'vat' in desc:
                                v_fee_vat += float(vl.amount or 0)
                            else:
                                v_fee += float(vl.amount or 0)

                v_net = v_remaining  # gross = amount_cash
                v_fee_ratio = v_fee / v_net if v_net > 0 else 0
                v_vat_ratio = v_fee_vat / v_net if v_net > 0 else 0

                while ip_idx < len(ip_queue) and v_remaining > 0.005:
                    ip = ip_queue[ip_idx]
                    ip_amt = round(float(ip.amount or 0), 2)

                    if ip_amt <= v_remaining + 0.005:
                        # Fully consumed
                        settled = ip_amt
                        v_remaining -= ip_amt
                        ip_idx += 1
                    else:
                        # Partial — this IP spans two vouchers
                        # For simplicity, skip partial and move to next voucher
                        break

                    sl = SettlementLine(
                        voucher_id=v.id,
                        invoice_payment_id=ip.id,
                        amount_settled=round(settled, 2),
                        commission=round(settled * v_fee_ratio, 2),
                        commission_vat=round(settled * v_vat_ratio, 2),
                    )
                    if apply:
                        db.session.add(sl)
                    lines_for_sb += 1

                    print(f"    V#{v.id} ({v.voucher_number}) ← IP#{ip.id} "
                          f"({settled:,.2f}) "
                          f"[fee={round(settled * v_fee_ratio, 2)}, "
                          f"vat={round(settled * v_vat_ratio, 2)}]")

            total_created += lines_for_sb
            unmatched = len(ip_queue) - ip_idx
            print(f"  → Created {lines_for_sb} SettlementLine rows")
            print(f"  → Unmatched (pending) IPs: {unmatched}")

        if apply:
            db.session.commit()
            print(f"\n✅ APPLIED: {total_created} SettlementLine rows created.")
        else:
            print(f"\n🔍 DRY RUN: Would create {total_created} SettlementLine rows.")
            print("   Run with --apply to save.")


if __name__ == '__main__':
    do_apply = '--apply' in sys.argv
    backfill(apply=do_apply)
