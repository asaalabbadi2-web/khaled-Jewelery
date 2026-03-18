"""Recalculate stored Account balances from posted JournalEntryLine (GL).

Why
- Many reports compare SafeBoxTransaction sums to Account.balance_cash/balance_XXk.
- Account.balance_* are stored fields that can drift after backfills or legacy imports.
- This tool recomputes stored balances from the General Ledger (journal_entry_line)
  for POSTED, non-draft, non-deleted entries.

Safety
- DRY-RUN by default.
- Use --apply to commit updates.

Notes
- Intentionally does NOT include VoucherAccountLine sums to avoid double counting.
  In the current system, vouchers/invoice payments post to JournalEntryLine.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from flask import Flask

# Ensure backend/ is importable when running from other working directories (e.g. Docker).
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import bindparam, text

from models import db


def _normalize_database_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return value
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("sqlite:///") and not value.startswith("sqlite:////"):
        sqlite_path = value[len("sqlite:///") :]
        if sqlite_path and not sqlite_path.startswith("/") and "/" not in sqlite_path and "\\" not in sqlite_path:
            abs_path = os.path.abspath(os.path.join(BACKEND_DIR, sqlite_path))
            return f"sqlite:///{abs_path}"
    return value


def _create_app() -> Flask:
    app = Flask(__name__)
    default_sqlite = f"sqlite:///{os.path.join(BACKEND_DIR, 'app.db')}"
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_database_url(os.getenv("DATABASE_URL", default_sqlite))
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


@dataclass(frozen=True)
class BalanceRow:
    account_id: int
    cash: float
    w18: float
    w21: float
    w22: float
    w24: float


def _fetch_gl_balances_for_accounts(account_ids: list[int]) -> dict[int, BalanceRow]:
    if not account_ids:
        return {}

    rows = (
        db.session.execute(
            text(
                "SELECT "
                "  jel.account_id AS account_id, "
                "  COALESCE(SUM(COALESCE(jel.cash_debit,0) - COALESCE(jel.cash_credit,0)), 0) AS cash, "
                "  COALESCE(SUM(COALESCE(jel.debit_18k,0) - COALESCE(jel.credit_18k,0)), 0) AS w18, "
                "  COALESCE(SUM(COALESCE(jel.debit_21k,0) - COALESCE(jel.credit_21k,0)), 0) AS w21, "
                "  COALESCE(SUM(COALESCE(jel.debit_22k,0) - COALESCE(jel.credit_22k,0)), 0) AS w22, "
                "  COALESCE(SUM(COALESCE(jel.debit_24k,0) - COALESCE(jel.credit_24k,0)), 0) AS w24 "
                "FROM journal_entry_line jel "
                "JOIN journal_entry je ON je.id = jel.journal_entry_id "
                "WHERE jel.account_id IN :ids "
                "  AND COALESCE(jel.is_deleted, FALSE) = FALSE "
                "  AND COALESCE(je.is_deleted, FALSE) = FALSE "
                "  AND COALESCE(je.is_draft, FALSE) = FALSE "
                "  AND COALESCE(je.is_posted, TRUE) = TRUE "
                "GROUP BY jel.account_id"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": list({int(x) for x in account_ids})},
        )
        .mappings()
        .all()
    )

    out: dict[int, BalanceRow] = {}
    for r in rows:
        aid = int(r["account_id"])
        out[aid] = BalanceRow(
            account_id=aid,
            cash=float(r.get("cash") or 0.0),
            w18=float(r.get("w18") or 0.0),
            w21=float(r.get("w21") or 0.0),
            w22=float(r.get("w22") or 0.0),
            w24=float(r.get("w24") or 0.0),
        )
    # Accounts with no rows => zeros
    for aid in account_ids:
        if int(aid) not in out:
            out[int(aid)] = BalanceRow(account_id=int(aid), cash=0.0, w18=0.0, w21=0.0, w22=0.0, w24=0.0)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Recalculate stored account balances from posted GL (journal_entry_line).")
    parser.add_argument("--apply", action="store_true", help="Commit changes (default: dry-run).")
    parser.add_argument("--account-id", type=int, default=None, help="Recalc a single account id.")
    parser.add_argument(
        "--account-number",
        type=str,
        default=None,
        help="Recalc a single account by account_number (e.g. 1100000).",
    )
    parser.add_argument(
        "--safe-box-id",
        type=int,
        default=None,
        help="Recalc the account linked to a given safe_box.id.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print per-account diffs.")
    args = parser.parse_args()

    dry_run = not bool(args.apply)

    app = _create_app()
    with app.app_context():
        # Resolve target account ids.
        if args.safe_box_id is not None:
            row = db.session.execute(
                text("SELECT account_id FROM safe_box WHERE id = :sid"), {"sid": int(args.safe_box_id)}
            ).mappings().first()
            if not row or row.get("account_id") is None:
                print(f"safe_box_id={args.safe_box_id}: no linked account_id")
                return 2
            target_ids = [int(row["account_id"])]
        elif args.account_id is not None:
            target_ids = [int(args.account_id)]
        elif args.account_number is not None:
            row = db.session.execute(
                text("SELECT id FROM account WHERE account_number = :n LIMIT 1"), {"n": str(args.account_number).strip()}
            ).mappings().first()
            if not row or row.get("id") is None:
                print(f"account_number={args.account_number}: not found")
                return 2
            target_ids = [int(row["id"])]
        else:
            rows = db.session.execute(text("SELECT id FROM account")).mappings().all()
            target_ids = [int(r["id"]) for r in rows if r.get("id") is not None]

        # Fetch current stored balances.
        stored = (
            db.session.execute(
                text(
                    "SELECT id, account_number, name, tracks_weight, "
                    "balance_cash, balance_18k, balance_21k, balance_22k, balance_24k "
                    "FROM account WHERE id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": list({int(x) for x in target_ids})},
            )
            .mappings()
            .all()
        )
        if not stored:
            print("No accounts selected.")
            return 0

        gl = _fetch_gl_balances_for_accounts([int(r["id"]) for r in stored])

        changed = 0
        for r in stored:
            aid = int(r["id"])
            tracks_weight = bool(r.get("tracks_weight"))
            gl_row = gl.get(aid) or BalanceRow(account_id=aid, cash=0.0, w18=0.0, w21=0.0, w22=0.0, w24=0.0)

            old_cash = float(r.get("balance_cash") or 0.0)
            old18 = float(r.get("balance_18k") or 0.0)
            old21 = float(r.get("balance_21k") or 0.0)
            old22 = float(r.get("balance_22k") or 0.0)
            old24 = float(r.get("balance_24k") or 0.0)

            new_cash = float(gl_row.cash)
            new18 = float(gl_row.w18) if tracks_weight else old18
            new21 = float(gl_row.w21) if tracks_weight else old21
            new22 = float(gl_row.w22) if tracks_weight else old22
            new24 = float(gl_row.w24) if tracks_weight else old24

            has_change = (
                abs(old_cash - new_cash) > 0.005
                or (tracks_weight and (
                    abs(old18 - new18) > 0.0005
                    or abs(old21 - new21) > 0.0005
                    or abs(old22 - new22) > 0.0005
                    or abs(old24 - new24) > 0.0005
                ))
            )
            if not has_change:
                continue

            changed += 1
            if args.verbose or dry_run:
                num = r.get("account_number")
                name = r.get("name")
                print(f"account {num} ({name}) id={aid}")
                print(f"  cash: {old_cash:.2f} -> {new_cash:.2f}")
                if tracks_weight:
                    print(f"  18k: {old18:.3f} -> {new18:.3f}")
                    print(f"  21k: {old21:.3f} -> {new21:.3f}")
                    print(f"  22k: {old22:.3f} -> {new22:.3f}")
                    print(f"  24k: {old24:.3f} -> {new24:.3f}")

            if dry_run:
                continue

            # Apply update.
            db.session.execute(
                text(
                    "UPDATE account SET balance_cash=:c, balance_18k=:b18, balance_21k=:b21, balance_22k=:b22, balance_24k=:b24 "
                    "WHERE id=:id"
                ),
                {
                    "id": aid,
                    "c": new_cash,
                    "b18": new18,
                    "b21": new21,
                    "b22": new22,
                    "b24": new24,
                },
            )

        if dry_run:
            print(f"[DRY RUN] accounts needing update: {changed}")
            print("Run again with --apply to commit.")
        else:
            db.session.commit()
            print(f"[APPLIED] accounts updated: {changed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
