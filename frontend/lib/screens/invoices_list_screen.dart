import 'package:flutter/material.dart';
import 'dart:convert';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';

import '../api_service.dart';
import '../providers/auth_provider.dart';
import '../services/data_sync_bus.dart';
import 'add_return_invoice_screen.dart';
import 'invoice_print_screen.dart';
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

class _InvoicesListScreenState extends State<InvoicesListScreen> with TickerProviderStateMixin {
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
  static const List<String> _tabTypes = ['بيع', 'شراء', 'مرتجع'];
  static const List<String> _tabTypesEn = ['Sales', 'Purchase', 'Returns'];

  // Filters
  String _searchQuery = '';
  String _selectedInvoiceType = 'all';
  String _selectedStatus = 'all';
  DateTimeRange? _dateRange;
  String _sortBy = 'date';
  bool _sortAscending = false;

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
    _tabController = TabController(length: 3, vsync: this);
    _tabController.addListener(() {
      if (!mounted) return;
      setState(() {
        // Rebuild to refresh statistics header/cards when tab changes.
      });
    });
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
    if (_itemsRevisionListener != null) {
      DataSyncBus.itemsRevision.removeListener(_itemsRevisionListener!);
    }
    super.dispose();
  }

  Future<void> _loadInvoices() async {
    if (!mounted) return;
    setState(() => _isLoading = true);

    try {
      final data = await _apiService.getInvoices();

      if (!mounted) return;

      // Process data
      final invoices = data is List ? data : (data['invoices'] ?? []);

      if (!mounted) return;

      setState(() {
        _invoices = invoices;
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
    if (_invoices.isEmpty) {
      _filteredInvoices = [];
      return;
    }

    try {
      _filteredInvoices = _invoices.where((invoice) {
        // Search filter
        if (_searchQuery.isNotEmpty) {
          final searchLower = _searchQuery.toLowerCase();
          final customerName = (invoice['customer_name'] ?? '')
              .toString()
              .toLowerCase();
          final supplierName = (invoice['supplier_name'] ?? '')
              .toString()
              .toLowerCase();
          final invoiceNumber = _getInvoiceDisplayNumber(invoice).toLowerCase();
          if (!customerName.contains(searchLower) &&
              !supplierName.contains(searchLower) &&
              !invoiceNumber.contains(searchLower)) {
            return false;
          }
        }

        // Invoice type filter
        if (_selectedInvoiceType != 'all') {
          final invoiceType = (invoice['invoice_type'] ?? '').toString().trim();
          if (invoiceType != _selectedInvoiceType) {
            return false;
          }
        }

        if (_selectedStatus != 'all') {
          final normalizedStatus = _normalizeStatus(
            (invoice['status'] ?? '').toString(),
          );
          if (_selectedStatus == 'paid_full') {
            if (normalizedStatus != 'paid') return false;
          } else if (_selectedStatus == 'remaining') {
            if (normalizedStatus != 'unpaid' &&
                normalizedStatus != 'partially_paid') {
              return false;
            }
          } else {
            if (normalizedStatus != _selectedStatus) {
              return false;
            }
          }
        }

        // Date range filter
        if (_dateRange != null && invoice['date'] != null) {
          try {
            final invoiceDate = DateTime.parse(invoice['date'].toString());
            if (invoiceDate.isBefore(_dateRange!.start) ||
                invoiceDate.isAfter(_dateRange!.end)) {
              return false;
            }
          } catch (e) {
            debugPrint('⚠️ خطأ في تحليل التاريخ: $e');
            return true; // اترك الفاتورة إذا فشل parsing التاريخ
          }
        }

        return true;
      }).toList();

      // Apply sorting
      if (_filteredInvoices.isNotEmpty) {
        _filteredInvoices.sort((a, b) {
          int comparison = 0;
          try {
            switch (_sortBy) {
              case 'recent':
                final idA = _tryParseInt(a['id']) ?? 0;
                final idB = _tryParseInt(b['id']) ?? 0;
                comparison = idA.compareTo(idB);
                break;
              case 'date':
                final dateA = a['date'] != null
                    ? DateTime.parse(a['date'].toString())
                    : DateTime.now();
                final dateB = b['date'] != null
                    ? DateTime.parse(b['date'].toString())
                    : DateTime.now();
                comparison = dateA.compareTo(dateB);
                if (comparison == 0) {
                  final idA = _tryParseInt(a['id']) ?? 0;
                  final idB = _tryParseInt(b['id']) ?? 0;
                  comparison = idA.compareTo(idB);
                }
                break;
              case 'customer':
                comparison = (a['customer_name'] ?? '').toString().compareTo(
                  (b['customer_name'] ?? '').toString(),
                );
                break;
              case 'amount':
                final aTotal = ((a['total'] ?? 0) as num).toDouble();
                final bTotal = ((b['total'] ?? 0) as num).toDouble();
                comparison = aTotal.compareTo(bTotal);
                break;
              case 'number':
                final aPrefix = _extractInvoicePrefix(a);
                final bPrefix = _extractInvoicePrefix(b);
                comparison = aPrefix.compareTo(bPrefix);
                if (comparison == 0) {
                  final aYear = _extractInvoiceYear(a);
                  final bYear = _extractInvoiceYear(b);
                  comparison = aYear.compareTo(bYear);
                  if (comparison == 0) {
                    final aSeq = _extractInvoiceSequence(a);
                    final bSeq = _extractInvoiceSequence(b);
                    comparison = aSeq.compareTo(bSeq);
                  }
                }
                break;
            }
          } catch (e) {
            debugPrint('⚠️ خطأ في الترتيب: $e');
            comparison = 0;
          }
          return _sortAscending ? comparison : -comparison;
        });
      }
    } catch (e) {
      debugPrint('❌ خطأ في تطبيق الفلاتر: $e');
      _filteredInvoices = _invoices;
    }
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
    final direct = _tryParseDouble(invoice['total_weight']);
    if (direct > 0) return direct;

    final items = invoice['items'];
    if (items is List) {
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

  List<dynamic> _getInvoicesForTabFromList(String tabType, List<dynamic> source) {
    if (source.isEmpty) return [];

    final normalizedLabel = tabType.trim().toLowerCase();
    final isSalesTab = tabType == 'بيع' || normalizedLabel == 'sales';
    final isPurchaseTab = tabType == 'شراء' || normalizedLabel == 'purchase';
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

    return source.where((inv) {
      final type = (inv['invoice_type'] ?? '').toString();
      if (isReturnsTab) return isReturnInvoiceType(type);
      if (isPurchaseTab) return isPurchaseInvoiceType(type);
      if (isSalesTab) return isSalesInvoiceType(type);
      return false;
    }).toList();
  }

  // Calculate stats for the current tab (respects active filters)
  Map<String, dynamic> _getTabStatistics(String tabType) {
    final tabInvoices = _getInvoicesForTabFromList(tabType, _filteredInvoices);
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
          final hasTotalSettledKey = invoice.containsKey('total_settled_amount');
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
          final hasTotalSettledKey = invoice.containsKey('total_settled_amount');
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
    setState(() {
      _searchQuery = '';
      _selectedInvoiceType = 'all';
      _selectedStatus = 'all';
      _dateRange = null;
      _applyFilters();
    });
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final primary = colorScheme.primary;
    final scaffoldBackground = theme.scaffoldBackgroundColor;
    final tabLabels = isAr ? _tabTypes : _tabTypesEn;
    final tabIcons = [Icons.shopping_bag, Icons.shopping_cart, Icons.undo];

    return Directionality(
      textDirection: isAr ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        backgroundColor: scaffoldBackground,
        appBar: AppBar(
          title: Text(isAr ? 'قائمة الفواتير' : 'Invoices List'),
          actions: [
            IconButton(
              icon: Icon(Icons.refresh, color: primary),
              onPressed: _loadInvoices,
              tooltip: isAr ? 'تحديث' : 'Refresh',
            ),
            IconButton(
              icon: Icon(Icons.filter_list_off, color: primary),
              onPressed: _clearFilters,
              tooltip: isAr ? 'إزالة الفلاتر' : 'Clear Filters',
            ),
          ],
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(50),
            child: TabBar(
              controller: _tabController,
              isScrollable: false,
              labelColor: primary,
              unselectedLabelColor: colorScheme.onSurface.withValues(alpha: 0.6),
              indicatorColor: primary,
              indicatorSize: TabBarIndicatorSize.label,
              tabs: List.generate(tabLabels.length, (index) {
                return Tab(
                  icon: Icon(tabIcons[index]),
                  text: tabLabels[index],
                );
              }),
            ),
          ),
        ),
        body: Column(
          children: [
            // Statistics Cards
            _buildStatisticsSection(),

            // Filters Section
            _buildFiltersSection(),

            // TabBarView
            Expanded(
              child: _isLoading
                  ? Center(
                      child: CircularProgressIndicator(
                        valueColor: AlwaysStoppedAnimation<Color>(primary),
                      ),
                    )
                  : TabBarView(
                      controller: _tabController,
                      children: List.generate(tabLabels.length, (index) {
                        final tabInvoices = _getInvoicesForTabFromList(
                          tabLabels[index],
                          _filteredInvoices,
                        );
                        
                        if (tabInvoices.isEmpty) {
                          return _buildEmptyState();
                        }
                        
                        return _buildTabContent(tabInvoices);
                      }),
                    ),
            ),
          ],
        ),
        floatingActionButton: FloatingActionButton.extended(
          backgroundColor: primary,
          foregroundColor: colorScheme.onPrimary,
          onPressed: () => _navigateToAddInvoice(),
          icon: Icon(Icons.add),
          label: Text(isAr ? 'فاتورة جديدة' : 'New Invoice'),
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
        padding: const EdgeInsets.all(16),
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
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: statsBackground,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  isAr ? 'الإحصائيات' : 'Statistics',
                  style: textTheme.titleLarge?.copyWith(
                    color: colorScheme.primary,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: colorScheme.primary.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  currentTabType,
                  style: textTheme.labelMedium?.copyWith(
                    color: colorScheme.primary,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                SizedBox(
                  width: 190,
                  child: _buildStatCard(
                    icon: Icons.receipt_long,
                    title: isAr ? 'إجمالي الفواتير' : 'Total Invoices',
                    value: tabStats['total_invoices'].toString(),
                    highlightColor: Colors.blue,
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 190,
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
                const SizedBox(width: 8),
                SizedBox(
                  width: 190,
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
                const SizedBox(width: 8),
                SizedBox(
                  width: 190,
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
                const SizedBox(width: 8),
                SizedBox(
                  width: 190,
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
                const SizedBox(width: 8),
                SizedBox(
                  width: 190,
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
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(6),
                  decoration: BoxDecoration(
                    color: highlightColor.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(icon, color: highlightColor, size: 18),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    title,
                    style: textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurface.withValues(alpha: 0.7),
                      fontWeight: FontWeight.w600,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              value,
              style: textTheme.titleLarge?.copyWith(
                color: highlightColor,
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFiltersSection() {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    final bool isDark = theme.brightness == Brightness.dark;
    final filterBackground = colorScheme.surfaceContainerHighest.withValues(
      alpha: isDark ? 0.4 : 0.7,
    );

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: filterBackground,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: colorScheme.outline.withValues(alpha: 0.1)),
      ),
      child: Column(
        children: [
          // Search and Date Range
          Row(
            children: [
              Expanded(
                child: TextField(
                  style: textTheme.bodyMedium?.copyWith(
                    color: colorScheme.onSurface,
                  ),
                  decoration: InputDecoration(
                    hintText: isAr
                        ? '🔍 بحث برقم الفاتورة أو اسم العميل...'
                        : '🔍 Search by number or customer...',
                    hintStyle: textTheme.bodyMedium?.copyWith(
                      color: colorScheme.onSurface.withValues(alpha: 0.5),
                    ),
                    filled: true,
                    fillColor: colorScheme.surface.withValues(
                      alpha: isDark ? 0.35 : 0.9,
                    ),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(
                        color: colorScheme.outline.withValues(alpha: 0.2),
                      ),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(
                        color: colorScheme.outline.withValues(alpha: 0.1),
                      ),
                    ),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 12,
                    ),
                  ),
                  onChanged: (value) {
                    setState(() {
                      _searchQuery = value;
                      _applyFilters();
                    });
                  },
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                icon: Icon(
                  Icons.date_range,
                  color: _dateRange != null
                      ? colorScheme.primary
                      : colorScheme.onSurface.withValues(alpha: 0.6),
                ),
                label: Text(
                  _dateRange == null
                      ? (isAr ? 'التاريخ' : 'Date')
                      : '${DateFormat('yyyy-MM-dd').format(_dateRange!.start)} - ${DateFormat('yyyy-MM-dd').format(_dateRange!.end)}',
                  style: textTheme.bodySmall?.copyWith(
                    color: _dateRange != null
                        ? colorScheme.primary
                        : colorScheme.onSurface.withValues(alpha: 0.8),
                    fontWeight: FontWeight.w600,
                  ),
                ),
                style: OutlinedButton.styleFrom(
                  side: BorderSide(
                    color: _dateRange != null
                        ? colorScheme.primary.withValues(alpha: 0.4)
                        : colorScheme.outline.withValues(alpha: 0.2),
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 12,
                  ),
                ),
                onPressed: () async {
                  final picked = await showDateRangePicker(
                    context: context,
                    firstDate: DateTime(2020),
                    lastDate: DateTime.now().add(Duration(days: 365)),
                    initialDateRange: _dateRange,
                  );
                  if (picked != null) {
                    setState(() {
                      _dateRange = picked;
                      _applyFilters();
                    });
                  }
                },
              ),
            ],
          ),
          const SizedBox(height: 12),

          // Dropdowns and Sort
          Row(
            children: [
              Expanded(
                child: _buildDropdown(
                  value: _selectedInvoiceType,
                  hint: isAr ? 'نوع الفاتورة' : 'Invoice Type',
                  items: _buildInvoiceTypeItems(isAr),
                  onChanged: (value) {
                    if (value == null) {
                      return;
                    }
                    setState(() {
                      _selectedInvoiceType = value;
                      _applyFilters();
                    });
                  },
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _buildDropdown(
                  value: _selectedStatus,
                  hint: isAr ? 'الحالة' : 'Status',
                  items: _buildStatusItems(isAr),
                  onChanged: (value) {
                    if (value == null) {
                      return;
                    }
                    setState(() {
                      _selectedStatus = value;
                      _applyFilters();
                    });
                  },
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _buildDropdown(
                  value: _sortBy,
                  hint: isAr ? 'ترتيب حسب' : 'Sort By',
                  items: [
                    {
                      'value': 'recent',
                      'label': isAr ? 'الأحدث' : 'Most Recent',
                    },
                    {'value': 'date', 'label': isAr ? 'التاريخ' : 'Date'},
                    {
                      'value': 'customer',
                      'label': isAr ? 'العميل' : 'Customer',
                    },
                    {'value': 'amount', 'label': isAr ? 'المبلغ' : 'Amount'},
                    {'value': 'number', 'label': isAr ? 'الرقم' : 'Number'},
                  ],
                  onChanged: (value) {
                    if (value == null) {
                      return;
                    }
                    setState(() {
                      _sortBy = value;
                      _applyFilters();
                    });
                  },
                ),
              ),
              IconButton(
                icon: Icon(
                  _sortAscending ? Icons.arrow_upward : Icons.arrow_downward,
                  color: colorScheme.primary,
                ),
                onPressed: () {
                  setState(() {
                    _sortAscending = !_sortAscending;
                    _applyFilters();
                  });
                },
              ),
            ],
          ),
        ],
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

  List<Map<String, String>> _buildInvoiceTypeItems(bool isArabic) {
    const defaultOrder = [
      'شراء',
      'شراء من عميل',
      'شراء خردة',
      'شراء مستعمل',
      'بيع',
      'بيع جديد',
      'بيع مستعمل',
      'مرتجع شراء',
      'مرتجع شراء (مورد)',
      'مرتجع شراء من عميل',
      'مرتجع بيع',
      'مرتجع بيع خردة',
      'مقايضة',
    ];

    const englishLabels = {
      'شراء': 'Purchase',
      'شراء من عميل': 'Purchase (Customer)',
      'شراء خردة': 'Scrap Purchase',
      'شراء مستعمل': 'Used Gold Purchase',
      'بيع': 'Sale',
      'بيع جديد': 'New Sale',
      'بيع مستعمل': 'Used Sale',
      'مرتجع شراء': 'Purchase Return',
      'مرتجع شراء (مورد)': 'Supplier Purchase Return',
      'مرتجع شراء من عميل': 'Customer Purchase Return',
      'مرتجع بيع': 'Sales Return',
      'مرتجع بيع خردة': 'Scrap Sales Return',
      'مقايضة': 'Exchange',
    };

    final collectedTypes = <String>{
      for (final invoice in _invoices)
        if (((invoice['invoice_type'] ?? '').toString().trim()).isNotEmpty)
          (invoice['invoice_type'] ?? '').toString().trim(),
    };

    final orderedTypes = <String>[];
    for (final type in defaultOrder) {
      if (collectedTypes.contains(type) || collectedTypes.isEmpty) {
        orderedTypes.add(type);
        collectedTypes.remove(type);
      }
    }

    final remaining = collectedTypes.toList()..sort();
    orderedTypes.addAll(remaining);

    final items = <Map<String, String>>[
      {'value': 'all', 'label': isArabic ? 'الكل' : 'All'},
    ];

    for (final type in orderedTypes) {
      final label = isArabic ? type : (englishLabels[type] ?? type);
      items.add({'value': type, 'label': label});
    }

    return items;
  }

  Widget _buildDropdown({
    required String value,
    required String hint,
    required List<Map<String, String>> items,
    required ValueChanged<String?> onChanged,
  }) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final textTheme = theme.textTheme;
    final bool isDark = theme.brightness == Brightness.dark;

    final hasMatch = items.any((item) => item['value'] == value);
    final fallbackValue = items.isNotEmpty
        ? (items.first['value'] ?? value)
        : value;
    final effectiveValue = hasMatch ? value : fallbackValue;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: colorScheme.surface.withValues(alpha: isDark ? 0.35 : 0.95),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colorScheme.outline.withValues(alpha: 0.1)),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: effectiveValue,
          hint: Text(
            hint,
            style: textTheme.bodyMedium?.copyWith(
              color: colorScheme.onSurface.withValues(alpha: 0.6),
            ),
          ),
          dropdownColor: theme.cardTheme.color ?? colorScheme.surface,
          style: textTheme.bodyMedium?.copyWith(color: colorScheme.onSurface),
          isExpanded: true,
          items: items.map((item) {
            return DropdownMenuItem<String>(
              value: item['value']!,
              child: Text(item['label']!, style: textTheme.bodyMedium),
            );
          }).toList(),
          onChanged: onChanged,
        ),
      ),
    );
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
          invoiceType == 'شراء' || invoiceType.toLowerCase() == 'buy';
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
      await Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => InvoicePrintScreen(
            invoice: mergedInvoice,
            isArabic: widget.isArabic,
            autoPrint: autoPrint,
            autoSharePdf: autoSharePdf,
            autoDownloadPdf: autoDownloadPdf,
          ),
        ),
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
                                  ? raw
                                      .map((k, v) => MapEntry(k.toString(), v))
                                  : <String, dynamic>{};

                              final paymentId = _tryParseInt(payment['id']);
                              final amount = _tryParseDouble(payment['amount']);
                              final methodName =
                                  (payment['payment_method_name'] ?? '')
                                      .toString();
                              final createdAt = (payment['created_at'] ?? '')
                                  .toString();
                              final notes =
                                  (payment['notes'] ?? '').toString().trim();

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
                                                    color: colorScheme
                                                        .onSurface
                                                        .withValues(
                                                          alpha: 0.7,
                                                        ),
                                                    fontWeight:
                                                        FontWeight.w600,
                                                  ),
                                            ),
                                          ],
                                          if (notes.isNotEmpty) ...[
                                            const SizedBox(height: 4),
                                            Text(
                                              notes,
                                              style: textTheme.bodySmall
                                                  ?.copyWith(
                                                    color: colorScheme
                                                        .onSurface
                                                        .withValues(
                                                          alpha: 0.7,
                                                        ),
                                                    fontStyle:
                                                        FontStyle.italic,
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
            final parsedPid = pid is int ? pid : int.tryParse(pid?.toString() ?? '');
            if (parsedPid == invoicePaymentId) {
              final vid = v['id'];
              linkedVoucherId = vid is int ? vid : int.tryParse(vid?.toString() ?? '');
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
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => VoucherDetailsScreen(voucherId: linkedVoucherId!),
        ),
      );
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
            builder: (_) => AddReturnInvoiceScreen(
              api: _apiService,
              returnType: 'مرتجع شراء (مورد)',
            ),
          ),
        );
        break;
    }

    if (mounted) {
      await _loadInvoices();
    }
  }
}
