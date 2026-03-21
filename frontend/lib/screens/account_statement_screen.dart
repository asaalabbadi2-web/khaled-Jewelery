import 'dart:convert';
import 'dart:isolate';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:csv/csv.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:open_file/open_file.dart';
import 'package:path_provider/path_provider.dart';
import 'package:pdf/pdf.dart' as pdf;
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../api_service.dart';
import '../models/account_statement_model.dart';
import '../pdf/account_statement_pdf_builder.dart';
import '../providers/settings_provider.dart';
import '../theme/app_theme.dart' as app_theme;

class AccountStatementScreen extends StatefulWidget {
  final int accountId;
  final String accountName;
  final String entityType; // 'customer', 'supplier', 'account'

  const AccountStatementScreen({
    super.key,
    required this.accountId,
    required this.accountName,
    this.entityType =
        'account', // default to account for backward compatibility
  });

  @override
  State<AccountStatementScreen> createState() => _AccountStatementScreenState();
}

class _AccountStatementScreenState extends State<AccountStatementScreen> {
  bool _isLoading = true;
  AccountStatement? _statement;
  List<StatementLine> _filteredLines = [];
  DateTimeRange? _dateRange;
  final TextEditingController _searchController = TextEditingController();
  String _filterType = 'all'; // 'all', 'credit', 'debit'
  // int? _expandedTransactionId; // Removed: unused

  bool _isRepairingBalances = false;

  final ScrollController _horizontalController = ScrollController();
  final ScrollController _verticalController = ScrollController();

  int _viewMode = 0; // 0: dual, 1: gold, 2: cash
  bool _showOnlyMovement = false;
  bool _includeBreakdown = true;
  bool _isExporting = false;
  bool _useMergedView = false; // Toggle for merged statement
  bool _resolvedMergedDefault = false;
  bool _resolvedViewModeDefault = false;

  bool _pdfIncludeValuation = true;
  int? _pdfViewModeOverride;
  bool _pdfLandscape = false;

  Future<AccountStatementPdfBranding> _resolvePdfBranding({
    required bool fetchIfEmpty,
  }) async {
    SettingsProvider? settingsProvider;
    try {
      settingsProvider = context.read<SettingsProvider>();
    } catch (_) {
      settingsProvider = null;
    }

    if (fetchIfEmpty && settingsProvider != null && settingsProvider.settings.isEmpty) {
      try {
        await settingsProvider.fetchSettings().timeout(
          const Duration(milliseconds: 800),
        );
      } catch (_) {
        // Non-blocking.
      }
    }

    final companyName = (settingsProvider?.companyName ?? '').trim();
    final companyAddress = (settingsProvider?.companyAddress ?? '').trim();
    final companyPhone = (settingsProvider?.companyPhone ?? '').trim();
    final companyVat = (settingsProvider?.companyTaxNumber ?? '').trim();
    final companyCr = (settingsProvider?.companyCrNumber ?? '').trim();
    final showCompanyLogo = settingsProvider?.showCompanyLogo ?? true;
    final companyLogoBase64 =
        (settingsProvider?.settings['company_logo_base64'] ?? '').toString();

    return AccountStatementPdfBranding(
      companyName: companyName,
      companyAddress: companyAddress,
      companyPhone: companyPhone,
      companyVat: companyVat,
      companyCr: companyCr,
      showCompanyLogo: showCompanyLogo,
      companyLogoBase64: companyLogoBase64,
    );
  }

  Future<Uint8List> _resizeImageBytes(Uint8List bytes, int targetSize) async {
    try {
      final codec = await ui.instantiateImageCodec(
        bytes,
        targetWidth: targetSize,
        targetHeight: targetSize,
      );
      final frame = await codec.getNextFrame();
      final byteData =
          await frame.image.toByteData(format: ui.ImageByteFormat.png);
      frame.image.dispose();
      if (byteData != null) return byteData.buffer.asUint8List();
    } catch (_) {}
    return bytes;
  }

  bool _truthy(dynamic v) {
    if (v is bool) return v;
    if (v is num) return v != 0;
    if (v is String) {
      final s = v.trim().toLowerCase();
      return s == 'true' || s == '1' || s == 'yes' || s == 'on';
    }
    return false;
  }

  bool _shouldDefaultToMergedView(Map<String, dynamic> account) {
    // Safe-box accounts that are not gold should not default to merged view.
    // This avoids showing weight-side memo movements in payment method statements.
    try {
      final safeType = (account['safe_box_type'] ?? '')
          .toString()
          .trim()
          .toLowerCase();
      if (safeType.isNotEmpty && safeType != 'gold') return false;
    } catch (_) {}

    try {
      if (_truthy(account['tracks_weight'])) return true;
    } catch (_) {}

    try {
      final num = (account['account_number'] ?? '').toString().trim();
      if (num.startsWith('7')) return true; // memo accounts are typically 7xxxx
    } catch (_) {}

    return false;
  }

  int _defaultViewModeForAccount(Map<String, dynamic> account) {
    // Default cash/bank style accounts to cash-only.
    // Weight/memo accounts keep the dual view by default.
    try {
      final safeType = (account['safe_box_type'] ?? '')
          .toString()
          .trim()
          .toLowerCase();
      if (safeType.isNotEmpty && safeType != 'gold') return 2;
    } catch (_) {}

    try {
      if (_truthy(account['tracks_weight'])) return 0;
    } catch (_) {}

    try {
      final num = (account['account_number'] ?? '').toString().trim();
      if (num.startsWith('7')) return 0;
    } catch (_) {}

    return 2; // cash-only
  }

  ({DateTime startInclusive, DateTime endExclusive}) _rangeBounds(
    DateTimeRange range,
  ) {
    // Normalize to full-day bounds so statements with timestamps behave
    // consistently across summary cards and table filtering.
    final start = DateTime(
      range.start.year,
      range.start.month,
      range.start.day,
    );
    final endExclusive = DateTime(
      range.end.year,
      range.end.month,
      range.end.day,
    ).add(const Duration(days: 1));
    return (startInclusive: start, endExclusive: endExclusive);
  }

  ({double gold, double cash}) _openingBalanceAt(DateTime? start) {
    final statement = _statement;
    if (statement == null || start == null) {
      return (
        gold: statement?.openingBalanceGold ?? 0.0,
        cash: statement?.openingBalanceCash ?? 0.0,
      );
    }

    double gold = statement.openingBalanceGold;
    double cash = statement.openingBalanceCash;

    for (final line in statement.lines) {
      if (line.date.isBefore(start)) {
        gold += line.goldDebit - line.goldCredit;
        cash += line.cashDebit - line.cashCredit;
      }
    }

    return (gold: gold, cash: cash);
  }

  ({
    double openingGold,
    double openingCash,
    double movementGold,
    double movementCash,
    double closingGold,
    double closingCash,
  })
  _periodSummary() {
    final statement = _statement;
    if (statement == null || _dateRange == null) {
      final movementGold = statement == null
          ? 0.0
          : (statement.totalDebitGold - statement.totalCreditGold);
      final movementCash = statement == null
          ? 0.0
          : (statement.totalDebitCash - statement.totalCreditCash);
      return (
        openingGold: statement?.openingBalanceGold ?? 0.0,
        openingCash: statement?.openingBalanceCash ?? 0.0,
        movementGold: movementGold,
        movementCash: movementCash,
        closingGold: statement?.effectiveClosingGold ?? 0.0,
        closingCash: statement?.effectiveClosingCash ?? 0.0,
      );
    }

    final range = _dateRange!;
    final bounds = _rangeBounds(range);
    final opening = _openingBalanceAt(bounds.startInclusive);

    double movementGold = 0.0;
    double movementCash = 0.0;

    for (final line in statement.lines) {
      final dt = line.date;
      final inRange =
          !dt.isBefore(bounds.startInclusive) &&
          dt.isBefore(bounds.endExclusive);
      if (!inRange) continue;
      movementGold += line.goldDebit - line.goldCredit;
      movementCash += line.cashDebit - line.cashCredit;
    }

    return (
      openingGold: opening.gold,
      openingCash: opening.cash,
      movementGold: movementGold,
      movementCash: movementCash,
      closingGold: opening.gold + movementGold,
      closingCash: opening.cash + movementCash,
    );
  }

