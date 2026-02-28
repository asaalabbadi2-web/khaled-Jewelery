# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_, func, or_

from models import Account, JournalEntry, JournalEntryLine, Supplier, db

_DB_COLUMN_CACHE: Dict[tuple, bool] = {}


def _db_has_column(table_name: str, column_name: str) -> bool:
    key = (table_name, column_name)
    cached = _DB_COLUMN_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from sqlalchemy import inspect as sa_inspect

        inspector = sa_inspect(db.engine)
        cols = {c.get('name') for c in inspector.get_columns(table_name)}
        exists = column_name in cols
    except Exception:
        exists = False
    _DB_COLUMN_CACHE[key] = exists
    return exists


def compute_live_supplier_balances(
    suppliers: Iterable[Supplier],
) -> Dict[int, Dict[str, float]]:
    """Compute supplier balances directly from the journal (ledger).

    Returns mapping supplier_id -> {'cash','18k','21k','22k','24k'}.

    This mirrors the filtering behavior used by the suppliers list endpoint:
    - include supplier payable liability lines (21%)
    - include the supplier's own financial + memo accounts
    - include mis-tagged lines posted to the supplier's own accounts when
      supplier_id is NULL.
    """

    suppliers = list(suppliers)
    supplier_ids: List[int] = []
    for s in suppliers:
        if getattr(s, 'id', None) is None:
            continue
        try:
            supplier_ids.append(int(s.id))
        except Exception:
            continue

    supplier_fin_account_ids: List[int] = []
    for s in suppliers:
        if not getattr(s, 'account_id', None):
            continue
        try:
            supplier_fin_account_ids.append(int(s.account_id))
        except Exception:
            continue

    financial_accounts: Dict[int, Account] = {}
    if supplier_fin_account_ids:
        for a in Account.query.filter(Account.id.in_(supplier_fin_account_ids)).all():
            try:
                financial_accounts[int(a.id)] = a
            except Exception:
                continue

    allowed_account_to_supplier: Dict[int, int] = {}
    for s in suppliers:
        try:
            sid = int(s.id)
        except Exception:
            continue

        fin_id: Optional[int]
        try:
            fin_id = int(s.account_id) if s.account_id else None
        except Exception:
            fin_id = None

        if not fin_id:
            continue

        allowed_account_to_supplier[fin_id] = sid

        fin_acc = financial_accounts.get(fin_id)
        memo_id: Optional[int]
        try:
            memo_id = int(fin_acc.memo_account_id) if fin_acc and fin_acc.memo_account_id else None
        except Exception:
            memo_id = None
        if memo_id:
            allowed_account_to_supplier[memo_id] = sid

        # Office-linked suppliers can post directly to a dedicated office account stored in
        # supplier.account_category_id (tracks_weight=True, transaction_type='both').
        # Include it so mis-tagged lines (supplier_id NULL) still reconcile.
        try:
            raw_office_acc_id = getattr(s, 'account_category_id', None)
            if raw_office_acc_id not in (None, '', 0, '0', False):
                office_acc = Account.query.get(int(raw_office_acc_id))
                if (
                    office_acc
                    and bool(getattr(office_acc, 'tracks_weight', False))
                    and str(getattr(office_acc, 'transaction_type', '') or '').lower() == 'both'
                ):
                    allowed_account_to_supplier[int(office_acc.id)] = sid
        except Exception:
            pass

    allowed_account_ids = list({int(x) for x in allowed_account_to_supplier.keys() if x})

    jl_filters = [
        JournalEntry.is_deleted == False,
        JournalEntryLine.is_deleted == False,
    ]
    if _db_has_column('journal_entry', 'is_draft'):
        jl_filters.append(JournalEntry.is_draft == False)
    elif _db_has_column('journal_entry', 'is_posted'):
        jl_filters.append(JournalEntry.is_posted == True)

    balances_by_supplier: Dict[int, Dict[str, float]] = {}

    payable_filter = and_(Account.type == 'Liability', Account.account_number.like('21%'))
    account_filter = payable_filter
    if allowed_account_ids:
        account_filter = or_(Account.id.in_(allowed_account_ids), payable_filter)

    # (A) Tagged lines grouped by supplier_id
    if supplier_ids:
        tagged_rows = (
            db.session.query(
                JournalEntryLine.supplier_id.label('supplier_id'),
                (
                    func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0)
                ).label('cash'),
                (
                    func.coalesce(func.sum(JournalEntryLine.debit_18k), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.credit_18k), 0.0)
                ).label('b18'),
                (
                    func.coalesce(func.sum(JournalEntryLine.debit_21k), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.credit_21k), 0.0)
                ).label('b21'),
                (
                    func.coalesce(func.sum(JournalEntryLine.debit_22k), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.credit_22k), 0.0)
                ).label('b22'),
                (
                    func.coalesce(func.sum(JournalEntryLine.debit_24k), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.credit_24k), 0.0)
                ).label('b24'),
            )
            .join(JournalEntry)
            .join(Account, JournalEntryLine.account_id == Account.id)
            .filter(JournalEntryLine.supplier_id.in_(supplier_ids))
            .filter(JournalEntry.is_deleted == False)
            .filter(*jl_filters)
            .filter(account_filter)
            .group_by(JournalEntryLine.supplier_id)
            .all()
        )
        for r in tagged_rows:
            try:
                sid = int(r.supplier_id)
            except Exception:
                continue
            balances_by_supplier[sid] = {
                'cash': float(getattr(r, 'cash', 0.0) or 0.0),
                '18k': float(getattr(r, 'b18', 0.0) or 0.0),
                '21k': float(getattr(r, 'b21', 0.0) or 0.0),
                '22k': float(getattr(r, 'b22', 0.0) or 0.0),
                '24k': float(getattr(r, 'b24', 0.0) or 0.0),
            }

    # (B) Mis-tagged lines posted to supplier accounts (supplier_id NULL)
    if allowed_account_ids:
        untagged_rows = (
            db.session.query(
                JournalEntryLine.account_id.label('account_id'),
                (
                    func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0)
                ).label('cash'),
                (
                    func.coalesce(func.sum(JournalEntryLine.debit_18k), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.credit_18k), 0.0)
                ).label('b18'),
                (
                    func.coalesce(func.sum(JournalEntryLine.debit_21k), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.credit_21k), 0.0)
                ).label('b21'),
                (
                    func.coalesce(func.sum(JournalEntryLine.debit_22k), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.credit_22k), 0.0)
                ).label('b22'),
                (
                    func.coalesce(func.sum(JournalEntryLine.debit_24k), 0.0)
                    - func.coalesce(func.sum(JournalEntryLine.credit_24k), 0.0)
                ).label('b24'),
            )
            .join(JournalEntry)
            .filter(JournalEntryLine.supplier_id.is_(None))
            .filter(JournalEntryLine.customer_id.is_(None))
            .filter(JournalEntryLine.account_id.in_(allowed_account_ids))
            .filter(JournalEntry.is_deleted == False)
            .filter(*jl_filters)
            .group_by(JournalEntryLine.account_id)
            .all()
        )

        for r in untagged_rows:
            try:
                acc_id = int(r.account_id)
            except Exception:
                continue
            sid = allowed_account_to_supplier.get(acc_id)
            if not sid:
                continue
            cur = balances_by_supplier.get(sid)
            if not cur:
                cur = {'cash': 0.0, '18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0}
                balances_by_supplier[sid] = cur

            cur['cash'] += float(getattr(r, 'cash', 0.0) or 0.0)
            cur['18k'] += float(getattr(r, 'b18', 0.0) or 0.0)
            cur['21k'] += float(getattr(r, 'b21', 0.0) or 0.0)
            cur['22k'] += float(getattr(r, 'b22', 0.0) or 0.0)
            cur['24k'] += float(getattr(r, 'b24', 0.0) or 0.0)

    return balances_by_supplier
