import sys
sys.path.insert(0, "backend")
from app import app
from models import db, SafeBoxTransaction, InvoicePayment, PaymentMethod, SettlementLine, Voucher, HistoricalClearingAdjustment, JournalEntry, JournalEntryLine
from sqlalchemy import func, case

SAFE_BOX_ID = 32

with app.app_context():
    print("=== التحقق من نتيجة تصحيح AV-2026-00133 ===\n")

    # ── التصحيح المطبق ──────────────────────────────────────────────────────
    adj = HistoricalClearingAdjustment.query.filter_by(
        reference_voucher_number='AV-2026-00133',
        status='applied',
    ).first()
    if not adj:
        print("❌ لا يوجد تصحيح مطبق لـ AV-2026-00133")
        sys.exit(1)

    print(f"✅ التصحيح: id={adj.id}  amount={adj.amount:,.2f}  status={adj.status}")
    print(f"   sbt_id={adj.safe_box_transaction_id}  je_id={adj.journal_entry_id}")
    print(f"   applied_by={adj.approved_by}  at={adj.approved_at}")

    # ── SafeBox net balance ─────────────────────────────────────────────────
    sbt_balance = db.session.query(
        func.coalesce(
            func.sum(
                case(
                    (SafeBoxTransaction.direction == 'in',  SafeBoxTransaction.amount_cash),
                    else_=-SafeBoxTransaction.amount_cash
                )
            ), 0.0
        )
    ).filter(SafeBoxTransaction.safe_box_id == SAFE_BOX_ID).scalar()

    # ── SL-based pending ────────────────────────────────────────────────────
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

    # ── JournalEntry للتصحيح ────────────────────────────────────────────────
    je = JournalEntry.query.get(adj.journal_entry_id)
    je_lines = JournalEntryLine.query.filter_by(journal_entry_id=je.id).all()
    je_debit  = sum(l.cash_debit  for l in je_lines)
    je_credit = sum(l.cash_credit for l in je_lines)

    # ── SafeBoxTransaction للتصحيح ──────────────────────────────────────────
    sbt = SafeBoxTransaction.query.get(adj.safe_box_transaction_id)

    print(f"\n── القيد المحاسبي (JE#{je.id}) ─────────────────────────────────")
    for l in je_lines:
        print(f"   acc={l.account_id}  Dr={l.cash_debit:,.2f}  Cr={l.cash_credit:,.2f}  {l.description}")
    print(f"   إجمالي Dr={je_debit:,.2f}  Cr={je_credit:,.2f}  {'✅ متوازن' if abs(je_debit-je_credit)<0.01 else '❌ غير متوازن'}")

    print(f"\n── حركة الخزينة (SBT#{sbt.id}) ──────────────────────────────────")
    print(f"   direction={sbt.direction}  amount={sbt.amount_cash:,.2f}  ref_type={sbt.ref_type}")

    print(f"\n── مقارنة الطبقات ───────────────────────────────────────────────")
    print(f"   SafeBox net balance (SBT)  = {float(sbt_balance):>10,.2f} SAR")
    print(f"   SL-based pending           = {pending_sl:>10,.2f} SAR")
    diff = abs(float(sbt_balance) - pending_sl)
    if diff < 0.01:
        print(f"   ✅ الطبقات متطابقة — جاهز لتسوية الـ 8 IPs")
    else:
        print(f"   ❌ فرق = {diff:,.2f} SAR — يحتاج مراجعة")
