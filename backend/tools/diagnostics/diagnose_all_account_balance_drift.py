"""
diagnose_all_account_balance_drift.py
=============================================
تشخيص فقط (لا تعديل على الإطلاق) — لا --apply ولا أي كتابة لقاعدة البيانات.

يوسّع diagnose_cash_transfer_balance_drift.py (الذي كشف فروقاً ضخمة في
755/757/777) ليشمل *كل* الحسابات (398 حساباً)، للإجابة على سؤال واحد:
هل هذا الفرق محصور في حسابات الخزائن الثلاثة، أم منتشر في النظام كله؟

النتيجة تحدّد القرار التالي:
  - لو محصور في عدد قليل من الحسابات: الأرجح خلل محدد في مسار معيّن
    (مثل عدم عكس update_balance() عند unpost_invoice/delete_unposted_invoice).
  - لو منتشر في عدد كبير من الحسابات بأنماط مختلفة: الأرجح أن قاعدة
    البيانات لم تُعاد بناء أرصدتها منذ فترة طويلة (نفس الحالة التي صُمم
    /api/system/rebuild-account-balances الموجود فعلاً في النظام لمعالجتها).

لا يكتب أي شيء؛ فقط يطبع كل حساب فيه فرق حقيقي (> 1 ريال أو > 0.001 جم)
بين balance_cash/balance_*k المخزَّن والمحسوَب فعلياً من القيود المرحَّلة
غير المحذوفة (نفس فلتر live_balances_by_account_ids المعتمد في كل تسويات
النظام).

تشغيل:
    docker cp backend/diagnose_all_account_balance_drift.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/diagnose_all_account_balance_drift.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import Account
from services.live_balances import live_balances_by_account_ids

with app.app_context():
    all_accounts = Account.query.all()
    ids = [a.id for a in all_accounts]
    live = live_balances_by_account_ids(ids)

    print(f"فحص {len(ids)} حساباً...\n")
    print(f"{'ID':>6} | {'الاسم':<35} | {'مخزَّن (نقدي)':>15} | {'فعلي (نقدي)':>15} | {'فرق نقدي':>12}")
    print("-" * 100)

    total_cash_drift = 0.0
    flagged = 0
    for acc in all_accounts:
        stored_cash = float(getattr(acc, 'balance_cash', 0.0) or 0.0)
        live_row = live.get(acc.id, {})
        actual_cash = float(live_row.get('cash', 0.0))
        diff_cash = round(stored_cash - actual_cash, 2)

        weight_diffs = []
        for k in ('18k', '21k', '22k', '24k'):
            stored_w = float(getattr(acc, f'balance_{k}', 0.0) or 0.0)
            actual_w = float(live_row.get(k, 0.0))
            d = round(stored_w - actual_w, 3)
            if abs(d) > 0.001:
                weight_diffs.append(f"{k}:{d:+.3f}")

        if abs(diff_cash) > 1.0 or weight_diffs:
            flagged += 1
            total_cash_drift += diff_cash
            extra = f"  [وزن: {', '.join(weight_diffs)}]" if weight_diffs else ""
            print(f"{acc.id:>6} | {(acc.name or '')[:35]:<35} | {stored_cash:>15.2f} | {actual_cash:>15.2f} | {diff_cash:>12.2f}{extra}")

    print("-" * 100)
    print(f"\nعدد الحسابات التي فيها فرق حقيقي: {flagged} من {len(ids)}")
    print(f"إجمالي صافي الفرق النقدي عبر كل الحسابات المعلَّمة: {total_cash_drift:.2f}")
    print("(صافي قريب من صفر يعني أن المبالغ انتقلت بين حسابات بدل أن تُفقد/تُخلَق من العدم -- متوقَّع لو السبب 'عدم عكس' حركة كانت متوازنة أصلاً)")
