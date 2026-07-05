"""Inventory API Blueprint — /api/inventory/

Endpoints:
    GET  /balance                  أرصدة الـ buckets (branch+category+karat)
    GET  /balance/summary          تجميع للـ dashboard
    GET  /count                    قائمة جلسات الجرد
    POST /count                    فتح جلسة جرد جديدة
    GET  /count/<id>               تفاصيل جلسة + سطورها
    PUT  /count/<id>/entry         تسج��ل عدّ فعلي لـ bucket
    POST /count/<id>/close         إغلاق الجلسة (تحضير للاعتماد)
    POST /count/<id>/approve       اعتماد ��لجلسة + توليد قيود التسوية
    POST /adjustment               تسوية يدوية مستقلة
    GET  /adjustment/<id>          تفاصيل تسوية + سطورها
    GET  /reconciliation           تقرير الم��ابقة الرباعي
    GET  /health                   تقرير صحة محرك الجرد

Permissions:
    inventory.view    → GET  balance, balance/summary, count, count/<id>,
                              adjustment/<id>, reconciliation*, health*
    inventory.count   → POST count, PUT entry, POST close
    inventory.approve → POST approve, POST adjustment
    (* reconciliation و health: inventory.approve فقط — بيانات تدقيق حساسة)
"""
from __future__ import annotations

from datetime import datetime
from flask import Blueprint, request, jsonify, g

from auth_decorators import require_permission
from models import db, Branch, Category, InventoryBalance, InventoryCountSession

inventory_bp = Blueprint('inventory', __name__, url_prefix='/api/inventory')


# ── helpers ───────────────��──────────────────────────────��────────────────────

def _current_user() -> str:
    u = getattr(g, 'current_user', None)
    if u is None:
        return 'unknown'
    return getattr(u, 'username', None) or getattr(u, 'email', None) or str(u.id)


def _get_session_or_404(session_id: int):
    s = InventoryCountSession.query.get(session_id)
    if s is None:
        return None, jsonify({'error': 'جلسة الجرد غير موجودة', 'session_id': session_id}), 404
    return s, None, None


def _err(msg: str, code: int = 400):
    return jsonify({'error': msg}), code


# ── Balance ───────────────���─────────────────────────────��─────────────────────

@inventory_bp.route('/balance', methods=['GET'])
@require_permission('inventory.view')
def get_balance():
    """أرصدة الـ buckets مع فلاتر اختيارية.

    Query params:
        branch_id   (int)   فلتر بالفرع
        category_id (int)   فلتر بالتصنيف
        karat       (float) فلتر بالعيار
    """
    q = InventoryBalance.query

    branch_id = request.args.get('branch_id', type=int)
    category_id = request.args.get('category_id', type=int)
    karat = request.args.get('karat', type=float)

    if branch_id is not None:
        q = q.filter_by(branch_id=branch_id)
    if category_id is not None:
        q = q.filter_by(category_id=category_id)
    if karat is not None:
        q = q.filter_by(karat=karat)

    rows = q.order_by(
        InventoryBalance.branch_id,
        InventoryBalance.category_id,
        InventoryBalance.karat,
    ).all()

    return jsonify([_balance_row(r) for r in rows]), 200


@inventory_bp.route('/balance/summary', methods=['GET'])
@require_permission('inventory.view')
def get_balance_summary():
    """تجميع للـ dashboard: إجمالي ال��رصدة مجمّعة بالفرع وبالعيار.

    Returns:
        by_branch: [{branch_id, branch_name, total_weight}]
        by_karat:  [{karat, total_weight}]
        grand_total_weight: float
    """
    from sqlalchemy import func

    # تجميع بالفرع
    by_branch_q = (
        db.session.query(
            InventoryBalance.branch_id,
            func.sum(InventoryBalance.balance).label('total'),
        )
        .group_by(InventoryBalance.branch_id)
        .all()
    )
    branch_names = {
        b.id: b.name
        for b in Branch.query.filter(
            Branch.id.in_([r.branch_id for r in by_branch_q if r.branch_id])
        ).all()
    }
    by_branch = [
        {
            'branch_id': r.branch_id,
            'branch_name': branch_names.get(r.branch_id, '—'),
            'total_weight': round(float(r.total or 0), 4),
        }
        for r in by_branch_q
    ]

    # تجميع بالعيار
    by_karat_q = (
        db.session.query(
            InventoryBalance.karat,
            func.sum(InventoryBalance.balance).label('total'),
        )
        .group_by(InventoryBalance.karat)
        .order_by(InventoryBalance.karat)
        .all()
    )
    by_karat = [
        {'karat': r.karat, 'total_weight': round(float(r.total or 0), 4)}
        for r in by_karat_q
    ]

    grand_total = sum(r['total_weight'] for r in by_karat)

    return jsonify({
        'by_branch': by_branch,
        'by_karat': by_karat,
        'grand_total_weight': round(grand_total, 4),
        'generated_at': datetime.now().isoformat(),
    }), 200


