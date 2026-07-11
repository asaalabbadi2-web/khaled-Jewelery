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
import os
import sys
from datetime import datetime

from flask import Flask

# Ensure backend/ is importable when running from other working directories (e.g. Docker).
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from models import db, JournalEntry, SafeBox, SafeBoxTransaction

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
    # reference_type filtering may be handled at the SQL level; keep manual-like
    # as a safe default unless the caller opts in.
    if not _is_manual_like_journal_entry(entry):
        return False
    return True


def _is_manual_like_journal_entry(entry: JournalEntry) -> bool:
    """Return True when a JournalEntry is manually created/edited.

    Keep identical semantics to the server-side helper.
    """
    try:
        rt = (getattr(entry, 'reference_type', None) or '').strip().lower()
    except Exception:
        rt = ''
    return rt in ('', 'manual', 'journal_entry')


def _rebuild_safe_box_transactions_for_journal_entry(
    entry: JournalEntry,
    lines,
    *,
    created_by: str | None = None,
) -> None:
    """Rebuild derived SafeBoxTransaction rows for a manual JournalEntry.

    - Idempotent: deletes existing ref_type='journal_entry' rows for this entry.
    - Only creates movements for SafeBox-linked accounts.
    - Mirrors journal semantics: debit => in, credit => out.
    - Creates up to 2 tx per safe box per entry (per asset): one for 'in' and one for 'out' when mixed.
    """
    if not entry or not getattr(entry, 'id', None):
        return

    # Always remove previously-derived rows.
    try:
        existing = (
            SafeBoxTransaction.query
            .filter_by(ref_type='journal_entry', ref_id=int(entry.id))
            .all()
        )
        for tx in existing:
            db.session.delete(tx)
        db.session.flush()
    except Exception:
        pass

    # Only rebuild for posted, non-draft entries.
    try:
        if bool(getattr(entry, 'is_draft', False)):
            return
    except Exception:
        pass

    try:
        if hasattr(entry, 'is_posted') and (bool(getattr(entry, 'is_posted', False)) is not True):
            return
    except Exception:
        # If schema doesn't have is_posted, proceed.
        pass

    if not _is_manual_like_journal_entry(entry):
        return

    j_lines = [l for l in (lines or []) if getattr(l, 'account_id', None) is not None]
    if not j_lines:
        return

    account_ids = list({int(l.account_id) for l in j_lines if l.account_id is not None})
    if not account_ids:
        return

    safe_by_account_id: dict[int, SafeBox] = {}
    for sb in SafeBox.query.filter(SafeBox.account_id.in_(account_ids)).all():
        if getattr(sb, 'account_id', None) is not None:
            safe_by_account_id[int(sb.account_id)] = sb

    if not safe_by_account_id:
        return

    notes = None
    try:
        notes = f"Journal entry {getattr(entry, 'entry_number', None) or entry.id}"
    except Exception:
        notes = None

    eps_cash = 0.005
    eps_w = 0.0005

    def _add_tx(*, sb_id: int, direction: str, amount_cash: float = 0.0, w18: float = 0.0, w21: float = 0.0, w22: float = 0.0, w24: float = 0.0):
        tx = SafeBoxTransaction(
            safe_box_id=int(sb_id),
            ref_type='journal_entry',
            ref_id=int(entry.id),
            direction=direction,
            amount_cash=float(amount_cash or 0.0),
            weight_18k=float(w18 or 0.0),
            weight_21k=float(w21 or 0.0),
            weight_22k=float(w22 or 0.0),
            weight_24k=float(w24 or 0.0),
            notes=notes,
            created_by=created_by,
        )
        db.session.add(tx)

    for line in j_lines:
        sb = safe_by_account_id.get(int(line.account_id))
        if not sb:
            continue

        # Cash
        try:
            cash_net = float(getattr(line, 'cash_debit', 0.0) or 0.0) - float(getattr(line, 'cash_credit', 0.0) or 0.0)
        except Exception:
            cash_net = 0.0

        if abs(cash_net) > eps_cash:
            _add_tx(
                sb_id=sb.id,
                direction='in' if cash_net > 0 else 'out',
                amount_cash=abs(float(cash_net)),
            )

        # Gold by karat (net per karat)
        def _net(field_debit: str, field_credit: str) -> float:
            try:
                return float(getattr(line, field_debit, 0.0) or 0.0) - float(getattr(line, field_credit, 0.0) or 0.0)
            except Exception:
                return 0.0

        nets = {
            '18k': _net('debit_18k', 'credit_18k'),
            '21k': _net('debit_21k', 'credit_21k'),
            '22k': _net('debit_22k', 'credit_22k'),
            '24k': _net('debit_24k', 'credit_24k'),
        }
        pos = {k: v for k, v in nets.items() if v > eps_w}
        neg = {k: v for k, v in nets.items() if v < -eps_w}

        if pos:
            _add_tx(
                sb_id=sb.id,
                direction='in',
                w18=float(pos.get('18k') or 0.0),
                w21=float(pos.get('21k') or 0.0),
                w22=float(pos.get('22k') or 0.0),
                w24=float(pos.get('24k') or 0.0),
            )
        if neg:
            _add_tx(
                sb_id=sb.id,
                direction='out',
                w18=abs(float(neg.get('18k') or 0.0)),
                w21=abs(float(neg.get('21k') or 0.0)),
                w22=abs(float(neg.get('22k') or 0.0)),
                w24=abs(float(neg.get('24k') or 0.0)),
            )


