"""
نظام التحكم بالترحيل (Posting Control System)
================================================

هذا الملف يوفر endpoints للتحكم بترحيل الفواتير والقيود:

1. ترحيل فاتورة واحدة أو مجموعة
2. إلغاء ترحيل فاتورة
3. ترحيل قيد واحد أو مجموعة
4. إلغاء ترحيل قيد
5. عرض الفواتير/القيود غير المرحلة

الاستخدام:
-----------
from posting_routes import posting_bp
app.register_blueprint(posting_bp, url_prefix='/api')
"""

from __future__ import annotations

from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
from models import (
    db,
    Invoice,
    InvoicePayment,
    JournalEntry,
    JournalEntryLine,
    Account,
    Customer,
    Supplier,
    AuditLog,
    Settings,
    SystemAlert,
    PaymentType,
    PaymentMethod,
    Employee,
    SafeBox,
    SafeBoxTransaction,
)
from sqlalchemy import func, case, or_, and_
import json
from auth_decorators import require_permission, optional_auth

posting_bp = Blueprint('posting', __name__)


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _main_karat_value() -> float:
    settings_row = _get_settings_row()
    try:
        main_karat = _to_float(getattr(settings_row, 'main_karat', None), 21.0)
    except Exception:
        main_karat = 21.0
    return main_karat if main_karat > 0 else 21.0


def _convert_to_main_karat(weight: float, karat: float, main_karat: float) -> float:
    w = _to_float(weight, 0.0)
    k = _to_float(karat, 0.0)
    mk = _to_float(main_karat, 21.0)
    if w == 0.0 or k == 0.0 or mk == 0.0:
        return 0.0
    return (w * k) / mk


def _journal_entry_gold_totals_main_karat(entry: JournalEntry) -> tuple[float, float, float, float]:
    """Return (main_karat, debit_main, credit_main, diff_main) for a journal entry."""
    main_karat = _main_karat_value()
    debit_main = 0.0
    credit_main = 0.0
    for line in (entry.lines or []):
        if getattr(line, 'is_deleted', False):
            continue
        debit_main += (
            _convert_to_main_karat(getattr(line, 'debit_18k', 0) or 0, 18, main_karat)
            + _convert_to_main_karat(getattr(line, 'debit_21k', 0) or 0, 21, main_karat)
            + _convert_to_main_karat(getattr(line, 'debit_22k', 0) or 0, 22, main_karat)
            + _convert_to_main_karat(getattr(line, 'debit_24k', 0) or 0, 24, main_karat)
        )
        credit_main += (
            _convert_to_main_karat(getattr(line, 'credit_18k', 0) or 0, 18, main_karat)
            + _convert_to_main_karat(getattr(line, 'credit_21k', 0) or 0, 21, main_karat)
            + _convert_to_main_karat(getattr(line, 'credit_22k', 0) or 0, 22, main_karat)
            + _convert_to_main_karat(getattr(line, 'credit_24k', 0) or 0, 24, main_karat)
        )

    diff_main = debit_main - credit_main
    return main_karat, debit_main, credit_main, diff_main


def _journal_entry_posting_summary(entry: JournalEntry) -> dict:
    """Compute compact summary for posting screen lists."""
    cash_debit = 0.0
    cash_credit = 0.0
    line_count = 0

    for line in (getattr(entry, 'lines', None) or []):
        if getattr(line, 'is_deleted', False):
            continue
        line_count += 1
        cash_debit += _to_float(getattr(line, 'cash_debit', 0.0), 0.0)
        cash_credit += _to_float(getattr(line, 'cash_credit', 0.0), 0.0)

    main_karat, debit_main, credit_main, diff_main = _journal_entry_gold_totals_main_karat(entry)
    cash_diff = cash_debit - cash_credit

    return {
        'lines_count': int(line_count),
        'cash_debit_total': round(float(cash_debit), 6),
        'cash_credit_total': round(float(cash_credit), 6),
        'cash_diff': round(float(cash_diff), 6),
        'cash_balanced': abs(cash_diff) <= 0.01,
        'main_karat': int(round(float(main_karat))),
        'gold_debit_main_karat': round(float(debit_main), 6),
        'gold_credit_main_karat': round(float(credit_main), 6),
        'gold_diff_main_karat': round(float(diff_main), 6),
        'gold_balanced_main_karat': abs(diff_main) <= 0.01,
    }


# ==========================================
# 🧾 إغلاق اليومية (Shift Closing)
# ==========================================


def _direction_for_invoice_gold(invoice_type: str) -> str:
    """Map invoice type to gold movement direction (in/out)."""
    t = (invoice_type or '').strip()
    if 'مورد' in t and 'شراء' in t:
        if 'مرتجع' in t:
            t = 'مرتجع شراء (مورد)'
        else:
            t = 'شراء'
    if t == 'بيع':
        return 'out'
    if t == 'مرتجع بيع':
        return 'in'
    if t in ('شراء من عميل', 'شراء'):
        return 'in'
    if t in ('مرتجع شراء', 'مرتجع شراء (مورد)'):
        return 'out'
    # Default: no-op direction is safer as 'out'/'in' both change inventory;
    # but we only create rows when weights exist, so choose 'out' only for explicit sale.
    return 'in'


def _get_settings_row() -> Settings | None:
    try:
        return Settings.query.first()
    except Exception:
        return None


def _resolve_employee_for_invoice(invoice: Invoice, for_scrap_purchase: bool = False) -> Employee | None:
    if not invoice:
        return None

    # For scrap purchases, prefer explicit scrap holder.
    if for_scrap_purchase:
        try:
            holder_id = getattr(invoice, 'scrap_holder_employee_id', None)
            if holder_id not in (None, '', False):
                try:
                    holder_id = int(holder_id)
                except Exception:
                    holder_id = None
            if holder_id:
                return Employee.query.get(holder_id)
        except Exception:
            pass

    # Fallback: invoice.employee
    try:
        emp = getattr(invoice, 'employee', None)
        if emp and getattr(emp, 'id', None):
            return emp
    except Exception:
        pass

    try:
        emp_id = getattr(invoice, 'employee_id', None)
        if emp_id not in (None, '', False):
            return Employee.query.get(int(emp_id))
    except Exception:
        pass

    return None


def _direction_for_invoice_cash(invoice_type: str) -> str:
    """Map invoice type to cash direction: 'in' (cash received) or 'out' (cash paid)."""
    t = (invoice_type or '').strip()
    if t == 'بيع':
        return 'in'
    if t == 'مرتجع بيع':
        return 'out'
    if t in ('شراء من عميل', 'شراء') or ('شراء' in t and 'مورد' in t and 'مرتجع' not in t):
        return 'out'
    if t in ('مرتجع شراء', 'مرتجع شراء (مورد)') or ('مرتجع' in t and 'شراء' in t and 'مورد' in t):
        return 'in'
    return 'in'


def _is_receivable_pm(pm) -> bool:
    try:
        return str(getattr(pm, 'payment_type', '') or '').strip().lower() == 'receivable'
    except Exception:
        return False


