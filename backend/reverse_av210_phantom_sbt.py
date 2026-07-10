"""
reverse_av210_phantom_sbt.py
==============================
يلغي الـ SafeBoxTransaction الوهمية التي أُنشئت بالخطأ لتصحيح AV210.

المشكلة:
  historical_gl_adjustment = تصحيح GL بحت، لا يوجد نقص نقدي في الخزينة.
  لكن apply() أنشأ SBT IN 3,700 — وهذا رفع رصيد الخزينة دون وجود IPs لتسويتها.

الحل:
  إنشاء SBT OUT 3,700 مقابل (reversal)، ثم تحديث السجل ليشير إلى null.
  القيد المحاسبي (JE#5154) يبقى كما هو — هو صحيح.
"""

import sys
sys.path.insert(0, "backend")
from app import app
from models import db, HistoricalClearingAdjustment, SafeBoxTransaction

HCA_ID   = 2          # adj لـ AV210
SBT_ID   = 7783       # الـ phantom SBT الذي يجب إلغاؤه
REVERSED_BY = 'admin'

with app.app_context():
    print("=== إلغاء Phantom SBT لـ AV210 ===\n")

    adj = HistoricalClearingAdjustment.query.get(HCA_ID)
    if not adj:
        print(f"❌ HCA id={HCA_ID} غير موجود")
        sys.exit(1)

    sbt = SafeBoxTransaction.query.get(SBT_ID)
    if not sbt:
        print(f"❌ SBT id={SBT_ID} غير موجود")
        sys.exit(1)

    print(f"HCA: id={adj.id}  type={adj.adjustment_type}  amount={adj.amount:,.2f}")
    print(f"SBT: id={sbt.id}  direction={sbt.direction}  amount={sbt.amount_cash:,.2f}")

    if sbt.direction != 'in' or sbt.ref_type != 'historical_clearing_adjustment':
        print("❌ السجل ليس phantom SBT — توقف")
        sys.exit(1)

    # إنشاء SBT OUT مقابل (reversal)
    reversal = SafeBoxTransaction(
        safe_box_id=sbt.safe_box_id,
        ref_type='historical_clearing_adjustment_reversal',
        ref_id=adj.id,
        direction='out',
        amount_cash=sbt.amount_cash,
        created_by=REVERSED_BY,
    )
    db.session.add(reversal)
    db.session.flush()

    # فصل الـ HCA عن الـ phantom SBT (القيد JE يبقى)
    adj.safe_box_transaction_id = None

    db.session.commit()

    print(f"\n✅ تم")
    print(f"   reversal SBT id = {reversal.id}  direction=out  amount={reversal.amount_cash:,.2f}")
    print(f"   HCA.safe_box_transaction_id → None")
    print(f"   JE#{adj.journal_entry_id} يبقى كما هو (تصحيح GL سليم)")
    print(f"\nرصيد مدى الآن = 0 (الفجوة أُلغيت)")
