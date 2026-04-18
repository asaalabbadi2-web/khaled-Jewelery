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

from models import db, PaymentMethod, SafeBoxTransaction, Voucher, InvoicePayment, SettlementLine
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
        self._scheduler = schedule.Scheduler()

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

    def _compute_sbt_based_due(self, safe_box_id: int) -> float:
        """Compute total due for a clearing safe box using SBT-based accounting.

        due = sum(IP.amount via PM routing) - sum(SBT voucher_out for this safe box)

        This mirrors _compute_clearing_due_amount() in routes.py and is more
        reliable than SettlementLine-only approach when legacy settlements exist
        (SBT records without matching SettlementLine entries).
        """
        ip_in = (
            db.session.query(func.coalesce(func.sum(InvoicePayment.amount), 0.0))
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(PaymentMethod.default_safe_box_id == safe_box_id)
            .scalar()
        ) or 0.0

        voucher_out = (
            db.session.query(func.coalesce(func.sum(SafeBoxTransaction.amount_cash), 0.0))
            .filter(
                SafeBoxTransaction.safe_box_id == safe_box_id,
                SafeBoxTransaction.ref_type == 'voucher',
                SafeBoxTransaction.direction == 'out',
            )
            .scalar()
        ) or 0.0

        return round(float(ip_in) - float(voucher_out), 2)

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

    def _compute_fee_amount_with_count(self, *, pm, gross_amount: float, transaction_count: int) -> tuple[float, int]:
        """Compute fee using the given transaction_count (for day-level settlement)."""
        timing = str(getattr(pm, 'commission_timing', 'invoice') or 'invoice').strip().lower()
        if timing != 'settlement':
            return 0.0, 0

        rate = float(getattr(pm, 'commission_rate', 0.0) or 0.0)
        fixed = float(getattr(pm, 'commission_fixed_amount', 0.0) or 0.0)
        if rate <= 0.0 and fixed <= 0.0:
            return 0.0, 0

        effective_count = transaction_count if transaction_count > 0 else 1
        fee_amount = round((gross_amount * rate / 100.0) + (fixed * effective_count), 2)
        return fee_amount, transaction_count

    # ------------------------------------------------------------------
    # Last-settlement date detection
    # ------------------------------------------------------------------
    def _last_settlement_date_for_safe_box(self, safe_box_id: int) -> date | None:
        """Return the date of the most recent clearing-settlement voucher for this safe box."""
        last_dt = (
            db.session.query(func.max(Voucher.date))
            .join(SafeBoxTransaction, SafeBoxTransaction.ref_id == Voucher.id)
            .filter(
                SafeBoxTransaction.safe_box_id == safe_box_id,
                SafeBoxTransaction.ref_type.in_(['voucher', 'voucher_reversal']),
                Voucher.reference_type == 'clearing_settlement',
            )
            .scalar()
        )
        if last_dt is None:
            return None
        if isinstance(last_dt, datetime):
            return last_dt.date()
        return last_dt

    # ------------------------------------------------------------------
    # Due amount for a specific day window
    # ------------------------------------------------------------------
    def _compute_due_for_day(self, safe_box_id: int, day_start: datetime, day_end: datetime) -> float:
        """Sum unsettled invoice-payment amounts in the [day_start, day_end] window.

        Uses InvoicePayment as source and subtracts any SettlementLine amounts
        to correctly handle partial settlements.
        """
        ips = (
            InvoicePayment.query
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(
                PaymentMethod.default_safe_box_id == safe_box_id,
                InvoicePayment.created_at >= day_start,
                InvoicePayment.created_at <= day_end,
            )
            .all()
        )
        if not ips:
            return 0.0
        ip_ids = [ip.id for ip in ips]
        settled_by_ip = {}
        if ip_ids:
            rows = (
                db.session.query(
                    SettlementLine.invoice_payment_id,
                    func.coalesce(func.sum(SettlementLine.amount_settled), 0.0),
                )
                .filter(SettlementLine.invoice_payment_id.in_(ip_ids))
                .group_by(SettlementLine.invoice_payment_id)
                .all()
            )
            settled_by_ip = {r[0]: float(r[1]) for r in rows}
        total = 0.0
        for ip in ips:
            ip_amt = float(ip.amount or 0)
            sl_amt = settled_by_ip.get(ip.id, 0.0)
            remaining = ip_amt - sl_amt
            if remaining > 0.005:
                total += remaining
        return round(total, 2)

    def _get_unsettled_ip_ids_for_day(self, safe_box_id: int, day_start: datetime, day_end: datetime) -> list[int]:
        """Return invoice_payment IDs with unsettled balance in the given day window."""
        ips = (
            InvoicePayment.query
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(
                PaymentMethod.default_safe_box_id == safe_box_id,
                InvoicePayment.created_at >= day_start,
                InvoicePayment.created_at <= day_end,
            )
            .all()
        )
        if not ips:
            return []
        ip_ids = [ip.id for ip in ips]
        settled_by_ip = {}
        if ip_ids:
            rows = (
                db.session.query(
                    SettlementLine.invoice_payment_id,
                    func.coalesce(func.sum(SettlementLine.amount_settled), 0.0),
                )
                .filter(SettlementLine.invoice_payment_id.in_(ip_ids))
                .group_by(SettlementLine.invoice_payment_id)
                .all()
            )
            settled_by_ip = {r[0]: float(r[1]) for r in rows}
        result = []
        for ip in ips:
            ip_amt = float(ip.amount or 0)
            sl_amt = settled_by_ip.get(ip.id, 0.0)
            if ip_amt - sl_amt > 0.005:
                result.append(ip.id)
        return result

    def _get_unsettled_ip_ids_up_to(self, safe_box_id: int, cutoff_dt: datetime) -> list[int]:
        """Return all unsettled IP IDs for a safe box up to cutoff_dt."""
        ips = (
            InvoicePayment.query
            .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
            .filter(
                PaymentMethod.default_safe_box_id == safe_box_id,
                InvoicePayment.created_at <= cutoff_dt,
            )
            .all()
        )
        if not ips:
            return []
        ip_ids = [ip.id for ip in ips]
        settled_by_ip = {}
        if ip_ids:
            rows = (
                db.session.query(
                    SettlementLine.invoice_payment_id,
                    func.coalesce(func.sum(SettlementLine.amount_settled), 0.0),
                )
                .filter(SettlementLine.invoice_payment_id.in_(ip_ids))
                .group_by(SettlementLine.invoice_payment_id)
                .all()
            )
            settled_by_ip = {r[0]: float(r[1]) for r in rows}
        result = []
        for ip in ips:
            ip_amt = float(ip.amount or 0)
            sl_amt = settled_by_ip.get(ip.id, 0.0)
            if ip_amt - sl_amt > 0.005:
                result.append(ip.id)
        return result

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

                        # عدد أيام تأخير الإيداع بعد يوم التسوية
                        deposit_delay = int(getattr(pm, 'deposit_delay_days', 0) or 0)
                        if deposit_delay < 0:
                            deposit_delay = 0

                        # يوم التنفيذ الفعلي = (يوم التسوية + أيام التأخير) % 7
                        execution_weekday = (configured_weekday + deposit_delay) % 7
                        if execution_weekday != weekday:
                            _skip(f'not_scheduled_today:execution={execution_weekday},today={weekday}')
                            continue

                        # cutoff = اليوم - أيام التأخير (= يوم التسوية الأصلي)
                        cutoff_days = max(int(pm.settlement_days or 0), 1) + deposit_delay
                    else:
                        schedule_type = 'days'

                    cutoff_date = today - timedelta(days=max(cutoff_days, 0))
                    cutoff_dt = datetime.combine(cutoff_date, time.max)

                    # Check if there are unsettled IPs (SettlementLine-aware)
                    unsettled_ip_ids = self._get_unsettled_ip_ids_up_to(pm.default_safe_box_id, cutoff_dt)
                    if not unsettled_ip_ids:
                        _skip(f'no_unsettled_ips:cutoff={cutoff_dt.date().isoformat()}')
                        continue

                    # Compute total unsettled amount from those IPs
                    _ip_rows = (
                        db.session.query(
                            InvoicePayment.id,
                            InvoicePayment.amount,
                            func.coalesce(func.sum(SettlementLine.amount_settled), 0.0),
                        )
                        .outerjoin(SettlementLine, SettlementLine.invoice_payment_id == InvoicePayment.id)
                        .filter(InvoicePayment.id.in_(unsettled_ip_ids))
                        .group_by(InvoicePayment.id)
                        .all()
                    )
                    gross_amount = round(sum(
                        max(0.0, float(r[1]) - float(r[2])) for r in _ip_rows
                    ), 2)

                    # Nothing due
                    if gross_amount < 0.01:
                        _skip(f'due_amount_zero_sl:cutoff={cutoff_dt.date().isoformat()}')
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

                    # ================================================================
                    # تسوية أسبوعية (weekday): سند واحد مجمّع لكل دفعات الأسبوع
                    # ================================================================
                    if schedule_type == 'weekday':
                        if gross_amount > clearing_balance:
                            gross_amount = round(clearing_balance, 2)
                        if gross_amount < 0.01:
                            _skip('gross_after_cap_zero')
                            continue
                        # Cap to SBT-based due to avoid exceeds_due_amount errors
                        # caused by SettlementLine vs SBT accounting discrepancies
                        sbt_due = self._compute_sbt_based_due(clearing_sb.id)
                        if gross_amount > sbt_due + 0.01:
                            gross_amount = round(min(gross_amount, max(sbt_due, 0.0)), 2)
                        if gross_amount < 0.01:
                            _skip('gross_after_sbt_cap_zero')
                            continue

                        reference_number = f"AUTO-PM-{pm.id}-W-{today.isoformat()}"

                        # Collect all unsettled IP IDs up to cutoff for this safe box
                        weekly_ip_ids = self._get_unsettled_ip_ids_up_to(clearing_sb.id, cutoff_dt)

                        fee_amount, fee_tx_count = self._compute_fee_amount_with_count(
                            pm=pm,
                            gross_amount=gross_amount,
                            transaction_count=len(weekly_ip_ids),
                        )
                        if fee_amount >= gross_amount:
                            _skip(f'fee_exceeds_gross:{fee_amount:.2f}>={gross_amount:.2f}')
                            continue

                        _bulk_net = round(gross_amount - fee_amount, 2)
                        description = (
                            f"تسوية أسبوعية تلقائية: {pm.name} "
                            f"({clearing_sb.name} → {bank_sb.name}) "
                            f"(إجمالي {gross_amount:.2f}، عمولة {fee_amount:.2f}، صافي {_bulk_net:.2f})"
                        )

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
                                notes='auto_settlement:weekly',
                                ensure_unique_reference=True,
                                invoice_payment_ids=weekly_ip_ids if weekly_ip_ids else None,
                            )
                            if voucher_result.get('skipped'):
                                db.session.rollback()
                                _skip('duplicate_reference_skipped')
                                continue

                            db.session.commit()
                            result['settled_count'] += 1
                            print(
                                f"[ClearingSettlementScheduler] ✓ Weekly settled {gross_amount:.2f}"
                                f" (fee {fee_amount:.2f}) for PM#{pm.id} ({pm.name})"
                            )
                        except Exception as exc:
                            db.session.rollback()
                            print(f"[ClearingSettlementScheduler] ❌ Failed PM#{pm.id} ({pm.name}): {exc}")
                            _skip(f'voucher_creation_error:{str(exc)[:120]}')
                        continue

                    # ================================================================
                    # تسوية يومية (days): يوم بيوم عند التأخير
                    # ================================================================
                    # نبدأ من أقدم عملية غير مسوّاة (بدل last_settlement + 1)
                    # هذا يضمن التقاط العمليات القديمة التي لم تشملها تسويات سابقة
                    _unsettled_sub = (
                        db.session.query(
                            InvoicePayment.id,
                            InvoicePayment.created_at,
                        )
                        .join(PaymentMethod, PaymentMethod.id == InvoicePayment.payment_method_id)
                        .outerjoin(SettlementLine, SettlementLine.invoice_payment_id == InvoicePayment.id)
                        .filter(PaymentMethod.default_safe_box_id == clearing_sb.id)
                        .group_by(InvoicePayment.id)
                        .having(
                            InvoicePayment.amount - func.coalesce(func.sum(SettlementLine.amount_settled), 0.0) > 0.005
                        )
                        .subquery()
                    )
                    oldest_unsettled_ip = (
                        db.session.query(func.min(_unsettled_sub.c.created_at)).scalar()
                    )

                    if oldest_unsettled_ip:
                        if isinstance(oldest_unsettled_ip, datetime):
                            range_start = oldest_unsettled_ip.date()
                        elif isinstance(oldest_unsettled_ip, str):
                            range_start = date.fromisoformat(oldest_unsettled_ip[:10])
                        else:
                            range_start = oldest_unsettled_ip
                    else:
                        range_start = cutoff_date + timedelta(days=1)  # nothing unsettled

                    # لا نسوي أيام بعد cutoff_date
                    if range_start > cutoff_date:
                        _skip(f'no_days_due:range_start={range_start.isoformat()},cutoff={cutoff_date.isoformat()}')
                        continue

                    # بناء قائمة الأيام المستحقة
                    due_days = []
                    d = range_start
                    while d <= cutoff_date:
                        due_days.append(d)
                        d += timedelta(days=1)

                    if not due_days:
                        _skip('no_due_days')
                        continue

                    # محاولة التسوية لكل يوم (cap بالرصيد المتاح وبالمستحق الفعلي)
                    running_balance = clearing_balance
                    # Track SBT-based remaining due to prevent exceeds_due_amount errors.
                    # SettlementLine may be missing legacy settlement records that only
                    # exist as SBT voucher_out rows, causing _compute_due_for_day to
                    # overestimate the day amount vs what _create_clearing_settlement_voucher allows.
                    running_sbt_due = self._compute_sbt_based_due(clearing_sb.id)
                    days_settled = 0

                    for settle_day in due_days:
                        if running_sbt_due < 0.01:
                            break  # nothing left to settle per SBT accounting

                        day_start = datetime.combine(settle_day, time.min)
                        day_end = datetime.combine(settle_day, time.max)

                        day_amount = self._compute_due_for_day(clearing_sb.id, day_start, day_end)
                        if day_amount < 0.01:
                            continue

                        # فحص الحد الأدنى
                        if min_settle > 0.01 and day_amount < min_settle:
                            continue

                        # cap بالرصيد المتبقي
                        if day_amount > running_balance:
                            day_amount = round(running_balance, 2)
                        if day_amount < 0.01:
                            break  # الرصيد نفد

                        # Cap to SBT-based remaining due (handles legacy settlements
                        # missing from SettlementLine, preventing exceeds_due_amount)
                        if day_amount > running_sbt_due + 0.01:
                            day_amount = round(min(day_amount, running_sbt_due), 2)
                        if day_amount < 0.01:
                            break

                        reference_number = f"AUTO-PM-{pm.id}-{settle_day.isoformat()}"

                        # Collect unsettled IP IDs for this day (for SettlementLine creation)
                        day_ip_ids = self._get_unsettled_ip_ids_for_day(clearing_sb.id, day_start, day_end)

                        fee_amount_day, fee_tx_count = self._compute_fee_amount_with_count(
                            pm=pm,
                            gross_amount=day_amount,
                            transaction_count=len(day_ip_ids),
                        )
                        if fee_amount_day >= day_amount:
                            continue

                        _day_net = round(day_amount - fee_amount_day, 2)
                        description = (
                            f"تسوية تلقائية لمستحقات التحصيل: {pm.name} "
                            f"({clearing_sb.name} → {bank_sb.name}) "
                            f"يوم {settle_day.isoformat()} "
                            f"(إجمالي {day_amount:.2f}، عمولة {fee_amount_day:.2f}، صافي {_day_net:.2f})"
                        )

                        try:
                            voucher_result = _create_clearing_settlement_voucher(
                                clearing_safe_box_id=clearing_sb.id,
                                bank_safe_box_id=bank_sb.id,
                                gross_amount=day_amount,
                                fee_amount=fee_amount_day,
                                settlement_dt=datetime.combine(settle_day, time(12, 0)),
                                reference_number=reference_number,
                                created_by='scheduler',
                                fee_account_id=getattr(pm, 'fee_expense_account_id', None),
                                description_override=description,
                                notes=f'auto_settlement:day={settle_day.isoformat()}',
                                ensure_unique_reference=True,
                                invoice_payment_ids=day_ip_ids if day_ip_ids else None,
                            )
                            if voucher_result.get('skipped'):
                                continue

                            db.session.commit()
                            running_balance -= day_amount
                            running_sbt_due -= day_amount
                            days_settled += 1
                            result['settled_count'] += 1
                            print(
                                f"[ClearingSettlementScheduler] ✓ Settled {day_amount:.2f}"
                                f" (fee {fee_amount_day:.2f}) for PM#{pm.id} ({pm.name})"
                                f" day={settle_day.isoformat()}"
                            )
                        except Exception as exc:
                            db.session.rollback()
                            print(
                                f"[ClearingSettlementScheduler] ❌ Failed PM#{pm.id} ({pm.name})"
                                f" day={settle_day.isoformat()}: {exc}"
                            )

                    if days_settled == 0:
                        _skip(f'no_days_had_due_amount:range={range_start.isoformat()}..{cutoff_date.isoformat()}')

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

        # 2. Detect already-settled payment ids via SettlementLine + legacy notes
        settled_ip_ids: set[int] = set()
        # Check SettlementLine (fully settled IPs)
        try:
            all_ip_ids = [tx.invoice_payment_id for tx in unsettled_txs if tx.invoice_payment_id]
            if all_ip_ids:
                sl_rows = (
                    db.session.query(
                        SettlementLine.invoice_payment_id,
                        func.coalesce(func.sum(SettlementLine.amount_settled), 0.0),
                    )
                    .filter(SettlementLine.invoice_payment_id.in_(all_ip_ids))
                    .group_by(SettlementLine.invoice_payment_id)
                    .all()
                )
                # Build map of ip_id → amount for partial check
                ip_amount_map = {tx.invoice_payment_id: float(tx.amount_cash or 0) for tx in unsettled_txs if tx.invoice_payment_id}
                for ip_id, sl_total in sl_rows:
                    ip_amt = ip_amount_map.get(ip_id, 0)
                    if float(sl_total) >= ip_amt - 0.005:
                        settled_ip_ids.add(ip_id)
        except Exception:
            pass
        # Also check legacy per_tx notes
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

            _pertx_net = round(gross - fee, 2)
            desc = (
                f'تسوية فردية تلقائية: {clearing_sb.name} → {bank_sb.name}'
                f'{inv_info} '
                f'(إجمالي {gross:.2f}، عمولة {fee:.2f}، صافي {_pertx_net:.2f})'
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
                    invoice_payment_ids=[ip_id] if ip_id else None,
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
        # Run every 2 hours so settlements happen throughout the day,
        # not just once at 04:10.  The process_due_settlements() method
        # is idempotent (duplicate_reference guard + SettlementLine tracking),
        # so running more often is safe.
        self._scheduler.every(2).hours.do(self.process_due_settlements)
        print('[ClearingSettlementScheduler] ✓ Auto settlement scheduled every 2 hours')

    def start(self):
        if self.is_running:
            print('[ClearingSettlementScheduler] already running')
            return

        self.setup_schedule()
        self.is_running = True

        def run_scheduler():
            # Run once immediately on startup so we don't wait 2 hours
            # after a container restart / deployment.
            try:
                self.process_due_settlements()
            except Exception as exc:
                print(f'[ClearingSettlementScheduler] ⚠ initial run failed: {exc}')

            while self.is_running:
                self._scheduler.run_pending()
                # Check every minute
                import time as _time

                _time.sleep(60)

        thread = Thread(target=run_scheduler, daemon=True)
        thread.start()
        print('[ClearingSettlementScheduler] 🚀 started')

    def stop(self):
        self.is_running = False
        self._scheduler.clear()
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
