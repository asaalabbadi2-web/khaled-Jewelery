"""Integration tests for Inventory API blueprint (/api/inventory/).

Tests hit the actual Flask test client with a real in-memory DB.
Auth is bypassed via the test_client fixture (no JWT required in test mode).

Covers:
  GET  /api/inventory/balance               → 200, returns bucket list
  GET  /api/inventory/balance?branch_id=X   → filtered
  GET  /api/inventory/balance/summary       → by_branch + by_karat + grand_total
  GET  /api/inventory/count                 → empty list initially
  POST /api/inventory/count                 → 201, session opened + lines populated
  GET  /api/inventory/count/<id>            → session detail with lines
  PUT  /api/inventory/count/<id>/entry      → 200, variance computed
  POST /api/inventory/count/<id>/close      → 200, status=closed
  POST /api/inventory/count/<id>/approve    → 200, status=approved, adjustment returned
  POST /api/inventory/adjustment            → 201, manual adjustment
  GET  /api/inventory/adjustment/<id>       → 200, detail + lines
  GET  /api/inventory/reconciliation        → 200, is_clean + rows
  GET  /api/inventory/health                → 200, has ledger_row_count

Auth:
  Tests use a helper that patches g.current_user so require_permission passes.
"""
from __future__ import annotations

import itertools
import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app import app
from models import db, Branch, Category, Invoice, InvoiceItem
from services.inventory_posting_service import InventoryPostingService

_id_seq = itertools.count(900_000)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


# access_token and auth_headers are provided by conftest.py fixtures


def _uid(p='x'):
    return f'{p}-{uuid.uuid4().hex[:6]}'


def _branch():
    b = Branch(name=_uid('فرع'), branch_code=_uid('BR'))
    db.session.add(b); db.session.flush()
    return b


def _category():
    c = Category(name=_uid('تصنيف'))
    db.session.add(c); db.session.flush()
    return c


def _post_invoice(itype, branch_id, cat_id, karat, weight):
    inv = Invoice(
        invoice_type_id=next(_id_seq), invoice_type=itype,
        date=datetime.now(), total=0.0, is_posted=True,
        posted_by='test', branch_id=branch_id,
    )
    db.session.add(inv); db.session.flush()
    item = InvoiceItem(
        invoice_id=inv.id, quantity=1, price=0.0,
        karat=karat, weight=weight, category_id=cat_id,
    )
    db.session.add(item); db.session.flush()
    db.session.refresh(inv)
    InventoryPostingService.post(inv)
    db.session.flush()
    return inv


def _json(resp):
    return json.loads(resp.data)


# ── Balance ───────────────────────────────────────────────────────────────────

class TestBalanceEndpoints:

    def test_balance_returns_200(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)
            db.session.commit()

            resp = client.get('/api/inventory/balance', headers=auth_headers)
            assert resp.status_code == 200
            data = _json(resp)
            assert isinstance(data, list)
            our = [r for r in data if r['branch_id'] == br.id]
            assert len(our) == 1
            assert our[0]['balance'] == pytest.approx(10.0)
            db.session.rollback()

    def test_balance_filter_by_branch(self, client, auth_headers):
        with app.app_context():
            cat = _category()
            br1 = _branch(); br2 = _branch()
            _post_invoice('شراء', br1.id, cat.id, 21.0, 5.0)
            _post_invoice('شراء', br2.id, cat.id, 21.0, 8.0)
            db.session.commit()

            resp = client.get(f'/api/inventory/balance?branch_id={br1.id}', headers=auth_headers)
            assert resp.status_code == 200
            data = _json(resp)
            assert all(r['branch_id'] == br1.id for r in data)
            db.session.rollback()

    def test_balance_summary_structure(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 20.0)
            db.session.commit()

            resp = client.get('/api/inventory/balance/summary', headers=auth_headers)
            assert resp.status_code == 200
            data = _json(resp)
            assert 'by_branch' in data
            assert 'by_karat' in data
            assert 'grand_total_weight' in data
            assert data['grand_total_weight'] >= 20.0
            db.session.rollback()


# ── Count Sessions ────────────────────────────────────────────────────────────

