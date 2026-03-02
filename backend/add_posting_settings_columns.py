"""
Migration: Add posting settings columns to the settings table.

Columns added:
  - auto_post_invoices      BOOLEAN DEFAULT TRUE
  - auto_post_entries        BOOLEAN DEFAULT TRUE
  - require_approval_before_post BOOLEAN DEFAULT FALSE
  - allow_unposting          BOOLEAN DEFAULT FALSE

Works with both SQLite and PostgreSQL.
"""
import os, sys

def migrate():
    # Import Flask app to get DB connection
    from app import app, db
    from sqlalchemy import text, inspect
    
    with app.app_context():
        inspector = inspect(db.engine)
        existing = {col['name'] for col in inspector.get_columns('settings')}
        
        # Define columns with database-agnostic defaults
        columns = [
            ('auto_post_invoices',          'BOOLEAN DEFAULT TRUE'),
            ('auto_post_entries',           'BOOLEAN DEFAULT TRUE'),
            ('require_approval_before_post','BOOLEAN DEFAULT FALSE'),
            ('allow_unposting',            'BOOLEAN DEFAULT FALSE'),
        ]
        
        added = 0
        for col_name, col_def in columns:
            if col_name in existing:
                print(f'  ✓ Column "{col_name}" already exists — skipping')
            else:
                stmt = f'ALTER TABLE settings ADD COLUMN {col_name} {col_def}'
                try:
                    db.session.execute(text(stmt))
                    db.session.commit()
                    print(f'  + Added column "{col_name}"')
                    added += 1
                except Exception as e:
                    print(f'  ✗ Failed to add "{col_name}": {e}')
                    db.session.rollback()
        
        print(f'\nDone. {added} column(s) added.')

if __name__ == '__main__':
    migrate()
