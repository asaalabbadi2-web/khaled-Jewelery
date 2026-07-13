"""Admin & temp-pdf domain routes — admin_bp registered under /api in app.py."""
from __future__ import annotations

import os
import secrets
import time as _time
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request, send_file

from models import (
    db,
    JournalEntry,
    PaymentMethod,
    SafeBox,
    SafeBoxTransaction,
    SettlementLine,
    Voucher,
    VoucherAccountLine,
)

from auth_decorators import require_permission

admin_bp = Blueprint('admin', __name__)

_TEMP_PDF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp_pdfs')
_TEMP_PDF_MAX_BYTES = 10 * 1024 * 1024   # 10 MB per upload
_TEMP_PDF_TTL_SECONDS = 86400             # 24 hours


def _temp_pdf_lazy_cleanup():
    """Remove temp PDF files older than _TEMP_PDF_TTL_SECONDS (best-effort)."""
    import time as _time
    try:
        cutoff = _time.time() - _TEMP_PDF_TTL_SECONDS
        for fname in os.listdir(_TEMP_PDF_DIR):
            fpath = os.path.join(_TEMP_PDF_DIR, fname)
            try:
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
            except OSError:
                pass
    except OSError:
        pass


@admin_bp.route('/temp-pdf', methods=['POST'])
def upload_temp_pdf():
    """
    Accept raw PDF bytes (Content-Type: application/pdf).
    Returns: {"token": "<url-safe token>"} with status 201.
    The caller builds the download URL as <api_base>/temp-pdf/<token>.
    """
    import secrets
    import re

    data = request.get_data()
    if not data:
        return jsonify({'error': 'empty body'}), 400
    if len(data) > _TEMP_PDF_MAX_BYTES:
        return jsonify({'error': 'file too large'}), 413

    # Validate that the payload looks like a PDF.
    if not data.startswith(b'%PDF'):
        return jsonify({'error': 'not a PDF'}), 400

    os.makedirs(_TEMP_PDF_DIR, exist_ok=True)
    _temp_pdf_lazy_cleanup()

    token = secrets.token_urlsafe(24)  # 32 url-safe chars, no path traversal risk
    # Paranoid check: token must be safe for filesystem and URL use.
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', token):
        token = secrets.token_hex(24)

    filepath = os.path.join(_TEMP_PDF_DIR, f'{token}.pdf')
    with open(filepath, 'wb') as fh:
        fh.write(data)

    return jsonify({'token': token}), 201


@admin_bp.route('/temp-pdf/<string:token>', methods=['GET'])
def serve_temp_pdf(token):
    """
    Serve a previously uploaded temporary PDF.
    Validates the token strictly to prevent path traversal.
    """
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', token):
        return jsonify({'error': 'invalid token'}), 400

    filepath = os.path.join(_TEMP_PDF_DIR, f'{token}.pdf')
    # os.path.abspath check guards against any remaining traversal risk.
    if not os.path.abspath(filepath).startswith(os.path.abspath(_TEMP_PDF_DIR)):
        return jsonify({'error': 'invalid token'}), 400
    if not os.path.isfile(filepath):
        return jsonify({'error': 'not found or expired'}), 404

    return send_file(filepath, mimetype='application/pdf', as_attachment=False)


# Employees domain → routes/employees.py (achievements + goals)
# (GET /achievements/unseen, POST /achievements/<id>/mark-seen,
#  POST /achievements, POST /achievements/check-progress,
#  PATCH /employees/<id>/goals)