# ── Count Sessions ────────────────────────���──────────────────────────���────────

@inventory_bp.route('/count', methods=['GET'])
@require_permission('inventory.view')
def list_count_sessions():
    """قائمة جلسات الج��د مع فلاتر.

    Query params:
        branch_id (int)
        status    (str): open | counting | closed | approved
        limit     (int): default 50
    """
    q = InventoryCountSession.query

    branch_id = request.args.get('branch_id', type=int)
    status = request.args.get('status')
    limit = min(request.args.get('limit', 50, type=int), 200)

    if branch_id is not None:
        q = q.filter_by(branch_id=branch_id)
    if status:
        q = q.filter_by(status=status)

    sessions = q.order_by(InventoryCountSession.id.desc()).limit(limit).all()
    return jsonify([_session_summary(s) for s in sessions]), 200


@inventory_bp.route('/count', methods=['POST'])
@require_permission('inventory.count')
def open_count_session():
    """فتح جلسة جرد جديدة وتعبئة السطور من الأرصدة الحالية.

    Body (JSON):
        branch_id (int, required)
        notes     (str, optional)
    """
    from services.inventory_count_service import InventoryCountService

    data = request.get_json(silent=True) or {}
    branch_id = data.get('branch_id')
    if not branch_id:
        return _err('branch_id مطلوب')

    # blind_count=True by default — manager may pass false for spot-checks
    blind_count = data.get('blind_count', True)
    if not isinstance(blind_count, bool):
        blind_count = str(blind_count).lower() not in ('false', '0', 'no')

    try:
        session = InventoryCountService.open_session(
            branch_id=branch_id,
            opened_by=_current_user(),
            notes=data.get('notes', ''),
            blind_count=blind_count,
        )
        db.session.flush()
        InventoryCountService.populate_lines(session)
        db.session.commit()
        return jsonify(_session_detail(session)), 201
    except ValueError as e:
        db.session.rollback()
        return _err(str(e))
    except Exception as e:
        db.session.rollback()
        return _err(f'خطأ في فتح الجلسة: {e}', 500)


@inventory_bp.route('/count/<int:session_id>', methods=['GET'])
@require_permission('inventory.view')
def get_count_session(session_id: int):
    """تفاصيل جلسة الجرد مع كامل سطورها."""
    s, err, code = _get_session_or_404(session_id)
    if err:
        return err, code
    return jsonify(_session_detail(s)), 200


@inventory_bp.route('/count/<int:session_id>/entry', methods=['PUT'])
@require_permission('inventory.count')
def record_count_entry(session_id: int):
    """تسجيل (أو تحديث) العدّ الفعلي لـ bucket واحد.

    Body (JSON):
        category_id    (int,   required)
        karat          (float, required)
        counted_weight (float, required)
    """
    from services.inventory_count_service import InventoryCountService

    s, err, code = _get_session_or_404(session_id)
    if err:
        return err, code

    data = request.get_json(silent=True) or {}
    category_id = data.get('category_id')
    karat = data.get('karat')
    counted_weight = data.get('counted_weight')

    if category_id is None or karat is None or counted_weight is None:
        return _err('category_id و karat و counted_weight مطلوبة')

    try:
        line = InventoryCountService.record_count(
            session=s,
            category_id=category_id,
            karat=float(karat),
            counted_weight=float(counted_weight),
            counted_by=_current_user(),
        )
        db.session.commit()
        return jsonify(_count_line(line)), 200
    except ValueError as e:
        db.session.rollback()
        return _err(str(e))
    except Exception as e:
        db.session.rollback()
        return _err(f'خطأ في تسجيل العدّ: {e}', 500)


