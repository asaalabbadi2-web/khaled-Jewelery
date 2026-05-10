"""
خدمة حساب المكافآت للموظفين
===================================

توفر وظائف لحساب المكافآت بناءً على القواعد المحددة والبيانات المتاحة.

ملاحظة مهمة:
- حساب مكافآت الأرباح يعتمد على الفواتير المرحلة (Invoice.is_posted=True)
  وعلى الربح النقدي المحسوب: profit = total - total_tax - total_cost - commission_amount.
- عند وجود مكافأة معتمدة لنفس الفترة، يمكن إنشاء مكافأة إضافية (Incremental)
  للفواتير الجديدة فقط (profit_based + profit_percentage) بدون تعديل المكافأة المعتمدة.
"""

from datetime import datetime, timedelta

from sqlalchemy import and_, func

from models import (
    BonusInvoiceLink,
    BonusRule,
    Employee,
    EmployeeBonus,
    Invoice,
    db,
    get_race_points_per_gram,
)


class BonusCalculator:
    """حاسبة المكافآت للموظفين"""

    @staticmethod
    def calculate_sales_bonus(employee, rule, period_start, period_end):
        """حساب مكافأة المبيعات (sales_target)."""
        try:
            period_start_dt = datetime.combine(period_start, datetime.min.time())
            period_end_dt = datetime.combine(period_end, datetime.max.time())
        except (TypeError, AttributeError):
            return None

        username = None
        if hasattr(employee, "user_account") and employee.user_account:
            username = employee.user_account.username
        if not username:
            return None

        sales_query = db.session.query(func.sum(Invoice.total)).filter(
            and_(
                Invoice.posted_by == username,
                Invoice.date >= period_start_dt,
                Invoice.date <= period_end_dt,
                Invoice.invoice_type == "بيع",
                Invoice.is_posted.is_(True),
            )
        )
        total_sales = sales_query.scalar() or 0.0

        conditions = rule.conditions or {}
        sales_target = conditions.get("sales_target", 0)
        if total_sales < sales_target:
            return None

        amount = 0.0
        if rule.bonus_type == "percentage":
            amount = employee.salary * (rule.bonus_value / 100)
        elif rule.bonus_type == "fixed":
            amount = rule.bonus_value
        elif rule.bonus_type == "sales_percentage":
            amount = total_sales * (rule.bonus_value / 100)

        if rule.min_bonus:
            amount = max(amount, rule.min_bonus)
        if rule.max_bonus:
            amount = min(amount, rule.max_bonus)

        calculation_data = {
            "sales_amount": total_sales,
            "sales_target": sales_target,
            "achievement_percentage": (total_sales / sales_target * 100) if sales_target > 0 else 0,
            "base_salary": employee.salary,
        }
        return amount, calculation_data

    @staticmethod
    def calculate_attendance_bonus(employee, rule, period_start, period_end):
        """حساب مكافأة الحضور (placeholder)."""
        conditions = rule.conditions or {}
        required_attendance = conditions.get("attendance_percentage", 95)
        actual_attendance = 100.0
        if actual_attendance < required_attendance:
            return None

        amount = 0.0
        if rule.bonus_type == "percentage":
            amount = employee.salary * (rule.bonus_value / 100)
        elif rule.bonus_type == "fixed":
            amount = rule.bonus_value

        if rule.min_bonus:
            amount = max(amount, rule.min_bonus)
        if rule.max_bonus:
            amount = min(amount, rule.max_bonus)

        calculation_data = {
            "attendance_percentage": actual_attendance,
            "required_attendance": required_attendance,
            "base_salary": employee.salary,
        }
        return amount, calculation_data

    @staticmethod
    def calculate_performance_bonus(employee, rule, period_start, period_end):
        """حساب مكافأة الأداء (placeholder)."""
        conditions = rule.conditions or {}
        required_rating = conditions.get("performance_rating", 4.0)
        actual_rating = 4.5
        if actual_rating < required_rating:
            return None

        amount = 0.0
        if rule.bonus_type == "percentage":
            amount = employee.salary * (rule.bonus_value / 100)
        elif rule.bonus_type == "fixed":
            amount = rule.bonus_value

        if rule.min_bonus:
            amount = max(amount, rule.min_bonus)
        if rule.max_bonus:
            amount = min(amount, rule.max_bonus)

        calculation_data = {
            "performance_rating": actual_rating,
            "required_rating": required_rating,
            "base_salary": employee.salary,
        }
        return amount, calculation_data

    @staticmethod
    def calculate_fixed_bonus(employee, rule, period_start, period_end):
        """حساب مكافأة ثابتة (fixed)."""
        amount = 0.0
        if rule.bonus_type == "percentage":
            amount = employee.salary * (rule.bonus_value / 100)
        elif rule.bonus_type == "fixed":
            amount = rule.bonus_value

        if rule.min_bonus:
            amount = max(amount, rule.min_bonus)
        if rule.max_bonus:
            amount = min(amount, rule.max_bonus)

        calculation_data = {"bonus_type": "fixed", "base_salary": employee.salary}
        return amount, calculation_data

    @staticmethod
    def calculate_profit_bonus(employee, rule, period_start, period_end):
        """حساب مكافأة الأرباح (profit_based)."""
        try:
            period_start_dt = datetime.combine(period_start, datetime.min.time())
            period_end_dt = datetime.combine(period_end, datetime.max.time())
        except (TypeError, AttributeError):
            return None

        username = None
        if hasattr(employee, "user_account") and employee.user_account:
            username = employee.user_account.username
        if not username:
            return None

        applicable_types = rule.applicable_invoice_types

        eligible_invoices_query = Invoice.query.filter(
            and_(
                Invoice.posted_by == username,
                Invoice.date >= period_start_dt,
                Invoice.date <= period_end_dt,
                Invoice.is_posted.is_(True),
            )
        )
        if applicable_types and len(applicable_types) > 0:
            eligible_invoices_query = eligible_invoices_query.filter(Invoice.invoice_type.in_(applicable_types))

        eligible_invoices = eligible_invoices_query.all()

        # نحسب الربح لكل فاتورة بنفس منطق السباق (profit_gold = وزن العيار الرئيسي)
        # حتى لا تُسقط فاتورة بخسارة مكافأة الفترة بالكامل.

        conditions = rule.conditions or {}
        min_profit = conditions.get("min_profit", 0)
        profit_type = conditions.get("profit_type", "cash")

        # ── نوع الفواتير التي تُعتبر "مشتريات" في سباق الأداء ──
        # شراء من عميل فقط (كسر) — لا تشمل شراء المورد
        PURCHASE_TYPES = {'شراء من عميل'}

        profitable_invoice_ids = []
        profitable_per_invoice_profit = []
        total_profit_cash = 0.0
        total_profit_gold = 0.0

        for inv in eligible_invoices:
            # ─ ربح ذهب: نفس الحقل الذي يستخدمه السباق ─
            inv_profit_gold = float(inv.profit_gold or 0.0)

            # ─ ربح نقدي ─
            if inv.invoice_type in PURCHASE_TYPES:
                # للمشتريات: الربح الحقيقي هو وزن الذهب المُقتنى (inv_profit_gold).
                # لا ربح نقدي صافٍ للمشتريات.
                inv_profit_cash = 0.0
            else:
                total_value = float(inv.total or 0)
                tax_value = float(inv.total_tax or 0)
                cost_value = float(inv.total_cost or 0)
                commission = float(inv.commission_amount or 0)
                inv_profit_cash = total_value - tax_value - cost_value - commission

            # ─ اختر قيمة الربح حسب نوع القاعدة ─
            if profit_type == "gold":
                profit_val = inv_profit_gold
            elif profit_type == "cash":
                profit_val = inv_profit_cash
            else:
                # "both": وزن للمشتريات + نقد للمبيعات
                profit_val = inv_profit_gold if inv.invoice_type in PURCHASE_TYPES else inv_profit_cash

            if profit_val > 0:
                profitable_invoice_ids.append(inv.id)
                profitable_per_invoice_profit.append(profit_val)
                total_profit_cash += inv_profit_cash
                total_profit_gold += inv_profit_gold

        invoice_count = len(profitable_invoice_ids)
        if invoice_count == 0:
            return None

        invoice_ids = profitable_invoice_ids
        per_invoice_profit = profitable_per_invoice_profit

        if profit_type == "cash":
            target_profit = total_profit_cash
        elif profit_type == "gold":
            # نحوّل الجرام لنقاط باستخدام إعداد سباق الأداء الديناميكي
            points_per_gram = get_race_points_per_gram()
            target_profit = total_profit_gold * points_per_gram
        else:
            target_profit = total_profit_cash + total_profit_gold

        if target_profit <= 0 or target_profit < min_profit:
            return None

        amount = 0.0
        if rule.bonus_type == "percentage":
            amount = employee.salary * (rule.bonus_value / 100)
        elif rule.bonus_type == "fixed":
            amount = rule.bonus_value
        elif rule.bonus_type == "profit_percentage":
            amount = target_profit * (rule.bonus_value / 100)

        if rule.min_bonus:
            amount = max(amount, rule.min_bonus)
        if rule.max_bonus:
            amount = min(amount, rule.max_bonus)

        calculation_data = {
            "total_profit_cash": total_profit_cash,
            "total_profit_gold": total_profit_gold,
            "target_profit": target_profit,
            "profit_type": profit_type,
            "points_per_gram": get_race_points_per_gram() if profit_type == "gold" else None,
            "invoice_count": invoice_count,
            "min_profit": min_profit,
            "base_salary": employee.salary,
            "applicable_invoice_types": applicable_types,
            "invoice_ids": invoice_ids,
            "per_invoice_profit": per_invoice_profit,
        }
        return amount, calculation_data

    @staticmethod
    def calculate_points_bonus(employee, rule, period_start, period_end):
        """حساب مكافأة النقاط (points_based) — تعتمد على نقاط سباق المبيعات."""
        conditions = rule.conditions or {}
        points_period = conditions.get("points_period", "month")
        min_points = float(conditions.get("min_points", 0))

        # تحديد حدود الفترة بناءً على إعداد القاعدة (وليس فترة الحساب الممررة)
        now = datetime.now()
        if points_period == "today":
            from datetime import date as _date
            start_dt = datetime.combine(_date.today(), datetime.min.time())
            end_dt = datetime.combine(_date.today(), datetime.max.time())
        elif points_period == "week":
            week_start = now.date() - timedelta(days=now.date().weekday())
            start_dt = datetime.combine(week_start, datetime.min.time())
            end_dt = datetime.combine(week_start + timedelta(days=6), datetime.max.time())
        else:  # month
            month_start = now.date().replace(day=1)
            start_dt = datetime.combine(month_start, datetime.min.time())
            end_dt = now

        # جلب معدل النقاط للجرام
        try:
            points_per_gram = get_race_points_per_gram()
        except Exception:
            points_per_gram = 10.0

        # نفس منطق اللوحة: بيع + شراء من عميل، profit_gold فقط
        RACE_TYPES = {"بيع", "شراء من عميل"}

        # ربط الموظف بالفواتير عبر employee_id أو user_account.username
        username = None
        if hasattr(employee, "user_account") and employee.user_account:
            username = employee.user_account.username

        invoice_filter = and_(
            Invoice.is_posted.is_(True),
            Invoice.invoice_type.in_(list(RACE_TYPES)),
            Invoice.date >= start_dt,
            Invoice.date <= end_dt,
        )

        # ابحث بـ employee_id أولاً ثم posted_by
        invoices = Invoice.query.filter(
            and_(invoice_filter, Invoice.employee_id == employee.id)
        ).all()

        if not invoices and username:
            invoices = Invoice.query.filter(
                and_(invoice_filter, Invoice.posted_by == username)
            ).all()

        total_profit_gold = sum(float(inv.profit_gold or 0.0) for inv in invoices if float(inv.profit_gold or 0.0) > 0)
        employee_points = int(round(total_profit_gold * points_per_gram))

        if employee_points < min_points:
            return None

        amount = 0.0
        if rule.bonus_type == "points_per_unit":
            amount = employee_points * rule.bonus_value
        elif rule.bonus_type == "fixed":
            amount = rule.bonus_value
        elif rule.bonus_type == "percentage":
            amount = employee.salary * (rule.bonus_value / 100)

        if rule.min_bonus:
            amount = max(amount, rule.min_bonus)
        if rule.max_bonus:
            amount = min(amount, rule.max_bonus)

        if amount <= 0:
            return None

        calculation_data = {
            "points_period": points_period,
            "points_per_gram": points_per_gram,
            "total_profit_gold_g": total_profit_gold,
            "employee_points": employee_points,
            "min_points": min_points,
            "bonus_type": rule.bonus_type,
            "invoice_count": len(invoices),
            "base_salary": employee.salary,
        }
        return amount, calculation_data

    @staticmethod
    def calculate_bonus(employee, rule, period_start, period_end):
        """حساب المكافأة بناءً على نوع القاعدة."""
        if not rule.is_active or not rule.is_valid_for_employee(employee):
            return None

        result = None
        if rule.rule_type == "sales_target":
            result = BonusCalculator.calculate_sales_bonus(employee, rule, period_start, period_end)
        elif rule.rule_type == "attendance":
            result = BonusCalculator.calculate_attendance_bonus(employee, rule, period_start, period_end)
        elif rule.rule_type == "performance":
            result = BonusCalculator.calculate_performance_bonus(employee, rule, period_start, period_end)
        elif rule.rule_type == "fixed":
            result = BonusCalculator.calculate_fixed_bonus(employee, rule, period_start, period_end)
        elif rule.rule_type == "profit_based":
            result = BonusCalculator.calculate_profit_bonus(employee, rule, period_start, period_end)
        elif rule.rule_type == "points_based":
            result = BonusCalculator.calculate_points_bonus(employee, rule, period_start, period_end)

        if not result:
            return None

        amount, calculation_data = result
        bonus = EmployeeBonus(
            employee_id=employee.id,
            bonus_rule_id=rule.id,
            bonus_type=rule.rule_type,
            amount=amount,
            period_start=period_start,
            period_end=period_end,
            calculation_data=calculation_data,
            status="pending",
            created_at=datetime.now(),
        )
        return bonus

    @staticmethod
    def calculate_all_bonuses_for_period(period_start, period_end, employee_ids=None, rule_ids=None, auto_approve=False, refresh_results=True):
        bonuses = []
        processed_bonus_ids = []

        employees_query = Employee.query.filter_by(is_active=True)
        if employee_ids:
            employees_query = employees_query.filter(Employee.id.in_(employee_ids))
        employees = employees_query.all()

        rules_query = BonusRule.query.filter_by(is_active=True)
        if rule_ids:
            rules_query = rules_query.filter(BonusRule.id.in_(rule_ids))
        rules = rules_query.all()

        def _sync_invoice_links(bonus_obj, invoice_ids):
            if invoice_ids is None:
                return
            BonusInvoiceLink.query.filter_by(bonus_id=bonus_obj.id).delete()
            for inv_id in invoice_ids:
                db.session.add(BonusInvoiceLink(bonus_id=bonus_obj.id, invoice_id=inv_id))

        def _linked_invoice_ids_for(employee_id, rule_id):
            bonus_ids = [
                b.id
                for b in EmployeeBonus.query.filter_by(
                    employee_id=employee_id,
                    bonus_rule_id=rule_id,
                    period_start=period_start,
                    period_end=period_end,
                ).all()
            ]
            if not bonus_ids:
                return set()
            links = BonusInvoiceLink.query.filter(BonusInvoiceLink.bonus_id.in_(bonus_ids)).all()
            return {l.invoice_id for l in links}

        for employee in employees:
            for rule in rules:
                existing_bonuses = EmployeeBonus.query.filter_by(
                    employee_id=employee.id,
                    bonus_rule_id=rule.id,
                    period_start=period_start,
                    period_end=period_end,
                ).all()

                # إذا وجد مكافأة معتمدة/مدفوعة مسبقاً لنفس الفترة، لا نعدلها
                # فقط نُعيدها في النتيجة
                immutable_existing = next((b for b in existing_bonuses if b.status in ("approved", "paid")), None)
                if immutable_existing and not auto_approve:
                    for b in existing_bonuses:
                        processed_bonus_ids.append(b.id)
                        bonuses.append(b)
                    continue

                # السلوك الافتراضي السابق: إذا يوجد مكافأة مرفوضة، لا تغيّرها
                if existing_bonuses and not auto_approve and any(b.status == "rejected" for b in existing_bonuses):
                    for b in existing_bonuses:
                        processed_bonus_ids.append(b.id)
                        bonuses.append(b)
                    continue

                # إذا كانت هناك مكافآت معلقة متعددة، نحذف القديمة ونحتفظ بواحدة فقط
                if len(existing_bonuses) > 1:
                    # نحذف جميع المكافآت المعلقة ما عدا الأحدث
                    existing_bonuses.sort(key=lambda x: x.id, reverse=True)
                    for old_bonus in existing_bonuses[1:]:
                        if old_bonus.status == "pending":
                            db.session.delete(old_bonus)

                existing = existing_bonuses[0] if existing_bonuses else None
                bonus = BonusCalculator.calculate_bonus(employee, rule, period_start, period_end)
                if not bonus:
                    continue

                target_status = "approved" if auto_approve else "pending"

                if existing:
                    existing.amount = bonus.amount
                    existing.calculation_data = bonus.calculation_data
                    existing.status = target_status
                    if auto_approve:
                        existing.approved_by = "system"
                        existing.approved_at = datetime.now()

                    invoice_ids = bonus.calculation_data.get("invoice_ids") if bonus.calculation_data else None
                    if invoice_ids is not None:
                        _sync_invoice_links(existing, invoice_ids)

                    processed_bonus_ids.append(existing.id)
                    bonuses.append(existing)
                else:
                    if auto_approve:
                        bonus.approve("system")
                    db.session.add(bonus)
                    db.session.flush()

                    invoice_ids = bonus.calculation_data.get("invoice_ids") if bonus.calculation_data else None
                    if invoice_ids is not None:
                        _sync_invoice_links(bonus, invoice_ids)

                    processed_bonus_ids.append(bonus.id)
                    bonuses.append(bonus)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"خطأ في حساب المكافآت: {e}")
            return []

        if refresh_results and processed_bonus_ids:
            bonuses = (
                EmployeeBonus.query.filter(EmployeeBonus.id.in_(processed_bonus_ids))
                .order_by(EmployeeBonus.employee_id.asc(), EmployeeBonus.bonus_rule_id.asc().nullsfirst())
                .all()
            )

        return bonuses

    @staticmethod
    def calculate_bonus_for_invoice(invoice_id):
        """حساب مكافأة تلقائية لفاتورة واحدة (غير مستخدم افتراضياً في المسارات الحالية)."""
        invoice = Invoice.query.get(invoice_id)
        print(f"\n🔍 calculate_bonus_for_invoice called for invoice #{invoice_id}")

        if not invoice:
            print("   ❌ Invoice not found")
            return None

        # هذا المسار يتطلب employee_id على invoice (قد لا يكون متوفر في هذا المشروع)
        if not getattr(invoice, "employee_id", None):
            print("   ❌ No employee_id assigned to invoice")
            return None

        profit_cash = float(invoice.profit_cash) if invoice.profit_cash else 0.0
        if profit_cash <= 0:
            return None

        rules = BonusRule.query.filter_by(is_active=True, rule_type="profit_based").all()
        applicable_rules = []
        for rule in rules:
            if rule.target_employee_ids and invoice.employee_id not in rule.target_employee_ids:
                continue
            if rule.applicable_invoice_types and invoice.invoice_type not in rule.applicable_invoice_types:
                continue
            applicable_rules.append(rule)

        if not applicable_rules:
            return None

        rule = applicable_rules[0]
        bonus_percentage = rule.bonus_value
        bonus_amount = profit_cash * (bonus_percentage / 100.0)

        if rule.min_bonus and bonus_amount < rule.min_bonus:
            bonus_amount = rule.min_bonus
        if rule.max_bonus and bonus_amount > rule.max_bonus:
            bonus_amount = rule.max_bonus

        bonus = EmployeeBonus(
            employee_id=invoice.employee_id,
            bonus_rule_id=rule.id,
            amount=round(bonus_amount, 2),
            bonus_type="profit_based",
            period_start=invoice.date.date() if isinstance(invoice.date, datetime) else invoice.date,
            period_end=invoice.date.date() if isinstance(invoice.date, datetime) else invoice.date,
            status="pending",
            calculation_data={
                "invoice_id": invoice_id,
                "profit_cash": profit_cash,
                "bonus_percentage": bonus_percentage,
                "auto_calculated": True,
            },
        )

        db.session.add(bonus)
        db.session.flush()
        db.session.add(BonusInvoiceLink(bonus_id=bonus.id, invoice_id=invoice_id))
        db.session.commit()
        return bonus

    @staticmethod
    def get_employee_bonuses_summary(employee_id, start_date=None, end_date=None):
        query = EmployeeBonus.query.filter_by(employee_id=employee_id)
        if start_date:
            query = query.filter(EmployeeBonus.period_start >= start_date)
        if end_date:
            query = query.filter(EmployeeBonus.period_end <= end_date)

        bonuses = query.all()
        total_bonuses = sum(b.amount for b in bonuses if b.status in ["approved", "paid"])
        pending_bonuses = sum(b.amount for b in bonuses if b.status == "pending")
        paid_bonuses = sum(b.amount for b in bonuses if b.status == "paid")

        return {
            "total_bonuses": total_bonuses,
            "pending_bonuses": pending_bonuses,
            "paid_bonuses": paid_bonuses,
            "bonuses_count": len(bonuses),
            "bonuses": [b.to_dict(include_employee=False, include_rule=True) for b in bonuses],
        }
