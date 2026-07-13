"""Accounts domain routes — accounts_bp registered under /api in app.py."""
from __future__ import annotations

from datetime import datetime, date, time

from flask import Blueprint, request, jsonify

from models import db, Account, AccountingMapping, JournalEntry, JournalEntryLine, SafeBox
from account_pair_service import link_accounts, unlink_account
from core.database import _db_has_column
from core.responses import _wrap_api_exceptions
from auth_decorators import require_permission
from pricing.gold_price_service import get_current_gold_price
from pricing.karat_service import convert_to_main_karat, get_main_karat
from services.live_balances import live_balances_by_account_ids
from accounting.statement_verification import (
    _build_statement_qr_signed_payload,
    _sign_qr_payload,
    _build_qr_verify_token,
    _build_statement_verify_url,
)

accounts_bp = Blueprint('accounts', __name__)

# ---------------------------------------------------------------------------
# Statement endpoints
# ---------------------------------------------------------------------------

@accounts_bp.route('/accounts/<int:account_id>/statement', methods=['GET'])
@_wrap_api_exceptions('account_statement_failed', 'Failed to load account statement')
def get_account_statement(account_id):
    account = Account.query.get_or_404(account_id)
    main_karat = get_main_karat()

    # Dual Statement: if the account has a linked memo/financial pair, return a
    # unified timeline using the existing merged statement logic.
    #
    # Escape hatch: pass `separate=1` or `merged=0` to force single-account statement.
    try:
        separate_flag = (str(request.args.get('separate', '')).strip().lower() in ('1', 'true', 'yes', 'y', 'on'))
        merged_flag = str(request.args.get('merged', '')).strip().lower()
        force_separate = separate_flag or (merged_flag in ('0', 'false', 'no', 'n', 'off'))
    except Exception:
        force_separate = False

    try:
        if force_separate:
            raise RuntimeError('force_separate_statement')
        try:
            payment_account_types = {'cash', 'bank_account', 'digital_wallet', 'bnpl'}
            is_payment_account = (
                (str(getattr(account, 'account_type', '') or '').strip().lower() in payment_account_types)
                or bool(getattr(account, 'bank_name', None))
                or bool(getattr(account, 'account_number_external', None))
            )
            if not is_payment_account:
                is_payment_account = SafeBox.query.filter_by(
                    account_id=account.id
                ).first() is not None
        except Exception:
            is_payment_account = False

        has_memo_pair = (not is_payment_account) and bool(getattr(account, 'memo_account_id', None))
        if not has_memo_pair and getattr(account, 'tracks_weight', False):
            has_memo_pair = Account.query.filter_by(memo_account_id=account.id).first() is not None
        if has_memo_pair:
            return get_account_statement_merged(account_id)
    except Exception:
        pass

    def _safe_dt(value, fallback=None):
        if value is None:
            return fallback
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min)
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return fallback

    def _iso_or_none(value):
        dt = _safe_dt(value)
        return dt.isoformat() if dt else None

    def _effective_entry_dt(je: 'JournalEntry'):
        if not je:
            return datetime.min
        primary = _safe_dt(getattr(je, 'date', None))
        posted = _safe_dt(getattr(je, 'posted_at', None))
        created = _safe_dt(getattr(je, 'created_at', None))
        if primary and getattr(primary, 'time', None) and primary.time() != time.min:
            return primary
        return posted or created or primary or datetime.min

    opening_balance_cash = 0
    opening_balances_gold = {'18k': 0, '21k': 0, '22k': 0, '24k': 0}

    opening_filters = [
        JournalEntryLine.account_id == account_id,
        JournalEntry.entry_type == 'افتتاحي',
        JournalEntry.is_deleted == False,
        JournalEntryLine.is_deleted == False,
    ]
    if _db_has_column('journal_entry', 'is_posted'):
        opening_filters.append(JournalEntry.is_posted == True)
    if _db_has_column('journal_entry', 'is_draft'):
        opening_filters.append(JournalEntry.is_draft == False)

    opening_journal_lines = JournalEntryLine.query.join(JournalEntry).filter(*opening_filters).all()

    for line in opening_journal_lines:
        opening_balance_cash += (line.cash_debit or 0) - (line.cash_credit or 0)
        opening_balances_gold['18k'] += (line.debit_18k or 0) - (line.credit_18k or 0)
        opening_balances_gold['21k'] += (line.debit_21k or 0) - (line.credit_21k or 0)
        opening_balances_gold['22k'] += (line.debit_22k or 0) - (line.credit_22k or 0)
        opening_balances_gold['24k'] += (line.debit_24k or 0) - (line.credit_24k or 0)

    opening_balance_gold_normalized = (
        convert_to_main_karat(opening_balances_gold['18k'], 18) +
        convert_to_main_karat(opening_balances_gold['21k'], 21) +
        convert_to_main_karat(opening_balances_gold['22k'], 22) +
        convert_to_main_karat(opening_balances_gold['24k'], 24)
    )

    running_balance_cash = opening_balance_cash
    running_balances_gold = opening_balances_gold.copy()

    from sqlalchemy import or_

    journal_filters = [
        JournalEntryLine.account_id == account_id,
        or_(JournalEntry.entry_type.is_(None), JournalEntry.entry_type != 'افتتاحي'),
        JournalEntry.is_deleted == False,
        JournalEntryLine.is_deleted == False,
    ]
    if _db_has_column('journal_entry', 'is_posted'):
        journal_filters.append(JournalEntry.is_posted == True)
    if _db_has_column('journal_entry', 'is_draft'):
        journal_filters.append(JournalEntry.is_draft == False)

    journal_lines = (
        JournalEntryLine.query.join(JournalEntry)
        .filter(*journal_filters)
        .order_by(JournalEntry.date.asc(), JournalEntry.id.asc(), JournalEntryLine.id.asc())
        .all()
    )

    statement_lines = []
    total_cash_debit = 0
    total_cash_credit = 0
    total_gold_debit_normalized = 0
    total_gold_credit_normalized = 0

    merged = []
    for line in journal_lines:
        je = getattr(line, 'journal_entry', None)
        dt = _effective_entry_dt(je)
        merged.append(('journal', dt, getattr(je, 'id', 0) or 0, line.id, line))
    merged.sort(key=lambda x: (x[1], x[2], x[3]))

    for kind, _, _, _, line in merged:
        running_balances_gold['18k'] += (line.debit_18k or 0) - (line.credit_18k or 0)
        running_balances_gold['21k'] += (line.debit_21k or 0) - (line.credit_21k or 0)
        running_balances_gold['22k'] += (line.debit_22k or 0) - (line.credit_22k or 0)
        running_balances_gold['24k'] += (line.debit_24k or 0) - (line.credit_24k or 0)
        running_balance_cash += (line.cash_debit or 0) - (line.cash_credit or 0)

        gold_debit_normalized = (
            convert_to_main_karat(line.debit_18k or 0, 18) +
            convert_to_main_karat(line.debit_21k or 0, 21) +
            convert_to_main_karat(line.debit_22k or 0, 22) +
            convert_to_main_karat(line.debit_24k or 0, 24)
        )
        gold_credit_normalized = (
            convert_to_main_karat(line.credit_18k or 0, 18) +
            convert_to_main_karat(line.credit_21k or 0, 21) +
            convert_to_main_karat(line.credit_22k or 0, 22) +
            convert_to_main_karat(line.credit_24k or 0, 24)
        )

        je = getattr(line, 'journal_entry', None)
        if not je:
            continue

        statement_lines.append({
            'id': line.id,
            'date': _iso_or_none(_effective_entry_dt(je)),
            'description': je.description,
            'journal_entry_id': line.journal_entry_id,
            'entry_number': je.entry_number,
            'entry_type': je.entry_type,
            'reference_type': je.reference_type,
            'reference_id': je.reference_id,
            'reference_number': je.reference_number,
            'cash_debit': line.cash_debit or 0,
            'cash_credit': line.cash_credit or 0,
            'gold_debit': gold_debit_normalized,
            'gold_credit': gold_credit_normalized,
            'debit_18k': line.debit_18k or 0,
            'credit_18k': line.credit_18k or 0,
            'debit_21k': line.debit_21k or 0,
            'credit_21k': line.credit_21k or 0,
            'debit_22k': line.debit_22k or 0,
            'credit_22k': line.credit_22k or 0,
            'debit_24k': line.debit_24k or 0,
            'credit_24k': line.credit_24k or 0,
        })

        total_cash_debit += line.cash_debit or 0
        total_cash_credit += line.cash_credit or 0
        total_gold_debit_normalized += gold_debit_normalized
        total_gold_credit_normalized += gold_credit_normalized

    closing_balance_gold_normalized = (
        convert_to_main_karat(running_balances_gold['18k'], 18) +
        convert_to_main_karat(running_balances_gold['21k'], 21) +
        convert_to_main_karat(running_balances_gold['22k'], 22) +
        convert_to_main_karat(running_balances_gold['24k'], 24)
    )

    price_snapshot = get_current_gold_price()
    price_main = float(price_snapshot.get('price_per_gram_main_karat', 0.0) or 0.0)
    closing_cash_value = float(running_balance_cash or 0.0)
    closing_gold_value = float(closing_balance_gold_normalized or 0.0)
    estimated_gold_value = closing_gold_value * price_main
    estimated_total_value = estimated_gold_value + closing_cash_value

    qr_issued_at = datetime.now().replace(microsecond=0).isoformat() + 'Z'
    qr_signed_payload = _build_statement_qr_signed_payload(
        account=account,
        main_karat=main_karat,
        closing_gold_g=closing_gold_value,
        closing_cash=closing_cash_value,
        issued_at=qr_issued_at,
        is_merged=False,
    )
    qr_signature = _sign_qr_payload(qr_signed_payload)
    qr_verify_token = _build_qr_verify_token(signed_payload=qr_signed_payload, signature=qr_signature)
    qr_verify_url = _build_statement_verify_url(qr_verify_token)

    return jsonify({
        'account_id': account.id,
        'account_number': account.account_number,
        'account_name': account.name,
        'main_karat': main_karat,
        'qr_issued_at': qr_issued_at,
        'qr_signed_payload': qr_signed_payload,
        'qr_signature': qr_signature,
        'qr_verify_token': qr_verify_token,
        'qr_verify_url': qr_verify_url,
        'gold_price_snapshot': price_snapshot,
        'valuation': {
            'price_per_gram_main_karat': round(price_main, 4),
            'gold_value_estimate': round(estimated_gold_value, 2),
            'total_value_estimate': round(estimated_total_value, 2),
        },
        'opening_balance_cash': opening_balance_cash,
        'opening_balance_gold_normalized': opening_balance_gold_normalized,
        'opening_balance_gold_details': opening_balances_gold,
        'lines': statement_lines,
        'totals': {
            'cash_debit': total_cash_debit,
            'cash_credit': total_cash_credit,
            'gold_debit_normalized': total_gold_debit_normalized,
            'gold_credit_normalized': total_gold_credit_normalized,
        },
        'closing_balance_cash': running_balance_cash,
        'closing_balance_gold_normalized': closing_balance_gold_normalized,
        'closing_balance_gold_details': running_balances_gold,
    })