@inventory_bp.route('/count/<int:session_id>/close', methods=['POST'])
@require_permission('inventory.count')
def close_count_session(session_id: int):
    """إغلاق الجلسة — تحقق أن جميع السطور تم عدّها."""
    from services.inventory_count_service import InventoryCountService

    s, err, code = _get_session_or_404(session_id)
    if err:
        return err, code

    try:
        InventoryCountService.close_session(s)
        db.session.commit()
        return jsonify(_session_summary(s)), 200
    except ValueError as e:
        db.session.rollback()
        return _err(str(e))
    except Exception as e:
        db.session.rollback()
        return _err(f'خطأ في إغلاق الجلسة: {e}', 500)


@inventory_bp.route('/count/<int:session_id>/approve', methods=['POST'])
@require_permission('inventory.approve')
def approve_count_session(session_id: int):
    """اعتماد الجلسة — ينشئ قيود تسوية لأي فروقات.

    Body (JSON):
        reason (str, optional)  سبب التسوية للقيد
    """
    from services.inventory_count_service import InventoryCountService

    # SELECT FOR UPDATE prevents two concurrent approval requests from both
    # reading status='closed' and creating duplicate adjustment entries.
    s = InventoryCountSession.query.with_for_update().get(session_id)
    if s is None:
        return _err('جلسة الجرد غير موجودة', 404)

    data = request.get_json(silent=True) or {}
    reason = data.get('reason', 'تسوية جرد دوري')

    try:
        session, adjustment = InventoryCountService.approve_session(
            session=s,
            approved_by=_current_user(),
            adjustment_reason=reason,
        )
        db.session.commit()
        return jsonify({
            'session': _session_summary(session),
            'adjustment': _adjustment_summary(adjustment) if adjustment else None,
        }), 200
    except ValueError as e:
        db.session.rollback()
        return _err(str(e))
    except Exception as e:
        db.session.rollback()
        return _err(f'خطأ في اعتماد الجلسة: {e}', 500)


# ── Adjustments ──────────────────────��──────────────────────────────���─────────

@inventory_bp.route('/adjustment', methods=['POST'])
@require_permission('inventory.approve')
def create_manual_adjustment():
    """تسوية يدوية مست��لة (فاقد تصنيع، خسارة، تصحيح).

    Body (JSON):
        branch_id  (int, required)
        reason     (str, required)
        lines      (list, required): [{category_id, karat, variance_weight}]
        auto_post  (bool, default true)
    """
    from services.inventory_adjustment_service import InventoryAdjustmentService

    data = request.get_json(silent=True) or {}
    branch_id = data.get('branch_id')
    reason = data.get('reason', '').strip()
    lines_data = data.get('lines', [])
    auto_post = data.get('auto_post', True)

    if not branch_id:
        return _err('branch_id مطلوب')
    if not reason:
        return _err('reason مطلوب')
    if not lines_data or not isinstance(lines_data, list):
        return _err('lines مطلوبة و��جب أن تكون قائمة')

    # تحقق من كل سطر
    for i, line in enumerate(lines_data):
        if line.get('category_id') is None:
            return _err(f'السطر {i+1}: category_id مطلوب')
        if line.get('karat') is None:
            return _err(f'السطر {i+1}: karat مطلوب')
        if line.get('variance_weight') is None:
            return _err(f'السطر {i+1}: variance_weight مطلوب')

    try:
        adjustment = InventoryAdjustmentService.create_manual(
            branch_id=branch_id,
            lines_data=lines_data,
            reason=reason,
            created_by=_current_user(),
            auto_post=bool(auto_post),
        )
        db.session.commit()
        return jsonify(_adjustment_detail(adjustment)), 201
    except ValueError as e:
        db.session.rollback()
        return _err(str(e))
    except Exception as e:
        db.session.rollback()
        return _err(f'خطأ في إنشاء التسوية: {e}', 500)


@inventory_bp.route('/adjustment/<int:adjustment_id>', methods=['GET'])
@require_permission('inventory.view')
def get_adjustment(adjustment_id: int):
    """تفاصيل تسوية مع سطورها."""
    from models import InventoryAdjustment
    adj = InventoryAdjustment.query.get(adjustment_id)
    if not adj:
        return _err('��لتسوية غير موجودة', 404)
    return jsonify(_adjustment_detail(adj)), 200


# ── Reports ───────────��───────────────────────────────────��───────────────────

@inventory_bp.route('/reconciliation', methods=['GET'])
@require_permission('inventory.approve')
def get_reconciliation():
    """تقرير المطابقة الرباعي: Ledger / Balance / Physical Count / GL.

    مخصص للمدير والمحاسب للتدقيق الدوري.
    """
    from services.inventory_reconciliation_report import InventoryReconciliationReport
    snap = InventoryReconciliationReport.build()
    return jsonify(snap.to_dict()), 200


