# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from sqlalchemy import and_, func, or_

from models import Account, JournalEntry, JournalEntryLine, Office, Supplier, db

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

    # Map supplier -> office posting account id (only for suppliers that are linked to an Office).
    office_account_by_supplier_id: Dict[int, int] = {}
    try:
        office_rows = (
            db.session.query(Office.supplier_id, Office.account_category_id)
            .filter(Office.supplier_id.isnot(None))
            .all()
        )
        for supplier_id, office_account_id in office_rows:
            if supplier_id is None or office_account_id is None:
                continue
            try:
                office_account_by_supplier_id[int(supplier_id)] = int(office_account_id)
            except Exception:
                continue
    except Exception:
        office_account_by_supplier_id = {}

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

        # Office-linked suppliers can post directly to a dedicated office posting account.
        # That account lives on Office.account_category_id (NOT Supplier.account_category_id).
        # Include it so mis-tagged lines (supplier_id NULL) still reconcile.
        try:
            raw_office_acc_id = office_account_by_supplier_id.get(sid)
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

    # Legacy DB robustness:
    # Some datasets have NULLs in is_draft/is_posted even if the model declares them non-nullable.
    # Use COALESCE to avoid accidentally excluding valid historical entries.
    jl_filters = [
        func.coalesce(JournalEntry.is_deleted, False) == False,
        func.coalesce(JournalEntryLine.is_deleted, False) == False,
    ]
    if _db_has_column('journal_entry', 'is_draft'):
        jl_filters.append(func.coalesce(JournalEntry.is_draft, False) == False)
    elif _db_has_column('journal_entry', 'is_posted'):
        jl_filters.append(func.coalesce(JournalEntry.is_posted, True) == True)

    # Always return an entry for each supplier in input.
    balances_by_supplier: Dict[int, Dict[str, float]] = {
        int(sid): {'cash': 0.0, '18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0}
        for sid in supplier_ids
    }

    payable_filter = and_(Account.type == 'Liability', Account.account_number.like('21%'))
    account_filter = payable_filter
    if allowed_account_ids:
        account_filter = or_(Account.id.in_(allowed_account_ids), payable_filter)

    # (A) Tagged lines grouped by supplier_id (STRICT)
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
            .filter(*jl_filters)
            .filter(account_filter)
            .group_by(JournalEntryLine.supplier_id)
            .all()
        )
        strict_counts = (
            db.session.query(
                JournalEntryLine.supplier_id.label('supplier_id'),
                func.count(JournalEntryLine.id).label('cnt'),
            )
            .join(JournalEntry)
            .join(Account, JournalEntryLine.account_id == Account.id)
            .filter(JournalEntryLine.supplier_id.in_(supplier_ids))
            .filter(*jl_filters)
            .filter(account_filter)
            .group_by(JournalEntryLine.supplier_id)
            .all()
        )
        strict_count_by_supplier: Dict[int, int] = {}
        for r in strict_counts:
            try:
                strict_count_by_supplier[int(r.supplier_id)] = int(getattr(r, 'cnt', 0) or 0)
            except Exception:
                continue

        # (A2) Tagged lines grouped by supplier_id (RELAXED)
        relaxed_rows = (
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
            .filter(*jl_filters)
            .group_by(JournalEntryLine.supplier_id)
            .all()
        )
        relaxed_counts = (
            db.session.query(
                JournalEntryLine.supplier_id.label('supplier_id'),
                func.count(JournalEntryLine.id).label('cnt'),
            )
            .join(JournalEntry)
            .filter(JournalEntryLine.supplier_id.in_(supplier_ids))
            .filter(*jl_filters)
            .group_by(JournalEntryLine.supplier_id)
            .all()
        )
        relaxed_count_by_supplier: Dict[int, int] = {}
        for r in relaxed_counts:
            try:
                relaxed_count_by_supplier[int(r.supplier_id)] = int(getattr(r, 'cnt', 0) or 0)
            except Exception:
                continue

        strict_by_supplier: Dict[int, Dict[str, float]] = {}
        for r in tagged_rows:
            try:
                sid = int(r.supplier_id)
            except Exception:
                continue
            strict_by_supplier[sid] = {
                'cash': float(getattr(r, 'cash', 0.0) or 0.0),
                '18k': float(getattr(r, 'b18', 0.0) or 0.0),
                '21k': float(getattr(r, 'b21', 0.0) or 0.0),
                '22k': float(getattr(r, 'b22', 0.0) or 0.0),
                '24k': float(getattr(r, 'b24', 0.0) or 0.0),
            }

        relaxed_by_supplier: Dict[int, Dict[str, float]] = {}
        for r in relaxed_rows:
            try:
                sid = int(r.supplier_id)
            except Exception:
                continue
            relaxed_by_supplier[sid] = {
                'cash': float(getattr(r, 'cash', 0.0) or 0.0),
                '18k': float(getattr(r, 'b18', 0.0) or 0.0),
                '21k': float(getattr(r, 'b21', 0.0) or 0.0),
                '22k': float(getattr(r, 'b22', 0.0) or 0.0),
                '24k': float(getattr(r, 'b24', 0.0) or 0.0),
            }

        # Decide strict vs relaxed per supplier (mirrors statement fallback behavior).
        for sid in supplier_ids:
            strict = strict_by_supplier.get(sid, {'cash': 0.0, '18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0})
            relaxed = relaxed_by_supplier.get(sid, {'cash': 0.0, '18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0})

            strict_cnt = int(strict_count_by_supplier.get(sid, 0) or 0)
            relaxed_cnt = int(relaxed_count_by_supplier.get(sid, 0) or 0)

            differs = any(abs(float(strict[k]) - float(relaxed[k])) > 1e-9 for k in ('cash', '18k', '21k', '22k', '24k'))
            if relaxed_cnt > strict_cnt and differs:
                balances_by_supplier[sid] = dict(relaxed)
            else:
                balances_by_supplier[sid] = dict(strict)

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
