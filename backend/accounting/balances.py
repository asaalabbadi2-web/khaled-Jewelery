from __future__ import annotations

from models import db, Account, JournalEntry, JournalEntryLine
from core.database import _db_has_column


def _recalculate_account_balances_for_accounts(account_ids) -> None:
    """Recalculate stored Account balances for the given account IDs.

    Uses posted (non-draft) + non-deleted journal lines only.
    """
    if not account_ids:
        return

    for account_id in set(account_ids):
        account = Account.query.get(account_id)
        if not account:
            continue

        account.balance_cash = 0.0
        account.balance_18k = 0.0
        account.balance_21k = 0.0
        account.balance_22k = 0.0
        account.balance_24k = 0.0

        filters = [
            JournalEntryLine.account_id == account_id,
            JournalEntry.is_deleted == False,
            JournalEntryLine.is_deleted == False,
        ]
        if _db_has_column('journal_entry', 'is_posted'):
            filters.append(JournalEntry.is_posted == True)
        if _db_has_column('journal_entry', 'is_draft'):
            filters.append(JournalEntry.is_draft == False)

        all_lines = (
            JournalEntryLine.query
            .join(JournalEntry)
            .filter(*filters)
            .all()
        )

        for line in all_lines:
            account.balance_cash += (line.cash_debit or 0) - (line.cash_credit or 0)

            if account.tracks_weight:
                account.balance_18k += (line.debit_18k or 0) - (line.credit_18k or 0)
                account.balance_21k += (line.debit_21k or 0) - (line.credit_21k or 0)
                account.balance_22k += (line.debit_22k or 0) - (line.credit_22k or 0)
                account.balance_24k += (line.debit_24k or 0) - (line.credit_24k or 0)
