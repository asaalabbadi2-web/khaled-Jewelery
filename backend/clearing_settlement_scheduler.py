"""Automatic clearing settlements scheduler.

Creates clearing settlement vouchers (Clearing → Bank) for payment methods that
opt in via PaymentMethod auto-settlement settings.

Important notes:
- We currently auto-create settlements with fee_amount=0.0.
  If a payment method uses commission_timing='settlement' and has commission_rate > 0,
  we skip it to avoid silently missing commission entries.
- Due calculation is based on SafeBoxTransaction ledger:
  invoice_payment transactions up to a cutoff date minus previous clearing_settlement
  voucher outs (FIFO-style approximation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from threading import Thread

import schedule
from sqlalchemy import case, func

from models import db, PaymentMethod, SafeBoxTransaction, Voucher
from services.live_balances import live_balances_by_account_ids


@dataclass
class _DueAmounts:
    payments_up_to_cutoff: float
    settled_total: float
    due_amount: float


class ClearingSettlementScheduler:
    def __init__(self, app):
        self.app = app
        self.is_running = False

    def _live_cash_balance_for_safe_box(self, safe_box) -> float:
        account = getattr(safe_box, 'account', None)
        account_id = getattr(account, 'id', None)
        fallback = float(getattr(account, 'balance_cash', 0.0) or 0.0) if account is not None else 0.0
        if account_id is None:
            return fallback
        try:
            live = live_balances_by_account_ids([int(account_id)]).get(int(account_id))
            if isinstance(live, dict):
                return float(live.get('cash') or 0.0)
        except Exception:
            pass
        return fallback

    def _compute_due_amount(self, safe_box_id: int, cutoff_dt: datetime) -> _DueAmounts:
        # Sum invoice payments up to cutoff
        payments_signed = func.coalesce(
            func.sum(
                case(
                    (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.amount_cash),
                    else_=-SafeBoxTransaction.amount_cash,
                )
            ),
            0.0,
        )

        payments_up_to_cutoff = (
            db.session.query(payments_signed)
            .filter(
                SafeBoxTransaction.safe_box_id == safe_box_id,
                SafeBoxTransaction.ref_type == 'invoice_payment',
                SafeBoxTransaction.created_at <= cutoff_dt,
            )
            .scalar()
            or 0.0
        )

        # Sum previous clearing settlements (including reversals) to avoid double-settling.
        settled_signed = func.coalesce(
            func.sum(
                case(
                    (SafeBoxTransaction.direction == 'out', SafeBoxTransaction.amount_cash),
                    else_=-SafeBoxTransaction.amount_cash,
                )
            ),
            0.0,
        )

        settled_total = (
            db.session.query(settled_signed)
            .join(Voucher, Voucher.id == SafeBoxTransaction.ref_id)
            .filter(
                SafeBoxTransaction.safe_box_id == safe_box_id,
                SafeBoxTransaction.ref_type.in_(['voucher', 'voucher_reversal']),
                Voucher.reference_type == 'clearing_settlement',
            )
            .scalar()
            or 0.0
        )

        due_amount = float(payments_up_to_cutoff or 0.0) - float(settled_total or 0.0)
        return _DueAmounts(
            payments_up_to_cutoff=float(payments_up_to_cutoff or 0.0),
            settled_total=float(settled_total or 0.0),
            due_amount=float(due_amount or 0.0),
        )

    def _count_bulk_due_transactions(self, safe_box_id: int, cutoff_dt: datetime) -> int:
        """Approximate how many invoice-payment rows belong to the next bulk settlement.

        We use the latest clearing-settlement voucher timestamp on this safe box as the
        lower bound, then count incoming invoice payments up to the current cutoff.
        This enables fixed-fee auto settlement for bulk mode without changing the
        voucher data model.
        """

        last_settlement_dt = (
            db.session.query(func.max(Voucher.date))
            .join(SafeBoxTransaction, SafeBoxTransaction.ref_id == Voucher.id)
            .filter(
                SafeBoxTransaction.safe_box_id == safe_box_id,
                SafeBoxTransaction.ref_type.in_(['voucher', 'voucher_reversal']),
                Voucher.reference_type == 'clearing_settlement',
            )
            .scalar()
        )

        query = SafeBoxTransaction.query.filter(
            SafeBoxTransaction.safe_box_id == safe_box_id,
            SafeBoxTransaction.ref_type == 'invoice_payment',
            SafeBoxTransaction.direction == 'in',
            SafeBoxTransaction.created_at <= cutoff_dt,
        )
        if last_settlement_dt is not None:
            query = query.filter(SafeBoxTransaction.created_at > last_settlement_dt)

        return int(query.count() or 0)

    def _compute_bulk_fee_amount(self, *, pm, safe_box_id: int, cutoff_dt: datetime, gross_amount: float) -> tuple[float, int]:
        timing = str(getattr(pm, 'commission_timing', 'invoice') or 'invoice').strip().lower()
        if timing != 'settlement':
            return 0.0, 0

        rate = float(getattr(pm, 'commission_rate', 0.0) or 0.0)
        fixed = float(getattr(pm, 'commission_fixed_amount', 0.0) or 0.0)
        if rate <= 0.0 and fixed <= 0.0:
            return 0.0, 0

        transaction_count = self._count_bulk_due_transactions(safe_box_id, cutoff_dt)
        effective_count = transaction_count if transaction_count > 0 else 1
        fee_amount = round((gross_amount * rate / 100.0) + (fixed * effective_count), 2)
        return fee_amount, transaction_count

    def process_due_settlements(self) -> dict:
        """Run auto-settlement for all eligible payment methods.

        Returns a diagnostic dict with keys:
          - settled_count: number of bulk settlement vouchers created
          - per_tx_settled_count: number of per-transaction vouchers created
          - skipped: list of {pm_id, name, reason} for skipped PMs
          - enabled_methods: total PMs checked
        """
        result: dict = {
            'settled_count': 0,
            'per_tx_settled_count': 0,
            'enabled_methods': 0,
            'skipped': [],
        }
        with self.app.app_context():
            from routes import _create_clearing_settlement_voucher

            today = date.today()
            weekday = today.weekday()  # 0=Mon .. 6=Sun

            methods = (
                PaymentMethod.query
                .filter_by(is_active=True, auto_settlement_enabled=True)
                .all()
            )
            result['enabled_methods'] = len(methods)

            if not methods:
                print('[ClearingSettlementScheduler] No enabled payment methods')
                return result

            for pm in methods:
                try:
                    pm_name = getattr(pm, 'name', str(pm.id))

                    def _skip(reason: str):
                        result['skipped'].append({'pm_id': pm.id, 'name': pm_name, 'reason': reason})

                    # Basic config
                    if not pm.default_safe_box_id:
                        _skip('no_clearing_safe_box')
                        continue
                    if not pm.settlement_bank_safe_box_id:
                        _skip('no_bank_safe_box')
                        continue

                    clearing_sb = pm.default_safe_box
                    bank_sb = pm.settlement_bank_safe_box
                    if not clearing_sb or not bank_sb:
                        _skip('safe_box_not_found')
                        continue
                    if not getattr(clearing_sb, 'is_active', True) or not getattr(bank_sb, 'is_active', True):
                        _skip('safe_box_inactive')
                        continue

                    if (clearing_sb.safe_type or '').strip().lower() != 'clearing':
                        _skip(f'clearing_safe_wrong_type:{clearing_sb.safe_type}')
                        continue
                    if (bank_sb.safe_type or '').strip().lower() != 'bank':
                        _skip(f'bank_safe_wrong_type:{bank_sb.safe_type}')
                        continue

                    schedule_type = (pm.settlement_schedule_type or 'days').strip().lower()

                    # Determine if this method is due to run today, and compute cutoff.
                    cutoff_days = int(pm.settlement_days or 0)
                    if schedule_type == 'weekday':
                        if pm.settlement_weekday is None:
                            _skip('weekday_not_configured')
                            continue
                        try:
                            configured_weekday = int(pm.settlement_weekday)
                        except Exception:
                            _skip('weekday_invalid')
                            continue
                        if configured_weekday < 0 or configured_weekday > 6:
                            _skip(f'weekday_out_of_range:{configured_weekday}')
                            continue
                        if configured_weekday != weekday:
                            _skip(f'not_scheduled_today:configured={configured_weekday},today={weekday}')
                            continue
                        # Default weekly: settle up to yesterday (or more if settlement_days>0)
                        cutoff_days = max(cutoff_days, 1)
                    else:
                        schedule_type = 'days'

                    cutoff_date = today - timedelta(days=max(cutoff_days, 0))
                    cutoff_dt = datetime.combine(cutoff_date, time.max)

                    due = self._compute_due_amount(pm.default_safe_box_id, cutoff_dt)
                    gross_amount = round(max(0.0, due.due_amount), 2)

                    # Nothing due
                    if gross_amount < 0.01:
                        _skip(f'due_amount_zero:payments={due.payments_up_to_cutoff:.2f},settled={due.settled_total:.2f},cutoff={cutoff_dt.date().isoformat()}')
                        continue

                    # فحص الحد الأدنى للتسوية
                    min_settle = float(getattr(pm, 'min_settlement_amount', 0.0) or 0.0)
                    if min_settle > 0.01 and gross_amount < min_settle:
                        print(
                            f"[ClearingSettlementScheduler] Skipping PM#{pm.id} ({pm.name}): "
                            f"balance {gross_amount:.2f} < min_settlement_amount {min_settle:.2f}"
                        )
                        _skip(f'below_min_settlement:{gross_amount:.2f}<{min_settle:.2f}')
                        continue

                    # Cap to current clearing balance for safety
                    try:
                        clearing_balance = self._live_cash_balance_for_safe_box(clearing_sb)
                    except Exception:
                        clearing_balance = 0.0

                    if clearing_balance <= 0.0:
                        _skip(f'clearing_balance_zero_or_negative:{clearing_balance:.2f}')
                        continue
                    if gross_amount > clearing_balance:
                        gross_amount = round(clearing_balance, 2)

                    if gross_amount < 0.01:
                        _skip('gross_after_cap_zero')
                        continue

                    # نمط التسوية: bulk أو per_transaction
                    settlement_mode = str(getattr(pm, 'settlement_mode', 'bulk') or 'bulk').strip().lower()

                    if settlement_mode == 'per_transaction':
                        # -------- تسوية فردية: سند لكل معاملة --------
                        settled = self._settle_per_transaction(
                            pm=pm,
                            clearing_sb=clearing_sb,
                            bank_sb=bank_sb,
                            cutoff_dt=cutoff_dt,
                            today=today,
                        )
                        result['per_tx_settled_count'] += settled
                        continue

                    # -------- تسوية مجمّعة (bulk) — الوضع الافتراضي --------
                    reference_number = f"AUTO-PM-{pm.id}-{today.isoformat()}"
                    description = (
                        f"تسوية تلقائية لمستحقات التحصيل: {pm.name} "
                        f"({clearing_sb.name} → {bank_sb.name})"
                    )

                    fee_amount, fee_tx_count = self._compute_bulk_fee_amount(
                        pm=pm,
                        safe_box_id=clearing_sb.id,
                        cutoff_dt=cutoff_dt,
                        gross_amount=gross_amount,
                    )
                    if fee_amount >= gross_amount:
                        print(
                            f"[ClearingSettlementScheduler] Skipping PM#{pm.id} ({pm.name}): fee {fee_amount:.2f} >= gross {gross_amount:.2f}"
                        )
                        _skip(f'fee_exceeds_gross:{fee_amount:.2f}>={gross_amount:.2f}')
                        continue

                    try:
                        voucher_result = _create_clearing_settlement_voucher(
                            clearing_safe_box_id=clearing_sb.id,
                            bank_safe_box_id=bank_sb.id,
                            gross_amount=gross_amount,
                            fee_amount=fee_amount,
                            settlement_dt=datetime.now(),
                            reference_number=reference_number,
                            created_by='scheduler',
                            fee_account_id=getattr(pm, 'fee_expense_account_id', None),
                            description_override=description,
                            notes='auto_settlement',
                            ensure_unique_reference=True,
                        )
                        # If the helper reports it was skipped (idempotent), don't commit anything.
                        if voucher_result.get('skipped'):
                            db.session.rollback()
                            _skip('duplicate_reference_skipped')
                            continue

                        db.session.commit()
                        result['settled_count'] += 1
                        print(
                            f"[ClearingSettlementScheduler] ✓ Settled {gross_amount:.2f}"
                            f" (fee {fee_amount:.2f}, tx_count {fee_tx_count}) for PM#{pm.id} ({pm.name})"
                        )
                    except Exception as exc:
                        db.session.rollback()
                        print(
                            f"[ClearingSettlementScheduler] ❌ Failed PM#{pm.id} ({pm.name}): {exc}"
                        )
                        _skip(f'voucher_creation_error:{str(exc)[:120]}')

                except Exception as exc:
                    db.session.rollback()
                    print(f"[ClearingSettlementScheduler] ❌ Unexpected error for PM#{getattr(pm, 'id', '?')}: {exc}")
                    result['skipped'].append({'pm_id': getattr(pm, 'id', '?'), 'name': '?', 'reason': f'unexpected:{str(exc)[:120]}'})

        return result

    # ------------------------------------------------------------------
    # Per-transaction settlement helper
    # ------------------------------------------------------------------
    def _settle_per_transaction(self, *, pm, clearing_sb, bank_sb, cutoff_dt, today) -> int:
        """Create one clearing-settlement voucher per unsettled invoice payment.

        Returns the number of successfully created per-transaction vouchers.

        Each voucher is tracked via ``SafeBoxTransaction.notes`` with the
        pattern ``per_tx:ip_{invoice_payment_id}`` so we can detect which
        payments have already been individually settled.
        """
        from routes import _create_clearing_settlement_voucher

        # 1. All incoming invoice-payment txs up to cutoff
        unsettled_txs = (
            SafeBoxTransaction.query
            .filter(
                SafeBoxTransaction.safe_box_id == clearing_sb.id,
                SafeBoxTransaction.ref_type == 'invoice_payment',
                SafeBoxTransaction.direction == 'in',
                SafeBoxTransaction.created_at <= cutoff_dt,
            )
            .order_by(SafeBoxTransaction.created_at.asc())
            .all()
        )

        if not unsettled_txs:
            return

        # 2. Detect already-settled payment ids via notes pattern
        settled_ip_ids: set[int] = set()
        try:
            settled_rows = (
                db.session.query(SafeBoxTransaction.notes)
                .join(Voucher, Voucher.id == SafeBoxTransaction.ref_id)
                .filter(
                    SafeBoxTransaction.safe_box_id == clearing_sb.id,
                    SafeBoxTransaction.ref_type.in_(['voucher', 'voucher_reversal']),
                    Voucher.reference_type == 'clearing_settlement',
                    SafeBoxTransaction.notes.isnot(None),
                )
                .all()
            )
            for (note_val,) in settled_rows:
                if note_val and note_val.startswith('per_tx:ip_'):
                    try:
                        settled_ip_ids.add(int(note_val.split('per_tx:ip_')[1]))
                    except Exception:
                        pass
        except Exception:
            pass

        # 3. Filter to pending
        pending = []
        for tx in unsettled_txs:
            ip_id = tx.invoice_payment_id or tx.id
            if ip_id in settled_ip_ids:
                continue
            pending.append(tx)

        if not pending:
            return

        # 4. Cap total to the clearing safe-box balance
        try:
            clearing_balance = self._live_cash_balance_for_safe_box(clearing_sb)
        except Exception:
            clearing_balance = 0.0
        if clearing_balance <= 0.0:
            return

        # 5. Resolve fee parameters
        timing = str(getattr(pm, 'commission_timing', 'invoice') or 'invoice').strip().lower()
        rate = float(getattr(pm, 'commission_rate', 0.0) or 0.0)
        fixed = float(getattr(pm, 'commission_fixed_amount', 0.0) or 0.0)
        fee_account_id = getattr(pm, 'fee_expense_account_id', None)

        settled_count = 0
        running_total = 0.0

        for tx in pending:
            gross = round(float(tx.amount_cash or 0.0), 2)
            if gross <= 0.01:
                continue

            # Safety: don't exceed what the clearing box actually holds
            if running_total + gross > clearing_balance:
                break

            fee = 0.0
            if timing == 'settlement' and (rate > 0 or fixed > 0):
                fee = round((gross * rate / 100.0) + fixed, 2)

            ip_id = tx.invoice_payment_id or tx.id
            ref_num = f"AUTO-PERTX-IP{ip_id}-{today.isoformat()}"

            # Build descriptive text
            inv_info = ''
            if tx.invoice_id:
                try:
                    from models import Invoice
                    inv = Invoice.query.get(tx.invoice_id)
                    if inv:
                        inv_info = f' (فاتورة {inv.invoice_number})'
                except Exception:
                    pass

            desc = (
                f'تسوية فردية تلقائية: {clearing_sb.name} → {bank_sb.name}'
                f' — مبلغ {gross:.2f}{inv_info}'
            )

            try:
                result = _create_clearing_settlement_voucher(
                    clearing_safe_box_id=clearing_sb.id,
                    bank_safe_box_id=bank_sb.id,
                    gross_amount=gross,
                    fee_amount=fee,
                    settlement_dt=datetime.now(),
                    reference_number=ref_num,
                    created_by='scheduler',
                    fee_account_id=fee_account_id if fee > 0 else None,
                    description_override=desc,
                    notes=f'per_tx:ip_{ip_id}',
                    ensure_unique_reference=True,
                )
                if result.get('skipped'):
                    continue
                db.session.commit()
                running_total += gross
                settled_count += 1
            except Exception as exc:
                db.session.rollback()
                print(
                    f"[ClearingSettlementScheduler] ❌ Per-tx settle failed "
                    f"PM#{pm.id} IP#{ip_id}: {exc}"
                )

        if settled_count:
            print(
                f"[ClearingSettlementScheduler] ✓ Per-transaction: settled {settled_count} "
                f"txs ({running_total:.2f}) for PM#{pm.id} ({pm.name})"
            )

        return settled_count

    def setup_schedule(self):
        # Run once per day at 04:10.
        schedule.every().day.at('04:10').do(self.process_due_settlements)
        print('[ClearingSettlementScheduler] ✓ Auto settlement scheduled daily at 04:10')

    def start(self):
        if self.is_running:
            print('[ClearingSettlementScheduler] already running')
            return

        self.setup_schedule()
        self.is_running = True

        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                # Check every minute
                import time as _time

                _time.sleep(60)

        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        print('[ClearingSettlementScheduler] 🚀 started')

    def stop(self):
        self.is_running = False
        schedule.clear()
        print('[ClearingSettlementScheduler] stopped')


_scheduler_instance: ClearingSettlementScheduler | None = None


def get_clearing_settlement_scheduler(app):
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ClearingSettlementScheduler(app)
    return _scheduler_instance


def start_clearing_settlement_scheduler(app):
    scheduler = get_clearing_settlement_scheduler(app)
    scheduler.start()
    return scheduler