def _create_deferred_payment_entries(invoice: Invoice, posted_by: str) -> None:
    """
    عند ترحيل فاتورة كانت محفوظة بوضع 'غير مرحّلة' (unposted_mode):

    المشكلة:
      قيد الفاتورة يُمدن ذمم العميل (AR) ← ويبقى معلقاً حتى يُسوَّى.
      لكن عند الحفظ كمسودة لا يُنشأ سند ولا SafeBoxTransaction.
      فعند الترحيل لاحقاً: ذمم العميل تظل مدينة والنقد لا يدخل الخزينة!

    الحل:
      لكل InvoicePayment لم تُسجَّل SafeBoxTransaction خاصة بها بعد:
        1. ننشئ SafeBoxTransaction (لرصيد الخزينة في لوحة التحكم)
        2. ننشئ JournalEntry:
             مدين خزينة / دائن ذمم العميل   (للبيع - cash in)
             مدين ذمم المورد / دائن خزينة   (للشراء - cash out)
      → ذمم العميل/المورد تصفر تلقائياً.
    """
    payments = list(getattr(invoice, 'payments', []) or [])
    if not payments:
        return

    direction = _direction_for_invoice_cash(getattr(invoice, 'invoice_type', None))

    # حساب الطرف (ذمم العميل أو المورد)
    party_account_id = None
    try:
        cust_id = getattr(invoice, 'customer_id', None)
        supp_id = getattr(invoice, 'supplier_id', None)
        if cust_id:
            c = Customer.query.get(int(cust_id))
            party_account_id = int(c.account_id) if (c and c.account_id) else None
        elif supp_id:
            s = Supplier.query.get(int(supp_id))
            party_account_id = int(s.account_id) if (s and s.account_id) else None
    except Exception:
        pass

    for pay in payments:
        try:
            pay_id = int(getattr(pay, 'id', 0) or 0)
        except Exception:
            pay_id = 0
        if pay_id <= 0:
            continue

        # Idempotency (prevent duplicates): handle legacy rows too.
        # A payment may have been recorded via voucher flow (receipt/payment voucher),
        # or via legacy deferred-payment recovery (ref_type=invoice_payment).
        # - Prefer invoice_payment_id when present.
        # - Fall back to ref_type/ref_id for older rows.
        existing_safe_tx = (
            SafeBoxTransaction.query
            .filter(
                or_(
                    SafeBoxTransaction.invoice_payment_id == pay_id,
                    and_(
                        SafeBoxTransaction.ref_type == 'invoice_payment',
                        SafeBoxTransaction.invoice_payment_id.is_(None),
                        SafeBoxTransaction.ref_id == pay_id,
                    ),
                )
            )
            .first()
        )

        # JournalEntry idempotency:
        # - New format uses reference_type='invoice_payment' and reference_id=pay_id
        # - Older formats used entry_number prefix DEF-{invoice_id}-{pay_id}-...
        existing_je = (
            JournalEntry.query
            .filter(JournalEntry.is_deleted == False)
            .filter(
                or_(
                    and_(JournalEntry.reference_type == 'invoice_payment', JournalEntry.reference_id == pay_id),
                    JournalEntry.entry_number.like(f'PAY-{invoice.id}-{pay_id}-%'),
                    JournalEntry.entry_number.like(f'DEF-{invoice.id}-{pay_id}-%'),
                )
            )
            .first()
        )

        # Voucher-based payments create a JournalEntry with reference_type='voucher'.
        # Those entries are legitimate and should prevent creating a duplicate
        # deferred-payment recovery entry.
        try:
            from models import Voucher

            # Prefer explicit note linkage when available; otherwise fall back
            # to (invoice_id + amount) which is stable in many legacy DBs.
            note_like = or_(
                Voucher.notes.like(f'%\"invoice_payment_id\": {pay_id}%'),
                Voucher.notes.like(f'%\"invoice_payment_id\":{pay_id}%'),
                Voucher.notes.like(f'%\"invoice_payment_id\"%{pay_id}%'),
            )

            voucher_filters = [
                Voucher.reference_type == 'invoice',
                Voucher.reference_id == int(invoice.id),
                # Some DBs support soft-delete semantics via voucher status.
                Voucher.status != 'cancelled',
            ]
            # Best-effort: if the Voucher model has an is_deleted column (some installs),
            # respect it.
            try:
                if hasattr(Voucher, 'is_deleted'):
                    voucher_filters.append(Voucher.is_deleted == False)
            except Exception:
                pass

            voucher_for_payment = (
                Voucher.query
                .filter(
                    *voucher_filters,
                    or_(
                        note_like,
                        and_(
                            Voucher.amount_cash.isnot(None),
                            func.abs(func.coalesce(Voucher.amount_cash, 0.0) - float(getattr(pay, 'amount', 0.0) or 0.0)) < 0.01,
                        ),
                    ),
                )
                .order_by(Voucher.id.desc())
                .first()
            )
            if voucher_for_payment and getattr(voucher_for_payment, 'journal_entry_id', None):
                voucher_je_id = int(voucher_for_payment.journal_entry_id)
                voucher_je = (
                    JournalEntry.query
                    .filter(JournalEntry.is_deleted == False)
                    .filter(JournalEntry.id == voucher_je_id)
                    .first()
                )
                if voucher_je is not None:
                    existing_je = existing_je or voucher_je
        except Exception:
            pass

        # If both artifacts exist, nothing to do.
        if existing_safe_tx and existing_je:
            continue

        pm_obj = None
        try:
            pm_id = getattr(pay, 'payment_method_id', None)
            if pm_id not in (None, '', False):
                pm_obj = PaymentMethod.query.get(int(pm_id))
        except Exception:
            pass

        if _is_receivable_pm(pm_obj):
            continue  # دفع آجل: لا حركة خزينة

        # استرجاع safe_box_id المحفوظ مسبقاً في حقل notes أو invoice
        explicit_safe_box_id = None
        notes_user = None
        try:
            raw_notes = getattr(pay, 'notes', None)
            if raw_notes:
                decoded = json.loads(raw_notes)
                if isinstance(decoded, dict):
                    notes_user = decoded.get('user_notes')
                    raw_sb = decoded.get('safe_box_id')
                    if raw_sb not in (None, '', 0, '0', False):
                        explicit_safe_box_id = int(raw_sb)
        except Exception:
            notes_user = getattr(pay, 'notes', None)

        # If we already have a safe transaction, trust its safe_box_id.
        safe_box_id = None
        if existing_safe_tx and getattr(existing_safe_tx, 'safe_box_id', None):
            try:
                safe_box_id = int(existing_safe_tx.safe_box_id)
            except Exception:
                safe_box_id = None

        safe_box_id = safe_box_id or _resolve_cash_safe_box_id_for_invoice(
            invoice=invoice,
            pm_obj=pm_obj,
            explicit_safe_box_id=explicit_safe_box_id,
        )
        if safe_box_id is None:
            print(f'[deferred_payment] تحذير: تعذر إيجاد خزينة لدفعة #{pay_id} في الفاتورة #{invoice.id}')
            continue

        sb = SafeBox.query.get(int(safe_box_id))
        if not sb:
            print(f'[deferred_payment] تحذير: الخزينة {safe_box_id} غير موجودة - دفعة #{pay_id}')
            continue

        # Use existing safe tx amount if present (supports partial recovery).
        try:
            if existing_safe_tx is not None:
                amount_cash = float(getattr(existing_safe_tx, 'amount_cash', 0.0) or 0.0)
            else:
                amount_cash = float(getattr(pay, 'amount', 0.0) or 0.0)
        except Exception:
            amount_cash = 0.0

        if amount_cash <= 0:
            continue

        # 1) SafeBoxTransaction (create only if missing)
        if existing_safe_tx is None:
            db.session.add(SafeBoxTransaction(
                safe_box_id=int(safe_box_id),
                ref_type='invoice_payment',
                ref_id=pay_id,
                invoice_id=invoice.id,
                invoice_payment_id=pay_id,
                payment_method_id=getattr(pay, 'payment_method_id', None),
                direction=direction,
                amount_cash=amount_cash,
                notes=notes_user,
                created_by=posted_by,
            ))

        # 2) JournalEntry: مدين خزينة / دائن ذمم -- أو العكس للشراء
        safe_account_id = getattr(sb, 'account_id', None)
        if not safe_account_id:
            print(f'[deferred_payment] تحذير: الخزينة {safe_box_id} لا تحتوي على account_id - لن يُنشأ قيد')
            continue

        # Extra idempotency for legacy data:
        # If the invoice already has a posted journal entry (reference_type='invoice')
        # that already hit the same safe account with the same cash amount,
        # do NOT create a duplicate deferred-payment JE.
        #
        # This covers legacy queued/unposted invoices where the invoice JE was
        # originally built to debit/credit the SafeBox directly; when those
        # invoices are posted later, we should not add a second cash movement.
        try:
            safe_account_id_int = int(safe_account_id)
        except Exception:
            safe_account_id_int = None

        try:
            if safe_account_id_int and amount_cash > 0:
                eps = 0.01
                if direction == 'in':
                    safe_amt_cond = func.abs(func.coalesce(JournalEntryLine.cash_debit, 0.0) - float(amount_cash)) < eps
                else:
                    safe_amt_cond = func.abs(func.coalesce(JournalEntryLine.cash_credit, 0.0) - float(amount_cash)) < eps

                # 1) Safe-only check (legacy cash invoices)
                invoice_cash_je = (
                    JournalEntry.query
                    .join(JournalEntryLine, JournalEntryLine.journal_entry_id == JournalEntry.id)
                    .filter(JournalEntry.is_deleted == False)
                    .filter(JournalEntryLine.is_deleted == False)
                    .filter(JournalEntry.reference_type == 'invoice', JournalEntry.reference_id == int(invoice.id))
                    .filter(JournalEntryLine.account_id == safe_account_id_int)
                    .filter(safe_amt_cond)
                    .first()
                )
                if invoice_cash_je is not None:
                    existing_je = existing_je or invoice_cash_je

                # 2) Safe + party check (newer behavior, keep as a refinement)
                if existing_je is None:
                    credit_acc = party_account_id or safe_account_id_int
                    if credit_acc:
                        if direction == 'in':
                            party_amt_cond = func.abs(func.coalesce(JournalEntryLine.cash_credit, 0.0) - float(amount_cash)) < eps
                        else:
                            party_amt_cond = func.abs(func.coalesce(JournalEntryLine.cash_debit, 0.0) - float(amount_cash)) < eps

                        invoice_cash_je_2 = (
                            JournalEntry.query
                            .join(JournalEntryLine, JournalEntryLine.journal_entry_id == JournalEntry.id)
                            .filter(JournalEntry.is_deleted == False)
                            .filter(JournalEntryLine.is_deleted == False)
                            .filter(JournalEntry.reference_type == 'invoice', JournalEntry.reference_id == int(invoice.id))
                            .filter(JournalEntryLine.account_id == safe_account_id_int)
                            .filter(safe_amt_cond)
                            .filter(
                                JournalEntry.lines.any(
                                    and_(
                                        JournalEntryLine.is_deleted == False,
                                        JournalEntryLine.account_id == int(credit_acc),
                                        party_amt_cond,
                                    )
                                )
                            )
                            .first()
                        )
                        if invoice_cash_je_2 is not None:
                            existing_je = existing_je or invoice_cash_je_2
        except Exception:
            pass

        # 2) JournalEntry (create only if missing)
        if existing_je is None:
            ts = datetime.now().strftime('%Y%m%d%H%M%S')
            # NOTE: This journal entry represents posting a previously persisted invoice payment
            # for an unposted/approval-gated invoice. It is not a credit (آجل) invoice payment.
            entry_number = f'PAY-{invoice.id}-{pay_id}-{ts}'
            je = JournalEntry(
                entry_number=entry_number,
                date=getattr(invoice, 'date', None) or datetime.now(),
                description=(
                    f'ترحيل دفعة فاتورة - فاتورة #{getattr(invoice, "invoice_number", None) or invoice.id}'
                ),
                reference_type='invoice_payment',
                reference_id=pay_id,
                reference_number=(getattr(invoice, 'invoice_number', None) or str(getattr(invoice, 'id', '') or '')),
                is_posted=True,
                posted_at=datetime.now(),
                posted_by=posted_by,
                created_by=posted_by,
            )
            db.session.add(je)
            db.session.flush()

            if direction == 'in':
                # بيع: مدين خزينة ← دائن ذمم عميل
                db.session.add(JournalEntryLine(
                    journal_entry_id=je.id,
                    account_id=int(safe_account_id),
                    cash_debit=amount_cash,
                    description=f'استلام نقد - دفعة #{pay_id}',
                ))
                credit_acc = party_account_id or int(safe_account_id)
                db.session.add(JournalEntryLine(
                    journal_entry_id=je.id,
                    account_id=credit_acc,
                    cash_credit=amount_cash,
                    description=f'تسوية ذمم عميل - دفعة #{pay_id}',
                ))
            else:
                # شراء: مدين ذمم مورد ← دائن خزينة
                debit_acc = party_account_id or int(safe_account_id)
                db.session.add(JournalEntryLine(
                    journal_entry_id=je.id,
                    account_id=debit_acc,
                    cash_debit=amount_cash,
                    description=f'تسوية ذمم مورد - دفعة #{pay_id}',
                ))
                db.session.add(JournalEntryLine(
                    journal_entry_id=je.id,
                    account_id=int(safe_account_id),
                    cash_credit=amount_cash,
                    description=f'صرف نقد - دفعة #{pay_id}',
                ))


def _resolve_cash_safe_box_id_for_invoice(
    *,
    invoice: Invoice,
    pm_obj: PaymentMethod | None = None,
    explicit_safe_box_id: int | None = None,
) -> int | None:
    """Resolve cash SafeBox for invoice payments.

    Precedence:
    1) explicit_safe_box_id
    2) invoice.safe_box_id
    3) employee cash safe (if enabled AND payment method is cash)
    4) payment_method.default_safe_box_id
    5) settings.main_cash_safe_box_id
    6) default cash safe
    """
    if explicit_safe_box_id:
        return int(explicit_safe_box_id)

    try:
        inv_sb = getattr(invoice, 'safe_box_id', None)
        if inv_sb not in (None, '', 0, '0', False):
            return int(inv_sb)
    except Exception:
        pass

    settings_row = _get_settings_row()
    emp = _resolve_employee_for_invoice(invoice, for_scrap_purchase=False)

    def _is_cash_payment_method(pm: PaymentMethod | None) -> bool:
        if pm is None:
            return False
        try:
            pt = str(getattr(pm, 'payment_type', '') or '').strip().lower()
            name = str(getattr(pm, 'name', '') or '').strip()
            if pt in {'cash'}:
                return True
            # Backward-compat: infer from Arabic naming.
            return 'نقد' in name
        except Exception:
            return False

    if bool(getattr(settings_row, 'employee_cash_safes_enabled', False)) and _is_cash_payment_method(pm_obj):
        try:
            emp_cash = getattr(emp, 'cash_safe_box_id', None) if emp else None
            if emp_cash not in (None, '', 0, '0', False):
                return int(emp_cash)
        except Exception:
            pass

    if pm_obj is not None:
        try:
            pm_sb = getattr(pm_obj, 'default_safe_box_id', None)
            if pm_sb not in (None, '', 0, '0', False):
                return int(pm_sb)
        except Exception:
            pass

    try:
        main_cash = getattr(settings_row, 'main_cash_safe_box_id', None) if settings_row else None
        if main_cash not in (None, '', 0, '0', False):
            return int(main_cash)
    except Exception:
        pass

    try:
        sb = SafeBox.get_default_by_type('cash')
        if sb and sb.id:
            return int(sb.id)
    except Exception:
        pass

    return None


def _resolve_gold_safe_for_invoice(invoice: Invoice, karat: int) -> SafeBox | None:
    """Resolve gold SafeBox for invoice gold movements.

    Rules requested:
    - Sale (new): use the configured sale gold safe (ذهب مشغول معروض للبيع)
    - Sale (scrap): use main scrap safe (صندوق الكسر الرئيسي)
    - Customer scrap purchase: use employee gold safe if enabled, else main scrap safe
    - Otherwise: fallback to sale gold safe, then default gold safe
    """
    settings_row = _get_settings_row()
    invoice_type = (getattr(invoice, 'invoice_type', None) or '').strip()
    gold_type = (str(getattr(invoice, 'gold_type', '') or '').strip().lower() or 'new')

    is_customer_scrap_purchase = (invoice_type == 'شراء من عميل' and gold_type == 'scrap')
    is_scrap_sale = (invoice_type in ('بيع', 'مرتجع بيع') and gold_type == 'scrap')

    # Allow explicit invoice.safe_box_id override for gold if it points to an active gold safe.
    try:
        inv_sb_id = getattr(invoice, 'safe_box_id', None)
        if inv_sb_id not in (None, '', 0, '0', False):
            sb = SafeBox.query.get(int(inv_sb_id))
            if sb and (sb.safe_type or '').lower() == 'gold' and bool(getattr(sb, 'is_active', True)):
                return sb
    except Exception:
        pass

    # Scrap sale: debit/credit gold inventory should hit main scrap safe (not "sale" safe).
    if is_scrap_sale:
        try:
            scrap_sb_id = getattr(settings_row, 'main_scrap_gold_safe_box_id', None) if settings_row else None
            if scrap_sb_id not in (None, '', 0, '0', False):
                sb = SafeBox.query.get(int(scrap_sb_id))
                if sb and bool(getattr(sb, 'is_active', True)):
                    return sb
        except Exception:
            pass

    if invoice_type == 'بيع' or invoice_type == 'مرتجع بيع':
        try:
            sale_sb_id = getattr(settings_row, 'sale_gold_safe_box_id', None) if settings_row else None
            if sale_sb_id not in (None, '', 0, '0', False):
                sb = SafeBox.query.get(int(sale_sb_id))
                if sb and bool(getattr(sb, 'is_active', True)):
                    return sb
        except Exception:
            pass

    if is_customer_scrap_purchase:
        emp = _resolve_employee_for_invoice(invoice, for_scrap_purchase=True)
        if bool(getattr(settings_row, 'employee_gold_safes_enabled', False)):
            try:
                emp_gold = getattr(emp, 'gold_safe_box_id', None) if emp else None
                if emp_gold not in (None, '', 0, '0', False):
                    sb = SafeBox.query.get(int(emp_gold))
                    if sb and bool(getattr(sb, 'is_active', True)):
                        return sb
            except Exception:
                pass

        try:
            scrap_sb_id = getattr(settings_row, 'main_scrap_gold_safe_box_id', None) if settings_row else None
            if scrap_sb_id not in (None, '', 0, '0', False):
                sb = SafeBox.query.get(int(scrap_sb_id))
                if sb and bool(getattr(sb, 'is_active', True)):
                    return sb
        except Exception:
            pass

    # Default: try configured sale gold safe
    try:
        sale_sb_id = getattr(settings_row, 'sale_gold_safe_box_id', None) if settings_row else None
        if sale_sb_id not in (None, '', 0, '0', False):
            sb = SafeBox.query.get(int(sale_sb_id))
            if sb and bool(getattr(sb, 'is_active', True)):
                return sb
    except Exception:
        pass

    # Last resort: unified gold safe by karat
    try:
        return SafeBox.get_gold_safe_by_karat(karat)
    except Exception:
        return None


