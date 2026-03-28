#!/usr/bin/env python3
"""Repair missing SafeBoxTransaction rows for posted invoices and vouchers.

Replicates the logic of POST /api/safe-boxes/repair-transactions as a
standalone devtools script so it can be run directly inside the Docker
container without a running server or auth token.

What it does
============
Phase A — Post unposted voucher JEs
  Finds vouchers linked to posted invoices whose journal entry is still
  marked is_posted=False and posts them.

Phase B — Backfill missing SBTs for invoice JE lines
  Scans all posted invoice journal entries.  For every JE line that hits
  a safe-box account (account_id matches SafeBox.account_id), creates a
  SafeBoxTransaction row when none exists yet.  Idempotent — running it
  twice produces no duplicates.

Safety
======
- Default mode is **dry-run** (prints what would change, touches nothing).
- Pass ``--apply`` to write changes to the database.

Usage
=====
  # Inside Docker container:
  cd /app/backend
  python devtools/repair_safebox_transactions.py --dry-run
  python devtools/repair_safebox_transactions.py --apply

  # Local dev:
  cd backend
  source venv/bin/activate
  python devtools/repair_safebox_transactions.py --dry-run
  python devtools/repair_safebox_transactions.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

# Ensure backend/ is on sys.path regardless of cwd.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from flask import Flask
from sqlalchemy import or_

from models import (
    db,
    Invoice,
    JournalEntry,
    JournalEntryLine,
    PaymentMethod,
    SafeBox,
    SafeBoxTransaction,
    Voucher,
)


# ── app bootstrap ──────────────────────────────────────────────────────────────

def _normalize_db_url(raw: str) -> str:
    value = (raw or "").strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if value.startswith("sqlite:///") and not value.startswith("sqlite:////"):
        path = value[len("sqlite:///"):]
        if path and not path.startswith("/") and "/" not in path and "\\" not in path:
            value = f"sqlite:///{os.path.abspath(os.path.join(BACKEND_DIR, path))}"
    return value


def _create_app() -> Flask:
    app = Flask(__name__)
    default = f"sqlite:///{os.path.join(BACKEND_DIR, 'app.db')}"
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_db_url(os.getenv("DATABASE_URL", default))
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


# ── core logic ─────────────────────────────────────────────────────────────────

def _ensure_sbt_for_je(
    je: JournalEntry,
    safe_by_account: dict,
    created_by: str,
    dry_run: bool,
    phase: str = "B",
) -> list[dict]:
    """Create (or report) missing SBTs for a JE whose lines hit safe-box accounts.

    Works for any reference_type (invoice, invoice_payment, etc.).
    Idempotent: skips safe-boxes that already have an SBT row for this ref_id.
    """
    ref_type = str(je.reference_type or "")
    ref_id = je.reference_id
    if not ref_id:
        return []
    ref_id = int(ref_id)

    lines = [
        ln for ln in (getattr(je, "lines", None) or [])
        if not getattr(ln, "is_deleted", False)
    ]
    if not lines:
        return []

    # Which lines hit a safe-box account?
    hits = [(ln, safe_by_account[int(ln.account_id)]) for ln in lines
            if ln.account_id is not None and int(ln.account_id) in safe_by_account]
    if not hits:
        return []

    # Existing SBTs for this ref_id on each safe_box (any ref_type)
    existing_sb_ids: set[int] = {
        int(sbt.safe_box_id)
        for sbt in SafeBoxTransaction.query.filter(
            SafeBoxTransaction.ref_id == ref_id,
        ).all()
        if abs(float(getattr(sbt, "amount_cash", 0) or 0)) > 0.005
    }

    # Payment method lookup (safe_box_id → payment_method_id)
    safe_ids = list({sb.id for _, sb in hits})
    pm_by_safe: dict[int, int] = {}
    for pm in PaymentMethod.query.filter(PaymentMethod.default_safe_box_id.in_(safe_ids)).all():
        if pm.default_safe_box_id and pm.default_safe_box_id not in pm_by_safe:
            pm_by_safe[pm.default_safe_box_id] = pm.id

    # For invoice JEs, also carry invoice_id on the SBT
    invoice_id = ref_id if ref_type == "invoice" else None

    eps = 0.005
    actions: list[dict] = []

    for line, sb in hits:
        if sb.id in existing_sb_ids:
            continue

        cash_debit = float(getattr(line, "cash_debit", 0) or 0)
        cash_credit = float(getattr(line, "cash_credit", 0) or 0)

        for amount, direction in ((cash_debit, "in"), (cash_credit, "out")):
            if amount <= eps:
                continue
            action = {
                "phase": phase,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "journal_entry_id": je.id,
                "safe_box_id": sb.id,
                "safe_box_name": getattr(sb, "name", str(sb.id)),
                "direction": direction,
                "amount_cash": round(amount, 4),
                "action": "would_create" if dry_run else "created",
            }
            if not dry_run:
                tx = SafeBoxTransaction(
                    safe_box_id=sb.id,
                    ref_type=ref_type,
                    ref_id=ref_id,
                    invoice_id=invoice_id,
                    payment_method_id=pm_by_safe.get(sb.id),
                    direction=direction,
                    amount_cash=amount,
                    notes=f"{ref_type} #{ref_id} – backfill via repair_safebox_transactions",
                    created_by=created_by,
                )
                db.session.add(tx)
                existing_sb_ids.add(sb.id)
            actions.append(action)

    return actions


# Keep old name as alias for backward compat
def _ensure_sbt_for_invoice_je(
    invoice_id: int,
    je: JournalEntry,
    safe_by_account: dict,
    created_by: str,
    dry_run: bool,
) -> list[dict]:
    return _ensure_sbt_for_je(je, safe_by_account, created_by, dry_run, phase="B")


def run(dry_run: bool, created_by: str = "system") -> None:
    now = datetime.utcnow()
    mode_label = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n{'='*65}")
    print(f"  repair_safebox_transactions  [{mode_label}]  {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"{'='*65}\n")

    # ── Phase A: post unposted voucher JEs for posted invoices ──────────────
    print("Phase A — post unposted voucher JEs for posted invoices …")

    posted_invoice_ids = [
        int(r[0])
        for r in Invoice.query.filter(
            Invoice.is_posted == True  # noqa: E712
        ).with_entities(Invoice.id).all()
    ]

    phase_a_actions: list[dict] = []

    if posted_invoice_ids:
        linked_vouchers = Voucher.query.filter(
            Voucher.reference_type == "invoice",
            Voucher.reference_id.in_(posted_invoice_ids),
        ).all()
        voucher_to_invoice = {v.id: v.reference_id for v in linked_vouchers}
        voucher_ids = list(voucher_to_invoice.keys())

        if voucher_ids:
            unposted_jes = JournalEntry.query.filter(
                JournalEntry.reference_type == "voucher",
                JournalEntry.reference_id.in_(voucher_ids),
                JournalEntry.is_deleted.is_(None) | (JournalEntry.is_deleted == False),  # noqa: E712
                or_(
                    JournalEntry.is_posted == False,  # noqa: E712
                    JournalEntry.is_posted.is_(None),
                ),
            ).all()

            for vje in unposted_jes:
                inv_id = voucher_to_invoice.get(vje.reference_id)
                action = {
                    "phase": "A",
                    "voucher_id": vje.reference_id,
                    "journal_entry_id": vje.id,
                    "invoice_id": inv_id,
                    "action": "would_post" if dry_run else "posted",
                }
                if not dry_run:
                    vje.is_posted = True
                    vje.is_draft = False
                    if not getattr(vje, "posted_at", None):
                        vje.posted_at = now
                    if not getattr(vje, "posted_by", None):
                        vje.posted_by = created_by
                phase_a_actions.append(action)
                print(f"  {'[would post]' if dry_run else '[posted]'} JE #{vje.id}  "
                      f"voucher #{vje.reference_id}  invoice #{inv_id}")

    if not phase_a_actions:
        print("  ✅ nothing to do")
    print(f"  Phase A total: {len(phase_a_actions)}\n")

    # ── Phase B: backfill SBTs for invoice JE lines on safe-box accounts ────
    print("Phase B — backfill missing SBTs for invoice JE lines …")

    all_safe_boxes = SafeBox.query.all()
    safe_by_account: dict[int, SafeBox] = {
        int(sb.account_id): sb
        for sb in all_safe_boxes
        if sb.account_id is not None
    }

    def _query_jes(ref_type: str):
        return (
            JournalEntry.query
            .filter(JournalEntry.reference_type == ref_type)
            .filter(JournalEntry.is_posted.is_(None) | (JournalEntry.is_posted == True))   # noqa: E712
            .filter(JournalEntry.is_deleted.is_(None) | (JournalEntry.is_deleted == False)) # noqa: E712
            .filter(JournalEntry.is_draft.is_(None) | (JournalEntry.is_draft == False))     # noqa: E712
            .all()
        )

    phase_b_actions: list[dict] = []
    skipped = 0

    for je in _query_jes("invoice"):
        if not je.reference_id:
            continue
        actions = _ensure_sbt_for_je(je, safe_by_account, created_by, dry_run, phase="B")
        if actions:
            for a in actions:
                phase_b_actions.append(a)
                print(f"  {'[would create]' if dry_run else '[created]'} SBT  "
                      f"{a['ref_type']} #{a['ref_id']}  JE #{je.id}  "
                      f"safe_box #{a['safe_box_id']} ({a['safe_box_name'][:20]})  "
                      f"{a['direction']}  {a['amount_cash']:,.2f}")
        else:
            skipped += 1

    if not phase_b_actions:
        print("  ✅ nothing to do")
    print(f"  Phase B total: {len(phase_b_actions)}  (skipped {skipped} JEs with no missing SBTs)\n")

    # ── Phase C: backfill SBTs for invoice_payment JE lines ─────────────────
    print("Phase C — backfill missing SBTs for invoice_payment JE lines …")

    phase_c_actions: list[dict] = []
    skipped_c = 0

    for je in _query_jes("invoice_payment"):
        if not je.reference_id:
            continue
        actions = _ensure_sbt_for_je(je, safe_by_account, created_by, dry_run, phase="C")
        if actions:
            for a in actions:
                phase_c_actions.append(a)
                print(f"  {'[would create]' if dry_run else '[created]'} SBT  "
                      f"{a['ref_type']} #{a['ref_id']}  JE #{je.id}  "
                      f"safe_box #{a['safe_box_id']} ({a['safe_box_name'][:20]})  "
                      f"{a['direction']}  {a['amount_cash']:,.2f}")
        else:
            skipped_c += 1

    if not phase_c_actions:
        print("  ✅ nothing to do")
    print(f"  Phase C total: {len(phase_c_actions)}  (skipped {skipped_c} JEs with no missing SBTs)\n")

    # ── commit or rollback ────────────────────────────────────────────────────
    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    # ── summary ───────────────────────────────────────────────────────────────
    print(f"{'='*65}")
    print(f"  Summary [{mode_label}]")
    print(f"{'='*65}")
    print(f"  Phase A (voucher JE posts):      {len(phase_a_actions):>5}")
    print(f"  Phase B (invoice SBTs):          {len(phase_b_actions):>5}")
    print(f"  Phase C (invoice_payment SBTs):  {len(phase_c_actions):>5}")
    total = len(phase_a_actions) + len(phase_b_actions) + len(phase_c_actions)
    print(f"  Total actions:                   {total:>5}")
    print(f"  Mode:                            {mode_label}")
    if dry_run:
        print("\n  ⚠️  Dry-run — no changes written.  Pass --apply to apply.\n")
    else:
        print("\n  ✅ Changes committed to database.\n")


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair missing SafeBoxTransaction rows for posted invoices/vouchers.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would change without writing anything (default).",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes to the database.",
    )
    parser.add_argument(
        "--created-by",
        default="system",
        help="Username to record as creator of new SBT rows (default: system).",
    )
    args = parser.parse_args()

    dry_run = not args.apply

    app = _create_app()
    with app.app_context():
        run(dry_run=dry_run, created_by=args.created_by)


if __name__ == "__main__":
    main()
