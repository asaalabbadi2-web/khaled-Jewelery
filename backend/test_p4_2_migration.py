"""
test_p4_2_migration.py — P4.2: Migration Unit Tests + Integration Gate
=======================================================================
يختبر:
  1. دوال PRE/POST-CHECK كـ unit tests خالصة (بدون DB)
  2. Idempotency: تشغيل المنطق مرتين لا يُعدِّل شيئاً
  3. سلامة رصيد الحساب 15 (على الإنتاج مع PYTEST_ALLOW_REAL_DB=1)
  4. invariant بعد التصحيح
"""
from __future__ import annotations

import importlib.util
import os
import sys
import pytest
from unittest.mock import MagicMock

# ─── import migration module (اسمه يبدأ برقم — لا يمكن import مباشر) ────────
_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    'alembic', 'versions',
    '20260908_fix_legacy_transaction_type_both.py',
)
_spec = importlib.util.spec_from_file_location('_p4_2_migration', _MIGRATION_PATH)
_mod  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_needs_fix    = _mod._needs_fix
_pre_check    = _mod._pre_check
_post_check   = _mod._post_check
_apply_update = _mod._apply_update
_TARGETS      = _mod._TARGETS

_IS_POSTGRES = os.getenv('PYTEST_ALLOW_REAL_DB', '').strip() in ('1', 'true', 'yes')


# ─── بناة بيانات اختبار ──────────────────────────────────────────────────────

def _make_row(**kw):
    """يبني صف مزيف يشبه SQLAlchemy Row."""
    defaults = {
        'id': 999,
        'transaction_type': 'both',
        'tracks_weight': True,
        'balance_cash': 0.0,
        'balance_21k': 0.0,
        'memo_account_id': None,
    }
    defaults.update(kw)
    row = MagicMock()
    for k, v in defaults.items():
        setattr(row, k, v)
    row._mapping = defaults
    return row


def _make_conn(rows_by_num: dict, je_counts: dict | None = None, rowcount: int = 5):
    """يبني connection مزيف يُرجع الصفوف المحددة."""
    je_counts = je_counts or {}
    conn = MagicMock()

    def _execute(stmt, params=None):
        params = params or {}
        result = MagicMock()

        # journal_entry_line COUNT
        if params and 'id' in params and 'journal_entry_line' in str(stmt):
            result.scalar.return_value = je_counts.get(params['id'], 0)
            return result

        # account SELECT by account_number
        if params and 'n' in params:
            row = rows_by_num.get(str(params['n']))
            result.fetchone.return_value = row
            return result

        # UPDATE
        result.rowcount = rowcount
        # invariant SELECT (returns empty by default)
        result.fetchall.return_value = []
        return result

    conn.execute.side_effect = _execute
    return conn


# ─── _needs_fix() ────────────────────────────────────────────────────────────

class TestNeedsFix:
    def test_both_true_needs_fix(self):
        assert _needs_fix(_make_row(transaction_type='both', tracks_weight=True))

    def test_both_false_needs_fix(self):
        assert _needs_fix(_make_row(transaction_type='both', tracks_weight=False))

    def test_cash_true_needs_fix(self):
        assert _needs_fix(_make_row(transaction_type='cash', tracks_weight=True))

    def test_cash_false_no_fix(self):
        assert not _needs_fix(_make_row(transaction_type='cash', tracks_weight=False))

    def test_gold_true_needs_fix(self):
        assert _needs_fix(_make_row(transaction_type='gold', tracks_weight=True))


# ─── _pre_check() unit tests ─────────────────────────────────────────────────