@inventory_bp.route('/health', methods=['GET'])
@require_permission('inventory.approve')
def get_health():
    """تقرير صحة محرك الجرد: مخالفات، جلسات مفتوحة، تسويات معلقة."""
    from services.inventory_health_report import InventoryHealthReport
    report = InventoryHealthReport.build()
    return jsonify(report.to_dict() if hasattr(report, 'to_dict') else report.__dict__), 200


# ── Serialisers ──────────────────────��────────────────────────────────────────

def _balance_row(r) -> dict:
    return {
        'id':                    r.id,
        'branch_id':             r.branch_id,
        'category_id':           r.category_id,
        'karat':                 r.karat,
        'balance':               round(float(r.balance or 0), 4),
        'snapshot_max_ledger_id': r.snapshot_max_ledger_id,
        'updated_at':            r.updated_at.isoformat() if r.updated_at else None,
    }


def _session_summary(s) -> dict:
    return {
        'id':                 s.id,
        'branch_id':          s.branch_id,
        'status':             s.status,
        'blind_count':        getattr(s, 'blind_count', True),
        'snapshot_ledger_id': s.snapshot_ledger_id,
        'opened_by':          s.opened_by,
        'opened_at':          s.opened_at.isoformat() if s.opened_at else None,
        'closed_at':          s.closed_at.isoformat() if s.closed_at else None,
        'approved_by':        s.approved_by,
        'approved_at':        s.approved_at.isoformat() if s.approved_at else None,
        'notes':              s.notes,
    }


def _session_detail(s) -> dict:
    summary = _session_summary(s)
    reveal = _should_reveal_expected(s)
    summary['lines'] = [_count_line(ln, reveal_expected=reveal) for ln in s.lines]
    return summary


def _count_line(ln, reveal_expected: bool = True) -> dict:
    """Serialise a count line.

    When reveal_expected=False (blind count, session still open/counting),
    expected_weight and expected_ledger_id are hidden — the counter sees
    only their own input, preventing anchoring bias.
    Expected is always revealed once the session is closed or approved.
    """
    return {
        'id':               ln.id,
        'session_id':       ln.session_id,
        'branch_id':        ln.branch_id,
        'category_id':      ln.category_id,
        'karat':            ln.karat,
        'expected_weight':  round(float(ln.expected_weight or 0), 4) if reveal_expected else None,
        'expected_ledger_id': ln.expected_ledger_id if reveal_expected else None,
        'counted_weight':   round(float(ln.counted_weight), 4) if ln.counted_weight is not None else None,
        'variance':         round(float(ln.variance), 4) if ln.variance is not None and reveal_expected else None,
        'counted_by':       ln.counted_by,
        'counted_at':       ln.counted_at.isoformat() if ln.counted_at else None,
        'notes':            ln.notes,
    }


def _should_reveal_expected(session) -> bool:
    """True when expected_weight may be shown to the client.

    Rules:
      - Non-blind sessions: always reveal
      - Blind sessions: reveal only after session is closed or approved
    """
    blind = getattr(session, 'blind_count', True)
    if not blind:
        return True
    return session.status in ('closed', 'approved')


def _adjustment_summary(adj) -> dict | None:
    if adj is None:
        return None
    return {
        'id':              adj.id,
        'branch_id':       adj.branch_id,
        'adjustment_type': adj.adjustment_type,
        'status':          adj.status,
        'reason':          adj.reason,
        'created_by':      adj.created_by,
        'created_at':      adj.created_at.isoformat() if adj.created_at else None,
        'posted_by':       adj.posted_by,
        'posted_at':       adj.posted_at.isoformat() if adj.posted_at else None,
    }


def _adjustment_detail(adj) -> dict:
    summary = _adjustment_summary(adj)
    summary['lines'] = [
        {
            'id':               ln.id,
            'branch_id':        ln.branch_id,
            'category_id':      ln.category_id,
            'karat':            ln.karat,
            'expected_weight':  round(float(ln.expected_weight or 0), 4),
            'counted_weight':   round(float(ln.counted_weight or 0), 4),
            'variance_weight':  round(float(ln.variance_weight), 4),
            'notes':            ln.notes,
        }
        for ln in adj.lines
    ]
    return summary
