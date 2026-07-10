@'
import sys, os
sys.path.insert(0, "backend")
from app import app
from models import db, InvoicePayment, PaymentMethod, SettlementLine, Voucher
from sqlalchemy import func

SAFE_BOX_ID = 32

with app.app_context():
    print("=== اختبار _compute_clearing_due_amount الجديدة ===\n")

    # ── جميع IPs لمدى ────────────────────────────────────────────────────────
    all_ips = (
        db.session.query(InvoicePayment.id, InvoicePayment.amount)
        .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
        .filter(PaymentMethod.default_safe_box_id == SAFE_BOX_ID)
        .all()
    )
    all_ip_ids = [r[0] for r in all_ips]
    ip_amounts = {r[0]: round(float(r[1]), 2) for r in all_ips}
    print(f"إجمالي IPs مدى: {len(all_ip_ids)}")

    # ── SL المُعتمدة لكل IP ───────────────────────────────────────────────────
    sl_rows = (
        db.session.query(
            SettlementLine.invoice_payment_id,
            func.coalesce(func.sum(SettlementLine.amount_settled), 0.0),
        )
        .join(Voucher, Voucher.id == SettlementLine.voucher_id)
        .filter(
            SettlementLine.invoice_payment_id.in_(all_ip_ids),
            Voucher.status == 'approved',
        )
        .group_by(SettlementLine.invoice_payment_id)
        .all()
    )
    sl_settled = {r[0]: round(float(r[1]), 2) for r in sl_rows}

    # ── حساب pending لكل IP ──────────────────────────────────────────────────
    pending_rows = []
    for ip_id in all_ip_ids:
        amt = ip_amounts[ip_id]
        settled = sl_settled.get(ip_id, 0.0)
        remaining = round(max(0.0, amt - settled), 2)
        if remaining > 0:
            pending_rows.append((ip_id, amt, settled, remaining))

    total_pending = round(sum(r[3] for r in pending_rows), 2)

    print(f"\nIPs pending (غير مغطاة بالكامل بـ SL):")
    print(f"  {'IP':>6}  {'amount':>8}  {'sl_settled':>10}  {'pending':>8}")
    print(f"  {'─'*40}")
    for r in pending_rows[-15:]:   # آخر 15 كحد أقصى
        print(f"  #{r[0]:<5}  {r[1]:>8.2f}  {r[2]:>10.2f}  {r[3]:>8.2f}")

    print(f"\n  {'─'*40}")
    print(f"  pending_sl (إجمالي) = {total_pending:>10.2f} SAR")

    # ── الدالة كاملة ─────────────────────────────────────────────────────────
    from routes import _compute_clearing_due_amount
    due = _compute_clearing_due_amount(SAFE_BOX_ID)
    print(f"\n_compute_clearing_due_amount({SAFE_BOX_ID}) = {due:,.2f} SAR")
    if due > 0:
        print(f"  ✅ الدالة تُعيد القيمة الصحيحة — ستظهر IPs في تسوية المقاصة")
    else:
        print(f"  ❌ الدالة لا تزال تُعيد صفر")

    print(f"\n{'='*60}")
'@ | docker exec -i yasargold-backend python 2>&1 | Select-String -NotMatch "schema_guard|Auto-migration|Startup bootstrap|psycopg2|Background on this error|FullyQualified"
