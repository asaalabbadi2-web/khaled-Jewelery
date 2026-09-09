"""مصدر وحيد لمنطق تسوية مشتريات الذهب.

يُستدعى من موضعين:
  - routes/reports.py   → نقطة نهاية HTTP  (GET /api/reports/gold_acquisition_reconciliation)
  - gold_acquisition_reconciliation_scheduler.py → وظيفة شهرية
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_

from models import Account, Invoice, InvoiceKaratLine, JournalEntry, JournalEntryLine, db
from utils import get_main_karat


def compute(start_dt: datetime, end_dt: datetime) -> dict:
    """تشغيل الاستعلامين والمقارنة.

    Returns:
        dict بالمفاتيح:
          avg_buy_path, je_path, discrepancy, is_clean, supplier_purchases
    """
    _posted = func.coalesce(Invoice.is_posted, False) == True
    _in_period = (Invoice.date >= start_dt, Invoice.date < end_dt)
    _cols = (Invoice.id, Invoice.total)

    customer_invoices = (
        Invoice.query
        .filter(Invoice.invoice_type == 'شراء من عميل', *_in_period, _posted)
        .with_entities(*_cols).all()
    )
    customer_returns = (
        Invoice.query
        .filter(Invoice.invoice_type == 'مرتجع شراء', *_in_period, _posted)
        .with_entities(*_cols).all()
    )
    settlement_invoices = (
        Invoice.query
        .filter(
            Invoice.invoice_type.in_(['شراء', 'buy']),
            func.coalesce(Invoice.gold_type, '') == 'scrap',
            *_in_period, _posted,
        )
        .with_entities(*_cols).all()
    )
    supplier_invoices = (
        Invoice.query
        .filter(
            Invoice.invoice_type.in_(['شراء', 'buy']),
            func.coalesce(Invoice.gold_type, '') != 'scrap',
            *_in_period, _posted,
        )
        .with_entities(*_cols).all()
    )
    supplier_returns = (
        Invoice.query
        .filter(Invoice.invoice_type == 'مرتجع شراء (مورد)', *_in_period, _posted)
        .with_entities(*_cols).all()
    )

    def _cash(rows): return sum(float(r.total or 0.0) for r in rows)

    customer_cash = _cash(customer_invoices)
    customer_return_cash = _cash(customer_returns)
    settlement_cash = _cash(settlement_invoices)
    supplier_cash = _cash(supplier_invoices)
    supplier_return_cash = _cash(supplier_returns)

    avg_buy_numerator = customer_cash + settlement_cash - customer_return_cash

    # مقام avg_buy: وزن الاقتناء الصافي بالغرام MK
    main_karat = get_main_karat()
    def _weight_mk(inv_ids: list) -> float:
        if not inv_ids:
            return 0.0
        rows = (
            db.session.query(
                func.coalesce(func.sum(
                    InvoiceKaratLine.weight_grams * InvoiceKaratLine.karat / main_karat
                ), 0.0)
            )
            .filter(InvoiceKaratLine.invoice_id.in_(inv_ids))
            .scalar()
        )
        return float(rows or 0.0)

    purchase_weight_mk = _weight_mk([r.id for r in customer_invoices] + [r.id for r in settlement_invoices])
    return_weight_mk   = _weight_mk([r.id for r in customer_returns])
    avg_buy_denominator = round(purchase_weight_mk - return_weight_mk, 6)

    # ── Q2 الجزء A — قيود مرتبطة بفواتير Q1 ──────────────────────────────────
    purchase_ids = [r.id for r in customer_invoices] + [r.id for r in settlement_invoices]
    return_ids = [r.id for r in customer_returns]
    all_relevant_ids = purchase_ids + return_ids

    if all_relevant_ids:
        agg_a = (
            db.session.query(
                func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0).label('credit'),
                func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0).label('debit'),
            )
            .join(JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id)
            .filter(
                JournalEntry.reference_type == 'invoice',
                JournalEntry.reference_id.in_(all_relevant_ids),
                func.coalesce(JournalEntry.is_posted, False) == True,
                JournalEntry.is_deleted == False,
            )
            .one()
        )
        invoice_linked_cash = float(agg_a.credit or 0.0) - float(agg_a.debit or 0.0)

        accounted_je_ids = [
            r.id for r in (
                db.session.query(JournalEntry.id)
                .filter(
                    JournalEntry.reference_type == 'invoice',
                    JournalEntry.reference_id.in_(all_relevant_ids),
                    func.coalesce(JournalEntry.is_posted, False) == True,
                    JournalEntry.is_deleted == False,
                )
                .all()
            )
        ]
    else:
        invoice_linked_cash = 0.0
        accounted_je_ids = []

    # ── Q2 الجزء B — قيود غير مرتبطة تُدين حسابات ذهب ────────────────────────
    gold_acct_ids = [a.id for a in Account.query.filter_by(tracks_weight=True).all()]

    if gold_acct_ids:
        unlinked_je_id_rows = (
            db.session.query(JournalEntryLine.journal_entry_id)
            .join(JournalEntry, JournalEntryLine.journal_entry_id == JournalEntry.id)
            .filter(
                JournalEntryLine.account_id.in_(gold_acct_ids),
                or_(
                    JournalEntryLine.debit_18k > 0,
                    JournalEntryLine.debit_21k > 0,
                    JournalEntryLine.debit_22k > 0,
                    JournalEntryLine.debit_24k > 0,
                    JournalEntryLine.debit_weight > 0,
                ),
                JournalEntry.date >= start_dt,
                JournalEntry.date < end_dt,
                func.coalesce(JournalEntry.is_posted, False) == True,
                JournalEntry.is_deleted == False,
            )
            .distinct()
            .all()
        )
        accounted_set = set(accounted_je_ids)
        unlinked_je_ids = [
            r.journal_entry_id for r in unlinked_je_id_rows
            if r.journal_entry_id not in accounted_set
        ]
    else:
        unlinked_je_ids = []

    if unlinked_je_ids:
        agg_b = (
            db.session.query(
                func.coalesce(func.sum(JournalEntryLine.cash_credit), 0.0).label('credit'),
                func.coalesce(func.sum(JournalEntryLine.cash_debit), 0.0).label('debit'),
            )
            .filter(JournalEntryLine.journal_entry_id.in_(unlinked_je_ids))
            .one()
        )
        unlinked_gold_cash = float(agg_b.credit or 0.0) - float(agg_b.debit or 0.0)
    else:
        unlinked_gold_cash = 0.0

    je_net_cash = invoice_linked_cash + unlinked_gold_cash
    discrepancy = round(je_net_cash - avg_buy_numerator, 4)
    is_clean = abs(discrepancy) < 0.01

    return {
        'avg_buy_path': {
            'customer_purchases_cash': round(customer_cash, 4),
            'customer_purchases_count': len(customer_invoices),
            'customer_buy_returns_cash': round(customer_return_cash, 4),
            'customer_buy_returns_count': len(customer_returns),
            'settlement_purchases_cash': round(settlement_cash, 4),
            'settlement_purchases_count': len(settlement_invoices),
            'avg_buy_numerator': round(avg_buy_numerator, 4),
            'avg_buy_denominator': avg_buy_denominator,
        },
        'je_path': {
            'je_net_cash': round(je_net_cash, 4),
            'invoice_linked_cash': round(invoice_linked_cash, 4),
            'unlinked_gold_cash': round(unlinked_gold_cash, 4),
            'invoices_matched': len(all_relevant_ids),
        },
        'discrepancy': discrepancy,
        'is_clean': is_clean,
        'supplier_purchases': {
            'cash': round(supplier_cash - supplier_return_cash, 4),
            'count': len(supplier_invoices),
            'return_count': len(supplier_returns),
            'note': 'مستبعدة من avg_buy — تحقق أنها ليست خردة مُعاد تصنيفها' if supplier_cash > 0 else None,
        },
    }
