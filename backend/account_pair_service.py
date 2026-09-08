"""account_pair_service.py
===========================
الطريق الوحيد المُعتمد لربط حساب مالي بحساب وزني (memo_account_id).

السياق الكامل: حادثة حساب #1213 (انظر diagnose_latest_office_reservation.py
وfix_office6_weight_account_1213_to_1074.py) كشفت أن memo_account_id كان
يُكتب مباشرة من 36 موضعاً مختلفاً في الكود بلا أي تحقق مشترك. تدقيق شامل
(audit_account_memo_invariants.py) أكَّد أن هذا ليس حادثة منفردة: وُجدت
عشرات حالات duplicate_target (حسابان مختلفان يطالبان بنفس الشريك) وone_way
link (ربط باتجاه واحد فقط) منتشرة فعلياً في قاعدة البيانات.

القاعدة المعتمدة من الآن: العلاقة financial <-> memo ثنائية (Bidirectional)
و1:1 (Unique) دائماً، ولا يجوز لأي كود في النظام تعديل memo_account_id
مباشرة -- يجب أن يمر عبر link_accounts()/unlink_account() هنا فقط، حتى
يستحيل بنيوياً تكرار حادثة #1213 (بدل الاعتماد على انتباه كل مطور لاحقاً).

ملاحظة عن النمط: التزمت بنمط الدوال المستقلة (لا class) ليطابق باقي ملفات
الخدمات في هذا المشروع (office_supplier_service.py، party_account_service.py)
بدل إدخال نمط class جديد لمجرد هذا الملف.

ما لا يفعله هذا الملف (نقل لاحق متعمَّد، لا إسقاط): لا يُهاجر أياً من 36
موضع الكتابة المباشرة الحالية لاستخدام هذه الخدمة -- ذلك نقل أوسع يحتاج
مراجعة كل موضع على حدة، ومرحلة منفصلة بعد تنظيف البيانات القائمة عبر
audit_account_memo_invariants.py.
"""

from __future__ import annotations

import json

from models import Account, AuditLog, JournalEntryLine, db


class AccountPairLinkError(ValueError):
    """تُرفع عند مخالفة أي قاعدة من قواعد ربط حساب مالي بحساب وزني."""


