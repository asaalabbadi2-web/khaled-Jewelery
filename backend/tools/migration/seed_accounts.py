import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app, db  # noqa: E402
from models import Account  # noqa: E402
from renumber_accounts import create_financial_and_memo_accounts  # noqa: E402


def reset_accounts_table() -> None:
    """يمسح جميع الحسابات الحالية لتحميل الشجرة المثالية من جديد."""
    with app.app_context():
        existing = Account.query.count()
        logging.info("Deleting %s existing accounts before reseed...", existing)
        db.session.query(Account).delete()
        db.session.commit()
        logging.info("✓ تمت تهيئة جدول الحسابات.")


def seed_accounts() -> None:
    """ينفّذ شجرة الحسابات المثالية (المالية + المذكرة) من ملف renumber_accounts."""
    reset_accounts_table()
    create_financial_and_memo_accounts()


if __name__ == '__main__':
    logging.info("Starting ideal chart seed...")
    seed_accounts()
    logging.info("✓ تم تحميل الشجرة المثالية بنجاح.")
