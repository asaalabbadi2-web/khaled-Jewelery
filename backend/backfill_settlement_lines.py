#!/usr/bin/env python3
"""Backfill SettlementLine rows for historical clearing settlement vouchers.

Strategy:
  1. For each clearing safe box, gather all InvoicePayments (oldest→newest).
  2. Gather all clearing_settlement vouchers for that safe box (oldest→newest).
  3. Walk vouchers in order, consuming IP amounts via FIFO with partial support.
  4. Create SettlementLine rows linking each consumed IP to its voucher.
  5. Partial consumption: if an IP is larger than the voucher remainder,
     consume a partial amount and carry the rest to the next voucher.

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

# Ensure backend directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from models import (
    db, SafeBox, PaymentMethod, InvoicePayment, Voucher,
    VoucherAccountLine, SafeBoxTransaction, SettlementLine,
)
from sqlalchemy import func


def backfill(apply=False, reset=False):
    with app.app_context():
        # Ensure table exists
        db.create_all()

        if reset:
            count = SettlementLine.query.count()
            print(f"🗑  RESET: deleting {count} existing SettlementLine rows")
            if apply:
                SettlementLine.query.delete()
                db.session.flush()
            else:
                print("   (dry run — nothing deleted)")

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

            # Already-linked IPs — gather settled amounts per IP
            existing_settled = {}  # ip_id → total already settled
            if not reset:
                try:
                    ip_ids = [ip.id for ip in all_ips]
                    if ip_ids:
                        rows = (
                            db.session.query(
                                SettlementLine.invoice_payment_id,
                                func.sum(SettlementLine.amount_settled),
                            )
                            .filter(SettlementLine.invoice_payment_id.in_(ip_ids))
                            .group_by(SettlementLine.invoice_payment_id)
                            .all()
                        )
                        existing_settled = {r[0]: float(r[1] or 0) for r in rows}
                except Exception:
                    pass

                if existing_settled:
                    print(f"  Already linked (SettlementLine): {len(existing_settled)} IPs")

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

            # Track remaining unsettled amount per IP
            ip_remaining = {}
            for ip in all_ips:
                full = round(float(ip.amount or 0), 2)
                already = round(existing_settled.get(ip.id, 0.0), 2)
                ip_remaining[ip.id] = round(full - already, 2)

            # FIFO walk with partial consumption
            ip_idx = 0
            lines_for_sb = 0

            for v in vouchers:
                v_remaining = round(float(v.amount_cash or 0), 2)
                if v_remaining <= 0:
                    continue

                # Check if this voucher already has settlement lines (skip if not reset)
                if not reset:
                    existing_for_v = SettlementLine.query.filter_by(voucher_id=v.id).count()
                    if existing_for_v > 0:
                        # Already processed — subtract from budget and advance ip_idx
                        v_remaining = 0
                        continue

                # Compute per-voucher commission ratios
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

                v_gross = round(float(v.amount_cash or 0), 2)
                v_fee_ratio = v_fee / v_gross if v_gross > 0 else 0
                v_vat_ratio = v_fee_vat / v_gross if v_gross > 0 else 0

                while ip_idx < len(all_ips) and v_remaining > 0.005:
                    ip = all_ips[ip_idx]
                    avail = ip_remaining.get(ip.id, 0.0)

                    if avail <= 0.005:
                        ip_idx += 1
                        continue

                    # Consume min(available, voucher_remaining)
                    consume = round(min(avail, v_remaining), 2)

                    sl = SettlementLine(
                        voucher_id=v.id,
                        invoice_payment_id=ip.id,
                        amount_settled=consume,
                        commission=round(consume * v_fee_ratio, 2),
                        commission_vat=round(consume * v_vat_ratio, 2),
                    )
                    if apply:
                        db.session.add(sl)
                    lines_for_sb += 1

                    tag = '' if abs(consume - float(ip.amount or 0)) < 0.01 else ' [partial]'
                    print(f"    V#{v.id} ({v.voucher_number}) ← IP#{ip.id} "
                          f"({consume:,.2f}{tag}) "
                          f"[fee={round(consume * v_fee_ratio, 2)}, "
                          f"vat={round(consume * v_vat_ratio, 2)}]")

                    ip_remaining[ip.id] = round(avail - consume, 2)
                    v_remaining = round(v_remaining - consume, 2)

                    # Advance pointer only if IP is fully consumed
                    if ip_remaining[ip.id] <= 0.005:
                        ip_idx += 1

            total_created += lines_for_sb
            # Count truly unmatched IPs (remaining > 0)
            unmatched = sum(1 for ip in all_ips if ip_remaining.get(ip.id, 0) > 0.005)
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
    do_reset = '--reset' in sys.argv
    backfill(apply=do_apply, reset=do_reset)
