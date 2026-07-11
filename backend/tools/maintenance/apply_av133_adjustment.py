import sys
sys.path.insert(0, "backend")
from app import app
from models import db, Account, HistoricalClearingAdjustment
from historical_clearing_adjustment_service import (
    HistoricalClearingAdjustmentService,
    AlreadyAppliedError,
)

SAFE_BOX_ID              = 32
AMOUNT                   = 6050.00
CLEARING_ACCOUNT_ID      = 777
CONTRA_ACCOUNT_NUMBER    = '340'
REFERENCE_VOUCHER_NUMBER = 'AV-2026-00133'
APPLIED_BY               = 'admin'

with app.app_context():
    print("=== تطبيق تصحيح AV-2026-00133 ===\n")

    contra = Account.query.filter_by(account_number=CONTRA_ACCOUNT_NUMBER).first()
    if not contra:
        print(f"❌ حساب رقم={CONTRA_ACCOUNT_NUMBER} غير موجود — أنشئه أولاً في النظام")
        sys.exit(1)
    print(f"✅ حساب الفروقات: id={contra.id}  رقم={contra.account_number}  {contra.name}")

    clearing = Account.query.get(CLEARING_ACCOUNT_ID)
    if not clearing:
        print(f"❌ حساب مدى id={CLEARING_ACCOUNT_ID} غير موجود")
        sys.exit(1)
    print(f"✅ حساب مدى:      id={clearing.id}  رقم={clearing.account_number}  {clearing.name}")

    existing = HistoricalClearingAdjustment.query.filter_by(
        reference_voucher_number=REFERENCE_VOUCHER_NUMBER,
        adjustment_type='historical_allocation_gap',
        status='applied',
    ).first()
    if existing:
        print(f"\n⚠️  يوجد تصحيح مطبق مسبقاً لـ {REFERENCE_VOUCHER_NUMBER}:")
        print(f"   id={existing.id}  sbt={existing.safe_box_transaction_id}  je={existing.journal_entry_id}")
        print("   لا يلزم تطبيق جديد.")
        sys.exit(0)

    svc = HistoricalClearingAdjustmentService()

    print(f"\nإنشاء التصحيح...")
    adj = svc.create(
        safe_box_id=SAFE_BOX_ID,
        amount=AMOUNT,
        adjustment_type='historical_allocation_gap',
        reason=(
            'AV-2026-00133 سجّل SafeBoxTransaction OUT=19,710 SAR لكن SettlementLines '
            'تغطي 13,660 SAR فقط. الفارق 6,050 SAR ينتمي لـ IPs أُعيدت لـ AV236/AV237 '
            'في إعادة بناء التخصيص — تصحيح تاريخي بعد اعتماد AllocationService.validate().'
        ),
        reference_voucher_number=REFERENCE_VOUCHER_NUMBER,
        created_by=APPLIED_BY,
    )
    print(f"  adj id={adj.id}  status={adj.status}")

    print(f"تطبيق التصحيح...")
    adj = svc.apply(
        adjustment_id=adj.id,
        applied_by=APPLIED_BY,
        clearing_account_id=CLEARING_ACCOUNT_ID,
        contra_account_id=contra.id,
    )
    db.session.commit()

    print(f"\n✅ تم التطبيق بنجاح")
    print(f"   adj id              = {adj.id}")
    print(f"   status              = {adj.status}")
    print(f"   safe_box_transaction= {adj.safe_box_transaction_id}")
    print(f"   journal_entry       = {adj.journal_entry_id}")
    print(f"   applied_by          = {adj.approved_by}")
    print(f"   applied_at          = {adj.approved_at}")

    from models import SafeBoxTransaction, InvoicePayment, PaymentMethod, SettlementLine, Voucher
    from sqlalchemy import func

    sbt_balance = db.session.query(
        func.coalesce(
            func.sum(
                func.case(
                    (SafeBoxTransaction.direction == 'in',  SafeBoxTransaction.amount_cash),
                    else_=-SafeBoxTransaction.amount_cash
                )
            ), 0.0
        )
    ).filter(SafeBoxTransaction.safe_box_id == SAFE_BOX_ID).scalar()

    all_ip_ids = [r[0] for r in
        db.session.query(InvoicePayment.id)
        .join(PaymentMethod)
        .filter(PaymentMethod.default_safe_box_id == SAFE_BOX_ID).all()]

    sl_rows = (db.session.query(
        SettlementLine.invoice_payment_id,
        func.coalesce(func.sum(SettlementLine.amount_settled), 0.0))
        .join(Voucher, Voucher.id == SettlementLine.voucher_id)
        .filter(
            SettlementLine.invoice_payment_id.in_(all_ip_ids),
            Voucher.status == 'approved')
        .group_by(SettlementLine.invoice_payment_id).all())
    sl_settled = {r[0]: float(r[1]) for r in sl_rows}

    ip_amounts = {r[0]: float(r[1]) for r in
        db.session.query(InvoicePayment.id, InvoicePayment.amount)
        .filter(InvoicePayment.id.in_(all_ip_ids)).all()}

    pending_sl = round(sum(
        max(0.0, ip_amounts[ip_id] - sl_settled.get(ip_id, 0.0))
        for ip_id in all_ip_ids), 2)

    print(f"\n── التحقق من الطبقات بعد التصحيح ──────────────────────────────")
    print(f"   SafeBox balance (SBT net)  = {float(sbt_balance):>10,.2f} SAR")
    print(f"   SL-based pending           = {pending_sl:>10,.2f} SAR")
    match = "✅ متطابقة" if abs(float(sbt_balance) - pending_sl) < 0.01 else "❌ غير متطابقة"
    print(f"   النتيجة                    = {match}")