  ({double goldDebit, double goldCredit, double cashDebit, double cashCredit})
  _periodDebitCreditTotals() {
    final statement = _statement;
    if (statement == null || _dateRange == null) {
      return (
        goldDebit: statement?.totalDebitGold ?? 0.0,
        goldCredit: statement?.totalCreditGold ?? 0.0,
        cashDebit: statement?.totalDebitCash ?? 0.0,
        cashCredit: statement?.totalCreditCash ?? 0.0,
      );
    }

    final range = _dateRange!;
    final bounds = _rangeBounds(range);
    double goldDebit = 0.0;
    double goldCredit = 0.0;
    double cashDebit = 0.0;
    double cashCredit = 0.0;

    for (final line in statement.lines) {
      final dt = line.date;
      final inRange =
          !dt.isBefore(bounds.startInclusive) &&
          dt.isBefore(bounds.endExclusive);
      if (!inRange) continue;
      goldDebit += line.goldDebit;
      goldCredit += line.goldCredit;
      cashDebit += line.cashDebit;
      cashCredit += line.cashCredit;
    }

    return (
      goldDebit: goldDebit,
      goldCredit: goldCredit,
      cashDebit: cashDebit,
      cashCredit: cashCredit,
    );
  }

  void _clearFilters() {
    setState(() {
      _dateRange = null;
      _filterType = 'all';
      _showOnlyMovement = false;
    });
    _searchController.clear();
    _filterLines();
  }

  @override
  void initState() {
    super.initState();
    // _fetchAccountStatement(); // We will call this from didChangeDependencies
    _searchController.addListener(_filterLines);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _fetchAccountStatement();
  }

  @override
  void dispose() {
    // Dispose controllers to avoid leaks
    _searchController.dispose();
    _horizontalController.dispose();
    _verticalController.dispose();
    super.dispose();
  }

  Future<void> _fetchAccountStatement() async {
    setState(() => _isLoading = true);
    try {
      Map<String, dynamic> data;

      // Call appropriate API based on entity type
      if (widget.entityType == 'customer') {
        data = await ApiService().getCustomerStatement(widget.accountId);
      } else if (widget.entityType == 'supplier') {
        data = await ApiService().getSupplierStatement(widget.accountId);
      } else {
        // Auto-default merged view for memo/dual accounts once per screen.
        if (!_resolvedMergedDefault) {
          _resolvedMergedDefault = true;
          try {
            final account = await ApiService().getAccountById(widget.accountId);
            final wantsMerged = _shouldDefaultToMergedView(account);
            if (wantsMerged && mounted) {
              setState(() => _useMergedView = true);
            }

            if (!_resolvedViewModeDefault && mounted) {
              _resolvedViewModeDefault = true;
              final wantsViewMode = _defaultViewModeForAccount(account);
              setState(() => _viewMode = wantsViewMode);
            }
          } catch (_) {
            // If account metadata fetch fails, keep current toggle.
          }
        }

        // Use merged view if enabled, otherwise regular statement
        if (_useMergedView) {
          data = await ApiService().getAccountStatementMerged(widget.accountId);
        } else {
          data = await ApiService().getAccountStatement(widget.accountId);
        }
      }

      if (!mounted) return;
      setState(() {
        _statement = AccountStatement.fromJson(data);
        _filterLines(); // This will also handle the initial list
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('تعذر تحميل كشف الحساب: $e')));
    }
  }

  String _statementTitle() {
    switch (widget.entityType) {
      case 'supplier':
        return 'كشف حساب المورد: ${widget.accountName}';
      case 'customer':
        return 'كشف حساب العميل: ${widget.accountName}';
      default:
        return 'كشف حساب ${widget.accountName}';
    }
  }

