"""
apply_hca.py — Generic HistoricalClearingAdjustment runner
===========================================================
يستخدم نفس مسار create() → apply() → audit trail لأي تصحيح تاريخي.

تشغيل:
    python backend/apply_hca.py \\
        --safe-box-id     32 \\
        --amount          3700 \\
        --type            historical_gl_adjustment \\
        --voucher-number  "AV-2026-00210" \\
        --clearing-acc    777 \\
        --contra-acc      1215 \\
        --applied-by      admin \\
        --reason          "تصحيح GL يدوي قبل دعم النظام لتعديل وسائل الدفع"
"""

import sys
import argparse

sys.path.insert(0, "backend")
from app import app
from models import db, Account, SafeBox, HistoricalClearingAdjustment
from historical_clearing_adjustment_service import (
    HistoricalClearingAdjustmentService,
    AlreadyAppliedError,
)


def parse_args():
    p = argparse.ArgumentParser(description='Apply a HistoricalClearingAdjustment')
    p.add_argument('--safe-box-id',    type=int,   required=True)
    p.add_argument('--amount',         type=float, required=True)
    p.add_argument('--type',           required=True,
                   choices=sorted(HistoricalClearingAdjustment.VALID_TYPES))
    p.add_argument('--voucher-number', default=None)
    p.add_argument('--clearing-acc',   type=int,   required=True)
    p.add_argument('--contra-acc',     type=int,   required=True)
    p.add_argument('--applied-by',     default='admin')
    p.add_argument('--reason',         default='')
    return p.parse_args()


def main():
    args = parse_args()

    with app.app_context():
        print(f"\n=== HistoricalClearingAdjustment ===")
        print(f"  type           : {args.type}")
        print(f"  amount         : {args.amount:,.2f} SAR")
        print(f"  safe_box_id    : {args.safe_box_id}")
        print(f"  voucher        : {args.voucher_number or '—'}")
        print(f"  clearing_acc   : {args.clearing_acc}")
        print(f"  contra_acc     : {args.contra_acc}")
        print()

        # ── التحقق المبكر ─────────────────────────────────────────────────
        if not SafeBox.query.get(args.safe_box_id):
            print(f"❌ SafeBox id={args.safe_box_id} غير موجود")
            sys.exit(1)

        clearing = Account.query.get(args.clearing_acc)
        contra   = Account.query.get(args.contra_acc)
        if not clearing:
            print(f"❌ Account id={args.clearing_acc} غير موجود")
            sys.exit(1)
        if not contra:
            print(f"❌ Account id={args.contra_acc} غير موجود")
            sys.exit(1)

        print(f"  clearing: {clearing.account_number} — {clearing.name}")
        print(f"  contra  : {contra.account_number} — {contra.name}")

        # ── هل يوجد تصحيح مطبق مسبقاً لنفس المرجع والنوع؟ ──────────────
        if args.voucher_number:
            existing = HistoricalClearingAdjustment.query.filter_by(
                reference_voucher_number=args.voucher_number,
                adjustment_type=args.type,
                status='applied',
            ).first()
            if existing:
                print(f"\n⚠️  يوجد تصحيح مطبق مسبقاً:")
                print(f"   id={existing.id}  sbt={existing.safe_box_transaction_id}"
                      f"  je={existing.journal_entry_id}")
                sys.exit(0)

        # ── create() ──────────────────────────────────────────────────────
        svc = HistoricalClearingAdjustmentService()

        reason = args.reason or (
            f'تصحيح تاريخي [{args.type}]'
            + (f' مرجع {args.voucher_number}' if args.voucher_number else '')
        )

        print(f"\nإنشاء السجل (pending)...")
        adj = svc.create(
            safe_box_id=args.safe_box_id,
            amount=args.amount,
            adjustment_type=args.type,
            reason=reason,
            created_by=args.applied_by,
            reference_voucher_number=args.voucher_number,
        )
        print(f"  adj.id={adj.id}  status={adj.status}")

        # ── apply() ───────────────────────────────────────────────────────
        print(f"تطبيق القيد والخزينة...")
        try:
            adj = svc.apply(
                adjustment_id=adj.id,
                applied_by=args.applied_by,
                clearing_account_id=args.clearing_acc,
                contra_account_id=args.contra_acc,
            )
        except AlreadyAppliedError as e:
            db.session.rollback()
            print(f"❌ {e}")
            sys.exit(1)
        except ValueError as e:
            db.session.rollback()
            print(f"❌ {e}")
            sys.exit(1)

        db.session.commit()

        # ── النتيجة ───────────────────────────────────────────────────────
        print(f"\n✅ تم التطبيق")
        print(f"   adj.id              = {adj.id}")
        print(f"   status              = {adj.status}")
        print(f"   safe_box_transaction= {adj.safe_box_transaction_id}")
        print(f"   journal_entry       = {adj.journal_entry_id}")
        print(f"   applied_by          = {adj.approved_by}")
        print(f"   applied_at          = {adj.approved_at}")


if __name__ == '__main__':
    main()