class TestPreCheck:
    def _all_clean_rows(self, **override_by_num):
        rows = {}
        for num in _TARGETS:
            rows[num] = _make_row(
                id=int(num) if num.isdigit() else hash(num),
                transaction_type='both',
                tracks_weight=(num != '15'),
                balance_cash=(10000.0 if num == '15' else 0.0),
                memo_account_id=None,
            )
        for num, kw in override_by_num.items():
            for k, v in kw.items():
                setattr(rows[num], k, v)
                rows[num]._mapping[k] = v
        return rows

    def test_all_targets_pass_clean_state(self):
        conn = _make_conn(self._all_clean_rows())
        snapshot = _pre_check(conn)
        assert set(snapshot.keys()) == set(_TARGETS.keys())
        for num, s in snapshot.items():
            assert not s.get('_skip')

    def test_already_correct_marked_skip(self):
        rows = self._all_clean_rows()
        setattr(rows['400'], 'transaction_type', 'cash')
        setattr(rows['400'], 'tracks_weight', False)
        rows['400']._mapping['transaction_type'] = 'cash'
        rows['400']._mapping['tracks_weight'] = False
        conn = _make_conn(rows)
        snapshot = _pre_check(conn)
        assert snapshot['400'].get('_skip') is True
        assert not snapshot['521'].get('_skip')

    def test_fails_if_account_missing(self):
        rows = self._all_clean_rows()
        del rows['521']
        conn = _make_conn(rows)
        with pytest.raises(RuntimeError, match='PRE-CHECK FAIL.*521.*غير موجود'):
            _pre_check(conn)

    def test_fails_if_unexpected_transaction_type(self):
        rows = self._all_clean_rows()
        setattr(rows['400'], 'transaction_type', 'gold')
        rows['400']._mapping['transaction_type'] = 'gold'
        conn = _make_conn(rows)
        with pytest.raises(RuntimeError, match='PRE-CHECK FAIL.*400.*gold'):
            _pre_check(conn)

    def test_fails_if_has_memo_account(self):
        rows = self._all_clean_rows()
        setattr(rows['521'], 'memo_account_id', 99)
        rows['521']._mapping['memo_account_id'] = 99
        conn = _make_conn(rows)
        with pytest.raises(RuntimeError, match='PRE-CHECK FAIL.*521.*memo_account_id'):
            _pre_check(conn)

    def test_fails_if_non15_has_je_lines(self):
        rows = self._all_clean_rows()
        acc_id = rows['400'].id
        conn = _make_conn(rows, je_counts={acc_id: 3})
        with pytest.raises(RuntimeError, match='PRE-CHECK FAIL.*400.*3.*سطر'):
            _pre_check(conn)

    def test_account_15_je_lines_allowed(self):
        rows = self._all_clean_rows()
        acc_id = rows['15'].id
        conn = _make_conn(rows, je_counts={acc_id: 10})
        # يجب أن لا يُخطئ
        snapshot = _pre_check(conn)
        assert '15' in snapshot

    def test_fails_if_non15_has_balance(self):
        rows = self._all_clean_rows()
        setattr(rows['1200'], 'balance_cash', 500.0)
        rows['1200']._mapping['balance_cash'] = 500.0
        conn = _make_conn(rows)
        with pytest.raises(RuntimeError, match='PRE-CHECK FAIL.*1200.*رصيد'):
            _pre_check(conn)

    def test_account_15_balance_allowed(self):
        rows = self._all_clean_rows()
        conn = _make_conn(rows)
        snapshot = _pre_check(conn)
        assert snapshot['15']['balance_cash'] == 10000.0


# ─── _post_check() unit tests ────────────────────────────────────────────────

class TestPostCheck:
    def _make_post_conn(self, *, balance_15=0.0, bad_num=None,
                        bad_type=None, bad_tw=False, invariant_violations=None):
        """يبني conn للـ post-check."""
        conn = MagicMock()
        inv_rows = invariant_violations or []

        def _execute(stmt, params=None):
            params = params or {}
            result = MagicMock()
            stmt_str = str(stmt)

            if 'LIKE' in stmt_str or 'gold' in stmt_str.lower():
                result.fetchall.return_value = inv_rows
                return result

            num = (params or {}).get('n', '')
            row = MagicMock()
            is_bad = (num == bad_num)
            row.transaction_type = (bad_type if bad_type is not None else 'cash') if is_bad else 'cash'
            row.tracks_weight    = bad_tw if is_bad else False
            row.balance_cash     = balance_15 if num == '15' else 0.0
            result.fetchone.return_value = row
            return result

        conn.execute.side_effect = _execute
        return conn

    def test_passes_all_correct(self):
        snapshot = {n: {'transaction_type': 'both', 'tracks_weight': True,
                        'balance_cash': (10000.0 if n == '15' else 0.0),
                        '_skip': False}
                    for n in _TARGETS}
        conn = self._make_post_conn(balance_15=10000.0)
        _post_check(conn, snapshot)  # لا استثناء

    def test_fails_if_type_not_cash(self):
        snapshot = {n: {'_skip': False} for n in _TARGETS}
        conn = self._make_post_conn(bad_num='400', bad_type='both')
        with pytest.raises(RuntimeError, match='POST-CHECK FAIL.*400.*both'):
            _post_check(conn, snapshot)

    def test_fails_if_tracks_weight_true(self):
        snapshot = {n: {'_skip': False} for n in _TARGETS}
        conn = self._make_post_conn(bad_num='521', bad_tw=True)
        with pytest.raises(RuntimeError, match='POST-CHECK FAIL.*521.*tracks_weight'):
            _post_check(conn, snapshot)

    def test_fails_if_balance_15_changed(self):
        snapshot = {'15': {'balance_cash': 10000.0, '_skip': False},
                    **{n: {'_skip': False} for n in _TARGETS if n != '15'}}
        conn = self._make_post_conn(balance_15=9999.0)
        with pytest.raises(RuntimeError, match='POST-CHECK FAIL.*رصيد.*15'):
            _post_check(conn, snapshot)

    def test_fails_on_invariant_violation(self):
        snapshot = {n: {'_skip': True} for n in _TARGETS}
        inv_row = MagicMock()
        inv_row.account_number = '1500'
        inv_row.name = 'حساب سيء'
        conn = self._make_post_conn(invariant_violations=[inv_row])
        with pytest.raises(RuntimeError, match='INVARIANT FAIL.*1500'):
            _post_check(conn, snapshot)

    def test_skip_accounts_still_verified(self):
        """حسابات _skip=True لا تزال تُفحص في post-check."""
        snapshot = {n: {'_skip': True} for n in _TARGETS}
        conn = self._make_post_conn(bad_num='400', bad_type='both')
        with pytest.raises(RuntimeError, match='POST-CHECK FAIL.*400'):
            _post_check(conn, snapshot)