  Future<void> _confirmAndRepairSupplierBalances() async {
    if (widget.entityType != 'supplier') return;
    if (_isRepairingBalances) return;

    var ensureAccounts = true;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setStateDialog) {
            return AlertDialog(
              title: const Text('إصلاح الأرصدة التاريخية'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'سيقوم هذا الإجراء بإعادة احتساب الأرصدة المخزنة للمورد من دفتر الأستاذ وقد يساعد في تصحيح البيانات القديمة.',
                  ),
                  const SizedBox(height: 12),
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: ensureAccounts,
                    onChanged: (value) {
                      setStateDialog(() {
                        ensureAccounts = value ?? true;
                      });
                    },
                    title: const Text(
                      'تأكد من إنشاء حسابات المورد (مالي + مذكرة)',
                    ),
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(context).pop(false),
                  child: const Text('إلغاء'),
                ),
                ElevatedButton.icon(
                  onPressed: () => Navigator.of(context).pop(true),
                  icon: const Icon(Icons.build_circle_outlined),
                  label: const Text('تنفيذ'),
                ),
              ],
            );
          },
        );
      },
    );

    if (confirmed != true || !mounted) return;

    setState(() {
      _isRepairingBalances = true;
    });

    final rootNavigator = Navigator.of(context, rootNavigator: true);
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      useRootNavigator: true,
      builder: (context) {
        return const AlertDialog(
          content: Row(
            children: [
              SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              ),
              SizedBox(width: 16),
              Expanded(child: Text('جارٍ إصلاح الأرصدة...')),
            ],
          ),
        );
      },
    );

    try {
      final result = await ApiService().repairSupplierHistoricalBalances(
        widget.accountId,
        ensureAccounts: ensureAccounts,
      );

      if (!mounted) return;
      if (rootNavigator.canPop()) {
        rootNavigator.pop();
      }

      final message = (result['message'] is String)
          ? result['message'] as String
          : 'تم إصلاح الأرصدة بنجاح';

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message), backgroundColor: Colors.green),
      );

      await _fetchAccountStatement();
    } catch (e) {
      if (!mounted) return;
      if (rootNavigator.canPop()) {
        rootNavigator.pop();
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('فشل إصلاح الأرصدة: $e'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isRepairingBalances = false;
        });
      }
    }
  }

  void _filterLines() {
    if (_statement == null) return;

    setState(() {
      final mainKarat = (_statement?.mainKarat ?? 21).toDouble();
      final query = _searchController.text.trim().toLowerCase();
      final bounds = _dateRange == null ? null : _rangeBounds(_dateRange!);

      var filtered = _statement!.lines.where((line) {
        final date = line.date;
        final description = line.description.toLowerCase();

        final matchesDateRange = bounds == null
            ? true
            : (!date.isBefore(bounds.startInclusive) &&
                  date.isBefore(bounds.endExclusive));
        final matchesSearch = query.isEmpty
            ? true
            : description.contains(query) ||
                  _matchesSearch(
                    line: line,
                    query: query,
                    mainKarat: mainKarat,
                  );

        bool matchesFilterType = true;
        if (_filterType == 'credit') {
          matchesFilterType = line.goldCredit > 0 || line.cashCredit > 0;
        } else if (_filterType == 'debit') {
          matchesFilterType = line.goldDebit > 0 || line.cashDebit > 0;
        }

        final hasGoldMovement =
            (line.goldDebit + line.goldCredit).abs() > 0.0001;
        final hasCashMovement =
            (line.cashDebit + line.cashCredit).abs() > 0.0001;
        final hasMovement = hasGoldMovement || hasCashMovement;

        // In single-mode views, hide lines that have no movement
        // in the selected dimension to avoid confusion.
        var matchesViewMode = true;
        if (_viewMode == 2) {
          matchesViewMode = hasCashMovement || !hasMovement;
        } else if (_viewMode == 1) {
          matchesViewMode = hasGoldMovement || !hasMovement;
        }

        final matchesMovement =
            (!_showOnlyMovement || hasMovement) && matchesViewMode;

        return matchesDateRange &&
            matchesSearch &&
            matchesFilterType &&
            matchesMovement;
      }).toList();

      // Recalculate running balances for the filtered list
      final openingAtStart = _openingBalanceAt(bounds?.startInclusive);
      double runningGold = openingAtStart.gold;
      double runningCash = openingAtStart.cash;
      _filteredLines = [];
      for (var line in filtered) {
        runningGold += line.goldDebit - line.goldCredit;
        runningCash += line.cashDebit - line.cashCredit;
        _filteredLines.add(
          line.copyWith(
            runningGoldBalance: runningGold,
            runningCashBalance: runningCash,
          ),
        );
      }
    });
  }

  bool _matchesSearch({
    required StatementLine line,
    required String query,
    required double mainKarat,
  }) {
    final normalizedQuery = query.replaceAll(',', '.');

    final ref = (line.referenceNumber ?? '').toLowerCase();
    if (ref.isNotEmpty && ref.contains(query)) return true;

    final entryNum = (line.entryNumber ?? '').toLowerCase();
    if (entryNum.isNotEmpty && entryNum.contains(query)) return true;

    if (line.journalEntryId != null &&
        line.journalEntryId.toString().contains(normalizedQuery)) {
      return true;
    }

    final invoiceId = _tryExtractInvoiceId(line);
    if (invoiceId != null && invoiceId.toString().contains(normalizedQuery)) {
      return true;
    }

    final debitMain =
        _convertToMainKarat(line.debit18k, 18, mainKarat) +
        _convertToMainKarat(line.debit21k, 21, mainKarat) +
        _convertToMainKarat(line.debit22k, 22, mainKarat) +
        _convertToMainKarat(line.debit24k, 24, mainKarat);
    final creditMain =
        _convertToMainKarat(line.credit18k, 18, mainKarat) +
        _convertToMainKarat(line.credit21k, 21, mainKarat) +
        _convertToMainKarat(line.credit22k, 22, mainKarat) +
        _convertToMainKarat(line.credit24k, 24, mainKarat);

    final netGold = debitMain - creditMain;
    final netCash = line.cashDebit - line.cashCredit;

    final candidates = <String>{
      debitMain.toStringAsFixed(3),
      creditMain.toStringAsFixed(3),
      netGold.toStringAsFixed(3),
      (line.runningGoldBalance ?? 0).toStringAsFixed(3),
      line.cashDebit.toStringAsFixed(2),
      line.cashCredit.toStringAsFixed(2),
      netCash.toStringAsFixed(2),
      (line.runningCashBalance ?? 0).toStringAsFixed(2),
      DateFormat('yyyy-MM-dd').format(line.date).toLowerCase(),
    };

    for (final c in candidates) {
      if (c.toLowerCase().contains(normalizedQuery)) return true;
    }

    return false;
  }

  Future<void> _pickDateRange() async {
    final initialDateRange =
        _dateRange ??
        DateTimeRange(
          start: DateTime.now().subtract(const Duration(days: 30)),
          end: DateTime.now(),
        );

    final picked = await showDateRangePicker(
      context: context,
      initialDateRange: initialDateRange,
      firstDate: DateTime.now().subtract(const Duration(days: 365 * 5)),
      lastDate: DateTime.now().add(const Duration(days: 365)),
      saveText: 'تطبيق',
      builder: (context, child) {
        return Directionality(
          textDirection: ui.TextDirection.rtl,
          child: child!,
        );
      },
    );

    if (picked != null) {
      setState(() {
        _dateRange = picked;
      });
      _filterLines();
    }
  }

  void _showExportSheet() {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (_) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: 16.0,
              vertical: 12.0,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.grey.shade300,
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
                const SizedBox(height: 16),
                ListTile(
                  leading: const Icon(Icons.print),
                  title: const Text('طباعة'),
                  subtitle: const Text('فتح نافذة الطباعة مباشرة'),
                  onTap: () => _handleExport(_printPdf),
                ),
                ListTile(
                  leading: const Icon(Icons.picture_as_pdf),
                  title: const Text('تصدير إلى PDF'),
                  subtitle: const Text('تنسيق احترافي للطباعة والمشاركة'),
                  onTap: () => _handleExport(_exportToPdf),
                ),
                ListTile(
                  leading: const Icon(Icons.table_view),
                  title: const Text('تصدير إلى CSV/Excel'),
                  subtitle: const Text('للمحاسبين والتحليل في Excel'),
                  onTap: () => _handleExport(_exportToCsv),
                ),
                ListTile(
                  leading: const Icon(Icons.copy),
                  title: const Text('نسخ ملخص الحساب'),
                  subtitle: const Text('يتم النسخ إلى الحافظة'),
                  onTap: () => _handleExport(() async {
                    await _copySummaryToClipboard();
                    if (mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('تم نسخ الملخص')),
                      );
                    }
                  }),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Future<void> _handleExport(Future<void> Function() action) async {
    Navigator.of(context).pop();
    setState(() => _isExporting = true);
    try {
      await action();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('فشل التصدير: $e')));
    } finally {
      if (mounted) {
        setState(() => _isExporting = false);
      }
    }
  }

  Future<void> _exportToCsv() async {
    if (_statement == null) return;

    final cashLabel = (_statement?.isMerged ?? false) ? 'قيمة' : 'نقد';

    final headers = <String>['التاريخ', 'الوصف'];
    if (_viewMode != 2) {
      headers.addAll(['ذهب مدين', 'ذهب دائن', 'رصيد الذهب']);
    }
    if (_viewMode != 1) {
      headers.addAll([
        '$cashLabel مدين',
        '$cashLabel دائن',
        'رصيد $cashLabel',
      ]);
    }

    final rows = <List<String>>[headers];
    for (final line in _filteredLines) {
      final row = <String>[
        DateFormat('yyyy-MM-dd').format(line.date),
        line.description,
      ];

      if (_viewMode != 2) {
        row
          ..add(line.goldDebit.toStringAsFixed(3))
          ..add(line.goldCredit.toStringAsFixed(3))
          ..add((line.runningGoldBalance ?? 0).toStringAsFixed(3));
      }

      if (_viewMode != 1) {
        row
          ..add(line.cashDebit.toStringAsFixed(2))
          ..add(line.cashCredit.toStringAsFixed(2))
          ..add((line.runningCashBalance ?? 0).toStringAsFixed(2));
      }

      rows.add(row);
    }

    final csvData = const ListToCsvConverter().convert(rows);
    final directory = await getTemporaryDirectory();
    final file = File(
      '${directory.path}/account_statement_${widget.accountId}_${DateFormat('yyyyMMdd_HHmm').format(DateTime.now())}.csv',
    );
    await file.writeAsString(csvData, encoding: utf8);
    await OpenFile.open(file.path);
  }

  Future<void> _exportToPdf() async {
    if (_statement == null) return;

    final options = await _askPdfOptions();
    if (options == null) return;

    final branding = await _resolvePdfBranding(fetchIfEmpty: true);

    if (mounted) {
      showDialog(
        context: context,
        barrierDismissible: false,
        useRootNavigator: true,
        builder: (_) => const AlertDialog(
          content: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(),
              SizedBox(width: 16),
              Text('جارٍ تجهيز الملف...'),
            ],
          ),
        ),
      );
    }
    try {
      final bytes = await _buildStatementPdfBytes(
        options.landscape ? pdf.PdfPageFormat.a4.landscape : pdf.PdfPageFormat.a4,
        viewModeOverride: options.viewModeOverride,
        includeValuation: options.includeValuation,
        branding: branding,
      );
      await Printing.sharePdf(
        bytes: bytes,
        filename:
            'account_statement_${widget.accountId}_${DateFormat('yyyyMMdd_HHmm').format(DateTime.now())}.pdf',
      );
    } finally {
      if (mounted) Navigator.of(context, rootNavigator: true).pop();
    }
  }

  Future<void> _printPdf() async {
    if (_statement == null) return;

    final options = await _askPdfOptions();
    if (options == null) return;

    // IMPORTANT (Web): keep onLayout free of network/context/provider work.
    // Resolve branding once (best-effort, cached only).
    final branding = await _resolvePdfBranding(fetchIfEmpty: false);

    if (mounted) {
      showDialog(
        context: context,
        barrierDismissible: false,
        useRootNavigator: true,
        builder: (_) => const AlertDialog(
          content: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(),
              SizedBox(width: 16),
              Text('جارٍ تجهيز الكشف للطباعة...'),
            ],
          ),
        ),
      );
    }
    final filename =
        'account_statement_${widget.accountId}_${DateFormat('yyyyMMdd_HHmm').format(DateTime.now())}.pdf';
    try {
      await Printing.layoutPdf(
        name: filename,
        onLayout: (format) async {
          final effectiveFormat = options.landscape ? format.landscape : format;
          return _buildStatementPdfBytes(
            effectiveFormat,
            viewModeOverride: options.viewModeOverride,
            includeValuation: options.includeValuation,
            branding: branding,
          );
        },
      );
    } finally {
      if (mounted) Navigator.of(context, rootNavigator: true).pop();
    }
  }

  Future<({bool includeValuation, int? viewModeOverride, bool landscape})?>
  _askPdfOptions()
  async {
    final currentViewMode = _viewMode;
    var includeValuation = _pdfIncludeValuation;
    var viewModeOverride = _pdfViewModeOverride;
    var landscape = _pdfLandscape;

    final cashLabel = (_statement?.isMerged ?? false) ? 'قيمة' : 'نقد';

    final result = await showDialog<({
      bool includeValuation,
      int? viewModeOverride,
      bool landscape,
    })>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setStateDialog) {
            final effectiveViewMode = viewModeOverride ?? currentViewMode;
            return AlertDialog(
              title: const Text('خيارات الطباعة'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: includeValuation,
                    onChanged: (value) {
                      setStateDialog(() {
                        includeValuation = value ?? true;
                      });
                    },
                    title: const Text('إظهار التقييم المالي للذهب (السعر اللحظي)'),
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    value: landscape,
                    onChanged: (value) {
                      setStateDialog(() {
                        landscape = value;
                      });
                    },
                    title: const Text('طباعة بالعرض (Landscape)'),
                  ),
                  const SizedBox(height: 8),
                  const Text('نمط الطباعة:'),
                  const SizedBox(height: 6),
                  DropdownButton<int>(
                    value: effectiveViewMode,
                    isDense: true,
                    items: [
                      DropdownMenuItem(
                        value: 0,
                        child: Text('ذهب + $cashLabel'),
                      ),
                      const DropdownMenuItem(
                        value: 1,
                        child: Text('ذهب فقط'),
                      ),
                      DropdownMenuItem(
                        value: 2,
                        child: Text('$cashLabel فقط'),
                      ),
                    ],
                    onChanged: (value) {
                      if (value == null) return;
                      setStateDialog(() {
                        viewModeOverride =
                            (value == currentViewMode) ? null : value;
                      });
                    },
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(context).pop(null),
                  child: const Text('إلغاء'),
                ),
                ElevatedButton(
                  onPressed: () {
                    Navigator.of(context).pop((
                      includeValuation: includeValuation,
                      viewModeOverride: viewModeOverride,
                      landscape: landscape,
                    ));
                  },
                  child: const Text('متابعة'),
                ),
              ],
            );
          },
        );
      },
    );

    if (!mounted) return null;
    if (result == null) return null;

    setState(() {
      _pdfIncludeValuation = result.includeValuation;
      _pdfViewModeOverride = result.viewModeOverride;
      _pdfLandscape = result.landscape;
    });

    return result;
  }

  Future<Uint8List> _buildStatementPdfBytes(
    pdf.PdfPageFormat pageFormat, {
    int? viewModeOverride,
    bool includeValuation = true,
    required AccountStatementPdfBranding branding,
  }) async {
    if (_statement == null) return Uint8List(0);

    final statement = _statement!;
    final effectiveViewMode = viewModeOverride ?? _viewMode;

    // Pre-load assets on the main isolate; rootBundle is not available in
    // spawned isolates, so we pass the raw bytes to the builder instead.
    final fontBytes =
        (await rootBundle.load('assets/fonts/Cairo-Regular.ttf'))
            .buffer
            .asUint8List();
    final boldFontBytes =
        (await rootBundle.load('assets/fonts/Cairo-Bold.ttf'))
            .buffer
            .asUint8List();
    Uint8List? fallbackLogoBytes;
    try {
      final raw = (await rootBundle.load('assets/KHGL.png')).buffer.asUint8List();
      fallbackLogoBytes = await _resizeImageBytes(raw, 128);
    } catch (_) {}

    // Pre-decode and resize the base64 company logo (main isolate only).
    Uint8List? preloadedLogo;
    if (branding.showCompanyLogo && branding.companyLogoBase64.trim().isNotEmpty) {
      try {
        final b64 = branding.companyLogoBase64.trim();
        final commaIdx = b64.indexOf(',');
        final payload = (b64.startsWith('data:') && commaIdx >= 0)
            ? b64.substring(commaIdx + 1)
            : b64;
        final decoded = base64Decode(payload);
        preloadedLogo = await _resizeImageBytes(decoded, 128);
      } catch (_) {}
    }

    // Capture primitives so the closure only sends isolate-safe values.
    final fmtW = pageFormat.width;
    final fmtH = pageFormat.height;
    final fmtML = pageFormat.marginLeft;
    final fmtMR = pageFormat.marginRight;
    final fmtMT = pageFormat.marginTop;
    final fmtMB = pageFormat.marginBottom;

    final lines = List<StatementLine>.of(_filteredLines);
    final accountName = widget.accountName;
    final accountId = widget.accountId;
    final rangeStart = _dateRange?.start;
    final rangeEnd = _dateRange?.end;
    final filterType = _filterType;
    final showOnlyMovement = _showOnlyMovement;

    final fmt = pdf.PdfPageFormat(
      fmtW,
      fmtH,
      marginLeft: fmtML,
      marginRight: fmtMR,
      marginTop: fmtMT,
      marginBottom: fmtMB,
    );
    final dateRange = rangeStart != null
        ? DateTimeRange(start: rangeStart, end: rangeEnd!)
        : null;

    Future<Uint8List> buildPdf() => AccountStatementPdfBuilder.build(
          fmt,
          statement: statement,
          tableLines: lines,
          accountName: accountName,
          accountId: accountId,
          viewMode: effectiveViewMode,
          includeValuation: includeValuation,
          dateRange: dateRange,
          filterType: filterType,
          showOnlyMovement: showOnlyMovement,
          branding: branding,
          preloadedRegularFont: fontBytes,
          preloadedBoldFont: boldFontBytes,
          preloadedFallbackLogo: fallbackLogoBytes,
          preloadedLogo: preloadedLogo,
        );

    // dart:isolate is not supported on Flutter Web — run directly there.
    if (kIsWeb) return buildPdf();

    // On native: offload to a background isolate so the spinner animates freely.
    return Isolate.run(buildPdf);
  }

  Future<void> _copySummaryToClipboard() async {
    if (_statement == null) return;

    final statement = _statement!;
    final period = _periodSummary();
    final totals = _periodDebitCreditTotals();
    final summary = StringBuffer()
      ..writeln('كشف حساب: ${widget.accountName}')
      ..writeln('عيار أساسي: ${statement.mainKarat}')
      ..writeln('رصيد افتتاحي ذهب: ${period.openingGold.toStringAsFixed(3)}')
      ..writeln('رصيد افتتاحي نقد: ${period.openingCash.toStringAsFixed(2)}')
      ..writeln('إجمالي ذهب مدين: ${totals.goldDebit.toStringAsFixed(3)}')
      ..writeln('إجمالي ذهب دائن: ${totals.goldCredit.toStringAsFixed(3)}')
      ..writeln('إجمالي نقد مدين: ${totals.cashDebit.toStringAsFixed(2)}')
      ..writeln('إجمالي نقد دائن: ${totals.cashCredit.toStringAsFixed(2)}')
      ..writeln(
        'رصيد ختامي ذهب (حسب الكشف): ${(_dateRange == null ? statement.closingBalanceGoldNormalized : period.closingGold).toStringAsFixed(3)}',
      )
      ..writeln(
        'رصيد ختامي نقد (حسب الكشف): ${(_dateRange == null ? statement.closingBalanceCash : period.closingCash).toStringAsFixed(2)}',
      );

    if (statement.hasEntityBalances) {
      summary
        ..writeln(
          'الرصيد الحالي ذهب (من الملف): ${statement.effectiveClosingGold.toStringAsFixed(3)}',
        )
        ..writeln(
          'الرصيد الحالي نقد (من الملف): ${statement.effectiveClosingCash.toStringAsFixed(2)}',
        );
    }

    await Clipboard.setData(ClipboardData(text: summary.toString()));
  }

  // Removed unused _exportToCsv

  // Removed unused _exportToPdf

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_statementTitle()),
        actions: [
          if (widget.entityType == 'supplier')
            IconButton(
              icon: const Icon(Icons.build_circle_outlined),
              tooltip: 'إصلاح الأرصدة',
              onPressed: (_isLoading || _isRepairingBalances)
                  ? null
                  : _confirmAndRepairSupplierBalances,
            ),
        ],
      ),
      body: SafeArea(
        child: _isLoading
            ? const Center(child: CircularProgressIndicator())
            : _statement == null
            ? _buildEmptyState()
            : _buildStatementContent(),
      ),
    );
  }

  Widget _buildStatementContent() {
    return RefreshIndicator(
      onRefresh: _fetchAccountStatement,
      child: LayoutBuilder(
        builder: (context, constraints) {
          return ListView(
            padding: const EdgeInsets.all(16),
            physics: const AlwaysScrollableScrollPhysics(),
            children: [
              _buildSummaryOverview(constraints.maxWidth),
              const SizedBox(height: 16),
              _buildToolbar(constraints.maxWidth),
              const SizedBox(height: 12),
              _buildFilteredTotalsBar(),
              const SizedBox(height: 16),
              _buildStatementTable(),
            ],
          );
        },
      ),
    );
  }

  Widget _buildFilteredTotalsBar() {
    if (_statement == null) return const SizedBox.shrink();

    final mainKarat = (_statement?.mainKarat ?? 21).toDouble();

    double goldDebit = 0;
    double goldCredit = 0;
    double cashDebit = 0;
    double cashCredit = 0;

    for (final line in _filteredLines) {
      final debitMain =
          _convertToMainKarat(line.debit18k, 18, mainKarat) +
          _convertToMainKarat(line.debit21k, 21, mainKarat) +
          _convertToMainKarat(line.debit22k, 22, mainKarat) +
          _convertToMainKarat(line.debit24k, 24, mainKarat);
      final creditMain =
          _convertToMainKarat(line.credit18k, 18, mainKarat) +
          _convertToMainKarat(line.credit21k, 21, mainKarat) +
          _convertToMainKarat(line.credit22k, 22, mainKarat) +
          _convertToMainKarat(line.credit24k, 24, mainKarat);

      goldDebit += debitMain;
      goldCredit += creditMain;
      cashDebit += line.cashDebit;
      cashCredit += line.cashCredit;
    }

    final theme = Theme.of(context);
    final chips = <Widget>[
      Chip(
        label: Text('النتائج: ${_filteredLines.length}'),
        backgroundColor: theme.colorScheme.surfaceContainerHighest,
      ),
    ];

    if (_viewMode != 2) {
      chips.addAll([
        Chip(
          label: Text('ذهب مدين: ${goldDebit.toStringAsFixed(3)}'),
          backgroundColor: theme.colorScheme.surfaceContainerHighest,
        ),
        Chip(
          label: Text('ذهب دائن: ${goldCredit.toStringAsFixed(3)}'),
          backgroundColor: theme.colorScheme.surfaceContainerHighest,
        ),
        Chip(
          label: Text(
            'صافي ذهب: ${(goldDebit - goldCredit).toStringAsFixed(3)}',
          ),
          backgroundColor: theme.colorScheme.surfaceContainerHighest,
        ),
      ]);
    }

    if (_viewMode != 1) {
      chips.addAll([
        Chip(
          label: Text('نقد مدين: ${cashDebit.toStringAsFixed(2)}'),
          backgroundColor: theme.colorScheme.surfaceContainerHighest,
        ),
        Chip(
          label: Text('نقد دائن: ${cashCredit.toStringAsFixed(2)}'),
          backgroundColor: theme.colorScheme.surfaceContainerHighest,
        ),
        Chip(
          label: Text(
            'صافي نقد: ${(cashDebit - cashCredit).toStringAsFixed(2)}',
          ),
          backgroundColor: theme.colorScheme.surfaceContainerHighest,
        ),
      ]);
    }

    return Card(
      elevation: 0,
      color: theme.colorScheme.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(12.0),
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: chips,
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.inbox_outlined, size: 56, color: Colors.grey),
          const SizedBox(height: 12),
          const Text('لا توجد سجلات لهذا الحساب'),
          const SizedBox(height: 12),
          ElevatedButton.icon(
            onPressed: _fetchAccountStatement,
            icon: const Icon(Icons.refresh),
            label: const Text('تحديث'),
          ),
        ],
      ),
    );
  }

  Widget _buildSummaryOverview(double maxWidth) {
    final theme = Theme.of(context);
    final statement = _statement!;

    final period = _periodSummary();

    final closingTitle = statement.hasEntityBalances
        ? 'الرصيد الحالي (من الملف)'
        : 'رصيد ختامي (موزون)';

    final openingTitle = _dateRange == null
        ? 'رصيد افتتاحي (عيار ${statement.mainKarat})'
        : 'رصيد افتتاحي للفترة (عيار ${statement.mainKarat})';

    final movementTitle = _dateRange == null ? 'إجمالي الحركة' : 'حركة الفترة';

    final cards = <Widget>[
      _SummaryCard(
        title: openingTitle,
        goldValue: period.openingGold,
        cashValue: period.openingCash,
        color: theme.colorScheme.primary,
        icon: Icons.lock_clock,
        mainKarat: statement.mainKarat,
      ),
      _SummaryCard(
        title: movementTitle,
        goldValue: period.movementGold,
        cashValue: period.movementCash,
        color: theme.colorScheme.secondary,
        icon: Icons.sync_alt,
        mainKarat: statement.mainKarat,
      ),
      _SummaryCard(
        title: closingTitle,
        goldValue: _dateRange == null
            ? statement.effectiveClosingGold
            : period.closingGold,
        cashValue: _dateRange == null
            ? statement.effectiveClosingCash
            : period.closingCash,
        color: theme.colorScheme.tertiary,
        icon: Icons.summarize,
        mainKarat: statement.mainKarat,
      ),
    ];

    final hasLivePrice =
        (statement.goldPricePerGramMainKarat ?? 0) > 0 ||
        (statement.valuationTotalValueEstimate ?? 0) != 0;

    if (hasLivePrice) {
      cards.add(
        _ValuationCard(
          mainKarat: statement.mainKarat,
          pricePerGramMainKarat: statement.goldPricePerGramMainKarat,
          priceSource: statement.goldPriceSource,
          priceUpdatedAt: statement.goldPriceUpdatedAt,
          totalValueEstimate: statement.valuationTotalValueEstimate,
          goldValueEstimate: statement.valuationGoldValueEstimate,
        ),
      );
    }

    final isCompact = maxWidth < 720;
    final cardsPerRow = isCompact ? 1 : (cards.length == 4 ? 2 : 3);
    final cardWidth =
        isCompact ? maxWidth : (maxWidth - (12 * (cardsPerRow - 1))) / cardsPerRow;

    return Wrap(
      spacing: 12,
      runSpacing: 12,
      children: cards
          .map(
            (card) => SizedBox(
              width: cardWidth.clamp(260, 420).toDouble(),
              child: card,
            ),
          )
          .toList(),
    );
  }

  Widget _buildToolbar(double maxWidth) {
    final isNarrow = maxWidth < 500;

    // View-mode labels
    const viewModeLabels = {0: 'مزدوج', 1: 'ذهب فقط', 2: 'نقدي فقط'};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            ElevatedButton.icon(
              onPressed: _pickDateRange,
              icon: const Icon(Icons.date_range, size: 18),
              label: Text(
                _dateRange == null
                    ? 'نطاق التاريخ'
                    : '${DateFormat('dd/MM/yyyy').format(_dateRange!.start)} - ${DateFormat('dd/MM/yyyy').format(_dateRange!.end)}',
                overflow: TextOverflow.ellipsis,
              ),
            ),
            // Use a compact dropdown on narrow screens instead of SegmentedButton
            if (isNarrow)
              DropdownButton<int>(
                value: _viewMode,
                isDense: true,
                items: viewModeLabels.entries
                    .map(
                      (e) =>
                          DropdownMenuItem(value: e.key, child: Text(e.value)),
                    )
                    .toList(),
                onChanged: (value) {
                  if (value == null) return;
                  setState(() => _viewMode = value);
                  _filterLines();
                },
              )
            else
              ConstrainedBox(
                constraints: BoxConstraints(maxWidth: maxWidth),
                child: SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 0, label: Text('مزدوج')),
                    ButtonSegment(value: 1, label: Text('ذهب فقط')),
                    ButtonSegment(value: 2, label: Text('نقدي فقط')),
                  ],
                  selected: {_viewMode},
                  onSelectionChanged: (value) {
                    setState(() => _viewMode = value.first);
                    _filterLines();
                  },
                ),
              ),
            if (widget.entityType == 'account')
              FilterChip(
                label: const Text('دمج الحسابين'),
                avatar: Icon(
                  _useMergedView ? Icons.merge : Icons.call_split,
                  size: 18,
                ),
                selected: _useMergedView,
                onSelected: (value) {
                  setState(() {
                    _useMergedView = value;
                  });
                  _fetchAccountStatement();
                },
              ),
            FilterChip(
              label: const Text('حركات فقط'),
              selected: _showOnlyMovement,
              onSelected: (value) {
                setState(() {
                  _showOnlyMovement = value;
                  _filterLines();
                });
              },
            ),
            FilterChip(
              label: const Text('تفصيل العيارات'),
              selected: _includeBreakdown,
              onSelected: (value) {
                setState(() => _includeBreakdown = value);
              },
            ),
            OutlinedButton.icon(
              onPressed:
                  (_dateRange != null ||
                      _searchController.text.isNotEmpty ||
                      _filterType != 'all' ||
                      _showOnlyMovement)
                  ? _clearFilters
                  : null,
              icon: const Icon(Icons.filter_alt_off, size: 18),
              label: const Text('مسح الفلاتر'),
            ),
            _buildExportMenu(),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _searchController,
                decoration: InputDecoration(
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _searchController.text.isEmpty
                      ? null
                      : IconButton(
                          icon: const Icon(Icons.clear),
                          onPressed: () {
                            _searchController.clear();
                            _filterLines();
                          },
                        ),
                  hintText: isNarrow
                      ? 'بحث...'
                      : 'ابحث بالبيان / رقم المرجع / المبلغ',
                  border: const OutlineInputBorder(),
                  isDense: isNarrow,
                ),
              ),
            ),
            const SizedBox(width: 8),
            DropdownButton<String>(
              value: _filterType,
              isDense: true,
              items: const [
                DropdownMenuItem(value: 'all', child: Text('الكل')),
                DropdownMenuItem(value: 'debit', child: Text('مدين')),
                DropdownMenuItem(value: 'credit', child: Text('دائن')),
              ],
              onChanged: (value) {
                if (value == null) return;
                setState(() {
                  _filterType = value;
                  _filterLines();
                });
              },
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildExportMenu() {
    return ElevatedButton.icon(
      onPressed: _isExporting ? null : _showExportSheet,
      icon: _isExporting
          ? const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.file_download),
      label: const Text('تصدير'),
    );
  }

  Widget _buildStatementTable() {
    final theme = Theme.of(context);
    final mainKarat = (_statement?.mainKarat ?? 21).toDouble();
    final cashLabel = (_statement?.isMerged ?? false) ? 'القيمة' : 'النقد';

    final positiveColor = theme.colorScheme.primary;
    final negativeColor = theme.colorScheme.error;
    final balanceColor = theme.colorScheme.onSurfaceVariant;

    Text heading(String text) {
      return Text(text, style: const TextStyle(fontWeight: FontWeight.bold));
    }

    final List<DataColumn> columns = [
      DataColumn(label: heading('التاريخ')),
      DataColumn(label: heading('البيان')),
    ];

    if (_viewMode != 2) {
      columns.addAll([
        DataColumn(label: heading('حركة الذهب (+/-)')),
        DataColumn(label: heading('رصيد الذهب')),
      ]);
    }

    if (_viewMode != 1) {
      columns.addAll([
        DataColumn(label: heading('حركة $cashLabel (+/-)')),
        DataColumn(label: heading('رصيد $cashLabel')),
      ]);
    }

    if (_includeBreakdown && _viewMode != 2) {
      columns.add(
        const DataColumn(
          label: Text(
            'العيارات',
            style: TextStyle(fontWeight: FontWeight.bold),
          ),
        ),
      );
    }

    final rows = List<DataRow>.generate(_filteredLines.length, (index) {
      final line = _filteredLines[index];
      final debitMain =
          _convertToMainKarat(line.debit18k, 18, mainKarat) +
          _convertToMainKarat(line.debit21k, 21, mainKarat) +
          _convertToMainKarat(line.debit22k, 22, mainKarat) +
          _convertToMainKarat(line.debit24k, 24, mainKarat);
      final creditMain =
          _convertToMainKarat(line.credit18k, 18, mainKarat) +
          _convertToMainKarat(line.credit21k, 21, mainKarat) +
          _convertToMainKarat(line.credit22k, 22, mainKarat) +
          _convertToMainKarat(line.credit24k, 24, mainKarat);

      final goldMovement = debitMain - creditMain;
      final cashMovement = line.cashDebit - line.cashCredit;

      final cells = <DataCell>[
        DataCell(Text(DateFormat('yyyy-MM-dd').format(line.date))),
        DataCell(_buildDescriptionCell(line)),
      ];

      if (_viewMode != 2) {
        cells.addAll([
          DataCell(
            _signedNumCell(
              goldMovement,
              positiveColor: positiveColor,
              negativeColor: negativeColor,
              fractionDigits: 3,
            ),
          ),
          DataCell(
            _numCell(
              line.runningGoldBalance,
              color: balanceColor,
              fractionDigits: 3,
            ),
          ),
        ]);
      }

      if (_viewMode != 1) {
        cells.addAll([
          DataCell(
            _signedNumCell(
              cashMovement,
              positiveColor: positiveColor,
              negativeColor: negativeColor,
              fractionDigits: 2,
            ),
          ),
          DataCell(
            _numCell(
              line.runningCashBalance,
              color: balanceColor,
              fractionDigits: 2,
            ),
          ),
        ]);
      }

      if (_includeBreakdown && _viewMode != 2) {
        cells.add(
          DataCell(
            Tooltip(
              message: 'تفاصيل العيارات',
              child: IconButton(
                icon: const Icon(Icons.tune, size: 20),
                onPressed: () => _showLineDetails(line, mainKarat),
              ),
            ),
          ),
        );
      }

      return DataRow(
        color: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return Theme.of(context).colorScheme.primaryContainer;
          }
          return index.isEven
              ? Theme.of(context).colorScheme.surface
              : Theme.of(
                  context,
                ).colorScheme.surfaceContainerHighest.withValues(alpha: 0.35);
        }),
        cells: cells,
        onSelectChanged: (_) => _handleRowTap(line, mainKarat),
      );
    });

    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Scrollbar(
            controller: _horizontalController,
            thumbVisibility: true,
            notificationPredicate: (notification) =>
                notification.metrics.axis == Axis.horizontal,
            child: SingleChildScrollView(
              controller: _horizontalController,
              scrollDirection: Axis.horizontal,
              child: Scrollbar(
                controller: _verticalController,
                thumbVisibility: true,
                child: SingleChildScrollView(
                  controller: _verticalController,
                  child: DataTable(
                    headingRowColor: WidgetStateProperty.all(
                      Theme.of(context).colorScheme.surfaceContainerHighest
                          .withValues(alpha: 0.5),
                    ),
                    headingRowHeight: 48,
                    columnSpacing: 18,
                    dataRowMinHeight: 56,
                    dataRowMaxHeight: 84,
                    columns: columns,
                    rows: rows,
                  ),
                ),
              ),
            ),
          ),
          if (_statement != null) _buildClosingBreakdown(mainKarat),
        ],
      ),
    );
  }

  Widget _buildClosingBreakdown(double mainKarat) {
    final closingDetails = _statement!.effectiveClosingGoldDetails;
    if (closingDetails.isEmpty) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'تفصيل الرصيد الختامي حسب العيارات',
            style: TextStyle(fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: closingDetails.entries
                .map(
                  (entry) => Chip(
                    avatar: const Icon(Icons.scale, size: 16),
                    label: Text(
                      '${entry.key}: ${entry.value.toStringAsFixed(3)} جم ≈ ${_convertToMainKarat(entry.value, int.tryParse(entry.key.replaceAll(RegExp(r'[^0-9]'), '')) ?? 21, mainKarat).toStringAsFixed(3)} (${_statement!.mainKarat}k)',
                    ),
                  ),
                )
                .toList(),
          ),
        ],
      ),
    );
  }

  double _convertToMainKarat(double value, int karat, double mainKarat) {
    if (value == 0) return 0;
    return (value * karat) / mainKarat;
  }

  Widget _numCell(double? value, {Color? color, int fractionDigits = 3}) {
    if (value == null || value.abs() < 0.0001) {
      return const Text('', textAlign: TextAlign.end);
    }

    return Text(
      value.toStringAsFixed(fractionDigits),
      textAlign: TextAlign.end,
      style: TextStyle(
        color: color ?? Theme.of(context).colorScheme.onSurface,
        fontWeight: FontWeight.w500,
        fontFeatures: const [ui.FontFeature.tabularFigures()],
      ),
    );
  }

  Widget _signedNumCell(
    double value, {
    required Color positiveColor,
    required Color negativeColor,
    int fractionDigits = 3,
  }) {
    if (value.abs() < 0.0001) {
      return const Text('', textAlign: TextAlign.end);
    }
    final isPositive = value > 0;
    final sign = isPositive ? '+' : '-';
    final absText = value.abs().toStringAsFixed(fractionDigits);
    return Text(
      '$sign$absText',
      textAlign: TextAlign.end,
      style: TextStyle(
        color: isPositive ? positiveColor : negativeColor,
        fontWeight: FontWeight.w500,
        fontFeatures: const [ui.FontFeature.tabularFigures()],
      ),
    );
  }

  Widget _buildDescriptionCell(StatementLine line) {
    final theme = Theme.of(context);
    final icon = _iconForLine(line);
    final subtitle = _subtitleForLine(line);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Row(
          children: [
            Icon(icon, size: 18, color: theme.colorScheme.onSurfaceVariant),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                line.description,
                style: const TextStyle(fontWeight: FontWeight.w600),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Row(
          children: [
            Icon(
              Icons.tag,
              size: 14,
              color: theme.colorScheme.onSurfaceVariant,
            ),
            const SizedBox(width: 4),
            Text(
              subtitle,
              style: TextStyle(
                fontSize: 11,
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ],
    );
  }

  IconData _iconForLine(StatementLine line) {
    final refType = (line.referenceType ?? '').toLowerCase().trim();
    if (refType == 'invoice') return Icons.receipt_long;
    if (refType == 'voucher') return Icons.payments;
    if (refType == 'journal_entry') return Icons.library_books;
    if (refType == 'manual') return Icons.edit_note;

    final desc = line.description.toLowerCase();
    if (desc.contains('مقايضة')) return Icons.compare_arrows;
    if (desc.contains('سداد') || desc.contains('قبض') || desc.contains('صرف')) {
      return Icons.payments;
    }
    if (desc.contains('فاتورة') || desc.contains('invoice')) {
      return Icons.receipt_long;
    }
    return Icons.notes;
  }

  String _subtitleForLine(StatementLine line) {
    final parts = <String>[];
    if ((line.referenceNumber ?? '').trim().isNotEmpty) {
      parts.add('مرجع: ${line.referenceNumber}');
    } else if ((line.entryNumber ?? '').trim().isNotEmpty) {
      parts.add('قيد: ${line.entryNumber}');
    }
    if (line.journalEntryId != null) {
      parts.add('# ${line.journalEntryId}');
    }
    return parts.join(' • ');
  }

  int? _tryExtractInvoiceId(StatementLine line) {
    // Only treat it as an invoice when the backend explicitly marks it so.
    // Parsing invoice numbers from description is ambiguous (often not the DB ID)
    // and causes 404s when calling /api/invoices/<id>.
    if ((line.referenceType ?? '').toLowerCase().trim() != 'invoice') {
      return null;
    }
    return line.referenceId;
  }

  Future<void> _handleRowTap(StatementLine line, double mainKarat) async {
    final invoiceId = _tryExtractInvoiceId(line);
    if (invoiceId != null) {
      await _showInvoiceQuickView(invoiceId);
      return;
    }
    _showLineDetails(line, mainKarat);
  }

  Future<void> _showInvoiceQuickView(int invoiceId) async {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (_) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: FutureBuilder<Map<String, dynamic>>(
              future: ApiService().getInvoiceById(invoiceId),
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.waiting) {
                  return const SizedBox(
                    height: 240,
                    child: Center(child: CircularProgressIndicator()),
                  );
                }

                if (snapshot.hasError || !snapshot.hasData) {
                  return SizedBox(
                    height: 240,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.error_outline),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                'تعذر تحميل تفاصيل الفاتورة (#$invoiceId)',
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 16,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text(snapshot.error.toString()),
                      ],
                    ),
                  );
                }

                final invoice = snapshot.data!;
                final items = (invoice['items'] as List?) ?? const [];
                final invoiceType = (invoice['invoice_type'] ?? '').toString();
                final customerName = (invoice['customer_name'] ?? '')
                    .toString();
                final supplierName = (invoice['supplier_name'] ?? '')
                    .toString();

                return ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: MediaQuery.of(context).size.height * 0.85,
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.receipt_long),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'عرض سريع للفاتورة #$invoiceId',
                              style: const TextStyle(
                                fontWeight: FontWeight.bold,
                                fontSize: 16,
                              ),
                            ),
                          ),
                          IconButton(
                            icon: const Icon(Icons.close),
                            onPressed: () => Navigator.of(context).pop(),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          if (invoiceType.isNotEmpty)
                            Chip(label: Text('النوع: $invoiceType')),
                          if (customerName.isNotEmpty && customerName != 'N/A')
                            Chip(label: Text('العميل: $customerName')),
                          if (supplierName.isNotEmpty && supplierName != 'N/A')
                            Chip(label: Text('المورد: $supplierName')),
                          Chip(label: Text('الأصناف: ${items.length}')),
                        ],
                      ),
                      const SizedBox(height: 12),
                      const Divider(height: 1),
                      const SizedBox(height: 12),
                      Expanded(
                        child: items.isEmpty
                            ? const Center(child: Text('لا توجد أصناف'))
                            : ListView.separated(
                                itemCount: items.length,
                                separatorBuilder: (context, index) =>
                                    const Divider(height: 1),
                                itemBuilder: (context, index) {
                                  final item = items[index];
                                  if (item is! Map) {
                                    return ListTile(
                                      title: Text(item.toString()),
                                    );
                                  }

                                  final description =
                                      (item['description'] ??
                                              item['item_name'] ??
                                              '')
                                          .toString();
                                  final karat = (item['karat'] ?? '')
                                      .toString();
                                  final weight = item['weight_grams'];
                                  final weightText = (weight is num)
                                      ? weight.toDouble().toStringAsFixed(3)
                                      : (weight?.toString() ?? '');

                                  return ListTile(
                                    dense: true,
                                    title: Text(
                                      description.isEmpty
                                          ? 'صنف #${index + 1}'
                                          : description,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                    subtitle: karat.isEmpty
                                        ? null
                                        : Text('عيار: $karat'),
                                    trailing: weightText.isEmpty
                                        ? null
                                        : Text('$weightText جم'),
                                  );
                                },
                              ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        );
      },
    );
  }

  void _showLineDetails(StatementLine line, double mainKarat) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (_) {
        return Padding(
          padding: const EdgeInsets.all(20.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.receipt_long),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'تفاصيل الحركة - ${DateFormat('dd/MM/yyyy').format(line.date)}',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.copy_all),
                    onPressed: () async {
                      final summary = _buildLineSummary(line, mainKarat);
                      await Clipboard.setData(ClipboardData(text: summary));
                      if (mounted) {
                        Navigator.of(context).pop();
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('تم نسخ التفاصيل')),
                        );
                      }
                    },
                  ),
                ],
              ),
              const SizedBox(height: 16),
              _buildDetailsRow('الوصف', line.description),
              _buildDetailsRow('رقم السطر', line.id.toString()),
              const Divider(height: 24),
              if (_viewMode != 2) ...[
                _buildDetailsRow(
                  'ذهب مدين (عيار ${_statement!.mainKarat})',
                  _convertToMainKarat(
                    line.debit21k +
                        line.debit22k +
                        line.debit24k +
                        line.debit18k,
                    21,
                    mainKarat,
                  ).toStringAsFixed(3),
                ),
                _buildDetailsRow(
                  'ذهب دائن (عيار ${_statement!.mainKarat})',
                  _convertToMainKarat(
                    line.credit21k +
                        line.credit22k +
                        line.credit24k +
                        line.credit18k,
                    21,
                    mainKarat,
                  ).toStringAsFixed(3),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    if (line.debit18k != 0 || line.credit18k != 0)
                      _buildKaratChip('18k', line.debit18k, line.credit18k),
                    if (line.debit21k != 0 || line.credit21k != 0)
                      _buildKaratChip('21k', line.debit21k, line.credit21k),
                    if (line.debit22k != 0 || line.credit22k != 0)
                      _buildKaratChip('22k', line.debit22k, line.credit22k),
                    if (line.debit24k != 0 || line.credit24k != 0)
                      _buildKaratChip('24k', line.debit24k, line.credit24k),
                  ],
                ),
              ],
              if (_viewMode != 1) ...[
                const Divider(height: 32),
                _buildDetailsRow('نقد مدين', line.cashDebit.toStringAsFixed(2)),
                _buildDetailsRow(
                  'نقد دائن',
                  line.cashCredit.toStringAsFixed(2),
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _buildDetailsRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6.0),
      child: Row(
        children: [
          SizedBox(
            width: 140,
            child: Text(
              label,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
          Expanded(child: Text(value, style: const TextStyle(fontSize: 13))),
        ],
      ),
    );
  }

  Widget _buildKaratChip(String label, double debit, double credit) {
    final base = app_theme.AppColors.karatColorFor(label);
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Chip(
      backgroundColor: base.withValues(alpha: isDark ? 0.20 : 0.12),
      shape: StadiumBorder(
        side: BorderSide(color: base.withValues(alpha: isDark ? 0.55 : 0.35)),
      ),
      label: Text(
        '$label • مدين ${debit.toStringAsFixed(3)} / دائن ${credit.toStringAsFixed(3)}',
        style: TextStyle(color: base, fontWeight: FontWeight.w700),
      ),
    );
  }

  String _buildLineSummary(StatementLine line, double mainKarat) {
    final buffer = StringBuffer()
      ..writeln('التاريخ: ${DateFormat('yyyy-MM-dd').format(line.date)}')
      ..writeln('الوصف: ${line.description}')
      ..writeln('رقم السطر: ${line.id}');

    if (_viewMode != 2) {
      buffer
        ..writeln(
          'ذهب مدين (عيار ${_statement!.mainKarat}): ${_convertToMainKarat(line.debit18k + line.debit21k + line.debit22k + line.debit24k, 21, mainKarat).toStringAsFixed(3)}',
        )
        ..writeln(
          'ذهب دائن (عيار ${_statement!.mainKarat}): ${_convertToMainKarat(line.credit18k + line.credit21k + line.credit22k + line.credit24k, 21, mainKarat).toStringAsFixed(3)}',
        );
    }

    if (_viewMode != 1) {
      buffer
        ..writeln('نقد مدين: ${line.cashDebit.toStringAsFixed(2)}')
        ..writeln('نقد دائن: ${line.cashCredit.toStringAsFixed(2)}');
    }

    return buffer.toString();
  }
}

