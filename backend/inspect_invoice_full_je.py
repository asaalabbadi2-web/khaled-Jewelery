"""
inspect_invoice_full_je.py
=============================
يطبع كل أسطر القيد المحاسبي (كل الحسابات، ليس فقط 760) لفاتورة بيع معيّنة،
للتأكد من أن السطر الآخر (المقابل لحساب 760) هو حساب "عميل وزني" الخاص
بالعميل، وأن وزنه مطابق للفرق المُضخَّم.

قراءة فقط.

تشغيل:
    docker exec yasargold-backend python backend/inspect_invoice_full_je.py --invoice-id 118
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from app import app
from models import db, JournalEntry, JournalEntryLine, Invoice, InvoiceItem, Account, Customer


def run(invoice_id: int):
    with app.app_context():
        inv = Invoice.query.get(invoice_id)
        print(f"invoice_id={invoice_id} number={inv.invoice_number if inv else None} "
              f"type={getattr(inv, 'invoice_type', None)} gold_type={getattr(inv, 'gold_type', None)} "
              f"customer_id={getattr(inv, 'customer_id', None)}")

        if getattr(inv, 'customer_id', None):
            cust = Customer.query.get(inv.customer_id)
            print(f"customer: id={cust.id} name={cust.name!r} "
                  f"weight_account_id={getattr(cust, 'weight_account_id', None)} "
                  f"account_id={getattr(cust, 'account_id', None)}")

        entries = JournalEntry.query.filter_by(reference_type='invoice', reference_id=invoice_id).all()
        for je in entries:
            print(f"\nJournalEntry id={je.id} entry_number={je.entry_number} desc={je.description!r} "
                  f"is_posted={je.is_posted} is_deleted={je.is_deleted}")
            for l in JournalEntryLine.query.filter_by(journal_entry_id=je.id, is_deleted=False).all():
                acc = Account.query.get(l.account_id)
                print(f"   line id={l.id} account=[{l.account_id}] {acc.account_number if acc else '?'} "
                      f"{acc.name if acc else '?'} desc={l.description!r}")
                for k in (18, 21, 22, 24):
                    d = getattr(l, f'debit_{k}k') or 0
                    c = getattr(l, f'credit_{k}k') or 0
                    if d or c:
                        print(f"        karat={k}: debit={d} credit={c}")
                if l.cash_debit or l.cash_credit:
                    print(f"        cash: debit={l.cash_debit} credit={l.cash_credit}")

        items = InvoiceItem.query.filter_by(invoice_id=invoice_id).all()
        print("\nitems:")
        for it in items:
            print(f"   name={it.name!r} qty={it.quantity} karat={it.karat} weight={it.weight}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--invoice-id', type=int, required=True)
    args = parser.parse_args()
    run(invoice_id=args.invoice_id)
