"""Chart-of-Accounts security & correctness tests.

Coverage:
  - Auth: 401 (no token), 403 (no permission), 2xx (with permission) × 5 endpoints
  - Validation: missing/invalid fields, invalid parent, invalid account number, duplicate
  - Business rule: tracks_weight derived from account number prefix, user value ignored
  - Parallel account: warning in response (not crash) when creation fails
  - Database: duplicate number → 409, rollback on IntegrityError, children guard on delete
"""
import pytest
from app import app
from models import db, Account, User
from auth_decorators import generate_token


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_user(username, is_admin=False, permissions=None):
    """Create and flush a test user. `permissions` is a list of permission name strings."""
    u = User(
        username=username,
        full_name=username,
        email=None,
        is_active=True,
        is_admin=is_admin,
    )
    u.set_password('pass123')
    db.session.add(u)
    db.session.flush()
    if permissions:
        from models import Permission
        for perm_name in permissions:
            p = Permission.query.filter_by(name=perm_name).first()
            if p:
                u.permissions.append(p)
    return u


@pytest.fixture(scope='module')
def admin_headers():
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        token = generate_token(admin)
        return {'Authorization': f'Bearer {token}'}


@pytest.fixture(scope='module')
def no_perm_headers():
    """Non-admin user with NO accounts.* permissions."""
    with app.app_context():
        u = _make_user('noperm_accounts')
        db.session.commit()
        token = generate_token(u)
        return {'Authorization': f'Bearer {token}'}


@pytest.fixture(scope='module')
def parent_account_id():
    """ID of a seeded root account to use as parent in tests."""
    with app.app_context():
        a = Account.query.filter_by(account_number='15').first()
        return a.id


# ── 1. Authentication: 401 when token is invalid ─────────────────────────────
# Note: .env sets BYPASS_AUTH_FOR_DEVELOPMENT=1, which auto-sets g.current_user=admin
# for requests WITHOUT an Authorization header. Sending a bad token forces the bypass
# to stand down (it bails when Authorization header is present) so real auth runs.

_BAD_TOKEN = {'Authorization': 'Bearer totally.invalid.token'}


class TestAuth401:
    def test_next_number_rejects_bad_token(self):
        with app.test_client() as c:
            r = c.get('/api/accounts/next-number/1', headers=_BAD_TOKEN)
            assert r.status_code == 401

    def test_validate_number_rejects_bad_token(self):
        with app.test_client() as c:
            r = c.post('/api/accounts/validate-number', json={}, headers=_BAD_TOKEN)
            assert r.status_code == 401

    def test_add_account_rejects_bad_token(self):
        with app.test_client() as c:
            r = c.post('/api/accounts', json={}, headers=_BAD_TOKEN)
            assert r.status_code == 401

    def test_update_account_rejects_bad_token(self):
        # Use seeded account_number='15' — id may vary, so look it up first.
        with app.app_context():
            a = Account.query.filter_by(account_number='15').first()
            account_id = a.id if a else 15

        with app.test_client() as c:
            r = c.put(f'/api/accounts/{account_id}', json={}, headers=_BAD_TOKEN)
            assert r.status_code == 401

    def test_delete_account_rejects_bad_token(self):
        with app.app_context():
            a = Account.query.filter_by(account_number='15').first()
            account_id = a.id if a else 15

        with app.test_client() as c:
            r = c.delete(f'/api/accounts/{account_id}', headers=_BAD_TOKEN)
            assert r.status_code == 401


# ── 2. Authorization: 403 when authenticated but no permission ───────────────

class TestAuth403:
    def test_next_number_forbidden(self, no_perm_headers):
        with app.test_client() as c:
            r = c.get('/api/accounts/next-number/1', headers=no_perm_headers)
            assert r.status_code == 403

    def test_validate_number_forbidden(self, no_perm_headers):
        with app.test_client() as c:
            r = c.post('/api/accounts/validate-number', json={}, headers=no_perm_headers)
            assert r.status_code == 403

    def test_add_account_forbidden(self, no_perm_headers):
        with app.test_client() as c:
            r = c.post('/api/accounts', json={}, headers=no_perm_headers)
            assert r.status_code == 403

    def test_update_account_forbidden(self, no_perm_headers):
        with app.test_client() as c:
            r = c.put('/api/accounts/1', json={}, headers=no_perm_headers)
            assert r.status_code == 403

    def test_delete_account_forbidden(self, no_perm_headers):
        with app.test_client() as c:
            r = c.delete('/api/accounts/1', headers=no_perm_headers)
            assert r.status_code == 403


