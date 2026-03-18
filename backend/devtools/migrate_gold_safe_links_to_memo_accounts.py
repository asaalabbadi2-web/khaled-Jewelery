"""Migration: relink misconfigured gold SafeBoxes to memo (weight) accounts.

Why
- Gold SafeBoxes (safe_type='gold') must be linked to weight (memo) accounts.
- Legacy datasets may have gold safes linked to a financial/bridge account (e.g. 1074)
  which has a memo account (e.g. 71074). This can cause:
  - cash movements appearing under a gold safe
  - SafeBox subledger mismatches vs GL

What this script does
- Finds gold SafeBoxes whose linked Account is NOT a memo-weight account.
- Resolves the appropriate memo account and updates safe_box.account_id.
- Special handling for Offices: if a gold safe is linked to office.account_category_id,
  it will migrate it to the office memo account.

Safety
- Default is DRY-RUN (no changes). Use --apply to commit.
- Idempotent: safe already linked to memo is skipped.
- Reports conflicts (when a memo-linked gold safe already exists).

Usage
    cd backend
    source venv/bin/activate

    # Dry-run (recommended first)
    python devtools/migrate_gold_safe_links_to_memo_accounts.py --since 2026-01-01

    # Apply
    python devtools/migrate_gold_safe_links_to_memo_accounts.py --apply

    # Only offices
    python devtools/migrate_gold_safe_links_to_memo_accounts.py --office-only --apply

Environment
- DATABASE_URL (optional). If missing, defaults to backend/app.db.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime

from flask import Flask

# Ensure backend/ is importable when running from devtools/ or docker.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import and_, or_

from models import db, Account, Office, SafeBox, Supplier


def _parse_ymd(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    return datetime.strptime(raw, "%Y-%m-%d")


def _normalize_database_url(raw: str) -> str:
    value = (raw or '').strip()
    if not value:
        return value
    # SQLAlchemy expects postgresql:// (some deployments still provide postgres://)
    if value.startswith('postgres://'):
        value = 'postgresql://' + value[len('postgres://'):]
    if value.startswith('sqlite:///') and not value.startswith('sqlite:////'):
        sqlite_path = value[len('sqlite:///'):]
        if sqlite_path and not sqlite_path.startswith('/') and '/' not in sqlite_path and '\\' not in sqlite_path:
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            abs_path = os.path.abspath(os.path.join(backend_dir, sqlite_path))
            return f"sqlite:///{abs_path}"
    return value


def _create_app() -> Flask:
    app = Flask(__name__)
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_sqlite = f"sqlite:///{os.path.join(backend_dir, 'app.db')}"
    app.config['SQLALCHEMY_DATABASE_URI'] = _normalize_database_url(os.getenv('DATABASE_URL', default_sqlite))
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _digits_only(value: str) -> str:
    return ''.join(ch for ch in str(value or '').strip() if ch.isdigit())


def _is_memo_weight_account(acc: Account | None) -> bool:
    if not acc:
        return False
    try:
        if not bool(getattr(acc, 'tracks_weight', False)):
            return False
        if (getattr(acc, 'transaction_type', None) or '').strip().lower() != 'gold':
            return False
        if not str(getattr(acc, 'account_number', '') or '').startswith('7'):
            return False
        return True
    except Exception:
        return False


def _ensure_memo_account_for_any(financial_or_bridge: Account) -> Account:
    """Ensure memo account exists even for transaction_type='both' accounts."""

    if not financial_or_bridge:
        raise ValueError('account is required')

    existing = Account.query.get(int(financial_or_bridge.memo_account_id)) if financial_or_bridge.memo_account_id else None
    if _is_memo_weight_account(existing):
        return existing

    fin_no = _digits_only(getattr(financial_or_bridge, 'account_number', '') or '')
    if not fin_no:
        raise ValueError('account_number missing digits')
    memo_no = f"7{fin_no}"

    memo = Account.query.filter_by(account_number=memo_no).first()

    desired_parent_id = None
    try:
        if getattr(financial_or_bridge, 'parent_id', None):
            parent = Account.query.get(int(financial_or_bridge.parent_id))
            if parent and getattr(parent, 'memo_account_id', None):
                desired_parent_id = int(parent.memo_account_id)
    except Exception:
        desired_parent_id = None

    if memo:
        memo.transaction_type = 'gold'
        memo.tracks_weight = True
        if desired_parent_id and memo.parent_id != desired_parent_id:
            memo.parent_id = desired_parent_id
    else:
        memo = Account(
            account_number=memo_no,
            name=f"{financial_or_bridge.name} وزني",
            type=financial_or_bridge.type,
            transaction_type='gold',
            tracks_weight=True,
            parent_id=desired_parent_id,
        )
        db.session.add(memo)
        db.session.flush()

    financial_or_bridge.memo_account_id = memo.id
    memo.memo_account_id = financial_or_bridge.id
    db.session.add(financial_or_bridge)
    db.session.add(memo)
    db.session.flush()

    return memo


@dataclass
class Change:
    safe_box_id: int
    safe_name: str
    old_account_id: int
    old_account_no: str
    new_account_id: int
    new_account_no: str
    conflict_with_safe_id: int | None = None
    office_id: int | None = None
    supplier_ids_updated: int = 0


def _find_office_by_account_id(account_id: int) -> Office | None:
    try:
        return Office.query.filter_by(account_category_id=int(account_id)).first()
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description='Relink gold SafeBoxes to memo (weight) accounts.')
    parser.add_argument('--apply', action='store_true', help='Apply changes (default is dry-run).')
    parser.add_argument('--limit', type=int, default=0, help='Limit number of SafeBoxes processed (0 = no limit).')
    parser.add_argument('--safe-box-id', type=int, default=0, help='Only migrate a specific safe_box.id.')
    parser.add_argument('--office-only', action='store_true', help='Only migrate gold safes linked to office.account_category_id.')
    parser.add_argument('--include-inactive', action='store_true', help='Include inactive SafeBoxes.')
    parser.add_argument('--on-conflict', choices=['skip', 'deactivate-legacy'], default='skip', help='What to do when memo-linked gold safe already exists.')
    parser.add_argument('--since', type=str, default=None, help='Optional filter by SafeBox.created_at >= YYYY-MM-DD (best effort).')
    args = parser.parse_args()

    since = _parse_ymd(args.since)

    app = _create_app()
    with app.app_context():
        q = SafeBox.query.filter(SafeBox.safe_type == 'gold')
        if not args.include_inactive:
            q = q.filter(SafeBox.is_active.is_(True))
        if args.safe_box_id:
            q = q.filter(SafeBox.id == int(args.safe_box_id))
        if since is not None and hasattr(SafeBox, 'created_at'):
            q = q.filter(SafeBox.created_at >= since)

        # Fetch a stable order to make limit deterministic.
        q = q.order_by(SafeBox.id.asc())

        safes: list[SafeBox] = q.all()

        changes: list[Change] = []
        skipped_already_ok = 0
        skipped_no_memo = 0
        skipped_conflict = 0
        processed = 0

        for sb in safes:
            if args.limit and processed >= int(args.limit):
                break

            if not getattr(sb, 'account_id', None):
                continue

            account = Account.query.get(int(sb.account_id))
            if _is_memo_weight_account(account):
                skipped_already_ok += 1
                continue

            # Office-only scope: only if this gold safe is currently linked to the office bridge account.
            office = _find_office_by_account_id(int(sb.account_id))
            if args.office_only and office is None:
                continue

            # Ensure memo target.
            try:
                memo = _ensure_memo_account_for_any(account)
            except Exception:
                memo = None

            if not memo:
                skipped_no_memo += 1
                continue

            if _is_memo_weight_account(account) and int(account.id) == int(memo.id):
                skipped_already_ok += 1
                continue

            # Detect conflicts: an existing gold safe already linked to memo account.
            existing_memo_safe = SafeBox.query.filter(
                and_(SafeBox.safe_type == 'gold', SafeBox.account_id == int(memo.id))
            ).order_by(SafeBox.is_active.desc(), SafeBox.id.asc()).first()

            conflict_safe_id = None
            if existing_memo_safe and int(existing_memo_safe.id) != int(sb.id):
                conflict_safe_id = int(existing_memo_safe.id)

            old_no = str(getattr(account, 'account_number', '') or '')
            new_no = str(getattr(memo, 'account_number', '') or '')

            change = Change(
                safe_box_id=int(sb.id),
                safe_name=str(getattr(sb, 'name', '') or ''),
                old_account_id=int(account.id),
                old_account_no=old_no,
                new_account_id=int(memo.id),
                new_account_no=new_no,
                conflict_with_safe_id=conflict_safe_id,
                office_id=int(getattr(office, 'id', 0) or 0) if office else None,
            )

            if conflict_safe_id and args.on_conflict == 'skip':
                skipped_conflict += 1
                changes.append(change)
                processed += 1
                continue

            # Apply actions.
            if args.apply:
                if conflict_safe_id and args.on_conflict == 'deactivate-legacy':
                    # Keep the memo-linked safe as the canonical one.
                    # 1) Update suppliers default_safe_box_id if pointing to legacy safe.
                    updated = 0
                    try:
                        suppliers = Supplier.query.filter_by(default_safe_box_id=int(sb.id)).all()
                        for sup in suppliers:
                            sup.default_safe_box_id = int(existing_memo_safe.id)
                            db.session.add(sup)
                            updated += 1
                    except Exception:
                        updated = 0
                    change.supplier_ids_updated = updated

                    # 2) Deactivate legacy safe (do not delete).
                    sb.is_active = False
                    try:
                        note = str(getattr(sb, 'notes', '') or '')
                        suffix = f" [migrated: replaced by safe_box_id={conflict_safe_id}]"
                        if suffix not in note:
                            sb.notes = (note + suffix).strip()
                    except Exception:
                        pass
                    db.session.add(sb)
                else:
                    # Normal migration: update account_id in place (keeps safe_box_id stable).
                    sb.account_id = int(memo.id)
                    try:
                        note = str(getattr(sb, 'notes', '') or '')
                        suffix = f" [migrated: account_id {account.id}->{memo.id}]"
                        if suffix not in note:
                            sb.notes = (note + suffix).strip()
                    except Exception:
                        pass
                    db.session.add(sb)

                db.session.flush()

            changes.append(change)
            processed += 1

        # Reporting
        mode = 'APPLY' if args.apply else 'DRY-RUN'
        print(f"== migrate_gold_safe_links_to_memo_accounts ({mode}) ==")
        print(f"gold safes scanned: {len(safes)}")
        print(f"candidates processed: {processed}")
        print(f"skipped already ok: {skipped_already_ok}")
        print(f"skipped no memo: {skipped_no_memo}")
        print(f"conflicts encountered: {skipped_conflict}")

        # Print a compact change list.
        shown = 0
        for ch in changes:
            if args.limit and shown >= int(args.limit):
                break
            conflict = f" conflict_safe={ch.conflict_with_safe_id}" if ch.conflict_with_safe_id else ""
            office_tag = f" office_id={ch.office_id}" if ch.office_id else ""
            suppliers_tag = f" suppliers_updated={ch.supplier_ids_updated}" if ch.supplier_ids_updated else ""
            print(
                f"- safe_box_id={ch.safe_box_id} '{ch.safe_name}' "
                f"{ch.old_account_no}({ch.old_account_id}) -> {ch.new_account_no}({ch.new_account_id})"
                f"{conflict}{office_tag}{suppliers_tag}"
            )
            shown += 1

        if args.apply:
            db.session.commit()
            print('✓ committed')
        else:
            db.session.rollback()
            print('✓ rolled back (dry-run)')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