def _normalize_database_url(raw: str) -> str:
    """Mirror backend/app.py behavior for relative sqlite URLs.

    In production Postgres, this is a no-op.
    """
    value = (raw or '').strip()
    if not value:
        return value
    # SQLAlchemy expects postgresql:// (some deployments still provide postgres://)
    if value.startswith('postgres://'):
        value = 'postgresql://' + value[len('postgres://'):]
    if value.startswith('sqlite:///') and not value.startswith('sqlite:////'):
        sqlite_path = value[len('sqlite:///'):]
        if sqlite_path and not sqlite_path.startswith('/') and '/' not in sqlite_path and '\\' not in sqlite_path:
            backend_dir = os.path.dirname(os.path.abspath(__file__))
            abs_path = os.path.abspath(os.path.join(backend_dir, sqlite_path))
            return f"sqlite:///{abs_path}"
    return value


def _create_app() -> Flask:
    app = Flask(__name__)
    default_sqlite = f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.db')}"
    app.config['SQLALCHEMY_DATABASE_URI'] = _normalize_database_url(os.getenv('DATABASE_URL', default_sqlite))
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


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
    parser.add_argument(
        '--all-reference-types',
        action='store_true',
        help=(
            'Include ALL posted journal entries regardless of reference_type. '
            'Default behavior is to process only manual-like entries (safer; avoids double counting).'
        ),
    )
    parser.add_argument(
        '--reference-types',
        type=str,
        default=None,
        help=(
            'Comma-separated list of reference_type values to include (case-insensitive). '
            "Use '' for empty. Example: \"manual,journal_entry,voucher\". "
            'Ignored if --all-reference-types is set.'
        ),
    )
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

    app = _create_app()
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

        # reference_type filter:
        # - default: manual-like only (safer)
        # - --all-reference-types: no filter
        # - --reference-types: explicit allow-list
        if not args.all_reference_types:
            if args.reference_types is not None:
                raw = [p.strip() for p in str(args.reference_types).split(',')]
                norm = [p.lower() for p in raw if p is not None]
                allow_empty = any(p in ('', "''") for p in norm)
                allowed = [p for p in norm if p not in ('', "''")]

                conditions = []
                if allow_empty:
                    conditions.append(JournalEntry.reference_type.is_(None))
                    conditions.append(JournalEntry.reference_type == '')
                if allowed:
                    conditions.append(func.lower(JournalEntry.reference_type).in_(allowed))
                if conditions:
                    q = q.filter(or_(*conditions))
            else:
                # Manual-like reference_type filter (same semantics as _is_manual_like_journal_entry).
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
                if args.all_reference_types or args.reference_types is not None:
                    # When the user explicitly opts into broader scopes, only enforce
                    # the non-draft/posted/not-deleted checks (already applied in SQL).
                    pass
                else:
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