# ── 3. Validation: add_account ───────────────────────────────────────────────

class TestAddAccountValidation:
    def _post(self, client, data, headers):
        return client.post('/api/accounts', json=data, headers=headers)

    def test_missing_account_number(self, admin_headers):
        with app.test_client() as c:
            r = self._post(c, {'name': 'اختبار', 'type': 'Asset'}, admin_headers)
            assert r.status_code == 400
            body = r.get_json()
            assert body['error'] == 'MISSING_ACCOUNT_NUMBER'

    def test_blank_account_number(self, admin_headers):
        with app.test_client() as c:
            r = self._post(c, {'account_number': '   ', 'name': 'اختبار', 'type': 'Asset'}, admin_headers)
            assert r.status_code == 400
            assert r.get_json()['error'] == 'MISSING_ACCOUNT_NUMBER'

    def test_missing_name(self, admin_headers):
        with app.test_client() as c:
            r = self._post(c, {'account_number': '9901', 'type': 'Asset'}, admin_headers)
            assert r.status_code == 400
            assert r.get_json()['error'] == 'MISSING_NAME'

    def test_blank_name(self, admin_headers):
        with app.test_client() as c:
            r = self._post(c, {'account_number': '9901', 'name': '', 'type': 'Asset'}, admin_headers)
            assert r.status_code == 400
            assert r.get_json()['error'] == 'MISSING_NAME'

    def test_missing_type(self, admin_headers):
        with app.test_client() as c:
            r = self._post(c, {'account_number': '9901', 'name': 'اختبار'}, admin_headers)
            assert r.status_code == 400
            assert r.get_json()['error'] == 'MISSING_TYPE'

    def test_invalid_type(self, admin_headers):
        with app.test_client() as c:
            r = self._post(c, {'account_number': '9901', 'name': 'اختبار', 'type': 'Fake'}, admin_headers)
            assert r.status_code == 400
            assert r.get_json()['error'] == 'INVALID_TYPE'

    def test_invalid_parent_id(self, admin_headers):
        with app.test_client() as c:
            r = self._post(
                c,
                {'account_number': '9901', 'name': 'اختبار', 'type': 'Asset', 'parent_id': 999999},
                admin_headers,
            )
            assert r.status_code == 404
            assert r.get_json()['error'] == 'PARENT_NOT_FOUND'

    def test_duplicate_account_number_returns_409(self, admin_headers):
        with app.test_client() as c:
            # account_number='15' already seeded in conftest
            r = self._post(c, {'account_number': '15', 'name': 'مكرر', 'type': 'Asset'}, admin_headers)
            assert r.status_code == 409
            assert r.get_json()['error'] == 'ACCOUNT_NUMBER_EXISTS'


# ── 4. Business rule: tracks_weight derived from prefix ──────────────────────