@admin_bp.route('/admin/clearing-gap-report', methods=['GET'])
@require_permission('system.settings')
def clearing_gap_report():
    """تقرير تشخيصي مؤقت: ثغرات SettlementLine في صناديق المقاصة.

    يعيد:
    - incomplete_vouchers: سندات لها SettlementLine أقل من amount_cash
    - uncovered_ips: IPs بلا أي SettlementLine (True Gap — لا voucher يغطيها)
    """
    from allocation_repair_service import AllocationRepairService
    from sqlalchemy import func as sqlfunc

    result = {}
    sbs = SafeBox.query.filter_by(safe_type='clearing', is_active=True).all()
    svc = AllocationRepairService()

    for sb in sbs:
        sb_key = f'SB#{sb.id}_{sb.name}'

        # 1. سندات ذات تغطية ناقصة
        incomplete = svc.find_incomplete_vouchers(safe_box=sb)
        incomplete_list = []
        for v in incomplete:
            total_sl = (
                db.session.query(sqlfunc.coalesce(sqlfunc.sum(SettlementLine.amount_settled), 0.0))
                .filter(SettlementLine.voucher_id == v.id)
                .scalar()
            ) or 0.0
            incomplete_list.append({
                'voucher_id': v.id,
                'voucher_number': v.voucher_number,
                'amount_cash': float(v.amount_cash or 0),
                'total_settled': round(float(total_sl), 2),
                'gap': round(float(v.amount_cash or 0) - round(float(total_sl), 2), 2),
                'date': str(v.date)[:10] if v.date else None,
            })

        # 2. IPs بلا أي SettlementLine (True Gap)
        all_ips = (
            InvoicePayment.query
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(PaymentMethod.default_safe_box_id == sb.id)
            .all()
        )
        ip_ids = [ip.id for ip in all_ips]
        settled_map = {}
        if ip_ids:
            sl_rows = (
                db.session.query(
                    SettlementLine.invoice_payment_id,
                    sqlfunc.coalesce(sqlfunc.sum(SettlementLine.amount_settled), 0.0),
                )
                .join(Voucher, Voucher.id == SettlementLine.voucher_id)
                .filter(SettlementLine.invoice_payment_id.in_(ip_ids))
                .filter(Voucher.status == 'approved')
                .group_by(SettlementLine.invoice_payment_id)
                .all()
            )
            settled_map = {r[0]: round(float(r[1]), 2) for r in sl_rows}

        uncovered = []
        for ip in all_ips:
            remaining = round(float(ip.amount or 0) - settled_map.get(ip.id, 0.0), 2)
            if remaining > 0.01:
                uncovered.append({
                    'ip_id': ip.id,
                    'amount': float(ip.amount or 0),
                    'settled': settled_map.get(ip.id, 0.0),
                    'remaining': remaining,
                    'created_at': str(ip.created_at)[:19] if ip.created_at else None,
                })

        result[sb_key] = {
            'incomplete_vouchers': incomplete_list,
            'incomplete_count': len(incomplete_list),
            'uncovered_ips': sorted(uncovered, key=lambda x: x['created_at'] or ''),
            'uncovered_count': len(uncovered),
            'total_uncovered_amount': round(sum(x['remaining'] for x in uncovered), 2),
        }

    return jsonify({'gap_report': result}), 200


@admin_bp.route('/admin/ip-settlement-trace', methods=['GET'])
@require_permission('system.settings')
def ip_settlement_trace():
    """تتبع SettlementLines لمجموعة من InvoicePayment IDs.

    Query params: ids=2435,2436,2440 (comma-separated)
    """
    ip_ids_param = request.args.get('ids', '')
    try:
        ip_ids = [int(x.strip()) for x in ip_ids_param.split(',') if x.strip()]
    except ValueError:
        return jsonify({'error': 'ids must be comma-separated integers'}), 400

    if not ip_ids:
        return jsonify({'error': 'ids param required'}), 400

    result = []
    for ip_id in ip_ids:
        ip = InvoicePayment.query.get(ip_id)
        if not ip:
            result.append({'ip_id': ip_id, 'error': 'not found'})
            continue

        sl_rows = (
            db.session.query(
                SettlementLine.voucher_id,
                SettlementLine.amount_settled,
                Voucher.voucher_number,
                Voucher.status,
                Voucher.date,
            )
            .join(Voucher, Voucher.id == SettlementLine.voucher_id)
            .filter(SettlementLine.invoice_payment_id == ip_id)
            .all()
        )

        total_all = sum(float(r[1] or 0) for r in sl_rows)
        total_approved = sum(float(r[1] or 0) for r in sl_rows if r[3] == 'approved')

        result.append({
            'ip_id': ip_id,
            'ip_amount': float(ip.amount or 0),
            'created_at': str(ip.created_at)[:19] if ip.created_at else None,
            'total_settled_all': round(total_all, 2),
            'total_settled_approved': round(total_approved, 2),
            'remaining_approved': round(float(ip.amount or 0) - total_approved, 2),
            'settlement_lines': [
                {
                    'voucher_id': r[0],
                    'voucher_number': r[2],
                    'voucher_status': r[3],
                    'voucher_date': str(r[4])[:10] if r[4] else None,
                    'amount_settled': float(r[1] or 0),
                }
                for r in sl_rows
            ],
        })

    return jsonify({'ip_trace': result}), 200


