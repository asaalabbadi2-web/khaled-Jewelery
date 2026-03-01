import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../api_service.dart';
import '../theme/app_theme.dart';

class ImportSalesInvoicesExcelScreen extends StatefulWidget {
  final bool isArabic;

  const ImportSalesInvoicesExcelScreen({
    super.key,
    required this.isArabic,
  });

  @override
  State<ImportSalesInvoicesExcelScreen> createState() =>
      _ImportSalesInvoicesExcelScreenState();
}

class _ImportSalesInvoicesExcelScreenState
    extends State<ImportSalesInvoicesExcelScreen> {
  final ApiService _api = ApiService();

  PlatformFile? _picked;
  Uint8List? _fileBytes;

  bool _busy = false;
  Map<String, dynamic>? _lastResult;
  bool _lastWasApply = false;

  bool get _hasFile => _picked != null && _fileBytes != null;

  String get _title => widget.isArabic
      ? 'استيراد فواتير البيع (Excel)'
      : 'Import Sales Invoices (Excel)';

  Future<void> _pickFile() async {
    setState(() {
      _busy = true;
      _lastResult = null;
      _lastWasApply = false;
    });

    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: const ['xlsx'],
        withData: true,
      );

      if (result == null || result.files.isEmpty) {
        return;
      }

      final file = result.files.first;
      final bytes = file.bytes;

      if (bytes == null || bytes.isEmpty) {
        throw Exception(widget.isArabic
            ? 'تعذر قراءة بيانات الملف'
            : 'Unable to read file bytes');
      }

      setState(() {
        _picked = file;
        _fileBytes = bytes;
      });
    } finally {
      setState(() {
        _busy = false;
      });
    }
  }

  Future<void> _run({required bool apply}) async {
    if (!_hasFile) return;

    setState(() {
      _busy = true;
      _lastResult = null;
      _lastWasApply = apply;
    });

    try {
      final res = await _api.importSalesInvoicesFromExcel(
        fileBytes: _fileBytes!,
        filename: _picked?.name ?? 'sales.xlsx',
        apply: apply,
      );

      setState(() {
        _lastResult = res;
      });

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(widget.isArabic
              ? (apply ? 'تم تنفيذ الاستيراد' : 'تم التحليل بنجاح')
              : (apply ? 'Import completed' : 'Dry-run completed')),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(widget.isArabic
              ? 'فشل: $e'
              : 'Failed: $e'),
          backgroundColor: Theme.of(context).colorScheme.error,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
        });
      }
    }
  }

  Widget _buildKeyValue(String k, Object? v, ThemeData theme) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              k,
              style: theme.textTheme.bodyMedium?.copyWith(
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Text(
            v?.toString() ?? '-',
            style: theme.textTheme.bodyMedium,
          ),
        ],
      ),
    );
  }

  Widget _buildResult(ThemeData theme) {
    final res = _lastResult;
    if (res == null) return const SizedBox.shrink();

    final parsedRows = res['parsed_rows'];
    final groupsTotal = res['invoice_groups_total'];
    final sheetName = res['sheet_name'] as String?;
    final wouldCreate = res['groups_would_create'];
    final skippedExisting = res['groups_skipped_existing'];
    final skippedMissingEmployee = res['groups_skipped_missing_employee'];
    final created = res['created_invoices'];

    final warnings = (res['warnings'] is List) ? (res['warnings'] as List) : [];
    final errors = (res['row_parse_errors'] is List)
        ? (res['row_parse_errors'] as List)
        : [];

    final headerText = widget.isArabic
        ? (_lastWasApply ? 'نتيجة التنفيذ' : 'نتيجة التحليل')
        : (_lastWasApply ? 'Apply Result' : 'Dry-run Result');

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.55)),
      ),
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(16, 14, 16, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              headerText,
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 12),
            if (sheetName != null && sheetName.isNotEmpty)
              _buildKeyValue(
                widget.isArabic ? 'الشيت المقروء' : 'Sheet read',
                '"$sheetName"',
                theme,
              ),
            _buildKeyValue(
              widget.isArabic ? 'الصفوف المقروءة' : 'Parsed rows',
              parsedRows,
              theme,
            ),
            _buildKeyValue(
              widget.isArabic ? 'عدد مجموعات الفواتير' : 'Invoice groups',
              groupsTotal,
              theme,
            ),
            _buildKeyValue(
              widget.isArabic ? 'سيتم إنشاؤها' : 'Would create',
              wouldCreate,
              theme,
            ),
            _buildKeyValue(
              widget.isArabic ? 'تم تخطيها (مكررة)' : 'Skipped (existing)',
              skippedExisting,
              theme,
            ),
            _buildKeyValue(
              widget.isArabic
                  ? 'تم تخطيها (بدون موظف)'
                  : 'Skipped (missing employee)',
              skippedMissingEmployee,
              theme,
            ),
            if (_lastWasApply)
              _buildKeyValue(
                widget.isArabic ? 'تم إنشاؤها' : 'Created',
                created,
                theme,
              ),
            const SizedBox(height: 10),
            if (warnings.isNotEmpty) ...[
              Text(
                widget.isArabic ? 'تحذيرات (أول 50)' : 'Warnings (first 50)',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 6),
              ...warnings.take(10).map(
                    (w) => Padding(
                      padding: const EdgeInsetsDirectional.only(bottom: 4),
                      child: Text(
                        '- ${w.toString()}',
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                  ),
              if (warnings.length > 10)
                Text(
                  widget.isArabic
                      ? '... (${warnings.length - 10} أخرى)'
                      : '... (${warnings.length - 10} more)',
                  style: theme.textTheme.bodySmall,
                ),
              const SizedBox(height: 10),
            ],
            if (errors.isNotEmpty) ...[
              Text(
                widget.isArabic ? 'أخطاء قراءة' : 'Parse errors',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 6),
              ...errors.take(10).map(
                    (e) => Padding(
                      padding: const EdgeInsetsDirectional.only(bottom: 4),
                      child: Text(
                        '- ${e.toString()}',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.error,
                        ),
                      ),
                    ),
                  ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: Text(
          _title,
          style: const TextStyle(fontFamily: 'Cairo'),
        ),
      ),
      body: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(16, 16, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Card(
              elevation: 0,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
                side:
                    BorderSide(color: theme.dividerColor.withValues(alpha: 0.55)),
              ),
              child: Padding(
                padding: const EdgeInsetsDirectional.fromSTEB(16, 14, 16, 14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      widget.isArabic
                          ? 'اختر ملف SalesDB.xlsx ثم نفّذ Dry-run وبعدها Apply'
                          : 'Pick SalesDB.xlsx, run dry-run, then apply',
                      style: theme.textTheme.bodyMedium,
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: _busy ? null : _pickFile,
                            icon: const Icon(Icons.upload_file),
                            label: Text(
                              widget.isArabic
                                  ? 'اختيار ملف Excel'
                                  : 'Choose Excel file',
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        if (_busy)
                          const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Text(
                      () {
                        if (_picked == null) {
                          return widget.isArabic
                              ? 'لا يوجد ملف محدد'
                              : 'No file selected';
                        }
                        final base =
                            '${_picked!.name} (${(_picked!.size / 1024).toStringAsFixed(1)} KB)';
                        final sheetName =
                            _lastResult?['sheet_name'] as String?;
                        if (sheetName != null && sheetName.isNotEmpty) {
                          final label =
                              widget.isArabic ? 'الشيت' : 'Sheet';
                          return '$base  •  $label: "$sheetName"';
                        }
                        return base;
                      }(),
                      style: theme.textTheme.bodySmall,
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: ElevatedButton(
                            onPressed: (_busy || !_hasFile)
                                ? null
                                : () => _run(apply: false),
                            child: Text(
                              widget.isArabic ? 'تحليل (Dry-run)' : 'Dry-run',
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ElevatedButton(
                            onPressed: (_busy || !_hasFile)
                                ? null
                                : () => _run(apply: true),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.warning,
                              foregroundColor: Colors.white,
                            ),
                            child: Text(
                              widget.isArabic ? 'تنفيذ (Apply)' : 'Apply',
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 14),
            Expanded(
              child: SingleChildScrollView(
                child: _buildResult(theme),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
