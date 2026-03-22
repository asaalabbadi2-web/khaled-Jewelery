import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';
import 'package:pdf/pdf.dart';

import '../api_service.dart';
import '../pdf/voucher_pdf_builder.dart';
import '../providers/settings_provider.dart';
import '../theme/app_theme.dart' as theme;

Future<bool?> showVoucherDetailsSheet(
  BuildContext context, {
  required int voucherId,
}) {
  return showModalBottomSheet<bool>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    builder: (sheetContext) {
      return FractionallySizedBox(
        heightFactor: 0.94,
        child: ClipRRect(
          borderRadius: const BorderRadius.vertical(top: Radius.circular(28)),
          child: VoucherDetailsScreen(voucherId: voucherId, asSheet: true),
        ),
      );
    },
  );
}

class VoucherDetailsScreen extends StatefulWidget {
  final int voucherId;
  final bool asSheet;

  const VoucherDetailsScreen({
    super.key,
    required this.voucherId,
    this.asSheet = false,
  });

  @override
  State<VoucherDetailsScreen> createState() => _VoucherDetailsScreenState();
}

class _VoucherDetailsScreenState extends State<VoucherDetailsScreen> {
  final ApiService _apiService = ApiService();

  Map<String, dynamic>? _voucher;
  bool _isLoading = true;
  String? _error;

  final NumberFormat _currencyFormat = NumberFormat('#,##0.00', 'ar');
  final NumberFormat _weightFormat = NumberFormat('#,##0.000', 'ar');

  @override
  void initState() {
    super.initState();
    _loadVoucher();
  }

