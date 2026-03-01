import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../api_service.dart';
import '../theme/app_theme.dart';

// ─── Supported import types ───────────────────────────────────────────────────

enum _DocType {
  salesInvoices,
  purchaseInvoices,
  salesReturns,
  purchaseReturns,
  journalEntries,
  openingEntries,
}

class _DocTypeMeta {
  final _DocType type;
  final String labelAr;
  final String labelEn;
  final String endpointPath; // relative to /api, used by ApiService
  final String hintAr;
  final String hintEn;
  final IconData icon;
  final bool enabled;

  const _DocTypeMeta({
    required this.type,
    required this.labelAr,
    required this.labelEn,
    required this.endpointPath,
    required this.hintAr,
    required this.hintEn,
    required this.icon,
    required this.enabled,
  });
}

const _kDocTypes = <_DocTypeMeta>[
  _DocTypeMeta(
    type: _DocType.salesInvoices,
    labelAr: 'فواتير البيع',
    labelEn: 'Sales Invoices',
    endpointPath: '/devtools/import/sales-invoices',
    hintAr:
        'اختر ملف Excel (xlsx) ثم نفّذ Dry-run للمعاينة، وبعدها Apply لإنشاء الفواتير فعلاً.',
    hintEn:
        'Pick an Excel (.xlsx) file, run dry-run to preview, then apply to create the invoices.',
    icon: Icons.receipt_long,
    enabled: true,
  ),
  _DocTypeMeta(
    type: _DocType.purchaseInvoices,
    labelAr: 'فواتير الشراء',
    labelEn: 'Purchase Invoices',
    endpointPath: '/devtools/import/purchase-invoices',
    hintAr: 'غير متوفر حالياً — يلزم إضافة endpoint في الباك-إند + تحديد قالب Excel.',
    hintEn: 'Not available yet — requires a backend endpoint and an Excel template.',
    icon: Icons.shopping_bag,
    enabled: false,
  ),
  _DocTypeMeta(
    type: _DocType.salesReturns,
    labelAr: 'مرتجعات البيع',
    labelEn: 'Sales Returns',
    endpointPath: '/devtools/import/sales-returns',
    hintAr: 'غير متوفر حالياً — يلزم إضافة endpoint في الباك-إند + تحديد قالب Excel.',
    hintEn: 'Not available yet — requires a backend endpoint and an Excel template.',
    icon: Icons.assignment_return,
    enabled: false,
  ),
  _DocTypeMeta(
    type: _DocType.purchaseReturns,
    labelAr: 'مرتجعات الشراء',
    labelEn: 'Purchase Returns',
    endpointPath: '/devtools/import/purchase-returns',
    hintAr: 'غير متوفر حالياً — يلزم إضافة endpoint في الباك-إند + تحديد قالب Excel.',
    hintEn: 'Not available yet — requires a backend endpoint and an Excel template.',
    icon: Icons.keyboard_return,
    enabled: false,
  ),
  _DocTypeMeta(
    type: _DocType.journalEntries,
    labelAr: 'قيود اليومية',
    labelEn: 'Journal Entries',
    endpointPath: '/devtools/import/journal-entries',
    hintAr: 'غير متوفر حالياً — يلزم إضافة endpoint في الباك-إند + تحديد قالب Excel.',
    hintEn: 'Not available yet — requires a backend endpoint and an Excel template.',
    icon: Icons.article,
    enabled: false,
  ),
  _DocTypeMeta(
    type: _DocType.openingEntries,
    labelAr: 'قيود افتتاحية',
    labelEn: 'Opening Entries',
    endpointPath: '/devtools/import/opening-entries',
    hintAr: 'غير متوفر حالياً — يلزم إضافة endpoint في الباك-إند + تحديد قالب Excel.',
    hintEn: 'Not available yet — requires a backend endpoint and an Excel template.',
    icon: Icons.flag,
    enabled: false,
  ),
];

// ─── Screen ───────────────────────────────────────────────────────────────────

