import sys
sys.path.insert(0, "/app/backend")

from app import app
from models import db, JournalEntry, JournalEntryLine, Account

JE_ID = 3056

with app.app_context():
    je = JournalEntry.query.get(JE_ID)
    if not je:
        print(f"JournalEntry#{JE_ID} not found")
        sys.exit(0)

    print("JournalEntry full row:")
    for col in je.__table__.columns:
        print(f"  {col.name}: {getattr(je, col.name)}")

    print()
    print("All lines on this JournalEntry:")
    for l in JournalEntryLine.query.filter_by(journal_entry_id=JE_ID).all():
        acc = Account.query.get(l.account_id)
        print(f"  line#{l.id} account_id={l.account_id} ({acc.name if acc else '?'}) "
              f"debit={l.cash_debit} credit={l.cash_credit} desc={l.description!r} "
              f"is_deleted={l.is_deleted}")
