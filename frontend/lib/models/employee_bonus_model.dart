class EmployeeBonusModel {
  final int? id;
  final int employeeId;
  final int? bonusRuleId;
  final String bonusType;
  final double amount;
  final DateTime periodStart;
  final DateTime periodEnd;
  final Map<String, dynamic>? calculationData;
  final String status;
  final String? notes;
  final String? approvedBy;
  final DateTime? approvedAt;
  final DateTime? paidAt;
  final String? paymentReference;
  final DateTime? createdAt;
  final String? createdBy;

  // معلومات إضافية من العلاقات
  final EmployeeSummary? employee;
  final BonusRuleSummary? bonusRule;

  const EmployeeBonusModel({
    this.id,
    required this.employeeId,
    this.bonusRuleId,
    required this.bonusType,
    required this.amount,
    required this.periodStart,
    required this.periodEnd,
    this.calculationData,
    this.status = 'pending',
    this.notes,
    this.approvedBy,
    this.approvedAt,
    this.paidAt,
    this.paymentReference,
    this.createdAt,
    this.createdBy,
    this.employee,
    this.bonusRule,
  });

  factory EmployeeBonusModel.fromJson(Map<String, dynamic> json) {
    // Use (num).toInt() for all integer fields — on Flutter Web JSON numbers
    // may arrive as double (e.g. 1.0) and `as int` would throw a TypeError.
    return EmployeeBonusModel(
      id: (json['id'] as num?)?.toInt(),
      employeeId: (json['employee_id'] as num).toInt(),
      bonusRuleId: (json['bonus_rule_id'] as num?)?.toInt(),
      bonusType: (json['bonus_type'] as String?) ?? 'manual',
      amount: (json['amount'] as num?)?.toDouble() ?? 0.0,
      periodStart: json['period_start'] != null
          ? DateTime.tryParse(json['period_start'].toString()) ?? DateTime.now()
          : DateTime.now(),
      periodEnd: json['period_end'] != null
          ? DateTime.tryParse(json['period_end'].toString()) ?? DateTime.now()
          : DateTime.now(),
      calculationData: json['calculation_data'] is Map
          ? Map<String, dynamic>.from(json['calculation_data'] as Map)
          : null,
      status: (json['status'] as String?) ?? 'pending',
      notes: json['notes'] as String?,
      approvedBy: json['approved_by'] as String?,
      approvedAt: json['approved_at'] != null
          ? DateTime.tryParse(json['approved_at'].toString())
          : null,
      paidAt: json['paid_at'] != null
          ? DateTime.tryParse(json['paid_at'].toString())
          : null,
      paymentReference: json['payment_reference'] as String?,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString())
          : null,
      createdBy: json['created_by'] as String?,
      employee: json['employee'] is Map
          ? EmployeeSummary.fromJson(
              Map<String, dynamic>.from(json['employee'] as Map))
          : null,
      bonusRule: (json['bonus_rule'] ?? json['rule']) is Map
          ? BonusRuleSummary.fromJson(
              Map<String, dynamic>.from(
                  (json['bonus_rule'] ?? json['rule']) as Map))
          : null,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      if (id != null) 'id': id,
      'employee_id': employeeId,
      'bonus_rule_id': bonusRuleId,
      'bonus_type': bonusType,
      'amount': amount,
      'period_start': periodStart.toIso8601String().split('T').first,
      'period_end': periodEnd.toIso8601String().split('T').first,
      'calculation_data': calculationData,
      'status': status,
      'notes': notes,
      'payment_reference': paymentReference,
      'created_by': createdBy,
    };
  }

  EmployeeBonusModel copyWith({
    int? id,
    int? employeeId,
    int? bonusRuleId,
    String? bonusType,
    double? amount,
    DateTime? periodStart,
    DateTime? periodEnd,
    Map<String, dynamic>? calculationData,
    String? status,
    String? notes,
    String? approvedBy,
    DateTime? approvedAt,
    DateTime? paidAt,
    String? paymentReference,
    String? createdBy,
    EmployeeSummary? employee,
    BonusRuleSummary? bonusRule,
  }) {
    return EmployeeBonusModel(
      id: id ?? this.id,
      employeeId: employeeId ?? this.employeeId,
      bonusRuleId: bonusRuleId ?? this.bonusRuleId,
      bonusType: bonusType ?? this.bonusType,
      amount: amount ?? this.amount,
      periodStart: periodStart ?? this.periodStart,
      periodEnd: periodEnd ?? this.periodEnd,
      calculationData: calculationData ?? this.calculationData,
      status: status ?? this.status,
      notes: notes ?? this.notes,
      approvedBy: approvedBy ?? this.approvedBy,
      approvedAt: approvedAt ?? this.approvedAt,
      paidAt: paidAt ?? this.paidAt,
      paymentReference: paymentReference ?? this.paymentReference,
      createdBy: createdBy ?? this.createdBy,
      employee: employee ?? this.employee,
      bonusRule: bonusRule ?? this.bonusRule,
    );
  }

  /// حالات المكافأة
  static const List<String> statuses = [
    'pending', // معلقة
    'approved', // معتمدة
    'paid', // مدفوعة
    'rejected', // مرفوضة
  ];

  /// أسماء الحالات بالعربية
  static String getStatusNameAr(String status) {
    switch (status) {
      case 'pending':
        return 'معلقة';
      case 'approved':
        return 'معتمدة';
      case 'paid':
        return 'مدفوعة';
      case 'rejected':
        return 'مرفوضة';
      default:
        return status;
    }
  }

  /// ألوان الحالات
  static int getStatusColor(String status) {
    switch (status) {
      case 'pending':
        return 0xFFFFA500; // برتقالي
      case 'approved':
        return 0xFF4CAF50; // أخضر
      case 'paid':
        return 0xFF2196F3; // أزرق
      case 'rejected':
        return 0xFFF44336; // أحمر
      default:
        return 0xFF9E9E9E; // رمادي
    }
  }

  /// التحقق من إمكانية اعتماد المكافأة
  bool canApprove() => status == 'pending';

  /// التحقق من إمكانية رفض المكافأة
  bool canReject() => status == 'pending';

  /// التحقق من إمكانية دفع المكافأة
  bool canPay() => status == 'approved';
}

/// ملخص معلومات الموظف
class EmployeeSummary {
  final String employeeCode;
  final String fullName;
  final String? position;
  final String? department;
  final String? photo;

  const EmployeeSummary({
    required this.employeeCode,
    required this.fullName,
    this.position,
    this.department,
    this.photo,
  });

  factory EmployeeSummary.fromJson(Map<String, dynamic> json) {
    final code = (json['employee_code'] ?? json['employeeCode'] ?? '') as String;
    final name = (json['full_name'] ?? json['name'] ?? '') as String;
    return EmployeeSummary(
      employeeCode: code,
      fullName: name,
      position: json['position'] as String?,
      department: json['department'] as String?,
      photo: json['photo'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'employee_code': employeeCode,
      'full_name': fullName,
      'position': position,
      'department': department,
      'photo': photo,
    };
  }
}

/// ملخص معلومات قاعدة المكافأة
class BonusRuleSummary {
  final String name;
  final String ruleType;

  const BonusRuleSummary({required this.name, required this.ruleType});

  factory BonusRuleSummary.fromJson(Map<String, dynamic> json) {
    return BonusRuleSummary(
      name: json['name'] as String,
      ruleType: json['rule_type'] as String,
    );
  }

  Map<String, dynamic> toJson() {
    return {'name': name, 'rule_type': ruleType};
  }
}