class ImportDocumentsScreen extends StatefulWidget {
  final bool isArabic;

  const ImportDocumentsScreen({
    super.key,
    required this.isArabic,
  });

  @override
  State<ImportDocumentsScreen> createState() => _ImportDocumentsScreenState();
}

class _ImportDocumentsScreenState extends State<ImportDocumentsScreen> {
  final ApiService _api = ApiService();

  // Selected document type
  _DocType _selectedType = _kDocTypes.first.type;
  _DocTypeMeta get _meta =>
      _kDocTypes.firstWhere((m) => m.type == _selectedType);

  // File state
  PlatformFile? _picked;
  Uint8List? _fileBytes;

  // Operation state
  bool _busy = false;
  Map<String, dynamic>? _lastResult;
  bool _lastWasApply = false;

  bool get _hasFile => _picked != null && _fileBytes != null;

  // ── Helpers ───────────────────────────────────────────────────────────────

  void _resetFile() {
    setState(() {
      _picked = null;
      _fileBytes = null;
      _lastResult = null;
      _lastWasApply = false;
    });
  }

  void _selectType(_DocType t) {
    if (t == _selectedType) return;
    setState(() {
      _selectedType = t;
      // Reset file & result when switching type to avoid confusion
      _picked = null;
      _fileBytes = null;
      _lastResult = null;
      _lastWasApply = false;
    });
  }

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
      if (result == null || result.files.isEmpty) return;

