import 'package:flutter/material.dart';

import '../api_service.dart';
import '../models/employee_model.dart';
import '../models/payroll_model.dart';
import 'payroll_report_screen.dart';

class PayrollScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;
  const PayrollScreen({super.key, required this.api, this.isArabic = true});

  @override
  State<PayrollScreen> createState() => _PayrollScreenState();
}

class _PayrollScreenState extends State<PayrollScreen> {
  List<PayrollModel> _entries = [];
  bool _loading = false;
  int? _selectedYear;
  int? _selectedMonth;
  String? _statusFilter;

  @override
  void initState() {
    super.initState();
    _selectedYear = DateTime.now().year;
    _loadPayroll();
  }

  Future<void> _loadPayroll() async {
    setState(() => _loading = true);
    try {
      final entries = await widget.api.getPayroll(
        year: _selectedYear,
        month: _selectedMonth,
        status: _statusFilter,
      );
      setState(() => _entries = entries);
    } catch (e) {
      _showSnack(e.toString(), isError: true);
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  void _showSnack(String message, {bool isError = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError
            ? Colors.red
            : Theme.of(context).colorScheme.primary,
      ),
    );
  }

  Future<void> _openForm({PayrollModel? entry}) async {
    final result = await showDialog<Map<String, dynamic>?>(
      context: context,
      builder: (context) => PayrollFormDialog(
        api: widget.api,
        isArabic: widget.isArabic,
        entry: entry,
      ),
    );

    if (result == null) return;

    final desiredStatus = (result['status'] ?? '').toString();
    final wasApproved = (entry?.status ?? '').toLowerCase() == 'approved';
    final justApproved =
        desiredStatus.toLowerCase() == 'approved' && !wasApproved;

    try {
      if (entry == null) {
        final created = await widget.api.createPayroll(result);
        setState(() => _entries.insert(0, created));
        _showSnack(
          widget.isArabic ? 'تم إنشاء سجل الرواتب' : 'Payroll entry created',
        );

        if (desiredStatus.toLowerCase() == 'approved') {
          await _promptPostAccrual(created);
        }
      } else {
        final updated = await widget.api.updatePayroll(entry.id ?? 0, result);
        setState(() {
          final index = _entries.indexWhere((p) => p.id == entry.id);
          if (index != -1) {
            _entries[index] = updated;
          }
        });
        _showSnack(
          widget.isArabic ? 'تم تحديث سجل الرواتب' : 'Payroll entry updated',
        );

        if (justApproved) {
          await _promptPostAccrual(updated);
        }
      }
    } catch (e) {
      _showSnack(e.toString(), isError: true);
    }
  }

  Future<void> _promptPostAccrual(PayrollModel entry) async {
    final isAr = widget.isArabic;
    final payrollId = entry.id;
    if (payrollId == null || payrollId <= 0) return;

    final employeeName = entry.employee?.name ?? '';
    final month = entry.month;
    final year = entry.year;
    final net = entry.netSalary;

    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(isAr ? 'ترحيل استحقاق الرواتب' : 'Post Payroll Accrual'),
        content: Text(
          isAr
              ? 'تم اعتماد سجل الراتب${employeeName.isNotEmpty ? " للموظف: $employeeName" : ""} (${month}/${year}).\nهل تريد ترحيل الاستحقاق الآن؟\n\nسيتم إنشاء قيد: \nمدين 5410 (مصروف الرواتب) = ${net.toStringAsFixed(2)}\nدائن 2400xxxx (رواتب مستحقة) = ${net.toStringAsFixed(2)}'
              : 'This payroll entry has been approved${employeeName.isNotEmpty ? " for $employeeName" : ""} (${month}/${year}).\nPost the accrual now?\n\nJournal: \nDr 5410 (Salary Expense) = ${net.toStringAsFixed(2)}\nCr 2400xxxx (Salaries Payable) = ${net.toStringAsFixed(2)}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(isAr ? 'لاحقاً' : 'Later'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(isAr ? 'ترحيل الآن' : 'Post now'),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      await widget.api.postPayrollAccrual(payrollId);
      _showSnack(
        isAr ? 'تم ترحيل الاستحقاق بنجاح' : 'Accrual posted successfully',
      );
    } catch (e) {
      _showSnack(e.toString(), isError: true);
    }
  }

  Future<void> _deleteEntry(PayrollModel entry) async {
    final isAr = widget.isArabic;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(isAr ? 'حذف سجل راتب' : 'Delete Payroll Entry'),
        content: Text(
          isAr
              ? 'هل تريد حذف سجل راتب ${entry.employee?.name ?? entry.employeeId}؟'
              : 'Delete payroll entry for ${entry.employee?.name ?? entry.employeeId}?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(isAr ? 'إلغاء' : 'Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(isAr ? 'حذف' : 'Delete'),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      await widget.api.deletePayroll(entry.id ?? 0);
      setState(() => _entries.removeWhere((e) => e.id == entry.id));
      _showSnack(isAr ? 'تم حذف السجل' : 'Entry deleted');
    } catch (e) {
      _showSnack(e.toString(), isError: true);
    }
  }

  Future<void> _markAsPaid(PayrollModel entry) async {
    final isAr = widget.isArabic;

    // الحصول على حسابات الدفع المتاحة
    List<Map<String, dynamic>> paymentAccounts = [];
    try {
      paymentAccounts = await widget.api.getPaymentAccounts();
    } catch (e) {
      _showSnack('فشل تحميل حسابات الدفع: $e', isError: true);
      return;
    }

    if (paymentAccounts.isEmpty) {
      _showSnack(
        isAr ? 'لا توجد حسابات دفع متاحة' : 'No payment accounts available',
        isError: true,
      );
      return;
    }

    // البحث عن الحساب الافتراضي (النقدية)
    final defaultAccount = paymentAccounts.firstWhere(
      (acc) => acc['is_default'] == true,
      orElse: () => paymentAccounts.first,
    );

    int? selectedAccountId = defaultAccount['id'];

    double advanceDeductionAmount = 0.0;
    final advanceDeductionController = TextEditingController(text: '0.00');

    // إظهار dialog لاختيار طريقة الدفع
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Text(isAr ? 'تأكيد دفع الراتب' : 'Confirm Payment'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isAr
                      ? 'الموظف: ${entry.employee?.name ?? ""}'
                      : 'Employee: ${entry.employee?.name ?? ""}',
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 8),
                Text(
                  isAr
                      ? 'الراتب الصافي: ${entry.netSalary.toStringAsFixed(2)} ريال'
                      : 'Net Salary: ${entry.netSalary.toStringAsFixed(2)} SAR',
                ),
                const SizedBox(height: 8),
                Text(
                  isAr
                      ? 'المدفوع فعلياً: ${(entry.netSalary - advanceDeductionAmount).clamp(0, entry.netSalary).toStringAsFixed(2)} ريال'
                      : 'Cash Paid: ${(entry.netSalary - advanceDeductionAmount).clamp(0, entry.netSalary).toStringAsFixed(2)} SAR',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 16),
                Text(
                  isAr ? 'طريقة الدفع:' : 'Payment Method:',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 8),
                DropdownButtonFormField<int>(
                  initialValue: selectedAccountId,
                  decoration: InputDecoration(
                    border: const OutlineInputBorder(),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 8,
                    ),
                    hintText: isAr
                        ? 'اختر حساب الدفع'
                        : 'Select payment account',
                  ),
                  items: paymentAccounts.map((acc) {
                    return DropdownMenuItem<int>(
                      value: acc['id'],
                      child: SizedBox(
                        width: 420,
                        child: Row(
                          children: [
                            Icon(
                              _getAccountIcon(acc['name']),
                              size: 18,
                              color: acc['is_default'] == true
                                  ? Colors.green
                                  : Colors.grey,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                '${acc['name']} (${acc['account_number']})',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  }).toList(),
                  onChanged: (value) {
                    setDialogState(() {
                      selectedAccountId = value;
                    });
                  },
                ),
                const SizedBox(height: 16),
                Text(
                  isAr
                      ? 'خصم من سلفة (اختياري):'
                      : 'Advance Deduction (optional):',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: advanceDeductionController,
                  decoration: InputDecoration(
                    border: const OutlineInputBorder(),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 10,
                    ),
                    hintText: isAr ? '0.00' : '0.00',
                  ),
                  keyboardType: const TextInputType.numberWithOptions(
                    signed: false,
                    decimal: true,
                  ),
                  onChanged: (value) {
                    final parsed =
                        double.tryParse(value.trim().replaceAll(',', '.')) ??
                        0.0;
                    setDialogState(() {
                      advanceDeductionAmount = parsed < 0 ? 0.0 : parsed;
                      if (advanceDeductionAmount > entry.netSalary) {
                        advanceDeductionAmount = entry.netSalary;
                      }
                    });
                  },
                ),
                const SizedBox(height: 8),
                Text(
                  isAr
                      ? 'سيتم خصم هذا المبلغ من حساب سلفة الموظف ضمن نفس سند الصرف.'
                      : 'This amount will be credited to the employee advance account in the same voucher.',
                  style: TextStyle(
                    fontSize: 12,
                    color: Theme.of(context).hintColor,
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: Text(isAr ? 'إلغاء' : 'Cancel'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(isAr ? 'تأكيد الدفع' : 'Confirm Payment'),
            ),
          ],
        ),
      ),
    );

    if (confirmed != true || selectedAccountId == null) return;

    // تنفيذ عملية الدفع
    try {
      final updated = await widget.api.markPayrollPaid(
        entry.id ?? 0,
        paymentAccountId: selectedAccountId,
        advanceDeductionAmount: advanceDeductionAmount > 0
            ? advanceDeductionAmount
            : null,
      );
      setState(() {
        final index = _entries.indexWhere((p) => p.id == entry.id);
        if (index != -1) {
          _entries[index] = updated;
        }
      });
      _showSnack(
        isAr
            ? 'تم تأكيد الدفع وإنشاء سند الصرف'
            : 'Payment confirmed and voucher created',
      );
    } catch (e) {
      _showSnack(e.toString(), isError: true);
    }
  }

  IconData _getAccountIcon(String accountName) {
    final name = accountName.toLowerCase();
    if (name.contains('بنك') || name.contains('bank')) {
      return Icons.account_balance;
    } else if (name.contains('شيك') || name.contains('check')) {
      return Icons.receipt_long;
    } else {
      return Icons.money; // نقدية/صندوق
    }
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final months = List.generate(12, (index) => index + 1);
    final years = List.generate(5, (index) => DateTime.now().year - 2 + index);

    return Scaffold(
      appBar: AppBar(
        title: Text(isAr ? 'سجلات الرواتب' : 'Payroll Records'),
        actions: [
          IconButton(
            onPressed: _loadPayroll,
            icon: const Icon(Icons.refresh),
            tooltip: isAr ? 'تحديث' : 'Refresh',
          ),
          IconButton(
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) =>
                      PayrollReportScreen(api: widget.api, isArabic: isAr),
                ),
              );
            },
            icon: const Icon(Icons.assessment),
            tooltip: isAr ? 'التقرير الشهري' : 'Monthly Report',
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openForm(),
        icon: const Icon(Icons.add_card),
        label: Text(isAr ? 'سجل جديد' : 'New Entry'),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Wrap(
              spacing: 12,
              runSpacing: 12,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                DropdownButton<int>(
                  value: _selectedYear,
                  hint: Text(isAr ? 'السنة' : 'Year'),
                  onChanged: (value) {
                    setState(() => _selectedYear = value);
                    _loadPayroll();
                  },
                  items: years
                      .map(
                        (year) => DropdownMenuItem(
                          value: year,
                          child: Text(year.toString()),
                        ),
                      )
                      .toList(),
                ),
                DropdownButton<int?>(
                  value: _selectedMonth,
                  hint: Text(isAr ? 'الشهر' : 'Month'),
                  onChanged: (value) {
                    setState(() => _selectedMonth = value);
                    _loadPayroll();
                  },
                  items: [
                    const DropdownMenuItem(value: null, child: Text('All')),
                    ...months.map(
                      (m) => DropdownMenuItem(value: m, child: Text('$m')),
                    ),
                  ],
                ),
                DropdownButton<String?>(
                  value: _statusFilter,
                  hint: Text(isAr ? 'الحالة' : 'Status'),
                  onChanged: (value) {
                    setState(() => _statusFilter = value);
                    _loadPayroll();
                  },
                  items: const [
                    DropdownMenuItem(value: null, child: Text('All')),
                    DropdownMenuItem(value: 'pending', child: Text('Pending')),
                    DropdownMenuItem(
                      value: 'approved',
                      child: Text('Approved'),
                    ),
                    DropdownMenuItem(value: 'paid', child: Text('Paid')),
                    DropdownMenuItem(
                      value: 'cancelled',
                      child: Text('Cancelled'),
                    ),
                  ],
                ),
              ],
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _entries.isEmpty
                ? Center(
                    child: Text(
                      isAr ? 'لا توجد سجلات رواتب' : 'No payroll entries',
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: colorScheme.primary,
                      ),
                    ),
                  )
                : ListView.builder(
                    itemCount: _entries.length,
                    itemBuilder: (context, index) {
                      final entry = _entries[index];
                      final statusColor = _statusColor(entry.status);
                      return Card(
                        margin: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 6,
                        ),
                        child: ListTile(
                          onTap: () => _openForm(entry: entry),
                          leading: CircleAvatar(
                            backgroundColor: statusColor.withValues(
                              alpha: 0.15,
                            ),
                            child: Icon(Icons.payments, color: statusColor),
                          ),
                          title: Text(
                            '${entry.month}/${entry.year} - ${entry.employee?.name ?? '#${entry.employeeId}'}',
                            style: theme.textTheme.titleMedium,
                          ),
                          subtitle: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${isAr ? 'الصافي' : 'Net'}: ${entry.netSalary.toStringAsFixed(2)}',
                              ),
                              Text(
                                '${isAr ? 'الحالة' : 'Status'}: ${entry.status}',
                              ),
                            ],
                          ),
                          trailing: PopupMenuButton<String>(
                            onSelected: (value) {
                              if (value == 'edit') {
                                _openForm(entry: entry);
                              } else if (value == 'delete') {
                                _deleteEntry(entry);
                              } else if (value == 'paid') {
                                _markAsPaid(entry);
                              }
                            },
                            itemBuilder: (context) => [
                              PopupMenuItem(
                                value: 'edit',
                                child: Text(isAr ? 'تعديل' : 'Edit'),
                              ),
                              PopupMenuItem(
                                value: 'paid',
                                child: Text(isAr ? 'تعيين مدفوع' : 'Mark Paid'),
                              ),
                              PopupMenuItem(
                                value: 'delete',
                                child: Text(isAr ? 'حذف' : 'Delete'),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }

  Color _statusColor(String status) {
    switch (status) {
      case 'paid':
        return Colors.green;
      case 'approved':
        return Colors.blue;
      case 'cancelled':
        return Colors.red;
      default:
        return Colors.orange;
    }
  }
}

class PayrollFormDialog extends StatefulWidget {
  final ApiService api;
  final bool isArabic;
  final PayrollModel? entry;
  const PayrollFormDialog({
    super.key,
    required this.api,
    required this.isArabic,
    this.entry,
  });

  @override
  State<PayrollFormDialog> createState() => _PayrollFormDialogState();
}

class _PayrollFormDialogState extends State<PayrollFormDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _employeeIdController;
  late final TextEditingController _monthController;
  late final TextEditingController _yearController;
  late final TextEditingController _basicController;
  late final TextEditingController _allowancesController;
  late final TextEditingController _deductionsController;
  late final TextEditingController _netController;
  late final TextEditingController _notesController;
  String _status = 'pending';

  bool _loadingEmployees = false;
  String? _employeesLoadError;
  List<EmployeeModel> _employees = [];
  int? _selectedEmployeeId;

  @override
  void initState() {
    super.initState();
    final entry = widget.entry;
    final now = DateTime.now();
    _employeeIdController = TextEditingController(
      text: entry?.employeeId.toString() ?? '',
    );
    _selectedEmployeeId = entry?.employeeId;
    _monthController = TextEditingController(
      text: (entry?.month ?? now.month).toString(),
    );
    _yearController = TextEditingController(
      text: (entry?.year ?? now.year).toString(),
    );
    _basicController = TextEditingController(
      text: entry != null ? entry.basicSalary.toStringAsFixed(2) : '',
    );
    _allowancesController = TextEditingController(
      text: entry != null ? entry.allowances.toStringAsFixed(2) : '',
    );
    _deductionsController = TextEditingController(
      text: entry != null ? entry.deductions.toStringAsFixed(2) : '',
    );
    _netController = TextEditingController(
      text: entry != null ? entry.netSalary.toStringAsFixed(2) : '',
    );
    _notesController = TextEditingController(text: entry?.notes ?? '');
    _status = entry?.status ?? 'pending';

    // ✅ حساب الصافي تلقائياً عند التغيير
    _basicController.addListener(_calculateNet);
    _allowancesController.addListener(_calculateNet);
    _deductionsController.addListener(_calculateNet);

    _loadEmployees();
  }

  Future<void> _loadEmployees() async {
    setState(() {
      _loadingEmployees = true;
      _employeesLoadError = null;
    });

    try {
      // Fetch all pages of active employees (best-effort).
      final all = <EmployeeModel>[];
      int page = 1;
      int pages = 1;
      do {
        final res = await widget.api.getEmployees(
          page: page,
          perPage: 200,
          isActive: true,
        );
        final chunk = (res['employees'] as List<EmployeeModel>? ?? []);
        all.addAll(chunk);
        pages = (res['pages'] as int?) ?? 1;
        page++;
      } while (page <= pages);

      all.sort((a, b) => a.name.compareTo(b.name));

      if (!mounted) return;
      setState(() {
        _employees = all;
      });

      // If editing and employee is inactive/missing from list, keep selected id.
      if (_selectedEmployeeId != null && _employees.isNotEmpty) {
        final exists = _employees.any((e) => e.id == _selectedEmployeeId);
        if (!exists) {
          // Keep it as-is; dropdown will show hint only.
        }
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _employeesLoadError = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _loadingEmployees = false;
      });
    }
  }

  void _calculateNet() {
    final basic =
        double.tryParse(_basicController.text.trim().replaceAll(',', '.')) ??
        0.0;
    final allowances =
        double.tryParse(
          _allowancesController.text.trim().replaceAll(',', '.'),
        ) ??
        0.0;
    final deductions =
        double.tryParse(
          _deductionsController.text.trim().replaceAll(',', '.'),
        ) ??
        0.0;
    final net = basic + allowances - deductions;
    _netController.text = net.toStringAsFixed(2);
  }

  @override
  void dispose() {
    _basicController.removeListener(_calculateNet);
    _allowancesController.removeListener(_calculateNet);
    _deductionsController.removeListener(_calculateNet);
    _employeeIdController.dispose();
    _monthController.dispose();
    _yearController.dispose();
    _basicController.dispose();
    _allowancesController.dispose();
    _deductionsController.dispose();
    _netController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;

    final employeeId = _employeesLoadError == null
        ? _selectedEmployeeId
        : int.tryParse(_employeeIdController.text.trim());

    final payload = <String, dynamic>{
      'employee_id': employeeId,
      'month': int.tryParse(_monthController.text.trim()),
      'year': int.tryParse(_yearController.text.trim()),
      'basic_salary':
          double.tryParse(_basicController.text.trim().replaceAll(',', '.')) ??
          0.0,
      'allowances':
          double.tryParse(
            _allowancesController.text.trim().replaceAll(',', '.'),
          ) ??
          0.0,
      'deductions':
          double.tryParse(
            _deductionsController.text.trim().replaceAll(',', '.'),
          ) ??
          0.0,
      'net_salary':
          double.tryParse(_netController.text.trim().replaceAll(',', '.')) ??
          0.0,
      'notes': _notesController.text.trim().isEmpty
          ? null
          : _notesController.text.trim(),
      'status': _status,
    }..removeWhere((key, value) => value == null);

    Navigator.of(context).pop(payload);
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    return AlertDialog(
      title: Text(
        widget.entry == null
            ? (isAr ? 'سجل راتب جديد' : 'New Payroll Entry')
            : (isAr ? 'تعديل سجل الراتب' : 'Edit Payroll Entry'),
      ),
      content: SizedBox(
        width: 400,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (_employeesLoadError == null) ...[
                  DropdownButtonFormField<int>(
                    value: _selectedEmployeeId,
                    decoration: InputDecoration(
                      labelText: isAr ? 'الموظف' : 'Employee',
                      suffixIcon: _loadingEmployees
                          ? Padding(
                              padding: const EdgeInsets.all(12),
                              child: SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              ),
                            )
                          : null,
                    ),
                    items: _employees
                        .where((e) => e.id != null)
                        .map(
                          (e) => DropdownMenuItem<int>(
                            value: e.id,
                            child: Text(
                              '${e.name} (${e.employeeCode})',
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        )
                        .toList(),
                    onChanged: _loadingEmployees
                        ? null
                        : (value) =>
                              setState(() => _selectedEmployeeId = value),
                    validator: (value) {
                      if (value == null) {
                        return isAr
                            ? 'يرجى اختيار الموظف'
                            : 'Select an employee';
                      }
                      return null;
                    },
                  ),
                ] else ...[
                  TextFormField(
                    controller: _employeeIdController,
                    decoration: InputDecoration(
                      labelText: isAr ? 'معرّف الموظف' : 'Employee ID',
                      helperText: isAr
                          ? 'تعذر تحميل قائمة الموظفين، أدخل المعرّف يدوياً.'
                          : 'Could not load employees list, enter ID manually.',
                    ),
                    keyboardType: TextInputType.number,
                    validator: (value) {
                      if (value == null || value.trim().isEmpty) {
                        return isAr ? 'المعرف مطلوب' : 'Employee ID required';
                      }
                      return null;
                    },
                  ),
                ],
                TextFormField(
                  controller: _monthController,
                  decoration: InputDecoration(
                    labelText: isAr ? 'الشهر' : 'Month (1-12)',
                  ),
                  keyboardType: TextInputType.number,
                ),
                TextFormField(
                  controller: _yearController,
                  decoration: InputDecoration(
                    labelText: isAr ? 'السنة' : 'Year',
                  ),
                  keyboardType: TextInputType.number,
                ),
                TextFormField(
                  controller: _basicController,
                  decoration: InputDecoration(
                    labelText: isAr ? 'الراتب الأساسي' : 'Basic Salary',
                  ),
                  keyboardType: TextInputType.number,
                ),
                TextFormField(
                  controller: _allowancesController,
                  decoration: InputDecoration(
                    labelText: isAr ? 'البدلات' : 'Allowances',
                  ),
                  keyboardType: TextInputType.number,
                ),
                TextFormField(
                  controller: _deductionsController,
                  decoration: InputDecoration(
                    labelText: isAr ? 'الخصومات' : 'Deductions',
                  ),
                  keyboardType: TextInputType.number,
                ),
                TextFormField(
                  controller: _netController,
                  decoration: InputDecoration(
                    labelText: isAr ? 'صافي الراتب' : 'Net Salary',
                    suffixIcon: Icon(
                      Icons.lock,
                      color: Theme.of(context).colorScheme.primary,
                    ),
                  ),
                  keyboardType: TextInputType.number,
                  enabled: false, // ✅ للقراءة فقط - يتم حسابه تلقائياً
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                ),
                TextFormField(
                  controller: _notesController,
                  decoration: InputDecoration(
                    labelText: isAr ? 'ملاحظات' : 'Notes',
                  ),
                  maxLines: 2,
                ),
                DropdownButtonFormField<String>(
                  initialValue: _status,
                  items: const [
                    DropdownMenuItem(value: 'pending', child: Text('Pending')),
                    DropdownMenuItem(
                      value: 'approved',
                      child: Text('Approved'),
                    ),
                    DropdownMenuItem(value: 'paid', child: Text('Paid')),
                    DropdownMenuItem(
                      value: 'cancelled',
                      child: Text('Cancelled'),
                    ),
                  ],
                  onChanged: (value) =>
                      setState(() => _status = value ?? 'pending'),
                  decoration: InputDecoration(
                    labelText: isAr ? 'الحالة' : 'Status',
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(isAr ? 'إلغاء' : 'Cancel'),
        ),
        FilledButton(onPressed: _submit, child: Text(isAr ? 'حفظ' : 'Save')),
      ],
    );
  }
}
