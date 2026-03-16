"""Historical backfill: derive SafeBoxTransaction rows from manual-like posted JournalEntry.

Problem this fixes:
- SafeBox balances are computed from `safe_box_transaction`.
- Some older manual journal entries (GL) affected SafeBox-linked accounts but did not create
  corresponding SafeBoxTransaction rows, so the SafeBox subledger diverged from GL.

This script rebuilds the derived rows for those historical journal entries.

Safety:
- Default is DRY-RUN (no changes). Use `--apply` to commit.
- By default it only touches entries that are missing derived rows.
- Derived rows are identified by: ref_type='journal_entry' and ref_id=<journal_entry.id>

Usage:
    cd backend
    source venv/bin/activate

    # Dry-run (default): reports what would change
    python backfill_safebox_from_journal_entries.py

    # Apply changes
    python backfill_safebox_from_journal_entries.py --apply

    # Narrow scope
    python backfill_safebox_from_journal_entries.py --entry-id 123 --apply
    python backfill_safebox_from_journal_entries.py --since 2026-01-01 --until 2026-03-16 --limit 200 --apply

Notes:
- Only manual-like journal entries are considered (reference_type in: '', 'manual', 'journal_entry').
- Only posted and non-draft entries are considered, and soft-deleted entries are skipped.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from app import app
from models import db, JournalEntry, SafeBoxTransaction
from routes import _is_manual_like_journal_entry, _rebuild_safe_box_transactions_for_journal_entry

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import selectinload


def _parse_ymd(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    # Accept YYYY-MM-DD
    return datetime.strptime(raw, "%Y-%m-%d")


def _entry_is_candidate(entry: JournalEntry) -> bool:
    if not entry:
        return False
    if bool(getattr(entry, 'is_deleted', False)):
        return False
    if bool(getattr(entry, 'is_draft', False)):
        return False
    if hasattr(entry, 'is_posted') and (bool(getattr(entry, 'is_posted', False)) is not True):
        return False
    if not _is_manual_like_journal_entry(entry):
        return False
    return True


def _count_derived(entry_id: int) -> int:
    return (
        SafeBoxTransaction.query
        .filter_by(ref_type='journal_entry', ref_id=int(entry_id))
        .count()
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Backfill derived SafeBoxTransaction rows from manual-like posted journal entries.'
    )
    parser.add_argument('--apply', action='store_true', help='Commit changes (default: dry-run).')
    parser.add_argument('--rebuild-all', action='store_true', help='Process all candidates (default: only missing derived rows).')
    parser.add_argument('--only-missing', action='store_true', default=False, help='Only process entries missing derived rows (default behavior unless --rebuild-all).')
    parser.add_argument('--entry-id', type=int, default=None, help='Process a single journal entry id.')
    parser.add_argument('--since', type=str, default=None, help='Filter entry.date >= YYYY-MM-DD')
    parser.add_argument('--until', type=str, default=None, help='Filter entry.date <= YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=None, help='Max number of entries to process.')
    parser.add_argument('--newest-first', action='store_true', help='Process newest entries first (useful with --limit).')
    parser.add_argument('--created-by', type=str, default='system-backfill', help='Value to store in SafeBoxTransaction.created_by')
    parser.add_argument('--verbose', action='store_true', help='Print per-entry details (default: summary only).')
    args = parser.parse_args()

    dry_run = not bool(args.apply)

    since_dt = _parse_ymd(args.since)
    until_dt = _parse_ymd(args.until)
    if until_dt is not None:
        # include the entire day
        until_dt = until_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Determine missing behavior.
    # Default behavior: only missing (unless --rebuild-all is set).
    only_missing = True
    if args.rebuild_all:
        only_missing = False
    if args.only_missing:
        only_missing = True

    with app.app_context():
        q = (
            JournalEntry.query
            .options(selectinload(JournalEntry.lines))
        )

        if args.entry_id is not None:
            q = q.filter(JournalEntry.id == int(args.entry_id))

        if since_dt is not None:
            q = q.filter(JournalEntry.date >= since_dt)
        if until_dt is not None:
            q = q.filter(JournalEntry.date <= until_dt)

        # Exclude deleted/draft/unposted.
        q = q.filter(JournalEntry.is_deleted.is_(False))
        q = q.filter(JournalEntry.is_draft.is_(False))
        q = q.filter(JournalEntry.is_posted.is_(True))

        # Manual-like reference_type filter (same semantics as _is_manual_like_journal_entry).
        # Keep it DB-side for performance.
        q = q.filter(
            or_(
                JournalEntry.reference_type.is_(None),
                JournalEntry.reference_type == '',
                func.lower(JournalEntry.reference_type).in_(['manual', 'journal_entry']),
            )
        )

        # If only_missing, use a LEFT JOIN to select only entries with no derived rows.
        if only_missing:
            q = (
                q.outerjoin(
                    SafeBoxTransaction,
                    and_(
                        SafeBoxTransaction.ref_type == 'journal_entry',
                        SafeBoxTransaction.ref_id == JournalEntry.id,
                    ),
                )
                .group_by(JournalEntry.id)
                .having(func.count(SafeBoxTransaction.id) == 0)
            )

        # Order entries.
        # Default: oldest -> newest for predictable progress.
        # Use --newest-first to target recent history when combined with --limit.
        q = q.order_by(JournalEntry.id.desc() if args.newest_first else JournalEntry.id.asc())

        if args.limit is not None and args.limit > 0:
            q = q.limit(int(args.limit))

        candidates: list[JournalEntry] = q.all()
        print(f"Candidates loaded from DB: {len(candidates)}", flush=True)

        if not candidates:
            print('Nothing to backfill.', flush=True)
            return 0

        processed = 0
        would_change = 0
        total_before = 0
        total_after = 0

        for entry in candidates:
            entry_id = int(entry.id)

            # Safety check: keep Python-side guard too.
            if not _entry_is_candidate(entry):
                continue

            before = _count_derived(entry_id)
            total_before += before

            # Lines: skip deleted lines.
            lines = [l for l in (entry.lines or []) if not bool(getattr(l, 'is_deleted', False))]

            if dry_run:
                # Use a savepoint so we can measure after-count without persisting.
                nested = db.session.begin_nested()
                try:
                    _rebuild_safe_box_transactions_for_journal_entry(entry, lines, created_by=str(args.created_by))
                    db.session.flush()
                    after = _count_derived(entry_id)
                    if after != before:
                        would_change += 1
                    total_after += after
                    if args.verbose:
                        print(f"[DRY] entry_id={entry_id}  derived_before={before} -> derived_after={after}", flush=True)
                finally:
                    # Roll back only the nested transaction.
                    try:
                        nested.rollback()
                    except Exception:
                        db.session.rollback()
                    try:
                        db.session.expire_all()
                    except Exception:
                        pass
            else:
                try:
                    _rebuild_safe_box_transactions_for_journal_entry(entry, lines, created_by=str(args.created_by))
                    db.session.commit()
                    after = _count_derived(entry_id)
                    total_after += after
                    if after != before:
                        would_change += 1
                    if args.verbose:
                        print(f"[OK] entry_id={entry_id}  derived_before={before} -> derived_after={after}")
                except Exception as exc:
                    db.session.rollback()
                    print(f"[ERROR] entry_id={entry_id}: {exc}", flush=True)
                    raise

            processed += 1

        mode = 'DRY RUN' if dry_run else 'APPLIED'
        print('\n' + '=' * 60, flush=True)
        print(f"[{mode}] Processed candidates: {processed}", flush=True)
        print(f"[{mode}] Entries changed (derived count differs): {would_change}", flush=True)
        print(f"[{mode}] Derived total before (sum, checked entries): {total_before}", flush=True)
        if dry_run:
            print(f"[{mode}] Derived total after (simulated): {total_after}", flush=True)
            print("Run again with --apply to commit changes.", flush=True)
        else:
            print(f"[{mode}] Derived total after (committed): {total_after}", flush=True)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