  Future<void> _loadVoucher() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final voucher = await _apiService.getVoucher(widget.voucherId);
      setState(() {
        _voucher = voucher;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Future<void> _deleteVoucher() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('تأكيد الحذف'),
        content: const Text(
          'هل أنت متأكد من حذف هذا السند؟\nلا يمكن التراجع عن هذا الإجراء.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('إلغاء'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: theme.AppColors.error),
            child: const Text('حذف'),
          ),
        ],
      ),
    );

    if (confirm == true) {
      try {
        await _apiService.deleteVoucher(widget.voucherId);
        if (!mounted) return;
        _showSnack('تم حذف السند بنجاح');
        Navigator.pop(context, true);
      } catch (e) {
        if (!mounted) return;
        _showSnack('خطأ في الحذف: $e', error: true);
      }
    }
  }

  Future<void> _cancelVoucher() async {
    String? reason;
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('إلغاء السند'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('الرجاء إدخال سبب الإلغاء:'),
            const SizedBox(height: 16),
            TextField(
              decoration: const InputDecoration(
                hintText: 'سبب الإلغاء',
                border: OutlineInputBorder(),
              ),
              maxLines: 3,
              onChanged: (value) => reason = value,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('إلغاء'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: theme.AppColors.error),
            child: const Text('إلغاء السند'),
          ),
        ],
      ),
    );

    if (confirm == true && reason != null && reason!.isNotEmpty) {
      try {
        await _apiService.cancelVoucher(widget.voucherId, reason!);
        if (!mounted) return;
        _showSnack('تم إلغاء السند بنجاح');
        _loadVoucher();
      } catch (e) {
        if (!mounted) return;
        _showSnack('خطأ في الإلغاء: $e', error: true);
      }
    } else if (confirm == true) {
      _showSnack('يجب إدخال سبب الإلغاء', error: true);
    }
  }

  Future<void> _approveVoucher() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('اعتماد السند'),
        content: const Text(
          'هل تريد اعتماد (ترحيل) هذا السند الآن؟ سيتم إنشاء قيد محاسبي.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('إلغاء'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(
              foregroundColor: theme.AppColors.primaryGold,
            ),
            child: const Text('اعتماد'),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    try {
      await _apiService.approveVoucher(widget.voucherId);
      if (!mounted) return;
      _showSnack('تم اعتماد السند');
      _loadVoucher();
    } catch (e) {
      if (!mounted) return;
      _showSnack('خطأ في اعتماد السند: $e', error: true);
    }
  }

  Future<Uint8List> _buildVoucherPdfBytes(PdfPageFormat format) async {
    final voucher = _voucher;
    if (voucher == null) return Uint8List(0);

    SettingsProvider? sp;
    try {
      sp = context.read<SettingsProvider>();
    } catch (_) {}

    return VoucherPdfBuilder.buildBytes(
      voucher: voucher,
      format: format,
      options: const VoucherPdfOptions(
        isArabic: true,
        includeAccountLines: false,
      ),
      settings: sp,
    );
  }

  Future<({String paperSize, String orientation})> _loadPrintPrefs() async {
    final prefs = await SharedPreferences.getInstance();
    final storedPaper = prefs.getString('printer_paper_size_v1') ?? 'A4';
    final normalizedPaper = storedPaper.contains('A5') ? 'A5' : 'A4';
    return (paperSize: normalizedPaper, orientation: 'portrait');
  }

  String _voucherPdfFilename() {
    final v = _voucher;
    final id = (v?['id'] ?? '').toString();
    final number = (v?['voucher_number'] ?? '').toString();
    final base = number.trim().isNotEmpty ? number.trim() : (id.isNotEmpty ? 'voucher_$id' : 'voucher');
    return '$base.pdf';
  }

  Future<void> _printVoucher() async {
    if (_voucher == null) return;
    try {
      await Printing.layoutPdf(
        name: _voucherPdfFilename(),
        onLayout: (format) => _buildVoucherPdfBytes(format),
      );
    } catch (e) {
      if (!mounted) return;
      _showSnack('تعذر فتح الطباعة: $e', error: true);
    }
  }

  Future<void> _downloadVoucherPdf() async {
    if (_voucher == null) return;
    try {
      final prefs = await _loadPrintPrefs();
      final format = VoucherPdfBuilder.pageFormatFromSettings(
        paperSize: prefs.paperSize,
        orientation: prefs.orientation,
      );
      final bytes = await _buildVoucherPdfBytes(format);
      await Printing.sharePdf(bytes: bytes, filename: _voucherPdfFilename());
    } catch (e) {
      if (!mounted) return;
      _showSnack('تعذر تحميل PDF: $e', error: true);
    }
  }

  Future<void> _shareVoucherPdf() async {
    if (_voucher == null) return;
    try {
      final prefs = await _loadPrintPrefs();
      final format = VoucherPdfBuilder.pageFormatFromSettings(
        paperSize: prefs.paperSize,
        orientation: prefs.orientation,
      );
      final bytes = await _buildVoucherPdfBytes(format);
      await Printing.sharePdf(bytes: bytes, filename: _voucherPdfFilename());
    } catch (e) {
      if (!mounted) return;
      _showSnack('تعذر مشاركة PDF: $e', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return widget.asSheet
          ? const Material(
              color: Colors.white,
              child: Center(child: CircularProgressIndicator()),
            )
          : Scaffold(
              appBar: AppBar(title: const Text('تفاصيل السند')),
              body: const Center(child: CircularProgressIndicator()),
            );
    }

    if (_error != null || _voucher == null) {
      final errorBody = Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.error_outline, size: 64, color: Colors.red[300]),
            const SizedBox(height: 16),
            Text('خطأ: $_error'),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadVoucher,
              child: const Text('إعادة المحاولة'),
            ),
          ],
        ),
      );

      return widget.asSheet
          ? Material(color: Colors.white, child: errorBody)
          : Scaffold(
              appBar: AppBar(title: const Text('تفاصيل السند')),
              body: errorBody,
            );
    }

    final voucher = _voucher!;
    final voucherType = voucher['voucher_type'] ?? 'unknown';
    final status = voucher['status'] ?? 'active';
    final isCancelled = status == 'cancelled';
    final isActive = status == 'active';
    final double? amountCash = _toDouble(voucher['amount_cash']);
    final double? amountGold = _toDouble(voucher['amount_gold']);

    Color typeColor;
    IconData typeIcon;
    String typeText;

    switch (voucherType) {
      case 'receipt':
        typeColor = Colors.green;
        typeIcon = Icons.south;
        typeText = 'سند قبض';
        break;
      case 'payment':
        typeColor = Colors.red;
        typeIcon = Icons.north;
        typeText = 'سند صرف';
        break;
      case 'adjustment':
        typeColor = Colors.orange;
        typeIcon = Icons.balance;
        typeText = 'سند تسوية';
        break;
      default:
        typeColor = Colors.grey;
        typeIcon = Icons.help;
        typeText = 'غير محدد';
    }

    final actions = [
      if (isActive) ...[
        IconButton(
          icon: const Icon(Icons.cancel),
          onPressed: _cancelVoucher,
          tooltip: 'إلغاء السند',
        ),
        IconButton(
          icon: const Icon(Icons.delete),
          onPressed: _deleteVoucher,
          tooltip: 'حذف السند',
        ),
      ],
      if (!isCancelled && (voucher['status'] ?? '') != 'approved')
        IconButton(
          icon: const Icon(Icons.check_circle_outline),
          onPressed: () async => await _approveVoucher(),
          tooltip: 'اعتماد/ترحيل السند',
        ),
      IconButton(
        icon: const Icon(Icons.download),
        onPressed: _downloadVoucherPdf,
        tooltip: 'تحميل PDF',
      ),
      IconButton(
        icon: const Icon(Icons.share),
        onPressed: _shareVoucherPdf,
        tooltip: 'مشاركة',
      ),
      IconButton(
        icon: const Icon(Icons.print),
        onPressed: _printVoucher,
        tooltip: 'طباعة',
      ),
    ];

    final String voucherNumber = (voucher['voucher_number'] ?? '').toString();
    final String statusText = _getStatusName(status.toString());
    final Color statusColor = _getStatusColor(status.toString());
    final String dateText = _formatDateOnly(voucher['date']);

    final String? cashText = (amountCash != null && amountCash > 0)
        ? '${_currencyFormat.format(amountCash)} ر.س'
        : null;
    final String? goldText = (amountGold != null && amountGold > 0)
        ? '${_weightFormat.format(amountGold)} غ'
        : null;
    final String? equivalentGoldText = _formatEquivalentGold(voucher);
    final List<String> goldBreakdownLines = _extractGoldBreakdownLines(voucher);

    final body = RefreshIndicator(
      onRefresh: _loadVoucher,
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildSectionCard(
              title: 'ملخص السند',
              icon: Icons.receipt_long_outlined,
              accentColor: typeColor,
              child: Column(
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(11),
                        decoration: BoxDecoration(
                          color: typeColor.withValues(alpha: 0.16),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Icon(typeIcon, color: typeColor, size: 26),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              voucherNumber,
                              style: TextStyle(
                                fontSize: 22,
                                fontWeight: FontWeight.w800,
                                decoration: isCancelled
                                    ? TextDecoration.lineThrough
                                    : null,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              typeText,
                              style: TextStyle(
                                color: typeColor,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ],
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 6,
                        ),
                        decoration: BoxDecoration(
                          color: statusColor.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: statusColor.withValues(alpha: 0.3),
                          ),
                        ),
                        child: Text(
                          statusText,
                          style: TextStyle(
                            color: statusColor,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  _buildInfoRow('التاريخ', dateText, Icons.calendar_today),
                  if (isCancelled) ...[
                    const SizedBox(height: 8),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.red.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(
                          color: Colors.red.withValues(alpha: 0.3),
                        ),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'السند ملغى',
                            style: TextStyle(
                              color: Colors.red,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          if (voucher['cancellation_reason'] != null)
                            Padding(
                              padding: const EdgeInsets.only(top: 6),
                              child: Text(
                                'السبب: ${voucher['cancellation_reason']}',
                                style: const TextStyle(color: Colors.black87),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 12),

            _buildSectionCard(
              title: 'المبلغ والوزن',
              icon: Icons.account_balance_wallet_outlined,
              accentColor: theme.AppColors.primaryGold,
              child: Column(
                children: [
                  if (cashText != null)
                    _buildAmountRow(
                      'المبلغ النقدي',
                      cashText,
                      Icons.payments_outlined,
                      theme.AppColors.success,
                    ),
                  if (goldText != null)
                    _buildAmountRow(
                      'وزن الذهب',
                      goldText,
                      Icons.scale_outlined,
                      theme.AppColors.darkGold,
                    ),
                  if (equivalentGoldText != null)
                    _buildAmountRow(
                      'الوزن المكافئ',
                      equivalentGoldText,
                      Icons.auto_awesome,
                      const Color(0xFFB8860B),
                    ),
                  if (goldBreakdownLines.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.amber.withValues(alpha: 0.08),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(
                            color: Colors.amber.withValues(alpha: 0.24),
                          ),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'تفصيل العيارات',
                              style: TextStyle(
                                fontWeight: FontWeight.w700,
                                color: Colors.black87,
                              ),
                            ),
                            const SizedBox(height: 6),
                            ...goldBreakdownLines.map(
                              (line) => Padding(
                                padding: const EdgeInsets.only(bottom: 4),
                                child: Text(
                                  line,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  if (cashText == null && goldText == null)
                    const Padding(
                      padding: EdgeInsets.only(top: 4),
                      child: Text(
                        'لا توجد قيم مالية أو وزنية مسجلة.',
                        style: TextStyle(color: Colors.black54),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 12),

            _buildSectionCard(
              title: 'الطرف',
              icon: Icons.groups_outlined,
              accentColor: Colors.blueGrey,
              child: Column(
                children: [
                  _buildInfoRow(
                    'نوع الطرف',
                    _getPartyTypeName(voucher['party_type']),
                    Icons.category_outlined,
                  ),
                  if (voucher['customer'] != null)
                    _buildInfoRow(
                      'العميل',
                      voucher['customer']['name'],
                      Icons.person_outline,
                    ),
                  if (voucher['supplier'] != null)
                    _buildInfoRow(
                      'المورد',
                      voucher['supplier']['name'],
                      Icons.store_outlined,
                    ),
                  if (voucher['employee'] != null)
                    _buildInfoRow(
                      'الموظف',
                      voucher['employee']['name']?.toString() ??
                          voucher['employee']['full_name']?.toString() ??
                          'غير محدد',
                      Icons.badge_outlined,
                    ),
                ],
              ),
            ),
            const SizedBox(height: 12),

            if (voucher['description'] != null &&
                voucher['description'].toString().isNotEmpty)
              _buildSectionCard(
                title: 'البيان',
                icon: Icons.description_outlined,
                accentColor: Colors.indigo,
                child: Text(
                  voucher['description'],
                  style: const TextStyle(
                    fontSize: 16,
                    color: Colors.black87,
                    height: 1.5,
                  ),
                ),
              ),
            const SizedBox(height: 12),

            if (voucher['reference_type'] != null &&
                voucher['reference_type'] != 'manual')
              _buildSectionCard(
                title: 'المرجع',
                icon: Icons.link_outlined,
                accentColor: Colors.teal,
                child: Column(
                  children: [
                    _buildInfoRow(
                      'نوع المرجع',
                      _getReferenceTypeName(voucher['reference_type']),
                      Icons.link,
                    ),
                    if (voucher['reference_id'] != null)
                      _buildInfoRow(
                        'رقم المرجع',
                        voucher['reference_id'].toString(),
                        Icons.tag,
                      ),
                  ],
                ),
              ),
            const SizedBox(height: 12),

            if (voucher['notes'] != null &&
                voucher['notes'].toString().isNotEmpty)
              _buildSectionCard(
                title: 'ملاحظات',
                icon: Icons.sticky_note_2_outlined,
                accentColor: Colors.brown,
                child: Text(
                  voucher['notes'],
                  style: const TextStyle(
                    fontSize: 14,
                    color: Colors.black87,
                    height: 1.45,
                  ),
                ),
              ),
            const SizedBox(height: 12),

            _buildSectionCard(
              title: 'معلومات إضافية',
              icon: Icons.info_outline,
              accentColor: Colors.blueGrey,
              child: Column(
                children: [
                  _buildInfoRow(
                    'تاريخ الإنشاء',
                    _formatDateTime(voucher['created_at']),
                    Icons.access_time,
                  ),
                  if (voucher['updated_at'] != null)
                    _buildInfoRow(
                      'آخر تحديث',
                      _formatDateTime(voucher['updated_at']),
                      Icons.update,
                    ),
                  if (voucher['created_by'] != null)
                    _buildInfoRow(
                      'المستخدم',
                      voucher['created_by'],
                      Icons.person,
                    ),
                ],
              ),
            ),

            if (voucher['audit_log'] != null &&
                voucher['audit_log'] is List &&
                voucher['audit_log'].isNotEmpty) ...[
              const SizedBox(height: 12),
              _buildSectionCard(
                title: 'سجل التعديلات',
                icon: Icons.history,
                accentColor: const Color(0xFFFFB300),
                child: Column(
                  children: [
                    ...voucher['audit_log'].map<Widget>(
                      (entry) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFFF8E1),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(
                                Icons.person,
                                size: 18,
                                color: Colors.grey[700],
                              ),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      (entry['user'] ?? '---').toString(),
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                    const SizedBox(height: 2),
                                    Text(
                                      _formatDateTime(entry['timestamp']),
                                      style: TextStyle(
                                        color: Colors.grey[700],
                                        fontSize: 12,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              if (entry['action'] != null)
                                Text(
                                  '(${entry['action']})',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: Colors.black54,
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );

    if (widget.asSheet) {
      return Material(
        color: Colors.white,
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
              decoration: BoxDecoration(
                color: typeColor.withValues(alpha: 0.08),
                border: Border(
                  bottom: BorderSide(color: typeColor.withValues(alpha: 0.18)),
                ),
              ),
              child: Column(
                children: [
                  Center(
                    child: Container(
                      width: 44,
                      height: 5,
                      decoration: BoxDecoration(
                        color: Colors.black.withValues(alpha: 0.18),
                        borderRadius: BorderRadius.circular(100),
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: () => Navigator.of(context).pop(),
                        tooltip: 'إغلاق',
                      ),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              typeText,
                              style: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            Text(
                              voucherNumber,
                              style: TextStyle(
                                color: Colors.black.withValues(alpha: 0.65),
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                      ),
                      ...actions,
                    ],
                  ),
                ],
              ),
            ),
            Expanded(child: body),
          ],
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(typeText),
        backgroundColor: typeColor,
        actions: actions,
      ),
      body: body,
    );
  }

  void _showSnack(String message, {bool error = false}) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: error
            ? theme.AppColors.error
            : theme.AppColors.primaryGold,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  double? _toDouble(dynamic value) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    if (value is String) {
      return double.tryParse(value);
    }
    return null;
  }

  String _formatDateOnly(dynamic value) {
    if (value == null) return 'غير محدد';
    final raw = value.toString();
    if (raw.isEmpty) return 'غير محدد';
    try {
      final dt = DateTime.parse(raw);
      // Use Western digits so date stays stable alongside mixed RTL/LTR text.
      return DateFormat('yyyy/MM/dd', 'en').format(dt);
    } catch (_) {
      return raw;
    }
  }

  String? _formatEquivalentGold(Map<String, dynamic> voucher) {
    final double? amount = _toDouble(voucher['amount_gold_main_karat']);
    if (amount == null || amount == 0) return null;
    final int mainKarat = (_toDouble(voucher['main_karat']) ?? 21).round();
    return 'مكافئ عيار $mainKarat: ${_weightFormat.format(amount)} غ';
  }

  List<String> _extractGoldBreakdownLines(Map<String, dynamic> voucher) {
    final raw = voucher['gold_breakdown'];
    if (raw is List && raw.isNotEmpty) {
      return raw.whereType<Map>().map((entry) {
        final double? weightValue = _toDouble(entry['weight']);
        final String weight = _weightFormat.format(weightValue ?? 0);
        final karat = _toDouble(entry['karat'])?.round() ?? entry['karat'];
        return '• عيار $karat: $weight غ';
      }).toList();
    }

    final double? amountGold = _toDouble(voucher['amount_gold']);
    if (amountGold == null || amountGold == 0) return const [];
    final karat = voucher['gold_karat'];
    if (karat == null || karat.toString().isEmpty || karat == 'متعدد') {
      return ['• إجمالي الذهب: ${_weightFormat.format(amountGold)} غ'];
    }
    return [
      '• عيار ${_toDouble(karat)?.round() ?? karat}: ${_weightFormat.format(amountGold)} غ',
    ];
  }

  String _getStatusName(String status) {
    switch (status) {
      case 'approved':
        return 'مُعتمد';
      case 'cancelled':
        return 'ملغى';
      case 'voided':
        return 'مُبطل';
      case 'active':
      default:
        return 'نشط';
    }
  }

  Color _getStatusColor(String status) {
    switch (status) {
      case 'approved':
        return theme.AppColors.success;
      case 'cancelled':
      case 'voided':
        return theme.AppColors.error;
      case 'active':
      default:
        return const Color(0xFF607D8B);
    }
  }

  Widget _buildSectionCard({
    required String title,
    required IconData icon,
    required Color accentColor,
    required Widget child,
  }) {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: accentColor.withValues(alpha: 0.18)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 18, color: accentColor),
                const SizedBox(width: 6),
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                    color: accentColor,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            child,
          ],
        ),
      ),
    );
  }

  Widget _buildInfoRow(String label, String value, IconData icon) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Icon(icon, size: 20, color: Colors.grey[600]),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(fontSize: 12, color: Colors.grey[600]),
                ),
                Text(
                  value,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                    color: Colors.black87,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAmountRow(
    String label,
    String value,
    IconData icon,
    Color color,
  ) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Icon(icon, size: 24, color: color),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(fontSize: 12, color: Colors.grey[600]),
                ),
                Text(
                  value,
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: color,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _getPartyTypeName(String? type) {
    switch (type) {
      case 'customer':
        return 'عميل';
      case 'supplier':
        return 'مورد';
      case 'other':
        return 'آخر';
      default:
        return 'غير محدد';
    }
  }

  String _getReferenceTypeName(String? type) {
    switch (type) {
      case 'invoice':
        return 'فاتورة';
      case 'journal_entry':
        return 'قيد محاسبي';
      case 'manual':
        return 'يدوي';
      default:
        return 'غير محدد';
    }
  }

  String _formatDateTime(String? dateTime) {
    if (dateTime == null) return 'غير محدد';
    try {
      final dt = DateTime.parse(dateTime);
      return DateFormat('yyyy-MM-dd HH:mm').format(dt);
    } catch (e) {
      return dateTime;
    }
  }
}
