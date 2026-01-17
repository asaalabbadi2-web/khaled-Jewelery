import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../api_service.dart';
import '../../providers/auth_provider.dart';
import '../invoice_print_screen.dart';

class InvoiceApprovalScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;
  final int invoiceId;
  final int? alertId;

  /// Optional metadata from SystemAlert.details (for display only).
  final Map<String, dynamic>? alertDetails;

  const InvoiceApprovalScreen({
    super.key,
    required this.api,
    required this.invoiceId,
    this.alertId,
    this.isArabic = true,
    this.alertDetails,
  });

  @override
  State<InvoiceApprovalScreen> createState() => _InvoiceApprovalScreenState();
}

class _InvoiceApprovalScreenState extends State<InvoiceApprovalScreen> {
  bool _loading = true;
  bool _approving = false;
  Map<String, dynamic>? _invoice;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final details = await widget.api.getInvoiceById(widget.invoiceId);
      if (!mounted) return;
      setState(() {
        _invoice = details;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  double _asDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? 0.0;
    return 0.0;
  }

  bool _asBool(dynamic value) {
    if (value is bool) return value;
    if (value is num) return value != 0;
    if (value is String) {
      final s = value.trim().toLowerCase();
      return s == 'true' || s == '1' || s == 'yes' || s == 'y';
    }
    return false;
  }

  Future<void> _openInvoicePreview() async {
    final invoice = _invoice;
    if (invoice == null) return;

    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) =>
            InvoicePrintScreen(invoice: invoice, isArabic: widget.isArabic),
      ),
    );
  }

  Future<void> _confirmAndApprove() async {
    final isArabic = widget.isArabic;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: Text(isArabic ? 'تأكيد الاعتماد' : 'Confirm approval'),
          content: Text(
            isArabic
                ? 'سيتم الآن ترحيل القيود المحاسبية وتعديل أرصدة الخزائن. هل أنت متأكد؟'
                : 'This will post journal entries and update safebox balances. Are you sure?',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(isArabic ? 'إلغاء' : 'Cancel'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.of(ctx).pop(true),
              child: Text(isArabic ? 'اعتماد وترحيل' : 'Approve & Post'),
            ),
          ],
        );
      },
    );

    if (confirmed != true) return;

    setState(() {
      _approving = true;
    });

    try {
      await widget.api.approveInvoice(widget.invoiceId);
      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            isArabic
                ? 'تم اعتماد وترحيل الفاتورة'
                : 'Invoice approved and posted',
          ),
        ),
      );

      // Refresh local invoice state (now posted).
      await _load();

      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(e.toString())));
      setState(() {
        _approving = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final isArabic = widget.isArabic;

    final invoice = _invoice;
    final invoiceType = (invoice?['invoice_type'] ?? '').toString();
    final invoiceNumber = (invoice?['invoice_number'] ?? invoice?['id'] ?? '')
        .toString();
    final isPosted = _asBool(invoice?['is_posted']);
    final total = _asDouble(invoice?['total']);

    final details = widget.alertDetails ?? const <String, dynamic>{};
    final discountPct = details.containsKey('discount_pct')
        ? _asDouble(details['discount_pct'])
        : null;
    final thresholdPct = details.containsKey('threshold_pct')
        ? _asDouble(details['threshold_pct'])
        : null;

    return Directionality(
      textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        appBar: AppBar(
          title: Text(isArabic ? 'تفاصيل اعتماد الفاتورة' : 'Invoice Approval'),
          actions: [
            IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: _loading ? null : _load,
            ),
          ],
        ),
        body: SafeArea(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? _buildError(_error!)
              : _buildBody(
                  invoiceNumber: invoiceNumber,
                  invoiceType: invoiceType,
                  total: total,
                  isPosted: isPosted,
                  discountPct: discountPct,
                  thresholdPct: thresholdPct,
                ),
        ),
      ),
    );
  }

  Widget _buildError(String error) {
    final isArabic = widget.isArabic;
    final theme = Theme.of(context);

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, color: theme.colorScheme.error, size: 40),
            const SizedBox(height: 12),
            Text(
              isArabic
                  ? 'تعذر تحميل تفاصيل الفاتورة'
                  : 'Failed to load invoice',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(
              error,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.hintColor,
              ),
            ),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh),
              label: Text(isArabic ? 'إعادة المحاولة' : 'Try again'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBody({
    required String invoiceNumber,
    required String invoiceType,
    required double total,
    required bool isPosted,
    required double? discountPct,
    required double? thresholdPct,
  }) {
    final isArabic = widget.isArabic;
    final theme = Theme.of(context);
    final auth = context.watch<AuthProvider>();

    final canApprove = auth.isManager;

    final statusText = isPosted
        ? (isArabic ? 'مرحّلة' : 'Posted')
        : (isArabic ? 'غير مرحّلة' : 'Unposted');

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          elevation: 0,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isArabic ? 'الفاتورة' : 'Invoice',
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 12),
                _kv(theme, isArabic ? 'الرقم' : 'Number', invoiceNumber),
                const SizedBox(height: 6),
                _kv(theme, isArabic ? 'النوع' : 'Type', invoiceType),
                const SizedBox(height: 6),
                _kv(
                  theme,
                  isArabic ? 'الإجمالي' : 'Total',
                  total.toStringAsFixed(2),
                ),
                const SizedBox(height: 6),
                _kv(theme, isArabic ? 'الحالة' : 'Status', statusText),
                if (discountPct != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: _kv(
                      theme,
                      isArabic ? 'نسبة الخصم' : 'Discount %',
                      '${discountPct.toStringAsFixed(2)}%',
                    ),
                  ),
                if (thresholdPct != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: _kv(
                      theme,
                      isArabic ? 'حد الاعتماد' : 'Threshold %',
                      '${thresholdPct.toStringAsFixed(2)}%',
                    ),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: _invoice == null ? null : _openInvoicePreview,
          icon: const Icon(Icons.receipt_long),
          label: Text(isArabic ? 'عرض تفاصيل الفاتورة' : 'View invoice'),
        ),
        const SizedBox(height: 12),
        if (!canApprove)
          Card(
            elevation: 0,
            color: theme.colorScheme.surfaceContainerHighest,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                isArabic
                    ? 'لا تملك صلاحية اعتماد وترحيل هذه الفاتورة.'
                    : 'You do not have permission to approve this invoice.',
                style: theme.textTheme.bodyMedium,
              ),
            ),
          ),
        if (canApprove)
          FilledButton.icon(
            onPressed: (isPosted || _approving) ? null : _confirmAndApprove,
            icon: _approving
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.verified_outlined),
            label: Text(
              isArabic ? 'اعتماد وترحيل الفاتورة' : 'Approve & Post Invoice',
            ),
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
            ),
          ),
      ],
    );
  }

  Widget _kv(ThemeData theme, String label, String value) {
    return Row(
      children: [
        SizedBox(
          width: 110,
          child: Text(
            label,
            style: theme.textTheme.bodyMedium?.copyWith(color: theme.hintColor),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            value,
            style: theme.textTheme.bodyMedium?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    );
  }
}