def link_accounts(
    financial: Account,
    memo: Account,
    *,
    created_by: str = 'system',
    auto_commit: bool = False,
) -> None:
    """يربط حسابين ربطاً ثنائياً (1:1)، فاسخاً أي ربط سابق على أي من
    الطرفين تلقائياً، ويسجّل العملية في AuditLog.

    القواعد المفروضة (ترفض العملية بالكامل، بلا تنفيذ جزئي، لو خالف أي منها):
      1. لا حساب يشير لنفسه.
      2. النوعان يجب أن يختلفا في tracks_weight (لا يجوز ربط مالي بمالي
         أو وزني بوزني).
      3. لا يجوز ربط حساب موسوم صراحةً كمتروك/مكرَّر (نفس علامات
         Account._DEPRECATED_ACCOUNT_MARKERS).

    بعد التحقق، تُفسخ تلقائياً:
      - أي ربط سابق لـfinancial مع شريك آخر غير memo.
      - أي ربط سابق لـmemo مع شريك آخر غير financial.
      - أي حساب ثالث كان يشير خطأً لـfinancial أو memo (duplicate_target).

    Raises:
        AccountPairLinkError: عند مخالفة أي قاعدة أعلاه.
    """
    if financial.id is None or memo.id is None:
        raise AccountPairLinkError('يجب حفظ (flush) كلا الحسابين قبل ربطهما (يحتاجان id).')

    if financial.id == memo.id:
        raise AccountPairLinkError(f'لا يمكن ربط حساب #{financial.id} بنفسه.')

    if bool(financial.tracks_weight) == bool(memo.tracks_weight):
        raise AccountPairLinkError(
            f'لا يجوز ربط حسابين من نفس النوع (tracks_weight متطابق لكليهما): '
            f'#{financial.id} و#{memo.id}.'
        )

    for acc in (financial, memo):
        if acc.name and any(m in acc.name for m in Account._DEPRECATED_ACCOUNT_MARKERS):
            raise AccountPairLinkError(
                f'لا يمكن ربط حساب #{acc.id} ({acc.name}) لأنه موسوم كمتروك/مكرَّر.'
            )

    # يضمن 1:1: أي حساب ثالث (غير الطرفين) كان يشير لأحدهما يُفسَخ ربطه.
    # يغطي تلقائياً حالة "الشريك القديم" لأي من الطرفين أيضاً (لو كان
    # financial.memo_account_id يشير سابقاً لحساب X != memo، فX من ضمن
    # هذا الاستعلام، فيُفسَخ ربطه دون حاجة لمعالجة خاصة).
    stale_pointers = Account.query.filter(
        Account.memo_account_id.in_([financial.id, memo.id]),
        Account.id.notin_([financial.id, memo.id]),
    ).all()
    for stale in stale_pointers:
        stale.memo_account_id = None
        db.session.add(stale)

    financial.memo_account_id = memo.id
    memo.memo_account_id = financial.id
    db.session.add(financial)
    db.session.add(memo)

    db.session.add(AuditLog(
        user_name=created_by or 'system',
        action='link_account_pair',
        entity_type='Account',
        entity_id=financial.id,
        entity_number=financial.account_number,
        details=json.dumps({
            'financial_account_id': financial.id,
            'financial_account_name': financial.name,
            'memo_account_id': memo.id,
            'memo_account_name': memo.name,
            'unlinked_stale_pointers': [s.id for s in stale_pointers],
        }, ensure_ascii=False),
        success=True,
    ))

    if auto_commit:
        db.session.commit()


def unlink_account(account: Account, *, created_by: str = 'system', auto_commit: bool = False) -> None:
    """يفسخ ربط حساب وشريكه (إن وُجد) من الطرفين معاً."""
    partner_id = account.memo_account_id
    if partner_id is None:
        return

    partner = Account.query.get(partner_id)
    account.memo_account_id = None
    db.session.add(account)
    if partner is not None and partner.memo_account_id == account.id:
        partner.memo_account_id = None
        db.session.add(partner)

    db.session.add(AuditLog(
        user_name=created_by or 'system',
        action='unlink_account_pair',
        entity_type='Account',
        entity_id=account.id,
        entity_number=account.account_number,
        details=json.dumps({
            'account_id': account.id,
            'account_name': account.name,
            'unlinked_partner_id': partner_id,
        }, ensure_ascii=False),
        success=True,
    ))

    if auto_commit:
        db.session.commit()


# ─── إزالة الحساب الموازي ─────────────────────────────────────────────────────

