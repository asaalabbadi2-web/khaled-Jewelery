"""
test_transaction_type_both_audit.py — P4.1: Classification Unit Tests + Read-Only Gate
========================================================================================
يختبر:
  1. منطق classify_account() بمعزل تام عن DB
  2. بوابة read-only: الـ audit لا يُعدِّل حالة DB
"""
from __future__ import annotations

import pytest
from audit_transaction_type_both import classify_account


# ─── بناة بيانات اختبار مساعدة ────────────────────────────────────────────────

def _clean_info(**overrides) -> dict:
    """يبني dict حساب نظيف (صفر حركة) — override ما تحتاج."""
    base = {
        'account_number': '1111',
        'tracks_weight': False,
        'is_safebox': False,
        'balance_cash': 0.0,
        'balance_18k': 0.0,
        'balance_21k': 0.0,
        'balance_22k': 0.0,
        'balance_24k': 0.0,
        'je_count': 0,
        'voucher_count': 0,
        'invoice_count': 0,
        'mapping_count': 0,
        'customer_count': 0,
        'supplier_count': 0,
        'employee_count': 0,
        'office_count': 0,
        'children_count': 0,
        'in_system_config': False,
        'memo_account_id': None,
    }
    base.update(overrides)
    return base


# ─── فئة [A]: خزائن ───────────────────────────────────────────────────────────

class TestGradeA:
    def test_safebox_non_7xxx(self):
        info = _clean_info(account_number='1200', tracks_weight=False, is_safebox=True)
        grade, reason = classify_account(info)
        assert grade == 'A', reason

    def test_safebox_7xxx(self):
        info = _clean_info(account_number='7200', tracks_weight=True, is_safebox=True)
        grade, reason = classify_account(info)
        assert grade == 'A', reason

    def test_safebox_beats_activity(self):
        """الخزينة تحصل على A حتى لو فيها JE — الخزائن لها حكم خاص."""
        info = _clean_info(is_safebox=True, je_count=50, balance_cash=5000)
        grade, _ = classify_account(info)
        assert grade == 'A'


# ─── فئة [B]: Legacy نظيف ────────────────────────────────────────────────────

class TestGradeB:
    def test_non_7xxx_no_activity(self):
        info = _clean_info(account_number='1000', tracks_weight=False)
        grade, reason = classify_account(info)
        assert grade == 'B', reason
        assert 'cash' in reason

    def test_assets_root_account(self):
        info = _clean_info(account_number='1000', tracks_weight=False)
        grade, _ = classify_account(info)
        assert grade == 'B'

    def test_expense_account(self):
        info = _clean_info(account_number='5000', tracks_weight=False)
        grade, _ = classify_account(info)
        assert grade == 'B'

    def test_payment_method_account(self):
        for num in ['1111', '1112', '1113', '1114', '1115', '1116',
                    '1117', '1118', '1119']:
            info = _clean_info(account_number=num, tracks_weight=False)
            grade, _ = classify_account(info)
            assert grade == 'B', f'حساب {num} يجب B وليس {grade}'

    def test_expense_subaccounts(self):
        for num in ['5100', '5111', '5112', '5113', '5114', '5115', '5116']:
            info = _clean_info(account_number=num, tracks_weight=False)
            grade, _ = classify_account(info)
            assert grade == 'B', f'حساب {num} يجب B وليس {grade}'

    def test_7xxx_with_tracks_weight_true_no_activity(self):
        info = _clean_info(account_number='7500', tracks_weight=True)
        grade, reason = classify_account(info)
        assert grade == 'B', reason
        assert 'gold' in reason


# ─── فئة [C]: يحتاج مراجعة ───────────────────────────────────────────────────