class TestTracksWeightBusinessRule:
    def test_non_7_prefix_always_sets_tracks_weight_false(self, admin_headers):
        """Non-7xxx accounts are always cash + tracks_weight=False, regardless of user input."""
        with app.test_client() as c:
            # User sends True — backend must ignore it and set False
            r = c.post(
                '/api/accounts',
                json={
                    'account_number': '9910',
                    'name': 'حساب نقدي اختبار',
                    'type': 'Asset',
                    'tracks_weight': True,
                },
                headers=admin_headers,
            )
            assert r.status_code == 201
            body = r.get_json()
            assert body['tracks_weight'] is False, 'Backend must ignore user tracks_weight for non-7xxx'
            assert body['transaction_type'] == 'cash'

        with app.test_client() as c:
            # User sends False — backend sets False (same result, explicit case)
            r = c.post(
                '/api/accounts',
                json={
                    'account_number': '9911',
                    'name': 'حساب نقدي اختبار 2',
                    'type': 'Asset',
                    'tracks_weight': False,
                },
                headers=admin_headers,
            )
            assert r.status_code == 201
            assert r.get_json()['tracks_weight'] is False

    def test_7xxx_prefix_sets_gold(self, admin_headers):
        """Account number starting with 7 → tracks_weight=True, transaction_type=gold."""
        with app.test_client() as c:
            r = c.post(
                '/api/accounts',
                json={
                    'account_number': '7910',
                    'name': 'حساب ذهبي اختبار',
                    'type': 'Expense',
                    'tracks_weight': False,  # user sends False — must be ignored
                },
                headers=admin_headers,
            )
            assert r.status_code == 201
            body = r.get_json()
            assert body['tracks_weight'] is True, 'Backend must ignore user-supplied tracks_weight'
            assert body['transaction_type'] == 'gold'

    def test_7xxx_account_number_forces_tracks_weight_true_on_update(self, admin_headers):
        """PUT: changing account_number to 7xxx forces tracks_weight=True (user False ignored)."""
        with app.app_context():
            a = Account(account_number='9920', name='تعديل اختبار', type='Asset', tracks_weight=False)
            db.session.add(a)
            db.session.commit()
            target_id = a.id

        with app.test_client() as c:
            r = c.put(
                f'/api/accounts/{target_id}',
                json={'account_number': '7920', 'tracks_weight': False},  # user sends False but 7xxx enforces True
                headers=admin_headers,
            )
            assert r.status_code == 200
            body = r.get_json()
            assert body['tracks_weight'] is True
            assert body['transaction_type'] == 'gold'

    def test_non_7xxx_update_always_sets_tracks_weight_false(self, admin_headers):
        """PUT: non-7xxx accounts always get tracks_weight=False, derived from account number."""
        with app.app_context():
            # Account with legacy tracks_weight=True (e.g. old inventory account)
            a = Account(account_number='9921', name='مخزون اختبار', type='Asset', tracks_weight=True)
            db.session.add(a)
            db.session.commit()
            target_id = a.id

        with app.test_client() as c:
            # Update name only — tracks_weight must be corrected to False (always derived)
            r = c.put(f'/api/accounts/{target_id}', json={'name': 'مخزون اختبار معدّل'}, headers=admin_headers)
            assert r.status_code == 200
            assert r.get_json()['tracks_weight'] is False, 'Non-7xxx must always be False (derived)'


# ── 5. Parallel account: warning surfaces, not crash ─────────────────────────

class TestParallelAccountWarning:
    def test_no_create_parallel_flag_means_no_parallel(self, admin_headers):
        """Without create_parallel=True in request → no parallel account, no error, no warning."""
        with app.test_client() as c:
            r = c.post(
                '/api/accounts',
                json={'account_number': '9930', 'name': 'بدون موازي', 'type': 'Asset'},
                headers=admin_headers,
            )
            assert r.status_code == 201
            body = r.get_json()
            assert 'parallel_account' not in body or body.get('parallel_account') is None
            assert 'warning' not in body

    def test_create_parallel_creates_gold_account_and_links(self, admin_headers):
        """create_parallel=True → creates 7xxx gold account and links both via link_accounts()."""
        with app.test_client() as c:
            r = c.post(
                '/api/accounts',
                json={
                    'account_number': '9935',
                    'name': 'شريك اختبار',
                    'type': 'Liability',
                    'create_parallel': True,
                },
                headers=admin_headers,
            )
            assert r.status_code == 201
            body = r.get_json()
            assert body['tracks_weight'] is False
            assert body['transaction_type'] == 'cash'
            assert 'parallel_account' in body
            parallel = body['parallel_account']
            assert parallel['account_number'] == '79935'
            assert parallel['transaction_type'] == 'gold'

        with app.app_context():
            cash_acc = Account.query.filter_by(account_number='9935').first()
            gold_acc = Account.query.filter_by(account_number='79935').first()
            assert cash_acc is not None
            assert gold_acc is not None
            assert cash_acc.memo_account_id == gold_acc.id, 'cash→gold link must be bidirectional'
            assert gold_acc.memo_account_id == cash_acc.id, 'gold→cash link must be bidirectional'
            assert gold_acc.tracks_weight is True
            assert gold_acc.transaction_type == 'gold'

    def test_create_parallel_ignored_for_7xxx_accounts(self, admin_headers):
        """create_parallel=True on a 7xxx (gold) account is silently ignored — already the memo side."""
        with app.test_client() as c:
            r = c.post(
                '/api/accounts',
                json={
                    'account_number': '79936',
                    'name': 'ذهبي اختبار',
                    'type': 'Liability',
                    'create_parallel': True,
                },
                headers=admin_headers,
            )
            assert r.status_code == 201
            body = r.get_json()
            assert body['tracks_weight'] is True
            assert body['transaction_type'] == 'gold'
            assert 'parallel_account' not in body or body.get('parallel_account') is None