@accounts_bp.route('/accounts/by-number/<string:account_number>/statement', methods=['GET'])
@_wrap_api_exceptions('account_statement_failed', 'Failed to load account statement')
def get_account_statement_by_number(account_number):
    """Convenience endpoint: fetch statement using account_number (stable identifier)."""
    account = Account.query.filter_by(account_number=account_number).first_or_404()
    return get_account_statement(account.id)

@accounts_bp.route('/accounts/<int:account_id>/statement_merged', methods=['GET'])
@_wrap_api_exceptions('account_statement_merged_failed', 'Failed to load merged account statement')
def get_account_statement_merged(account_id):
    """كشف حساب مدمج - يجمع بين الحساب المالي وحساب المذكرة المقابل"""
    account = Account.query.get_or_404(account_id)
    main_karat = get_main_karat()

    def _safe_dt(value, fallback=None):
        if value is None:
            return fallback
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time.min)
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return fallback

    def _iso_or_none(value):
        dt = _safe_dt(value)
        return dt.isoformat() if dt else None

    def _effective_entry_dt(je: 'JournalEntry'):
        if not je:
            return datetime.min
        primary = _safe_dt(getattr(je, 'date', None))
        posted = _safe_dt(getattr(je, 'posted_at', None))
        created = _safe_dt(getattr(je, 'created_at', None))
        if primary and getattr(primary, 'time', None) and primary.time() != time.min:
            return primary
        return posted or created or primary or datetime.min

    memo_account = None
    if account.memo_account_id:
        memo_account = Account.query.get(account.memo_account_id)

    if not memo_account and account.tracks_weight:
        financial = Account.query.filter_by(memo_account_id=account_id).first()
        if financial:
            account, memo_account = financial, account

    primary_account_id = account.id

    opening_balance_cash = 0
    opening_balances_gold = {'18k': 0, '21k': 0, '22k': 0, '24k': 0}

    opening_filters = [
        JournalEntryLine.account_id == primary_account_id,
        JournalEntry.entry_type == 'افتتاحي',
        JournalEntry.is_deleted == False,
        JournalEntryLine.is_deleted == False,
    ]
    if _db_has_column('journal_entry', 'is_posted'):
        opening_filters.append(JournalEntry.is_posted == True)
    if _db_has_column('journal_entry', 'is_draft'):
        opening_filters.append(JournalEntry.is_draft == False)

    opening_journal_lines = JournalEntryLine.query.join(JournalEntry).filter(*opening_filters).all()

    for line in opening_journal_lines:
        opening_balance_cash += (line.cash_debit or 0) - (line.cash_credit or 0)
        opening_balances_gold['18k'] += (line.debit_18k or 0) - (line.credit_18k or 0)
        opening_balances_gold['21k'] += (line.debit_21k or 0) - (line.credit_21k or 0)
        opening_balances_gold['22k'] += (line.debit_22k or 0) - (line.credit_22k or 0)
        opening_balances_gold['24k'] += (line.debit_24k or 0) - (line.credit_24k or 0)

    if memo_account:
        memo_opening_filters = [
            JournalEntryLine.account_id == memo_account.id,
            JournalEntry.entry_type == 'افتتاحي',
            JournalEntry.is_deleted == False,
            JournalEntryLine.is_deleted == False,
        ]
        if _db_has_column('journal_entry', 'is_posted'):
            memo_opening_filters.append(JournalEntry.is_posted == True)
        if _db_has_column('journal_entry', 'is_draft'):
            memo_opening_filters.append(JournalEntry.is_draft == False)

        memo_opening_lines = (
            JournalEntryLine.query.join(JournalEntry)
            .filter(*memo_opening_filters)
            .all()
        )
        for line in memo_opening_lines:
            opening_balances_gold['18k'] += (line.debit_18k or 0) - (line.credit_18k or 0)
            opening_balances_gold['21k'] += (line.debit_21k or 0) - (line.credit_21k or 0)
            opening_balances_gold['22k'] += (line.debit_22k or 0) - (line.credit_22k or 0)
            opening_balances_gold['24k'] += (line.debit_24k or 0) - (line.credit_24k or 0)

    opening_balance_gold_normalized = (
        convert_to_main_karat(opening_balances_gold['18k'], 18) +
        convert_to_main_karat(opening_balances_gold['21k'], 21) +
        convert_to_main_karat(opening_balances_gold['22k'], 22) +
        convert_to_main_karat(opening_balances_gold['24k'], 24)
    )

    running_balance_cash = opening_balance_cash
    running_balances_gold = opening_balances_gold.copy()

    account_ids = [primary_account_id]
    if memo_account:
        account_ids.append(memo_account.id)

    from sqlalchemy import or_

    journal_filters = [
        JournalEntryLine.account_id.in_(account_ids),
        or_(JournalEntry.entry_type.is_(None), JournalEntry.entry_type != 'افتتاحي'),
        JournalEntry.is_deleted == False,
        JournalEntryLine.is_deleted == False,
    ]
    if _db_has_column('journal_entry', 'is_posted'):
        journal_filters.append(JournalEntry.is_posted == True)
    if _db_has_column('journal_entry', 'is_draft'):
        journal_filters.append(JournalEntry.is_draft == False)

    journal_lines = (
        JournalEntryLine.query.join(JournalEntry)
        .filter(*journal_filters)
        .order_by(JournalEntry.date.asc(), JournalEntry.id.asc(), JournalEntryLine.id.asc())
        .all()
    )

    lines_by_entry = {}
    for line in journal_lines:
        entry_id = line.journal_entry_id
        if entry_id not in lines_by_entry:
            je = getattr(line, 'journal_entry', None)
            dt = _effective_entry_dt(je)
            lines_by_entry[entry_id] = {
                'date': dt,
                'entry_id': entry_id,
                'entry_number': je.entry_number if je else None,
                'entry_type': je.entry_type if je else None,
                'description': je.description if je else None,
                'reference_type': je.reference_type if je else None,
                'reference_id': je.reference_id if je else None,
                'reference_number': je.reference_number if je else None,
                'cash_debit': 0, 'cash_credit': 0,
                'debit_18k': 0, 'credit_18k': 0,
                'debit_21k': 0, 'credit_21k': 0,
                'debit_22k': 0, 'credit_22k': 0,
                'debit_24k': 0, 'credit_24k': 0,
                'line_ids': []
            }

        entry_data = lines_by_entry[entry_id]
        entry_data['cash_debit'] += line.cash_debit or 0
        entry_data['cash_credit'] += line.cash_credit or 0
        entry_data['debit_18k'] += line.debit_18k or 0
        entry_data['credit_18k'] += line.credit_18k or 0
        entry_data['debit_21k'] += line.debit_21k or 0
        entry_data['credit_21k'] += line.credit_21k or 0
        entry_data['debit_22k'] += line.debit_22k or 0
        entry_data['credit_22k'] += line.credit_22k or 0
        entry_data['debit_24k'] += line.debit_24k or 0
        entry_data['credit_24k'] += line.credit_24k or 0
        entry_data['line_ids'].append(line.id)

    merged_lines = sorted(lines_by_entry.values(), key=lambda x: (x['date'], x['entry_id']))

    statement_lines = []
    total_cash_debit = 0
    total_cash_credit = 0
    total_gold_debit_normalized = 0
    total_gold_credit_normalized = 0

    for entry_data in merged_lines:
        running_balances_gold['18k'] += entry_data['debit_18k'] - entry_data['credit_18k']
        running_balances_gold['21k'] += entry_data['debit_21k'] - entry_data['credit_21k']
        running_balances_gold['22k'] += entry_data['debit_22k'] - entry_data['credit_22k']
        running_balances_gold['24k'] += entry_data['debit_24k'] - entry_data['credit_24k']
        running_balance_cash += entry_data['cash_debit'] - entry_data['cash_credit']

        gold_debit_normalized = (
            convert_to_main_karat(entry_data['debit_18k'], 18) +
            convert_to_main_karat(entry_data['debit_21k'], 21) +
            convert_to_main_karat(entry_data['debit_22k'], 22) +
            convert_to_main_karat(entry_data['debit_24k'], 24)
        )
        gold_credit_normalized = (
            convert_to_main_karat(entry_data['credit_18k'], 18) +
            convert_to_main_karat(entry_data['credit_21k'], 21) +
            convert_to_main_karat(entry_data['credit_22k'], 22) +
            convert_to_main_karat(entry_data['credit_24k'], 24)
        )

        statement_lines.append({
            'id': entry_data['line_ids'][0],
            'merged_ids': entry_data['line_ids'],
            'date': _iso_or_none(entry_data.get('date')),
            'description': entry_data['description'],
            'journal_entry_id': entry_data['entry_id'],
            'entry_number': entry_data['entry_number'],
            'entry_type': entry_data.get('entry_type'),
            'reference_type': entry_data['reference_type'],
            'reference_id': entry_data['reference_id'],
            'reference_number': entry_data['reference_number'],
            'cash_debit': entry_data['cash_debit'],
            'cash_credit': entry_data['cash_credit'],
            'gold_debit': gold_debit_normalized,
            'gold_credit': gold_credit_normalized,
            'debit_18k': entry_data['debit_18k'],
            'credit_18k': entry_data['credit_18k'],
            'debit_21k': entry_data['debit_21k'],
            'credit_21k': entry_data['credit_21k'],
            'debit_22k': entry_data['debit_22k'],
            'credit_22k': entry_data['credit_22k'],
            'debit_24k': entry_data['debit_24k'],
            'credit_24k': entry_data['credit_24k'],
        })

        total_cash_debit += entry_data['cash_debit']
        total_cash_credit += entry_data['cash_credit']
        total_gold_debit_normalized += gold_debit_normalized
        total_gold_credit_normalized += gold_credit_normalized

    closing_balance_gold_normalized = (
        convert_to_main_karat(running_balances_gold['18k'], 18) +
        convert_to_main_karat(running_balances_gold['21k'], 21) +
        convert_to_main_karat(running_balances_gold['22k'], 22) +
        convert_to_main_karat(running_balances_gold['24k'], 24)
    )

    price_snapshot = get_current_gold_price()
    price_main = float(price_snapshot.get('price_per_gram_main_karat', 0.0) or 0.0)
    closing_cash_value = float(running_balance_cash or 0.0)
    closing_gold_value = float(closing_balance_gold_normalized or 0.0)
    estimated_gold_value = closing_gold_value * price_main
    estimated_total_value = estimated_gold_value + closing_cash_value

    qr_issued_at = datetime.now().replace(microsecond=0).isoformat() + 'Z'
    qr_signed_payload = _build_statement_qr_signed_payload(
        account=account,
        main_karat=main_karat,
        closing_gold_g=closing_gold_value,
        closing_cash=closing_cash_value,
        issued_at=qr_issued_at,
        is_merged=bool(memo_account is not None),
    )
    qr_signature = _sign_qr_payload(qr_signed_payload)
    qr_verify_token = _build_qr_verify_token(signed_payload=qr_signed_payload, signature=qr_signature)
    qr_verify_url = _build_statement_verify_url(qr_verify_token)

    return jsonify({
        'account_id': account.id,
        'account_number': account.account_number,
        'account_name': account.name,
        'memo_account_name': memo_account.name if memo_account else None,
        'main_karat': main_karat,
        'is_merged': memo_account is not None,
        'qr_issued_at': qr_issued_at,
        'qr_signed_payload': qr_signed_payload,
        'qr_signature': qr_signature,
        'qr_verify_token': qr_verify_token,
        'qr_verify_url': qr_verify_url,
        'gold_price_snapshot': price_snapshot,
        'valuation': {
            'price_per_gram_main_karat': round(price_main, 4),
            'gold_value_estimate': round(estimated_gold_value, 2),
            'total_value_estimate': round(estimated_total_value, 2),
        },
        'opening_balance_cash': opening_balance_cash,
        'opening_balance_gold_normalized': opening_balance_gold_normalized,
        'opening_balance_gold_details': opening_balances_gold,
        'lines': statement_lines,
        'totals': {
            'cash_debit': total_cash_debit,
            'cash_credit': total_cash_credit,
            'gold_debit_normalized': total_gold_debit_normalized,
            'gold_credit_normalized': total_gold_credit_normalized,
        },
        'closing_balance_cash': running_balance_cash,
        'closing_balance_gold_normalized': closing_balance_gold_normalized,
        'closing_balance_gold_details': running_balances_gold,
    })