def _append_safe_transactions_for_invoice_gold(invoice: Invoice, created_by: str = None):
    """Append SafeBoxTransaction rows representing gold inventory movements for an invoice.

    Source weights:
    - Prefer InvoiceKaratLine (bulk purchases).
    - Fallback to InvoiceItem weight * quantity.

    Ledger is append-only; reversal is handled by a separate helper.
    """
    if not invoice or not getattr(invoice, 'id', None):
        return []

    existing = (
        SafeBoxTransaction.query.filter_by(ref_type='invoice_gold', ref_id=invoice.id)
        .order_by(SafeBoxTransaction.id.desc())
        .first()
    )
    if existing:
        return []

    weights_by_karat = {18: 0.0, 21: 0.0, 22: 0.0, 24: 0.0}

    invoice_type = (getattr(invoice, 'invoice_type', None) or '').strip()
    gold_type = (str(getattr(invoice, 'gold_type', '') or '').strip().lower() or 'new')
    is_customer_scrap_purchase = (
        invoice_type in ('شراء من عميل', 'مرتجع شراء')
        and gold_type == 'scrap'
    )

    used_karat_lines = False
    try:
        karat_lines = getattr(invoice, 'karat_lines', None) or []
        for kl in karat_lines:
            karat_val = getattr(kl, 'karat', None)
            try:
                karat = int(float(karat_val or 21))
            except Exception:
                karat = 21
            if karat not in weights_by_karat:
                karat = 21

            grams = _to_float(getattr(kl, 'weight_grams', 0.0) or 0.0)
            if grams <= 0:
                continue
            weights_by_karat[karat] += float(grams)
            used_karat_lines = True
    except Exception:
        used_karat_lines = False

    if not used_karat_lines:
        for inv_item in getattr(invoice, 'items', None) or []:
            qty = getattr(inv_item, 'quantity', None)
            try:
                qty = int(qty or 1)
            except Exception:
                qty = 1
            if qty <= 0:
                qty = 1

            karat_val = getattr(inv_item, 'karat', None)
            if karat_val in (None, '', False) and getattr(inv_item, 'item', None):
                karat_val = getattr(inv_item.item, 'karat', None)

            try:
                karat = int(float(karat_val or 21))
            except Exception:
                karat = 21
            if karat not in weights_by_karat:
                karat = 21

            weight_per_unit = getattr(inv_item, 'weight', None)
            if weight_per_unit in (None, '', False) and getattr(inv_item, 'item', None):
                weight_per_unit = getattr(inv_item.item, 'weight', None)
            qty_multiplier = 1 if is_customer_scrap_purchase else qty
            grams = _to_float(weight_per_unit) * float(qty_multiplier)
            if grams <= 0:
                continue
            weights_by_karat[karat] += float(grams)

    direction = _direction_for_invoice_gold(getattr(invoice, 'invoice_type', None))
    invoice_number = getattr(invoice, 'invoice_number', None) or str(getattr(invoice, 'id', ''))

    created = []
    for karat, grams in weights_by_karat.items():
        if grams <= 0.0005:
            continue

        sb = _resolve_gold_safe_for_invoice(invoice, karat)
        if not sb:
            raise Exception(f'لا توجد خزينة ذهب نشطة لعيار {karat}')

        tx = SafeBoxTransaction(
            safe_box_id=sb.id,
            ref_type='invoice_gold',
            ref_id=invoice.id,
            invoice_id=invoice.id,
            payment_method_id=None,
            direction=direction,
            amount_cash=0.0,
            notes=f"Invoice {invoice_number} - {getattr(invoice, 'invoice_type', '')}",
            created_by=created_by,
        )

        grams = float(grams)
        if karat == 18:
            tx.weight_18k = grams
        elif karat == 22:
            tx.weight_22k = grams
        elif karat == 24:
            tx.weight_24k = grams
        else:
            tx.weight_21k = grams

        db.session.add(tx)
        created.append(tx)

    return created


def _append_safe_reversal_transactions_for_voucher(voucher, created_by=None, reason=None):
    """Append reversing SafeBoxTransaction rows for a previously-approved voucher (payment/receipt)."""
    if not voucher or not getattr(voucher, 'id', None):
        return []
    existing_reversal = (
        SafeBoxTransaction.query.filter_by(ref_type='voucher_reversal', ref_id=voucher.id)
        .order_by(SafeBoxTransaction.id.desc())
        .first()
    )
    if existing_reversal:
        return []
    original = SafeBoxTransaction.query.filter(
        SafeBoxTransaction.ref_id == voucher.id,
        SafeBoxTransaction.ref_type.in_(['voucher', 'invoice_payment']),
    ).all()
    if not original:
        return []
    created = []
    for tx in original:
        rev = SafeBoxTransaction(
            safe_box_id=tx.safe_box_id,
            ref_type='voucher_reversal',
            ref_id=voucher.id,
            payment_method_id=tx.payment_method_id,
            direction='out' if (tx.direction or 'in') == 'in' else 'in',
            amount_cash=float(tx.amount_cash or 0.0),
            weight_18k=float(tx.weight_18k or 0.0),
            weight_21k=float(tx.weight_21k or 0.0),
            weight_22k=float(tx.weight_22k or 0.0),
            weight_24k=float(tx.weight_24k or 0.0),
            notes=(reason or f"Reversal for voucher {voucher.voucher_number}"),
            created_by=created_by or getattr(voucher, 'created_by', 'system'),
        )
        db.session.add(rev)
        created.append(rev)
    return created


def _append_safe_reversal_transactions_for_invoice_gold(invoice: Invoice, created_by: str = None, reason: str = None):
    """Append reversing SafeBoxTransaction rows for a previously-posted invoice gold movement."""
    if not invoice or not getattr(invoice, 'id', None):
        return []

    existing_reversal = (
        SafeBoxTransaction.query.filter_by(ref_type='invoice_gold_reversal', ref_id=invoice.id)
        .order_by(SafeBoxTransaction.id.desc())
        .first()
    )
    if existing_reversal:
        return []

    original = SafeBoxTransaction.query.filter_by(ref_type='invoice_gold', ref_id=invoice.id).all()
    if not original:
        return []

    invoice_number = getattr(invoice, 'invoice_number', None) or str(getattr(invoice, 'id', ''))
    created = []
    for tx in original:
        rev = SafeBoxTransaction(
            safe_box_id=tx.safe_box_id,
            ref_type='invoice_gold_reversal',
            ref_id=invoice.id,
            invoice_id=invoice.id,
            payment_method_id=None,
            direction='out' if (tx.direction or 'in') == 'in' else 'in',
            amount_cash=0.0,
            weight_18k=float(tx.weight_18k or 0.0),
            weight_21k=float(tx.weight_21k or 0.0),
            weight_22k=float(tx.weight_22k or 0.0),
            weight_24k=float(tx.weight_24k or 0.0),
            notes=(reason or '') or f"Reversal for invoice {invoice_number}",
            created_by=created_by,
        )
        db.session.add(rev)
        created.append(rev)
    return created