class TestCountSessionEndpoints:

    def test_list_sessions_empty(self, client, auth_headers):
        with app.app_context():
            resp = client.get('/api/inventory/count', headers=auth_headers)
            assert resp.status_code == 200
            assert isinstance(_json(resp), list)

    def test_open_session_creates_lines(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 30.0)
            db.session.commit()

            resp = client.post(
                '/api/inventory/count',
                json={'branch_id': br.id},
                headers=auth_headers,
            )
            assert resp.status_code == 201
            data = _json(resp)
            assert data['status'] == 'open'
            assert data['branch_id'] == br.id
            assert len(data['lines']) >= 1
            db.session.rollback()

    def test_open_session_missing_branch_400(self, client, auth_headers):
        with app.app_context():
            resp = client.post('/api/inventory/count', json={}, headers=auth_headers)
            assert resp.status_code == 400

    def test_get_session_detail(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 18.0, 15.0)
            db.session.commit()

            open_resp = client.post('/api/inventory/count', json={'branch_id': br.id}, headers=auth_headers)
            session_id = _json(open_resp)['id']

            resp = client.get(f'/api/inventory/count/{session_id}', headers=auth_headers)
            assert resp.status_code == 200
            data = _json(resp)
            assert data['id'] == session_id
            assert 'lines' in data
            db.session.rollback()

    def test_get_session_404(self, client, auth_headers):
        with app.app_context():
            resp = client.get('/api/inventory/count/999999', headers=auth_headers)
            assert resp.status_code == 404

    def test_record_count_entry(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 25.0)
            db.session.commit()

            open_resp = client.post('/api/inventory/count', json={'branch_id': br.id}, headers=auth_headers)
            session_id = _json(open_resp)['id']

            resp = client.put(
                f'/api/inventory/count/{session_id}/entry',
                json={'category_id': cat.id, 'karat': 21.0, 'counted_weight': 24.5},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            line = _json(resp)
            assert line['counted_weight'] == pytest.approx(24.5)
            assert line['variance'] == pytest.approx(-0.5)
            db.session.rollback()

    def test_record_entry_missing_fields_400(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)
            db.session.commit()

            open_resp = client.post('/api/inventory/count', json={'branch_id': br.id}, headers=auth_headers)
            session_id = _json(open_resp)['id']

            resp = client.put(
                f'/api/inventory/count/{session_id}/entry',
                json={'category_id': cat.id},  # missing karat + counted_weight
                headers=auth_headers,
            )
            assert resp.status_code == 400
            db.session.rollback()

    def test_full_count_lifecycle(self, client, auth_headers):
        """open → entry → close → approve"""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 50.0)
            db.session.commit()

            r = client.post('/api/inventory/count', json={'branch_id': br.id}, headers=auth_headers)
            assert r.status_code == 201
            sid = _json(r)['id']

            r = client.put(
                f'/api/inventory/count/{sid}/entry',
                json={'category_id': cat.id, 'karat': 21.0, 'counted_weight': 50.0},
                headers=auth_headers,
            )
            assert r.status_code == 200

            r = client.post(f'/api/inventory/count/{sid}/close', headers=auth_headers)
            assert r.status_code == 200
            assert _json(r)['status'] == 'closed'

            r = client.post(
                f'/api/inventory/count/{sid}/approve',
                json={'reason': 'جرد دوري'},
                headers=auth_headers,
            )
            assert r.status_code == 200
            body = _json(r)
            assert body['session']['status'] == 'approved'
            assert body['adjustment'] is None
            db.session.rollback()

    def test_approve_with_variance_creates_adjustment(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 40.0)
            db.session.commit()

            r = client.post('/api/inventory/count', json={'branch_id': br.id}, headers=auth_headers)
            sid = _json(r)['id']
            client.put(
                f'/api/inventory/count/{sid}/entry',
                json={'category_id': cat.id, 'karat': 21.0, 'counted_weight': 38.5},
                headers=auth_headers,
            )
            client.post(f'/api/inventory/count/{sid}/close', headers=auth_headers)
            r = client.post(
                f'/api/inventory/count/{sid}/approve',
                json={'reason': 'فاقد'},
                headers=auth_headers,
            )
            assert r.status_code == 200
            body = _json(r)
            assert body['adjustment'] is not None
            assert body['adjustment']['status'] == 'posted'
            db.session.rollback()

    def test_double_approve_returns_clean_arabic_error(self, client, auth_headers):
        """Second approve on an already-approved session must return 400 with Arabic
        message — not a 500 / raw exception.  Guards against duplicate GL entries
        in the concurrent-manager scenario."""
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 30.0)
            db.session.commit()

            r = client.post('/api/inventory/count', json={'branch_id': br.id}, headers=auth_headers)
            sid = _json(r)['id']
            client.put(
                f'/api/inventory/count/{sid}/entry',
                json={'category_id': cat.id, 'karat': 21.0, 'counted_weight': 30.0},
                headers=auth_headers,
            )
            client.post(f'/api/inventory/count/{sid}/close', headers=auth_headers)
            # First approval succeeds
            r1 = client.post(
                f'/api/inventory/count/{sid}/approve',
                json={'reason': 'جرد دوري'},
                headers=auth_headers,
            )
            assert r1.status_code == 200

            # Second approval on the now-approved session must fail cleanly
            r2 = client.post(
                f'/api/inventory/count/{sid}/approve',
                json={'reason': 'جرد دوري'},
                headers=auth_headers,
            )
            assert r2.status_code == 400
            error_msg = _json(r2).get('error', '')
            # Message must be Arabic (contains Arabic characters) — not a raw Python exception
            assert any('؀' <= c <= 'ۿ' for c in error_msg), \
                f'Expected Arabic error message, got: {error_msg!r}'
            db.session.rollback()