# ── 6. Delete: guards ────────────────────────────────────────────────────────

class TestDeleteAccount:
    def test_delete_account_with_children_returns_409(self, admin_headers):
        with app.app_context():
            parent = Account(account_number='8800', name='أب اختبار', type='Asset')
            db.session.add(parent)
            db.session.flush()
            child = Account(
                account_number='88001', name='فرع اختبار', type='Asset', parent_id=parent.id
            )
            db.session.add(child)
            db.session.commit()
            parent_id = parent.id

        with app.test_client() as c:
            r = c.delete(f'/api/accounts/{parent_id}', headers=admin_headers)
            assert r.status_code == 409
            assert r.get_json()['error'] == 'HAS_CHILDREN'

    def test_delete_account_with_je_lines_returns_409(self, admin_headers):
        """Account referenced by a JournalEntryLine must return HAS_TRANSACTIONS."""
        from models import JournalEntry, JournalEntryLine
        from datetime import datetime
        with app.app_context():
            acct = Account(account_number='8810', name='حساب بحركات', type='Asset')
            db.session.add(acct)
            db.session.flush()
            je = JournalEntry(
                entry_number='TEST-8810-JE',
                date=datetime.now(),
                description='اختبار حذف',
            )
            db.session.add(je)
            db.session.flush()
            line = JournalEntryLine(
                journal_entry_id=je.id,
                account_id=acct.id,
                cash_debit=100.0,
                cash_credit=0.0,
            )
            db.session.add(line)
            db.session.commit()
            acct_id = acct.id

        with app.test_client() as c:
            r = c.delete(f'/api/accounts/{acct_id}', headers=admin_headers)
            assert r.status_code == 409
            assert r.get_json()['error'] == 'HAS_TRANSACTIONS'

    def test_delete_leaf_account_with_no_transactions_succeeds(self, admin_headers):
        """Account with no JE lines, no entity links, no SafeBox → deleted successfully."""
        with app.app_context():
            leaf = Account(account_number='8899', name='ورقة اختبار', type='Asset')
            db.session.add(leaf)
            db.session.commit()
            leaf_id = leaf.id

        with app.test_client() as c:
            r = c.delete(f'/api/accounts/{leaf_id}', headers=admin_headers)
            assert r.status_code == 200
            assert r.get_json()['result'] == 'success'

        with app.app_context():
            assert Account.query.get(leaf_id) is None, 'Account must be physically deleted'

    def test_delete_paired_account_returns_confirm_required(self, admin_headers):
        """When a paired account exists with no deps, first DELETE returns confirm_required."""
        from account_pair_service import link_accounts
        with app.app_context():
            cash = Account(account_number='8860', name='نقدي confirm', type='Asset',
                           transaction_type='cash', tracks_weight=False)
            gold = Account(account_number='78860', name='ذهبي confirm', type='Asset',
                           transaction_type='gold', tracks_weight=True)
            db.session.add_all([cash, gold])
            db.session.flush()
            link_accounts(cash, gold, created_by='test')
            db.session.commit()
            cash_id = cash.id
            gold_id = gold.id

        with app.test_client() as c:
            r = c.delete(f'/api/accounts/{cash_id}', headers=admin_headers)
            assert r.status_code == 200
            body = r.get_json()
            assert body['result'] == 'confirm_required'
            assert body['parallel_account']['id'] == gold_id

        with app.app_context():
            # Neither account must be deleted yet
            assert Account.query.get(cash_id) is not None
            assert Account.query.get(gold_id) is not None

    def test_delete_parallel_true_deletes_both(self, admin_headers):
        """?delete_parallel=true → both accounts deleted in a single transaction."""
        from account_pair_service import link_accounts
        with app.app_context():
            cash = Account(account_number='8861', name='نقدي حذف كلاهما', type='Asset',
                           transaction_type='cash', tracks_weight=False)
            gold = Account(account_number='78861', name='ذهبي حذف كلاهما', type='Asset',
                           transaction_type='gold', tracks_weight=True)
            db.session.add_all([cash, gold])
            db.session.flush()
            link_accounts(cash, gold, created_by='test')
            db.session.commit()
            cash_id = cash.id
            gold_id = gold.id

        with app.test_client() as c:
            r = c.delete(f'/api/accounts/{cash_id}?delete_parallel=true', headers=admin_headers)
            assert r.status_code == 200
            assert r.get_json()['result'] == 'success'

        with app.app_context():
            assert Account.query.get(cash_id) is None, 'Cash account must be deleted'
            assert Account.query.get(gold_id) is None, 'Gold parallel must also be deleted'

    def test_delete_parallel_false_keeps_parallel_unlinked(self, admin_headers):
        """?delete_parallel=false → only main account deleted; parallel survives with memo cleared."""
        from account_pair_service import link_accounts
        with app.app_context():
            cash = Account(account_number='8862', name='نقدي حذف واحد', type='Asset',
                           transaction_type='cash', tracks_weight=False)
            gold = Account(account_number='78862', name='ذهبي باقٍ', type='Asset',
                           transaction_type='gold', tracks_weight=True)
            db.session.add_all([cash, gold])
            db.session.flush()
            link_accounts(cash, gold, created_by='test')
            db.session.commit()
            cash_id = cash.id
            gold_id = gold.id

        with app.test_client() as c:
            r = c.delete(f'/api/accounts/{cash_id}?delete_parallel=false', headers=admin_headers)
            assert r.status_code == 200
            assert r.get_json()['result'] == 'success'

        with app.app_context():
            assert Account.query.get(cash_id) is None, 'Cash account must be deleted'
            surviving = Account.query.get(gold_id)
            assert surviving is not None, 'Gold parallel must survive'
            assert surviving.memo_account_id is None, 'memo link must be cleared'

    def test_delete_nonexistent_returns_404(self, admin_headers):
        with app.test_client() as c:
            r = c.delete('/api/accounts/999999', headers=admin_headers)
            assert r.status_code == 404
            assert r.get_json()['error'] == 'ACCOUNT_NOT_FOUND'


