import 'package:flutter/material.dart';
import 'dart:convert';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:pdf/pdf.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../api_service.dart';
import '../providers/auth_provider.dart';
import '../services/data_sync_bus.dart';
import '../utils/invoice_direct_print.dart';
import 'add_return_invoice_screen.dart';
import 'purchase_invoice_screen.dart';
import 'sales_invoice_screen_v2.dart';
import 'scrap_purchase_invoice_screen.dart';
import 'scrap_sales_invoice_screen.dart';
import 'voucher_details_screen.dart';
// import 'add_invoice_screen.dart'; // TODO: Uncomment when implementing add invoice

enum _InvoiceCreationTarget {
  sales,
  scrapSale,
  scrapPurchase,
  supplierPurchase,
  salesReturn,
  scrapReturn,
  supplierReturn,
}

class InvoicesListScreen extends StatefulWidget {
  final bool isArabic;

  const InvoicesListScreen({super.key, this.isArabic = true});

  @override
  State<InvoicesListScreen> createState() => _InvoicesListScreenState();
}

class _InvoicesListScreenState extends State<InvoicesListScreen>
    with TickerProviderStateMixin {
  final ApiService _apiService = ApiService();
  List<dynamic> _invoices = [];
  List<dynamic> _filteredInvoices = [];
  bool _isLoading = false;
  List<Map<String, dynamic>>? _cachedCustomers;
  List<Map<String, dynamic>>? _cachedItems;
  int _itemsRevisionSnapshot = 0;
  VoidCallback? _itemsRevisionListener;

  // Tab controller
  late TabController _tabController;
  static const List<String> _tabTypes = [
    'بيع',
    'شراء من عميل',
    'شراء مورد',
    'مرتجع',
  ];
  static const List<String> _tabTypesEn = [
    'Sales',
    'Customer Purchase',
    'Supplier Purchase',
    'Returns',
  ];

  // Per-tab filter state (index 0=بيع, 1=شراء من عميل, 2=شراء مورد, 3=مرتجع)
  late final List<TextEditingController> _searchControllers;
  final List<String> _tabInvoiceSubType = ['all', 'all', 'all', 'all'];
  final List<String> _tabStatus = ['all', 'all', 'all', 'all'];
  final List<DateTimeRange?> _tabDateRange = [null, null, null, null];
  final List<String> _tabSort = ['date', 'date', 'date', 'date'];
  final List<bool> _tabSortAsc = [false, false, false, false];
  int _currentPage = 1;
  int _totalPages = 1;
  int _totalInvoices = 0;
  static const int _perPage = 50;
  Map<String, dynamic>? _globalTabSummary;

  static const Map<String, String> _invoicePrefixLookup = {
    'بيع': 'SELL',
    'sell': 'SELL',
    'sale': 'SELL',
    'شراء من عميل': 'BUY',
    // Supplier purchase (worked gold)
    'شراء': 'SUPP',
    'buy': 'BUY',
    'purchase': 'BUY',
    'مرتجع بيع': 'RETSELL',
    'sales return': 'RETSELL',
    'مرتجع شراء': 'RETBUY',
    'purchase return': 'RETBUY',
    'supplier purchase': 'SUPP',
    'مرتجع شراء (مورد)': 'RETSUPP',
    'supplier purchase return': 'RETSUPP',
  };

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: _tabTypes.length, vsync: this);
    _tabController.addListener(() {
      if (!mounted) return;
      setState(() {
        // Rebuild to refresh statistics header/search bar when tab changes.
      });
    });
    _searchControllers = List.generate(
      _tabTypes.length,
      (_) => TextEditingController(),
    );
    for (final ctrl in _searchControllers) {
      ctrl.addListener(() {
        if (mounted) setState(() {});
      });
    }
    _itemsRevisionSnapshot = DataSyncBus.itemsRevision.value;
    _itemsRevisionListener = () {
      _cachedItems = null;
      _itemsRevisionSnapshot = DataSyncBus.itemsRevision.value;
    };
    DataSyncBus.itemsRevision.addListener(_itemsRevisionListener!);
    _loadInvoices();
  }

  @override
  void dispose() {
    _tabController.dispose();
    for (final c in _searchControllers) {
      c.dispose();
    }
    if (_itemsRevisionListener != null) {
      DataSyncBus.itemsRevision.removeListener(_itemsRevisionListener!);
    }
    super.dispose();
  }

  Future<void> _loadInvoices({int? page}) async {
    if (!mounted) return;
    final targetPage = page ?? _currentPage;
    setState(() => _isLoading = true);

    try {
      const statusForApi = 'all';

      final data = await _apiService.getInvoices(
        page: targetPage,
        perPage: _perPage,
        sortBy: 'date',
        sortOrder: 'desc',
        search: '',
        status: statusForApi,
        invoiceType: null,
      );

      if (!mounted) return;

      // Process data
      final invoices = data['invoices'] ?? [];
      final total = _tryParseInt(data['total']) ?? invoices.length;
      final pages = _tryParseInt(data['pages']) ?? 1;
      final currentPage = _tryParseInt(data['current_page']) ?? targetPage;
      final meta = data['meta'] as Map<String, dynamic>?;
      Map<String, dynamic>? summary =
          meta?['tab_summary'] as Map<String, dynamic>?;

      if (summary == null ||
          summary['customer_purchase'] == null ||
          summary['supplier_purchase'] == null) {
        summary = await _fetchFullTabSummaryFromApi(
          statusForApi: statusForApi,
          dateFrom: null,
          dateTo: null,
        );
      }

      if (!mounted) return;

      setState(() {
        _invoices = invoices;
        _totalInvoices = total;
        _totalPages = pages < 1 ? 1 : pages;
        _currentPage = currentPage < 1 ? 1 : currentPage;
        _globalTabSummary = summary;
        _applyFilters();
      });
    } catch (e) {
      if (mounted) {
        _showSnackBar('خطأ في تحميل الفواتير: ${e.toString()}', isError: true);
      }
      debugPrint('❌ Error loading invoices: $e');
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  Future<Map<String, dynamic>?> _fetchFullTabSummaryFromApi({
    required String statusForApi,
    DateTime? dateFrom,
    DateTime? dateTo,
  }) async {
    try {
      const int summaryPerPage = 300;
      final firstPage = await _apiService.getInvoices(
        page: 1,
        perPage: summaryPerPage,
        sortBy: 'date',
        sortOrder: 'desc',
        search: '',
        status: 'all',
        invoiceType: null,
      );

      final allInvoices = <dynamic>[];
      allInvoices.addAll((firstPage['invoices'] as List?) ?? const []);

      final totalPages = _tryParseInt(firstPage['pages']) ?? 1;
      for (int page = 2; page <= totalPages; page++) {
        final pageData = await _apiService.getInvoices(
          page: page,
          perPage: summaryPerPage,
          sortBy: 'date',
          sortOrder: 'desc',
          search: '',
          status: 'all',
          invoiceType: null,
        );
        allInvoices.addAll((pageData['invoices'] as List?) ?? const []);
      }

      return _buildTabSummaryFromInvoices(allInvoices);
    } catch (_) {
      return null;
    }
  }

  Future<List<Map<String, dynamic>>> _getCachedCustomers() async {
    if (_cachedCustomers != null) {
      return _cachedCustomers!;
    }

    final customers = await _apiService.getCustomers();
    _cachedCustomers = _normalizeDynamicList(customers);
    return _cachedCustomers!;
  }

  Future<List<Map<String, dynamic>>> _getCachedItems() async {
    if (_itemsRevisionSnapshot != DataSyncBus.itemsRevision.value) {
      _cachedItems = null;
      _itemsRevisionSnapshot = DataSyncBus.itemsRevision.value;
    }
    if (_cachedItems != null) {
      return _cachedItems!;
    }

    final items = await _apiService.getItems();
    _cachedItems = _normalizeDynamicList(items);
    return _cachedItems!;
  }

  List<Map<String, dynamic>> _normalizeDynamicList(List<dynamic> source) {
    final normalized = <Map<String, dynamic>>[];
    for (final entry in source) {
      if (entry is Map<String, dynamic>) {
        normalized.add(Map<String, dynamic>.from(entry));
      } else if (entry is Map) {
        normalized.add(
          entry.map((key, value) => MapEntry(key.toString(), value)),
        );
      }
    }
    return normalized;
  }

  List<Map<String, dynamic>> _cloneDataList(List<Map<String, dynamic>> source) {
    return source.map((entry) => Map<String, dynamic>.from(entry)).toList();
  }

  double _parseStock(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) {
      return double.tryParse(value) ?? 0.0;
    }
    return 0.0;
  }

  List<Map<String, dynamic>> _filterSaleReadyItems(
    List<Map<String, dynamic>> source,
  ) {
    // 🔥 في تجارة الذهب: stock >= 1 تعني القطعة متاحة
    return source
        .where((item) => _parseStock(item['stock']) >= 1)
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Future<String?> _showStatusUpdateSheet(String currentStatus) async {
    final isAr = widget.isArabic;
    final options = [
      {'value': 'paid', 'label': isAr ? 'مدفوعة' : 'Paid'},
      {
        'value': 'partially_paid',
        'label': isAr ? 'مدفوعة جزئياً' : 'Partially Paid',
      },
      {'value': 'unpaid', 'label': isAr ? 'غير مدفوعة' : 'Unpaid'},
    ];

    return showModalBottomSheet<String>(
      context: context,
      builder: (ctx) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(height: 12),
              Text(
                isAr ? 'تحديث حالة الفاتورة' : 'Update Invoice Status',
                style: Theme.of(ctx).textTheme.titleMedium,
              ),
              const Divider(),
              for (final option in options)
                Card(
                  margin: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 6,
                  ),
                  child: ListTile(
                    leading: Icon(
                      currentStatus == option['value']
                          ? Icons.check_circle
                          : Icons.radio_button_unchecked,
                      color: currentStatus == option['value']
                          ? Colors.green
                          : Theme.of(ctx).colorScheme.onSurfaceVariant,
                    ),
                    title: Text(option['label']!),
                    onTap: () => Navigator.pop(ctx, option['value']),
                  ),
                ),
              const SizedBox(height: 12),
            ],
          ),
        );
      },
    );
  }

  void _applyFilters() {
    _filteredInvoices = List.from(_invoices);
  }

  /// Returns the filtered+sorted invoice list for a specific tab.
  List<dynamic> _getTabFilteredInvoices(int tabIndex, String tabType) {
    final tabBase = _getInvoicesForTabFromList(tabType, _filteredInvoices);
    final searchQ = _searchControllers[tabIndex].text.trim().toLowerCase();
    final subType = _tabInvoiceSubType[tabIndex];
    final status = _tabStatus[tabIndex];
    final dateRange = _tabDateRange[tabIndex];
    final sortField = _tabSort[tabIndex];
    final sortAsc = _tabSortAsc[tabIndex];

    var result = tabBase.where((invoice) {
      // Sub-type filter
      if (subType != 'all') {
        final invType = (invoice['invoice_type'] ?? '').toString().trim();
        if (invType != subType) return false;
      }

      // Search filter (number, customer/supplier, amount)
      if (searchQ.isNotEmpty) {
        final customerName = (invoice['customer_name'] ?? '')
            .toString()
            .toLowerCase();
        final supplierName = (invoice['supplier_name'] ?? '')
            .toString()
            .toLowerCase();
        final invNumber = _getInvoiceDisplayNumber(invoice).toLowerCase();
        final totalStr = _tryParseDouble(invoice['total']).toStringAsFixed(2);
        final totalRounded = _tryParseDouble(
          invoice['total'],
        ).toStringAsFixed(0);
        if (!customerName.contains(searchQ) &&
            !supplierName.contains(searchQ) &&
            !invNumber.contains(searchQ) &&
            !totalStr.contains(searchQ) &&
            !totalRounded.contains(searchQ)) {
          return false;
        }
      }

      // Status filter
      if (status != 'all') {
        final ns = _normalizeStatus((invoice['status'] ?? '').toString());
        if (status == 'paid_full') {
          if (ns != 'paid') return false;
        } else if (status == 'remaining') {
          if (ns != 'unpaid' && ns != 'partially_paid') return false;
        } else {
          if (ns != status) return false;
        }
      }

      // Date range filter
      if (dateRange != null && invoice['date'] != null) {
        try {
          final invoiceDate = DateTime.parse(invoice['date'].toString());
          final start = DateTime(
            dateRange.start.year,
            dateRange.start.month,
            dateRange.start.day,
          );
          final end = DateTime(
            dateRange.end.year,
            dateRange.end.month,
            dateRange.end.day,
            23,
            59,
            59,
            999,
          );
          if (invoiceDate.isBefore(start) || invoiceDate.isAfter(end)) {
            return false;
          }
        } catch (_) {}
      }

      return true;
    }).toList();

    // Sort
    result.sort((a, b) {
      int comparison = 0;
      try {
        switch (sortField) {
          case 'recent':
            comparison = (_tryParseInt(a['id']) ?? 0).compareTo(
              _tryParseInt(b['id']) ?? 0,
            );
            break;
          case 'date':
            final da = a['date'] != null
                ? DateTime.parse(a['date'].toString())
                : DateTime.now();
            final db = b['date'] != null
                ? DateTime.parse(b['date'].toString())
                : DateTime.now();
            comparison = da.compareTo(db);
            if (comparison == 0) {
              comparison = (_tryParseInt(a['id']) ?? 0).compareTo(
                _tryParseInt(b['id']) ?? 0,
              );
            }
            break;
          case 'customer':
            comparison = (a['customer_name'] ?? '').toString().compareTo(
              (b['customer_name'] ?? '').toString(),
            );
            break;
          case 'amount':
            comparison = _tryParseDouble(
              a['total'],
            ).compareTo(_tryParseDouble(b['total']));
            break;
          case 'number':
            final ap = _extractInvoicePrefix(a);
            final bp = _extractInvoicePrefix(b);
            comparison = ap.compareTo(bp);
            if (comparison == 0) {
              comparison = _extractInvoiceYear(
                a,
              ).compareTo(_extractInvoiceYear(b));
              if (comparison == 0) {
                comparison = _extractInvoiceSequence(
                  a,
                ).compareTo(_extractInvoiceSequence(b));
              }
            }
            break;
        }
      } catch (_) {}
      return sortAsc ? comparison : -comparison;
    });

    return result;
  }

  String _normalizeStatus(String? rawStatus) {
    if (rawStatus == null) {
      return 'unknown';
    }

    final trimmed = rawStatus.trim();
    if (trimmed.isEmpty) {
      return 'unknown';
    }

    final lower = trimmed.toLowerCase();

    if (lower == 'paid' || trimmed == 'مدفوعة') {
      return 'paid';
    }
    if (lower == 'unpaid' || trimmed == 'غير مدفوعة') {
      return 'unpaid';
    }
    if (lower == 'partially_paid' ||
        lower == 'partially paid' ||
        trimmed == 'مدفوعة جزئياً') {
      return 'partially_paid';
    }
    // Invoice drafts are not supported.
    if (lower == 'cancelled' || lower == 'canceled' || trimmed == 'ملغاة') {
      return 'cancelled';
    }

    return lower;
  }

  int? _tryParseInt(dynamic value) {
    if (value == null) {
      return null;
    }
    if (value is int) {
      return value;
    }
    return int.tryParse(value.toString());
  }

  double _tryParseDouble(dynamic value) {
    if (value == null) return 0.0;
    if (value is num) return value.toDouble();
    return double.tryParse(value.toString()) ?? 0.0;
  }

  double _extractInvoiceTotalWeight(Map<String, dynamic> invoice) {
    final items = invoice['items'];
    // Prefer deriving from items when available.
    // Some backends/legacy invoices store `total_weight` already multiplied by
    // quantity; the invoice details view shows per-line weight, so the list
    // should match that and avoid qty multiplication.
    if (items is List && items.isNotEmpty) {
      var sum = 0.0;
      for (final entry in items) {
        if (entry is Map) {
          sum += _tryParseDouble(
            entry['weight'] ??
                entry['weight_grams'] ??
                entry['gold_weight'] ??
                entry['total_weight'],
          );
        }
      }
      return sum;
    }

    final direct = _tryParseDouble(invoice['total_weight']);
    if (direct > 0) return direct;

    return 0.0;
  }

  String? _extractInvoiceKaratLabel(Map<String, dynamic> invoice) {
    final direct =
        invoice['karat'] ?? invoice['gold_karat'] ?? invoice['karat_value'];
    final directStr = direct?.toString().trim();
    if (directStr != null && directStr.isNotEmpty) {
      return directStr;
    }

    final items = invoice['items'];
    if (items is List) {
      final karats = <String>{};
      for (final entry in items) {
        if (entry is Map) {
          final v =
              (entry['karat'] ?? entry['gold_karat'] ?? entry['karat_value'])
                  ?.toString()
                  .trim();
          if (v != null && v.isNotEmpty) {
            karats.add(v);
          }
        }
      }
      if (karats.isEmpty) return null;
      final list = karats.toList()..sort();
      return list.join('/');
    }

    return null;
  }

  String? _extractInvoiceGoldTypeLabel(Map<String, dynamic> invoice) {
    final direct =
        invoice['gold_type'] ??
        invoice['goldType'] ??
        invoice['gold_type_name'];
    final directStr = direct?.toString().trim();
    if (directStr != null && directStr.isNotEmpty) {
      return directStr;
    }

    final items = invoice['items'];
    if (items is List) {
      final types = <String>{};
      for (final entry in items) {
        if (entry is Map) {
          final v =
              (entry['gold_type'] ??
                      entry['goldType'] ??
                      entry['gold_type_name'] ??
                      entry['type'])
                  ?.toString()
                  .trim();
          if (v != null && v.isNotEmpty) {
            types.add(v);
          }
        }
      }
      if (types.isEmpty) return null;
      final list = types.toList()..sort();
      return list.join('/');
    }

    return null;
  }

  String? _extractInvoiceEmployeeName(Map<String, dynamic> invoice) {
    final candidates = [
      invoice['employee_name'],
      invoice['seller_name'],
      invoice['created_by_name'],
      invoice['created_by'],
      invoice['posted_by_name'],
      invoice['posted_by'],
      invoice['user_name'],
      invoice['cashier_name'],
      invoice['cashier'],
    ];

    for (final v in candidates) {
      final s = v?.toString().trim();
      if (s != null && s.isNotEmpty) {
        return s;
      }
    }
    return null;
  }

  String _getInvoiceDisplayNumber(Map<String, dynamic> invoice) {
    final String? trimmedNumber = invoice['invoice_number']?.toString().trim();
    if (trimmedNumber?.isNotEmpty ?? false) {
      return trimmedNumber!;
    }

    final fallback = _buildFallbackInvoiceNumber(invoice);
    if (fallback != null) {
      return fallback;
    }

    final legacyId = invoice['id'];
    return legacyId != null ? '#${legacyId.toString()}' : '#---';
  }

  String? _buildFallbackInvoiceNumber(Map<String, dynamic> invoice) {
    try {
      final invoiceType = (invoice['invoice_type'] ?? '').toString().trim();
      if (invoiceType.isEmpty) {
        return null;
      }

      final int? sequence = _tryParseInt(invoice['invoice_type_id']);
      if (sequence == null || sequence <= 0) {
        return null;
      }

      final prefix = _resolveInvoicePrefix(invoiceType);
      final String? rawDate = invoice['date']?.toString();
      final parsedDate = rawDate != null ? DateTime.tryParse(rawDate) : null;
      final year = parsedDate?.year ?? DateTime.now().year;

      final digits = sequence >= 1000 ? 4 : 3;
      final sequenceStr = sequence.toString().padLeft(digits, '0');

      return '$prefix-$year-$sequenceStr';
    } catch (e) {
      debugPrint('⚠️ فشل بناء رقم فاتورة بديل: $e');
      return null;
    }
  }

  String _resolveInvoicePrefix(String invoiceType) {
    final trimmed = invoiceType.trim();
    if (trimmed.isEmpty) {
      return 'INV';
    }

    final lower = trimmed.toLowerCase();
    if (_invoicePrefixLookup.containsKey(trimmed)) {
      return _invoicePrefixLookup[trimmed]!;
    }
    if (_invoicePrefixLookup.containsKey(lower)) {
      return _invoicePrefixLookup[lower]!;
    }

    return 'INV';
  }

  String _extractInvoicePrefix(Map<String, dynamic> invoice) {
    final String? rawNumber = invoice['invoice_number']?.toString();
    if (rawNumber != null) {
      final parts = rawNumber.split('-');
      if (parts.isNotEmpty && parts.first.trim().isNotEmpty) {
        return parts.first.trim();
      }
    }
    final invoiceType = (invoice['invoice_type'] ?? '').toString();
    return _resolveInvoicePrefix(invoiceType);
  }

  int _extractInvoiceYear(Map<String, dynamic> invoice) {
    final String? rawNumber = invoice['invoice_number']?.toString();
    if (rawNumber != null) {
      final parts = rawNumber.split('-');
      if (parts.length >= 2) {
        final year = int.tryParse(parts[1]);
        if (year != null) {
          return year;
        }
      }
    }

    final String? rawDate = invoice['date']?.toString();
    final parsedDate = rawDate != null ? DateTime.tryParse(rawDate) : null;
    return parsedDate?.year ?? DateTime.now().year;
  }

  int _extractInvoiceSequence(Map<String, dynamic> invoice) {
    final String? rawNumber = invoice['invoice_number']?.toString();
    if (rawNumber != null) {
      final parts = rawNumber.split('-');
      if (parts.isNotEmpty) {
        final sequence = int.tryParse(parts.last);
        if (sequence != null) {
          return sequence;
        }
      }
    }

    final int? parsed = _tryParseInt(invoice['invoice_type_id']);
    if (parsed != null) {
      return parsed;
    }

    final int? legacyIdValue = _tryParseInt(invoice['id']);
    if (legacyIdValue != null) {
      return legacyIdValue;
    }

    return int.tryParse(invoice['id']?.toString() ?? '') ?? 0;
  }

  String _translateStatus(String? status, bool isArabic) {
    if (status == null || status.isEmpty) {
      return isArabic ? 'غير محدد' : 'N/A';
    }

    final normalized = _normalizeStatus(status);
    switch (normalized) {
      case 'paid':
        return isArabic ? 'مدفوعة' : 'Paid';
      case 'unpaid':
        return isArabic ? 'غير مدفوعة' : 'Unpaid';
      case 'partially_paid':
        return isArabic ? 'مدفوعة جزئياً' : 'Partially Paid';
      case 'cancelled':
        return isArabic ? 'ملغاة' : 'Cancelled';
      default:
        return status;
    }
  }

  List<dynamic> _getInvoicesForTabFromList(
    String tabType,
    List<dynamic> source,
  ) {
    if (source.isEmpty) return [];

    final normalizedLabel = tabType.trim().toLowerCase();
    final isSalesTab = tabType == 'بيع' || normalizedLabel == 'sales';
    final isCustomerPurchaseTab =
        tabType == 'شراء من عميل' || normalizedLabel == 'customer purchase';
    final isSupplierPurchaseTab =
        tabType == 'شراء مورد' || normalizedLabel == 'supplier purchase';
    final isReturnsTab = tabType == 'مرتجع' || normalizedLabel == 'returns';

    bool isReturnInvoiceType(String type) {
      final t = type.trim();
      if (t.isEmpty) return false;
      final lower = t.toLowerCase();
      return t.contains('مرتجع') || lower.contains('return');
    }

    bool isSalesInvoiceType(String type) {
      final t = type.trim();
      if (t.isEmpty) return false;
      if (isReturnInvoiceType(t)) return false;
      final lower = t.toLowerCase();
      return t.contains('بيع') || lower == 'sell' || lower.contains('sale');
    }

    bool isPurchaseInvoiceType(String type) {
      final t = type.trim();
      if (t.isEmpty) return false;
      if (isReturnInvoiceType(t)) return false;
      final lower = t.toLowerCase();
      return t.contains('شراء') || lower == 'buy' || lower.contains('purchase');
    }

    bool isCustomerPurchaseInvoiceType(String type) {
      final t = type.trim();
      if (t.isEmpty) return false;
      if (isReturnInvoiceType(t)) return false;
      return t == 'شراء من عميل' || t == 'شراء خردة' || t == 'شراء مستعمل';
    }

    bool isSupplierPurchaseInvoiceType(String type) {
      final t = type.trim();
      if (t.isEmpty) return false;
      if (isReturnInvoiceType(t)) return false;
      if (t == 'شراء') return true;
      return isPurchaseInvoiceType(t) && !isCustomerPurchaseInvoiceType(t);
    }

    return source.where((inv) {
      final type = (inv['invoice_type'] ?? '').toString();
      if (isReturnsTab) return isReturnInvoiceType(type);
      if (isCustomerPurchaseTab) return isCustomerPurchaseInvoiceType(type);
      if (isSupplierPurchaseTab) return isSupplierPurchaseInvoiceType(type);
      if (isSalesTab) return isSalesInvoiceType(type);
      return false;
    }).toList();
  }

  Map<String, dynamic> _calculateStatsFromInvoices(List<dynamic> tabInvoices) {
    final stats = <String, dynamic>{
      'total_invoices': 0,
      'total_amount': 0.0,
      'paid_amount': 0.0,
      'unpaid_amount': 0.0,
      'vat_total': 0.0,
      'sold_weight_total': 0.0,
    };

    if (tabInvoices.isEmpty) return stats;

    try {
      stats['total_invoices'] = tabInvoices.length;

      stats['total_amount'] = tabInvoices.fold(0.0, (sum, invoice) {
        try {
          final normalized = _normalizeStatus(
            (invoice['status'] ?? '').toString(),
          );
          if (normalized == 'cancelled') return sum;
          return sum + ((invoice['total'] ?? 0) as num).toDouble();
        } catch (e) {
          return sum;
        }
      });

      stats['paid_amount'] = tabInvoices.fold(0.0, (sum, invoice) {
        try {
          final normalized = _normalizeStatus(
            (invoice['status'] ?? '').toString(),
          );
          if (normalized == 'cancelled') return sum;

          final total = _tryParseDouble(invoice['total']);
          final paidCash = _tryParseDouble(
            invoice['amount_paid'] ?? invoice['total_payments_amount'],
          );
          final barterTotal = _tryParseDouble(invoice['barter_total']);
          final hasTotalSettledKey = invoice.containsKey(
            'total_settled_amount',
          );
          final totalSettled = hasTotalSettledKey
              ? _tryParseDouble(invoice['total_settled_amount'])
              : (paidCash + barterTotal);
          final paidClamped = totalSettled.clamp(0.0, total);
          return sum + paidClamped;
        } catch (e) {
          return sum;
        }
      });

      stats['unpaid_amount'] = tabInvoices.fold(0.0, (sum, invoice) {
        try {
          final normalized = _normalizeStatus(
            (invoice['status'] ?? '').toString(),
          );
          if (normalized == 'cancelled') return sum;

          final total = _tryParseDouble(invoice['total']);
          final paidCash = _tryParseDouble(
            invoice['amount_paid'] ?? invoice['total_payments_amount'],
          );
          final barterTotal = _tryParseDouble(invoice['barter_total']);
          final hasTotalSettledKey = invoice.containsKey(
            'total_settled_amount',
          );
          final totalSettled = hasTotalSettledKey
              ? _tryParseDouble(invoice['total_settled_amount'])
              : (paidCash + barterTotal);
          final remaining = (total - totalSettled).clamp(0.0, double.infinity);
          return sum + remaining;
        } catch (e) {
          return sum;
        }
      });

      stats['vat_total'] = tabInvoices.fold(0.0, (sum, invoice) {
        try {
          final normalized = _normalizeStatus(
            (invoice['status'] ?? '').toString(),
          );
          if (normalized == 'cancelled') return sum;
          return sum + _tryParseDouble(invoice['total_tax']);
        } catch (e) {
          return sum;
        }
      });

      stats['sold_weight_total'] = tabInvoices.fold(0.0, (sum, invoice) {
        try {
          final normalized = _normalizeStatus(
            (invoice['status'] ?? '').toString(),
          );
          if (normalized == 'cancelled') return sum;
          return sum + _extractInvoiceTotalWeight(invoice);
        } catch (e) {
          return sum;
        }
      });
    } catch (e) {
      debugPrint('❌ خطأ في حساب إحصائيات التبويب: $e');
    }

    return stats;
  }

  Map<String, dynamic> _buildTabSummaryFromInvoices(List<dynamic> source) {
    return {
      'sales': _calculateStatsFromInvoices(
        _getInvoicesForTabFromList('بيع', source),
      ),
      'customer_purchase': _calculateStatsFromInvoices(
        _getInvoicesForTabFromList('شراء من عميل', source),
      ),
      'supplier_purchase': _calculateStatsFromInvoices(
        _getInvoicesForTabFromList('شراء مورد', source),
      ),
      'returns': _calculateStatsFromInvoices(
        _getInvoicesForTabFromList('مرتجع', source),
      ),
    };
  }

  // Calculate stats for the current tab (respects active filters)
  Map<String, dynamic> _getTabStatistics(String tabType) {
    String resolveSummaryKey(String label) {
      final normalizedLabel = label.trim().toLowerCase();
      if (label == 'بيع' || normalizedLabel == 'sales') return 'sales';
      if (label == 'شراء من عميل' || normalizedLabel == 'customer purchase') {
        return 'customer_purchase';
      }
      if (label == 'شراء مورد' || normalizedLabel == 'supplier purchase') {
        return 'supplier_purchase';
      }
      if (label == 'مرتجع' || normalizedLabel == 'returns') return 'returns';
      return 'sales';
    }

    final summaryKey = resolveSummaryKey(tabType);
    final tabIndex = _tabTypes.indexOf(tabType);
    final effectiveIndex = tabIndex >= 0 ? tabIndex : 0;

    final globalSummary = _globalTabSummary?[summaryKey];
    if (globalSummary is Map &&
        _tabStatus[effectiveIndex] == 'all' &&
        _tabDateRange[effectiveIndex] == null &&
        _tabInvoiceSubType[effectiveIndex] == 'all' &&
        _searchControllers[effectiveIndex].text.isEmpty) {
      return {
        'total_invoices': _tryParseInt(globalSummary['total_invoices']) ?? 0,
        'total_amount': _tryParseDouble(globalSummary['total_amount']),
        'paid_amount': _tryParseDouble(globalSummary['paid_amount']),
        'unpaid_amount': _tryParseDouble(globalSummary['unpaid_amount']),
        'vat_total': _tryParseDouble(globalSummary['vat_total']),
        'sold_weight_total': _tryParseDouble(
          globalSummary['sold_weight_total'],
        ),
      };
    }

    final tabInvoices = _getTabFilteredInvoices(effectiveIndex, tabType);
    return _calculateStatsFromInvoices(tabInvoices);
  }

  void _showSnackBar(String message, {required bool isError}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? Colors.red : Colors.green,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  void _clearFilters() {
    final idx = _tabController.index;
    setState(() {
      _searchControllers[idx].clear();
      _tabInvoiceSubType[idx] = 'all';
      _tabStatus[idx] = 'all';
      _tabDateRange[idx] = null;
      _tabSort[idx] = 'date';
      _tabSortAsc[idx] = false;
      _currentPage = 1;
    });
    _loadInvoices(page: 1);
  }

  int get _activeFiltersCount {
    final idx = _tabController.index;
    int count = 0;
    if (_searchControllers[idx].text.isNotEmpty) count++;
    if (_tabInvoiceSubType[idx] != 'all') count++;
    if (_tabStatus[idx] != 'all') count++;
    if (_tabDateRange[idx] != null) count++;
    if (_tabSort[idx] != 'date' && _tabSort[idx] != 'recent') count++;
    return count;
  }

  Widget _buildPaginationStrip() {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    if (_totalInvoices == 0) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(12, 2, 6, 4),
      child: Row(
        children: [
          Expanded(
            child: Text(
              isAr
                  ? 'الصفحة $_currentPage من $_totalPages • $_totalInvoices فاتورة'
                  : 'Page $_currentPage of $_totalPages • $_totalInvoices invoices',
              style: theme.textTheme.labelSmall?.copyWith(
                color: colorScheme.onSurface.withValues(alpha: 0.45),
              ),
            ),
          ),
          SizedBox(
            width: 28,
            height: 28,
            child: IconButton(
              visualDensity: VisualDensity.compact,
              padding: EdgeInsets.zero,
              icon: const Icon(Icons.chevron_left, size: 18),
              tooltip: isAr ? 'السابق' : 'Previous',
              onPressed: (_isLoading || _currentPage <= 1)
                  ? null
                  : () => _loadInvoices(page: _currentPage - 1),
            ),
          ),
          SizedBox(
            width: 28,
            height: 28,
            child: IconButton(
              visualDensity: VisualDensity.compact,
              padding: EdgeInsets.zero,
              icon: const Icon(Icons.chevron_right, size: 18),
              tooltip: isAr ? 'التالي' : 'Next',
              onPressed: (_isLoading || _currentPage >= _totalPages)
                  ? null
                  : () => _loadInvoices(page: _currentPage + 1),
            ),
          ),
        ],
      ),
    );
  }

  void _showFiltersBottomSheet() {
    final isAr = widget.isArabic;
    final idx = _tabController.index;
    String tempSubType = _tabInvoiceSubType[idx];
    String tempStatus = _tabStatus[idx];
    String tempSort = _tabSort[idx];
    bool tempAsc = _tabSortAsc[idx];
    DateTimeRange? tempDate = _tabDateRange[idx];

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSS) {
          final theme = Theme.of(context);
          final colorScheme = theme.colorScheme;
          final textTheme = theme.textTheme;
          final bdRadius = BorderRadius.circular(12);

          Widget sheetDropdown({
            required String value,
            required List<Map<String, String>> items,
            required ValueChanged<String?> onChanged,
          }) {
            final hasMatch = items.any((i) => i['value'] == value);
            final eff = hasMatch
                ? value
                : (items.isNotEmpty ? items.first['value']! : value);
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
              decoration: BoxDecoration(
                color: colorScheme.surface,
                borderRadius: bdRadius,
                border: Border.all(
                  color: colorScheme.outline.withValues(alpha: 0.25),
                ),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: eff,
                  isExpanded: true,
                  dropdownColor: colorScheme.surface,
                  style: textTheme.bodyMedium?.copyWith(
                    color: colorScheme.onSurface,
                  ),
                  items: items
                      .map(
                        (i) => DropdownMenuItem(
                          value: i['value']!,
                          child: Text(i['label']!, style: textTheme.bodyMedium),
                        ),
                      )
                      .toList(),
                  onChanged: onChanged,
                ),
              ),
            );
          }

          return Directionality(
            textDirection: isAr ? TextDirection.rtl : TextDirection.ltr,
            child: Padding(
              padding: EdgeInsets.only(
                top: 16,
                left: 16,
                right: 16,
                bottom: MediaQuery.of(ctx).viewInsets.bottom + 24,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Handle
                  Center(
                    child: Container(
                      width: 40,
                      height: 4,
                      margin: const EdgeInsets.only(bottom: 12),
                      decoration: BoxDecoration(
                        color: colorScheme.onSurface.withValues(alpha: 0.18),
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                  ),
                  // Header
                  Row(
                    children: [
                      Icon(Icons.tune, color: colorScheme.primary, size: 18),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          isAr
                              ? 'تصفية: ${_tabTypes[idx]}'
                              : 'Filter: ${_tabTypesEn[idx]}',
                          style: textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                      TextButton(
                        onPressed: () {
                          Navigator.pop(ctx);
                          _clearFilters();
                        },
                        child: Text(
                          isAr ? 'مسح الكل' : 'Clear All',
                          style: TextStyle(
                            color: colorScheme.error,
                            fontSize: 13,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  // Date range
                  OutlinedButton.icon(
                    icon: Icon(
                      Icons.date_range,
                      size: 18,
                      color: tempDate != null
                          ? colorScheme.primary
                          : colorScheme.onSurface.withValues(alpha: 0.6),
                    ),
                    label: Text(
                      tempDate == null
                          ? (isAr ? 'اختر نطاق تاريخ' : 'Select date range')
                          : '${DateFormat('dd/MM/yy').format(tempDate!.start)}  →  ${DateFormat('dd/MM/yy').format(tempDate!.end)}',
                      style: textTheme.bodySmall?.copyWith(
                        color: tempDate != null ? colorScheme.primary : null,
                        fontWeight: tempDate != null ? FontWeight.w600 : null,
                      ),
                    ),
                    style: OutlinedButton.styleFrom(
                      alignment: AlignmentDirectional.centerStart,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 12,
                      ),
                      side: BorderSide(
                        color: tempDate != null
                            ? colorScheme.primary.withValues(alpha: 0.5)
                            : colorScheme.outline.withValues(alpha: 0.3),
                      ),
                      shape: RoundedRectangleBorder(borderRadius: bdRadius),
                    ),
                    onPressed: () async {
                      final picked = await showDateRangePicker(
                        context: context,
                        firstDate: DateTime(2020),
                        lastDate: DateTime.now().add(const Duration(days: 365)),
                        initialDateRange: tempDate,
                      );
                      if (picked != null) setSS(() => tempDate = picked);
                    },
                  ),
                  if (tempDate != null)
                    Align(
                      alignment: AlignmentDirectional.centerEnd,
                      child: TextButton.icon(
                        onPressed: () => setSS(() => tempDate = null),
                        icon: const Icon(Icons.close, size: 14),
                        label: Text(isAr ? 'مسح التاريخ' : 'Clear date'),
                        style: TextButton.styleFrom(
                          foregroundColor: colorScheme.onSurface.withValues(
                            alpha: 0.55,
                          ),
                          visualDensity: VisualDensity.compact,
                        ),
                      ),
                    ),
                  const SizedBox(height: 10),
                  // Sub-type (scoped to this tab) + Status
                  Row(
                    children: [
                      Expanded(
                        child: sheetDropdown(
                          value: tempSubType,
                          items: _buildInvoiceTypeItemsForTab(isAr, idx),
                          onChanged: (v) {
                            if (v != null) setSS(() => tempSubType = v);
                          },
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: sheetDropdown(
                          value: tempStatus,
                          items: _buildStatusItems(isAr),
                          onChanged: (v) {
                            if (v != null) setSS(() => tempStatus = v);
                          },
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  // Sort
                  Row(
                    children: [
                      Expanded(
                        child: sheetDropdown(
                          value: tempSort,
                          items: [
                            {
                              'value': 'recent',
                              'label': isAr ? 'الأحدث' : 'Most Recent',
                            },
                            {
                              'value': 'date',
                              'label': isAr ? 'التاريخ' : 'Date',
                            },
                            {
                              'value': 'customer',
                              'label': isAr ? 'العميل' : 'Customer',
                            },
                            {
                              'value': 'amount',
                              'label': isAr ? 'المبلغ' : 'Amount',
                            },
                            {
                              'value': 'number',
                              'label': isAr ? 'الرقم' : 'Number',
                            },
                          ],
                          onChanged: (v) {
                            if (v != null) setSS(() => tempSort = v);
                          },
                        ),
                      ),
                      const SizedBox(width: 8),
                      OutlinedButton.icon(
                        icon: Icon(
                          tempAsc ? Icons.arrow_upward : Icons.arrow_downward,
                          size: 16,
                        ),
                        label: Text(
                          tempAsc
                              ? (isAr ? 'تصاعدي' : 'Asc')
                              : (isAr ? 'تنازلي' : 'Desc'),
                          style: textTheme.bodySmall,
                        ),
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 12,
                          ),
                          shape: RoundedRectangleBorder(borderRadius: bdRadius),
                        ),
                        onPressed: () => setSS(() => tempAsc = !tempAsc),
                      ),
                    ],
                  ),
                  const SizedBox(height: 18),
                  // Apply
                  FilledButton.icon(
                    icon: const Icon(Icons.check, size: 18),
                    label: Text(
                      isAr ? 'تطبيق الفلاتر' : 'Apply Filters',
                      style: const TextStyle(fontWeight: FontWeight.bold),
                    ),
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                    ),
                    onPressed: () {
                      Navigator.pop(ctx);
                      setState(() {
                        _tabInvoiceSubType[idx] = tempSubType;
                        _tabStatus[idx] = tempStatus;
                        _tabSort[idx] = tempSort;
                        _tabSortAsc[idx] = tempAsc;
                        _tabDateRange[idx] = tempDate;
                        _currentPage = 1;
                      });
                    },
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final primary = colorScheme.primary;
    final scaffoldBackground = theme.scaffoldBackgroundColor;
    final tabLabels = isAr ? _tabTypes : _tabTypesEn;
    final tabIcons = [
      Icons.shopping_bag,
      Icons.person_search,
      Icons.local_shipping,
      Icons.undo,
    ];

    return Directionality(
      textDirection: isAr ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        backgroundColor: scaffoldBackground,
        appBar: AppBar(
          title: Text(isAr ? 'قائمة الفواتير' : 'Invoices List'),
          actions: [
            IconButton(
              icon: Icon(Icons.add, color: primary),
              onPressed: _navigateToAddInvoice,
              tooltip: isAr ? 'فاتورة جديدة' : 'New Invoice',
            ),
            Badge(
              isLabelVisible: _activeFiltersCount > 0,
              label: Text('$_activeFiltersCount'),
              child: IconButton(
                icon: Icon(Icons.tune, color: primary),
                onPressed: _showFiltersBottomSheet,
                tooltip: isAr ? 'الفلاتر' : 'Filters',
              ),
            ),
            IconButton(
              icon: Icon(Icons.refresh, color: primary),
              onPressed: _loadInvoices,
              tooltip: isAr ? 'تحديث' : 'Refresh',
            ),
          ],
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(102),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TabBar(
                  controller: _tabController,
                  isScrollable: true,
                  labelColor: primary,
                  unselectedLabelColor: colorScheme.onSurface.withValues(
                    alpha: 0.6,
                  ),
                  indicatorColor: primary,
                  indicatorSize: TabBarIndicatorSize.label,
                  tabs: List.generate(tabLabels.length, (index) {
                    return Tab(
                      icon: Icon(tabIcons[index]),
                      text: tabLabels[index],
                    );
                  }),
                ),
                // Pinned search bar — one per tab
                Padding(
                  padding: const EdgeInsets.fromLTRB(8, 0, 8, 6),
                  child: TextField(
                    controller: _searchControllers[_tabController.index],
                    style: Theme.of(context).textTheme.bodyMedium,
                    onTap: () {
                      final ctrl = _searchControllers[_tabController.index];
                      ctrl.selection = TextSelection(
                        baseOffset: 0,
                        extentOffset: ctrl.text.length,
                      );
                    },
                    decoration: InputDecoration(
                      hintText: isAr
                          ? 'بحث برقم الفاتورة أو العميل أو المبلغ...'
                          : 'Search: number, customer, amount...',
                      prefixIcon: const Icon(Icons.search, size: 18),
                      suffixIcon:
                          _searchControllers[_tabController.index]
                              .text
                              .isNotEmpty
                          ? IconButton(
                              icon: const Icon(Icons.clear, size: 16),
                              onPressed: () => setState(
                                () => _searchControllers[_tabController.index]
                                    .clear(),
                              ),
                            )
                          : null,
                      isDense: true,
                      filled: true,
                      fillColor: colorScheme.surface.withValues(alpha: 0.92),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(10),
                        borderSide: BorderSide.none,
                      ),
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 8,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        body: NestedScrollView(
          headerSliverBuilder: (context, innerBoxIsScrolled) {
            return [
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsetsDirectional.fromSTEB(8, 6, 8, 0),
                  child: _buildStatisticsSection(),
                ),
              ),
              SliverToBoxAdapter(child: _buildPaginationStrip()),
            ];
          },
          body: _isLoading
              ? Center(
                  child: CircularProgressIndicator(
                    valueColor: AlwaysStoppedAnimation<Color>(primary),
                  ),
                )
              : TabBarView(
                  controller: _tabController,
                  children: List.generate(tabLabels.length, (index) {
                    final tabInvoices = _getTabFilteredInvoices(
                      index,
                      tabLabels[index],
                    );

                    if (tabInvoices.isEmpty) {
                      return _buildEmptyState();
                    }

                    return _buildTabContent(tabInvoices);
                  }),
                ),
        ),
      ),
    );
  }

  // Build content for each tab
  Widget _buildTabContent(List<dynamic> tabInvoices) {
    if (tabInvoices.isEmpty) {
      return _buildEmptyState();
    }

    return RefreshIndicator(
      onRefresh: _loadInvoices,
      color: Theme.of(context).colorScheme.primary,
      backgroundColor: Theme.of(context).colorScheme.surface,
      child: ListView.builder(
        padding: const EdgeInsets.all(10),
        itemCount: tabInvoices.length,
        itemBuilder: (context, index) {
          try {
            final invoice = tabInvoices[index];
            return _buildInvoiceCard(invoice);
          } catch (e, stackTrace) {
            debugPrint('❌ خطأ في بناء بطاقة الفاتورة $index: $e');
            debugPrint('Stack: $stackTrace');
            return SizedBox.shrink();
          }
        },
      ),
    );
  }

  Widget _buildStatisticsSection() {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    final bool isDark = theme.brightness == Brightness.dark;
    final statsBackground = colorScheme.surfaceContainerHighest.withValues(
      alpha: isDark ? 0.35 : 0.2,
    );

    // Get current tab type
    final tabLabels = isAr ? _tabTypes : _tabTypesEn;
    final currentTabType = _tabController.index < tabLabels.length
        ? tabLabels[_tabController.index]
        : tabLabels[0];

    // Get statistics for current tab
    final tabStats = _getTabStatistics(currentTabType);

    return Container(
      padding: const EdgeInsetsDirectional.fromSTEB(8, 6, 8, 6),
      decoration: BoxDecoration(
        color: statsBackground,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: colorScheme.primary.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  currentTabType,
                  style: textTheme.labelSmall?.copyWith(
                    color: colorScheme.primary,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: _buildStatCard(
                  icon: Icons.receipt_long,
                  title: isAr ? 'إجمالي الفواتير' : 'Total Invoices',
                  value: tabStats['total_invoices'].toString(),
                  highlightColor: Colors.blue,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _buildStatCard(
                  icon: Icons.attach_money,
                  title: isAr ? 'المبلغ الكلي' : 'Total Amount',
                  value: NumberFormat(
                    '#,##0',
                    isAr ? 'ar' : 'en',
                  ).format(tabStats['total_amount']),
                  highlightColor: colorScheme.primary,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _buildStatCard(
                  icon: Icons.check_circle,
                  title: isAr ? 'المدفوع' : 'Paid',
                  value: NumberFormat(
                    '#,##0',
                    isAr ? 'ar' : 'en',
                  ).format(tabStats['paid_amount']),
                  highlightColor: Colors.green,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: _buildStatCard(
                  icon: Icons.pending,
                  title: isAr ? 'المتبقي' : 'Unpaid',
                  value: NumberFormat(
                    '#,##0',
                    isAr ? 'ar' : 'en',
                  ).format(tabStats['unpaid_amount']),
                  highlightColor: Colors.orange,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _buildStatCard(
                  icon: Icons.receipt,
                  title: isAr ? 'إجمالي الضريبة' : 'VAT Total',
                  value: NumberFormat(
                    '#,##0.00',
                    isAr ? 'ar' : 'en',
                  ).format(tabStats['vat_total']),
                  highlightColor: colorScheme.tertiary,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: _buildStatCard(
                  icon: Icons.scale,
                  title: isAr ? 'الوزن (جم)' : 'Weight (g)',
                  value: NumberFormat(
                    '#,##0.###',
                    isAr ? 'ar' : 'en',
                  ).format(tabStats['sold_weight_total']),
                  highlightColor: colorScheme.secondary,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatCard({
    required IconData icon,
    required String title,
    required String value,
    required Color highlightColor,
  }) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;

    return Card(
      elevation: theme.cardTheme.elevation ?? 2,
      color: theme.cardTheme.color ?? colorScheme.surface,
      shape:
          theme.cardTheme.shape ??
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(4),
                  decoration: BoxDecoration(
                    color: highlightColor.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(icon, color: highlightColor, size: 14),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    title,
                    style: textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurface.withValues(alpha: 0.7),
                      fontWeight: FontWeight.w600,
                      fontSize: 11,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              value,
              style: textTheme.titleLarge?.copyWith(
                color: highlightColor,
                fontWeight: FontWeight.bold,
                fontSize: 15,
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<Map<String, String>> _buildStatusItems(bool isArabic) {
    return [
      {'value': 'all', 'label': isArabic ? 'الكل' : 'All'},
      {
        'value': 'paid_full',
        'label': isArabic ? 'مدفوعة بالكامل' : 'Paid (Full)',
      },
      {'value': 'remaining', 'label': isArabic ? 'المتبقي/الآجل' : 'Remaining'},
      {'value': 'paid', 'label': isArabic ? 'مدفوعة' : 'Paid'},
      {
        'value': 'partially_paid',
        'label': isArabic ? 'مدفوعة جزئياً' : 'Partially Paid',
      },
      {'value': 'unpaid', 'label': isArabic ? 'غير مدفوعة' : 'Unpaid'},
      // Invoice drafts are not supported.
      {'value': 'cancelled', 'label': isArabic ? 'ملغاة' : 'Cancelled'},
    ];
  }

  /// Returns invoice sub-type dropdown items scoped to the given tab index.
  List<Map<String, String>> _buildInvoiceTypeItemsForTab(
    bool isAr,
    int tabIndex,
  ) {
    const salesTypes = ['بيع', 'بيع جديد', 'بيع مستعمل', 'مقايضة'];
    const customerPurchaseTypes = ['شراء من عميل', 'شراء خردة', 'شراء مستعمل'];
    const supplierPurchaseTypes = ['شراء'];
    const returnTypes = [
      'مرتجع بيع',
      'مرتجع بيع خردة',
      'مرتجع شراء',
      'مرتجع شراء (مورد)',
      'مرتجع شراء من عميل',
    ];
    const englishMap = {
      'بيع': 'Sale',
      'بيع جديد': 'New Sale',
      'بيع مستعمل': 'Used Sale',
      'مقايضة': 'Exchange',
      'شراء': 'Purchase',
      'شراء من عميل': 'Purchase (Customer)',
      'شراء خردة': 'Scrap Purchase',
      'شراء مستعمل': 'Used Purchase',
      'مرتجع بيع': 'Sales Return',
      'مرتجع بيع خردة': 'Scrap Sales Return',
      'مرتجع شراء': 'Purchase Return',
      'مرتجع شراء (مورد)': 'Supplier Return',
      'مرتجع شراء من عميل': 'Customer Return',
    };

    final tabTypes = tabIndex == 0
        ? salesTypes
        : tabIndex == 1
        ? customerPurchaseTypes
        : tabIndex == 2
        ? supplierPurchaseTypes
        : returnTypes;
    final existing = _invoices
        .map((inv) => (inv['invoice_type'] ?? '').toString().trim())
        .toSet();

    final items = <Map<String, String>>[
      {'value': 'all', 'label': isAr ? 'الكل' : 'All'},
    ];
    for (final t in tabTypes) {
      if (existing.contains(t) || existing.isEmpty) {
        items.add({'value': t, 'label': isAr ? t : (englishMap[t] ?? t)});
      }
    }
    return items;
  }

  Widget _buildInvoiceCard(Map<String, dynamic> invoice) {
    try {
      final isAr = widget.isArabic;
      final normalizedStatus = _normalizeStatus(
        (invoice['status'] ?? '').toString(),
      );
      final bool isPaid = normalizedStatus == 'paid';
      final bool isCancelled = normalizedStatus == 'cancelled';
      final theme = Theme.of(context);
      final colorScheme = theme.colorScheme;
      final textTheme = theme.textTheme;
      final statusColor = isCancelled
          ? colorScheme.onSurfaceVariant.withValues(alpha: 0.8)
          : (isPaid ? Colors.green : Colors.orange);
      final invoiceType = (invoice['invoice_type'] ?? '').toString();
      final bool isPurchase =
          invoiceType.contains('شراء') || invoiceType.toLowerCase() == 'buy';
      final Color typeColor = isPurchase ? Colors.blue : colorScheme.primary;
      final invoiceDisplayNumber = _getInvoiceDisplayNumber(invoice);

      final employeeName = _extractInvoiceEmployeeName(invoice);

      final karatLabel = _extractInvoiceKaratLabel(invoice);
      final goldTypeLabel = _extractInvoiceGoldTypeLabel(invoice);
      final totalWeight = _extractInvoiceTotalWeight(invoice);

      return Card(
        margin: const EdgeInsets.only(bottom: 12),
        color: theme.cardTheme.color ?? colorScheme.surface,
        shape:
            theme.cardTheme.shape ??
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: InkWell(
          onTap: () => _openInvoicePreview(invoice),
          borderRadius: BorderRadius.circular(16),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 6,
                      ),
                      decoration: BoxDecoration(
                        color: colorScheme.primary.withValues(alpha: 0.18),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        invoiceDisplayNumber,
                        style: textTheme.titleSmall?.copyWith(
                          color: colorScheme.primary,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 6,
                      ),
                      decoration: BoxDecoration(
                        color: typeColor.withValues(alpha: 0.18),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        invoiceType,
                        style: textTheme.bodySmall?.copyWith(
                          color: typeColor,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    const Spacer(),
                    IconButton(
                      tooltip: isAr ? 'طباعة' : 'Print',
                      icon: Icon(Icons.print, color: colorScheme.primary),
                      visualDensity: VisualDensity.compact,
                      onPressed: () =>
                          _viewInvoiceDetails(invoice, autoPrint: true),
                    ),
                    IconButton(
                      tooltip: isAr ? 'مشاركة PDF' : 'Share PDF',
                      icon: Icon(Icons.share, color: colorScheme.primary),
                      visualDensity: VisualDensity.compact,
                      onPressed: () =>
                          _viewInvoiceDetails(invoice, autoSharePdf: true),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 6,
                      ),
                      decoration: BoxDecoration(
                        color: statusColor.withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            isPaid ? Icons.check_circle : Icons.pending,
                            color: statusColor,
                            size: 16,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            _translateStatus(normalizedStatus, isAr),
                            style: textTheme.bodySmall?.copyWith(
                              color: statusColor,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),

                // Customer and Date
                Row(
                  children: [
                    Icon(
                      Icons.person,
                      color: colorScheme.onSurface.withValues(alpha: 0.7),
                      size: 18,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            (invoice['customer_name'] ??
                                        invoice['supplier_name'])
                                    ?.toString() ??
                                (isAr ? 'غير محدد' : 'N/A'),
                            style: textTheme.titleMedium?.copyWith(
                              color: colorScheme.onSurface,
                            ),
                          ),
                          if (employeeName != null) ...[
                            const SizedBox(height: 4),
                            Text(
                              isAr
                                  ? 'الموظف: $employeeName'
                                  : 'Employee: $employeeName',
                              style: textTheme.bodySmall?.copyWith(
                                color: colorScheme.onSurface.withValues(
                                  alpha: 0.7,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    Icon(
                      Icons.calendar_today,
                      color: colorScheme.onSurface.withValues(alpha: 0.7),
                      size: 16,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      _formatDate(invoice['date'], isAr),
                      style: textTheme.bodySmall?.copyWith(
                        color: colorScheme.onSurface.withValues(alpha: 0.7),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),

                // Gold tags (karat + total weight)
                if (karatLabel != null ||
                    goldTypeLabel != null ||
                    totalWeight > 0)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        if (goldTypeLabel != null)
                          _buildInfoChip(
                            label: isAr
                                ? 'النوع: $goldTypeLabel'
                                : 'Type: $goldTypeLabel',
                            colorScheme: colorScheme,
                          ),
                        if (karatLabel != null)
                          _buildInfoChip(
                            label: isAr
                                ? 'عيار: $karatLabel'
                                : 'Karat: $karatLabel',
                            colorScheme: colorScheme,
                          ),
                        if (totalWeight > 0)
                          _buildInfoChip(
                            label: isAr
                                ? 'وزن: ${NumberFormat('#,##0.###', isAr ? 'ar' : 'en').format(totalWeight)} جم'
                                : 'Weight: ${NumberFormat('#,##0.###', isAr ? 'ar' : 'en').format(totalWeight)} g',
                            colorScheme: colorScheme,
                          ),
                        if (isCancelled)
                          _buildInfoChip(
                            label: isAr ? 'ملغاة' : 'Cancelled',
                            colorScheme: colorScheme,
                          ),
                      ],
                    ),
                  ),

                // Amount
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: colorScheme.surfaceContainerHighest.withValues(
                      alpha: theme.brightness == Brightness.dark ? 0.35 : 0.8,
                    ),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        isAr ? 'الإجمالي:' : 'Total:',
                        style: textTheme.bodyMedium?.copyWith(
                          color: colorScheme.onSurface.withValues(alpha: 0.7),
                        ),
                      ),
                      Text(
                        '${NumberFormat('#,##0.00', isAr ? 'ar' : 'en').format(((invoice['total'] ?? 0) as num).toDouble())} ${isAr ? 'ريال' : 'SAR'}',
                        style: textTheme.titleLarge?.copyWith(
                          color: colorScheme.primary,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),

                // Actions
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () => _openInvoicePreview(invoice),
                        icon: const Icon(Icons.visibility, size: 18),
                        label: Text(isAr ? 'عرض' : 'View'),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: colorScheme.primary,
                          side: BorderSide(color: colorScheme.primary),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    // Edit content button — only for unposted invoices
                    if (invoice['is_posted'] != true && !isCancelled)
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: () => _editInvoiceContent(invoice),
                          icon: const Icon(Icons.edit, size: 18),
                          label: Text(isAr ? 'تعديل' : 'Edit'),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: Colors.orange.shade700,
                            side: BorderSide(color: Colors.orange.shade700),
                          ),
                        ),
                      ),
                    if (invoice['is_posted'] != true && !isCancelled)
                      const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: isCancelled
                            ? null
                            : () => _editInvoice(invoice),
                        icon: const Icon(Icons.sync_alt, size: 18),
                        label: Text(isAr ? 'تحديث الحالة' : 'Update Status'),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: Colors.blue,
                          side: const BorderSide(color: Colors.blue),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      onPressed: isCancelled
                          ? null
                          : () => _deleteInvoice(invoice),
                      icon: Icon(Icons.delete, color: colorScheme.error),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      );
    } catch (e, stackTrace) {
      debugPrint('❌ خطأ في بناء بطاقة الفاتورة: $e');
      debugPrint('Stack: $stackTrace');
      final invoiceDisplayNumber = _getInvoiceDisplayNumber(invoice);
      // Return simple error card
      return Card(
        margin: const EdgeInsets.only(bottom: 12),
        color: Colors.red.withValues(alpha: 0.15),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            'خطأ في عرض الفاتورة $invoiceDisplayNumber',
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: Colors.red),
          ),
        ),
      );
    }
  }

  String _formatDate(dynamic date, bool isAr) {
    try {
      if (date == null) return isAr ? 'غير محدد' : 'N/A';
      final dateTime = DateTime.parse(date.toString());
      return DateFormat('yyyy-MM-dd').format(dateTime);
    } catch (e) {
      return isAr ? 'غير محدد' : 'N/A';
    }
  }

  Widget _buildInfoChip({
    required String label,
    required ColorScheme colorScheme,
  }) {
    final theme = Theme.of(context);
    final textTheme = theme.textTheme;
    final bg = colorScheme.surfaceContainerHighest.withValues(
      alpha: theme.brightness == Brightness.dark ? 0.35 : 0.7,
    );

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: colorScheme.outline.withValues(alpha: 0.12)),
      ),
      child: Text(
        label,
        style: textTheme.bodySmall?.copyWith(
          color: colorScheme.onSurface,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    final isAr = widget.isArabic;
    final colorScheme = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.receipt_long,
            size: 80,
            color: colorScheme.onSurface.withValues(alpha: 0.2),
          ),
          const SizedBox(height: 16),
          Text(
            isAr ? 'لا توجد فواتير' : 'No Invoices',
            style: textTheme.titleMedium?.copyWith(
              color: colorScheme.onSurface.withValues(alpha: 0.7),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            isAr ? 'ابدأ بإضافة فاتورة جديدة' : 'Start by adding a new invoice',
            style: textTheme.bodySmall?.copyWith(
              color: colorScheme.onSurface.withValues(alpha: 0.5),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _viewInvoiceDetails(
    Map<String, dynamic> invoice, {
    bool autoPrint = false,
    bool autoSharePdf = false,
    bool autoDownloadPdf = false,
  }) async {
    final invoiceIdValue = invoice['id'];
    final invoiceId = invoiceIdValue is int
        ? invoiceIdValue
        : int.tryParse(invoiceIdValue?.toString() ?? '');

    if (invoiceId == null) {
      _showSnackBar(
        widget.isArabic ? 'معرف الفاتورة غير صالح' : 'Invalid invoice id',
        isError: true,
      );
      return;
    }

    var loaderVisible = true;
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => const Center(child: CircularProgressIndicator()),
    ).then((_) => loaderVisible = false);

    try {
      final details = await _apiService.getInvoiceById(invoiceId);
      if (!mounted) return;
      if (loaderVisible) {
        Navigator.of(context, rootNavigator: true).pop();
        loaderVisible = false;
      }

      final mergedInvoice = {...invoice, ...details};

      String filename() {
        final numStr = (mergedInvoice['invoice_type_id'] ?? '')
            .toString()
            .trim();
        final idStr = (mergedInvoice['id'] ?? '').toString().trim();
        final base = numStr.isNotEmpty
            ? 'invoice_$numStr'
            : (idStr.isNotEmpty ? 'invoice_$idStr' : 'invoice');
        return '$base.pdf';
      }

      final wantsShare = autoSharePdf || autoDownloadPdf;
      final wantsPrint = autoPrint || !wantsShare;

      if (wantsShare) {
        final bytes = await buildInvoicePdfBytes(
          context: context,
          invoice: mergedInvoice,
          format: PdfPageFormat.a4,
          isArabic: widget.isArabic,
        );
        await Printing.sharePdf(bytes: bytes, filename: filename());
      }

      if (wantsPrint) {
        await printInvoiceDirect(
          context: context,
          invoice: mergedInvoice,
          isArabic: widget.isArabic,
        );
      }
    } catch (e) {
      if (loaderVisible && mounted) {
        Navigator.of(context, rootNavigator: true).pop();
        loaderVisible = false;
      }
      if (mounted) {
        _showSnackBar(
          widget.isArabic
              ? 'فشل طباعة/تصدير الفاتورة: $e'
              : 'Failed to print/export invoice: $e',
          isError: true,
        );
      }
    }
  }

  Future<void> _openInvoicePreview(Map<String, dynamic> invoice) async {
    final invoiceIdValue = invoice['id'];
    final invoiceId = invoiceIdValue is int
        ? invoiceIdValue
        : int.tryParse(invoiceIdValue?.toString() ?? '');

    if (invoiceId == null) {
      _showSnackBar(
        widget.isArabic ? 'معرف الفاتورة غير صالح' : 'Invalid invoice id',
        isError: true,
      );
      return;
    }

    var loaderVisible = true;
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => const Center(child: CircularProgressIndicator()),
    ).then((_) => loaderVisible = false);

    try {
      final details = await _apiService.getInvoiceById(invoiceId);
      if (!mounted) return;
      if (loaderVisible) {
        Navigator.of(context, rootNavigator: true).pop();
        loaderVisible = false;
      }

      final mergedInvoice = {...invoice, ...details};
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        backgroundColor: Colors.transparent,
        builder: (sheetContext) {
          return _buildInvoicePreviewSheet(sheetContext, mergedInvoice);
        },
      );
    } catch (e) {
      if (loaderVisible && mounted) {
        Navigator.of(context, rootNavigator: true).pop();
        loaderVisible = false;
      }
      if (mounted) {
        _showSnackBar(
          widget.isArabic
              ? 'فشل تحميل تفاصيل الفاتورة: $e'
              : 'Failed to load invoice details: $e',
          isError: true,
        );
      }
    }
  }

  Widget _buildInvoicePreviewSheet(
    BuildContext sheetContext,
    Map<String, dynamic> invoice,
  ) {
    final isAr = widget.isArabic;
    final theme = Theme.of(sheetContext);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;

    final normalizedStatus = _normalizeStatus(
      (invoice['status'] ?? '').toString(),
    );
    final isCancelled = normalizedStatus == 'cancelled';

    final total = _tryParseDouble(invoice['total']);
    final tax = _tryParseDouble(invoice['total_tax']);
    final subtotal = (total - tax).clamp(0.0, double.infinity);

    final paidCash = _tryParseDouble(
      invoice['amount_paid'] ?? invoice['total_payments_amount'],
    );
    final barterTotal = _tryParseDouble(invoice['barter_total']);
    final hasTotalSettledKey = invoice.containsKey('total_settled_amount');
    final totalSettled = hasTotalSettledKey
        ? _tryParseDouble(invoice['total_settled_amount'])
        : (paidCash + barterTotal);
    final paid = totalSettled;
    final remaining = (total - totalSettled).clamp(0.0, double.infinity);
    final canSettle = !isCancelled && remaining > 0.01;

    final invoiceNumber = _getInvoiceDisplayNumber(invoice);
    final customerName =
        invoice['customer_name']?.toString() ?? (isAr ? 'غير محدد' : 'N/A');
    final invoiceType = (invoice['invoice_type'] ?? '').toString();

    final items = (invoice['items'] is List)
        ? (invoice['items'] as List)
        : const [];

    final payments = (invoice['payments'] is List)
        ? (invoice['payments'] as List)
        : const [];

    final auth = Provider.of<AuthProvider>(sheetContext, listen: false);
    final canSeeLogs = auth.isManager;

    final invoiceDate = _tryParseDateTime(invoice['date']);
    final minutesSince = invoiceDate == null
        ? null
        : DateTime.now().difference(invoiceDate).inMinutes;
    const editWindowMinutes = 15;
    final withinEditWindow =
        minutesSince != null && minutesSince <= editWindowMinutes;
    final canDirectEdit = auth.isManager || withinEditWindow;

    final returnType = _returnTypeForInvoice(invoiceType);
    final canReturn = returnType != null;

    return DraggableScrollableSheet(
      initialChildSize: 0.92,
      minChildSize: 0.5,
      maxChildSize: 0.98,
      builder: (context, scrollController) {
        return Container(
          decoration: BoxDecoration(
            color: theme.scaffoldBackgroundColor,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: Column(
            children: [
              const SizedBox(height: 10),
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: colorScheme.onSurface.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(height: 10),

              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            invoiceNumber,
                            style: textTheme.titleLarge?.copyWith(
                              color: colorScheme.primary,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '$invoiceType • $customerName',
                            style: textTheme.bodyMedium?.copyWith(
                              color: colorScheme.onSurface.withValues(
                                alpha: 0.75,
                              ),
                              fontWeight: FontWeight.w600,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.of(sheetContext).pop(),
                      icon: const Icon(Icons.close),
                      tooltip: isAr ? 'إغلاق' : 'Close',
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 8),

              // Action bar
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () {
                          Navigator.of(sheetContext).pop();
                          _viewInvoiceDetails(invoice, autoPrint: true);
                        },
                        icon: const Icon(Icons.print, size: 18),
                        label: Text(isAr ? 'طباعة' : 'Print'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () {
                          Navigator.of(sheetContext).pop();
                          _viewInvoiceDetails(invoice, autoDownloadPdf: true);
                        },
                        icon: const Icon(Icons.download, size: 18),
                        label: Text(isAr ? 'تحميل PDF' : 'Download PDF'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () {
                          Navigator.of(sheetContext).pop();
                          _viewInvoiceDetails(invoice, autoSharePdf: true);
                        },
                        icon: const Icon(Icons.share, size: 18),
                        label: Text(isAr ? 'واتساب' : 'WhatsApp'),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              Expanded(
                child: ListView(
                  controller: scrollController,
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                  children: [
                    // Status + date
                    Row(
                      children: [
                        _buildInfoChip(
                          label: isAr
                              ? 'الحالة: ${_translateStatus(normalizedStatus, isAr)}'
                              : 'Status: ${_translateStatus(normalizedStatus, isAr)}',
                          colorScheme: colorScheme,
                        ),
                        const SizedBox(width: 8),
                        _buildInfoChip(
                          label: isAr
                              ? 'التاريخ: ${_formatDate(invoice['date'], isAr)}'
                              : 'Date: ${_formatDate(invoice['date'], isAr)}',
                          colorScheme: colorScheme,
                        ),
                      ],
                    ),

                    const SizedBox(height: 12),

                    // Items table preview
                    Text(
                      isAr ? 'الأصناف' : 'Items',
                      style: textTheme.titleMedium?.copyWith(
                        color: colorScheme.primary,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),

                    if (items.isEmpty)
                      Text(
                        isAr ? 'لا توجد أصناف' : 'No items',
                        style: textTheme.bodyMedium?.copyWith(
                          color: colorScheme.onSurface.withValues(alpha: 0.7),
                        ),
                      )
                    else
                      ...items.map((raw) {
                        final item = raw is Map
                            ? raw.map((k, v) => MapEntry(k.toString(), v))
                            : <String, dynamic>{};

                        final name = (item['name'] ?? '').toString();
                        final qty = _tryParseInt(item['quantity']) ?? 1;
                        final weight = _tryParseDouble(item['weight']);
                        final karat = item['karat']?.toString();
                        final wage = _tryParseDouble(item['wage']);
                        final itemTax = _tryParseDouble(item['tax']);
                        final itemTotal = _tryParseDouble(
                          item['price'] ?? item['total'],
                        );

                        return Card(
                          margin: const EdgeInsets.only(bottom: 8),
                          elevation: 0,
                          color: colorScheme.surfaceContainerHighest.withValues(
                            alpha: theme.brightness == Brightness.dark
                                ? 0.35
                                : 0.6,
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  name.isNotEmpty
                                      ? name
                                      : (isAr ? 'صنف' : 'Item'),
                                  style: textTheme.bodyLarge?.copyWith(
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                Wrap(
                                  spacing: 8,
                                  runSpacing: 8,
                                  children: [
                                    _buildInfoChip(
                                      label: isAr
                                          ? 'الكمية: $qty'
                                          : 'Qty: $qty',
                                      colorScheme: colorScheme,
                                    ),
                                    if (karat != null &&
                                        karat.trim().isNotEmpty)
                                      _buildInfoChip(
                                        label: isAr
                                            ? 'عيار: $karat'
                                            : 'Karat: $karat',
                                        colorScheme: colorScheme,
                                      ),
                                    if (weight > 0)
                                      _buildInfoChip(
                                        label: isAr
                                            ? 'وزن: ${NumberFormat('#,##0.###', isAr ? 'ar' : 'en').format(weight)} جم'
                                            : 'Weight: ${NumberFormat('#,##0.###', isAr ? 'ar' : 'en').format(weight)} g',
                                        colorScheme: colorScheme,
                                      ),
                                    if (wage > 0)
                                      _buildInfoChip(
                                        label: isAr
                                            ? 'أجور: ${NumberFormat('#,##0.00', isAr ? 'ar' : 'en').format(wage)}'
                                            : 'Wage: ${NumberFormat('#,##0.00', isAr ? 'ar' : 'en').format(wage)}',
                                        colorScheme: colorScheme,
                                      ),
                                    if (itemTax > 0)
                                      _buildInfoChip(
                                        label: isAr
                                            ? 'ضريبة: ${NumberFormat('#,##0.00', isAr ? 'ar' : 'en').format(itemTax)}'
                                            : 'Tax: ${NumberFormat('#,##0.00', isAr ? 'ar' : 'en').format(itemTax)}',
                                        colorScheme: colorScheme,
                                      ),
                                    if (itemTotal > 0)
                                      _buildInfoChip(
                                        label: isAr
                                            ? 'الإجمالي: ${NumberFormat('#,##0.00', isAr ? 'ar' : 'en').format(itemTotal)}'
                                            : 'Total: ${NumberFormat('#,##0.00', isAr ? 'ar' : 'en').format(itemTotal)}',
                                        colorScheme: colorScheme,
                                      ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        );
                      }),

                    const SizedBox(height: 12),

                    // Summary
                    Text(
                      isAr ? 'الملخص المالي' : 'Summary',
                      style: textTheme.titleMedium?.copyWith(
                        color: colorScheme.primary,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Card(
                      elevation: 0,
                      color: colorScheme.surfaceContainerHighest.withValues(
                        alpha: theme.brightness == Brightness.dark ? 0.35 : 0.6,
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          children: [
                            _buildSummaryRow(
                              label: isAr ? 'قبل الضريبة' : 'Subtotal',
                              value: subtotal,
                              isAr: isAr,
                              colorScheme: colorScheme,
                            ),
                            const SizedBox(height: 8),
                            _buildSummaryRow(
                              label: isAr ? 'الضريبة' : 'VAT',
                              value: tax,
                              isAr: isAr,
                              colorScheme: colorScheme,
                            ),
                            const Divider(height: 18),
                            _buildSummaryRow(
                              label: isAr ? 'الإجمالي' : 'Total',
                              value: total,
                              isAr: isAr,
                              colorScheme: colorScheme,
                              emphasize: true,
                            ),
                            const SizedBox(height: 8),
                            _buildSummaryRow(
                              label: isAr ? 'المدفوع' : 'Paid',
                              value: paid,
                              isAr: isAr,
                              colorScheme: colorScheme,
                            ),
                            if (barterTotal > 0.01) ...[
                              const SizedBox(height: 8),
                              _buildSummaryRow(
                                label: isAr
                                    ? 'المقايضة (قيمة)'
                                    : 'Barter (Value)',
                                value: barterTotal,
                                isAr: isAr,
                                colorScheme: colorScheme,
                              ),
                            ],
                            const SizedBox(height: 8),
                            _buildSummaryRow(
                              label: isAr ? 'المتبقي' : 'Remaining',
                              value: remaining,
                              isAr: isAr,
                              colorScheme: colorScheme,
                            ),
                          ],
                        ),
                      ),
                    ),

                    if (payments.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      Text(
                        isAr ? 'الدفعات' : 'Payments',
                        style: textTheme.titleMedium?.copyWith(
                          color: colorScheme.primary,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Card(
                        elevation: 0,
                        color: colorScheme.surfaceContainerHighest.withValues(
                          alpha: theme.brightness == Brightness.dark
                              ? 0.35
                              : 0.6,
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            children: payments.map<Widget>((raw) {
                              final Map<String, dynamic> payment = raw is Map
                                  ? raw.map((k, v) => MapEntry(k.toString(), v))
                                  : <String, dynamic>{};

                              final paymentId = _tryParseInt(payment['id']);
                              final amount = _tryParseDouble(payment['amount']);
                              final methodName =
                                  (payment['payment_method_name'] ?? '')
                                      .toString();
                              final createdAt = (payment['created_at'] ?? '')
                                  .toString();
                              final notes = (payment['notes'] ?? '')
                                  .toString()
                                  .trim();

                              return Padding(
                                padding: const EdgeInsets.only(bottom: 10),
                                child: Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Row(
                                            children: [
                                              Icon(
                                                Icons.payments_outlined,
                                                size: 18,
                                                color: colorScheme.primary,
                                              ),
                                              const SizedBox(width: 8),
                                              Expanded(
                                                child: Text(
                                                  methodName.isNotEmpty
                                                      ? methodName
                                                      : (isAr
                                                            ? 'وسيلة دفع'
                                                            : 'Payment method'),
                                                  style: textTheme.bodyMedium
                                                      ?.copyWith(
                                                        fontWeight:
                                                            FontWeight.w800,
                                                      ),
                                                  overflow:
                                                      TextOverflow.ellipsis,
                                                ),
                                              ),
                                              Text(
                                                NumberFormat(
                                                  '#,##0.00',
                                                  isAr ? 'ar' : 'en',
                                                ).format(amount),
                                                style: textTheme.bodyMedium
                                                    ?.copyWith(
                                                      fontWeight:
                                                          FontWeight.w800,
                                                      color:
                                                          colorScheme.primary,
                                                    ),
                                              ),
                                            ],
                                          ),
                                          if (createdAt.isNotEmpty) ...[
                                            const SizedBox(height: 4),
                                            Text(
                                              isAr
                                                  ? 'تاريخ: ${_formatDate(createdAt, isAr)}'
                                                  : 'Date: ${_formatDate(createdAt, isAr)}',
                                              style: textTheme.bodySmall
                                                  ?.copyWith(
                                                    color: colorScheme.onSurface
                                                        .withValues(alpha: 0.7),
                                                    fontWeight: FontWeight.w600,
                                                  ),
                                            ),
                                          ],
                                          if (notes.isNotEmpty) ...[
                                            const SizedBox(height: 4),
                                            Text(
                                              notes,
                                              style: textTheme.bodySmall
                                                  ?.copyWith(
                                                    color: colorScheme.onSurface
                                                        .withValues(alpha: 0.7),
                                                    fontStyle: FontStyle.italic,
                                                  ),
                                              maxLines: 2,
                                              overflow: TextOverflow.ellipsis,
                                            ),
                                          ],
                                        ],
                                      ),
                                    ),
                                    const SizedBox(width: 10),
                                    IconButton(
                                      onPressed: paymentId == null
                                          ? null
                                          : () => _openLinkedVoucherForPayment(
                                              sheetContext: sheetContext,
                                              invoice: invoice,
                                              invoicePaymentId: paymentId,
                                            ),
                                      tooltip: isAr
                                          ? 'عرض السند المرتبط'
                                          : 'View linked voucher',
                                      icon: Icon(
                                        Icons.receipt_long,
                                        color: colorScheme.primary,
                                      ),
                                    ),
                                  ],
                                ),
                              );
                            }).toList(),
                          ),
                        ),
                      ),
                    ],

                    if (canSettle) ...[
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton.icon(
                          onPressed: () async {
                            final didPay = await _showSettleRemainingDialog(
                              sheetContext: sheetContext,
                              invoice: invoice,
                              remaining: remaining,
                            );
                            if (didPay == true && mounted) {
                              Navigator.of(sheetContext).pop();
                              await _loadInvoices();
                            }
                          },
                          icon: const Icon(Icons.payments),
                          label: Text(isAr ? 'سداد متبقي' : 'Settle Remaining'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: colorScheme.primary,
                            foregroundColor: colorScheme.onPrimary,
                          ),
                        ),
                      ),
                    ],

                    if (canReturn) ...[
                      const SizedBox(height: 12),
                      Card(
                        elevation: 0,
                        color: colorScheme.surfaceContainerHighest.withValues(
                          alpha: theme.brightness == Brightness.dark
                              ? 0.35
                              : 0.6,
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                isAr ? 'التعديل الآمن' : 'Safe Editing',
                                style: textTheme.titleSmall?.copyWith(
                                  fontWeight: FontWeight.w800,
                                  color: colorScheme.primary,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                canDirectEdit
                                    ? (isAr
                                          ? 'يفضل استخدام المرتجع بدلاً من تعديل الفاتورة الأصلية للحفاظ على دقة المخزون والحسابات.'
                                          : 'Prefer using returns instead of editing the original invoice to preserve inventory/accounting integrity.')
                                    : (isAr
                                          ? 'انتهت مدة التعديل ($editWindowMinutes دقيقة). يلزم صلاحية مدير أو استخدم مرتجع.'
                                          : 'Edit window expired ($editWindowMinutes min). Manager permission required or use a return.'),
                                style: textTheme.bodySmall?.copyWith(
                                  color: colorScheme.onSurface.withValues(
                                    alpha: 0.75,
                                  ),
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: 10),
                              SizedBox(
                                width: double.infinity,
                                child: OutlinedButton.icon(
                                  onPressed: () {
                                    Navigator.of(sheetContext).pop();
                                    _openReturnForInvoice(invoice, returnType);
                                  },
                                  icon: const Icon(Icons.keyboard_return),
                                  label: Text(
                                    isAr ? 'إنشاء مرتجع' : 'Create Return',
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],

                    if (canSeeLogs) ...[
                      const SizedBox(height: 16),
                      Text(
                        isAr ? 'سجل الأحداث' : 'Logs',
                        style: textTheme.titleMedium?.copyWith(
                          color: colorScheme.primary,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Card(
                        elevation: 0,
                        color: colorScheme.surfaceContainerHighest.withValues(
                          alpha: theme.brightness == Brightness.dark
                              ? 0.35
                              : 0.6,
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'ID: ${invoice['id'] ?? '-'}',
                                style: textTheme.bodyMedium,
                              ),
                              const SizedBox(height: 6),
                              Text(
                                isAr
                                    ? 'ترحيل: ${invoice['is_posted'] == true ? 'نعم' : 'لا'}'
                                    : 'Posted: ${invoice['is_posted'] == true ? 'Yes' : 'No'}',
                                style: textTheme.bodyMedium,
                              ),
                              const SizedBox(height: 6),
                              if ((invoice['posted_at'] ?? '')
                                  .toString()
                                  .isNotEmpty)
                                Text(
                                  isAr
                                      ? 'تاريخ الترحيل: ${invoice['posted_at']}'
                                      : 'Posted at: ${invoice['posted_at']}',
                                  style: textTheme.bodySmall?.copyWith(
                                    color: colorScheme.onSurface.withValues(
                                      alpha: 0.75,
                                    ),
                                  ),
                                ),
                              if ((invoice['posted_by'] ?? '')
                                  .toString()
                                  .isNotEmpty)
                                Text(
                                  isAr
                                      ? 'مرحل بواسطة: ${invoice['posted_by']}'
                                      : 'Posted by: ${invoice['posted_by']}',
                                  style: textTheme.bodySmall?.copyWith(
                                    color: colorScheme.onSurface.withValues(
                                      alpha: 0.75,
                                    ),
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Future<void> _openLinkedVoucherForPayment({
    required BuildContext sheetContext,
    required Map<String, dynamic> invoice,
    required int invoicePaymentId,
  }) async {
    final isAr = widget.isArabic;

    final invoiceIdValue = invoice['id'];
    final invoiceId = invoiceIdValue is int
        ? invoiceIdValue
        : int.tryParse(invoiceIdValue?.toString() ?? '');
    if (invoiceId == null) {
      _showSnackBar(
        isAr ? 'معرف الفاتورة غير صالح' : 'Invalid invoice id',
        isError: true,
      );
      return;
    }

    var loaderVisible = true;
    showDialog(
      context: sheetContext,
      barrierDismissible: false,
      builder: (_) => const Center(child: CircularProgressIndicator()),
    ).then((_) => loaderVisible = false);

    try {
      final vouchers = await _apiService.getVouchersForInvoice(
        invoiceId,
        perPage: 100,
      );

      int? linkedVoucherId;
      for (final v in vouchers) {
        final notesRaw = (v['notes'] ?? '').toString().trim();
        if (!notesRaw.startsWith('{')) continue;
        try {
          final parsed = json.decode(notesRaw);
          if (parsed is Map) {
            final pid = parsed['invoice_payment_id'];
            final parsedPid = pid is int
                ? pid
                : int.tryParse(pid?.toString() ?? '');
            if (parsedPid == invoicePaymentId) {
              final vid = v['id'];
              linkedVoucherId = vid is int
                  ? vid
                  : int.tryParse(vid?.toString() ?? '');
              if (linkedVoucherId != null) break;
            }
          }
        } catch (_) {
          // ignore
        }
      }

      // Fallback: open latest linked voucher for this invoice
      linkedVoucherId ??= (() {
        if (vouchers.isEmpty) return null;
        final vid = vouchers.first['id'];
        return vid is int ? vid : int.tryParse(vid?.toString() ?? '');
      })();

      if (loaderVisible && mounted) {
        Navigator.of(sheetContext, rootNavigator: true).pop();
        loaderVisible = false;
      }

      if (linkedVoucherId == null) {
        _showSnackBar(
          isAr ? 'لا يوجد سند مرتبط بهذه الدفعة' : 'No linked voucher found',
          isError: true,
        );
        return;
      }

      if (!mounted) return;
      await showVoucherDetailsSheet(context, voucherId: linkedVoucherId);
    } catch (e) {
      if (loaderVisible && mounted) {
        Navigator.of(sheetContext, rootNavigator: true).pop();
        loaderVisible = false;
      }
      if (mounted) {
        _showSnackBar(
          isAr ? 'فشل فتح السند: $e' : 'Failed to open voucher: $e',
          isError: true,
        );
      }
    }
  }

  DateTime? _tryParseDateTime(dynamic value) {
    if (value == null) return null;
    try {
      return DateTime.parse(value.toString());
    } catch (_) {
      return null;
    }
  }

  String? _returnTypeForInvoice(String invoiceType) {
    final t = invoiceType.trim();
    if (t.isEmpty) return null;
    if (t.contains('مرتجع')) return null;
    if (t == 'بيع' || t.toLowerCase() == 'sell') return 'مرتجع بيع';
    if (t == 'شراء من عميل') return 'مرتجع شراء';
    if (t == 'شراء') return 'مرتجع شراء (مورد)';
    return null;
  }

  Future<void> _openReturnForInvoice(
    Map<String, dynamic> invoice,
    String returnType,
  ) async {
    if (!mounted) return;

    final result = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => AddReturnInvoiceScreen(
          api: _apiService,
          returnType: returnType,
          prefilledOriginalInvoice: invoice,
        ),
      ),
    );

    if (result == true && mounted) {
      await _loadInvoices();
    }
  }

  Widget _buildSummaryRow({
    required String label,
    required double value,
    required bool isAr,
    required ColorScheme colorScheme,
    bool emphasize = false,
  }) {
    final theme = Theme.of(context);
    final textTheme = theme.textTheme;
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          label,
          style: textTheme.bodyMedium?.copyWith(
            color: colorScheme.onSurface.withValues(alpha: 0.75),
            fontWeight: emphasize ? FontWeight.bold : FontWeight.w600,
          ),
        ),
        Text(
          NumberFormat('#,##0.00', isAr ? 'ar' : 'en').format(value),
          style: textTheme.bodyLarge?.copyWith(
            color: emphasize ? colorScheme.primary : colorScheme.onSurface,
            fontWeight: emphasize ? FontWeight.bold : FontWeight.w700,
          ),
        ),
      ],
    );
  }

  Future<bool?> _showSettleRemainingDialog({
    required BuildContext sheetContext,
    required Map<String, dynamic> invoice,
    required double remaining,
  }) async {
    final isAr = widget.isArabic;
    final theme = Theme.of(sheetContext);
    final colorScheme = theme.colorScheme;

    final invoiceIdValue = invoice['id'];
    final invoiceId = invoiceIdValue is int
        ? invoiceIdValue
        : int.tryParse(invoiceIdValue?.toString() ?? '');
    if (invoiceId == null) {
      _showSnackBar(
        isAr ? 'معرف الفاتورة غير صالح' : 'Invalid invoice id',
        isError: true,
      );
      return false;
    }

    final methodsRaw = await _apiService.getActivePaymentMethods();
    final methods = methodsRaw
        .whereType<Map>()
        .map((m) => Map<String, dynamic>.from(m))
        .toList();

    int? selectedMethodId;
    if (methods.isNotEmpty) {
      selectedMethodId = _tryParseInt(methods.first['id']);
    }

    final amountController = TextEditingController(
      text: remaining.toStringAsFixed(2),
    );
    final notesController = TextEditingController();

    return showDialog<bool>(
      context: sheetContext,
      builder: (ctx) {
        return AlertDialog(
          title: Text(isAr ? 'سداد متبقي' : 'Settle Remaining'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  isAr
                      ? 'المتبقي: ${remaining.toStringAsFixed(2)}'
                      : 'Remaining: ${remaining.toStringAsFixed(2)}',
                  style: Theme.of(ctx).textTheme.bodyMedium,
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<int>(
                  initialValue: selectedMethodId,
                  decoration: InputDecoration(
                    labelText: isAr ? 'وسيلة الدفع' : 'Payment Method',
                  ),
                  items: methods
                      .map((m) {
                        final id = _tryParseInt(m['id']);
                        final name = (m['name'] ?? '').toString();
                        if (id == null) return null;
                        return DropdownMenuItem<int>(
                          value: id,
                          child: Text(name.isNotEmpty ? name : id.toString()),
                        );
                      })
                      .whereType<DropdownMenuItem<int>>()
                      .toList(),
                  onChanged: (v) => selectedMethodId = v,
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: amountController,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: InputDecoration(
                    labelText: isAr ? 'المبلغ' : 'Amount',
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: notesController,
                  decoration: InputDecoration(
                    labelText: isAr ? 'ملاحظات (اختياري)' : 'Notes (optional)',
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: Text(isAr ? 'إلغاء' : 'Cancel'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: colorScheme.primary,
                foregroundColor: colorScheme.onPrimary,
              ),
              onPressed: () async {
                if (selectedMethodId == null) {
                  Navigator.of(ctx).pop(false);
                  _showSnackBar(
                    isAr ? 'اختر وسيلة دفع' : 'Select a payment method',
                    isError: true,
                  );
                  return;
                }
                final amount =
                    double.tryParse(amountController.text.trim()) ?? 0.0;
                if (amount <= 0) {
                  _showSnackBar(
                    isAr ? 'أدخل مبلغاً صحيحاً' : 'Enter a valid amount',
                    isError: true,
                  );
                  return;
                }
                if (amount > remaining + 0.01) {
                  _showSnackBar(
                    isAr
                        ? 'المبلغ أكبر من المتبقي'
                        : 'Amount exceeds remaining',
                    isError: true,
                  );
                  return;
                }
                try {
                  await _apiService.addInvoicePayment(
                    invoiceId: invoiceId,
                    paymentMethodId: selectedMethodId!,
                    amount: amount,
                    notes: notesController.text,
                  );
                  if (!mounted) return;
                  _showSnackBar(
                    isAr ? 'تم تسجيل الدفعة' : 'Payment recorded',
                    isError: false,
                  );
                  Navigator.of(ctx).pop(true);
                } catch (e) {
                  _showSnackBar(
                    isAr
                        ? 'فشل تسجيل الدفعة: $e'
                        : 'Failed to record payment: $e',
                    isError: true,
                  );
                }
              },
              child: Text(isAr ? 'تأكيد' : 'Confirm'),
            ),
          ],
        );
      },
    );
  }

  /// Open the sales invoice screen in **edit mode** for an unposted invoice.
  Future<void> _editInvoiceContent(Map<String, dynamic> invoice) async {
    final isAr = widget.isArabic;
    final invoiceIdValue = invoice['id'];
    final invoiceId = invoiceIdValue is int
        ? invoiceIdValue
        : int.tryParse(invoiceIdValue?.toString() ?? '');

    if (invoiceId == null) {
      _showSnackBar(
        isAr ? 'معرف الفاتورة غير صالح' : 'Invalid invoice id',
        isError: true,
      );
      return;
    }

    if (invoice['is_posted'] == true) {
      _showSnackBar(
        isAr ? 'لا يمكن تعديل فاتورة مرحّلة' : 'Cannot edit a posted invoice',
        isError: true,
      );
      return;
    }

    // Fetch full invoice data from backend
    try {
      final fullInvoice = await _apiService.getInvoiceById(invoiceId);

      if (!mounted) return;

      // Navigate to SalesInvoiceScreenV2 in edit mode
      final items = _cloneDataList(await _getCachedItems());
      final saleItems = _filterSaleReadyItems(items);
      final customers = _cloneDataList(await _getCachedCustomers());

      final result = await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => SalesInvoiceScreenV2(
            items: saleItems,
            customers: customers,
            editInvoiceId: invoiceId,
            editInvoiceData: fullInvoice,
          ),
        ),
      );

      if (result == true && mounted) {
        await _loadInvoices();
      }
    } catch (e) {
      if (mounted) {
        _showSnackBar(
          isAr
              ? 'فشل تحميل بيانات الفاتورة: $e'
              : 'Failed to load invoice data: $e',
          isError: true,
        );
      }
    }
  }

  Future<void> _editInvoice(Map<String, dynamic> invoice) async {
    final invoiceIdValue = invoice['id'];
    final invoiceId = invoiceIdValue is int
        ? invoiceIdValue
        : int.tryParse(invoiceIdValue?.toString() ?? '');

    if (invoiceId == null) {
      _showSnackBar(
        widget.isArabic ? 'معرف الفاتورة غير صالح' : 'Invalid invoice id',
        isError: true,
      );
      return;
    }

    final currentStatus = _normalizeStatus(
      (invoice['status'] ?? '').toString(),
    );
    final selectedStatus = await _showStatusUpdateSheet(currentStatus);

    if (selectedStatus == null || selectedStatus == currentStatus) {
      return;
    }

    try {
      await _apiService.updateInvoiceStatus(invoiceId, selectedStatus);
      if (!mounted) return;
      _showSnackBar(
        widget.isArabic ? 'تم تحديث حالة الفاتورة' : 'Invoice status updated',
        isError: false,
      );
      await _loadInvoices();
    } catch (e) {
      if (mounted) {
        _showSnackBar(
          widget.isArabic
              ? 'فشل تحديث الحالة: $e'
              : 'Failed to update status: $e',
          isError: true,
        );
      }
    }
  }

  Future<void> _deleteInvoice(Map<String, dynamic> invoice) async {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final invoiceDisplayNumber = _getInvoiceDisplayNumber(invoice);

    // Show confirmation dialog
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Row(
          children: [
            Icon(Icons.warning_amber_rounded, color: Colors.orange),
            const SizedBox(width: 8),
            Text(
              isAr ? 'تأكيد الحذف' : 'Confirm Delete',
              style: theme.textTheme.titleMedium?.copyWith(
                color: colorScheme.primary,
              ),
            ),
          ],
        ),
        content: Text(
          isAr
              ? 'هل أنت متأكد من حذف الفاتورة رقم $invoiceDisplayNumber؟'
              : 'Are you sure you want to delete invoice $invoiceDisplayNumber?',
          style: theme.textTheme.bodyMedium,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(
              isAr ? 'إلغاء' : 'Cancel',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: colorScheme.onSurface.withValues(alpha: 0.7),
              ),
            ),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
            child: Text(isAr ? 'حذف' : 'Delete'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      try {
        final invoiceIdValue = invoice['id'];
        final invoiceId = invoiceIdValue is int
            ? invoiceIdValue
            : int.tryParse(invoiceIdValue?.toString() ?? '');

        if (invoiceId == null) {
          _showSnackBar(
            isAr ? 'معرف الفاتورة غير صالح' : 'Invalid invoice id',
            isError: true,
          );
          return;
        }

        await _apiService.deleteInvoice(invoiceId);
        _showSnackBar(
          isAr ? 'تم حذف الفاتورة بنجاح' : 'Invoice deleted successfully',
          isError: false,
        );
        await _loadInvoices();
      } catch (e) {
        _showSnackBar(
          isAr
              ? 'فشل حذف الفاتورة: ${e.toString()}'
              : 'Failed to delete: ${e.toString()}',
          isError: true,
        );
      }
    }
  }

  Future<void> _navigateToAddInvoice() async {
    final isAr = widget.isArabic;
    final selection = await showModalBottomSheet<_InvoiceCreationTarget>(
      context: context,
      builder: (sheetContext) {
        final options = [
          {
            'target': _InvoiceCreationTarget.sales,
            'icon': Icons.point_of_sale,
            'color': Colors.green,
            'title': isAr ? 'فاتورة بيع' : 'Sales Invoice',
            'subtitle': isAr
                ? 'بيع ذهب جديد أو مستعمل'
                : 'Sell new or used gold',
          },
          {
            'target': _InvoiceCreationTarget.scrapSale,
            'icon': Icons.recycling,
            'color': Colors.orange,
            'title': isAr ? 'بيع ذهب كسر' : 'Scrap Gold Sale',
            'subtitle': isAr
                ? 'تصفية الذهب المستعمل'
                : 'Liquidate scrap inventory',
          },
          {
            'target': _InvoiceCreationTarget.scrapPurchase,
            'icon': Icons.shopping_basket,
            'color': Colors.blue,
            'title': isAr ? 'شراء كسر من عميل' : 'Buy Scrap from Customer',
            'subtitle': isAr
                ? 'استلام ذهب من عملاء'
                : 'Accept client scrap gold',
          },
          {
            'target': _InvoiceCreationTarget.supplierPurchase,
            'icon': Icons.business_center,
            'color': Colors.purple,
            'title': isAr ? 'شراء' : 'Supplier Purchase',
            'subtitle': isAr ? 'توريدات من التجار' : 'Bulk supplier orders',
          },
          {
            'target': _InvoiceCreationTarget.salesReturn,
            'icon': Icons.keyboard_return,
            'color': Colors.red.shade300,
            'title': isAr ? 'مرتجع بيع' : 'Sales Return',
            'subtitle': isAr ? 'استرجاع مبيعات' : 'Return sold items',
          },
          {
            'target': _InvoiceCreationTarget.scrapReturn,
            'icon': Icons.undo,
            'color': Colors.deepOrange.shade300,
            'title': isAr ? 'مرتجع شراء كسر' : 'Scrap Purchase Return',
            'subtitle': isAr ? 'إرجاع مشتريات الكسر' : 'Return scrap purchases',
          },
          {
            'target': _InvoiceCreationTarget.supplierReturn,
            'icon': Icons.assignment_return,
            'color': Colors.teal,
            'title': isAr ? 'مرتجع شراء (مورد)' : 'Supplier Purchase Return',
            'subtitle': isAr ? 'إرجاع مورد' : 'Supplier returns',
          },
        ];

        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  isAr ? 'اختر نوع الفاتورة' : 'Choose invoice type',
                  style: Theme.of(sheetContext).textTheme.titleMedium,
                ),
                const SizedBox(height: 12),
                for (final option in options)
                  Card(
                    margin: const EdgeInsets.symmetric(vertical: 6),
                    child: ListTile(
                      leading: CircleAvatar(
                        backgroundColor: (option['color'] as Color).withValues(
                          alpha: 0.15,
                        ),
                        child: Icon(
                          option['icon'] as IconData,
                          color: option['color'] as Color,
                        ),
                      ),
                      title: Text(option['title'] as String),
                      subtitle: Text(option['subtitle'] as String),
                      onTap: () => Navigator.pop(
                        sheetContext,
                        option['target'] as _InvoiceCreationTarget,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );

    if (selection != null) {
      await _openInvoiceCreation(selection);
    }
  }

  Future<void> _openInvoiceCreation(_InvoiceCreationTarget target) async {
    switch (target) {
      case _InvoiceCreationTarget.sales:
        final items = _cloneDataList(await _getCachedItems());
        final saleItems = _filterSaleReadyItems(items);
        final customers = _cloneDataList(await _getCachedCustomers());
        if (!mounted) return;
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) =>
                SalesInvoiceScreenV2(items: saleItems, customers: customers),
          ),
        );
        break;
      case _InvoiceCreationTarget.scrapSale:
        final customers = _cloneDataList(await _getCachedCustomers());
        final items = _cloneDataList(await _getCachedItems());
        if (!mounted) return;
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) =>
                ScrapSalesInvoiceScreen(customers: customers, items: items),
          ),
        );
        break;
      case _InvoiceCreationTarget.scrapPurchase:
        final customers = _cloneDataList(await _getCachedCustomers());
        if (!mounted) return;
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => ScrapPurchaseInvoiceScreen(customers: customers),
          ),
        );
        break;
      case _InvoiceCreationTarget.supplierPurchase:
        if (!mounted) return;
        await Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const PurchaseInvoiceScreen()),
        );
        break;
      case _InvoiceCreationTarget.salesReturn:
        if (!mounted) return;
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => AddReturnInvoiceScreen(
              api: _apiService,
              returnType: 'مرتجع بيع',
            ),
          ),
        );
        break;
      case _InvoiceCreationTarget.scrapReturn:
        if (!mounted) return;
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => AddReturnInvoiceScreen(
              api: _apiService,
              returnType: 'مرتجع شراء',
            ),
          ),
        );
        break;
      case _InvoiceCreationTarget.supplierReturn:
        if (!mounted) return;
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) =>
                const PurchaseInvoiceScreen(supplierReturnMode: true),
          ),
        );
        break;
    }

    if (mounted) {
      await _loadInvoices();
    }
  }
}
