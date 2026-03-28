"""Historical backfill/repair for voucher SafeBoxTransaction rows.

Why this exists
- SafeBox balances use `safe_box_transaction`.
- Vouchers create SafeBoxTransaction rows based on VoucherAccountLine.
- In some production datasets, voucher posting (journal_entry_line) drifted from
  voucher account line mappings, causing wrong SafeBox postings (e.g. cash IN
  into a gold safe).

This script rebuilds SafeBoxTransaction rows for approved vouchers by using the
linked accounting entry (`voucher.journal_entry_id`) as the source of truth.

Safety
- Default is DRY-RUN.
- On APPLY, it deletes existing SafeBoxTransaction rows for the voucher where
  ref_type in ('voucher', 'invoice_payment') and ref_id=voucher.id, then recreates
  them based on the linked JournalEntry lines and existing SafeBoxes.

Usage
    cd backend
    source venv/bin/activate

    # Dry-run
    python backfill_safebox_from_vouchers.py --since 2026-03-01 --until 2026-03-16 --limit 500 --newest-first

    # Target specific voucher IDs (dry-run)
    python backfill_safebox_from_vouchers.py --voucher-ids 634,637,638

    # Apply
    python backfill_safebox_from_vouchers.py --since 2026-03-01 --until 2026-03-16 --limit 500 --newest-first --apply

    # Target specific voucher IDs (apply)
    python backfill_safebox_from_vouchers.py --voucher-ids 634,637,638 --apply

Docker (inside backend container)
    cd /app/backend
    export PYTHONPATH=.
    python backfill_safebox_from_vouchers.py --since 2026-03-01 --until 2026-03-16 --limit 500 --newest-first

Notes
- This script does NOT create missing SafeBoxes. If a JournalEntry line hits an
  account_id that has no SafeBox, it is skipped (by design).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date as _date, datetime

from flask import Flask

# Ensure backend/ is importable when running from other working directories (e.g. Docker).
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import bindparam, text

from models import db


def _parse_ymd(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    return datetime.strptime(raw, "%Y-%m-%d")


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []

    normalized = raw.replace(';', ',')
    for ch in ('\n', '\r', '\t', ' '):
        normalized = normalized.replace(ch, ',')
    parts = [p.strip() for p in normalized.split(',')]

    out: list[int] = []
    seen: set[int] = set()
    for p in parts:
        if not p:
            continue
        val = int(p)
        if val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


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


def _round4(x) -> float:
    try:
        return float(round(float(x or 0.0), 4))
    except Exception:
        return 0.0


def _tx_sig_row(row: dict) -> tuple:
    return (
        int(row['safe_box_id']),
        str(row['direction'] or 'in'),
        _round4(row.get('amount_cash')),
        _round4(row.get('weight_18k')),
        _round4(row.get('weight_21k')),
        _round4(row.get('weight_22k')),
        _round4(row.get('weight_24k')),
        str(row.get('ref_type') or ''),
    )


def _coerce_created_at(value) -> datetime:
    """Coerce various DB-returned representations into a datetime.

    In PostgreSQL, voucher.date is typically a datetime; in some datasets it may
    be a date or even a string.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, _date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                # Accept ISO-8601; handle trailing 'Z' defensively.
                return datetime.fromisoformat(raw.replace('Z', '+00:00'))
            except Exception:
                pass
    return datetime.utcnow()