# ── Manual Adjustment ─────────────────────────────────────────────────────────

class TestAdjustmentEndpoints:

    def test_create_manual_adjustment(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 100.0)
            db.session.commit()

            resp = client.post('/api/inventory/adjustment', headers=auth_headers, json={
                'branch_id': br.id,
                'reason': 'فاقد تصنيع',
                'lines': [{'category_id': cat.id, 'karat': 21.0, 'variance_weight': -2.0}],
            })
            assert resp.status_code == 201
            data = _json(resp)
            assert data['status'] == 'posted'
            assert len(data['lines']) == 1
            assert data['lines'][0]['variance_weight'] == pytest.approx(-2.0)
            db.session.rollback()

    def test_create_adjustment_missing_reason_400(self, client, auth_headers):
        with app.app_context():
            br = _branch()
            resp = client.post('/api/inventory/adjustment', headers=auth_headers, json={
                'branch_id': br.id,
                'lines': [{'category_id': 1, 'karat': 21.0, 'variance_weight': -1.0}],
            })
            assert resp.status_code == 400
            db.session.rollback()

    def test_create_adjustment_empty_lines_400(self, client, auth_headers):
        with app.app_context():
            br = _branch()
            resp = client.post('/api/inventory/adjustment', headers=auth_headers, json={
                'branch_id': br.id,
                'reason': 'test',
                'lines': [],
            })
            assert resp.status_code == 400
            db.session.rollback()

    def test_get_adjustment_detail(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 50.0)
            db.session.commit()

            create_resp = client.post('/api/inventory/adjustment', headers=auth_headers, json={
                'branch_id': br.id,
                'reason': 'اختبار',
                'lines': [{'category_id': cat.id, 'karat': 21.0, 'variance_weight': -1.0}],
            })
            adj_id = _json(create_resp)['id']

            resp = client.get(f'/api/inventory/adjustment/{adj_id}', headers=auth_headers)
            assert resp.status_code == 200
            data = _json(resp)
            assert data['id'] == adj_id
            assert 'lines' in data
            db.session.rollback()

    def test_get_adjustment_404(self, client, auth_headers):
        with app.app_context():
            resp = client.get('/api/inventory/adjustment/999999', headers=auth_headers)
            assert resp.status_code == 404


# ── Reports ───────────────────────────────────────────────────────────────────

class TestReportEndpoints:

    def test_reconciliation_returns_200(self, client, auth_headers):
        with app.app_context():
            cat = _category(); br = _branch()
            _post_invoice('شراء', br.id, cat.id, 21.0, 10.0)
            db.session.commit()

            resp = client.get('/api/inventory/reconciliation', headers=auth_headers)
            assert resp.status_code == 200
            data = _json(resp)
            assert 'is_clean' in data
            assert 'rows' in data
            assert isinstance(data['rows'], list)
            db.session.rollback()

    def test_health_returns_200(self, client, auth_headers):
        with app.app_context():
            resp = client.get('/api/inventory/health', headers=auth_headers)
            assert resp.status_code == 200
            data = _json(resp)
            assert 'has_issues' in data
            metric_keys = {m['key'] for m in data.get('metrics', [])}
            assert 'ledger_row_count' in metric_keys
            assert 'invariant_violations' in metric_keys