@accounts_bp.route('/accounts/by-number/<string:account_number>/statement_merged', methods=['GET'])
@_wrap_api_exceptions('account_statement_merged_failed', 'Failed to load merged account statement')
def get_account_statement_merged_by_number(account_number):
    """Convenience endpoint: fetch merged statement using account_number."""
    account = Account.query.filter_by(account_number=account_number).first_or_404()
    return get_account_statement_merged(account.id)

# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@accounts_bp.route('/accounts', methods=['GET'])
def get_accounts():
    """الحصول على جميع الحسابات مع دعم الهيكل الهرمي (parent-child)"""
    accounts = Account.query.all()

    live_by_id = live_balances_by_account_ids([a.id for a in accounts])

    result = []
    for acc in accounts:
        account_dict = acc.to_dict()

        try:
            sb = (
                SafeBox.query.filter(SafeBox.account_id == acc.id)
                .order_by(SafeBox.is_active.desc(), SafeBox.id.asc())
                .first()
            )
        except Exception:
            sb = None
        if sb is not None:
            try:
                account_dict['safe_box_id'] = int(sb.id)
            except Exception:
                account_dict['safe_box_id'] = None
            try:
                account_dict['safe_box_type'] = (getattr(sb, 'safe_type', None) or None)
            except Exception:
                account_dict['safe_box_type'] = None
            try:
                account_dict['safe_box_name'] = (getattr(sb, 'name', None) or None)
            except Exception:
                account_dict['safe_box_name'] = None

        live = live_by_id.get(int(acc.id)) if getattr(acc, 'id', None) is not None else None
        live = live if isinstance(live, dict) else {'cash': 0.0, '18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0}
        account_dict['balances'] = {
            'cash': round(float(live.get('cash') or 0.0), 2),
        }
        if bool(getattr(acc, 'tracks_weight', False)):
            w18 = float(live.get('18k') or 0.0)
            w21 = float(live.get('21k') or 0.0)
            w22 = float(live.get('22k') or 0.0)
            w24 = float(live.get('24k') or 0.0)
            account_dict['balances']['weight'] = {
                '18k': round(w18, 3),
                '21k': round(w21, 3),
                '22k': round(w22, 3),
                '24k': round(w24, 3),
                'total': round(
                    convert_to_main_karat(w18, 18) +
                    convert_to_main_karat(w21, 21) +
                    convert_to_main_karat(w22, 22) +
                    convert_to_main_karat(w24, 24),
                    3
                ),
            }

        if acc.parent_id:
            parent = Account.query.get(acc.parent_id)
            if parent:
                account_dict['parent_account'] = {
                    'id': parent.id,
                    'account_number': parent.account_number,
                    'name': parent.name
                }

        children = Account.query.filter_by(parent_id=acc.id).all()
        if children:
            account_dict['sub_accounts'] = [{
                'id': child.id,
                'account_number': child.account_number,
                'name': child.name,
                'bank_name': child.bank_name,
                'account_number_external': child.account_number_external
            } for child in children]

        result.append(account_dict)

    return jsonify(result)

@accounts_bp.route('/accounts/<int:id>', methods=['GET'])
@_wrap_api_exceptions('account_get_failed', 'Failed to load account')
def get_account(id):
    """Fetch a single account by id."""
    account = Account.query.get_or_404(id)
    payload = account.to_dict()

    try:
        sb = (
            SafeBox.query.filter(SafeBox.account_id == account.id)
            .order_by(SafeBox.is_active.desc(), SafeBox.id.asc())
            .first()
        )
    except Exception:
        sb = None
    if sb is not None:
        try:
            payload['safe_box_id'] = int(sb.id)
        except Exception:
            payload['safe_box_id'] = None
        try:
            payload['safe_box_type'] = (getattr(sb, 'safe_type', None) or None)
        except Exception:
            payload['safe_box_type'] = None
        try:
            payload['safe_box_name'] = (getattr(sb, 'name', None) or None)
        except Exception:
            payload['safe_box_name'] = None

    live = live_balances_by_account_ids([account.id]).get(int(account.id))
    live = live if isinstance(live, dict) else {'cash': 0.0, '18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0}
    payload['balances'] = {
        'cash': round(float(live.get('cash') or 0.0), 2),
    }
    if bool(getattr(account, 'tracks_weight', False)):
        w18 = float(live.get('18k') or 0.0)
        w21 = float(live.get('21k') or 0.0)
        w22 = float(live.get('22k') or 0.0)
        w24 = float(live.get('24k') or 0.0)
        payload['balances']['weight'] = {
            '18k': round(w18, 3),
            '21k': round(w21, 3),
            '22k': round(w22, 3),
            '24k': round(w24, 3),
            'total': round(
                convert_to_main_karat(w18, 18) +
                convert_to_main_karat(w21, 21) +
                convert_to_main_karat(w22, 22) +
                convert_to_main_karat(w24, 24),
                3
            ),
        }

    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@accounts_bp.route('/accounts/export', methods=['GET'])
@require_permission('accounts.view')
def export_accounts():
    """Export chart of accounts structure (no balances)."""
    accounts = Account.query.order_by(Account.account_number.asc()).all()
    id_to_number = {acc.id: acc.account_number for acc in accounts}

    exported = []
    for acc in accounts:
        exported.append({
            'account_number': acc.account_number,
            'name': acc.name,
            'type': acc.type,
            'transaction_type': acc.transaction_type,
            'tracks_weight': bool(acc.tracks_weight),
            'bank_name': acc.bank_name,
            'account_number_external': acc.account_number_external,
            'account_type': acc.account_type,
            'parent_account_number': id_to_number.get(acc.parent_id) if acc.parent_id else None,
            'memo_account_number': id_to_number.get(acc.memo_account_id) if acc.memo_account_id else None,
        })

    return jsonify({
        'version': 1,
        'exported_at': datetime.now().isoformat(),
        'count': len(exported),
        'accounts': exported,
    })

@accounts_bp.route('/accounts/import', methods=['POST'])
@require_permission('accounts.edit')
def import_accounts():
    """Import (upsert) chart of accounts structure."""
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({'error': 'Invalid or missing JSON body'}), 400

    accounts_data = payload
    if isinstance(payload, dict):
        accounts_data = payload.get('accounts', payload.get('data'))

    if not isinstance(accounts_data, list):
        return jsonify({'error': 'accounts must be a JSON array'}), 400

    normalized = []
    for idx, row in enumerate(accounts_data, start=1):
        if not isinstance(row, dict):
            return jsonify({'error': f'Invalid account row at index {idx}'}), 400

        account_number = (row.get('account_number') or '').strip()
        name = (row.get('name') or '').strip()
        acc_type = (row.get('type') or '').strip()
        transaction_type = (row.get('transaction_type') or 'both').strip() or 'both'

        if not account_number:
            return jsonify({'error': f'account_number is required (index {idx})'}), 400
        if not name:
            return jsonify({'error': f'name is required (account {account_number})'}), 400
        if not acc_type:
            return jsonify({'error': f'type is required (account {account_number})'}), 400

        normalized.append({
            'account_number': account_number,
            'name': name,
            'type': acc_type,
            'transaction_type': transaction_type,
            'tracks_weight': bool(row.get('tracks_weight', False)),
            'bank_name': row.get('bank_name'),
            'account_number_external': row.get('account_number_external'),
            'account_type': row.get('account_type'),
            'parent_account_number': (row.get('parent_account_number') or None),
            'memo_account_number': (row.get('memo_account_number') or None),
        })

    numbers = [r['account_number'] for r in normalized]
    existing = Account.query.filter(Account.account_number.in_(numbers)).all()
    existing_by_number = {acc.account_number: acc for acc in existing}

    created = 0
    updated = 0

    for row in normalized:
        acc = existing_by_number.get(row['account_number'])
        if acc is None:
            acc = Account(
                account_number=row['account_number'],
                name=row['name'],
                type=row['type'],
                transaction_type=row['transaction_type'],
                tracks_weight=row['tracks_weight'],
            )
            created += 1
        else:
            acc.name = row['name']
            acc.type = row['type']
            acc.transaction_type = row['transaction_type']
            acc.tracks_weight = row['tracks_weight']
            updated += 1

        acc.bank_name = row['bank_name']
        acc.account_number_external = row['account_number_external']
        acc.account_type = row['account_type']

        db.session.add(acc)

    db.session.flush()

    imported_accounts = Account.query.filter(Account.account_number.in_(numbers)).all()
    number_to_id = {acc.account_number: acc.id for acc in imported_accounts}
    accounts_by_number = {acc.account_number: acc for acc in imported_accounts}

    skip_ref_check = bool(payload.get('skip_ref_check') if isinstance(payload, dict) else False)

    all_db_acc = {a.account_number: a.id for a in Account.query.all()}
    number_to_id_extended = {**all_db_acc, **number_to_id}

    missing_refs = []
    for row in normalized:
        p = row.get('parent_account_number')
        m = row.get('memo_account_number')
        if p and p not in number_to_id_extended:
            missing_refs.append({'account_number': row['account_number'], 'missing': 'parent_account_number', 'ref': p})
        if m and m not in number_to_id_extended:
            missing_refs.append({'account_number': row['account_number'], 'missing': 'memo_account_number', 'ref': m})
    if missing_refs and not skip_ref_check:
        db.session.rollback()
        return jsonify({
            'error': 'missing_references',
            'message': 'Some parent/memo references are missing from the import payload and DB. Pass skip_ref_check:true to ignore.',
            'missing': missing_refs,
        }), 400

    relinked = 0
    for row in normalized:
        acc = accounts_by_number[row['account_number']]
        parent_num = row.get('parent_account_number')
        memo_num = row.get('memo_account_number')

        new_parent_id = number_to_id_extended.get(parent_num) if parent_num else None
        new_memo_id = number_to_id_extended.get(memo_num) if memo_num else None

        memo_changed = acc.memo_account_id != new_memo_id
        if acc.parent_id != new_parent_id or memo_changed:
            relinked += 1

        acc.parent_id = new_parent_id
        db.session.add(acc)

        # الربط/الفسخ عبر الخدمة المركزية فقط -- انظر account_pair_service.py.
        if memo_changed:
            if new_memo_id is None:
                unlink_account(acc, created_by='import_accounts_route')
            else:
                memo_acc = accounts_by_number.get(memo_num) or Account.query.get(new_memo_id)
                if memo_acc:
                    link_accounts(acc, memo_acc, created_by='import_accounts_route')

    db.session.commit()

    return jsonify({
        'success': True,
        'created': created,
        'updated': updated,
        'relinked': relinked,
        'count': len(normalized),
    }), 200

@accounts_bp.route('/accounts/balances', methods=['GET'])
def get_accounts_balances():
    """الحصول على أرصدة جميع الحسابات (Cash + Gold) دفعة واحدة"""
    accounts = Account.query.all()

    balances = {}
    live_by_id = live_balances_by_account_ids([a.id for a in accounts])

    for acc in accounts:
        live = live_by_id.get(int(acc.id)) if getattr(acc, 'id', None) is not None else None
        live = live if isinstance(live, dict) else {'cash': 0.0, '18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0}

        cash = float(live.get('cash') or 0.0)
        g18 = float(live.get('18k') or 0.0)
        g21 = float(live.get('21k') or 0.0)
        g22 = float(live.get('22k') or 0.0)
        g24 = float(live.get('24k') or 0.0)

        balances[acc.id] = {
            'account_id': acc.id,
            'account_number': acc.account_number,
            'account_name': acc.name,
            'cash': round(cash, 2),
            'gold_18k': round(g18, 3),
            'gold_21k': round(g21, 3),
            'gold_22k': round(g22, 3),
            'gold_24k': round(g24, 3),
            'has_balance': abs(cash) > 0.01 or abs(g18) > 0.001 or abs(g21) > 0.001 or abs(g22) > 0.001 or abs(g24) > 0.001,
        }

    return jsonify(balances)

@accounts_bp.route('/accounts/hierarchy', methods=['GET'])
def get_accounts_hierarchy():
    """الحصول على شجرة الحسابات في شكل هرمي (tree structure)"""
    root_accounts = Account.query.filter_by(parent_id=None).all()

    def build_tree(account):
        node = {
            'id': account.id,
            'account_number': account.account_number,
            'name': account.name,
            'type': account.type,
            'transaction_type': account.transaction_type,
            'children': []
        }
        children = Account.query.filter_by(parent_id=account.id).all()
        for child in children:
            node['children'].append(build_tree(child))
        return node

    tree = [build_tree(acc) for acc in root_accounts]

    return jsonify({
        'accounts_tree': tree,
        'total_accounts': Account.query.count()
    })

@accounts_bp.route('/accounts/next-number/<parent_number>', methods=['GET'])
def get_next_account_number_api(parent_number):
    """API endpoint للحصول على رقم الحساب التالي المتاح"""
    try:
        from account_number_generator import suggest_account_number_with_validation

        result = suggest_account_number_with_validation(parent_number)
        return jsonify(result), 200

    except ValueError as e:
        return jsonify({
            'suggested_number': None,
            'is_valid': False,
            'message': str(e),
        }), 400
    except Exception as e:
        return jsonify({
            'suggested_number': None,
            'is_valid': False,
            'message': f'Failed to get next account number: {str(e)}',
        }), 400

@accounts_bp.route('/accounts/validate-number', methods=['POST'])
def validate_account_number_api():
    """API endpoint للتحقق من صحة رقم حساب"""
    try:
        from account_number_generator import validate_account_number

        data = request.get_json(silent=True) or {}
        account_number = (data.get('account_number') or '').strip()
        parent_account_number = (data.get('parent_account_number') or '').strip()
        exclude_account_id = data.get('exclude_account_id')
        try:
            exclude_account_id = int(exclude_account_id) if exclude_account_id is not None else None
        except Exception:
            exclude_account_id = None

        if not account_number or not parent_account_number:
            return jsonify({
                'is_valid': False,
                'message': 'يجب تقديم رقم الحساب ورقم الحساب الأب'
            }), 400

        result = validate_account_number(
            account_number,
            parent_account_number,
            exclude_account_id=exclude_account_id,
        )
        return jsonify(result), 200

    except Exception as e:
        return jsonify({
            'is_valid': False,
            'message': f'خطأ: {str(e)}'
        }), 400

@accounts_bp.route('/accounts/capacity/<category_number>', methods=['GET'])
def get_account_capacity_api(category_number):
    """API endpoint للحصول على معلومات السعة لفئة حسابات"""
    try:
        from account_number_generator import get_customer_account_capacity

        result = get_customer_account_capacity(category_number)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({
            'error': f'خطأ: {str(e)}'
        }), 400

@accounts_bp.route('/accounts', methods=['POST'])
def add_account():
    """إضافة حساب جديد مع إنشاء حساب موازي تلقائياً"""
    data = request.get_json(silent=True) or {}

    raw_account_number = str(data.get('account_number', '')).strip()
    account_number = ''.join(ch for ch in raw_account_number if ch.isdigit())

    if not account_number:
        return jsonify({'error': 'رقم الحساب مطلوب'}), 400

    parent_id = data.get('parent_id')
    parent_account = None
    if parent_id is not None:
        parent_account = Account.query.get(parent_id)
        if not parent_account:
            return jsonify({'error': 'الحساب الأب غير موجود'}), 400

        from account_number_generator import validate_account_number

        validation = validate_account_number(account_number, parent_account.account_number)
        if not validation.get('is_valid'):
            return jsonify({'error': validation.get('message', 'رقم الحساب غير صالح')}), 400

    is_memo_account = account_number.startswith('7')
    desired_transaction_type = 'gold' if is_memo_account else 'cash'
    desired_tracks_weight = True if is_memo_account else False

    if parent_account is not None:
        parent_is_memo = str(parent_account.account_number or '').startswith('7')
        if parent_is_memo != is_memo_account:
            return jsonify({'error': 'رقم الحساب يجب أن يتبع نفس مخطط الأب (مالي/مذكرة)'}), 400

    new_account = Account(
        account_number=account_number,
        name=data['name'],
        type=data['type'],
        parent_id=parent_id,
        transaction_type=desired_transaction_type,
        bank_name=data.get('bank_name'),
        account_number_external=data.get('account_number_external'),
        account_type=data.get('account_type'),
        tracks_weight=bool(desired_tracks_weight),
        include_in_gram_profit=bool(data.get('include_in_gram_profit', False)),
        exclude_from_gram_profit=bool(data.get('exclude_from_gram_profit', False)),
    )
    db.session.add(new_account)
    db.session.flush()

    parallel_account = None
    if data.get('create_parallel', True):
        try:
            parallel_account = new_account.create_parallel_account()
        except Exception as e:
            print(f"⚠️  تعذر إنشاء حساب موازي: {e}")

    db.session.commit()

    result = new_account.to_dict()
    if parallel_account:
        result['parallel_account'] = {
            'id': parallel_account.id,
            'account_number': parallel_account.account_number,
            'name': parallel_account.name,
            'transaction_type': parallel_account.transaction_type
        }

    return jsonify(result), 201

@accounts_bp.route('/accounts/<int:id>', methods=['PUT'])
def update_account(id):
    account = Account.query.get_or_404(id)
    data = request.get_json(silent=True) or {}

    if 'account_number' in data and data.get('account_number') is not None:
        raw_account_number = str(data.get('account_number', '')).strip()
        normalized = ''.join(ch for ch in raw_account_number if ch.isdigit())
        if normalized:
            account.account_number = normalized
    account.name = data.get('name', account.name)
    account.type = data.get('type', account.type)
    account.parent_id = data.get('parent_id', account.parent_id)

    if 'bank_name' in data:
        account.bank_name = data['bank_name']
    if 'account_number_external' in data:
        account.account_number_external = data['account_number_external']
    if 'account_type' in data:
        account.account_type = data['account_type']
    if 'include_in_gram_profit' in data:
        account.include_in_gram_profit = bool(data['include_in_gram_profit'])
    if 'exclude_from_gram_profit' in data:
        account.exclude_from_gram_profit = bool(data['exclude_from_gram_profit'])

    is_memo_account = str(account.account_number or '').startswith('7')
    account.transaction_type = 'gold' if is_memo_account else 'cash'
    account.tracks_weight = True if is_memo_account else False

    if account.parent_id is not None:
        parent = Account.query.get(account.parent_id)
        if parent is not None:
            parent_is_memo = str(parent.account_number or '').startswith('7')
            if parent_is_memo != is_memo_account:
                return jsonify({'error': 'لا يمكن نقل الحساب بين المالي والمذكرة عبر parent_id'}), 400
            account.tracks_weight = bool(parent.tracks_weight)

    db.session.commit()
    return jsonify(account.to_dict())

@accounts_bp.route('/accounts/<int:id>', methods=['DELETE'])
def delete_account(id):
    account = Account.query.get_or_404(id)
    db.session.delete(account)
    db.session.commit()
    return jsonify({'result': 'success'})

# ---------------------------------------------------------------------------
# Account ledger
# ---------------------------------------------------------------------------

@accounts_bp.route('/account_ledger/<int:account_id>', methods=['GET'])
@require_permission('accounts.view')
def get_account_ledger(account_id):
    """دفتر الأستاذ لحساب محدد مع تفاصيل كاملة"""
    account = Account.query.get_or_404(account_id)

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    karat_detail = request.args.get('karat_detail', 'true').lower() == 'true'

    query = JournalEntryLine.query.join(JournalEntry).filter(
        JournalEntryLine.account_id == account_id,
        JournalEntryLine.is_deleted == False
    )

    start_dt = None
    if start_date:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        query = query.filter(JournalEntry.date >= start_dt)

    if end_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        query = query.filter(JournalEntry.date <= end_dt)

    opening_cash = 0
    opening_18k = 0
    opening_21k = 0
    opening_22k = 0
    opening_24k = 0

    if start_dt:
        opening_query = JournalEntryLine.query.join(JournalEntry).filter(
            JournalEntryLine.account_id == account_id,
            JournalEntryLine.is_deleted == False,
            JournalEntry.date < start_dt
        )
        for line in opening_query.all():
            opening_cash += (line.cash_debit or 0) - (line.cash_credit or 0)
            opening_18k += (line.debit_18k or 0) - (line.credit_18k or 0)
            opening_21k += (line.debit_21k or 0) - (line.credit_21k or 0)
            opening_22k += (line.debit_22k or 0) - (line.credit_22k or 0)
            opening_24k += (line.debit_24k or 0) - (line.credit_24k or 0)

    lines = query.order_by(JournalEntry.date.asc(), JournalEntry.id.asc()).all()

    running_cash = opening_cash
    running_18k = opening_18k
    running_21k = opening_21k
    running_22k = opening_22k
    running_24k = opening_24k

    result = []
    for line in lines:
        gold_debit_normalized = (
            convert_to_main_karat(line.debit_18k or 0, 18) +
            convert_to_main_karat(line.debit_21k or 0, 21) +
            convert_to_main_karat(line.debit_22k or 0, 22) +
            convert_to_main_karat(line.debit_24k or 0, 24)
        )
        gold_credit_normalized = (
            convert_to_main_karat(line.credit_18k or 0, 18) +
            convert_to_main_karat(line.credit_21k or 0, 21) +
            convert_to_main_karat(line.credit_22k or 0, 22) +
            convert_to_main_karat(line.credit_24k or 0, 24)
        )

        running_cash += (line.cash_debit or 0) - (line.cash_credit or 0)
        running_18k += (line.debit_18k or 0) - (line.credit_18k or 0)
        running_21k += (line.debit_21k or 0) - (line.credit_21k or 0)
        running_22k += (line.debit_22k or 0) - (line.credit_22k or 0)
        running_24k += (line.debit_24k or 0) - (line.credit_24k or 0)

        entry_data = {
            'id': line.id,
            'journal_entry_id': line.journal_entry.id,
            'date': line.journal_entry.date.isoformat(),
            'description': line.journal_entry.description or line.description,
            'cash_debit': round(line.cash_debit or 0, 2),
            'cash_credit': round(line.cash_credit or 0, 2),
            'gold_debit': round(gold_debit_normalized, 3),
            'gold_credit': round(gold_credit_normalized, 3),
            'running_balance': {
                'cash': round(running_cash, 2),
                'gold_normalized': round(
                    convert_to_main_karat(running_18k, 18) +
                    convert_to_main_karat(running_21k, 21) +
                    convert_to_main_karat(running_22k, 22) +
                    convert_to_main_karat(running_24k, 24),
                    3
                )
            }
        }

        if karat_detail:
            entry_data['karat_details'] = {
                '18k': {'debit': round(line.debit_18k or 0, 3), 'credit': round(line.credit_18k or 0, 3)},
                '21k': {'debit': round(line.debit_21k or 0, 3), 'credit': round(line.credit_21k or 0, 3)},
                '22k': {'debit': round(line.debit_22k or 0, 3), 'credit': round(line.credit_22k or 0, 3)},
                '24k': {'debit': round(line.debit_24k or 0, 3), 'credit': round(line.credit_24k or 0, 3)},
            }
            entry_data['running_balance']['by_karat'] = {
                '18k': round(running_18k, 3),
                '21k': round(running_21k, 3),
                '22k': round(running_22k, 3),
                '24k': round(running_24k, 3),
            }

        result.append(entry_data)

    return jsonify({
        'account': {
            'id': account.id,
            'name': account.name,
            'number': account.account_number,
            'type': account.account_type
        },
        'opening_balance': {
            'cash': round(opening_cash, 2),
            'gold_normalized': round(
                convert_to_main_karat(opening_18k, 18) +
                convert_to_main_karat(opening_21k, 21) +
                convert_to_main_karat(opening_22k, 22) +
                convert_to_main_karat(opening_24k, 24),
                3
            ),
            'by_karat': {
                '18k': round(opening_18k, 3),
                '21k': round(opening_21k, 3),
                '22k': round(opening_22k, 3),
                '24k': round(opening_24k, 3),
            } if karat_detail else None
        },
        'closing_balance': {
            'cash': round(running_cash, 2),
            'gold_normalized': round(
                convert_to_main_karat(running_18k, 18) +
                convert_to_main_karat(running_21k, 21) +
                convert_to_main_karat(running_22k, 22) +
                convert_to_main_karat(running_24k, 24),
                3
            ),
            'by_karat': {
                '18k': round(running_18k, 3),
                '21k': round(running_21k, 3),
                '22k': round(running_22k, 3),
                '24k': round(running_24k, 3),
            } if karat_detail else None
        },
        'entries': result,
        'total_entries': len(result),
        'filters': {
            'start_date': start_date,
            'end_date': end_date,
            'karat_detail': karat_detail,
        }
    })

# ---------------------------------------------------------------------------
# Accounting mappings
# ---------------------------------------------------------------------------

@accounts_bp.route('/accounting-mappings', methods=['GET'])
@require_permission('system.settings')
def get_accounting_mappings():
    """الحصول على جميع إعدادات الربط المحاسبي"""
    try:
        operation_type = request.args.get('operation_type')

        if operation_type:
            mappings = AccountingMapping.query.filter_by(
                operation_type=operation_type,
                is_active=True
            ).all()
        else:
            mappings = AccountingMapping.query.filter_by(is_active=True).all()

        return jsonify([mapping.to_dict() for mapping in mappings]), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@accounts_bp.route('/accounting-mappings', methods=['POST'])
@require_permission('system.settings')
def create_accounting_mapping():
    """إنشاء أو تحديث إعداد ربط محاسبي"""
    try:
        data = request.get_json()

        operation_type = data.get('operation_type')
        account_type = data.get('account_type')
        account_id = data.get('account_id')

        if not all([operation_type, account_type, account_id]):
            return jsonify({
                'status': 'error',
                'message': 'يجب تحديد نوع العملية ونوع الحساب والحساب المحاسبي'
            }), 400

        account = Account.query.get(account_id)
        if not account:
            return jsonify({'status': 'error', 'message': 'الحساب المحاسبي غير موجود'}), 404

        existing_mapping = AccountingMapping.query.filter_by(
            operation_type=operation_type,
            account_type=account_type
        ).first()

        if existing_mapping:
            existing_mapping.account_id = account_id
            existing_mapping.allocation_percentage = data.get('allocation_percentage')
            existing_mapping.description = data.get('description')
            existing_mapping.is_active = data.get('is_active', True)
            db.session.commit()
            return jsonify({
                'status': 'success',
                'message': 'تم تحديث إعدادات الربط بنجاح',
                'mapping': existing_mapping.to_dict()
            }), 200
        else:
            new_mapping = AccountingMapping(
                operation_type=operation_type,
                account_type=account_type,
                account_id=account_id,
                allocation_percentage=data.get('allocation_percentage'),
                description=data.get('description'),
                is_active=data.get('is_active', True),
                created_by=data.get('created_by', 'system')
            )
            db.session.add(new_mapping)
            db.session.commit()
            return jsonify({
                'status': 'success',
                'message': 'تم إنشاء إعدادات الربط بنجاح',
                'mapping': new_mapping.to_dict()
            }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@accounts_bp.route('/accounting-mappings/batch', methods=['POST'])
@require_permission('system.settings')
def batch_create_accounting_mappings():
    """إنشاء عدة إعدادات ربط دفعة واحدة"""
    try:
        data = request.get_json()
        mappings_data = data.get('mappings', [])

        if not mappings_data:
            return jsonify({'status': 'error', 'message': 'لا توجد بيانات للإنشاء'}), 400

        created_mappings = []
        updated_mappings = []
        errors = []

        for mapping_data in mappings_data:
            try:
                operation_type = mapping_data.get('operation_type')
                account_type = mapping_data.get('account_type')
                account_id = mapping_data.get('account_id')

                if not all([operation_type, account_type, account_id]):
                    errors.append(f'بيانات ناقصة: {mapping_data}')
                    continue

                account = Account.query.get(account_id)
                if not account:
                    errors.append(f'الحساب {account_id} غير موجود')
                    continue

                existing_mapping = AccountingMapping.query.filter_by(
                    operation_type=operation_type,
                    account_type=account_type
                ).first()

                if existing_mapping:
                    existing_mapping.account_id = account_id
                    existing_mapping.allocation_percentage = mapping_data.get('allocation_percentage')
                    existing_mapping.description = mapping_data.get('description')
                    existing_mapping.is_active = mapping_data.get('is_active', True)
                    updated_mappings.append(existing_mapping.to_dict())
                else:
                    new_mapping = AccountingMapping(
                        operation_type=operation_type,
                        account_type=account_type,
                        account_id=account_id,
                        allocation_percentage=mapping_data.get('allocation_percentage'),
                        description=mapping_data.get('description'),
                        is_active=mapping_data.get('is_active', True),
                        created_by=data.get('created_by', 'system')
                    )
                    db.session.add(new_mapping)
                    created_mappings.append(new_mapping.to_dict())

            except Exception as e:
                errors.append(f'خطأ في معالجة {mapping_data}: {str(e)}')

        db.session.commit()

        return jsonify({
            'status': 'success',
            'message': f'تم إنشاء {len(created_mappings)} وتحديث {len(updated_mappings)} من إعدادات الربط',
            'created': created_mappings,
            'updated': updated_mappings,
            'errors': errors
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@accounts_bp.route('/accounting-mappings/<int:mapping_id>', methods=['DELETE'])
@require_permission('system.settings')
def delete_accounting_mapping(mapping_id):
    """حذف إعداد ربط محاسبي"""
    try:
        mapping = AccountingMapping.query.get(mapping_id)

        if not mapping:
            return jsonify({'status': 'error', 'message': 'إعدادات الربط غير موجودة'}), 404

        db.session.delete(mapping)
        db.session.commit()

        return jsonify({'status': 'success', 'message': 'تم حذف إعدادات الربط بنجاح'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@accounts_bp.route('/accounting-mappings/get-account', methods=['POST'])
@require_permission('system.settings')
def get_mapped_account():
    """الحصول على الحساب المرتبط لعملية معينة"""
    try:
        data = request.get_json()
        operation_type = data.get('operation_type')
        account_type = data.get('account_type')

        if not all([operation_type, account_type]):
            return jsonify({
                'status': 'error',
                'message': 'يجب تحديد نوع العملية ونوع الحساب'
            }), 400

        mapping = AccountingMapping.query.filter_by(
            operation_type=operation_type,
            account_type=account_type,
            is_active=True
        ).first()

        if not mapping:
            return jsonify({
                'status': 'error',
                'message': 'لا يوجد ربط محاسبي لهذه العملية'
            }), 404

        return jsonify({'status': 'success', 'mapping': mapping.to_dict()}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