def _expected_rows_for_voucher(v: dict, *, created_by: str | None) -> list[dict]:
    voucher_id = int(v['id'])
    voucher_number = str(v.get('voucher_number') or '')
    voucher_type = str(v.get('voucher_type') or '')
    je_id = v.get('journal_entry_id')
    if je_id in (None, '', False, 0):
        return []
    je_id = int(je_id)

    linked_invoice_id = None
    try:
        if (v.get('reference_type') == 'invoice') and v.get('reference_id') not in (None, '', False):
            linked_invoice_id = int(v.get('reference_id'))
    except Exception:
        linked_invoice_id = None

    linked_invoice_payment_id = None
    linked_payment_method_id = None
    try:
        raw_notes = v.get('notes')
        if raw_notes:
            parsed = json.loads(raw_notes)
            if isinstance(parsed, dict):
                if parsed.get('invoice_payment_id') not in (None, '', False):
                    linked_invoice_payment_id = int(parsed.get('invoice_payment_id'))
                if parsed.get('payment_method_id') not in (None, '', False):
                    linked_payment_method_id = int(parsed.get('payment_method_id'))
    except Exception:
        linked_invoice_payment_id = None
        linked_payment_method_id = None

    effective_ref_type = 'invoice_payment' if linked_invoice_payment_id else 'voucher'

    tx_created_at = _coerce_created_at(v.get('date'))

    # Load JE lines
    dialect = getattr(getattr(db, 'engine', None), 'dialect', None)
    dialect_name = getattr(dialect, 'name', '') if dialect is not None else ''
    # In PostgreSQL `is_deleted` is BOOLEAN (coalescing with integer 0 errors).
    is_deleted_expr = 'COALESCE(is_deleted, 0)'
    if dialect_name in ('postgresql', 'postgres'):
        is_deleted_expr = 'COALESCE(is_deleted, FALSE)'

    je_lines = db.session.execute(
        text(
            "SELECT account_id, "
            f"{is_deleted_expr} AS is_deleted, "
            "COALESCE(cash_debit, 0) AS cash_debit, COALESCE(cash_credit, 0) AS cash_credit, "
            "COALESCE(debit_18k, 0) AS debit_18k, COALESCE(credit_18k, 0) AS credit_18k, "
            "COALESCE(debit_21k, 0) AS debit_21k, COALESCE(credit_21k, 0) AS credit_21k, "
            "COALESCE(debit_22k, 0) AS debit_22k, COALESCE(credit_22k, 0) AS credit_22k, "
            "COALESCE(debit_24k, 0) AS debit_24k, COALESCE(credit_24k, 0) AS credit_24k "
            "FROM journal_entry_line WHERE journal_entry_id = :je_id"
        ),
        {'je_id': je_id},
    ).mappings().all()

    je_lines = [dict(r) for r in je_lines if not bool(r.get('is_deleted')) and r.get('account_id') is not None]
    if not je_lines:
        return []

    account_ids = list({int(r['account_id']) for r in je_lines})
    safes = db.session.execute(
        text("SELECT id, account_id, safe_type, karat FROM safe_box WHERE account_id IN :ids")
        .bindparams(bindparam('ids', expanding=True)),
        {'ids': account_ids},
    ).mappings().all()
    safe_by_account_id = {int(r['account_id']): dict(r) for r in safes if r.get('account_id') is not None}
    if not safe_by_account_id:
        return []

    safe_ids = list({int(r['id']) for r in safe_by_account_id.values() if r.get('id') is not None})
    pm_by_safe_id = {}
    if safe_ids:
        pms = db.session.execute(
            text("SELECT id, default_safe_box_id FROM payment_method WHERE default_safe_box_id IN :ids")
            .bindparams(bindparam('ids', expanding=True)),
            {'ids': safe_ids},
        ).mappings().all()
        for pm in pms:
            sid = pm.get('default_safe_box_id')
            if sid and sid not in pm_by_safe_id:
                pm_by_safe_id[int(sid)] = int(pm['id'])

    eps_cash = 0.005
    eps_w = 0.0005

    expected: list[dict] = []

    for line in je_lines:
        acc_id = int(line['account_id'])
        sb = safe_by_account_id.get(acc_id)
        if not sb:
            continue

        sb_id = int(sb['id'])
        safe_type = (sb.get('safe_type') or '')
        safe_karat = sb.get('karat')
        try:
            safe_karat = int(safe_karat) if safe_karat not in (None, '', False) else None
        except Exception:
            safe_karat = None

        cash_debit = float(line.get('cash_debit') or 0.0)
        cash_credit = float(line.get('cash_credit') or 0.0)
        if cash_debit > eps_cash:
            expected.append({
                'safe_box_id': sb_id,
                'ref_type': effective_ref_type,
                'ref_id': voucher_id,
                'invoice_id': linked_invoice_id,
                'invoice_payment_id': linked_invoice_payment_id,
                'payment_method_id': linked_payment_method_id or pm_by_safe_id.get(sb_id),
                'direction': 'in',
                'amount_cash': cash_debit,
                'weight_18k': 0.0,
                'weight_21k': 0.0,
                'weight_22k': 0.0,
                'weight_24k': 0.0,
                'notes': f"Voucher {voucher_number} - {voucher_type}",
                'created_by': created_by or v.get('created_by'),
                'created_at': tx_created_at,
            })
        if cash_credit > eps_cash:
            expected.append({
                'safe_box_id': sb_id,
                'ref_type': effective_ref_type,
                'ref_id': voucher_id,
                'invoice_id': linked_invoice_id,
                'invoice_payment_id': linked_invoice_payment_id,
                'payment_method_id': linked_payment_method_id or pm_by_safe_id.get(sb_id),
                'direction': 'out',
                'amount_cash': cash_credit,
                'weight_18k': 0.0,
                'weight_21k': 0.0,
                'weight_22k': 0.0,
                'weight_24k': 0.0,
                'notes': f"Voucher {voucher_number} - {voucher_type}",
                'created_by': created_by or v.get('created_by'),
                'created_at': tx_created_at,
            })

        w_deb = {
            '18k': float(line.get('debit_18k') or 0.0),
            '21k': float(line.get('debit_21k') or 0.0),
            '22k': float(line.get('debit_22k') or 0.0),
            '24k': float(line.get('debit_24k') or 0.0),
        }
        w_cred = {
            '18k': float(line.get('credit_18k') or 0.0),
            '21k': float(line.get('credit_21k') or 0.0),
            '22k': float(line.get('credit_22k') or 0.0),
            '24k': float(line.get('credit_24k') or 0.0),
        }

        if safe_type == 'gold' and safe_karat:
            allowed_key = f"{safe_karat}k"
            if allowed_key in ('18k', '21k', '22k', '24k'):
                other_keys = [k for k in ('18k', '21k', '22k', '24k') if k != allowed_key]
                if any(abs(w_deb[k]) > eps_w or abs(w_cred[k]) > eps_w for k in other_keys):
                    raise ValueError(f"karat_mismatch_for_safe_box: safe_box_id={sb_id}, allowed={safe_karat}")

        if any(w_deb[k] > eps_w for k in ('18k', '21k', '22k', '24k')):
            expected.append({
                'safe_box_id': sb_id,
                'ref_type': effective_ref_type,
                'ref_id': voucher_id,
                'invoice_id': linked_invoice_id,
                'invoice_payment_id': linked_invoice_payment_id,
                'payment_method_id': linked_payment_method_id or pm_by_safe_id.get(sb_id),
                'direction': 'in',
                'amount_cash': 0.0,
                'weight_18k': w_deb['18k'],
                'weight_21k': w_deb['21k'],
                'weight_22k': w_deb['22k'],
                'weight_24k': w_deb['24k'],
                'notes': f"Voucher {voucher_number} - {voucher_type}",
                'created_by': created_by or v.get('created_by'),
                'created_at': tx_created_at,
            })
        if any(w_cred[k] > eps_w for k in ('18k', '21k', '22k', '24k')):
            expected.append({
                'safe_box_id': sb_id,
                'ref_type': effective_ref_type,
                'ref_id': voucher_id,
                'invoice_id': linked_invoice_id,
                'invoice_payment_id': linked_invoice_payment_id,
                'payment_method_id': linked_payment_method_id or pm_by_safe_id.get(sb_id),
                'direction': 'out',
                'amount_cash': 0.0,
                'weight_18k': w_cred['18k'],
                'weight_21k': w_cred['21k'],
                'weight_22k': w_cred['22k'],
                'weight_24k': w_cred['24k'],
                'notes': f"Voucher {voucher_number} - {voucher_type}",
                'created_by': created_by or v.get('created_by'),
                'created_at': tx_created_at,
            })

    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description='Rebuild SafeBoxTransaction rows for vouchers based on linked journal entries.')
    parser.add_argument('--apply', action='store_true', help='Commit changes (default: dry-run).')
    parser.add_argument('--since', type=str, default=None, help='Filter voucher.date >= YYYY-MM-DD')
    parser.add_argument('--until', type=str, default=None, help='Filter voucher.date <= YYYY-MM-DD')
    parser.add_argument('--limit', type=int, default=None, help='Max number of vouchers to process.')
    parser.add_argument('--newest-first', action='store_true', help='Process newest vouchers first (useful with --limit).')
    parser.add_argument('--voucher-number', type=str, default=None, help='Process a single voucher_number.')
    parser.add_argument('--voucher-ids', type=str, default=None, help='Process specific voucher IDs (comma/space separated).')
    parser.add_argument('--created-by', type=str, default='system-backfill', help='Value to store in SafeBoxTransaction.created_by')
    parser.add_argument('--verbose', action='store_true', help='Print per-voucher details.')
    args = parser.parse_args()

    dry_run = not bool(args.apply)

    since_dt = _parse_ymd(args.since)
    until_dt = _parse_ymd(args.until)
    if until_dt is not None:
        until_dt = until_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    app = _create_app()
    with app.app_context():
        dialect = getattr(db.engine.dialect, 'name', '')

        def _table_columns(table_name: str) -> set[str]:
            if dialect == 'sqlite':
                rows = db.session.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
                return {str(r.get('name')) for r in rows if r.get('name')}

            rows = db.session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :t AND table_schema = CURRENT_SCHEMA()"
                ),
                {'t': table_name},
            ).all()
            return {str(r[0]) for r in rows if r and r[0]}

        sbt_cols = _table_columns('safe_box_transaction')
        where = ["status = 'approved'", "journal_entry_id IS NOT NULL"]
        params = {}

        voucher_ids = _parse_ids(args.voucher_ids)
        if args.voucher_number and voucher_ids:
            raise SystemExit('Use either --voucher-number or --voucher-ids (not both).')
        if args.voucher_number:
            where.append("voucher_number = :vn")
            params['vn'] = str(args.voucher_number)
        if voucher_ids:
            where.append("id IN :vids")
            params['vids'] = [int(v) for v in voucher_ids]
        if since_dt is not None:
            where.append("date >= :since")
            params['since'] = since_dt
        if until_dt is not None:
            where.append("date <= :until")
            params['until'] = until_dt

        order = "id DESC" if args.newest_first else "id ASC"
        limit_sql = " LIMIT :lim" if (args.limit and args.limit > 0) else ""
        if args.limit and args.limit > 0:
            params['lim'] = int(args.limit)

        sql = (
            "SELECT id, voucher_number, voucher_type, date, status, amount_cash, reference_type, reference_id, notes, created_by, journal_entry_id "
            "FROM voucher WHERE " + " AND ".join(where) + f" ORDER BY {order}" + limit_sql
        )

        stmt = text(sql)
        if voucher_ids:
            stmt = stmt.bindparams(bindparam('vids', expanding=True))

        vouchers = db.session.execute(stmt, params).mappings().all()
        vouchers = [dict(v) for v in vouchers]
        print(f"Loaded vouchers: {len(vouchers)}", flush=True)
        if not vouchers:
            return 0

        changed = 0
        processed = 0

        for v in vouchers:
            processed += 1
            existing_rows = db.session.execute(
                text(
                    "SELECT id, safe_box_id, ref_type, ref_id, direction, amount_cash, weight_18k, weight_21k, weight_22k, weight_24k "
                    "FROM safe_box_transaction "
                    "WHERE ref_id = :rid "
                    "  AND ("
                    "    ref_type = 'voucher'"
                    "    OR (ref_type = 'invoice_payment' AND (invoice_payment_id IS NULL OR invoice_payment_id != ref_id))"
                    "  )"
                ),
                {'rid': int(v['id'])},
            ).mappings().all()
            existing_rows = [dict(r) for r in existing_rows]

            expected_rows = _expected_rows_for_voucher(v, created_by=str(args.created_by))

            existing_sig = sorted([_tx_sig_row(r) for r in existing_rows])
            expected_sig = sorted([_tx_sig_row(r) for r in expected_rows])

            if existing_sig == expected_sig:
                continue

            changed += 1
            if args.verbose:
                print(
                    f"Voucher {v.get('voucher_number')} (id={v.get('id')}) will be rebuilt: existing={len(existing_rows)} expected={len(expected_rows)}",
                    flush=True,
                )

            if dry_run:
                continue

            # Apply: delete existing, insert expected.
            # Scope to voucher-owned rows only: ref_type='voucher', or ref_type='invoice_payment'
            # rows created by a previous backfill (identified by invoice_payment_id != ref_id).
            # Real invoice_payment SBTs have invoice_payment_id = ref_id and must NOT be deleted.
            db.session.execute(
                text(
                    "DELETE FROM safe_box_transaction "
                    "WHERE ref_id = :rid "
                    "  AND ("
                    "    ref_type = 'voucher'"
                    "    OR (ref_type = 'invoice_payment' AND (invoice_payment_id IS NULL OR invoice_payment_id != ref_id))"
                    "  )"
                ),
                {'rid': int(v['id'])},
            )
            base_insert_cols = [
                'safe_box_id',
                'ref_type',
                'ref_id',
                'direction',
                'amount_cash',
                'weight_18k',
                'weight_21k',
                'weight_22k',
                'weight_24k',
                'notes',
                'created_by',
                'created_at',
            ]
            optional_cols = ['invoice_id', 'invoice_payment_id', 'payment_method_id']
            insert_cols = [c for c in (base_insert_cols + optional_cols) if c in sbt_cols]
            if not insert_cols:
                raise RuntimeError('safe_box_transaction schema not detected')

            cols_sql = ', '.join(insert_cols)
            vals_sql = ', '.join([f":{c}" for c in insert_cols])
            insert_sql = text(f"INSERT INTO safe_box_transaction ({cols_sql}) VALUES ({vals_sql})")

            for row in expected_rows:
                payload = {k: row.get(k) for k in insert_cols}
                db.session.execute(insert_sql, payload)
            db.session.commit()

        mode = 'DRY RUN' if dry_run else 'APPLIED'
        print(f"[{mode}] Processed vouchers: {processed}", flush=True)
        print(f"[{mode}] Vouchers needing rebuild: {changed}", flush=True)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
