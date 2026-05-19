"""
Routes لنظام المكافآت للموظفين
====================================

Endpoints:
- GET/POST /api/employees - إدارة الموظفين (النظام الأساسي)
- GET/PUT /api/bonus/employees - إدارة الموظفين (نظام المكافآت)
- GET/POST/PUT/DELETE /api/bonus-rules - إدارة قواعد المكافآت
- GET /api/invoice-types - الحصول على قائمة أنواع الفواتير المتاحة
- GET/POST /api/bonuses - إدارة المكافآت
- POST /api/bonuses/calculate - حساب المكافآت لفترة محددة
- POST /api/bonuses/<id>/approve - اعتماد مكافأة
- POST /api/bonuses/<id>/reject - رفض مكافأة
- POST /api/bonuses/<id>/pay - تسجيل دفع مكافأة
"""

from flask import Blueprint, request, jsonify, g
from models import db, Employee, BonusRule, EmployeeBonus, Voucher, VoucherAccountLine, Account, Office, SafeBox, GoalAchievement
from bonus_calculator import BonusCalculator
from datetime import datetime, date
from auth_decorators import require_auth, require_permission, require_any_permission
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
from services.live_balances import live_balances_by_account_ids

bonus_bp = Blueprint('bonuses', __name__)


# ==========================================
# 👥 إدارة الموظفين (Employees)
# ==========================================

