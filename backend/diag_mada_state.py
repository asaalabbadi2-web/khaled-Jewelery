import sys
sys.path.insert(0, "backend")
from app import app
from models import db, SafeBoxTransaction, InvoicePayment, PaymentMethod, SettlementLine, Voucher
from sqlalchemy import func, case, text

SAFE_BOX_ID = 32

with app.app_context():
    from routes import _compute_clearing_due_amount

    # ── 1. _compute_clearing_due_amount (ما تراه واجهة المقاصة) ────────────
    due = _compute_clearing_due_amount(SAFE_BOX_ID)

    # ── 2. SBT net (ما يراه رصيد الخزينة) ─────────────────────────────────
    sbt_net = db.session.query(
        func.coalesce(func.sum(
            case((SafeBoxTransaction.direction == 'in', SafeBoxTransaction.amount_cash),
                 else_=-SafeBoxTransaction.amount_cash)
        ), 0.0)
    ).filter(SafeBoxTransaction.safe_box_id == SAFE_BOX_ID).scalar()

    # ── 3. SL pending ───────────────────────────────────────────────────────
    all_ip_ids = [r[0] for r in
        db.session.query(InvoicePayment.id)
        .join(PaymentMethod)
        .filter(PaymentMethod.default_safe_box_id == SAFE_BOX_ID).all()]

    if all_ip_ids:
        sl_rows = (db.session.query(
            SettlementLine.invoice_payment_id,
            func.coalesce(func.sum(SettlementLine.amount_settled), 0.0))
            .join(Voucher, Voucher.id == SettlementLine.voucher_id)
            .filter(SettlementLine.invoice_payment_id.in_(all_ip_ids),
                    Voucher.status == 'approved')
            .group_by(SettlementLine.invoice_payment_id).all())
        sl_settled = {r[0]: float(r[1]) for r in sl_rows}
        ip_amounts = {r[0]: float(r[1]) for r in
            db.session.query(InvoicePayment.id, InvoicePayment.amount)
            .filter(InvoicePayment.id.in_(all_ip_ids)).all()}
        sl_pending = round(sum(max(0.0, ip_amounts[i] - sl_settled.get(i, 0.0))
                               for i in all_ip_ids), 2)
    else:
        sl_pending = 0.0

    # ── 4. net_transfer_in (الجزء المضاف للـ due_amount) ───────────────────
    transfer_in = db.session.query(
        func.coalesce(func.sum(SafeBoxTransaction.amount_cash), 0.0)
    ).filter(
        SafeBoxTransaction.safe_box_id == SAFE_BOX_ID,
        SafeBoxTransaction.ref_type == 'voucher',
        SafeBoxTransaction.direction == 'in',
        SafeBoxTransaction.invoice_payment_id.is_(None),
    ).scalar() or 0.0

    reversal_out = db.session.query(
        func.coalesce(func.sum(SafeBoxTransaction.amount_cash), 0.0)
    ).filter(
        SafeBoxTransaction.safe_box_id == SAFE_BOX_ID,
        SafeBoxTransaction.ref_type == 'voucher_reversal',
        SafeBoxTransaction.direction == 'out',
        SafeBoxTransaction.invoice_payment_id.is_(None),
    ).scalar() or 0.0

    net_transfer_in = max(0.0, float(transfer_in) - float(reversal_out))

    # ── 5. كل أنواع SBT في الخزينة ─────────────────────────────────────────
    sbt_by_type = db.session.execute(text("""
        SELECT ref_type, direction,
               COUNT(*) as cnt,
               SUM(amount_cash) as total
        FROM safe_box_transaction
        WHERE safe_box_id = :sb
        GROUP BY ref_type, direction
        ORDER BY ref_type, direction
    """), {'sb': SAFE_BOX_ID}).fetchall()

    print(f"\n=== تشخيص مدى (sb={SAFE_BOX_ID}) ===\n")
    print(f"  _compute_clearing_due_amount = {due:>12,.2f}  ← ما تراه واجهة المقاصة")
    print(f"  SBT net (IN - OUT)           = {float(sbt_net):>12,.2f}  ← رصيد الخزينة الفعلي")
    print(f"  SL pending                   = {sl_pending:>12,.2f}")
    print(f"  net_transfer_in              = {net_transfer_in:>12,.2f}")
    print(f"\n  الفرق (SBT - due)            = {float(sbt_net) - due:>12,.2f}")

    print(f"\n── تفصيل SBT حسب النوع ─────────────────────────────────────────")
    print(f"  {'ref_type':<40}  {'dir':<4}  {'cnt':>5}  {'total':>12}")
    print(f"  {'─'*65}")
    for r in sbt_by_type:
        print(f"  {str(r[0] or 'NULL'):<40}  {str(r[1]):<4}  {r[2]:>5}  {float(r[3]):>12,.2f}")

    # ── 6. تفصيل SBTs المسببة لـ net_transfer_in ──────────────────────────
    transfer_rows = db.session.execute(text("""
        SELECT sbt.id, sbt.ref_id, sbt.amount_cash, sbt.created_at,
               v.voucher_number, v.reference_type, v.status
        FROM safe_box_transaction sbt
        LEFT JOIN voucher v ON v.id = sbt.ref_id
        WHERE sbt.safe_box_id = :sb
          AND sbt.ref_type = 'voucher'
          AND sbt.direction = 'in'
          AND sbt.invoice_payment_id IS NULL
        ORDER BY sbt.id
    """), {'sb': SAFE_BOX_ID}).fetchall()

    print(f"\n── SBTs المسببة لـ net_transfer_in (ref_type=voucher, dir=in, no IP) ─")
    if not transfer_rows:
        print("  لا يوجد")
    else:
        print(f"  {'sbt_id':>8}  {'voucher':>20}  {'ref_type':>25}  {'v_status':>10}  {'amount':>12}")
        print(f"  {'─'*85}")
        for r in transfer_rows:
            sbt_id, ref_id, amount, created_at, v_num, v_ref_type, v_status = r
            print(f"  {sbt_id:>8}  {str(v_num or '—'):>20}  {str(v_ref_type or '—'):>25}  "
                  f"{str(v_status or '—'):>10}  {float(amount):>12,.2f}")