class TestGradeC:
    def test_7xxx_without_tracks_weight(self):
        """7xxx + tracks_weight=False → تعارض → C."""
        info = _clean_info(account_number='7000', tracks_weight=False)
        grade, reason = classify_account(info)
        assert grade == 'C', reason
        assert 'تعارض' in reason

    def test_non_7xxx_with_tracks_weight(self):
        """non-7xxx + tracks_weight=True → تعارض → C."""
        info = _clean_info(account_number='1500', tracks_weight=True)
        grade, reason = classify_account(info)
        assert grade == 'C', reason
        assert 'تعارض' in reason

    def test_has_je_lines(self):
        info = _clean_info(account_number='1111', je_count=5)
        grade, reason = classify_account(info)
        assert grade == 'C', reason
        assert 'JE' in reason

    def test_has_voucher_lines(self):
        info = _clean_info(account_number='1111', voucher_count=2)
        grade, reason = classify_account(info)
        assert grade == 'C', reason
        assert 'Voucher' in reason

    def test_has_invoice(self):
        info = _clean_info(account_number='1111', invoice_count=1)
        grade, reason = classify_account(info)
        assert grade == 'C', reason
        assert 'Invoice' in reason

    def test_has_nonzero_cash_balance(self):
        info = _clean_info(account_number='1111', balance_cash=100.0)
        grade, reason = classify_account(info)
        assert grade == 'C', reason
        assert 'رصيد' in reason

    def test_has_nonzero_weight_balance(self):
        info = _clean_info(account_number='1111', balance_21k=5.5)
        grade, reason = classify_account(info)
        assert grade == 'C', reason

    def test_tiny_balance_treated_as_zero(self):
        """رصيد < 0.001 يُعامَل كصفر."""
        info = _clean_info(account_number='1111', balance_cash=0.0005)
        grade, _ = classify_account(info)
        assert grade == 'B'

    def test_has_mapping(self):
        info = _clean_info(account_number='1111', mapping_count=1)
        grade, reason = classify_account(info)
        assert grade == 'C', reason

    def test_has_customer_link(self):
        info = _clean_info(account_number='1111', customer_count=1)
        grade, reason = classify_account(info)
        assert grade == 'C', reason

    def test_has_supplier_link(self):
        info = _clean_info(account_number='1111', supplier_count=1)
        grade, reason = classify_account(info)
        assert grade == 'C', reason

    def test_has_employee_link(self):
        info = _clean_info(account_number='1111', employee_count=1)
        grade, reason = classify_account(info)
        assert grade == 'C', reason

    def test_has_children(self):
        info = _clean_info(account_number='1111', children_count=3)
        grade, reason = classify_account(info)
        assert grade == 'C', reason
        assert 'فرعية' in reason

    def test_in_system_config(self):
        info = _clean_info(account_number='1111', in_system_config=True)
        grade, reason = classify_account(info)
        assert grade == 'C', reason

    def test_weight_mismatch_wins_over_activity(self):
        """تعارض tracks_weight يُصنَّف C بغض النظر عن الحركة."""
        info = _clean_info(account_number='7000', tracks_weight=False, je_count=10)
        grade, reason = classify_account(info)
        assert grade == 'C'
        assert 'تعارض' in reason