@admin_bp.route('/admin/repair-voucher-date-bounded', methods=['POST'])
@require_permission('system.settings')
def repair_voucher_date_bounded():
    """أعِد تخصيص سند واحد مع احترام حدود التاريخ (IPs <= voucher.date + 2 days).

    Body JSON: {"voucher_id": 1649}

    يحذف جميع SettlementLines الحالية للسند ويُعيد التخصيص بـ IP pool
    مُقيَّد بالتاريخ — لا يستطيع استخدام IPs من فترة لاحقة على تاريخ السند.
    إذا تعذّر التغطية الكاملة يُرجع الخطأ بدون commit.
    """
    from datetime import datetime as _dt, timedelta as _td
    from allocation_service import AllocationService
    from allocation_repair_service import _get_clearing_account_id, _extract_fee_vat

    data = request.get_json(force=True) or {}
    voucher_id = data.get('voucher_id')
    if not voucher_id:
        return jsonify({'error': 'voucher_id required'}), 400

    voucher = Voucher.query.get(voucher_id)
    if not voucher:
        return jsonify({'error': f'voucher {voucher_id} not found'}), 404
    if voucher.reference_type != 'clearing_settlement':
        return jsonify({'error': 'not a clearing_settlement voucher'}), 400
    if voucher.status != 'approved':
        return jsonify({'error': 'voucher is not approved'}), 400

    # Determine safe box from the credit VoucherAccountLine (clearing account)
    clearing_account_id = _get_clearing_account_id(voucher)
    if not clearing_account_id:
        return jsonify({'error': 'cannot determine clearing account from voucher'}), 400

    sb = SafeBox.query.filter_by(account_id=clearing_account_id).first()
    if not sb:
        return jsonify({'error': f'no safe box for account_id={clearing_account_id}'}), 400

    # Build date-bounded IP pool
    v_dt = voucher.date
    if v_dt:
        if not isinstance(v_dt, _dt):
            v_dt = _dt(v_dt.year, v_dt.month, v_dt.day, 23, 59, 59)
        cutoff = v_dt + _td(days=2)
    else:
        cutoff = None

    ips_q = (
        InvoicePayment.query
        .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
        .filter(PaymentMethod.default_safe_box_id == sb.id)
        .order_by(InvoicePayment.created_at.asc())
    )
    if cutoff:
        ips_q = ips_q.filter(InvoicePayment.created_at <= cutoff)
    ip_pool = [ip.id for ip in ips_q.all()]

    fee_amount, fee_vat = _extract_fee_vat(voucher, clearing_account_id)
    gross_amount = round(float(voucher.amount_cash or 0), 2)

    svc = AllocationService()
    deleted = svc.unallocate(voucher)
    db.session.flush()

    try:
        plan = svc.allocate(
            voucher=voucher,
            invoice_payment_ids=ip_pool,
            gross_amount=gross_amount,
            fee_amount=fee_amount,
            fee_vat=fee_vat,
        )
        db.session.commit()
        return jsonify({
            'voucher_id': voucher_id,
            'voucher_number': voucher.voucher_number,
            'gross_amount': gross_amount,
            'ip_pool_size': len(ip_pool),
            'cutoff_date': str(cutoff)[:10] if cutoff else None,
            'lines_deleted': deleted,
            'lines_created': len(plan.lines),
            'unallocated_remainder': plan.unallocated_remainder,
            'is_fully_covered': plan.is_fully_covered,
        }), 200
    except ValueError as exc:
        db.session.rollback()
        return jsonify({
            'error': str(exc),
            'voucher_id': voucher_id,
            'voucher_number': voucher.voucher_number,
            'gross_amount': gross_amount,
            'ip_pool_size': len(ip_pool),
            'cutoff_date': str(cutoff)[:10] if cutoff else None,
            'lines_deleted': deleted,
            'lines_restored': 0,
        }), 422


