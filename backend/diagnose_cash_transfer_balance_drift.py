"""
diagnose_cash_transfer_balance_drift.py
=============================================
تشخيص فقط (لا تعديل على الإطلاق) — لا --apply ولا أي كتابة لقاعدة البيانات.

السياق: فاتورة BUY-2026-080 (id=989) كانت تحمل سندي دفع PV-2026-00239/00240
(تحويل، 19600.00 + 10000.00 = 29600.00) موجَّهين خطأً لحساب الصندوق النقدي
الرئيسي (755) بدل حساب تحويل (757) -- نفس خلل التوجيه الذي عُثر عليه في
6 سندات أخرى. المستخدم ألغى ترحيل الفاتورة ثم حذفها لأنها كانت مكررة
(مسجَّلة فعلاً مرة أخرى)، فاختفى السند والقيد المرتبط بها تماماً (تأكَّد
عبر API الإنتاج: 404 لكليهما).

لكن delete_unposted_invoice (routes.py) يحذف JournalEntryLine/JournalEntry/
Voucher/VoucherAccountLine/SafeBoxTransaction مباشرة دون استدعاء
Account.update_balance() لعكس أثرها -- فإن كانت الفاتورة قد رُحِّلت
فعلياً قبل الحذف، يبقى احتمال أن balance_cash المخزَّن لحسابي 755 و757
لا يزال يحمل أثر الـ29600.00 الخاطئ، رغم اختفاء كل الأدلة (السند/القيد)
التي تثبت ذلك الآن.

هذا السكريبت يقارن فقط:
  - الرصيد المخزَّن (Account.balance_cash) -- القيمة المعروضة في الواجهة
  - الرصيد الفعلي المحسوَب من السجل المحاسبي (live_balances_by_account_ids)
    -- نفس الدالة المعتمدة في كل تسويات النظام، تجمع فقط القيود
    المرحَّلة (is_posted=True) غير المحذوفة

لو تطابقا: لا أثر متبقٍّ، لا حاجة لأي تصحيح بخصوص هذه الفاتورة المحذوفة.
لو اختلفا: الفرق هو ما يحتاج تصحيحاً (سكريبت منفصل لاحقاً، بعد مراجعة
الناتج هنا أولاً -- هذا السكريبت لا يغيّر أي شيء بنفسه).

تشغيل:
    docker cp backend/diagnose_cash_transfer_balance_drift.py yasargold-backend:/app/backend/
    docker exec yasargold-backend python backend/diagnose_cash_transfer_balance_drift.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import Account
from services.live_balances import live_balances_by_account_ids

CASH_ACCOUNT_ID = 755
BANK_TRANSFER_ACCOUNT_ID = 757
MADA_ACCOUNT_ID = 777  # للمقارنة فقط، لم تتأثر بهذه الفاتورة المحذوفة

with app.app_context():
    ids = [CASH_ACCOUNT_ID, BANK_TRANSFER_ACCOUNT_ID, MADA_ACCOUNT_ID]
    live = live_balances_by_account_ids(ids)

    print("حساب | الرصيد المخزَّن (balance_cash) | الرصيد الفعلي (من السجل المحاسبي) | الفرق")
    print("-" * 90)
    for acc_id in ids:
        acc = Account.query.get(acc_id)
        stored = float(getattr(acc, 'balance_cash', 0.0) or 0.0)
        actual = float(live.get(acc_id, {}).get('cash', 0.0))
        diff = round(stored - actual, 2)
        flag = "  <-- فرق حقيقي، يحتاج تصحيح" if abs(diff) > 0.01 else ""
        print(f"{acc_id} ({getattr(acc, 'name', '?')}): مخزَّن={stored:.2f}  فعلي={actual:.2f}  فرق={diff:.2f}{flag}")
