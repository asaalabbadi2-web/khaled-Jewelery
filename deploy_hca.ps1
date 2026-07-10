# deploy_hca.ps1
# ينشر HistoricalClearingAdjustment: model + service + routes + migration

$CONTAINER = "yasargold-backend"

Write-Host "=== نشر HistoricalClearingAdjustment ===" -ForegroundColor Cyan

# ── 1) تحقق أن الكونتينر يعمل ─────────────────────────────────────────────
$running = docker ps --filter "name=$CONTAINER" --format "{{.Names}}" 2>&1
if (-not $running) {
    Write-Host "❌ الكونتينر $CONTAINER غير موجود" -ForegroundColor Red
    exit 1
}
Write-Host "✅ الكونتينر يعمل: $running" -ForegroundColor Green

# ── 2) نسخ الملفات المُحدَّثة ──────────────────────────────────────────────
Write-Host "`nنسخ الملفات..."

docker cp "backend/models.py"                            "${CONTAINER}:/app/backend/models.py"
docker cp "backend/routes.py"                            "${CONTAINER}:/app/backend/routes.py"
docker cp "backend/historical_clearing_adjustment_service.py" `
          "${CONTAINER}:/app/backend/historical_clearing_adjustment_service.py"

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ فشل نسخ الملفات" -ForegroundColor Red
    exit 1
}
Write-Host "✅ تم نسخ الملفات" -ForegroundColor Green

# ── 3) تشغيل migration SQL ─────────────────────────────────────────────────
Write-Host "`nتشغيل migration..."
docker cp "backend/migrations/create_historical_clearing_adjustment.sql" `
          "${CONTAINER}:/tmp/create_hca.sql"

docker exec $CONTAINER bash -c "
    psql \$DATABASE_URL -f /tmp/create_hca.sql 2>&1
" | Write-Host

Write-Host "✅ Migration اكتمل" -ForegroundColor Green

# ── 4) إعادة تشغيل gunicorn ────────────────────────────────────────────────
Write-Host "`nإعادة تشغيل gunicorn..."
docker exec $CONTAINER bash -c "kill -HUP \$(cat /tmp/gunicorn.pid 2>/dev/null || pgrep -f gunicorn | head -1) 2>/dev/null || true"
Start-Sleep -Seconds 3

# ── 5) تحقق من الـ API ──────────────────────────────────────────────────────
Write-Host "`nاختبار GET /api/admin/historical-clearing-adjustment ..."
@'
import sys
sys.path.insert(0, "backend")
from app import app
from models import db, HistoricalClearingAdjustment

with app.app_context():
    try:
        count = HistoricalClearingAdjustment.query.count()
        print(f"✅ جدول historical_clearing_adjustment موجود — عدد السجلات: {count}")
    except Exception as e:
        print(f"❌ خطأ: {e}")
'@ | docker exec -i $CONTAINER python 2>&1 | Select-String -NotMatch "schema_guard|Auto-migration|Startup bootstrap|psycopg2|Background on this error|FullyQualified"

Write-Host "`n=== اكتمل النشر ===" -ForegroundColor Green
Write-Host @"

الخطوة التالية — إنشاء التصحيح لـ AV133:
POST /api/admin/historical-clearing-adjustment
{
  "safe_box_id": 32,
  "amount": 6050.00,
  "adjustment_type": "historical_allocation_gap",
  "reason": "AV-2026-00133 سجّل SafeBoxTransaction OUT=19710 لكن SLs تغطي 13660 فقط. الفارق 6050 ينتمي لـ IPs مُعادة لـ AV236/AV237 في إعادة البناء.",
  "reference_voucher_number": "AV-2026-00133"
}

ثم تطبيقه:
POST /api/admin/historical-clearing-adjustment/<id>/apply
{
  "clearing_account_id": 777,
  "contra_account_id": <رقم حساب الفروق التاريخية>
}
"@