class AccountPairRemovalError(ValueError):
    """تُرفع عند رفض إزالة الحساب الموازي. .code يُميّز سبب الرفض."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _check_parallel_removable(account_id: int) -> None:
    """يتحقق من خلو الحساب من أي تبعية تمنع حذفه.
    يرفع AccountPairRemovalError فور اكتشاف أول تبعية.
    """
    from models import (AccountingMapping, Customer, Employee, Invoice,
                        Office, SafeBox, Settings, Supplier, VoucherAccountLine)
    from sqlalchemy import or_

    if Account.query.filter_by(parent_id=account_id).first():
        raise AccountPairRemovalError(
            'الحساب الموازي له حسابات فرعية', code='PARALLEL_HAS_CHILDREN')
    if JournalEntryLine.query.filter_by(account_id=account_id).first():
        raise AccountPairRemovalError(
            'الحساب الموازي له حركات محاسبية', code='PARALLEL_HAS_JE_LINES')
    if VoucherAccountLine.query.filter_by(account_id=account_id).first():
        raise AccountPairRemovalError(
            'الحساب الموازي له حركات في سندات', code='PARALLEL_HAS_VOUCHER_LINES')
    if Invoice.query.filter_by(wage_inventory_account_id=account_id).first():
        raise AccountPairRemovalError(
            'الحساب الموازي مستخدم في فواتير', code='PARALLEL_HAS_INVOICE_REF')
    if SafeBox.query.filter_by(account_id=account_id).first():
        raise AccountPairRemovalError(
            'الحساب الموازي مرتبط بخزينة', code='PARALLEL_IS_SAFEBOX')
    if AccountingMapping.query.filter_by(account_id=account_id).first():
        raise AccountPairRemovalError(
            'الحساب الموازي له ربط محاسبي تلقائي',
            code='PARALLEL_HAS_ACCOUNTING_MAPPING')
    settings = Settings.query.first()
    if settings and (
        settings.stones_pending_account_id == account_id
        or settings.stones_display_revenue_account_id == account_id
    ):
        raise AccountPairRemovalError(
            'الحساب الموازي مستخدم في إعدادات النظام',
            code='PARALLEL_HAS_SYSTEM_CONFIG')
    if Customer.query.filter(
        or_(Customer.account_id == account_id,
            Customer.account_category_id == account_id)
    ).first():
        raise AccountPairRemovalError(
            'الحساب الموازي مرتبط بعميل', code='PARALLEL_HAS_ENTITY_LINK')
    if Supplier.query.filter(
        or_(Supplier.account_id == account_id,
            Supplier.account_category_id == account_id)
    ).first():
        raise AccountPairRemovalError(
            'الحساب الموازي مرتبط بمورد', code='PARALLEL_HAS_ENTITY_LINK')
    if Office.query.filter_by(account_category_id=account_id).first():
        raise AccountPairRemovalError(
            'الحساب الموازي مرتبط بمكتب', code='PARALLEL_HAS_ENTITY_LINK')
    if Employee.query.filter_by(account_id=account_id).first():
        raise AccountPairRemovalError(
            'الحساب الموازي مرتبط بموظف', code='PARALLEL_HAS_ENTITY_LINK')


def remove_parallel_account(primary: Account, *, created_by: str = 'system') -> dict:
    """يُزيل الحساب الموازي لـprimary مع الحفاظ على primary نفسه.

    الترتيب (atomic — المُستدعي يتحكم في commit):
      1. تحقق من وجود الموازي.
      2. تحقق من خلوّه من أي تبعية.
      3. unlink_account() → فسخ الربط الثنائي + AuditLog للفسخ.
      4. حذف الموازي.
      5. AuditLog إضافي لعملية الإزالة الكاملة.

    Returns:
        dict بمعلومات الحساب المحذوف: {id, account_number, name}.

    Raises:
        AccountPairRemovalError: عند أي رفض — .code يحمل سبب الرفض.
    """
    if primary.memo_account_id is None:
        raise AccountPairRemovalError(
            'لا يوجد حساب موازٍ لهذا الحساب', code='NO_PARALLEL')

    parallel = Account.query.get(primary.memo_account_id)
    if parallel is None:
        raise AccountPairRemovalError(
            'الحساب الموازي المرتبط غير موجود', code='PARALLEL_NOT_FOUND')

    _check_parallel_removable(parallel.id)

    removed_info = {
        'id': parallel.id,
        'account_number': parallel.account_number,
        'name': parallel.name,
    }

    unlink_account(primary, created_by=created_by)
    db.session.delete(parallel)

    db.session.add(AuditLog(
        user_name=created_by or 'system',
        action='remove_parallel_account',
        entity_type='Account',
        entity_id=primary.id,
        entity_number=primary.account_number,
        details=json.dumps({
            'primary_account_id': primary.id,
            'primary_account_number': primary.account_number,
            'removed_parallel_id': removed_info['id'],
            'removed_parallel_number': removed_info['account_number'],
            'removed_parallel_name': removed_info['name'],
        }, ensure_ascii=False),
        success=True,
    ))

    return removed_info
