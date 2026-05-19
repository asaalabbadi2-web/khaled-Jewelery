"""Automatic SafeBox reconciliation scheduler.

Runs nightly to backfill any missing SafeBoxTransactions for:
  A) Voucher JEs that were never posted (for posted invoices)
  B) Invoice JE lines that hit safe-box accounts but have no SBT rows

This makes the system self-healing: no manual calls to the repair endpoint needed.

Note: Designed for single-process deployments (dev / gunicorn single-worker).
In multi-worker setups run this in a dedicated scheduler container.
"""

from __future__ import annotations

import time
from datetime import datetime
from threading import Thread

import schedule


class SafeboxReconciliationScheduler:
    """Daily reconciliation scheduler for SafeBoxTransaction sub-ledger."""

    RUN_AT = "02:30"  # Server local time. After backup (02:00).

    def __init__(self, app):
        self.app = app
        self.is_running = False
        self._scheduler = schedule.Scheduler()

    # ------------------------------------------------------------------
    # Repair logic (mirrors the /safe-boxes/repair-transactions endpoint)
    # ------------------------------------------------------------------

    def _run_repair(self) -> dict:
        """Execute the repair logic inside an app context. Returns a summary dict."""
        from models import Invoice, Voucher, JournalEntry, SafeBox, SafeBoxTransaction, db
        from sqlalchemy import func, or_

        now = datetime.utcnow()
        approved_by = "scheduler"
        voucher_je_fixed = 0
        sbt_fixed = 0
        errors = []

        try:
            # ── Phase A: Post unposted voucher JEs for posted invoices ──
            posted_invoice_ids = [
                int(r[0])
                for r in Invoice.query.filter(
                    func.coalesce(Invoice.is_posted, False) == True,  # noqa: E712
                ).with_entities(Invoice.id).all()
            ]

            if posted_invoice_ids:
                linked_vouchers = Voucher.query.filter(
                    Voucher.reference_type == "invoice",
                    Voucher.reference_id.in_(posted_invoice_ids),
                ).all()
                voucher_ids = [v.id for v in linked_vouchers]

                if voucher_ids:
                    unposted_voucher_jes = JournalEntry.query.filter(
                        JournalEntry.reference_type == "voucher",
                        JournalEntry.reference_id.in_(voucher_ids),
                        func.coalesce(JournalEntry.is_deleted, False) == False,  # noqa: E712
                        or_(
                            JournalEntry.is_posted == False,  # noqa: E712
                            JournalEntry.is_posted == None,   # noqa: E711
                        ),
                    ).all()

                    for vje in unposted_voucher_jes:
                        try:
                            vje.is_posted = True
                            vje.is_draft = False
                            if not getattr(vje, "posted_at", None):
                                vje.posted_at = now
                            if not getattr(vje, "posted_by", None):
                                vje.posted_by = approved_by
                            voucher_je_fixed += 1
                        except Exception as exc:
                            errors.append(f"Phase A JE {vje.id}: {exc}")

        except Exception as exc:
            errors.append(f"Phase A failed: {exc}")

        try:
            # ── Phase B: Create missing SBTs for invoice JE lines ──
            from routes import _ensure_safe_box_transactions_for_invoice_je

            invoice_jes = (
                JournalEntry.query
                .filter(JournalEntry.reference_type == "invoice")
                .filter(func.coalesce(JournalEntry.is_posted, True) == True)    # noqa: E712
                .filter(func.coalesce(JournalEntry.is_deleted, False) == False)  # noqa: E712
                .filter(func.coalesce(JournalEntry.is_draft, False) == False)    # noqa: E712
                .all()
            )

            all_safe_boxes = SafeBox.query.all()
            sb_account_ids = {
                int(sb.account_id)
                for sb in all_safe_boxes
                if sb.account_id is not None
            }

            for je in invoice_jes:
                invoice_id = je.reference_id
                if not invoice_id:
                    continue
                lines = [
                    l for l in (getattr(je, "lines", None) or [])
                    if not getattr(l, "is_deleted", False)
                ]
                hits_sb = any(
                    int(l.account_id) in sb_account_ids
                    for l in lines
                    if l.account_id is not None
                )
                if not hits_sb:
                    continue

                try:
                    created = _ensure_safe_box_transactions_for_invoice_je(
                        invoice_id=invoice_id,
                        journal_entry_id=je.id,
                        created_by=approved_by,
                    )
                    if created:
                        sbt_fixed += len(created)
                except Exception as exc:
                    errors.append(f"Phase B invoice {invoice_id}: {exc}")

        except Exception as exc:
            errors.append(f"Phase B failed: {exc}")

        # ── Commit everything ──
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            errors.append(f"Commit failed: {exc}")

        return {
            "ran_at": now.isoformat() + "Z",
            "voucher_je_fixed": voucher_je_fixed,
            "sbt_rows_created": sbt_fixed,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Scheduler wiring
    # ------------------------------------------------------------------

    def repair_job(self) -> None:
        """Called by the schedule loop. Runs inside app context."""
        with self.app.app_context():
            try:
                result = self._run_repair()
                tag = "[SafeboxReconciliation]"
                if result["errors"]:
                    print(
                        f"{tag} Finished with {len(result['errors'])} error(s). "
                        f"voucher_je_fixed={result['voucher_je_fixed']} "
                        f"sbt_rows_created={result['sbt_rows_created']} "
                        f"errors={result['errors']}"
                    )
                else:
                    print(
                        f"{tag} OK — voucher_je_fixed={result['voucher_je_fixed']} "
                        f"sbt_rows_created={result['sbt_rows_created']}"
                    )
            except Exception as exc:
                print(f"[SafeboxReconciliation] Unhandled error: {exc}")

    def _loop(self) -> None:
        while self.is_running:
            self._scheduler.run_pending()
            time.sleep(30)

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._scheduler.every().day.at(self.RUN_AT).do(self.repair_job).tag(
            "safebox_reconciliation"
        )
        thread = Thread(
            target=self._loop,
            name="SafeboxReconciliationScheduler",
            daemon=True,
        )
        thread.start()
        print(
            f"[SafeboxReconciliationScheduler] Started — "
            f"runs daily at {self.RUN_AT} (server local time)"
        )


def start_safebox_reconciliation_scheduler(app) -> None:
    scheduler = SafeboxReconciliationScheduler(app)
    scheduler.start()