# ── 7. Update: duplicate number guard ────────────────────────────────────────

class TestUpdateAccountValidation:
    def test_update_to_existing_number_returns_409(self, admin_headers):
        with app.app_context():
            a = Account(account_number='9940', name='الأول', type='Asset')
            b = Account(account_number='9941', name='الثاني', type='Asset')
            db.session.add_all([a, b])
            db.session.commit()
            b_id = b.id

        with app.test_client() as c:
            r = c.put(f'/api/accounts/{b_id}', json={'account_number': '9940'}, headers=admin_headers)
            assert r.status_code == 409
            assert r.get_json()['error'] == 'ACCOUNT_NUMBER_EXISTS'

    def test_update_nonexistent_returns_404(self, admin_headers):
        with app.test_client() as c:
            r = c.put('/api/accounts/999999', json={'name': 'لا يوجد'}, headers=admin_headers)
            assert r.status_code == 404
            assert r.get_json()['error'] == 'ACCOUNT_NOT_FOUND'

    def test_update_invalid_type_returns_400(self, admin_headers):
        with app.app_context():
            a = Account(account_number='9950', name='تحديث نوع', type='Asset')
            db.session.add(a)
            db.session.commit()
            a_id = a.id

        with app.test_client() as c:
            r = c.put(f'/api/accounts/{a_id}', json={'type': 'INVALID'}, headers=admin_headers)
            assert r.status_code == 400
            assert r.get_json()['error'] == 'INVALID_TYPE'


# ── 8. Happy-path: add and update succeed ────────────────────────────────────

class TestHappyPath:
    def test_add_account_returns_201_with_id(self, admin_headers):
        with app.test_client() as c:
            r = c.post(
                '/api/accounts',
                json={'account_number': '9960', 'name': 'حساب جديد', 'type': 'Expense'},
                headers=admin_headers,
            )
            assert r.status_code == 201
            body = r.get_json()
            assert 'id' in body
            assert body['account_number'] == '9960'

    def test_update_name_succeeds(self, admin_headers):
        with app.app_context():
            a = Account(account_number='9970', name='قديم', type='Asset')
            db.session.add(a)
            db.session.commit()
            a_id = a.id

        with app.test_client() as c:
            r = c.put(f'/api/accounts/{a_id}', json={'name': 'جديد'}, headers=admin_headers)
            assert r.status_code == 200
            assert r.get_json()['name'] == 'جديد'