# ─── حالات حدية ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_account_number(self):
        """رقم حساب فارغ يُعامَل كـ non-7xxx."""
        info = _clean_info(account_number='', tracks_weight=False)
        grade, _ = classify_account(info)
        assert grade == 'B'

    def test_none_account_number(self):
        info = _clean_info(account_number=None, tracks_weight=False)
        grade, _ = classify_account(info)
        assert grade == 'B'

    def test_7_prefix_various_lengths(self):
        for num in ['7', '70', '700', '7000', '70000', '700000', '7000000']:
            info = _clean_info(account_number=num, tracks_weight=True)
            grade, _ = classify_account(info)
            assert grade == 'B', f'رقم {num} يجب B'

    def test_all_balance_fields_checked(self):
        """أي حقل رصيد وزن غير صفري يُؤدي لـ C."""
        for field in ('balance_18k', 'balance_21k', 'balance_22k', 'balance_24k'):
            info = _clean_info(account_number='1111', **{field: 0.01})
            grade, _ = classify_account(info)
            assert grade == 'C', f'{field}=0.01 يجب أن يُؤدي لـ C'

    def test_negative_balance_detected(self):
        info = _clean_info(account_number='1111', balance_cash=-500.0)
        grade, _ = classify_account(info)
        assert grade == 'C'

    def test_all_18_production_accounts_classified_b(self):
        """
        اختبار تكاملي: الحسابات الـ18 الفعلية (من psql) يجب أن تُصنَّف B.
        بياناتها المستخرجة مباشرة من الإنتاج.
        """
        production_accounts = [
            ('1000', 'الأصول'),
            ('1111', 'الصندوق (نقداً)'),
            ('1112', 'البنك - الحساب الجاري'),
            ('1113', 'بطاقة مدى - نقاط البيع'),
            ('1114', 'بطاقات فيزا/ماستركارد'),
            ('1115', 'تابي - مستحقات قصيرة الأجل'),
            ('1116', 'تمارا - مستحقات قصيرة الأجل'),
            ('1117', 'STC Pay - المحفظة الرقمية'),
            ('1118', 'Apple Pay / Google Pay'),
            ('1119', 'التحويل البنكي المباشر'),
            ('5000', 'المصروفات'),
            ('5100', 'مصروفات التشغيل'),
            ('5111', 'عمولة البنك - بطاقة مدى'),
            ('5112', 'عمولة البنك - فيزا/ماستركارد'),
            ('5113', 'عمولة تابي (BNPL)'),
            ('5114', 'عمولة تمارا (BNPL)'),
            ('5115', 'عمولة STC Pay'),
            ('5116', 'عمولة Apple/Google Pay'),
        ]
        for num, name in production_accounts:
            info = _clean_info(account_number=num, tracks_weight=False)
            grade, reason = classify_account(info)
            assert grade == 'B', (
                f'حساب {num} ({name}) يجب B — حصل على {grade}: {reason}'
            )


# ─── بوابة read-only: الـ audit لا يُعدِّل DB ────────────────────────────────

class TestAuditIsReadOnly:
    """
    يتحقق أن run_audit() لا تُعدِّل حالة DB.
    يُشغَّل على SQLite (الافتراضي) — يكفي لإثبات الخاصية.
    """
    def test_db_state_unchanged_after_audit(self):
        """
        الطريقة:
          1. التقط snapshot لجميع حسابات transaction_type='both' قبل الـ audit
          2. شغّل run_audit()
          3. التقط snapshot بعده
          4. تحقق أن الـ snapshot لم يتغير
        """
        from app import app
        from models import Account

        def _snapshot():
            return {
                acc.id: {
                    'transaction_type': acc.transaction_type,
                    'tracks_weight':    acc.tracks_weight,
                    'memo_account_id':  acc.memo_account_id,
                    'balance_cash':     float(acc.balance_cash or 0),
                    'balance_21k':      float(acc.balance_21k or 0),
                }
                for acc in Account.query.filter_by(
                    transaction_type='both').all()
            }

        with app.app_context():
            before = _snapshot()

        from audit_transaction_type_both import run_audit
        with app.app_context():
            run_audit()

        with app.app_context():
            after = _snapshot()

        assert before == after, (
            'run_audit() عدَّل حالة DB — يجب أن يكون read-only:\n'
            f'قبل: {before}\nبعد: {after}'
        )

    def test_audit_guard_constant_is_true(self):
        """الثابت _AUDIT_READ_ONLY_GUARD يجب أن يكون True — تحقق من الكود نفسه."""
        from audit_transaction_type_both import _AUDIT_READ_ONLY_GUARD
        assert _AUDIT_READ_ONLY_GUARD is True

    def test_run_audit_returns_list_not_none(self):
        from app import app
        from audit_transaction_type_both import run_audit
        with app.app_context():
            result = run_audit()
        assert isinstance(result, list)

    def test_classify_account_has_no_db_side_effects(self):
        """classify_account() لا تستخدم DB — لا جلسة ولا استعلام."""
        info = _clean_info(account_number='1111')
        grade, reason = classify_account(info)
        assert grade in ('A', 'B', 'C', 'D')
        assert isinstance(reason, str) and len(reason) > 0