# ═══════════════════════════════════════════════════════════════════════════
#  HistoricalClearingAdjustment — Admin API
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/admin/historical-clearing-adjustment', methods=['GET'])
@require_permission('system.settings')
def list_historical_clearing_adjustments():
    """List all HistoricalClearingAdjustment records (newest first)."""
    from models import HistoricalClearingAdjustment as HCA
    rows = HCA.query.order_by(HCA.id.desc()).all()
    return jsonify({'adjustments': [r.to_dict() for r in rows]}), 200


@admin_bp.route('/admin/historical-clearing-adjustment', methods=['POST'])
@require_permission('system.settings')
def create_historical_clearing_adjustment():
    """Create a pending HistoricalClearingAdjustment.

    Body:
      {
        "safe_box_id": 32,
        "amount": 6050.00,
        "adjustment_type": "historical_allocation_gap",
        "reason": "...",
        "reference_voucher_number": "AV-2026-00133"   // optional
      }
    """
    from historical_clearing_adjustment_service import HistoricalClearingAdjustmentService

    data = request.get_json(force=True) or {}
    required = ('safe_box_id', 'amount', 'adjustment_type', 'reason')
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'missing fields: {missing}'}), 400

    actor = getattr(g, 'current_user', None)
    created_by = actor.username if actor else 'admin'

    try:
        svc = HistoricalClearingAdjustmentService()
        adj = svc.create(
            safe_box_id=int(data['safe_box_id']),
            amount=float(data['amount']),
            adjustment_type=data['adjustment_type'],
            reason=data['reason'],
            created_by=created_by,
            reference_voucher_number=data.get('reference_voucher_number'),
        )
        db.session.commit()
        return jsonify({'adjustment': adj.to_dict()}), 201
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@admin_bp.route('/admin/historical-clearing-adjustment/<int:adj_id>/apply', methods=['POST'])
@require_permission('system.settings')
def apply_historical_clearing_adjustment(adj_id):
    """Apply a pending adjustment: creates SafeBoxTransaction + JournalEntry.

    Body:
      {
        "clearing_account_id": 777,
        "contra_account_id": 900
      }
    """
    from historical_clearing_adjustment_service import HistoricalClearingAdjustmentService

    data = request.get_json(force=True) or {}
    clearing_account_id = data.get('clearing_account_id')
    contra_account_id = data.get('contra_account_id')
    if not clearing_account_id or not contra_account_id:
        return jsonify({'error': 'clearing_account_id and contra_account_id required'}), 400

    actor = getattr(g, 'current_user', None)
    applied_by = actor.username if actor else 'admin'

    try:
        from historical_clearing_adjustment_service import AlreadyAppliedError
        svc = HistoricalClearingAdjustmentService()
        adj = svc.apply(
            adjustment_id=adj_id,
            applied_by=applied_by,
            clearing_account_id=int(clearing_account_id),
            contra_account_id=int(contra_account_id),
        )
        db.session.commit()
        return jsonify({'adjustment': adj.to_dict()}), 200
    except AlreadyAppliedError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': 'already_applied'}), 409
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@admin_bp.route('/admin/historical-clearing-adjustment/<int:adj_id>/cancel', methods=['POST'])
@require_permission('system.settings')
def cancel_historical_clearing_adjustment(adj_id):
    """Cancel a pending adjustment.

    Body: {"reason": "..."}
    """
    from historical_clearing_adjustment_service import HistoricalClearingAdjustmentService

    data = request.get_json(force=True) or {}
    reason = data.get('reason', '')

    actor = getattr(g, 'current_user', None)
    cancelled_by = actor.username if actor else 'admin'

    try:
        svc = HistoricalClearingAdjustmentService()
        adj = svc.cancel(
            adjustment_id=adj_id,
            cancelled_by=cancelled_by,
            reason=reason,
        )
        db.session.commit()
        return jsonify({'adjustment': adj.to_dict()}), 200
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400