      final file = result.files.first;
      final bytes = file.bytes;
      if (bytes == null || bytes.isEmpty) {
        throw Exception(
            widget.isArabic ? 'تعذر قراءة بيانات الملف' : 'Unable to read file bytes');
      }
      setState(() {
        _picked = file;
        _fileBytes = bytes;
      });
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _run({required bool apply}) async {
    if (!_hasFile) return;
    if (!_meta.enabled) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            widget.isArabic
                ? 'هذا النوع غير متوفر حالياً في الباك-إند'
                : 'This document type is not available on the backend yet',
          ),
          backgroundColor: Theme.of(context).colorScheme.error,
        ),
      );
      return;
    }
    setState(() {
      _busy = true;
      _lastResult = null;
      _lastWasApply = apply;
    });
    try {
      final res = await _api.importDocumentsFromExcel(
        fileBytes: _fileBytes!,
        filename: _picked?.name ?? 'import.xlsx',
        apply: apply,
        endpointPath: _meta.endpointPath,
      );
      setState(() => _lastResult = res);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            widget.isArabic
                ? (apply ? 'تم تنفيذ الاستيراد بنجاح' : 'تم التحليل بنجاح')
                : (apply ? 'Import completed' : 'Dry-run completed'),
          ),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(widget.isArabic ? 'فشل: $e' : 'Failed: $e'),
          backgroundColor: Theme.of(context).colorScheme.error,
        ),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ── Widgets ───────────────────────────────────────────────────────────────

  /// Chip row to select the document type (only shown when > 1 type available).
  Widget _buildTypeSelector(ThemeData theme) {
    if (_kDocTypes.length <= 1) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: 14),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: _kDocTypes.map((m) {
          final selected = m.type == _selectedType;
          return ChoiceChip(
            avatar: Icon(m.icon, size: 16),
            label: Text(
              widget.isArabic ? m.labelAr : m.labelEn,
              style: TextStyle(
                color: m.enabled
                    ? null
                    : theme.textTheme.bodyMedium?.color
                        ?.withValues(alpha: 0.55),
              ),
            ),
            selected: selected,
            onSelected: (_) => _selectType(m.type),
          );
        }).toList(),
      ),
    );
  }

  /// Current file info line below the pick button.
  String get _fileInfoText {
    if (_picked == null) {
      return widget.isArabic ? 'لا يوجد ملف محدد' : 'No file selected';
    }
    final base =
        '${_picked!.name} (${(_picked!.size / 1024).toStringAsFixed(1)} KB)';
    final sheetName = _lastResult?['sheet_name'] as String?;
    if (sheetName != null && sheetName.isNotEmpty) {
      final label = widget.isArabic ? 'الشيت' : 'Sheet';
      return '$base  •  $label: "$sheetName"';
    }
    return base;
  }

  Widget _buildKeyValue(String k, Object? v, ThemeData theme) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              k,
              style:
                  theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
          const SizedBox(width: 10),
          Text(v?.toString() ?? '-', style: theme.textTheme.bodyMedium),
        ],
      ),
    );
  }

  /// Type-specific rows for the result card.
  List<Widget> _buildTypeSpecificRows(
      Map<String, dynamic> res, ThemeData theme) {
    switch (_selectedType) {
      case _DocType.salesInvoices:
        return [
          _buildKeyValue(
            widget.isArabic ? 'الصفوف المقروءة' : 'Parsed rows',
            res['parsed_rows'],
            theme,
          ),
          _buildKeyValue(
            widget.isArabic ? 'عدد مجموعات الفواتير' : 'Invoice groups',
            res['invoice_groups_total'],
            theme,
          ),
          _buildKeyValue(
            widget.isArabic ? 'سيتم إنشاؤها' : 'Would create',
            res['groups_would_create'],
            theme,
          ),
          _buildKeyValue(
            widget.isArabic ? 'تم تخطيها (مكررة)' : 'Skipped (existing)',
            res['groups_skipped_existing'],
            theme,
          ),
          _buildKeyValue(
            widget.isArabic ? 'تم تخطيها (بدون موظف)' : 'Skipped (no employee)',
            res['groups_skipped_missing_employee'],
            theme,
          ),
          if (_lastWasApply)
            _buildKeyValue(
              widget.isArabic ? 'تم إنشاؤها' : 'Created',
              res['created_invoices'],
              theme,
            ),
        ];

      case _DocType.purchaseInvoices:
      case _DocType.salesReturns:
      case _DocType.purchaseReturns:
      case _DocType.journalEntries:
      case _DocType.openingEntries:
        return [
          _buildKeyValue(
            widget.isArabic ? 'الحالة' : 'Status',
            widget.isArabic ? 'غير متوفر حالياً' : 'Not available yet',
            theme,
          ),
        ];
    }
  }

  Widget _buildResult(ThemeData theme) {
    final res = _lastResult;
    if (res == null) return const SizedBox.shrink();

    final sheetName = res['sheet_name'] as String?;
    final warnings =
        (res['warnings'] is List) ? (res['warnings'] as List) : const [];
    final errors = (res['row_parse_errors'] is List)
        ? (res['row_parse_errors'] as List)
        : const [];

    final headerText = widget.isArabic
        ? (_lastWasApply ? 'نتيجة التنفيذ' : 'نتيجة التحليل')
        : (_lastWasApply ? 'Apply Result' : 'Dry-run Result');

    final isSuccess = res['success'] == true;

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(
          color: isSuccess
              ? theme.colorScheme.primary.withValues(alpha: 0.4)
              : theme.colorScheme.error.withValues(alpha: 0.5),
        ),
      ),
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(16, 14, 16, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  isSuccess ? Icons.check_circle_outline : Icons.error_outline,
                  color: isSuccess
                      ? theme.colorScheme.primary
                      : theme.colorScheme.error,
                  size: 20,
                ),
                const SizedBox(width: 8),
                Text(
                  headerText,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),

            // Sheet name
            if (sheetName != null && sheetName.isNotEmpty)
              _buildKeyValue(
                widget.isArabic ? 'الشيت المقروء' : 'Sheet read',
                '"$sheetName"',
                theme,
              ),

            // Type-specific stats
            ..._buildTypeSpecificRows(res, theme),

            // Warnings
            if (warnings.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                widget.isArabic
                    ? 'تحذيرات (أول ${warnings.length > 10 ? 10 : warnings.length})'
                    : 'Warnings (first ${warnings.length > 10 ? 10 : warnings.length})',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 4),
              ...warnings.take(10).map(
                    (w) => Padding(
                      padding: const EdgeInsetsDirectional.only(bottom: 3),
                      child: Text('- ${w.toString()}',
                          style: theme.textTheme.bodySmall),
                    ),
                  ),
              if (warnings.length > 10)
                Text(
                  widget.isArabic
                      ? '... (${warnings.length - 10} أخرى)'
                      : '... (${warnings.length - 10} more)',
                  style: theme.textTheme.bodySmall,
                ),
            ],

            // Parse errors
            if (errors.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                widget.isArabic ? 'أخطاء قراءة الصفوف' : 'Row parse errors',
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: theme.colorScheme.error,
                ),
              ),
              const SizedBox(height: 4),
              ...errors.take(10).map(
                    (e) => Padding(
                      padding: const EdgeInsetsDirectional.only(bottom: 3),
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

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final meta = _meta;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.isArabic ? 'استيراد المستندات (Excel)' : 'Import Documents (Excel)',
          style: const TextStyle(fontFamily: 'Cairo'),
        ),
      ),
      body: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(16, 16, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ── Type selector (hidden when only one type) ──────────────────
            _buildTypeSelector(theme),

            // ── Main card ─────────────────────────────────────────────────
            Card(
              elevation: 0,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
                side: BorderSide(
                    color: theme.dividerColor.withValues(alpha: 0.55)),
              ),
              child: Padding(
                padding:
                    const EdgeInsetsDirectional.fromSTEB(16, 14, 16, 14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Current type label
                    Row(
                      children: [
                        Icon(meta.icon,
                            size: 18,
                            color: theme.colorScheme.primary),
                        const SizedBox(width: 8),
                        Text(
                          widget.isArabic ? meta.labelAr : meta.labelEn,
                          style: theme.textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                            color: theme.colorScheme.primary,
                          ),
                        ),
                        if (!meta.enabled) ...[
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsetsDirectional.fromSTEB(
                                8, 3, 8, 3),
                            decoration: BoxDecoration(
                              color: theme.dividerColor.withValues(alpha: 0.2),
                              borderRadius: BorderRadius.circular(999),
                            ),
                            child: Text(
                              widget.isArabic ? 'قريباً' : 'Soon',
                              style: theme.textTheme.labelSmall?.copyWith(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 6),
                    // Hint text
                    Text(
                      widget.isArabic ? meta.hintAr : meta.hintEn,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.textTheme.bodySmall?.color
                            ?.withValues(alpha: 0.75),
                      ),
                    ),
                    const SizedBox(height: 12),

                    // Pick button
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: (_busy || !meta.enabled) ? null : _pickFile,
                            icon: const Icon(Icons.upload_file),
                            label: Text(
                              widget.isArabic
                                  ? 'اختيار ملف Excel'
                                  : 'Choose Excel file',
                            ),
                          ),
                        ),
                        if (_hasFile) ...[
                          const SizedBox(width: 8),
                          IconButton(
                            tooltip: widget.isArabic
                                ? 'إزالة الملف'
                                : 'Clear file',
                            icon: const Icon(Icons.close, size: 18),
                            onPressed: _busy ? null : _resetFile,
                          ),
                        ],
                        if (_busy) ...[
                          const SizedBox(width: 8),
                          const SizedBox(
                            width: 18,
                            height: 18,
                            child:
                                CircularProgressIndicator(strokeWidth: 2),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 8),

                    // File info
                    Text(
                      _fileInfoText,
                      style: theme.textTheme.bodySmall,
                    ),
                    const SizedBox(height: 12),

                    // Action buttons
                    Row(
                      children: [
                        Expanded(
                          child: ElevatedButton(
                            onPressed: (_busy || !_hasFile || !meta.enabled)
                                ? null
                                : () => _run(apply: false),
                            child: Text(
                              widget.isArabic
                                  ? 'تحليل (Dry-run)'
                                  : 'Dry-run',
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ElevatedButton(
                            onPressed: (_busy || !_hasFile || !meta.enabled)
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

            // ── Result card ───────────────────────────────────────────────
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
