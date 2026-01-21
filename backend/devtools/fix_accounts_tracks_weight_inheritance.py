#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Fix accounts' tracks_weight to match their parent.

Rule:
- Any account with parent_id must have tracks_weight == parent.tracks_weight.

This script is safe to run on a dev database. It will only update rows where a
mismatch is detected.

Usage:
  cd backend
  BYPASS_AUTH_FOR_DEVELOPMENT=1 ./venv/bin/python devtools/fix_accounts_tracks_weight_inheritance.py
"""

import os
import sys

os.environ.setdefault('BYPASS_AUTH_FOR_DEVELOPMENT', '1')

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app import app  # noqa: E402
from models import db, Account  # noqa: E402


def main() -> int:
    with app.app_context():
        accounts = Account.query.filter(Account.parent_id.isnot(None)).all()
        updated = 0
        for acc in accounts:
            parent = Account.query.get(acc.parent_id)
            if not parent:
                continue
            desired = bool(parent.tracks_weight)
            if bool(acc.tracks_weight) != desired:
                acc.tracks_weight = desired
                updated += 1

        if updated:
            db.session.commit()
        print(f"Updated tracks_weight for {updated} account(s).")
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
