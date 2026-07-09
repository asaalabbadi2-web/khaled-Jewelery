"""
diag_mada_balance.py
====================
يشخّص لماذا رصيد مدى = 0 ولماذا IPs لا تظهر في تسوية المقاصة.

تشغيل:
    docker exec yasargold-backend python backend/diag_mada_balance.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import app
from models import db, SafeBoxTransaction, InvoicePayment, PaymentMethod, SettlementLine
from sqlalchemy import func, text

SAFE_BOX_ID = 32

with app.app_context():
    print(f"=== تشخيص رصيد مدى (safe_box_id={SAFE_BOX_ID}) ===\n")

    # ── 1) مكوّنات _compute_clearing_due_amount ───────────────────────────────
    ip_in = db.session.query(
        func.coalesce(func.sum(InvoicePayment.amount), 0.0)
    ).join(PaymentMethod).filter(
        PaymentMethod.default_safe_box_id == SAFE_BOX_ID
    ).scalar() or 0.0

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

    voucher_out = db.session.query(
        func.coalesce(func.sum(SafeBoxTransaction.amount_cash), 0.0)
    ).filter(
        SafeBoxTransaction.safe_box_id == SAFE_BOX_ID,
        SafeBoxTransaction.ref_type == 'voucher',
        SafeBoxTransaction.direction == 'out',
    ).scalar() or 0.0

    reversal_in = db.session.query(
        func.coalesce(func.sum(SafeBoxTransaction.amount_cash), 0.0)
    ).filter(
        SafeBoxTransaction.safe_box_id == SAFE_BOX_ID,
        SafeBoxTransaction.ref_type == 'voucher_reversal',
        SafeBoxTransaction.direction == 'in',
    ).scalar() or 0.0

    net_transfer_in = max(0.0, float(transfer_in) - float(reversal_out))
    net_voucher_out = max(0.0, float(voucher_out) - float(reversal_in))
    due = round(float(ip_in) + net_transfer_in - net_voucher_out, 2)

    print("── مكوّنات due_amount ──────────────────────────────────────────")
    print(f"  ip_in (كل IPs مدى)       = {float(ip_in):>12,.2f}")
    print(f"  transfer_in               = {float(transfer_in):>12,.2f}")
    print(f"  reversal_out              = {float(reversal_out):>12,.2f}")
    print(f"  net_transfer_in           = {net_transfer_in:>12,.2f}")
    print(f"  voucher_out               = {float(voucher_out):>12,.2f}")
    print(f"  reversal_in               = {float(reversal_in):>12,.2f}")
    print(f"  net_voucher_out           = {net_voucher_out:>12,.2f}")
    print(f"  {'─'*44}")
    print(f"  due_amount                = {due:>12,.2f}  {'✅' if due > 0 else '❌ هنا المشكلة'}")

    # ── 2) إجمالي SL المرتبطة بمدى ───────────────────────────────────────────
    sl_covered = db.session.execute(text("""
        SELECT COALESCE(SUM(sl.amount_settled), 0)
        FROM settlement_line sl
        JOIN invoice_payment ip ON ip.id = sl.invoice_payment_id
        JOIN payment_method  pm ON pm.id = ip.payment_method_id
        WHERE pm.default_safe_box_id = :sb
    """), {'sb': SAFE_BOX_ID}).scalar() or 0.0

    print(f"\n── تغطية SettlementLine ────────────────────────────────────────")
    print(f"  SL مُعتمدة (مدى)          = {float(sl_covered):>12,.2f}")
    print(f"  voucher_out - SL          = {net_voucher_out - float(sl_covered):>12,.2f}  (فرق غير مُفسَّر)")

    # ── 3) عدد IPs بدون SL ───────────────────────────────────────────────────
    pending_ips = db.session.execute(text("""
        SELECT COUNT(*), COALESCE(SUM(ip.amount), 0)
        FROM invoice_payment ip
        JOIN payment_method pm ON pm.id = ip.payment_method_id
        WHERE pm.default_safe_box_id = :sb
          AND NOT EXISTS (
              SELECT 1 FROM settlement_line sl WHERE sl.invoice_payment_id = ip.id
          )
    """), {'sb': SAFE_BOX_ID}).fetchone()

    print(f"\n── IPs بدون SettlementLine (pending) ───────────────────────────")
    print(f"  عدد IPs                   = {pending_ips[0]:>12}")
    print(f"  مجموع المبالغ             = {float(pending_ips[1]):>12,.2f}")

    # ── 4) آخر 5 SafeBoxTransactions لمدى ────────────────────────────────────
    print(f"\n── آخر 10 SafeBoxTransactions لـ safe_box=32 ───────────────────")
    sbts = db.session.execute(text("""
        SELECT id, ref_type, direction, amount_cash, invoice_payment_id, created_at::text
        FROM safe_box_transaction
        WHERE safe_box_id = :sb
        ORDER BY id DESC
        LIMIT 10
    """), {'sb': SAFE_BOX_ID}).fetchall()

    print(f"  {'id':>6}  {'ref_type':>20}  {'dir':>4}  {'amount':>8}  {'ip_id':>6}  created_at")
    print(f"  {'─'*75}")
    for r in sbts:
        print(f"  {r[0]:>6}  {str(r[1]):>20}  {str(r[2]):>4}  {float(r[3]):>8.0f}  "
              f"{'None' if r[4] is None else r[4]:>6}  {str(r[5])[:19]}")

    # ── 5) خلاصة ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if due <= 0:
        diff = net_voucher_out - float(ip_in)
        print(f"المشكلة: voucher_out ({net_voucher_out:,.0f}) > ip_in ({float(ip_in):,.0f})")
        print(f"  فرق زائد = {diff:,.2f} SAR في SafeBoxTransactions")
        print(f"  هذه السجلات تُلغي الرصيد وتخفي IPs عن واجهة المقاصة")
    else:
        print(f"due_amount = {due:,.2f} SAR — الرصيد صحيح")
        print(f"IPs pending = {pending_ips[1]:,.0f} SAR")
