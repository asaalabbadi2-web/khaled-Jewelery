"""settlement_state_service.py
===============================
نقطة القراءة الوحيدة لـ"كم سُوِّي من هذه الدفعة فعلاً" -- يستبدل 10 نسخاً
متطابقة من `SUM(SettlementLine.amount_settled) GROUP BY invoice_payment_id`
كانت موزَّعة بين routes.py وclearing_settlement_scheduler.py (انظر
PAYMENT_LIFECYCLE_ARCHITECTURE.md لتفاصيل الاكتشاف الكامل).

تنبيه مهم -- استثناء واحد متعمَّد، غير موحَّد بعد (انظر التعليق الكامل
INTENTIONAL DIVERGENCE في routes.py حول السطر 31097):
  routes.py (عند إنشاء سند تسوية جديد، حادثة الإنتاج AV-2026-00133) يفلتر
  بشرط `Voucher.status == 'approved'` -- الموضع الوحيد من أصل 10 الذي يفعل
  ذلك. تحقّق إنتاجي (2026-06-30، diagnose_cancelled_settlement_impact.py)
  أثبت أن هذا فرق حقيقي وليس تكراراً تافهاً: سند تسوية مُلغى
  (cancel_voucher لا يحذف SettlementLine المرتبط به) يجعل الـ9 مواضع
  الأخرى تعتبر الدفعة "مسوّاة" للأبد رغم أن المال لم يتحرك -- أثر فعلي
  مؤكَّد: 9 دفعات، 27,820 ريال، عبر 4 سندات ملغاة على الإنتاج.

  ما تُرجعه هذه الدوال حالياً (get_settled_amounts/get_settled_amount) هو
  "Raw Settled Amount" -- مجموع كل SettlementLine بلا فلتر، مطابق تماماً
  لسلوك الـ9 مواضع قبل هذا الترحيل (لا تغيير وظيفي). "Effective Settled
  Amount" (مجموع السندات المعتمدة فقط -- ما يطابق الواقع الاقتصادي فعلياً
  حسب بيانات الإنتاج) **لا توجد بعد كدالة هنا**؛ قرار تعميمها على الـ10
  مواضع معلَّق، بانتظار حسم العمل مع المستخدم.

  حين يُحسَم القرار: لا تُغيَّر دلالة get_settled_amounts() الحالية --
  أضِف get_raw_settled_amount(s) (إعادة تسمية واضحة لما هو موجود) و
  get_effective_settled_amount(s) (الفلتر الجديد) كدالتين منفصلتين
  بمعنيين واضحين، ثم رحِّل كل موضع استهلاك بقرار صريح خاص به -- لا تغييراً
  جماعياً صامتاً لدالة واحدة قد تعتمد عليها أجزاء مختلفة من النظام.
"""

from __future__ import annotations

from sqlalchemy import func

from models import db, SettlementLine

SETTLEMENT_EPSILON = 0.005


def get_settled_amounts(invoice_payment_ids: list[int]) -> dict[int, float]:
    """إجمالي amount_settled لكل invoice_payment_id، عبر كل السندات بلا أي
    فلتر على حالتها (مطابق للسلوك الحالي في كل المواضع غير المستثناة أعلاه)."""
    ids = [i for i in (invoice_payment_ids or []) if i is not None]
    if not ids:
        return {}
    rows = (
        db.session.query(
            SettlementLine.invoice_payment_id,
            func.coalesce(func.sum(SettlementLine.amount_settled), 0.0),
        )
        .filter(SettlementLine.invoice_payment_id.in_(ids))
        .group_by(SettlementLine.invoice_payment_id)
        .all()
    )
    return {r[0]: float(r[1]) for r in rows}


def get_settled_amount(invoice_payment_id: int) -> float:
    """نسخة مفردة من get_settled_amounts لموضع واحد فقط."""
    return get_settled_amounts([invoice_payment_id]).get(invoice_payment_id, 0.0)


def is_locked(invoice_payment_id: int) -> bool:
    """True لو أي مبلغ من هذه الدفعة دخل تسوية فعلية (بغض النظر عن حالة
    السند -- مطابق لحارس routes.py:9266-9281 الحالي حرفياً)."""
    return get_settled_amount(invoice_payment_id) > SETTLEMENT_EPSILON