class _SummaryCard extends StatelessWidget {
  final String title;
  final double goldValue;
  final double cashValue;
  final Color color;
  final IconData icon;
  final int mainKarat;

  const _SummaryCard({
    required this.title,
    required this.goldValue,
    required this.cashValue,
    required this.color,
    required this.icon,
    required this.mainKarat,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final textTheme = theme.textTheme;
    final borderColor = theme.colorScheme.outlineVariant;
    final goldColor = app_theme.AppColors.primaryGold;
    final cashColor = app_theme.AppColors.success;

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: borderColor),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(icon, color: color),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    title,
                    style: textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _SummaryMetric(
                    label: 'ذهب (جم)',
                    value: goldValue.toStringAsFixed(3),
                    subtitle: 'مكافئ عيار $mainKarat',
                    color: goldColor,
                    icon: Icons.scale,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _SummaryMetric(
                    label: 'نقد (ر.س)',
                    value: cashValue.toStringAsFixed(2),
                    color: cashColor,
                    icon: Icons.payments,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ValuationCard extends StatelessWidget {
  final int mainKarat;
  final double? pricePerGramMainKarat;
  final String? priceSource;
  final DateTime? priceUpdatedAt;
  final double? totalValueEstimate;
  final double? goldValueEstimate;

  const _ValuationCard({
    required this.mainKarat,
    required this.pricePerGramMainKarat,
    required this.priceSource,
    required this.priceUpdatedAt,
    required this.totalValueEstimate,
    required this.goldValueEstimate,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final textTheme = theme.textTheme;
    final borderColor = theme.colorScheme.outlineVariant;
    final goldColor = app_theme.AppColors.primaryGold;
    final cashColor = app_theme.AppColors.success;

    String updatedLabel() {
      final local = priceUpdatedAt?.toLocal();
      if (local == null) return '';
      try {
        return DateFormat('yyyy-MM-dd HH:mm').format(local);
      } catch (_) {
        return '';
      }
    }

    final priceText = (pricePerGramMainKarat ?? 0) > 0
        ? pricePerGramMainKarat!.toStringAsFixed(2)
        : '—';
    final totalText = totalValueEstimate?.toStringAsFixed(2) ?? '—';
    final goldValueText = goldValueEstimate?.toStringAsFixed(2);

    final source = (priceSource ?? '').trim();
    final updatedAt = updatedLabel();
    final subtitleParts = <String>['عيار $mainKarat'];
    if (source.isNotEmpty) subtitleParts.add(source);
    if (updatedAt.isNotEmpty) subtitleParts.add(updatedAt);

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: borderColor),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primary.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(Icons.price_check, color: theme.colorScheme.primary),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'السعر اللحظي والتقييم',
                        style: textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        subtitleParts.join(' • '),
                        style: textTheme.labelSmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _SummaryMetric(
                    label: 'سعر الجرام (ر.س)',
                    value: priceText,
                    subtitle: 'مكافئ عيار $mainKarat',
                    color: goldColor,
                    icon: Icons.attach_money,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _SummaryMetric(
                    label: 'قيمة تقديرية (ر.س)',
                    value: totalText,
                    subtitle: goldValueText == null ? null : 'ذهب: $goldValueText',
                    color: cashColor,
                    icon: Icons.assessment,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _SummaryMetric extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  final IconData icon;
  final String? subtitle;

  const _SummaryMetric({
    required this.label,
    required this.value,
    required this.color,
    required this.icon,
    this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 12,
                    color: color.withValues(alpha: 0.8),
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 4),
                FittedBox(
                  alignment: AlignmentDirectional.centerStart,
                  fit: BoxFit.scaleDown,
                  child: Text(
                    value,
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      color: color,
                      fontSize: 15,
                      fontFeatures: const [ui.FontFeature.tabularFigures()],
                    ),
                  ),
                ),
                if (subtitle != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    subtitle!,
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