# ─── Idempotency unit test ────────────────────────────────────────────────────

class TestIdempotency:
    def test_all_already_correct_returns_zero(self):
        rows = {}
        for num in _TARGETS:
            rows[num] = _make_row(
                id=hash(num),
                transaction_type='cash',
                tracks_weight=False,
                balance_cash=(10000.0 if num == '15' else 0.0),
                memo_account_id=None,
            )
        conn = _make_conn(rows)
        snapshot = _pre_check(conn)
        rows_changed = _apply_update(conn, snapshot)
        assert rows_changed == 0


# ─── Integration tests (تحتاج PYTEST_ALLOW_REAL_DB=1) ─────────────────────────

@pytest.mark.skipif(not _IS_POSTGRES, reason='يحتاج PostgreSQL — شغّل مع PYTEST_ALLOW_REAL_DB=1')
class TestP42IntegrationProduction:
    """
    يتحقق من الحالة الحالية في إنتاج — لا يُطبِّق migration.
    هدفه: التحقق أن الحسابات ما زالت في الحالة المتوقعة قبل التطبيق الفعلي.
    """

    def test_preconditions_pass_on_current_production_state(self):
        """
        يتحقق أن _pre_check تنجح على الإنتاج الحالي
        (ما لم تكن المـigration طُبِّقت مسبقاً — حينها كل الحسابات _skip=True).
        """
        from app import app
        from models import db

        with app.app_context():
            conn = db.engine.connect()
            try:
                snapshot = _pre_check(conn)
                # التحقق من أن كل الحسابات المستهدفة وُجدت
                for num in _TARGETS:
                    assert num in snapshot, f'الحساب {num} غير موجود في الإنتاج'
            finally:
                conn.close()

    def test_account_15_balance_is_positive(self):
        """الحساب 15 يجب أن يكون له رصيد نقدي > 0 (يُثبت أنه حساب نشط)."""
        from app import app
        from models import Account

        with app.app_context():
            acc = Account.query.filter_by(account_number='15').first()
            assert acc is not None, 'الحساب 15 (صندوق النقدية) غير موجود'
            assert float(acc.balance_cash or 0) > 0, (
                f'الحساب 15 رصيده {acc.balance_cash} — يُتوقع > 0'
            )

    def test_all_target_accounts_have_transaction_type_both_or_cash(self):
        """
        قبل Migration: كل حساب مستهدف يجب أن يكون 'both' أو 'cash' (لا 'gold').
        بعد Migration: كل الحسابات ستكون 'cash'.
        """
        from app import app
        from models import Account

        with app.app_context():
            for num in _TARGETS:
                acc = Account.query.filter_by(account_number=num).first()
                assert acc is not None, f'الحساب {num} غير موجود'
                assert acc.transaction_type in ('both', 'cash'), (
                    f'الحساب {num} لديه transaction_type={acc.transaction_type} — '
                    'غير متوقع قبل P4.2'
                )

    def test_no_target_account_has_memo_account_id(self):
        """لا يجب أن يكون لأي حساب مستهدف memo_account_id."""
        from app import app
        from models import Account

        with app.app_context():
            for num in _TARGETS:
                acc = Account.query.filter_by(account_number=num).first()
                if acc:
                    assert acc.memo_account_id is None, (
                        f'الحساب {num} لديه memo_account_id={acc.memo_account_id} — '
                        'غير متوقع'
                    )

    def test_non15_accounts_have_zero_je_lines(self):
        """الحسابات 400, 521, 1200, 1220 لا يجب أن يكون لها JE lines."""
        from app import app
        from models import Account, JournalEntryLine

        with app.app_context():
            for num in ('400', '521', '1200', '1220'):
                acc = Account.query.filter_by(account_number=num).first()
                if acc:
                    count = JournalEntryLine.query.filter_by(account_id=acc.id).count()
                    assert count == 0, (
                        f'الحساب {num} له {count} سطر قيد — '
                        'يتعارض مع نتائج P4.1.5'
                    )
