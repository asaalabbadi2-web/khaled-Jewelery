"""
Migration: Add posting settings columns to the settings table.

Columns added:
  - auto_post_invoices      BOOLEAN DEFAULT 1
  - auto_post_entries        BOOLEAN DEFAULT 1
  - require_approval_before_post BOOLEAN DEFAULT 0
  - allow_unposting          BOOLEAN DEFAULT 0
"""
import sqlite3, os, sys

DB_PATH = os.path.join(os.path.dirname(__file__), 'app.db')

COLUMNS = [
    ('auto_post_invoices',          'BOOLEAN DEFAULT 1'),
    ('auto_post_entries',           'BOOLEAN DEFAULT 1'),
    ('require_approval_before_post','BOOLEAN DEFAULT 0'),
    ('allow_unposting',            'BOOLEAN DEFAULT 0'),
]

def migrate():
    if not os.path.exists(DB_PATH):
        print(f'Database not found at {DB_PATH}')
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(settings)")
    existing = {row[1] for row in cursor.fetchall()}

    added = 0
    for col_name, col_def in COLUMNS:
        if col_name in existing:
            print(f'  ✓ Column "{col_name}" already exists — skipping')
        else:
            stmt = f'ALTER TABLE settings ADD COLUMN {col_name} {col_def}'
            cursor.execute(stmt)
            print(f'  + Added column "{col_name}"')
            added += 1

    conn.commit()
    conn.close()
    print(f'\nDone. {added} column(s) added.')

if __name__ == '__main__':
    migrate()