def _get_shift_window_for_user(user_name: str):
    """Determine the current shift window.

    Simplest rule:
    - From: last successful shift closing timestamp for this user (if any)
      otherwise start of today.
    - To: now.

    Note: timestamps are stored as naive UTC in AuditLog by default.
    This implementation uses naive datetimes consistently.
    """
    now = datetime.now()
    today_start = datetime.combine(now.date(), datetime.min.time())

    try:
        last_close = (
            AuditLog.query.filter_by(action='shift_closing', success=True)
            .filter(AuditLog.user_name == user_name)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        if last_close and last_close.timestamp:
            return last_close.timestamp, now
    except Exception:
        pass

    return today_start, now


@posting_bp.route('/shift-closing/summary', methods=['GET'])
@require_permission('safe_boxes.view')
def get_shift_closing_summary():
    """Return expected amounts per payment method for the current shift."""
    try:
        user_name = None
        try:
            user_name = getattr(getattr(g, 'current_user', None), 'username', None)
        except Exception:
            user_name = None
        user_name = user_name or 'system'

        # Allow overriding window.
        from_q = request.args.get('from')
        to_q = request.args.get('to')
        if from_q or to_q:
            try:
                window_from = datetime.fromisoformat(from_q) if from_q else None
            except Exception:
                return jsonify({'success': False, 'message': 'invalid_from'}), 400
            try:
                window_to = datetime.fromisoformat(to_q) if to_q else None
            except Exception:
                return jsonify({'success': False, 'message': 'invalid_to'}), 400
            if window_from is None or window_to is None:
                # If one side is missing, fill from defaults.
                default_from, default_to = _get_shift_window_for_user(user_name)
                window_from = window_from or default_from
                window_to = window_to or default_to
        else:
            window_from, window_to = _get_shift_window_for_user(user_name)

        pms = (
            PaymentMethod.query.filter_by(is_active=True)
            .order_by(PaymentMethod.display_order.asc(), PaymentMethod.id.asc())
            .all()
        )

        # Payment type categories (cash/card/bnpl/...) - best-effort
        pm_codes = list({(pm.payment_type or '').strip() for pm in pms if (pm.payment_type or '').strip()})
        code_to_category = {}
        if pm_codes:
            try:
                for pt in PaymentType.query.filter(PaymentType.code.in_(pm_codes)).all():
                    code_to_category[(pt.code or '').strip()] = (pt.category or '').strip() or None
            except Exception:
                code_to_category = {}

        # Preload safe box names
        safe_box_ids = [pm.default_safe_box_id for pm in pms if getattr(pm, 'default_safe_box_id', None)]
        safe_boxes = {}
        if safe_box_ids:
            for sb in SafeBox.query.filter(SafeBox.id.in_(safe_box_ids)).all():
                safe_boxes[sb.id] = sb

        rows = []
        for pm in pms:
            code = (pm.payment_type or '').strip()
            category = code_to_category.get(code)
            signed_sum = (
                db.session.query(
                    func.coalesce(
                        func.sum(
                            case(
                                (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.amount_cash),
                                else_=-SafeBoxTransaction.amount_cash,
                            )
                        ),
                        0.0,
                    )
                )
                .filter(
                    or_(
                        SafeBoxTransaction.payment_method_id == pm.id,
                        and_(
                            SafeBoxTransaction.payment_method_id.is_(None),
                            SafeBoxTransaction.safe_box_id == pm.default_safe_box_id,
                        ),
                    )
                )
                .filter(or_(SafeBoxTransaction.ref_type.is_(None), SafeBoxTransaction.ref_type != 'shift_closing_settlement'))
                .filter(SafeBoxTransaction.created_at >= window_from)
                .filter(SafeBoxTransaction.created_at <= window_to)
                .scalar()
            )

            expected_amount = float(signed_sum or 0.0)
            sb_id = getattr(pm, 'default_safe_box_id', None)
            sb = safe_boxes.get(sb_id) if sb_id else None

            # Fallback category via safe type when PaymentType is missing
            safe_type = getattr(sb, 'safe_type', None) if sb else None
            if not category and safe_type == 'cash':
                category = 'cash'

            is_cash = (category == 'cash') or (safe_type == 'cash')

            rows.append({
                'payment_method_id': pm.id,
                'payment_method_name': pm.name,
                'payment_type': code,
                'category': category,
                'is_cash': bool(is_cash),
                'default_safe_box_id': sb_id,
                'safe_box_name': getattr(sb, 'name', None) if sb else None,
                'expected_amount': round(expected_amount, 2),
            })

        return jsonify({
            'success': True,
            'from': window_from.isoformat(),
            'to': window_to.isoformat(),
            'rows': rows,
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/shift-closing/summary-gold', methods=['GET'])
@require_permission('safe_boxes.view')
def get_shift_closing_gold_summary():
    """Return expected gold weights (18/21/22/24) for the current shift.

    Source of truth: SafeBoxTransaction weight fields for gold safes.
    """
    try:
        user_name = None
        try:
            user_name = getattr(getattr(g, 'current_user', None), 'username', None)
        except Exception:
            user_name = None
        user_name = user_name or 'system'

        # Allow overriding window.
        from_q = request.args.get('from')
        to_q = request.args.get('to')
        if from_q or to_q:
            try:
                window_from = datetime.fromisoformat(from_q) if from_q else None
            except Exception:
                return jsonify({'success': False, 'message': 'invalid_from'}), 400
            try:
                window_to = datetime.fromisoformat(to_q) if to_q else None
            except Exception:
                return jsonify({'success': False, 'message': 'invalid_to'}), 400
            if window_from is None or window_to is None:
                default_from, default_to = _get_shift_window_for_user(user_name)
                window_from = window_from or default_from
                window_to = window_to or default_to
        else:
            window_from, window_to = _get_shift_window_for_user(user_name)

        gold_safe_ids = [
            sb.id
            for sb in SafeBox.query.filter_by(is_active=True, safe_type='gold').all()
            if sb and sb.id
        ]

        if not gold_safe_ids:
            return jsonify({
                'success': True,
                'from': window_from.isoformat(),
                'to': window_to.isoformat(),
                'totals': {
                    '18k': 0.0,
                    '21k': 0.0,
                    '22k': 0.0,
                    '24k': 0.0,
                },
            }), 200

        totals_row = (
            db.session.query(
                func.coalesce(
                    func.sum(
                        case(
                            (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.weight_18k),
                            else_=-SafeBoxTransaction.weight_18k,
                        )
                    ),
                    0.0,
                ).label('w18'),
                func.coalesce(
                    func.sum(
                        case(
                            (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.weight_21k),
                            else_=-SafeBoxTransaction.weight_21k,
                        )
                    ),
                    0.0,
                ).label('w21'),
                func.coalesce(
                    func.sum(
                        case(
                            (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.weight_22k),
                            else_=-SafeBoxTransaction.weight_22k,
                        )
                    ),
                    0.0,
                ).label('w22'),
                func.coalesce(
                    func.sum(
                        case(
                            (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.weight_24k),
                            else_=-SafeBoxTransaction.weight_24k,
                        )
                    ),
                    0.0,
                ).label('w24'),
            )
            .filter(SafeBoxTransaction.safe_box_id.in_(gold_safe_ids))
            .filter(or_(SafeBoxTransaction.ref_type.is_(None), SafeBoxTransaction.ref_type != 'shift_closing_settlement'))
            .filter(SafeBoxTransaction.created_at >= window_from)
            .filter(SafeBoxTransaction.created_at <= window_to)
            .first()
        )

        w18 = float(getattr(totals_row, 'w18', 0.0) or 0.0)
        w21 = float(getattr(totals_row, 'w21', 0.0) or 0.0)
        w22 = float(getattr(totals_row, 'w22', 0.0) or 0.0)
        w24 = float(getattr(totals_row, 'w24', 0.0) or 0.0)

        return jsonify({
            'success': True,
            'from': window_from.isoformat(),
            'to': window_to.isoformat(),
            'totals': {
                '18k': round(w18, 3),
                '21k': round(w21, 3),
                '22k': round(w22, 3),
                '24k': round(w24, 3),
            },
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/shift-closing/close', methods=['POST'])
@require_permission('safe_boxes.edit')
def close_shift():
    """Submit shift closing report and write it into AuditLog."""
    data = request.get_json(silent=True) or {}
    entries = data.get('entries')
    if not isinstance(entries, list) or len(entries) == 0:
        return jsonify({'success': False, 'message': 'entries_required'}), 400

    gold_actuals = data.get('gold_actuals')
    if gold_actuals is not None and not isinstance(gold_actuals, dict):
        return jsonify({'success': False, 'message': 'invalid_gold_actuals'}), 400

    user_name = None
    try:
        user_name = getattr(getattr(g, 'current_user', None), 'username', None)
    except Exception:
        user_name = None
    user_name = user_name or 'system'

    # Resolve window
    from_str = data.get('from')
    to_str = data.get('to')
    try:
        window_from = datetime.fromisoformat(from_str) if from_str else None
    except Exception:
        return jsonify({'success': False, 'message': 'invalid_from'}), 400
    try:
        window_to = datetime.fromisoformat(to_str) if to_str else None
    except Exception:
        return jsonify({'success': False, 'message': 'invalid_to'}), 400
    if window_from is None or window_to is None:
        default_from, default_to = _get_shift_window_for_user(user_name)
        window_from = window_from or default_from
        window_to = window_to or default_to

    def _to_float(v):
        try:
            if v in (None, '', False):
                return 0.0
            return float(v)
        except Exception:
            return 0.0

    settle_cash = bool(data.get('settle_cash') is True)
    opening_cash_amount = 0.0
    try:
        opening_cash_amount = float(data.get('opening_cash_amount') or 0.0)
    except Exception:
        opening_cash_amount = 0.0
    if opening_cash_amount < 0:
        opening_cash_amount = 0.0

    # Payment type categories (cash/card/bnpl/...) - best-effort
    try:
        pt_rows = PaymentType.query.filter_by(is_active=True).all()
        code_to_category = {(pt.code or '').strip(): (pt.category or '').strip() or None for pt in pt_rows}
    except Exception:
        code_to_category = {}

    # Validate payload and normalize amounts
    normalized = []
    for idx, row in enumerate(entries):
        if not isinstance(row, dict):
            return jsonify({'success': False, 'message': f'invalid_entry_{idx}'}), 400
        pm_id = row.get('payment_method_id')
        if pm_id in (None, '', False):
            return jsonify({'success': False, 'message': f'missing_payment_method_id_{idx}'}), 400
        try:
            pm_id = int(pm_id)
        except Exception:
            return jsonify({'success': False, 'message': f'invalid_payment_method_id_{idx}'}), 400

        expected = _to_float(row.get('expected_amount'))
        actual = _to_float(row.get('actual_amount'))

        denominations = row.get('denominations')
        denom_total = None
        if isinstance(denominations, dict) and len(denominations) > 0:
            try:
                total = 0.0
                for k, v in denominations.items():
                    denom = float(k)
                    count = int(v)
                    if denom <= 0 or count < 0:
                        continue
                    total += denom * count
                denom_total = round(total, 2)
                actual = float(denom_total)
            except Exception:
                denom_total = None
                denominations = None

        pm_obj = PaymentMethod.query.get(pm_id)
        pm_name = pm_obj.name if pm_obj else None
        pm_code = (pm_obj.payment_type or '').strip() if pm_obj else None
        category = code_to_category.get(pm_code or '') if pm_code else None
        default_sb_id = getattr(pm_obj, 'default_safe_box_id', None) if pm_obj else None
        sb = SafeBox.query.get(default_sb_id) if default_sb_id else None
        safe_type = getattr(sb, 'safe_type', None) if sb else None
        if not category and safe_type == 'cash':
            category = 'cash'
        is_cash = (category == 'cash') or (safe_type == 'cash')

        normalized.append({
            'payment_method_id': pm_id,
            'payment_method_name': pm_name,
            'payment_type': pm_code,
            'category': category,
            'is_cash': bool(is_cash),
            'default_safe_box_id': default_sb_id,
            'expected_amount': round(expected, 2),
            'actual_amount': round(actual, 2),
            'difference': round(actual - expected, 2),
            'denominations': denominations if isinstance(denominations, dict) else None,
            'denominations_total': denom_total,
        })

    # Create a human-readable reference
    entity_number = f"SHIFT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    total_expected = round(sum(float(r.get('expected_amount') or 0.0) for r in normalized), 2)
    total_actual = round(sum(float(r.get('actual_amount') or 0.0) for r in normalized), 2)
    total_difference = round(total_actual - total_expected, 2)

    details = {
        'from': window_from.isoformat(),
        'to': window_to.isoformat(),
        'totals': {
            'total_expected': total_expected,
            'total_actual': total_actual,
            'total_difference': total_difference,
        },
        'summary_ar': f"تم إغلاق الوردية بواسطة {user_name} بفرق {total_difference:.2f}",
        'entries': normalized,
        'notes': (data.get('notes') or '').strip() or None,
        'settle_cash': settle_cash,
        'opening_cash_amount': round(opening_cash_amount, 2),
    }

    # Optional: gold reconciliation snapshot (expected from ledger + provided actuals)
    gold_details = None
    try:
        if isinstance(gold_actuals, dict):
            # find active gold safes
            gold_safes = SafeBox.query.filter_by(safe_type='gold').all()
            gold_safe_ids = [sb.id for sb in gold_safes if getattr(sb, 'is_active', True)]

            expected_map = {'18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0}
            if gold_safe_ids:
                totals_row = (
                    db.session.query(
                        func.coalesce(
                            func.sum(
                                case(
                                    (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.weight_18k),
                                    else_=-SafeBoxTransaction.weight_18k,
                                )
                            ),
                            0.0,
                        ).label('w18'),
                        func.coalesce(
                            func.sum(
                                case(
                                    (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.weight_21k),
                                    else_=-SafeBoxTransaction.weight_21k,
                                )
                            ),
                            0.0,
                        ).label('w21'),
                        func.coalesce(
                            func.sum(
                                case(
                                    (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.weight_22k),
                                    else_=-SafeBoxTransaction.weight_22k,
                                )
                            ),
                            0.0,
                        ).label('w22'),
                        func.coalesce(
                            func.sum(
                                case(
                                    (SafeBoxTransaction.direction == 'in', SafeBoxTransaction.weight_24k),
                                    else_=-SafeBoxTransaction.weight_24k,
                                )
                            ),
                            0.0,
                        ).label('w24'),
                    )
                    .filter(SafeBoxTransaction.safe_box_id.in_(gold_safe_ids))
                    .filter(or_(SafeBoxTransaction.ref_type.is_(None), SafeBoxTransaction.ref_type != 'shift_closing_settlement'))
                    .filter(SafeBoxTransaction.created_at >= window_from)
                    .filter(SafeBoxTransaction.created_at <= window_to)
                    .first()
                )

                expected_map = {
                    '18k': float(getattr(totals_row, 'w18', 0.0) or 0.0),
                    '21k': float(getattr(totals_row, 'w21', 0.0) or 0.0),
                    '22k': float(getattr(totals_row, 'w22', 0.0) or 0.0),
                    '24k': float(getattr(totals_row, 'w24', 0.0) or 0.0),
                }

            actual_map = {
                '18k': _to_float(gold_actuals.get('18k')),
                '21k': _to_float(gold_actuals.get('21k')),
                '22k': _to_float(gold_actuals.get('22k')),
                '24k': _to_float(gold_actuals.get('24k')),
            }
            diff_map = {k: float(actual_map.get(k, 0.0)) - float(expected_map.get(k, 0.0)) for k in expected_map.keys()}

            def _to_pure_24(m: dict) -> float:
                w18 = float(m.get('18k', 0.0) or 0.0)
                w21 = float(m.get('21k', 0.0) or 0.0)
                w22 = float(m.get('22k', 0.0) or 0.0)
                w24 = float(m.get('24k', 0.0) or 0.0)
                return (w18 * (18.0 / 24.0)) + (w21 * (21.0 / 24.0)) + (w22 * (22.0 / 24.0)) + (w24 * 1.0)

            pure_expected = _to_pure_24(expected_map)
            pure_actual = _to_pure_24(actual_map)
            pure_diff = pure_actual - pure_expected

            gold_details = {
                'expected': {k: round(float(v or 0.0), 3) for k, v in expected_map.items()},
                'actual': {k: round(float(v or 0.0), 3) for k, v in actual_map.items()},
                'difference': {k: round(float(v or 0.0), 3) for k, v in diff_map.items()},
                'pure_24k': {
                    'expected': round(float(pure_expected or 0.0), 3),
                    'actual': round(float(pure_actual or 0.0), 3),
                    'difference': round(float(pure_diff or 0.0), 3),
                },
                'summary_ar': (
                    f"مطابقة الذهب - 18: {diff_map['18k']:+.3f} جم، "
                    f"21: {diff_map['21k']:+.3f} جم، "
                    f"22: {diff_map['22k']:+.3f} جم، "
                    f"24: {diff_map['24k']:+.3f} جم"
                ),
            }

            details['gold'] = gold_details
    except Exception:
        # keep shift closing best-effort even if gold snapshot fails
        pass

    try:
        log = AuditLog.log_action(
            user_name=user_name,
            action='shift_closing',
            entity_type='ShiftClosing',
            entity_id=0,
            entity_number=entity_number,
            details=json.dumps(details, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            success=True,
        )
        db.session.flush()
        if log:
            try:
                log.entity_id = log.id
            except Exception:
                pass

        # Optional settlement (ledger-only) to reflect physically clearing cash drawers.
        settlement_rows = []
        if settle_cash:
            for entry in normalized:
                if not entry.get('is_cash'):
                    continue
                sb_id = entry.get('default_safe_box_id')
                if not sb_id:
                    continue

                actual_amt = float(entry.get('actual_amount') or 0.0)
                withdraw_amt = max(round(actual_amt - opening_cash_amount, 2), 0.0)
                if withdraw_amt <= 0:
                    continue

                tx = SafeBoxTransaction(
                    safe_box_id=int(sb_id),
                    ref_type='shift_closing_settlement',
                    ref_id=(log.id if log else None),
                    payment_method_id=int(entry.get('payment_method_id')),
                    direction='out',
                    amount_cash=float(withdraw_amt),
                    notes=f"Shift closing settlement {entity_number}",
                    created_by=user_name,
                )
                db.session.add(tx)
                settlement_rows.append({
                    'safe_box_id': int(sb_id),
                    'payment_method_id': int(entry.get('payment_method_id')),
                    'amount_cash': float(withdraw_amt),
                    'direction': 'out',
                })

        if settlement_rows:
            try:
                details['settlement'] = settlement_rows
                if log:
                    log.details = json.dumps(details, ensure_ascii=False)
            except Exception:
                pass

        # --- Security thresholds: create critical in-app alert when deficit exceeds threshold ---
        try:
            settings_row = Settings.query.first()
            config = {}
            if settings_row and settings_row.weight_closing_settings:
                try:
                    decoded = json.loads(settings_row.weight_closing_settings)
                    if isinstance(decoded, dict):
                        config = decoded
                except Exception:
                    config = {}

            cash_threshold = 50.0
            gold_threshold = 0.10
            try:
                cash_threshold = float(config.get('shift_close_cash_deficit_threshold', cash_threshold) or cash_threshold)
            except Exception:
                cash_threshold = 50.0
            try:
                gold_threshold = float(
                    config.get('shift_close_gold_pure_deficit_threshold_grams', gold_threshold) or gold_threshold
                )
            except Exception:
                gold_threshold = 0.10

            cash_deficit = abs(float(total_difference or 0.0))

            pure_gold_diff = None
            try:
                pure_gold_diff = float((((details.get('gold') or {}).get('pure_24k') or {}).get('difference')))
            except Exception:
                pure_gold_diff = None

            gold_deficit = abs(float(pure_gold_diff or 0.0)) if pure_gold_diff is not None else 0.0

            is_cash_critical = cash_deficit > cash_threshold if cash_threshold is not None else False
            is_gold_critical = (pure_gold_diff is not None) and (gold_deficit > gold_threshold)

            if is_cash_critical or is_gold_critical:
                title = 'تنبيه عهده - إغلاق وردية'
                message = (
                    f"تم رصد فرق يتجاوز العتبة عند إغلاق {entity_number}. "
                    f"فرق النقد: {total_difference:+.2f}، "
                    f"فرق الذهب الصافي: {(pure_gold_diff if pure_gold_diff is not None else 0.0):+.3f} جم"
                )

                alert_details = {
                    'shift': {
                        'entity_number': entity_number,
                        'from': details.get('from'),
                        'to': details.get('to'),
                    },
                    'diffs': {
                        'cash_difference': float(total_difference or 0.0),
                        'gold_pure_24k_difference': float(pure_gold_diff) if pure_gold_diff is not None else None,
                    },
                    'thresholds': {
                        'cash_deficit_threshold': float(cash_threshold),
                        'gold_pure_deficit_threshold_grams': float(gold_threshold),
                    },
                    'flags': {
                        'cash_critical': bool(is_cash_critical),
                        'gold_critical': bool(is_gold_critical),
                    },
                    'audit_log_id': (log.id if log else None),
                }

                db.session.add(
                    SystemAlert(
                        alert_type='shift_closing',
                        severity='critical',
                        title=title,
                        message=message,
                        entity_type='ShiftClosing',
                        entity_id=(log.id if log else None),
                        entity_number=entity_number,
                        details=json.dumps(alert_details, ensure_ascii=False),
                        created_by=user_name,
                    )
                )
        except Exception:
            # alerts must never break shift closing
            pass

        db.session.commit()
        return jsonify({
            'success': True,
            'entity_number': entity_number,
            'totals': details.get('totals'),
        }), 201
    except Exception as e:
        db.session.rollback()
        # best-effort failure log
        try:
            AuditLog.log_action(
                user_name=user_name,
                action='shift_closing',
                entity_type='ShiftClosing',
                entity_id=0,
                entity_number=entity_number,
                details=json.dumps(details, ensure_ascii=False),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
                success=False,
                error_message=str(e),
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# ==========================================
# 📋 عرض الفواتير/القيود حسب حالة الترحيل
# ==========================================

@posting_bp.route('/invoices/unposted', methods=['GET'])
@require_permission('invoice.view')
def get_unposted_invoices():
    """عرض جميع الفواتير غير المرحلة"""
    try:
        invoices = Invoice.query.filter_by(is_posted=False).order_by(Invoice.date.desc()).all()
        
        return jsonify({
            'success': True,
            'count': len(invoices),
            'invoices': [inv.to_dict() for inv in invoices]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/invoices/posted', methods=['GET'])
@require_permission('invoice.view')
def get_posted_invoices():
    """عرض جميع الفواتير المرحلة"""
    try:
        invoices = Invoice.query.filter_by(is_posted=True).order_by(Invoice.posted_at.desc()).all()
        
        return jsonify({
            'success': True,
            'count': len(invoices),
            'invoices': [inv.to_dict() for inv in invoices]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/journal-entries/unposted', methods=['GET'])
@require_permission('journal.view')
def get_unposted_entries():
    """عرض جميع القيود غير المرحلة (باستثناء قيود الفواتير - تُرحَّل مع الفاتورة)"""
    try:
        entries = JournalEntry.query.filter(
            JournalEntry.is_posted == False,
            JournalEntry.is_deleted == False,
            # استثناء قيود الفواتير — يجب ترحيلها عبر بوابة ترحيل الفواتير
            db.or_(
                JournalEntry.reference_type.is_(None),
                JournalEntry.reference_type != 'invoice',
            ),
        ).order_by(JournalEntry.date.desc()).all()
        
        payload_entries = []
        for entry in entries:
            d = entry.to_dict()
            d['posting_summary'] = _journal_entry_posting_summary(entry)
            payload_entries.append(d)

        return jsonify({
            'success': True,
            'count': len(entries),
            'entries': payload_entries,
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/journal-entries/posted', methods=['GET'])
@require_permission('journal.view')
def get_posted_entries():
    """عرض جميع القيود المرحلة"""
    try:
        entries = JournalEntry.query.filter_by(
            is_posted=True,
            is_deleted=False
        ).order_by(JournalEntry.posted_at.desc()).all()
        
        payload_entries = []
        for entry in entries:
            d = entry.to_dict()
            d['posting_summary'] = _journal_entry_posting_summary(entry)
            payload_entries.append(d)

        return jsonify({
            'success': True,
            'count': len(entries),
            'entries': payload_entries,
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/journal-entries/<int:entry_id>', methods=['DELETE'])
@require_permission('journal.delete')
def delete_unposted_journal_entry(entry_id: int):
    """Delete (soft-delete) an UNPOSTED journal entry from the posting screen."""
    try:
        deleted_by = None
        try:
            user = getattr(g, 'current_user', None)
            deleted_by = (
                getattr(user, 'username', None)
                or getattr(user, 'full_name', None)
                or getattr(user, 'name', None)
            )
        except Exception:
            deleted_by = None

        try:
            deleted_by = str(deleted_by or '').strip()
        except Exception:
            deleted_by = ''
        if not deleted_by:
            deleted_by = 'system'

        entry = JournalEntry.query.get(entry_id)
        if not entry:
            return jsonify({'success': False, 'message': 'القيد غير موجود'}), 404

        if getattr(entry, 'is_deleted', False):
            return jsonify({'success': False, 'message': 'القيد محذوف'}), 400

        if getattr(entry, 'is_posted', False):
            return jsonify({'success': False, 'message': 'لا يمكن حذف قيد مرحل. استخدم إلغاء الترحيل أولاً.'}), 400

        if getattr(entry, 'reference_type', None) == 'invoice':
            return jsonify({
                'success': False,
                'message': 'لا يمكن حذف قيد مرتبط بفاتورة من هنا. يرجى التعامل معه عبر الفاتورة.',
            }), 400

        # Soft delete entry + lines to keep historical trace without hard-deleting rows.
        reason = None
        try:
            reason = (request.args.get('reason') or '').strip() or None
        except Exception:
            reason = None

        entry.soft_delete(deleted_by, reason)

        now = datetime.now()
        for line in (entry.lines or []):
            line.is_deleted = True
            line.deleted_at = now

        # Remove any derived SafeBox ledger rows tied to this entry.
        try:
            SafeBoxTransaction.query.filter_by(ref_type='journal_entry', ref_id=int(entry.id)).delete(
                synchronize_session=False
            )
        except Exception:
            pass

        try:
            AuditLog.log_action(
                user_name=deleted_by,
                action='delete_unposted',
                entity_type='journal_entry',
                entity_id=int(entry.id),
                entity_number=getattr(entry, 'entry_number', None),
                details=json.dumps({'reason': reason}, ensure_ascii=False),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
                success=True,
            )
        except Exception:
            pass

        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف القيد غير المرحل بنجاح'}), 200

    except Exception as e:
        db.session.rollback()
        try:
            AuditLog.log_action(
                user_name=getattr(getattr(g, 'current_user', None), 'username', None) or 'system',
                action='delete_unposted',
                entity_type='journal_entry',
                entity_id=int(entry_id),
                success=False,
                error_message=str(e),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
            )
        except Exception:
            pass
        return jsonify({'success': False, 'message': str(e)}), 500


# ==========================================
# ✅ ترحيل الفواتير
# ==========================================

@posting_bp.route('/invoices/post/<int:invoice_id>', methods=['POST'])
@require_permission('invoice.post')
def post_invoice(invoice_id):
    """
    ترحيل فاتورة واحدة
    
    Body:
    {
        "posted_by": "اسم المستخدم"
    }
    
    يتطلب صلاحية: invoice.post
    """
    try:
        # استخدام اسم المستخدم المصادق عليه
        posted_by = None
        try:
            user = getattr(g, 'current_user', None)
            posted_by = (
                getattr(user, 'username', None)
                or getattr(user, 'full_name', None)
                or getattr(user, 'name', None)
            )
        except Exception:
            posted_by = None

        try:
            posted_by = str(posted_by or '').strip()
        except Exception:
            posted_by = ''
        if not posted_by:
            posted_by = 'system'
        
        invoice = Invoice.query.get(invoice_id)
        if not invoice:
            return jsonify({'success': False, 'message': 'الفاتورة غير موجودة'}), 404
        
        if invoice.is_posted:
            return jsonify({
                'success': False, 
                'message': 'الفاتورة مرحلة بالفعل'
            }), 400
        
        # ترحيل الفاتورة
        invoice.is_posted = True
        invoice.posted_at = datetime.now()
        invoice.posted_by = posted_by or (invoice.posted_by or 'system')

        # Append gold inventory movements into SafeBox ledger (append-only)
        _append_safe_transactions_for_invoice_gold(invoice, created_by=posted_by)

        # ✅ ترحيل القيود المرتبطة بالفاتورة تلقائياً (لمنع الازدواجية عند ترحيل القيود منفردةً)
        try:
            linked_jes = JournalEntry.query.filter_by(
                reference_type='invoice', reference_id=invoice_id, is_posted=False
            ).filter(JournalEntry.is_deleted == False).all()
            for _je in linked_jes:
                _je.is_posted = True
                _je.posted_at = datetime.now()
                _je.posted_by = posted_by
        except Exception as _je_err:
            print(f"[post_invoice] خطأ في ترحيل القيود المرتبطة: {_je_err}")

        # ✅ إنشاء حركات الخزينة وقيود التسوية للدفعات المؤجلة (unposted_mode invoices)
        # يضمن دخول النقد للخزينة وصفر ذمم العميل بعد الترحيل.
        try:
            _create_deferred_payment_entries(invoice, posted_by=posted_by)
        except Exception as _def_err:
            print(f"[post_invoice] خطأ في إنشاء قيود الدفع المؤجل: {_def_err}")
        
        db.session.commit()
        
        # 📋 تسجيل في Audit Log
        try:
            details = json.dumps({
                'invoice_type': invoice.invoice_type,
                'total': float(invoice.total) if invoice.total else 0,
                'date': str(invoice.date),
                'customer_id': invoice.customer_id if hasattr(invoice, 'customer_id') else None,
            }, ensure_ascii=False)
            
            AuditLog.log_action(
                user_name=posted_by,
                action='post_invoice',
                entity_type='Invoice',
                entity_id=invoice_id,
                entity_number=getattr(invoice, 'invoice_number', None),
                details=details,
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
                success=True
            )
        except Exception as log_error:
            print(f"خطأ في تسجيل Audit Log: {log_error}")
        
        return jsonify({
            'success': True,
            'message': 'تم ترحيل الفاتورة بنجاح',
            'invoice': invoice.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        
        # 📋 تسجيل الفشل في Audit Log
        try:
            posted_by = g.current_user.username if hasattr(g, 'current_user') else 'النظام'
            AuditLog.log_action(
                user_name=posted_by,
                action='post_invoice',
                entity_type='Invoice',
                entity_id=invoice_id,
                entity_number=None,
                details=None,
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'),
                success=False,
                error_message=str(e)
            )
        except:
            pass
        
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/invoices/approve-large-discount/<int:invoice_id>', methods=['POST'])
@require_permission('invoice.post')
@require_permission('journal.post')
def approve_large_discount_invoice(invoice_id):
    """Approve and post an unposted invoice that was saved behind an approval gate.

    For approval-gated invoices, invoice payments are persisted but SafeBox movements
    are intentionally deferred until approval.
    """
    try:
        approved_by = g.current_user.username

        invoice = Invoice.query.get(invoice_id)
        if not invoice:
            return jsonify({'success': False, 'message': 'الفاتورة غير موجودة'}), 404

        if getattr(invoice, 'is_posted', False):
            return jsonify({'success': False, 'message': 'الفاتورة مرحلة بالفعل'}), 400

        # Mark invoice as posted (approval implies posting).
        invoice.is_posted = True
        invoice.posted_at = datetime.now()
        invoice.posted_by = approved_by

        # Restore basic payment status based on persisted payments.
        try:
            payments = list(getattr(invoice, 'payments', []) or [])
            total_paid = 0.0
            for pay in payments:
                try:
                    total_paid += float(getattr(pay, 'amount', 0.0) or 0.0)
                except Exception:
                    pass
            invoice.amount_paid = round(total_paid, 2)

            inv_total = float(getattr(invoice, 'total', 0.0) or 0.0)
            if total_paid <= 0.0:
                invoice.status = 'unpaid'
            elif inv_total > 0 and (total_paid + 0.01) < inv_total:
                invoice.status = 'partially_paid'
            else:
                invoice.status = 'paid'
        except Exception:
            pass

        # Append gold inventory movements into SafeBox ledger (append-only)
        _append_safe_transactions_for_invoice_gold(invoice, created_by=approved_by)

        # ✅ إنشاء SafeBoxTransaction + قيود التسوية للدفعات المؤجلة
        # (مشترك مع post_invoice - يضمن دخول النقد للخزينة وصفر ذمم الطرف)
        _create_deferred_payment_entries(invoice, posted_by=approved_by)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'تم اعتماد وترحيل الفاتورة بنجاح',
            'invoice': invoice.to_dict(),
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/invoices/approve/<int:invoice_id>', methods=['POST'])
@require_permission('invoice.post')
@require_permission('journal.post')
def approve_invoice(invoice_id):
    """Generic approval endpoint for invoices that were saved with `approval_required`.

    This is an alias to the existing approval implementation and is kept generic
    so it can be used for multiple approval reasons (e.g. large_discount, below_cost).
    """
    return approve_large_discount_invoice(invoice_id)


@posting_bp.route('/invoices/post-batch', methods=['POST'])
@require_permission('invoice.post')
def post_invoices_batch():
    """
    ترحيل مجموعة فواتير
    
    Body:
    {
        "invoice_ids": [1, 2, 3, ...]
    }
    
    يتطلب صلاحية: invoice.post
    """
    try:
        posted_by = g.current_user.username
        data = request.get_json()
        invoice_ids = data.get('invoice_ids', [])
        
        if not invoice_ids:
            return jsonify({'success': False, 'message': 'لم يتم تحديد أي فواتير'}), 400
        
        invoices = Invoice.query.filter(Invoice.id.in_(invoice_ids)).all()
        
        posted_count = 0
        skipped_count = 0
        
        for invoice in invoices:
            if not invoice.is_posted:
                invoice.is_posted = True
                invoice.posted_at = datetime.now()
                invoice.posted_by = posted_by
                posted_count += 1

                # Append gold inventory movements into SafeBox ledger (append-only)
                _append_safe_transactions_for_invoice_gold(invoice, created_by=posted_by)

                # ✅ ترحيل القيود المرتبطة بالفاتورة تلقائياً (لمنع الازدواجية)
                try:
                    linked_jes = JournalEntry.query.filter_by(
                        reference_type='invoice', reference_id=invoice.id, is_posted=False
                    ).filter(JournalEntry.is_deleted == False).all()
                    for _je in linked_jes:
                        _je.is_posted = True
                        _je.posted_at = datetime.now()
                        _je.posted_by = posted_by
                except Exception as _je_err:
                    print(f"[post_invoices_batch] خطأ في ترحيل القيود المرتبطة للفاتورة {invoice.id}: {_je_err}")

                # ✅ إنشاء حركات الخزينة وقيود التسوية للدفعات المؤجلة
                try:
                    _create_deferred_payment_entries(invoice, posted_by=posted_by)
                except Exception as _def_err:
                    print(f"[post_invoices_batch] خطأ في قيود الدفع المؤجل للفاتورة {invoice.id}: {_def_err}")

                # تسجيل كل عملية ناجحة
                AuditLog.log_action(
                    user_name=posted_by,
                    action='post',
                    entity_type='invoice',
                    entity_id=invoice.id,
                    entity_number=(getattr(invoice, 'invoice_number', None) or str(getattr(invoice, 'id', '') or '')),
                    details=json.dumps({'batch_operation': True}, ensure_ascii=False),
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent')
                )
            else:
                skipped_count += 1
        
        db.session.commit()
        
        # تسجيل العملية الجماعية
        AuditLog.log_action(
            user_name=posted_by,
            action='post_batch',
            entity_type='invoice',
            entity_id=0,  # batch operation
            details=json.dumps({
                'total_invoices': len(invoice_ids),
                'posted_count': posted_count,
                'skipped_count': skipped_count
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'تم ترحيل {posted_count} فاتورة، تم تخطي {skipped_count}',
            'posted_count': posted_count,
            'skipped_count': skipped_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        posted_by = g.current_user.username if hasattr(g, 'current_user') else 'النظام'
        AuditLog.log_action(
            user_name=posted_by,
            action='post_batch',
            entity_type='invoice',
            entity_id=0,  # batch operation لا يوجد entity_id محدد
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/invoices/unpost/<int:invoice_id>', methods=['POST'])
@require_permission('invoice.unpost')
def unpost_invoice(invoice_id):
    """
    إلغاء ترحيل فاتورة
    
    يتطلب صلاحية: invoice.unpost
    
    ⚠️ تحذير: هذا الإجراء حساس ويجب استخدامه بحذر
    """
    try:
        # Check server-side allow_unposting setting
        try:
            _unpost_settings = Settings.query.first()
            if _unpost_settings and not bool(getattr(_unpost_settings, 'allow_unposting', False)):
                return jsonify({
                    'success': False,
                    'message': 'إلغاء الترحيل معطّل في إعدادات النظام'
                }), 403
        except Exception:
            pass

        posted_by = g.current_user.username
        invoice = Invoice.query.get(invoice_id)
        if not invoice:
            AuditLog.log_action(
                user_name=posted_by,
                action='unpost',
                entity_type='invoice',
                entity_id=invoice_id,
                success=False,
                error_message='الفاتورة غير موجودة',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            return jsonify({'success': False, 'message': 'الفاتورة غير موجودة'}), 404
        
        if not invoice.is_posted:
            AuditLog.log_action(
                user_name=request.json.get('posted_by', 'system'),
                action='unpost',
                entity_type='invoice',
                entity_id=invoice_id,
                entity_number=(getattr(invoice, 'invoice_number', None) or str(getattr(invoice, 'id', '') or '')),
                success=False,
                error_message='الفاتورة غير مرحلة أصلاً',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            return jsonify({
                'success': False, 
                'message': 'الفاتورة غير مرحلة أصلاً'
            }), 400
        
        # Append reversal ledger movements (append-only)
        _append_safe_reversal_transactions_for_invoice_gold(
            invoice,
            created_by=posted_by,
            reason=f"Unpost invoice {getattr(invoice, 'invoice_number', None) or invoice.id}",
        )

        # إلغاء ترحيل قيود الفاتورة
        try:
            linked_jes = JournalEntry.query.filter_by(
                reference_type='invoice', reference_id=invoice_id, is_posted=True
            ).all()
            for _je in linked_jes:
                _je.is_posted = False
                _je.posted_at = None
                _je.posted_by = None
        except Exception:
            pass

        # إلغاء ترحيل السندات المرتبطة (وعكس حركات الخزينة النقدية)
        try:
            linked_vouchers = Voucher.query.filter_by(
                reference_type='invoice', reference_id=invoice_id
            ).all()
            for v in linked_vouchers:
                # عكس SafeBoxTransactions النقدية للسند
                try:
                    _append_safe_reversal_transactions_for_voucher(
                        v,
                        created_by=posted_by,
                        reason=f"Unpost invoice #{invoice_id} — reverse voucher {v.voucher_number}",
                    )
                except Exception:
                    pass
                # إلغاء ترحيل قيد السند
                if v.journal_entry_id:
                    _vje = JournalEntry.query.get(v.journal_entry_id)
                    if _vje and _vje.is_posted:
                        _vje.is_posted = False
                        _vje.posted_at = None
                        _vje.posted_by = None
                for _vje2 in JournalEntry.query.filter_by(
                    reference_type='voucher', reference_id=v.id, is_posted=True
                ).all():
                    _vje2.is_posted = False
                    _vje2.posted_at = None
                    _vje2.posted_by = None
                v.status = 'pending'
        except Exception:
            pass

        # إلغاء الترحيل
        invoice.is_posted = False
        invoice.posted_at = None
        invoice.posted_by = None
        
        # تسجيل العملية الناجحة
        posted_by = g.current_user.username if hasattr(g, 'current_user') else 'system'
        AuditLog.log_action(
            user_name=posted_by,
            action='unpost',
            entity_type='invoice',
            entity_id=invoice_id,
            entity_number=(getattr(invoice, 'invoice_number', None) or str(getattr(invoice, 'id', '') or '')),
            details=json.dumps({
                'invoice_type': invoice.invoice_type,
                'total': float(invoice.total or 0)
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.commit()  # Commit بعد تسجيل الـ Audit Log
        
        return jsonify({
            'success': True,
            'message': 'تم إلغاء ترحيل الفاتورة',
            'invoice': invoice.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        AuditLog.log_action(
            user_name=request.json.get('posted_by', 'system'),
            action='unpost',
            entity_type='invoice',
            entity_id=invoice_id,
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': False, 'message': str(e)}), 500


# ==========================================
# ✅ ترحيل القيود
# ==========================================

@posting_bp.route('/journal-entries/post/<int:entry_id>', methods=['POST'])
@require_permission('journal.post')
def post_journal_entry(entry_id):
    """
    ترحيل قيد يومية
    
    يتطلب صلاحية: journal.post
    """
    try:
        posted_by = g.current_user.username
        
        entry = JournalEntry.query.get(entry_id)
        if not entry:
            return jsonify({'success': False, 'message': 'القيد غير موجود'}), 404
        
        if entry.is_deleted:
            return jsonify({'success': False, 'message': 'القيد محذوف'}), 400
        
        if entry.is_posted:
            return jsonify({
                'success': False, 
                'message': 'القيد مرحل بالفعل'
            }), 400

        # ⛔ منع ترحيل قيود الفواتير بشكل منفرد — يجب ترحيلها مع الفاتورة
        if getattr(entry, 'reference_type', None) == 'invoice':
            return jsonify({
                'success': False,
                'message': 'لا يمكن ترحيل قيد مرتبط بفاتورة بشكل منفرد. يرجى ترحيل الفاتورة من تبويب الفواتير.'
            }), 400
        
        # التحقق من التوازن قبل الترحيل (النظام يستخدم cash_debit/credit و karat debits/credits)
        total_cash_debit = sum(line.cash_debit or 0 for line in entry.lines if not line.is_deleted)
        total_cash_credit = sum(line.cash_credit or 0 for line in entry.lines if not line.is_deleted)
        
        # التحقق من توازن النقد
        if abs(total_cash_debit - total_cash_credit) > 0.01:  # هامش خطأ صغير
            return jsonify({
                'success': False,
                'message': f'القيد غير متوازن (نقد). مدين: {total_cash_debit}, دائن: {total_cash_credit}'
            }), 400
        
        # التحقق من توازن الذهب بعد التحويل للعيار الرئيسي (يدعم القيود متعددة العيارات)
        main_karat, debit_main, credit_main, diff_main = _journal_entry_gold_totals_main_karat(entry)
        if abs(diff_main) > 0.01:  # هامش خطأ صغير بالعيار الرئيسي
            return jsonify({
                'success': False,
                'message': (
                    f'القيد غير متوازن (ذهب بعد التحويل لعيار {int(round(main_karat))}). '
                    f'مدين: {round(debit_main, 3)}, دائن: {round(credit_main, 3)}'
                ),
                'details': {
                    'main_karat': int(round(main_karat)),
                    'debit_main_karat': round(debit_main, 6),
                    'credit_main_karat': round(credit_main, 6),
                    'diff_main_karat': round(diff_main, 6),
                },
            }), 400
        
        # ترحيل القيد
        entry.is_posted = True
        entry.posted_at = datetime.now()
        entry.posted_by = posted_by
        if hasattr(entry, 'is_draft'):
            entry.is_draft = False
        
        # تسجيل العملية الناجحة
        AuditLog.log_action(
            user_name=posted_by,
            action='post',
            entity_type='journal_entry',
            entity_id=entry_id,
            entity_number=entry.entry_number,
            details=json.dumps({
                'entry_type': entry.entry_type,
                'description': entry.description,
                'total_cash_debit': float(total_cash_debit),
                'total_cash_credit': float(total_cash_credit)
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.commit()  # Commit بعد تسجيل الـ Audit Log
        
        return jsonify({
            'success': True,
            'message': 'تم ترحيل القيد بنجاح',
            'entry': entry.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        AuditLog.log_action(
            user_name=g.current_user.username if g.current_user else 'النظام',
            action='post',
            entity_type='journal_entry',
            entity_id=entry_id,
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/journal-entries/post-batch', methods=['POST'])
@require_permission('journal.post')
def post_journal_entries_batch():
    """
    ترحيل مجموعة قيود
    
    Body:
    {
        "entry_ids": [1, 2, 3, ...]
    }
    
    يتطلب صلاحية: journal.post
    """
    try:
        posted_by = g.current_user.username
        data = request.get_json()
        entry_ids = data.get('entry_ids', [])
        
        if not entry_ids:
            return jsonify({'success': False, 'message': 'لم يتم تحديد أي قيود'}), 400
        
        entries = JournalEntry.query.filter(
            JournalEntry.id.in_(entry_ids),
            JournalEntry.is_deleted == False
        ).all()
        
        posted_count = 0
        skipped_count = 0
        errors = []
        
        for entry in entries:
            if not entry.is_posted:
                # ⛔ تخطي قيود الفواتير — يجب ترحيلها عبر بوابة ترحيل الفواتير
                if getattr(entry, 'reference_type', None) == 'invoice':
                    errors.append(f"القيد {entry.entry_number} مرتبط بفاتورة — يُرحَّل تلقائياً مع الفاتورة")
                    skipped_count += 1
                    continue

                # التحقق من التوازن (النقد)
                total_cash_debit = sum(line.cash_debit or 0 for line in entry.lines if not line.is_deleted)
                total_cash_credit = sum(line.cash_credit or 0 for line in entry.lines if not line.is_deleted)
                
                if abs(total_cash_debit - total_cash_credit) > 0.01:
                    errors.append(f"القيد {entry.entry_number} غير متوازن (نقد)")
                    skipped_count += 1
                    continue
                
                # التحقق من توازن الذهب بعد التحويل للعيار الرئيسي (يدعم القيود متعددة العيارات)
                main_karat, debit_main, credit_main, diff_main = _journal_entry_gold_totals_main_karat(entry)
                if abs(diff_main) > 0.01:
                    errors.append(
                        f"القيد {entry.entry_number} غير متوازن (ذهب بعد التحويل لعيار {int(round(main_karat))})"
                    )
                    skipped_count += 1
                    continue
                
                entry.is_posted = True
                entry.posted_at = datetime.now()
                entry.posted_by = posted_by
                if hasattr(entry, 'is_draft'):
                    entry.is_draft = False
                posted_count += 1
                
                # تسجيل كل عملية ناجحة
                AuditLog.log_action(
                    user_name=posted_by,
                    action='post',
                    entity_type='journal_entry',
                    entity_id=entry.id,
                    entity_number=entry.entry_number,
                    details=json.dumps({'batch_operation': True}, ensure_ascii=False),
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent')
                )
            else:
                skipped_count += 1
        
        db.session.commit()
        
        # تسجيل العملية الجماعية
        AuditLog.log_action(
            user_name=posted_by,
            action='post_batch',
            entity_type='journal_entry',
            entity_id=0,  # batch operation
            details=json.dumps({
                'total_entries': len(entry_ids),
                'posted_count': posted_count,
                'skipped_count': skipped_count,
                'errors': errors
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        return jsonify({
            'success': True,
            'message': f'تم ترحيل {posted_count} قيد، تم تخطي {skipped_count}',
            'posted_count': posted_count,
            'skipped_count': skipped_count,
            'errors': errors
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/journal-entries/unpost/<int:entry_id>', methods=['POST'])
@require_permission('journal.unpost')
def unpost_journal_entry(entry_id):
    """
    إلغاء ترحيل قيد
    
    يتطلب صلاحية: journal.unpost
    ⚠️ تحذير: هذا الإجراء حساس ويجب استخدامه بحذر
    """
    try:
        # Check server-side allow_unposting setting
        try:
            _unpost_settings = Settings.query.first()
            if _unpost_settings and not bool(getattr(_unpost_settings, 'allow_unposting', False)):
                return jsonify({
                    'success': False,
                    'message': 'إلغاء الترحيل معطّل في إعدادات النظام'
                }), 403
        except Exception:
            pass

        posted_by = g.current_user.username
        entry = JournalEntry.query.get(entry_id)
        
        if not entry:
            AuditLog.log_action(
                user_name=posted_by,
                action='unpost',
                entity_type='journal_entry',
                entity_id=entry_id,
                success=False,
                error_message='القيد غير موجود',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            return jsonify({'success': False, 'message': 'القيد غير موجود'}), 404
        
        if entry.is_deleted:
            AuditLog.log_action(
                user_name=posted_by,
                action='unpost',
                entity_type='journal_entry',
                entity_id=entry_id,
                entity_number=entry.entry_number,
                success=False,
                error_message='القيد محذوف',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            return jsonify({'success': False, 'message': 'القيد محذوف'}), 400
        
        if not entry.is_posted:
            AuditLog.log_action(
                user_name=posted_by,
                action='unpost',
                entity_type='journal_entry',
                entity_id=entry_id,
                entity_number=entry.entry_number,
                success=False,
                error_message='القيد غير مرحل أصلاً',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )
            return jsonify({
                'success': False, 
                'message': 'القيد غير مرحل أصلاً'
            }), 400
        
        # إلغاء الترحيل
        entry.is_posted = False
        entry.posted_at = None
        entry.posted_by = None
        
        # تسجيل العملية الناجحة
        AuditLog.log_action(
            user_name=posted_by,
            action='unpost',
            entity_type='journal_entry',
            entity_id=entry_id,
            entity_number=entry.entry_number,
            details=json.dumps({
                'entry_type': entry.entry_type,
                'description': entry.description
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.commit()  # Commit بعد تسجيل الـ Audit Log
        
        return jsonify({
            'success': True,
            'message': 'تم إلغاء ترحيل القيد',
            'entry': entry.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        posted_by = request.json.get('posted_by', 'system') if request.json else 'system'
        AuditLog.log_action(
            user_name=posted_by,
            action='unpost',
            entity_type='journal_entry',
            entity_id=entry_id,
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': False, 'message': str(e)}), 500


# ==========================================
# � إلغاء الترحيل الجماعي
# ==========================================

@posting_bp.route('/invoices/unpost-batch', methods=['POST'])
@require_permission('invoice.unpost')
def unpost_invoices_batch():
    """إلغاء ترحيل مجموعة فواتير — يتطلب allow_unposting=True في الإعدادات"""
    try:
        _us = Settings.query.first()
        if _us and not bool(getattr(_us, 'allow_unposting', False)):
            return jsonify({'success': False, 'message': 'إلغاء الترحيل معطّل في إعدادات النظام'}), 403

        posted_by = g.current_user.username
        data = request.get_json()
        invoice_ids = data.get('invoice_ids', [])

        if not invoice_ids:
            return jsonify({'success': False, 'message': 'لم يتم تحديد أي فواتير'}), 400

        invoices = Invoice.query.filter(Invoice.id.in_(invoice_ids), Invoice.is_posted == True).all()
        unposted_count = 0

        for invoice in invoices:
            _append_safe_reversal_transactions_for_invoice_gold(
                invoice, created_by=posted_by,
                reason=f"Batch unpost {getattr(invoice, 'invoice_number', None) or invoice.id}",
            )
            # إلغاء قيود الفاتورة
            try:
                for _je in JournalEntry.query.filter_by(
                    reference_type='invoice', reference_id=invoice.id, is_posted=True
                ).all():
                    _je.is_posted = False
                    _je.posted_at = None
                    _je.posted_by = None
            except Exception:
                pass
            # إلغاء السندات وقيودها وعكس حركات الخزينة النقدية
            try:
                for _v in Voucher.query.filter_by(
                    reference_type='invoice', reference_id=invoice.id
                ).all():
                    try:
                        _append_safe_reversal_transactions_for_voucher(
                            _v, created_by=posted_by,
                            reason=f"Batch unpost invoice #{invoice.id} — reverse voucher {_v.voucher_number}",
                        )
                    except Exception:
                        pass
                    if _v.journal_entry_id:
                        _vje = JournalEntry.query.get(_v.journal_entry_id)
                        if _vje and _vje.is_posted:
                            _vje.is_posted = False
                            _vje.posted_at = None
                            _vje.posted_by = None
                    for _vje2 in JournalEntry.query.filter_by(
                        reference_type='voucher', reference_id=_v.id, is_posted=True
                    ).all():
                        _vje2.is_posted = False
                        _vje2.posted_at = None
                        _vje2.posted_by = None
                    _v.status = 'pending'
            except Exception:
                pass

            invoice.is_posted = False
            invoice.posted_at = None
            invoice.posted_by = None
            unposted_count += 1

            AuditLog.log_action(
                user_name=posted_by, action='unpost', entity_type='invoice',
                entity_id=invoice.id,
                entity_number=getattr(invoice, 'invoice_number', None) or str(invoice.id),
                details='{"batch_operation": true}',
                ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'),
            )

        db.session.commit()
        return jsonify({'success': True, 'message': f'تم إلغاء ترحيل {unposted_count} فاتورة',
                        'unposted_count': unposted_count}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/journal-entries/unpost-batch', methods=['POST'])
@require_permission('journal.unpost')
def unpost_journal_entries_batch():
    """إلغاء ترحيل مجموعة قيود — يتطلب allow_unposting=True في الإعدادات"""
    try:
        _us = Settings.query.first()
        if _us and not bool(getattr(_us, 'allow_unposting', False)):
            return jsonify({'success': False, 'message': 'إلغاء الترحيل معطّل في إعدادات النظام'}), 403

        posted_by = g.current_user.username
        data = request.get_json()
        entry_ids = data.get('entry_ids', [])

        if not entry_ids:
            return jsonify({'success': False, 'message': 'لم يتم تحديد أي قيود'}), 400

        entries = JournalEntry.query.filter(
            JournalEntry.id.in_(entry_ids),
            JournalEntry.is_posted == True,
            JournalEntry.is_deleted == False,
        ).all()

        unposted_count = 0
        for entry in entries:
            entry.is_posted = False
            entry.posted_at = None
            entry.posted_by = None
            unposted_count += 1
            AuditLog.log_action(
                user_name=posted_by, action='unpost', entity_type='journal_entry',
                entity_id=entry.id, entity_number=entry.entry_number,
                details='{"batch_operation": true}',
                ip_address=request.remote_addr, user_agent=request.headers.get('User-Agent'),
            )

        db.session.commit()
        return jsonify({'success': True, 'message': f'تم إلغاء ترحيل {unposted_count} قيد',
                        'unposted_count': unposted_count}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ==========================================
# �📊 إحصائيات الترحيل
# ==========================================

@posting_bp.route('/posting/stats', methods=['GET'])
@optional_auth
def get_posting_stats():
    """عرض إحصائيات الترحيل (لا يتطلب صلاحيات)"""
    try:
        # فواتير معلّقة للموافقة: غير مرحّلة + يوجد تنبيه موافقة غير مراجَع لها
        pending_approval_ids = set(
            r[0] for r in db.session.query(SystemAlert.entity_id).filter(
                SystemAlert.entity_type == 'Invoice',
                SystemAlert.alert_type == 'invoice_approval',
                SystemAlert.is_reviewed == False,
            ).all()
        )
        stats = {
            'invoices': {
                'total': Invoice.query.count(),
                'posted': Invoice.query.filter_by(is_posted=True).count(),
                'unposted': Invoice.query.filter_by(is_posted=False).count(),
                'pending_approval': len(pending_approval_ids),
            },
            'journal_entries': {
                'total': JournalEntry.query.filter_by(is_deleted=False).count(),
                'posted': JournalEntry.query.filter_by(is_posted=True, is_deleted=False).count(),
                'unposted': JournalEntry.query.filter_by(is_posted=False, is_deleted=False).count(),
            },
        }

        return jsonify({
            'success': True,
            'stats': stats
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ==========================================
# 📋 سجل التدقيق (Audit Log)
# ==========================================

@posting_bp.route('/audit-logs', methods=['GET'])
@require_permission('audit.view')
def get_audit_logs():
    """
    عرض سجلات التدقيق
    
    يتطلب صلاحية: audit.view
    
    Query Parameters:
    - limit: عدد السجلات (افتراضي 100)
    - user_name: تصفية حسب اسم المستخدم
    - action: تصفية حسب نوع العملية
    - entity_type: تصفية حسب نوع الكيان
    - entity_id: تصفية حسب معرف الكيان
    - success: تصفية حسب النجاح/الفشل (true/false)
    - from_date: من تاريخ (ISO format)
    - to_date: إلى تاريخ (ISO format)
    """
    try:
        # البارامترات
        limit = request.args.get('limit', 100, type=int)
        user_name = request.args.get('user_name')
        action = request.args.get('action')
        entity_type = request.args.get('entity_type')
        entity_id = request.args.get('entity_id', type=int)
        success = request.args.get('success')
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
        
        # بناء الاستعلام
        query = AuditLog.query
        
        if user_name:
            query = query.filter(AuditLog.user_name.like(f'%{user_name}%'))
        
        if action:
            query = query.filter_by(action=action)
        
        if entity_type:
            query = query.filter_by(entity_type=entity_type)
        
        if entity_id:
            query = query.filter_by(entity_id=entity_id)
        
        if success is not None:
            success_bool = success.lower() == 'true'
            query = query.filter_by(success=success_bool)
        
        if from_date:
            try:
                from_dt = datetime.fromisoformat(from_date)
                query = query.filter(AuditLog.timestamp >= from_dt)
            except:
                pass
        
        if to_date:
            try:
                to_dt = datetime.fromisoformat(to_date)
                query = query.filter(AuditLog.timestamp <= to_dt)
            except:
                pass
        
        # الترتيب والحد الأقصى
        logs = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()
        
        return jsonify({
            'success': True,
            'count': len(logs),
            'logs': [log.to_dict() for log in logs]
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/audit-logs/<int:log_id>', methods=['GET'])
@require_permission('audit.view')
def get_audit_log_detail(log_id):
    """الحصول على تفاصيل سجل تدقيق معين"""
    try:
        log = AuditLog.query.get(log_id)
        if not log:
            return jsonify({'success': False, 'message': 'السجل غير موجود'}), 404
        
        return jsonify({
            'success': True,
            'log': log.to_dict(include_details=True)
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/audit-logs/entity/<entity_type>/<int:entity_id>', methods=['GET'])
@require_permission('audit.view')
def get_audit_logs_by_entity(entity_type, entity_id):
    """الحصول على جميع سجلات التدقيق لكيان معين"""
    try:
        logs = AuditLog.get_logs_by_entity(entity_type, entity_id)
        
        return jsonify({
            'success': True,
            'count': len(logs),
            'entity_type': entity_type,
            'entity_id': entity_id,
            'logs': [log.to_dict() for log in logs]
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/audit-logs/user/<user_name>', methods=['GET'])
@require_permission('audit.view')
def get_audit_logs_by_user(user_name):
    """الحصول على سجلات مستخدم معين"""
    try:
        limit = request.args.get('limit', 100, type=int)
        logs = AuditLog.get_logs_by_user(user_name, limit=limit)
        
        return jsonify({
            'success': True,
            'count': len(logs),
            'user_name': user_name,
            'logs': [log.to_dict() for log in logs]
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/audit-logs/failed', methods=['GET'])
@require_permission('audit.view')
def get_failed_audit_logs():
    """الحصول على العمليات الفاشلة"""
    try:
        limit = request.args.get('limit', 50, type=int)
        logs = AuditLog.get_failed_logs(limit=limit)
        
        return jsonify({
            'success': True,
            'count': len(logs),
            'logs': [log.to_dict() for log in logs]
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/audit-logs/stats', methods=['GET'])
@require_permission('audit.view')
def get_audit_stats():
    """إحصائيات سجل التدقيق"""
    try:
        from sqlalchemy import func
        
        # إجمالي السجلات
        total_logs = AuditLog.query.count()
        
        # السجلات الناجحة والفاشلة
        successful = AuditLog.query.filter_by(success=True).count()
        failed = AuditLog.query.filter_by(success=False).count()
        
        # أكثر العمليات تكراراً
        top_actions = db.session.query(
            AuditLog.action,
            func.count(AuditLog.id).label('count')
        ).group_by(AuditLog.action).order_by(func.count(AuditLog.id).desc()).limit(10).all()
        
        # أكثر المستخدمين نشاطاً
        top_users = db.session.query(
            AuditLog.user_name,
            func.count(AuditLog.id).label('count')
        ).group_by(AuditLog.user_name).order_by(func.count(AuditLog.id).desc()).limit(10).all()
        
        # السجلات اليوم
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        logs_today = AuditLog.query.filter(AuditLog.timestamp >= today_start).count()
        
        stats = {
            'total_logs': total_logs,
            'successful': successful,
            'failed': failed,
            'logs_today': logs_today,
            'top_actions': [{'action': action, 'count': count} for action, count in top_actions],
            'top_users': [{'user_name': user, 'count': count} for user, count in top_users]
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ==========================================
# 📝 نظام الموافقة على السندات (Voucher Approval)
# ==========================================

@posting_bp.route('/vouchers/pending', methods=['GET'])
@require_permission('voucher.view')
def get_pending_vouchers():
    """عرض جميع السندات بانتظار الموافقة"""
    try:
        from models import Voucher
        
        vouchers = Voucher.query.filter_by(
            status='pending'
        ).order_by(Voucher.date.desc()).all()
        
        return jsonify({
            'success': True,
            'count': len(vouchers),
            'vouchers': [v.to_dict() for v in vouchers]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/vouchers/approved', methods=['GET'])
@require_permission('voucher.view')
def get_approved_vouchers():
    """عرض جميع السندات الموافق عليها"""
    try:
        from models import Voucher
        
        vouchers = Voucher.query.filter_by(
            status='approved'
        ).order_by(Voucher.date.desc()).all()
        
        return jsonify({
            'success': True,
            'count': len(vouchers),
            'vouchers': [v.to_dict() for v in vouchers]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/vouchers/rejected', methods=['GET'])
@require_permission('voucher.view')
def get_rejected_vouchers():
    """عرض جميع السندات المرفوضة"""
    try:
        from models import Voucher
        
        vouchers = Voucher.query.filter_by(
            status='rejected'
        ).order_by(Voucher.date.desc()).all()
        
        return jsonify({
            'success': True,
            'count': len(vouchers),
            'vouchers': [v.to_dict() for v in vouchers]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/vouchers/approve/<int:voucher_id>', methods=['POST'])
@require_permission('voucher.approve')
def approve_voucher(voucher_id):
    """
    الموافقة على سند
    
    يتطلب صلاحية: voucher.approve
    """
    try:
        from models import Voucher
        # Reuse canonical posting logic from main routes.
        from routes import create_journal_entry_from_voucher, _append_safe_transactions_for_voucher
        
        approved_by = g.current_user.username
        
        voucher = Voucher.query.get(voucher_id)
        if not voucher:
            return jsonify({'success': False, 'message': 'السند غير موجود'}), 404
        
        if voucher.status == 'approved':
            return jsonify({
                'success': False,
                'message': 'السند موافق عليه بالفعل'
            }), 400
        
        if voucher.status == 'cancelled':
            return jsonify({
                'success': False,
                'message': 'لا يمكن الموافقة على سند ملغى'
            }), 400

        # If voucher is already linked to a journal entry, do not create a new one.
        # Still ensure SafeBoxTransaction exists (idempotent).
        if getattr(voucher, 'journal_entry_id', None):
            voucher.status = 'approved'
            voucher.approved_at = datetime.now()
            voucher.approved_by = approved_by
            _append_safe_transactions_for_voucher(voucher, created_by=approved_by)
            db.session.commit()
            return jsonify({
                'success': True,
                'message': 'تم الموافقة على السند بنجاح',
                'voucher': voucher.to_dict()
            }), 200
        
        # Canonical behavior: approving a voucher posts it (creates JournalEntry + SafeBoxTransaction).
        journal_entry = create_journal_entry_from_voucher(voucher)
        if not journal_entry:
            return jsonify({'success': False, 'message': 'فشل إنشاء القيد المحاسبي من السند'}), 500

        voucher.status = 'approved'
        voucher.approved_at = datetime.now()
        voucher.approved_by = approved_by
        voucher.journal_entry_id = journal_entry.id

        _append_safe_transactions_for_voucher(voucher, created_by=approved_by)
        
        # تسجيل العملية
        AuditLog.log_action(
            user_name=approved_by,
            action='voucher_approve',
            entity_type='voucher',
            entity_id=voucher_id,
            entity_number=voucher.voucher_number,
            details=json.dumps({
                'voucher_type': voucher.voucher_type,
                'amount_cash': float(voucher.amount_cash or 0),
                'amount_gold': float(voucher.amount_gold or 0),
                'description': voucher.description
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم الموافقة على السند بنجاح',
            'voucher': voucher.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        AuditLog.log_action(
            user_name=g.current_user.username if g.current_user else 'النظام',
            action='voucher_approve',
            entity_type='voucher',
            entity_id=voucher_id,
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/vouchers/reject/<int:voucher_id>', methods=['POST'])
@require_permission('voucher.approve')
def reject_voucher(voucher_id):
    """
    رفض سند
    
    يتطلب صلاحية: voucher.approve
    
    Body:
    {
        "rejection_reason": "سبب الرفض"
    }
    """
    try:
        from models import Voucher
        
        data = request.get_json()
        rejected_by = g.current_user.username
        rejection_reason = data.get('rejection_reason', '')
        
        if not rejection_reason:
            return jsonify({
                'success': False,
                'message': 'يجب تحديد سبب الرفض'
            }), 400
        
        voucher = Voucher.query.get(voucher_id)
        if not voucher:
            return jsonify({'success': False, 'message': 'السند غير موجود'}), 404
        
        if voucher.status == 'rejected':
            return jsonify({
                'success': False,
                'message': 'السند مرفوض بالفعل'
            }), 400
        
        if voucher.status == 'cancelled':
            return jsonify({
                'success': False,
                'message': 'لا يمكن رفض سند ملغى'
            }), 400
        
        # رفض السند
        voucher.status = 'rejected'
        voucher.rejected_at = datetime.now()
        voucher.rejected_by = rejected_by
        voucher.rejection_reason = rejection_reason
        
        # تسجيل العملية
        AuditLog.log_action(
            user_name=rejected_by,
            action='voucher_reject',
            entity_type='voucher',
            entity_id=voucher_id,
            entity_number=voucher.voucher_number,
            details=json.dumps({
                'voucher_type': voucher.voucher_type,
                'rejection_reason': rejection_reason,
                'amount_cash': float(voucher.amount_cash or 0),
                'amount_gold': float(voucher.amount_gold or 0)
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم رفض السند',
            'voucher': voucher.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        AuditLog.log_action(
            user_name=g.current_user.username if g.current_user else 'النظام',
            action='voucher_reject',
            entity_type='voucher',
            entity_id=voucher_id,
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/vouchers/approve/batch', methods=['POST'])
@require_permission('voucher.approve')
def approve_vouchers_batch():
    """
    الموافقة على مجموعة سندات دفعة واحدة
    
    Body:
    {
        "voucher_ids": [1, 2, 3, ...]
    }
    """
    try:
        from models import Voucher
        from routes import create_journal_entry_from_voucher, _append_safe_transactions_for_voucher
        
        data = request.get_json()
        approved_by = g.current_user.username
        voucher_ids = data.get('voucher_ids', [])
        
        if not voucher_ids:
            return jsonify({
                'success': False,
                'message': 'لم يتم تحديد أي سندات'
            }), 400
        
        approved_count = 0
        errors = []
        
        for voucher_id in voucher_ids:
            try:
                voucher = Voucher.query.get(voucher_id)
                if not voucher:
                    errors.append(f'السند {voucher_id} غير موجود')
                    continue

                if voucher.status != 'pending':
                    errors.append(f'السند {voucher.voucher_number} ليس بانتظار الموافقة')
                    continue

                # Post voucher: create JE if missing, then SafeBoxTransaction.
                journal_entry_id = getattr(voucher, 'journal_entry_id', None)
                if not journal_entry_id:
                    journal_entry = create_journal_entry_from_voucher(voucher)
                    if not journal_entry:
                        errors.append(f'فشل إنشاء القيد المحاسبي للسند {voucher.voucher_number}')
                        db.session.rollback()
                        continue
                    voucher.journal_entry_id = journal_entry.id

                voucher.status = 'approved'
                voucher.approved_at = datetime.now()
                voucher.approved_by = approved_by

                _append_safe_transactions_for_voucher(voucher, created_by=approved_by)

                db.session.commit()
                approved_count += 1

            except Exception as e:
                db.session.rollback()
                errors.append(f'خطأ في السند {voucher_id}: {str(e)}')
        
        # تسجيل العملية الجماعية
        AuditLog.log_action(
            user_name=approved_by,
            action='batch_voucher_approve',
            entity_type='voucher',
            entity_id=0,
            details=json.dumps({
                'approved_count': approved_count,
                'voucher_ids': voucher_ids,
                'errors': errors
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        # Note: we commit per voucher above to avoid rolling back the whole batch on a single failure.
        
        return jsonify({
            'success': True,
            'message': f'تم الموافقة على {approved_count} سند',
            'approved_count': approved_count,
            'errors': errors
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/vouchers/unapprove/<int:voucher_id>', methods=['POST'])
@require_permission('voucher.approve')
def unapprove_voucher(voucher_id):
    """
    إلغاء الموافقة على سند
    
    يتطلب صلاحية: voucher.approve
    """
    try:
        from models import Voucher
        
        unapproved_by = g.current_user.username
        
        voucher = Voucher.query.get(voucher_id)
        if not voucher:
            return jsonify({'success': False, 'message': 'السند غير موجود'}), 404
        
        if voucher.status != 'approved':
            return jsonify({
                'success': False,
                'message': 'السند ليس موافق عليه'
            }), 400
        
        # التحقق من أن السند لم يُستخدم في قيد محاسبي
        if voucher.journal_entry_id:
            return jsonify({
                'success': False,
                'message': 'لا يمكن إلغاء الموافقة لأن السند مرتبط بقيد محاسبي'
            }), 400
        
        # إلغاء الموافقة
        voucher.status = 'pending'
        voucher.approved_at = None
        voucher.approved_by = None
        
        # تسجيل العملية
        AuditLog.log_action(
            user_name=unapproved_by,
            action='voucher_unapprove',
            entity_type='voucher',
            entity_id=voucher_id,
            entity_number=voucher.voucher_number,
            details=json.dumps({
                'voucher_type': voucher.voucher_type,
                'amount_cash': float(voucher.amount_cash or 0),
                'amount_gold': float(voucher.amount_gold or 0)
            }, ensure_ascii=False),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم إلغاء الموافقة على السند',
            'voucher': voucher.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        AuditLog.log_action(
            user_name=g.current_user.username if g.current_user else 'النظام',
            action='voucher_unapprove',
            entity_type='voucher',
            entity_id=voucher_id,
            success=False,
            error_message=str(e),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        return jsonify({'success': False, 'message': str(e)}), 500


@posting_bp.route('/vouchers/stats', methods=['GET'])
@require_permission('voucher.view')
def get_vouchers_stats():
    """إحصائيات السندات"""
    try:
        from models import Voucher
        
        # العدد حسب الحالة
        pending_count = Voucher.query.filter_by(status='pending').count()
        approved_count = Voucher.query.filter_by(status='approved').count()
        rejected_count = Voucher.query.filter_by(status='rejected').count()
        cancelled_count = Voucher.query.filter_by(status='cancelled').count()
        
        # العدد حسب النوع
        receipt_count = Voucher.query.filter_by(voucher_type='receipt').count()
        payment_count = Voucher.query.filter_by(voucher_type='payment').count()
        
        stats = {
            'by_status': {
                'pending': pending_count,
                'approved': approved_count,
                'rejected': rejected_count,
                'cancelled': cancelled_count
            },
            'by_type': {
                'receipt': receipt_count,
                'payment': payment_count
            },
            'total': pending_count + approved_count + rejected_count + cancelled_count
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
