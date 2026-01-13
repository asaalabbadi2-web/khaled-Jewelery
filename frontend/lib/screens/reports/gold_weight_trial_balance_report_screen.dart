import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';

import '../../api_service.dart';
import '../../providers/auth_provider.dart';

class GoldWeightTrialBalanceReportScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;

  const GoldWeightTrialBalanceReportScreen({
    super.key,
    required this.api,
    this.isArabic = true,
  });

  @override
  State<GoldWeightTrialBalanceReportScreen> createState() =>
      _GoldWeightTrialBalanceReportScreenState();
}

class _GoldWeightTrialBalanceReportScreenState
    extends State<GoldWeightTrialBalanceReportScreen> {
  bool _isLoading = true;
  String? _error;
  Map<String, dynamic>? _report;

  final NumberFormat _weightFormat = NumberFormat('#,##0.000');

  @override
  void initState() {
    super.initState();
    _loadReport();
  }

  bool _canViewReport() {
    try {
      return context.read<AuthProvider>().hasPermission('reports.financial');
    } catch (_) {
      return false;
    }
  }

  double _toDouble(dynamic value, {double fallback = 0.0}) {
    if (value == null) return fallback;
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? fallback;
    return fallback;
  }

  String _w(dynamic value) => _weightFormat.format(_toDouble(value));

  String _s(dynamic value) => value?.toString() ?? '';

  Map<String, dynamic> _asMap(dynamic value) {
    if (value is Map<String, dynamic>) return value;
    return const {};
  }

  List<Map<String, dynamic>> _rows() {
    final raw = _report?['rows'];
    if (raw is List) {
      return raw.whereType<Map<String, dynamic>>().toList();
    }
    return const [];
  }

  Map<String, dynamic> _summary() {
    final raw = _report?['summary'];
    if (raw is Map<String, dynamic>) return raw;
    return const {};
  }

  Future<void> _loadReport() async {
    if (!_canViewReport()) {
      setState(() {
        _isLoading = false;
        _report = null;
        _error = widget.isArabic
            ? 'ليس لديك صلاحية لعرض التقارير المالية'
            : 'You do not have permission to view financial reports';
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final result = await widget.api.getGoldWeightTrialBalance();
      if (!mounted) return;
      setState(() => _report = result);
    } catch (err) {
      if (!mounted) return;
      setState(() => _error = err.toString());
    } finally {
      if (!mounted) return;
      setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isArabic = widget.isArabic;

    return Directionality(
      textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        appBar: AppBar(
          title: Text(
            isArabic ? 'ميزان مراجعة الأوزان' : 'Gold Weight Trial Balance',
          ),
          actions: [
            IconButton(
              tooltip: isArabic ? 'تحديث' : 'Refresh',
              icon: const Icon(Icons.refresh),
              onPressed: _isLoading ? null : _loadReport,
            ),
          ],
        ),
        body: SafeArea(
          child: _isLoading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? _buildError(isArabic)
              : RefreshIndicator(
                  onRefresh: _loadReport,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      _buildSummaryCard(isArabic),
                      const SizedBox(height: 16),
                      ..._buildRows(isArabic),
                    ],
                  ),
                ),
        ),
      ),
    );
  }

  Widget _buildError(bool isArabic) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48, color: Colors.red.shade400),
            const SizedBox(height: 12),
            Text(
              isArabic ? 'تعذّر تحميل التقرير' : 'Failed to load report',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            Text(
              _error ?? '',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.grey),
            ),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _loadReport,
              icon: const Icon(Icons.refresh),
              label: Text(isArabic ? 'إعادة المحاولة' : 'Try again'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSummaryCard(bool isArabic) {
    final summary = _summary();
    final total = _toDouble(summary['total_safe_boxes']).toInt();
    final balanced = _toDouble(summary['balanced_safe_boxes']).toInt();
    final unbalanced = _toDouble(summary['unbalanced_safe_boxes']).toInt();
    final absVariance = _w(summary['total_abs_variance_main_karat']);

    final date = _s(_report?['date']);
    final mainKarat = _s(_report?['main_karat']);

    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: isArabic
              ? CrossAxisAlignment.end
              : CrossAxisAlignment.start,
          children: [
            Text(
              isArabic ? 'ملخص' : 'Summary',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                _pill(
                  title: isArabic ? 'التاريخ' : 'Date',
                  value: date.isEmpty ? '-' : date,
                ),
                _pill(
                  title: isArabic ? 'العيار الرئيسي' : 'Main karat',
                  value: mainKarat.isEmpty ? '-' : mainKarat,
                ),
                _pill(
                  title: isArabic ? 'عدد الخزائن' : 'Safe boxes',
                  value: total.toString(),
                ),
                _pill(
                  title: isArabic ? 'مطابق' : 'Balanced',
                  value: balanced.toString(),
                ),
                _pill(
                  title: isArabic ? 'غير مطابق' : 'Unbalanced',
                  value: unbalanced.toString(),
                ),
                _pill(
                  title: isArabic ? 'إجمالي |الفرق|' : 'Total |variance|',
                  value: absVariance,
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              isArabic
                  ? 'إذا كان الفرق = 0 فالحركات سليمة. أي فرق يعني وجود إدخال/تعديل خارج دفتر الخزينة أو خارج القيود.'
                  : 'Zero variance means everything matches. Any variance indicates a manual adjustment outside the safe ledger or journal entries.',
              style: TextStyle(color: Colors.grey.shade700, height: 1.3),
            ),
          ],
        ),
      ),
    );
  }

  Widget _pill({required String title, required String value}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.grey.shade100,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey.shade300),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              fontSize: 12,
              color: Colors.grey.shade700,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  List<Widget> _buildRows(bool isArabic) {
    final rows = _rows();
    if (rows.isEmpty) {
      return [
        Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 36),
            child: Text(
              isArabic ? 'لا توجد خزائن' : 'No safe boxes found',
              style: TextStyle(color: Colors.grey.shade600),
            ),
          ),
        ),
      ];
    }

    return rows
        .map(
          (row) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: _buildSafeRow(isArabic, row),
          ),
        )
        .toList();
  }

  Widget _buildSafeRow(bool isArabic, Map<String, dynamic> row) {
    final safeBox = _asMap(row['safe_box']);
    final safeBal = _asMap(row['safe_balance']);
    final accBal = _asMap(row['account_balance']);
    final variance = _asMap(row['variance']);

    final isBalanced = row['is_balanced'] == true;

    final safeName = _s(safeBox['name']);
    final accountNumber = _s(safeBox['account_number']);
    final accountName = _s(safeBox['account_name']);
    final fixedKarat = safeBox['karat'];

    final varianceMain = _w(variance['total_main_karat']);

    return Card(
      elevation: 1,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        title: Text(
          safeName.isEmpty ? (isArabic ? 'خزنة' : 'Safe box') : safeName,
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        subtitle: Text(
          isArabic
              ? 'الحساب: ${accountNumber.isEmpty ? '-' : accountNumber} ${accountName.isEmpty ? '' : '— $accountName'}'
              : 'Account: ${accountNumber.isEmpty ? '-' : accountNumber} ${accountName.isEmpty ? '' : '— $accountName'}',
        ),
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  isBalanced ? Icons.check_circle : Icons.warning_amber,
                  size: 18,
                  color: isBalanced ? Colors.green.shade700 : Colors.orange,
                ),
                const SizedBox(width: 6),
                Text(
                  varianceMain,
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: isBalanced ? Colors.green.shade800 : Colors.orange,
                  ),
                ),
              ],
            ),
            if (fixedKarat is num)
              Text(
                isArabic
                    ? 'عيار الخزنة: $fixedKarat'
                    : 'Safe karat: $fixedKarat',
                style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
              ),
          ],
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        children: [
          const SizedBox(height: 8),
          _buildThreeColumnByKarat(
            isArabic: isArabic,
            safeByKarat: _asMap(safeBal['by_karat']),
            accountByKarat: _asMap(accBal['by_karat']),
            varianceByKarat: _asMap(variance['by_karat']),
            safeTotalMain: safeBal['total_main_karat'],
            accountTotalMain: accBal['total_main_karat'],
            varianceTotalMain: variance['total_main_karat'],
          ),
        ],
      ),
    );
  }

  Widget _buildThreeColumnByKarat({
    required bool isArabic,
    required Map<String, dynamic> safeByKarat,
    required Map<String, dynamic> accountByKarat,
    required Map<String, dynamic> varianceByKarat,
    required dynamic safeTotalMain,
    required dynamic accountTotalMain,
    required dynamic varianceTotalMain,
  }) {
    Widget rowLine(String label, dynamic a, dynamic b, dynamic c) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          children: [
            SizedBox(
              width: 54,
              child: Text(
                label,
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  color: Colors.grey.shade700,
                ),
              ),
            ),
            Expanded(child: Text(_w(a), textAlign: TextAlign.center)),
            Expanded(child: Text(_w(b), textAlign: TextAlign.center)),
            Expanded(
              child: Text(
                _w(c),
                textAlign: TextAlign.center,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
      );
    }

    return Column(
      children: [
        Row(
          children: [
            const SizedBox(width: 54),
            Expanded(
              child: Text(
                isArabic ? 'رصيد الخزنة' : 'Safe balance',
                textAlign: TextAlign.center,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ),
            Expanded(
              child: Text(
                isArabic ? 'رصيد الحساب' : 'Account balance',
                textAlign: TextAlign.center,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ),
            Expanded(
              child: Text(
                isArabic ? 'الفرق' : 'Variance',
                textAlign: TextAlign.center,
                style: const TextStyle(fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
        Divider(color: Colors.grey.shade300),
        rowLine(
          '18k',
          safeByKarat['18k'],
          accountByKarat['18k'],
          varianceByKarat['18k'],
        ),
        rowLine(
          '21k',
          safeByKarat['21k'],
          accountByKarat['21k'],
          varianceByKarat['21k'],
        ),
        rowLine(
          '22k',
          safeByKarat['22k'],
          accountByKarat['22k'],
          varianceByKarat['22k'],
        ),
        rowLine(
          '24k',
          safeByKarat['24k'],
          accountByKarat['24k'],
          varianceByKarat['24k'],
        ),
        Divider(color: Colors.grey.shade300),
        rowLine(
          isArabic ? 'إجمالي*' : 'Total*',
          safeTotalMain,
          accountTotalMain,
          varianceTotalMain,
        ),
        const SizedBox(height: 6),
        Align(
          alignment: isArabic ? Alignment.centerRight : Alignment.centerLeft,
          child: Text(
            isArabic
                ? '* الإجمالي محوّل للعيار الرئيسي'
                : '* Total converted to main karat',
            style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
          ),
        ),
      ],
    );
  }
}