@bonus_bp.route('/bonus/employees', methods=['GET'])
@require_auth
def get_employees():
    """عرض جميع الموظفين"""
    try:
        include_bonuses = request.args.get('include_bonuses') == 'true'
        is_active = request.args.get('is_active')
        
        query = Employee.query
        
        if is_active is not None:
            query = query.filter_by(is_active=(is_active == 'true'))
        
        employees = query.order_by(Employee.employee_code).all()
        
        return jsonify({
            'success': True,
            'employees': [emp.to_dict(include_bonuses=include_bonuses) for emp in employees],
            'count': len(employees)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonus/employees/<int:employee_id>', methods=['GET'])
@require_auth
def get_employee(employee_id):
    """عرض موظف محدد"""
    try:
        employee = Employee.query.get_or_404(employee_id)
        
        include_bonuses = request.args.get('include_bonuses') == 'true'
        
        return jsonify({
            'success': True,
            'employee': employee.to_dict(include_bonuses=include_bonuses)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 404


# ❌ تم حذف create_employee() من هنا لأنه مكرر
# ✅ استخدم الدالة الأصلية في routes.py التي تولّد employee_code تلقائياً
# وتنشئ حساب محاسبي تلقائياً للموظف


@bonus_bp.route('/bonus/employees/<int:employee_id>', methods=['PUT'])
@require_auth
@require_permission('employee.update')
def update_employee(employee_id):
    """تحديث بيانات موظف"""
    try:
        employee = Employee.query.get_or_404(employee_id)
        data = request.get_json()
        
        # تحديث البيانات
        if 'full_name' in data:
            employee.name = data['full_name']  # استخدام name
        if 'position' in data:
            employee.job_title = data['position']  # استخدام job_title
        if 'department' in data:
            employee.department = data['department']
        if 'base_salary' in data:
            employee.salary = data['base_salary']  # استخدام salary
        if 'phone' in data:
            employee.phone = data['phone']
        if 'email' in data:
            employee.email = data['email']
        if 'national_id' in data:
            employee.national_id = data['national_id']
        if 'is_active' in data:
            employee.is_active = data['is_active']
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم تحديث بيانات الموظف بنجاح',
            'employee': employee.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ==========================================
# 📋 إدارة قواعد المكافآت (Bonus Rules)
# ==========================================

@bonus_bp.route('/bonus-rules', methods=['GET'])
@require_auth
def get_bonus_rules():
    """عرض جميع قواعد المكافآت"""
    try:
        is_active = request.args.get('is_active')
        rule_type = request.args.get('rule_type')
        
        query = BonusRule.query
        
        if is_active is not None:
            query = query.filter_by(is_active=(is_active == 'true'))
        
        if rule_type:
            query = query.filter_by(rule_type=rule_type)
        
        rules = query.order_by(BonusRule.created_at.desc()).all()
        
        return jsonify({
            'success': True,
            'rules': [rule.to_dict() for rule in rules],
            'count': len(rules)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonus-rules/<int:rule_id>', methods=['GET'])
@require_auth
def get_bonus_rule(rule_id):
    """عرض قاعدة مكافأة محددة"""
    try:
        rule = BonusRule.query.get_or_404(rule_id)
        
        return jsonify({
            'success': True,
            'rule': rule.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 404


@bonus_bp.route('/bonus-rules', methods=['POST'])
@require_auth
@require_any_permission('bonus_rule.create', 'bonus.calculate', 'bonus.approve')
def create_bonus_rule():
    """إنشاء قاعدة مكافأة جديدة"""
    try:
        data = request.get_json()
        
        # التحقق من البيانات المطلوبة
        required_fields = ['name', 'rule_type', 'bonus_type', 'bonus_value']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'message': f'الحقل {field} مطلوب'
                }), 400
        
        # تحويل التواريخ
        valid_from = None
        valid_to = None
        if data.get('valid_from'):
            valid_from = datetime.strptime(data['valid_from'], '%Y-%m-%d').date()
        if data.get('valid_to'):
            valid_to = datetime.strptime(data['valid_to'], '%Y-%m-%d').date()
        
        # 🔍 التحقق من صحة أنواع الفواتير المحددة
        valid_invoice_types = ['بيع', 'شراء من عميل', 'مرتجع بيع', 'مرتجع شراء', 'شراء', 'مرتجع شراء (مورد)']
        applicable_invoice_types = data.get('applicable_invoice_types')
        
        if applicable_invoice_types:
            invalid_types = [t for t in applicable_invoice_types if t not in valid_invoice_types]
            if invalid_types:
                return jsonify({
                    'success': False,
                    'message': f'أنواع فواتير غير صالحة: {", ".join(invalid_types)}',
                    'valid_types': valid_invoice_types
                }), 400
        
        # إنشاء القاعدة
        rule = BonusRule(
            name=data['name'],
            description=data.get('description'),
            rule_type=data['rule_type'],
            conditions=data.get('conditions'),
            bonus_type=data['bonus_type'],
            bonus_value=data['bonus_value'],
            min_bonus=data.get('min_bonus', 0.0),
            max_bonus=data.get('max_bonus'),
            target_departments=data.get('target_departments'),
            target_positions=data.get('target_positions'),
            target_employee_ids=data.get('target_employee_ids'),  # 🆕
            applicable_invoice_types=data.get('applicable_invoice_types'),  # 🆕
            is_active=data.get('is_active', True),
            valid_from=valid_from,
            valid_to=valid_to,
            created_by=data.get('created_by')
        )
        
        db.session.add(rule)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم إنشاء قاعدة المكافأة بنجاح',
            'rule': rule.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonus-rules/<int:rule_id>', methods=['PUT'])
@require_auth
@require_any_permission('bonus_rule.update', 'bonus.calculate', 'bonus.approve')
def update_bonus_rule(rule_id):
    """تحديث قاعدة مكافأة"""
    try:
        rule = BonusRule.query.get_or_404(rule_id)
        data = request.get_json()
        
        # 🔍 التحقق من صحة أنواع الفواتير إذا تم تحديثها
        valid_invoice_types = ['بيع', 'شراء من عميل', 'مرتجع بيع', 'مرتجع شراء', 'شراء', 'مرتجع شراء (مورد)']
        if 'applicable_invoice_types' in data and data['applicable_invoice_types']:
            invalid_types = [t for t in data['applicable_invoice_types'] if t not in valid_invoice_types]
            if invalid_types:
                return jsonify({
                    'success': False,
                    'message': f'أنواع فواتير غير صالحة: {", ".join(invalid_types)}',
                    'valid_types': valid_invoice_types
                }), 400
        
        # تحديث البيانات
        if 'name' in data:
            rule.name = data['name']
        if 'description' in data:
            rule.description = data['description']
        if 'rule_type' in data:
            rule.rule_type = data['rule_type']
        if 'conditions' in data:
            rule.conditions = data['conditions']
        if 'bonus_type' in data:
            rule.bonus_type = data['bonus_type']
        if 'bonus_value' in data:
            rule.bonus_value = data['bonus_value']
        if 'min_bonus' in data:
            rule.min_bonus = data['min_bonus']
        if 'max_bonus' in data:
            rule.max_bonus = data['max_bonus']
        if 'target_departments' in data:
            rule.target_departments = data['target_departments']
        if 'target_positions' in data:
            rule.target_positions = data['target_positions']
        if 'target_employee_ids' in data:  # 🆕
            rule.target_employee_ids = data['target_employee_ids']
        if 'applicable_invoice_types' in data:  # 🆕
            rule.applicable_invoice_types = data['applicable_invoice_types']
        if 'is_active' in data:
            rule.is_active = data['is_active']
        
        if data.get('valid_from'):
            rule.valid_from = datetime.strptime(data['valid_from'], '%Y-%m-%d').date()
        if data.get('valid_to'):
            rule.valid_to = datetime.strptime(data['valid_to'], '%Y-%m-%d').date()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم تحديث قاعدة المكافأة بنجاح',
            'rule': rule.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonus-rules/<int:rule_id>', methods=['DELETE'])
@require_auth
@require_any_permission('bonus_rule.delete', 'bonus.calculate', 'bonus.approve')
def delete_bonus_rule(rule_id):
    """حذف قاعدة مكافأة"""
    try:
        rule = BonusRule.query.get_or_404(rule_id)
        
        db.session.delete(rule)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم حذف قاعدة المكافأة بنجاح'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ==========================================
# 💰 إدارة المكافآت (Bonuses)
# ==========================================

@bonus_bp.route('/bonuses', methods=['GET'])
@require_auth
def get_bonuses():
    """عرض جميع المكافآت"""
    try:
        employee_id = request.args.get('employee_id', type=int)
        status = request.args.get('status')
        period_start = request.args.get('period_start')
        period_end = request.args.get('period_end')
        
        query = EmployeeBonus.query
        
        if employee_id:
            query = query.filter_by(employee_id=employee_id)
        
        if status:
            query = query.filter_by(status=status)
        
        if period_start:
            start_date = datetime.strptime(period_start, '%Y-%m-%d').date()
            query = query.filter(EmployeeBonus.period_start >= start_date)
        
        if period_end:
            end_date = datetime.strptime(period_end, '%Y-%m-%d').date()
            query = query.filter(EmployeeBonus.period_end <= end_date)
        
        bonuses = query.order_by(EmployeeBonus.created_at.desc()).all()
        
        total_amount = sum(b.amount for b in bonuses if b.status in ['approved', 'paid'])
        
        return jsonify({
            'success': True,
            'bonuses': [bonus.to_dict(include_employee=True, include_rule=True) for bonus in bonuses],
            'count': len(bonuses),
            'total_amount': total_amount
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonuses', methods=['POST'])
@require_auth
@require_any_permission('bonus.calculate', 'bonus.approve')
def create_bonus():
    """إنشاء مكافأة يدوية مباشرة (تُستخدم عند منح مكافأة الفائزين في السباق)"""
    try:
        data = request.get_json() or {}

        employee_id = data.get('employee_id')
        if not employee_id:
            return jsonify({'success': False, 'error': 'employee_id مطلوب'}), 400

        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({'success': False, 'error': 'الموظف غير موجود'}), 404

        amount = data.get('amount')
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'قيمة المبلغ غير صالحة'}), 400

        if amount <= 0:
            return jsonify({'success': False, 'error': 'يجب أن يكون المبلغ أكبر من صفر'}), 400

        bonus_type = data.get('bonus_type', 'fixed')
        status = data.get('status', 'pending')
        if status not in ('pending', 'approved'):
            status = 'pending'

        try:
            period_start = datetime.strptime(data['period_start'], '%Y-%m-%d').date()
            period_end = datetime.strptime(data['period_end'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            return jsonify({'success': False, 'error': 'period_start و period_end مطلوبان بصيغة YYYY-MM-DD'}), 400

        if period_end < period_start:
            return jsonify({'success': False, 'error': 'تاريخ النهاية يجب أن يكون بعد تاريخ البداية'}), 400

        bonus_rule_id = data.get('bonus_rule_id')
        if bonus_rule_id:
            rule = BonusRule.query.get(bonus_rule_id)
            if not rule:
                bonus_rule_id = None

        bonus = EmployeeBonus(
            employee_id=employee_id,
            bonus_rule_id=bonus_rule_id,
            bonus_type=bonus_type,
            amount=round(amount, 2),
            period_start=period_start,
            period_end=period_end,
            calculation_data=data.get('calculation_data'),
            status=status,
            notes=data.get('notes'),
            created_at=datetime.now(),
            created_by=getattr(g, 'username', None),
        )

        if status == 'approved':
            bonus.approved_by = getattr(g, 'username', 'system')
            bonus.approved_at = datetime.now()

        db.session.add(bonus)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'تم إنشاء المكافأة بنجاح',
            'bonus': bonus.to_dict(include_employee=True, include_rule=True),
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bonus_bp.route('/bonuses/<int:bonus_id>', methods=['GET'])
@require_auth
def get_bonus(bonus_id):
    """عرض مكافأة محددة"""
    try:
        bonus = EmployeeBonus.query.get_or_404(bonus_id)
        
        return jsonify({
            'success': True,
            'bonus': bonus.to_dict(include_employee=True, include_rule=True)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 404


@bonus_bp.route('/bonuses/<int:bonus_id>', methods=['PUT'])
@require_auth
@require_permission('bonus.calculate')
def update_bonus(bonus_id):
    """تعديل مكافأة معلقة قبل الاعتماد/الدفع"""
    try:
        bonus = EmployeeBonus.query.get_or_404(bonus_id)
        if bonus.status != 'pending':
            return jsonify({
                'success': False,
                'message': 'لا يمكن تعديل مكافأة غير معلقة'
            }), 400

        data = request.get_json() or {}

        # الحقول المسموح تعديلها قبل الاعتماد
        if 'amount' in data:
            amount = data.get('amount')
            try:
                bonus.amount = float(amount)
            except Exception:
                return jsonify({
                    'success': False,
                    'message': 'قيمة المبلغ غير صالحة'
                }), 400

        if 'notes' in data:
            bonus.notes = data.get('notes') or None

        if 'period_start' in data:
            try:
                bonus.period_start = datetime.strptime(data['period_start'], '%Y-%m-%d').date()
            except Exception:
                return jsonify({
                    'success': False,
                    'message': 'صيغة تاريخ البداية غير صحيحة'
                }), 400

        if 'period_end' in data:
            try:
                bonus.period_end = datetime.strptime(data['period_end'], '%Y-%m-%d').date()
            except Exception:
                return jsonify({
                    'success': False,
                    'message': 'صيغة تاريخ النهاية غير صحيحة'
                }), 400

        if bonus.period_start and bonus.period_end and bonus.period_end < bonus.period_start:
            return jsonify({
                'success': False,
                'message': 'تاريخ النهاية يجب أن يكون بعد تاريخ البداية'
            }), 400

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'تم تحديث المكافأة',
            'bonus': bonus.to_dict(include_employee=True, include_rule=True)
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonuses/calculate', methods=['POST'])
@require_auth
def calculate_bonuses():
    """حساب المكافآت لفترة محددة"""
    try:
        data = request.get_json() or {}

        # 🔐 الصلاحيات:
        # - admin أو من لديه bonus.calculate: يستطيع حساب مكافآت أي موظف/الجميع
        # - غير ذلك: يسمح بحساب مكافآت نفسه فقط (إذا كان AppUser مرتبط بموظف)
        current_user = getattr(g, 'current_user', None)
        can_calculate_all = bool(
            current_user
            and (
                getattr(current_user, 'is_admin', False)
                or (hasattr(current_user, 'has_permission') and current_user.has_permission('bonus.calculate'))
            )
        )

        # ⚙️ دعم كل من period_start/period_end والحقول القديمة date_from/date_to القادمة من الواجهة
        period_start_str = data.get('period_start') or data.get('date_from')
        period_end_str = data.get('period_end') or data.get('date_to')

        if not period_start_str or not period_end_str:
            return jsonify({
                'success': False,
                'message': 'يجب تحديد تاريخ البداية والنهاية'
            }), 400

        try:
            period_start = datetime.strptime(period_start_str, '%Y-%m-%d').date()
            period_end = datetime.strptime(period_end_str, '%Y-%m-%d').date()
        except Exception:
            return jsonify({
                'success': False,
                'message': 'صيغة التاريخ غير صحيحة، استخدم YYYY-MM-DD'
            }), 400
        auto_approve = data.get('auto_approve', False)

        # دعم employee_ids (list) و employee_id (single) القادم من Flutter
        employee_ids = data.get('employee_ids') if isinstance(data.get('employee_ids'), list) else None
        if employee_ids is None and isinstance(data.get('employee_id'), int):
            employee_ids = [data.get('employee_id')]

        # إن لم يكن لديه صلاحية عامة، احصر الحساب على موظفه فقط
        if not can_calculate_all:
            self_employee_id = getattr(current_user, 'employee_id', None) if current_user else None
            if not self_employee_id:
                return jsonify({
                    'success': False,
                    'message': 'ليس لديك صلاحية لحساب المكافآت',
                    'error': 'permission_denied',
                    'required_permission': 'bonus.calculate'
                }), 403
            employee_ids = [self_employee_id]

        rule_ids = data.get('rule_ids') if isinstance(data.get('rule_ids'), list) else None
        
        # حساب المكافآت
        bonuses = BonusCalculator.calculate_all_bonuses_for_period(
            period_start=period_start,
            period_end=period_end,
            employee_ids=employee_ids,
            rule_ids=rule_ids,
            auto_approve=auto_approve
        )
        
        total_amount = sum(b.amount for b in bonuses)
        
        return jsonify({
            'success': True,
            'message': f'تم حساب {len(bonuses)} مكافأة بنجاح',
            'bonuses': [bonus.to_dict(include_employee=True, include_rule=True) for bonus in bonuses],
            'count': len(bonuses),
            'total_amount': total_amount
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonuses/<int:bonus_id>/approve', methods=['POST'])
@require_auth
@require_permission('bonus.approve')
def approve_bonus(bonus_id):
    """
    اعتماد مكافأة مع إنشاء قيد محاسبي لإثبات المصروف والالتزام
    
    القيد المحاسبي:
    من ح/ مصروف مكافآت (5450)    مدين
      إلى ح/ مكافآت مستحقة (2310)  دائن
    """
    try:
        bonus = EmployeeBonus.query.get_or_404(bonus_id)
        data = request.get_json(silent=True) or {}
        
        if bonus.status != 'pending':
            return jsonify({
                'success': False,
                'message': 'لا يمكن اعتماد مكافأة غير معلقة'
            }), 400
        
        approved_by = data.get('approved_by', 'system')
        
        # البحث عن حساب مصروف المكافآت (5450)
        bonus_expense_account = Account.query.filter_by(account_number='5450').first()
        if not bonus_expense_account:
            return jsonify({
                'success': False,
                'message': 'حساب مصروف المكافآت غير موجود (5450)'
            }), 400
        
        # البحث عن حساب مكافآت مستحقة (2310)
        bonuses_payable_account = Account.query.filter_by(account_number='2310').first()
        if not bonuses_payable_account:
            return jsonify({
                'success': False,
                'message': 'حساب مكافآت مستحقة غير موجود (2310)'
            }), 400
        
        # إنشاء سند قيد لإثبات المصروف والالتزام
        employee = Employee.query.get(bonus.employee_id)
        voucher_number = f"BAPP-{bonus.id}"
        
        # التحقق من عدم وجود سند بنفس الرقم
        existing_voucher = Voucher.query.filter_by(voucher_number=voucher_number).first()
        if existing_voucher:
            return jsonify({
                'success': False,
                'message': f'سند الاعتماد موجود مسبقاً برقم {voucher_number}. لإعادة الاعتماد، يجب حذف السند الموجود أولاً.',
                'voucher_id': existing_voucher.id
            }), 409
        
        voucher = Voucher(
            voucher_number=voucher_number,
            voucher_type='adjustment',
            date=date.today(),
            description=f"اعتماد مكافأة {employee.name if employee else bonus.employee_id} - {bonus.bonus_type}",
            status='approved',
            created_by=approved_by,
        )
        db.session.add(voucher)
        db.session.flush()
        
        # السطر المدين: مصروف المكافآت
        debit_line = VoucherAccountLine(
            voucher_id=voucher.id,
            account_id=bonus_expense_account.id,
            line_type='debit',
            amount_type='cash',
            description=f"مصروف مكافأة {employee.name if employee else ''}",
            amount=bonus.amount,
        )
        db.session.add(debit_line)
        
        # السطر الدائن: مكافآت مستحقة
        credit_line = VoucherAccountLine(
            voucher_id=voucher.id,
            account_id=bonuses_payable_account.id,
            line_type='credit',
            amount_type='cash',
            description=f"استحقاق مكافأة {employee.name if employee else ''}",
            amount=bonus.amount,
        )
        db.session.add(credit_line)
        
        # اعتماد المكافأة
        bonus.approve(approved_by)
        bonus.payment_reference = voucher_number  # حفظ رقم سند الاستحقاق

        # 🎉 إنشاء سجل إنجاز تلقائي ليظهر للموظف كـ overlay احتفالية
        _create_achievement_for_bonus(bonus, employee)
        
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing_voucher = Voucher.query.filter_by(voucher_number=voucher_number).first()
            if existing_voucher:
                return jsonify({
                    'success': False,
                    'message': f'سند الاعتماد موجود مسبقاً برقم {voucher_number}. لإعادة الاعتماد، يجب حذف السند الموجود أولاً.',
                    'voucher_id': existing_voucher.id
                }), 409
            raise
        
        return jsonify({
            'success': True,
            'message': 'تم اعتماد المكافأة وإثبات المصروف بنجاح',
            'bonus': bonus.to_dict(include_employee=True, include_rule=True),
            'voucher': {
                'id': voucher.id,
                'voucher_number': voucher_number,
                'amount': bonus.amount
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


def _create_achievement_for_bonus(bonus: EmployeeBonus, employee):
    """
    ينشئ سجل GoalAchievement مرتبط بالمكافأة المعتمدة.
    يُستدعى تلقائياً من approve_bonus() قبل commit().
    
    - يبني اسم الهدف من نوع المكافأة أو من القاعدة إن وُجدت
    - يضع الـ metrics من calculation_data إن كانت موجودة
    - لا يرفع exception — الإنجاز اختياري ولا يعطّل الاعتماد
    """
    try:
        # لا تُنشئ إنجازاً مكرراً لنفس المكافأة
        existing = GoalAchievement.query.filter_by(bonus_id=bonus.id).first()
        if existing:
            return

        rule = bonus.rule
        goal_name = (rule.name if rule else None) or _bonus_type_label(bonus.bonus_type)
        goal_description = rule.description if rule else None

        # استخرج الـ metrics من calculation_data
        calc = bonus.calculation_data or {}
        metrics = {}
        for key in ('points', 'invoices', 'invoice_count', 'rank',
                    'sales_weight', 'total_sales', 'percentage'):
            val = calc.get(key)
            if val is not None:
                # normalize key names for the Flutter widget
                display_key = 'invoices' if key == 'invoice_count' else key
                metrics[display_key] = val

        achievement = GoalAchievement(
            employee_id=bonus.employee_id,
            bonus_rule_id=bonus.bonus_rule_id,
            bonus_id=bonus.id,
            goal_name=goal_name,
            goal_description=goal_description,
            bonus_amount=bonus.amount,
            metrics=metrics,
            achieved_at=bonus.approved_at or bonus.created_at,
        )
        db.session.add(achievement)
    except Exception as exc:
        # Non-fatal: log and continue
        import traceback
        traceback.print_exc()


def _bonus_type_label(bonus_type: str) -> str:
    labels = {
        'sales_target': 'هدف المبيعات',
        'attendance': 'مكافأة الحضور',
        'performance': 'مكافأة الأداء',
        'fixed': 'مكافأة ثابتة',
        'profit_based': 'مكافأة الأرباح',
        'goal_achieved': 'تحقيق هدف',
        'custom': 'مكافأة خاصة',
    }
    return labels.get(bonus_type, 'مكافأة معتمدة')


@bonus_bp.route('/bonuses/bulk/approve', methods=['POST'])
@bonus_bp.route('/bonuses/bulk-approve', methods=['POST'])
@require_auth
@require_permission('bonus.approve')
def bulk_approve_bonuses():
    """اعتماد عدة مكافآت معلقة دفعة واحدة"""
    try:
        data = request.get_json(silent=True) or {}
        ids = data.get('ids') or data.get('bonus_ids') or []
        approved_by = data.get('approved_by', 'system')

        if not isinstance(ids, list) or not ids:
            return jsonify({'success': False, 'message': 'قائمة المعرفات مطلوبة'}), 400

        bonuses = EmployeeBonus.query.filter(EmployeeBonus.id.in_(ids)).all()
        approved, skipped = [], []

        for bonus in bonuses:
            if bonus.status == 'pending':
                employee = Employee.query.get(bonus.employee_id)
                bonus.approve(approved_by)
                _create_achievement_for_bonus(bonus, employee)
                approved.append(bonus.id)
            else:
                skipped.append({'id': bonus.id, 'status': bonus.status})

        db.session.commit()

        return jsonify({
            'success': True,
            'approved_ids': approved,
            'skipped': skipped,
            'count': len(approved)
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@bonus_bp.route('/bonuses/<int:bonus_id>/reject', methods=['POST'])
@require_auth
@require_permission('bonus.approve')
def reject_bonus(bonus_id):
    """رفض مكافأة"""
    try:
        bonus = EmployeeBonus.query.get_or_404(bonus_id)
        data = request.get_json(silent=True) or {}
        
        if bonus.status != 'pending':
            return jsonify({
                'success': False,
                'message': 'لا يمكن رفض مكافأة غير معلقة'
            }), 400
        
        reason = data.get('reason')
        bonus.reject(reason)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم رفض المكافأة',
            'bonus': bonus.to_dict(include_employee=True, include_rule=True)
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonuses/bulk/reject', methods=['POST'])
@bonus_bp.route('/bonuses/bulk-reject', methods=['POST'])
@require_auth
@require_permission('bonus.approve')
def bulk_reject_bonuses():
    """رفض عدة مكافآت معلقة دفعة واحدة"""
    try:
        data = request.get_json(silent=True) or {}
        ids = data.get('ids') or data.get('bonus_ids') or []
        reason = data.get('reason')

        if not isinstance(ids, list) or not ids:
            return jsonify({'success': False, 'message': 'قائمة المعرفات مطلوبة'}), 400

        bonuses = EmployeeBonus.query.filter(EmployeeBonus.id.in_(ids)).all()
        rejected, skipped = [], []

        for bonus in bonuses:
            if bonus.status == 'pending':
                bonus.reject(reason)
                rejected.append(bonus.id)
            else:
                skipped.append({'id': bonus.id, 'status': bonus.status})

        db.session.commit()

        return jsonify({
            'success': True,
            'rejected_ids': rejected,
            'skipped': skipped,
            'count': len(rejected)
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@bonus_bp.route('/bonuses/<int:bonus_id>/pay', methods=['POST'])
@require_auth
@require_permission('bonus.pay')
def pay_bonus(bonus_id):
    """
    دفع مكافأة من خزينة معينة مع إنشاء سند صرف وتحديث رصيد الخزينة
    
    القيد المحاسبي:
    من ح/ مكافآت مستحقة (2310)    مدين
      إلى ح/ حساب الخزينة           دائن
    
    Body Parameters:
        - safe_box_id: معرف الخزينة (مفضل)
        - office_id: معرف الخزينة (قديم - للتوافق فقط)
        - payment_method: طريقة الدفع ('cash', 'transfer', 'add_to_payroll')
        - paid_date: تاريخ الدفع (اختياري)
        - created_by: اسم المستخدم (اختياري)
    """
    try:
        bonus = EmployeeBonus.query.get_or_404(bonus_id)
        data = request.get_json(silent=True) or {}
        
        if bonus.status != 'approved':
            return jsonify({
                'success': False,
                'message': 'لا يمكن دفع مكافأة غير معتمدة'
            }), 400
        
        payment_method = data.get('payment_method', 'cash')
        paid_date = datetime.strptime(data.get('paid_date'), '%Y-%m-%d').date() if data.get('paid_date') else date.today()
        created_by = data.get('created_by', 'system')
        
        # الحصول على معلومات الموظف
        employee = Employee.query.get(bonus.employee_id)
        if not employee:
            return jsonify({'success': False, 'message': 'الموظف غير موجود'}), 404
        
        # إذا كان الدفع عن طريق إضافة للراتب، نسجل فقط ولا ننشئ سند
        if payment_method == 'add_to_payroll':
            bonus.mark_as_paid(f"سيتم الدفع مع الراتب")
            bonus.notes = f"{bonus.notes or ''}\nسيتم إضافة المكافأة لراتب الشهر القادم"
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'تم تسجيل المكافأة لإضافتها للراتب',
                'bonus': bonus.to_dict(include_employee=True, include_rule=True)
            }), 200
        
        # التحقق من الخزينة (SafeBox مفضل) مع الحفاظ على office_id للتوافق
        safe_box_id = data.get('safe_box_id')
        office_id = data.get('office_id')

        safe_box = None
        office = None
        treasury_account = None
        treasury_name = None
        treasury_balance_cash = None

        if safe_box_id:
            safe_box = SafeBox.query.get(safe_box_id)
            if not safe_box:
                return jsonify({'success': False, 'message': 'الخزينة غير موجودة'}), 404

            if not safe_box.is_active:
                return jsonify({'success': False, 'message': 'الخزينة غير نشطة'}), 400

            # حماية: مكافآت = حركة نقدية/بنكية (لا تسمح بخزائن الذهب)
            if safe_box.safe_type not in ('cash', 'bank'):
                return jsonify({
                    'success': False,
                    'message': 'لا يمكن صرف المكافأة إلا من خزينة نقدية أو بنكية',
                    'safe_box_id': safe_box.id,
                    'safe_type': safe_box.safe_type,
                }), 400

            # توافق بسيط بين نوع الخزينة وطريقة الدفع
            if payment_method == 'cash' and safe_box.safe_type != 'cash':
                return jsonify({'success': False, 'message': 'طريقة الدفع نقدي تتطلب خزينة نقدية'}), 400
            if payment_method == 'transfer' and safe_box.safe_type != 'bank':
                return jsonify({'success': False, 'message': 'طريقة الدفع تحويل تتطلب خزينة بنكية'}), 400

            treasury_account = safe_box.account
            if not treasury_account:
                return jsonify({'success': False, 'message': f'الخزينة {safe_box.name} غير مرتبطة بحساب محاسبي'}), 400

            treasury_name = safe_box.name
            treasury_balance_cash = float(getattr(treasury_account, 'balance_cash', 0.0) or 0.0)

        else:
            if not office_id:
                return jsonify({'success': False, 'message': 'يجب تحديد الخزينة'}), 400

            office = Office.query.get(office_id)
            if not office:
                return jsonify({'success': False, 'message': 'الخزينة غير موجودة'}), 404

            if not office.active:
                return jsonify({'success': False, 'message': 'الخزينة غير نشطة'}), 400

            treasury_name = office.name
            treasury_balance_cash = float(getattr(office, 'balance_cash', 0.0) or 0.0)

        # التحقق من رصيد الخزينة
        if treasury_balance_cash < bonus.amount:
            return jsonify({
                'success': False,
                'message': f'رصيد الخزينة غير كافٍ. الرصيد الحالي: {treasury_balance_cash} ريال، المطلوب: {bonus.amount} ريال'
            }), 400
        
        # البحث عن حساب مكافآت مستحقة (2310)
        bonuses_payable_account = Account.query.filter_by(account_number='2310').first()
        if not bonuses_payable_account:
            return jsonify({'success': False, 'message': 'حساب مكافآت مستحقة غير موجود (2310)'}), 400
        
        # تحديد حساب الخزينة والتحقق من ملاءمته
        if safe_box is None:
            # الحصول على حساب الخزينة من account_category (مسار قديم)
            if not office.account_category:
                return jsonify({'success': False, 'message': f'الخزينة {office.name} غير مرتبطة بحساب محاسبي'}), 400
            treasury_account = office.account_category

        # حماية: لا تسمح بحسابات وزن/مخزون (يجب أن يكون حساب نقدي/بنكي)
        if getattr(treasury_account, 'tracks_weight', False) or getattr(treasury_account, 'transaction_type', 'both') not in ('cash', 'both'):
            return jsonify({
                'success': False,
                'message': (
                    f'الخزينة {treasury_name} مرتبطة بحساب غير مناسب للصرف. '
                    'يرجى ربط الخزينة بحساب نقدي/بنكي (مثل الصندوق/البنوك) ثم إعادة المحاولة.'
                ),
                'account_id': getattr(treasury_account, 'id', None),
                'account_number': getattr(treasury_account, 'account_number', None),
                'account_name': getattr(treasury_account, 'name', None),
                'office_id': getattr(office, 'id', None),
                'safe_box_id': getattr(safe_box, 'id', None),
            }), 400
        
        # إنشاء سند صرف
        voucher_prefix = f"BPAY-{paid_date.year}-{paid_date.month:02d}"
        latest_voucher = (
            Voucher.query.filter(Voucher.voucher_number.like(f"{voucher_prefix}%"))
            .order_by(Voucher.voucher_number.desc())
            .first()
        )
        
        if latest_voucher:
            try:
                last_seq = int(latest_voucher.voucher_number.split('-')[-1])
                voucher_number = f"{voucher_prefix}-{last_seq + 1:04d}"
            except (ValueError, IndexError):
                voucher_number = f"{voucher_prefix}-0001"
        else:
            voucher_number = f"{voucher_prefix}-0001"
        
        # التحقق من عدم وجود سند بنفس الرقم
        existing_voucher = Voucher.query.filter_by(voucher_number=voucher_number).first()
        if existing_voucher:
            return jsonify({
                'success': False,
                'message': f'سند الصرف موجود مسبقاً برقم {voucher_number}. لإعادة الدفع، يجب حذف السند الموجود أولاً.',
                'voucher_id': existing_voucher.id
            }), 409
        
        # إنشاء السند
        voucher = Voucher(
            voucher_number=voucher_number,
            voucher_type='payment',
            date=paid_date,
            description=f"صرف مكافأة {employee.name} - {bonus.bonus_type} من {treasury_name}",
            status='approved',
            created_by=created_by,
        )
        db.session.add(voucher)
        db.session.flush()
        
        # السطر المدين: مكافآت مستحقة (تسديد الالتزام)
        debit_line = VoucherAccountLine(
            voucher_id=voucher.id,
            account_id=bonuses_payable_account.id,
            line_type='debit',
            amount_type='cash',
            description=f"تسديد مكافأة {employee.name}",
            amount=bonus.amount,
        )
        db.session.add(debit_line)
        
        # السطر الدائن: حساب الخزينة (خروج أموال)
        credit_line = VoucherAccountLine(
            voucher_id=voucher.id,
            account_id=treasury_account.id,
            line_type='credit',
            amount_type='cash',
            description=f"صرف مكافأة من {treasury_name}",
            amount=bonus.amount,
        )
        db.session.add(credit_line)
        
        # خصم المبلغ من رصيد الخزينة
        if safe_box is not None:
            treasury_account.update_balance(cash_amount=-bonus.amount)
            # توثيق مصدر الدفع بدون تغيير مخطط قاعدة البيانات
            safe_type_ar = {'cash': 'نقدي', 'bank': 'بنكي', 'gold': 'ذهبي', 'check': 'شيكات'}.get(safe_box.safe_type, safe_box.safe_type)
            bonus.notes = f"{(bonus.notes or '').strip()}\nتم الدفع من خزينة: {safe_box.name} ({safe_type_ar})".strip()
        else:
            office.balance_cash -= bonus.amount

        # تحديث المكافأة وربطها بالخزينة (office فقط لمسار التوافق)
        bonus.mark_as_paid(voucher_number)
        if safe_box is None:
            bonus.office_id = office_id
        
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            existing_voucher = Voucher.query.filter_by(voucher_number=voucher_number).first()
            if existing_voucher:
                return jsonify({
                    'success': False,
                    'message': f'سند الصرف موجود مسبقاً برقم {voucher_number}. لإعادة الدفع، يجب حذف السند الموجود أولاً.',
                    'voucher_id': existing_voucher.id
                }), 409
            raise

        safe_box_payload = None
        office_payload = None
        treasury_balance_after = None

        if safe_box is not None:
            # Canonical source of truth: journal-derived balances.
            live_treasury = live_balances_by_account_ids([treasury_account.id]).get(int(treasury_account.id))
            live_treasury = live_treasury if isinstance(live_treasury, dict) else {'cash': 0.0}
            treasury_balance_after = round(float(live_treasury.get('cash') or 0.0), 2)

            safe_box_payload = safe_box.to_dict(include_account=True, include_balance=False)
            live_sb = live_balances_by_account_ids([safe_box.account_id]).get(int(safe_box.account_id))
            live_sb = live_sb if isinstance(live_sb, dict) else {'cash': 0.0, '18k': 0.0, '21k': 0.0, '22k': 0.0, '24k': 0.0}
            balance = {
                'cash': round(float(live_sb.get('cash') or 0.0), 2),
            }
            account = getattr(safe_box, 'account', None)
            if bool(getattr(account, 'tracks_weight', False)):
                w18 = float(live_sb.get('18k') or 0.0)
                w21 = float(live_sb.get('21k') or 0.0)
                w22 = float(live_sb.get('22k') or 0.0)
                w24 = float(live_sb.get('24k') or 0.0)
                balance['weight'] = {
                    '18k': round(w18, 3),
                    '21k': round(w21, 3),
                    '22k': round(w22, 3),
                    '24k': round(w24, 3),
                    'total': round(w18 + w21 + w22 + w24, 3),
                }
            safe_box_payload['balance'] = balance
        else:
            treasury_balance_after = float(getattr(office, 'balance_cash', 0.0) or 0.0)
            office_payload = {'id': office.id, 'name': office.name, 'balance_after': office.balance_cash}
        
        return jsonify({
            'success': True,
            'message': f'تم صرف المكافأة بنجاح من {treasury_name}',
            'bonus': bonus.to_dict(include_employee=True, include_rule=True),
            'voucher': {
                'id': voucher.id,
                'voucher_number': voucher_number,
                'amount': bonus.amount
            },
            'treasury': {
                'kind': 'safe_box' if safe_box is not None else 'office',
                'id': safe_box.id if safe_box is not None else office.id,
                'name': treasury_name,
                'balance_after': float(treasury_balance_after or 0.0)
            },
            **({'safe_box': safe_box_payload} if safe_box is not None else {'office': office_payload})
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonus/employees/<int:employee_id>/bonuses-summary', methods=['GET'])
@require_auth
def get_employee_bonuses_summary(employee_id):
    """الحصول على ملخص مكافآت موظف"""
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        start = datetime.strptime(start_date, '%Y-%m-%d').date() if start_date else None
        end = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else None
        
        summary = BonusCalculator.get_employee_bonuses_summary(
            employee_id=employee_id,
            start_date=start,
            end_date=end
        )
        
        return jsonify({
            'success': True,
            **summary
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ==========================================
# 🕐 إدارة مجدول المكافآت التلقائي
# ==========================================

@bonus_bp.route('/scheduler/status', methods=['GET'])
@require_auth
def get_scheduler_status():
    """الحصول على حالة مجدول المكافآت"""
    try:
        from bonus_scheduler import get_bonus_scheduler
        from flask import current_app
        
        scheduler = get_bonus_scheduler(current_app._get_current_object())
        
        return jsonify({
            'success': True,
            'is_running': scheduler.is_running,
            'message': 'المجدول يعمل' if scheduler.is_running else 'المجدول متوقف'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/scheduler/start', methods=['POST'])
@require_auth
@require_permission('bonus.admin')
def start_scheduler():
    """بدء مجدول المكافآت"""
    try:
        from bonus_scheduler import get_bonus_scheduler
        from flask import current_app
        
        scheduler = get_bonus_scheduler(current_app._get_current_object())
        scheduler.start()
        
        return jsonify({
            'success': True,
            'message': 'تم بدء مجدول المكافآت بنجاح'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/scheduler/stop', methods=['POST'])
@require_auth
@require_permission('bonus.admin')
def stop_scheduler():
    """إيقاف مجدول المكافآت"""
    try:
        from bonus_scheduler import get_bonus_scheduler
        from flask import current_app
        
        scheduler = get_bonus_scheduler(current_app._get_current_object())
        scheduler.stop()
        
        return jsonify({
            'success': True,
            'message': 'تم إيقاف مجدول المكافآت'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/scheduler/run-now', methods=['POST'])
@require_auth
@require_permission('bonus.calculate')
def run_scheduler_now():
    """تشغيل مهمة من مجدول المكافآت فوراً"""
    try:
        from bonus_scheduler import get_bonus_scheduler
        from flask import current_app
        
        data = request.get_json() or {}
        task_type = data.get('task_type', 'daily')  # daily, weekly, monthly, check
        
        if task_type not in ['daily', 'weekly', 'monthly', 'check']:
            return jsonify({
                'success': False,
                'message': 'نوع المهمة غير صحيح. الخيارات: daily, weekly, monthly, check'
            }), 400
        
        scheduler = get_bonus_scheduler(current_app._get_current_object())
        scheduler.run_now(task_type)
        
        task_names = {
            'daily': 'المكافآت اليومية',
            'weekly': 'المكافآت الأسبوعية',
            'monthly': 'المكافآت الشهرية',
            'check': 'فحص المكافآت المعلقة'
        }
        
        return jsonify({
            'success': True,
            'message': f'تم تشغيل مهمة {task_names[task_type]} بنجاح'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/invoices/<int:invoice_id>/assign-employee', methods=['POST'])
@require_auth
@require_permission('invoice.update')
def assign_employee_to_invoice(invoice_id):
    """تعيين موظف لفاتورة موجودة"""
    try:
        from models import Invoice, Employee
        
        invoice = Invoice.query.get_or_404(invoice_id)
        data = request.get_json()
        
        employee_id = data.get('employee_id')
        if not employee_id:
            return jsonify({
                'success': False,
                'message': 'employee_id is required'
            }), 400
        
        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({
                'success': False,
                'message': f'Employee with ID {employee_id} not found'
            }), 404
        
        invoice.employee_id = employee_id
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'تم تعيين الموظف {employee.name} للفاتورة رقم {invoice_id}',
            'invoice': invoice.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ==========================================
# 📋 قائمة أنواع الفواتير المتاحة
# ==========================================

@bonus_bp.route('/invoice-types', methods=['GET'])
@require_auth
def get_invoice_types():
    """
    الحصول على قائمة أنواع الفواتير المتاحة في النظام
    لاستخدامها في تحديد applicable_invoice_types عند إنشاء قواعد المكافآت
    """
    invoice_types = [
        {'value': 'بيع', 'label': 'بيع', 'description': 'فاتورة بيع للعميل'},
        {'value': 'شراء من عميل', 'label': 'شراء من عميل', 'description': 'شراء ذهب من عميل'},
        {'value': 'مرتجع بيع', 'label': 'مرتجع بيع', 'description': 'إرجاع بضاعة من عميل'},
        {'value': 'مرتجع شراء', 'label': 'مرتجع شراء', 'description': 'إرجاع بضاعة لعميل'},
        {'value': 'شراء', 'label': 'شراء', 'description': 'شراء ذهب من مورد'},
        {'value': 'مرتجع شراء (مورد)', 'label': 'مرتجع شراء (مورد)', 'description': 'إرجاع بضاعة لمورد'}
    ]
    
    return jsonify({
        'success': True,
        'invoice_types': invoice_types
    }), 200


# ==========================================
# 📊 تقرير المستحقات (Payables Report)
# ==========================================

@bonus_bp.route('/bonuses/payables-report', methods=['GET'])
@require_auth
def get_bonuses_payables_report():
    """
    تقرير المستحقات غير المدفوعة (approved)
    
    يوضح إجمالي المكافآت المستحقة لكل موظف والتي لم تُدفع بعد
    هذا المبلغ يجب أن يطابق رصيد حساب "مكافآت مستحقة" (215)
    """
    try:
        # إحصائيات حسب الحالة
        stats_by_status = db.session.query(
            EmployeeBonus.status,
            func.count(EmployeeBonus.id).label('count'),
            func.sum(EmployeeBonus.amount).label('total')
        ).group_by(EmployeeBonus.status).all()
        
        status_summary = {}
        for status, count, total in stats_by_status:
            status_summary[status] = {
                'count': count,
                'total': float(total or 0)
            }
        
        # المستحقات غير المدفوعة لكل موظف (approved فقط)
        unpaid_by_employee = db.session.query(
            Employee.id,
            Employee.name,
            Employee.employee_code,
            func.count(EmployeeBonus.id).label('count'),
            func.sum(EmployeeBonus.amount).label('total')
        ).join(
            EmployeeBonus, Employee.id == EmployeeBonus.employee_id
        ).filter(
            EmployeeBonus.status == 'approved'
        ).group_by(
            Employee.id, Employee.name, Employee.employee_code
        ).all()
        
        employees_payables = []
        total_unpaid = 0
        
        for emp_id, emp_name, emp_code, count, total in unpaid_by_employee:
            employees_payables.append({
                'employee_id': emp_id,
                'employee_name': emp_name,
                'employee_code': emp_code,
                'bonuses_count': count,
                'total_amount': float(total)
            })
            total_unpaid += float(total)
        
        # التحقق من رصيد حساب مكافآت مستحقة (215)
        bonuses_payable_account = Account.query.filter_by(account_number='215').first()
        account_balance = None
        balance_matches = None
        
        if bonuses_payable_account:
            # حساب الرصيد من VoucherAccountLine
            debit_sum = db.session.query(func.sum(VoucherAccountLine.amount)).filter(
                VoucherAccountLine.account_id == bonuses_payable_account.id,
                VoucherAccountLine.line_type == 'debit'
            ).scalar() or 0
            
            credit_sum = db.session.query(func.sum(VoucherAccountLine.amount)).filter(
                VoucherAccountLine.account_id == bonuses_payable_account.id,
                VoucherAccountLine.line_type == 'credit'
            ).scalar() or 0
            
            # رصيد حساب الالتزام = الدائن - المدين
            account_balance = float(credit_sum - debit_sum)
            balance_matches = abs(account_balance - total_unpaid) < 0.01
        
        return jsonify({
            'success': True,
            'report_date': date.today().isoformat(),
            'status_summary': status_summary,
            'employees_payables': employees_payables,
            'total_unpaid': total_unpaid,
            'account_info': {
                'account_number': '2310',
                'account_name': 'مكافآت مستحقة',
                'balance': account_balance,
                'balance_matches': balance_matches
            } if bonuses_payable_account else None
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ==========================================
# 📊 تقرير المكافآت الشامل
# ==========================================

@bonus_bp.route('/bonuses/report', methods=['GET'])
@require_auth
def bonuses_report():
    """
    تقرير شامل لجميع المكافآت
    
    Query Parameters:
        - employee_id: تصفية حسب موظف معين
        - status: تصفية حسب الحالة (pending, approved, rejected, paid)
        - from_date: من تاريخ
        - to_date: إلى تاريخ
        - office_id: تصفية حسب الخزينة
    """
    try:
        # الحصول على المعاملات
        employee_id = request.args.get('employee_id', type=int)
        status = request.args.get('status')
        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        office_id = request.args.get('office_id', type=int)
        
        # بناء الاستعلام
        query = EmployeeBonus.query
        
        if employee_id:
            query = query.filter_by(employee_id=employee_id)
        
        if status:
            query = query.filter_by(status=status)
        
        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
            query = query.filter(EmployeeBonus.created_at >= from_date)
        
        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
            query = query.filter(EmployeeBonus.created_at <= to_date)
        
        if office_id:
            query = query.filter_by(office_id=office_id)
        
        bonuses = query.order_by(EmployeeBonus.created_at.desc()).all()
        
        # إحصائيات حسب الحالة
        status_stats = {}
        for s in ['pending', 'approved', 'rejected', 'paid']:
            count = EmployeeBonus.query.filter_by(status=s).count()
            total = db.session.query(func.sum(EmployeeBonus.amount)).filter_by(status=s).scalar() or 0
            status_stats[s] = {
                'count': count,
                'total': float(total)
            }
        
        # إحصائيات حسب الموظف
        employee_stats = db.session.query(
            Employee.id,
            Employee.name,
            Employee.employee_code,
            func.count(EmployeeBonus.id).label('total_bonuses'),
            func.sum(EmployeeBonus.amount).label('total_amount'),
            func.sum(func.case([(EmployeeBonus.status == 'paid', EmployeeBonus.amount)], else_=0)).label('paid_amount'),
            func.sum(func.case([(EmployeeBonus.status == 'approved', EmployeeBonus.amount)], else_=0)).label('approved_amount')
        ).join(
            EmployeeBonus, Employee.id == EmployeeBonus.employee_id
        ).group_by(
            Employee.id, Employee.name, Employee.employee_code
        ).all()
        
        employees_summary = []
        for emp_id, emp_name, emp_code, total_bonuses, total_amt, paid_amt, approved_amt in employee_stats:
            employees_summary.append({
                'employee_id': emp_id,
                'employee_name': emp_name,
                'employee_code': emp_code,
                'total_bonuses': total_bonuses,
                'total_amount': float(total_amt or 0),
                'paid_amount': float(paid_amt or 0),
                'approved_not_paid': float(approved_amt or 0),
                'pending_amount': float((total_amt or 0) - (paid_amt or 0) - (approved_amt or 0))
            })
        
        # إحصائيات حسب الخزائن
        office_stats = db.session.query(
            Office.id,
            Office.name,
            Office.office_code,
            func.count(EmployeeBonus.id).label('payments_count'),
            func.sum(EmployeeBonus.amount).label('total_paid')
        ).join(
            EmployeeBonus, Office.id == EmployeeBonus.office_id
        ).filter(
            EmployeeBonus.status == 'paid'
        ).group_by(
            Office.id, Office.name, Office.office_code
        ).all()
        
        offices_summary = []
        for off_id, off_name, off_code, payments_count, total_paid in office_stats:
            offices_summary.append({
                'office_id': off_id,
                'office_name': off_name,
                'office_code': off_code,
                'payments_count': payments_count,
                'total_paid': float(total_paid or 0)
            })
        
        return jsonify({
            'success': True,
            'report_date': datetime.now().isoformat(),
            'filters': {
                'employee_id': employee_id,
                'status': status,
                'from_date': from_date_str,
                'to_date': to_date_str,
                'office_id': office_id
            },
            'status_summary': status_stats,
            'employees_summary': employees_summary,
            'offices_summary': offices_summary,
            'bonuses': [b.to_dict(include_employee=True, include_rule=True) for b in bonuses],
            'total_bonuses': len(bonuses),
            'grand_total': sum(b.amount for b in bonuses)
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@bonus_bp.route('/bonuses/employee/<int:employee_id>/summary', methods=['GET'])
@require_auth
def employee_bonus_summary(employee_id):
    """
    ملخص مكافآت موظف معين
    """
    try:
        employee = Employee.query.get_or_404(employee_id)
        
        # جميع المكافآت
        bonuses = EmployeeBonus.query.filter_by(employee_id=employee_id).order_by(EmployeeBonus.created_at.desc()).all()
        
        # الإحصائيات
        total_amount = sum(b.amount for b in bonuses)
        paid_amount = sum(b.amount for b in bonuses if b.status == 'paid')
        approved_not_paid = sum(b.amount for b in bonuses if b.status == 'approved')
        pending_amount = sum(b.amount for b in bonuses if b.status == 'pending')
        rejected_amount = sum(b.amount for b in bonuses if b.status == 'rejected')
        
        # حسب النوع
        by_type = {}
        for bonus in bonuses:
            if bonus.bonus_type not in by_type:
                by_type[bonus.bonus_type] = {
                    'count': 0,
                    'total': 0,
                    'paid': 0,
                    'pending': 0
                }
            by_type[bonus.bonus_type]['count'] += 1
            by_type[bonus.bonus_type]['total'] += bonus.amount
            if bonus.status == 'paid':
                by_type[bonus.bonus_type]['paid'] += bonus.amount
            elif bonus.status == 'pending' or bonus.status == 'approved':
                by_type[bonus.bonus_type]['pending'] += bonus.amount
        
        return jsonify({
            'success': True,
            'employee': employee.to_dict(),
            'summary': {
                'total_bonuses': len(bonuses),
                'total_amount': total_amount,
                'paid_amount': paid_amount,
                'approved_not_paid': approved_not_paid,
                'pending_amount': pending_amount,
                'rejected_amount': rejected_amount,
                'by_type': by_type
            },
            'bonuses': [b.to_dict(include_rule=True) for b in bonuses]
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500
