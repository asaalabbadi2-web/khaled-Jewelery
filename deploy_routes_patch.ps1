# deploy_routes_patch.ps1
# ينسخ routes.py المحدَّث مباشرة للكونتينر ويعيد تشغيل الـ backend
# بدون rebuild كامل للصورة

$CONTAINER = "yasargold-backend"
$LOCAL_ROUTES = "backend/routes.py"
$REMOTE_ROUTES = "/app/backend/routes.py"

Write-Host "=== نشر routes.py بشكل جزئي ===" -ForegroundColor Cyan
Write-Host ""

# ── 1) تحقق أن الكونتينر يعمل ─────────────────────────────────────────────
$running = docker ps --filter "name=$CONTAINER" --format "{{.Names}}" 2>&1
if (-not $running) {
    Write-Host "❌ الكونتينر $CONTAINER غير موجود أو متوقف" -ForegroundColor Red
    exit 1
}
Write-Host "✅ الكونتينر يعمل: $running" -ForegroundColor Green

# ── 2) انسخ routes.py للكونتينر ───────────────────────────────────────────
Write-Host ""
Write-Host "نسخ $LOCAL_ROUTES → $CONTAINER`:$REMOTE_ROUTES ..."
docker cp $LOCAL_ROUTES "${CONTAINER}:${REMOTE_ROUTES}"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ فشل docker cp" -ForegroundColor Red
    exit 1
}
Write-Host "✅ تم نسخ الملف" -ForegroundColor Green

# ── 3) انسخ سكريبت الاختبار للكونتينر ────────────────────────────────────
Write-Host ""
Write-Host "نسخ test_new_due_amount.ps1 → الكونتينر ..."
# نستخرج كود Python فقط من PS1 (بين @' و '@)
$ps1content = Get-Content "test_new_due_amount.ps1" -Raw
$pycode = $ps1content -replace "(?s)^@'(.+?)'@.*$", '$1'
$pycode | docker exec -i $CONTAINER bash -c "cat > /app/backend/test_new_due_amount.py"
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ لم يُنسخ سكريبت الاختبار — سنشغّله مباشرة" -ForegroundColor Yellow
}

# ── 4) أعد تشغيل gunicorn (reload بدون downtime) ──────────────────────────
Write-Host ""
Write-Host "إعادة تشغيل gunicorn (graceful reload) ..."
docker exec $CONTAINER bash -c "kill -HUP \$(cat /tmp/gunicorn.pid 2>/dev/null || pgrep -f gunicorn | head -1) 2>/dev/null || true"
Start-Sleep -Seconds 3

# ── 5) شغّل اختبار الدالة الجديدة ─────────────────────────────────────────
Write-Host ""
Write-Host "=== تشغيل اختبار _compute_clearing_due_amount ===" -ForegroundColor Cyan
@'
import sys, os
sys.path.insert(0, "backend")
from app import app
from models import db, InvoicePayment, PaymentMethod, SettlementLine, Voucher
from sqlalchemy import func

SAFE_BOX_ID = 32

with app.app_context():
    print("=== اختبار _compute_clearing_due_amount الجديدة ===\n")

    all_ips = (
        db.session.query(InvoicePayment.id, InvoicePayment.amount)
        .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
        .filter(PaymentMethod.default_safe_box_id == SAFE_BOX_ID)
        .all()
    )
    all_ip_ids = [r[0] for r in all_ips]
    ip_amounts = {r[0]: round(float(r[1]), 2) for r in all_ips}
    print(f"إجمالي IPs مدى: {len(all_ip_ids)}")

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

    pending_rows = []
    for ip_id in all_ip_ids:
        amt = ip_amounts[ip_id]
        settled = sl_settled.get(ip_id, 0.0)
        remaining = round(max(0.0, amt - settled), 2)
        if remaining > 0:
            pending_rows.append((ip_id, amt, settled, remaining))

    total_pending = round(sum(r[3] for r in pending_rows), 2)
    print(f"IPs pending: {len(pending_rows)}")
    print(f"  {'IP':>6}  {'amount':>8}  {'sl_settled':>10}  {'pending':>8}")
    print(f"  {chr(8211)*40}")
    for r in pending_rows[-15:]:
        print(f"  #{r[0]:<5}  {r[1]:>8.2f}  {r[2]:>10.2f}  {r[3]:>8.2f}")
    print(f"\n  pending_sl (اجمالي) = {total_pending:>10.2f} SAR")

    from routes import _compute_clearing_due_amount
    due = _compute_clearing_due_amount(SAFE_BOX_ID)
    print(f"\n_compute_clearing_due_amount({SAFE_BOX_ID}) = {due:,.2f} SAR")
    if due > 0:
        print("  OK الدالة تعيد القيمة الصحيحة -- IPs ستظهر في تسوية المقاصة")
    else:
        print("  ERROR الدالة لا تزال تعيد صفر")
'@ | docker exec -i $CONTAINER python 2>&1 | Select-String -NotMatch "schema_guard|Auto-migration|Startup bootstrap|psycopg2|Background on this error|FullyQualified"
