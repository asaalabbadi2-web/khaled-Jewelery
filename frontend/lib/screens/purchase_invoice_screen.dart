import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api_service.dart';
import '../models/category_model.dart';
import '../models/safe_box_model.dart';
import '../providers/auth_provider.dart';
import '../providers/settings_provider.dart';
import 'add_supplier_screen.dart';
import 'invoice_print_screen.dart';
import '../utils.dart';

class PurchaseInvoiceScreen extends StatefulWidget {
  final int? supplierId;

  const PurchaseInvoiceScreen({super.key, this.supplierId});

  @override
  State<PurchaseInvoiceScreen> createState() => _PurchaseInvoiceScreenState();
}

class _PurchaseInvoiceScreenState extends State<PurchaseInvoiceScreen> {
  final ApiService _api = ApiService();

  bool _manualPricing = false;
  bool _applyVatOnGold = true;
  String _wagePostingMode = 'expense';
  bool _isLoadingSuppliers = false;
  bool _isSavingInvoice = false;
  bool _showAdvancedPaymentOptions = false;

  // Branches (فروع المعرض/المحل)
  bool _isLoadingBranches = false;
  List<Map<String, dynamic>> _branches = [];
  int? _selectedBranchId;
  String? _branchError;

  List<Map<String, dynamic>> _suppliers = [];
  int? _selectedSupplierId;
  String? _supplierError;

  // Payment Methods
  List<Map<String, dynamic>> _paymentMethods = [];
  int? _selectedPaymentMethodId;

  List<SafeBoxModel> _safeBoxes = [];
  int? _selectedSafeBoxId;

  List<Category> _categories = [];
  bool _isLoadingCategories = false;
  String? _categoriesError;

  Map<String, dynamic>? _goldPrice;
  List<PurchaseKaratLine> _karatLines = [];
  List<PurchaseInlineItem> _inlineItems = [];

  double _totalWeight = 0;
  double _goldSubtotal = 0;
  double _wageSubtotal = 0;
  double _goldTaxTotal = 0;
  double _wageTaxTotal = 0;
  double _subtotal = 0;
  double _taxTotal = 0;
  double _grandTotal = 0;

  void _resetAfterSave() {
    setState(() {
      _selectedSupplierId = null;
      _karatLines = [];
      _inlineItems = [];
      _showAdvancedPaymentOptions = false;
      _selectedPaymentMethodId = null;
      _selectedSafeBoxId = null;
      _supplierError = null;
      _applyTotals(_KaratTotals.zero);
    });
  }

  double _vatRateFromSettings() {
    try {
      final settings = context.read<SettingsProvider>();
      return settings.taxEnabled ? settings.taxRate : 0.0;
    } catch (_) {
      return 0.15;
    }
  }

  Set<int> _vatExemptKaratsFromSettings() {
    try {
      final settings = context.read<SettingsProvider>();
      return settings.vatExemptKarats.toSet();
    } catch (_) {
      return {24};
    }
  }

  @override
  void initState() {
    super.initState();
    _selectedSupplierId = widget.supplierId;
    _loadBranches();
    _loadSuppliers();
    _loadCategories();
    _loadGoldPrice();
    _loadPaymentMethods();
    _loadSettings();
    _applyTotals(_KaratTotals.zero);
  }

  Future<void> _loadBranches() async {
    setState(() {
      _isLoadingBranches = true;
      _branchError = null;
    });

    try {
      final raw = await _api.getBranches(activeOnly: true);
      if (!mounted) return;

      final branches = raw
          .whereType<Map>()
          .map((b) => Map<String, dynamic>.from(b))
          .toList();

      setState(() {
        _branches = branches;
        if (_selectedBranchId == null && _branches.length == 1) {
          final id = _parseId(_branches.first['id']);
          if (id != null) _selectedBranchId = id;
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _branchError = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _isLoadingBranches = false;
      });
    }
  }

  Future<void> _loadSettings() async {
    Map<String, dynamic>? settings;

    // 1) Prefer cached settings to avoid permission noise
    try {
      final prefs = await SharedPreferences.getInstance();
      final cached = prefs.getString('app_settings');
      if (cached != null && cached.trim().isNotEmpty) {
        final decoded = jsonDecode(cached);
        if (decoded is Map<String, dynamic>) {
          settings = decoded;
        } else if (decoded is Map) {
          settings = Map<String, dynamic>.from(decoded);
        }
      }
    } catch (_) {
      // ignore cache failures
    }

    // 2) Fetch latest only if the user is allowed to read settings
    try {
      final auth = context.read<AuthProvider>();
      if (auth.hasPermission('system.settings')) {
        settings = await _api.getSettings();
        try {
          final prefs = await SharedPreferences.getInstance();
          await prefs.setString('app_settings', jsonEncode(settings));
        } catch (_) {
          // ignore caching failures
        }
      }
    } catch (_) {
      // ignore network/auth failures; fallback to cached/defaults
    }

    if (!mounted || settings == null) return;

    final rawMode = settings['manufacturing_wage_mode'];
    final normalized = rawMode is String
        ? rawMode.toLowerCase().trim()
        : rawMode?.toString().toLowerCase().trim();

    if (normalized == 'inventory' || normalized == 'expense') {
      setState(() {
        _wagePostingMode = normalized!;
      });
    }
  }

  Future<void> _loadSuppliers() async {
    setState(() {
      _isLoadingSuppliers = true;
      _supplierError = null;
    });

    try {
      final response = await _api.getSuppliers();
      if (!mounted) return;

      final suppliers = response
          .whereType<Map<String, dynamic>>()
          .map((supplier) {
            final normalized = Map<String, dynamic>.from(supplier);
            normalized['id'] = _parseId(supplier['id']);
            return normalized;
          })
          .where((supplier) => supplier['id'] != null)
          .toList();

      suppliers.sort(
        (a, b) => ((a['name'] ?? '') as String).compareTo(
          (b['name'] ?? '') as String,
        ),
      );

      final int? initialId = _selectedSupplierId ?? widget.supplierId;
      final bool hasInitial =
          initialId != null &&
          suppliers.any((supplier) => supplier['id'] == initialId);

      final int? resolvedId;
      if (hasInitial) {
        resolvedId = initialId;
      } else if (suppliers.length == 1) {
        resolvedId = suppliers.first['id'] as int?;
      } else {
        resolvedId = null;
      }

      setState(() {
        _suppliers = suppliers;
        _selectedSupplierId = resolvedId;
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('فشل تحميل الموردين: $e'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isLoadingSuppliers = false;
        });
      }
    }
  }

  Future<void> _loadCategories() async {
    setState(() {
      _isLoadingCategories = true;
      _categoriesError = null;
    });

    try {
      final response = await _api.getCategories();
      if (!mounted) return;

      final categories = response
          .whereType<Map<String, dynamic>>()
          .map(Category.fromJson)
          .toList()
        ..sort((a, b) => a.name.compareTo(b.name));

      setState(() {
        _categories = categories;
      });
    } catch (e) {
      if (!mounted) return;
      final message = 'فشل تحميل التصنيفات: $e';
      setState(() {
        _categoriesError = message;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(message),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isLoadingCategories = false;
        });
      }
    }
  }

  Future<void> _loadPaymentMethods() async {
    try {
      final methods = await _api.getActivePaymentMethods();
      if (!mounted) return;

      final normalizedMethods = methods
          .whereType<Map<String, dynamic>>()
          .map<Map<String, dynamic>>((method) {
            final map = Map<String, dynamic>.from(method);
            final id = _parseInt(map['id']);
            final commission = _toDouble(map['commission_rate']);
            final settlement = _parseInt(map['settlement_days']) ?? 0;
            final displayOrder = _parseInt(map['display_order']) ?? 999;

            return {
              ...map,
              'id': id,
              'commission_rate': commission,
              'settlement_days': settlement,
              'display_order': displayOrder,
            };
          })
          .where((method) => method['id'] != null)
          .toList();

      normalizedMethods.sort((a, b) {
        final aOrder = a['display_order'] as int;
        final bOrder = b['display_order'] as int;
        return aOrder.compareTo(bOrder);
      });

      setState(() {
        _paymentMethods = normalizedMethods;

        if (_paymentMethods.isNotEmpty) {
          final defaultMethod = _paymentMethods.firstWhere(
            (m) => (m['name'] ?? '').toString().trim() == 'نقداً',
            orElse: () => _paymentMethods.first,
          );
          _selectedPaymentMethodId = defaultMethod['id'] as int?;
        } else {
          _selectedPaymentMethodId = null;
        }

        // قم بإعادة تعيين الخزائن قبل تحميلها من جديد
        _safeBoxes = [];
        _selectedSafeBoxId = null;
      });

      if (_selectedPaymentMethodId != null) {
        await _loadSafeBoxesForPaymentMethod(_selectedPaymentMethodId!);
      } else {
        await _loadDefaultSafeBox();
      }
    } catch (e) {
      debugPrint('فشل تحميل وسائل الدفع: $e');
    }
  }

  Future<void> _loadSafeBoxesForPaymentMethod(int paymentMethodId) async {
    try {
      final method = _paymentMethods.firstWhere(
        (m) => m['id'] == paymentMethodId,
        orElse: () => {},
      );

      if (method.isEmpty) return;

      final paymentType = method['payment_type'] as String?;
      if (paymentType == null) return;

      final allBoxes = await _api.getSafeBoxes();
      List<SafeBoxModel> boxes;

      switch (paymentType) {
        case 'cash':
          boxes = allBoxes.where((box) => box.safeType == 'cash').toList();
          break;
        case 'bank_transfer':
        case 'check':
          boxes = allBoxes.where((box) => box.safeType == 'bank').toList();
          break;
        default:
          boxes = allBoxes
              .where((box) => box.safeType == 'cash' || box.safeType == 'bank')
              .toList();
      }

      if (!mounted) return;

      if (boxes.isEmpty) {
        await _loadDefaultSafeBox();
        return;
      }

      setState(() {
        _safeBoxes = boxes;
        final defaultBox = _safeBoxes.firstWhere(
          (box) => box.isDefault == true,
          orElse: () => _safeBoxes.first,
        );
        _selectedSafeBoxId = defaultBox.id;
      });
    } catch (e) {
      debugPrint('فشل تحميل الخزائن: $e');
    }
  }

  Future<void> _loadDefaultSafeBox() async {
    try {
      final boxes = await _api.getSafeBoxes();
      final cashBoxes = boxes.where((box) => box.safeType == 'cash').toList();

      if (!mounted) return;

      setState(() {
        _safeBoxes = cashBoxes;
        if (cashBoxes.isNotEmpty) {
          final defaultBox = cashBoxes.firstWhere(
            (box) => box.isDefault == true,
            orElse: () => cashBoxes.first,
          );
          _selectedSafeBoxId = defaultBox.id;
        }
      });
    } catch (e) {
      debugPrint('فشل تحميل الخزائن: $e');
    }
  }

  Future<void> _loadGoldPrice() async {
    try {
      final price = await _api.getGoldPrice();
      if (!mounted) return;

      final enriched = Map<String, dynamic>.from(price);
      final base24 = _toDouble(enriched['price_24k']);
      enriched['price_24k'] = base24;
      enriched['price_22k'] = base24 * 22 / 24;
      enriched['price_21k'] = base24 * 21 / 24;
      enriched['price_18k'] = base24 * 18 / 24;

      setState(() {
        _goldPrice = enriched;
        _applyCombinedTotals();
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('خطأ في تحميل سعر الذهب: $e'),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  Future<void> _openAddSupplierDialog() async {
    final result = await Navigator.push<bool?>(
      context,
      MaterialPageRoute(
        builder: (_) => AddSupplierScreen(
          api: _api,
          onSupplierSaved: (saved) {
            if (!mounted) return;
            final normalized = Map<String, dynamic>.from(saved);
            normalized['id'] = _parseId(saved['id']);
            final supplierId = normalized['id'] as int?;
            if (supplierId == null) return;

            setState(() {
              _suppliers.removeWhere(
                (supplier) => _parseId(supplier['id']) == supplierId,
              );
              _suppliers.add(normalized);
              _suppliers.sort(
                (a, b) => ((a['name'] ?? '') as String).compareTo(
                  (b['name'] ?? '') as String,
                ),
              );
              _selectedSupplierId = supplierId;
              _supplierError = null;
            });
          },
        ),
      ),
    );

    if (result == true) {
      debugPrint('Supplier added via AddSupplierScreen (purchase)');
    }
  }

  int? _parseId(dynamic value) {
    if (value == null) return null;
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value.toString());
  }

  int? _parseInt(dynamic value) {
    if (value == null) return null;
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value.toString());
  }

  double _toDouble(dynamic value) {
    if (value == null) return 0.0;
    if (value is double) return value;
    if (value is num) return value.toDouble();
    return double.tryParse(value.toString()) ?? 0.0;
  }

  double _resolveGoldPrice(double karat) {
    if (_goldPrice == null) return 0.0;
    final base24 = _toDouble(_goldPrice!['price_24k']);
    if (base24 <= 0) return 0.0;
    return (base24 * karat) / 24.0;
  }

  _KaratLineSnapshot _snapshotFor(PurchaseKaratLine line) {
    final pricePerGram = _resolveGoldPrice(line.karat);
    final autoGoldValue = line.weightGrams * pricePerGram;
    final autoWageCash = line.weightGrams * line.wagePerGram;

    final vatRate = _vatRateFromSettings();
    final exemptKarats = _vatExemptKaratsFromSettings();
    final karatInt = line.karat.round();
    final isGoldVatExempt = exemptKarats.contains(karatInt);

    final autoGoldTax = (_applyVatOnGold && !isGoldVatExempt)
        ? autoGoldValue * vatRate
        : 0.0;
    final autoWageTax = autoWageCash * vatRate;

    final goldValue = _manualPricing
        ? (line.goldValueOverride ?? autoGoldValue)
        : autoGoldValue;
    final wageCash = _manualPricing
        ? (line.wageCashOverride ?? autoWageCash)
        : autoWageCash;
    var goldTax = _manualPricing
      ? (line.goldTaxOverride ?? autoGoldTax)
      : autoGoldTax;
    final wageTax = _manualPricing
        ? (line.wageTaxOverride ?? autoWageTax)
        : autoWageTax;

    // Enforce exemption even when manual overrides are present.
    if (isGoldVatExempt) {
      goldTax = 0.0;
    }

    return _KaratLineSnapshot(
      line: line,
      pricePerGram: pricePerGram,
      weight: line.weightGrams,
      goldValue: goldValue,
      wageCash: wageCash,
      goldTax: goldTax,
      wageTax: wageTax,
    );
  }

  _KaratTotals _calculateTotals(List<PurchaseKaratLine> lines) {
    double totalWeight = 0;
    double goldSubtotal = 0;
    double wageSubtotal = 0;
    double goldTaxTotal = 0;
    double wageTaxTotal = 0;

    for (final line in lines) {
      final snapshot = _snapshotFor(line);
      totalWeight += snapshot.weight;
      goldSubtotal += snapshot.goldValue;
      wageSubtotal += snapshot.wageCash;
      goldTaxTotal += snapshot.goldTax;
      wageTaxTotal += snapshot.wageTax;
    }

    return _KaratTotals(
      totalWeight: totalWeight,
      goldSubtotal: goldSubtotal,
      wageSubtotal: wageSubtotal,
      goldTaxTotal: goldTaxTotal,
      wageTaxTotal: wageTaxTotal,
    );
  }

  List<PurchaseKaratLine> _derivedInlineKaratLines(
    List<PurchaseInlineItem>? items,
  ) {
    final source = items ?? _inlineItems;
    return source
        .map(
          (item) => PurchaseKaratLine(
            karat: item.karat,
            weightGrams: item.weightGrams,
            wagePerGram: item.wagePerGram,
          ),
        )
        .toList();
  }

  void _applyCombinedTotals({
    List<PurchaseKaratLine>? manualLines,
    List<PurchaseInlineItem>? inlineItems,
  }) {
    final resolvedManual = manualLines ?? _karatLines;
    final resolvedInline = inlineItems ?? _inlineItems;
    final combinedLines = [
      ...resolvedManual,
      ..._derivedInlineKaratLines(resolvedInline),
    ];
    _applyTotals(_calculateTotals(combinedLines));
  }

  void _applyTotals(_KaratTotals totals) {
    _totalWeight = _round(totals.totalWeight, 3);
    _goldSubtotal = _round(totals.goldSubtotal, 2);
    _wageSubtotal = _round(totals.wageSubtotal, 2);
    _goldTaxTotal = _round(totals.goldTaxTotal, 2);
    _wageTaxTotal = _round(totals.wageTaxTotal, 2);
    _subtotal = _round(_goldSubtotal + _wageSubtotal, 2);
    _taxTotal = _round(_goldTaxTotal + _wageTaxTotal, 2);
    _grandTotal = _round(_subtotal + _taxTotal, 2);
  }

  void _updateLines(List<PurchaseKaratLine> lines) {
    setState(() {
      _karatLines = lines;
      _applyCombinedTotals(manualLines: lines);
    });
  }

  void _updateInlineItems(List<PurchaseInlineItem> items) {
    setState(() {
      _inlineItems = items;
      _applyCombinedTotals(inlineItems: items);
    });
  }

  Future<void> _addInlineItem() async {
    final item = await _showInlineItemDialog();
    if (item == null) return;
    _updateInlineItems([..._inlineItems, item]);
  }

  Future<void> _addInlineItemsBulk() async {
    final result = await _showInlineBulkDialog();
    if (result == null || result.weights.isEmpty) return;

    final newItems = result.weights
        .map(
          (weight) => PurchaseInlineItem(
            name: result.name,
            karat: result.karat,
            weightGrams: weight,
            wagePerGram: result.wagePerGram,
            description: result.description,
            itemCode: result.itemCode,
            barcode: result.barcode,
            category: result.category,
            categoryId: result.categoryId,
          ),
        )
        .toList();

    _updateInlineItems([..._inlineItems, ...newItems]);

    if (!mounted) return;
    final totalWeight = newItems.fold<double>(
      0,
      (sum, item) => sum + item.weightGrams,
    );
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'تمت إضافة ${newItems.length} وزناً (${_formatWeight(totalWeight)}) للصنف ${result.name}',
        ),
      ),
    );
  }

  Future<void> _editInlineItem(int index) async {
    final existing = _inlineItems[index];
    final item = await _showInlineItemDialog(existing: existing);
    if (item == null) return;

    final updated = [..._inlineItems];
    updated[index] = item;
    _updateInlineItems(updated);
  }

  Future<void> _removeInlineItem(int index) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('حذف الصنف'),
        content: Text('هل تريد حذف الصنف "${_inlineItems[index].name}"؟'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('إلغاء'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('حذف'),
          ),
        ],
      ),
    );

    if (confirm != true) return;

    final updated = [..._inlineItems]..removeAt(index);
    _updateInlineItems(updated);
  }

  Future<void> _editKaratLine(int index) async {
    final existing = _karatLines[index];
    final line = await _showKaratLineDialog(existing: existing);
    if (line == null) return;

    final updated = [..._karatLines];
    updated[index] = line;
    _updateLines(updated);
  }

  Future<void> _removeKaratLine(int index) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('حذف سطر العيار'),
          content: const Text('هل أنت متأكد من حذف هذا السطر؟'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('إلغاء'),
            ),
            ElevatedButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('حذف'),
            ),
          ],
        );
      },
    );

    if (confirm != true) return;

    final updated = [..._karatLines]..removeAt(index);
    _updateLines(updated);
  }

  Future<void> _addManualKaratLine() async {
    final line = await _showKaratLineDialog();
    if (line == null) return;

    _updateLines([..._karatLines, line]);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'تمت إضافة وزن ${_formatWeight(line.weightGrams)} لعيار ${line.karat.toStringAsFixed(0)}',
        ),
      ),
    );
  }

  Future<void> _addBulkWeights() async {
    final result = await _showBulkWeightsDialog();
    if (result == null) return;

    final updated = [..._karatLines];
    for (final weight in result.weights) {
      updated.add(
        PurchaseKaratLine(
          karat: result.karat,
          weightGrams: weight,
          wagePerGram: result.wagePerGram,
          description: result.notes,
        ),
      );
    }

    _updateLines(updated);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'تمت إضافة ${result.weights.length} من الأوزان لعيار ${result.karat.toStringAsFixed(0)}',
        ),
      ),
    );
  }

  Map<String, double> _aggregateManualWeightByKarat() {
    final Map<String, double> summary = {};
    for (final line in _karatLines) {
      final key = _normalizeKaratKey(line.karat);
      summary[key] = (summary[key] ?? 0) + line.weightGrams;
    }
    return summary;
  }

  Map<String, double> _aggregateInlineWeightByKarat() {
    final Map<String, double> summary = {};
    for (final item in _inlineItems) {
      final key = _normalizeKaratKey(item.karat);
      summary[key] = (summary[key] ?? 0) + item.weightGrams;
    }
    return summary;
  }

  Map<String, double> _aggregateWeightByKarat() {
    final summary = Map<String, double>.from(_aggregateManualWeightByKarat());
    for (final entry in _aggregateInlineWeightByKarat().entries) {
      summary[entry.key] = (summary[entry.key] ?? 0) + entry.value;
    }
    return summary;
  }

  double get _inlineTotalWeight =>
      _inlineItems.fold(0.0, (sum, item) => sum + item.weightGrams);

  double get _inlineTotalWage => _inlineItems.fold(
      0.0, (sum, item) => sum + (item.weightGrams * item.wagePerGram));

  Map<double, _InlineKaratAggregate> _inlineKaratAggregates() {
    final Map<double, _InlineKaratAggregate> aggregates = {};
    for (final item in _inlineItems) {
      final line = PurchaseKaratLine(
        karat: item.karat,
        weightGrams: item.weightGrams,
        wagePerGram: item.wagePerGram,
      );
      final snapshot = _snapshotFor(line);
      aggregates.putIfAbsent(line.karat, () => _InlineKaratAggregate()).add(snapshot);
    }
    return aggregates;
  }

  String _normalizeKaratKey(double karat) {
    if (karat.isNaN || !karat.isFinite) return '0';
    final rounded = karat.round();
    if ((karat - rounded).abs() < 0.0001) {
      return rounded.toString();
    }
    return _round(karat, 2).toString();
  }

  double _round(double value, int fractionDigits) {
    final double mod = math.pow(10.0, fractionDigits).toDouble();
    return (value * mod).round() / mod;
  }

  String _formatCurrency(double value) => '${value.toStringAsFixed(2)} ر.س';

  String _formatWeight(double value) => '${value.toStringAsFixed(3)} جم';

  bool _validateBeforeSave() {
    if (_selectedBranchId == null) {
      setState(() {
        _branchError = 'يجب اختيار فرع';
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('يرجى اختيار الفرع قبل الحفظ')),
      );
      return false;
    }

    if (_selectedSupplierId == null) {
      setState(() {
        _supplierError = 'يجب اختيار مورد';
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('يرجى اختيار المورد قبل الحفظ')),
      );
      return false;
    }

    if (_karatLines.isEmpty && _inlineItems.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('أضف أصنافاً أو قم بتعبئة بيانات العيارات قبل الحفظ'),
        ),
      );
      return false;
    }

    if (_totalWeight <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('إجمالي الوزن يجب أن يكون أكبر من صفر')),
      );
      return false;
    }

    if (_paymentMethods.isNotEmpty && _selectedPaymentMethodId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('اختر وسيلة الدفع قبل الحفظ')),
      );
      return false;
    }

    return true;
  }

  Map<String, dynamic> _buildInvoicePayload() {
    final linePayloads = _karatLines.map((line) {
      final snapshot = _snapshotFor(line);
      return {
        'karat': line.karat,
        'weight_grams': _round(snapshot.weight, 3),
        'gold_value_cash': _round(snapshot.goldValue, 2),
        'manufacturing_wage_cash': _round(snapshot.wageCash, 2),
        'gold_tax': _round(snapshot.goldTax, 2),
        'wage_tax': _round(snapshot.wageTax, 2),
        if (line.description?.isNotEmpty ?? false)
          'description': line.description,
      };
    }).toList();

    final inlineAggregates = _inlineKaratAggregates();
    inlineAggregates.forEach((karat, aggregate) {
      linePayloads.add({
        'karat': karat,
        'weight_grams': _round(aggregate.weight, 3),
        'gold_value_cash': _round(aggregate.goldValue, 2),
        'manufacturing_wage_cash': _round(aggregate.wageCash, 2),
        'gold_tax': _round(aggregate.goldTax, 2),
        'wage_tax': _round(aggregate.wageTax, 2),
        'description': 'تفاصيل الأصناف المضافة داخل الفاتورة',
      });
    });

    final inlineItemsPayload =
        _inlineItems.map((item) => item.toPayload()).toList();
    final inlineWeights = _aggregateInlineWeightByKarat();
    final weightByKarat = _aggregateWeightByKarat();
    final supplierGoldLines = weightByKarat.entries
        .map(
          (entry) => {
            'karat': double.tryParse(entry.key) ?? 0,
            'weight': _round(entry.value, 3),
          },
        )
        .toList();

    return {
      'branch_id': _selectedBranchId,
      'supplier_id': _selectedSupplierId,
      'invoice_type': 'شراء من مورد',
      'date': DateTime.now().toIso8601String(),
      'total': _round(_grandTotal, 2),
      'total_cost': _round(_subtotal, 2),
      'total_tax': _round(_taxTotal, 2),
      'total_weight': _round(_totalWeight, 3),
      'gold_type': 'new',
      'gold_subtotal': _round(_goldSubtotal, 2),
      'wage_subtotal': _round(_wageSubtotal, 2),
      'gold_tax_total': _round(_goldTaxTotal, 2),
      'wage_tax_total': _round(_wageTaxTotal, 2),
      'apply_gold_tax': _applyVatOnGold,
      'karat_lines': linePayloads,
      'items': inlineItemsPayload,
      'supplier_gold_lines': supplierGoldLines,
      'supplier_gold_weights': weightByKarat.map(
        (key, value) => MapEntry(key, _round(value, 3)),
      ),
      'manufacturing_wage_cash': _round(_wageSubtotal, 2),
      'wage_cash': _round(_wageSubtotal, 2),
      'valuation_cash_total': _round(_goldSubtotal, 2),
      'gold_tax': _round(_goldTaxTotal, 2),
      'wage_tax': _round(_wageTaxTotal, 2),
      'wage_posting_mode': _wagePostingMode,
      'valuation': {
        'cash_total': _round(_goldSubtotal, 2),
        'weight_by_karat': weightByKarat.map(
          (key, value) => MapEntry(key, _round(value, 3)),
        ),
        'wage_total': _round(_wageSubtotal, 2),
      },
      if (_inlineItems.isNotEmpty) ...{
        'inline_items_summary': {
          'count': _inlineItems.length,
          'total_weight': _round(_inlineTotalWeight, 3),
          'total_wage_cash': _round(_inlineTotalWage, 2),
        },
        'inline_items_weight_by_karat': inlineWeights.map(
          (key, value) => MapEntry(key, _round(value, 3)),
        ),
      },
      if (_selectedSafeBoxId != null) 'safe_box_id': _selectedSafeBoxId,
    };
  }

  Future<void> _saveInvoice() async {
    if (_isSavingInvoice) return;
    if (!_validateBeforeSave()) return;

    setState(() {
      _isSavingInvoice = true;
    });

    try {
      final payload = _buildInvoicePayload();
      final response = await _api.addInvoice(payload);

      if (!mounted) return;

      final invoiceForPrint = Map<String, dynamic>.from(response);

      try {
        final supplier = _suppliers.firstWhere(
          (s) => s['id'] == _selectedSupplierId,
        );
        invoiceForPrint['supplier_name'] ??=
            supplier['name'] ?? supplier['supplier_name'];
        invoiceForPrint['supplier_phone'] ??=
            supplier['phone'] ?? supplier['supplier_phone'];
      } catch (_) {
        // ignore
      }

      final shouldPrint = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (dialogContext) {
          return AlertDialog(
            title: const Text('تم حفظ الفاتورة'),
            content: Text(
              '✅ تم حفظ فاتورة الشراء #${invoiceForPrint['id'] ?? ''}\nهل تريد طباعتها الآن؟',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('تم'),
              ),
              FilledButton.icon(
                onPressed: () => Navigator.pop(dialogContext, true),
                icon: const Icon(Icons.print),
                label: const Text('طباعة'),
              ),
            ],
          );
        },
      );

      if (!mounted) return;
      if (shouldPrint == true) {
        await Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => InvoicePrintScreen(
              invoice: invoiceForPrint,
              isArabic: true,
            ),
          ),
        );
      }

      if (!mounted) return;
      _resetAfterSave();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('فشل حفظ الفاتورة: $e'),
          backgroundColor: Colors.red,
        ),
      );
    } finally {
      if (mounted) {
        setState(() {
          _isSavingInvoice = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.of(context).size;
    final isWideLayout = size.width >= 1100;

    final leftColumn = <Widget>[
      _buildSupplierSection(),
      const SizedBox(height: 24),
      _buildInlineItemsSection(),
      if (_karatLines.isNotEmpty) ...[
        const SizedBox(height: 24),
        _buildKaratLinesSection(),
      ],
    ];

    final rightColumn = <Widget>[
      _buildGoldPriceCard(),
      const SizedBox(height: 24),
      _buildPricingModeCard(),
      const SizedBox(height: 24),
      _buildTotalsCard(),
      const SizedBox(height: 24),
      _buildWagePostingModeCard(),
      const SizedBox(height: 24),
      _buildSettlementCard(),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text('فاتورة شراء جديدة'),
        actions: [
          IconButton(
            tooltip: 'تحديث سعر الذهب',
            icon: const Icon(Icons.refresh),
            onPressed: _loadGoldPrice,
          ),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (isWideLayout)
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      flex: 7,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: leftColumn,
                      ),
                    ),
                    const SizedBox(width: 24),
                    Expanded(
                      flex: 4,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: rightColumn,
                      ),
                    ),
                  ],
                )
              else ...[
                ...leftColumn,
                const SizedBox(height: 24),
                ...rightColumn,
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSupplierSection() {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final isDark = theme.brightness == Brightness.dark;

    return Card(
      elevation: isDark ? 2 : 4,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      shadowColor: Colors.black.withValues(alpha: isDark ? 0.25 : 0.08),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: colorScheme.primary.withValues(alpha: 
                      isDark ? 0.18 : 0.12,
                    ),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Icon(
                    Icons.handshake_outlined,
                    color: colorScheme.primary,
                    size: 26,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'بيانات المورد',
                        style: theme.textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'اختر المورد أو أضف مورداً جديداً قبل متابعة إدخال الأوزان.',
                        style: theme.textTheme.bodyMedium,
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                if (_isLoadingSuppliers)
                  const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                if (!_isLoadingSuppliers) ...[
                  const SizedBox(width: 12),
                  FilledButton.icon(
                    onPressed: _openAddSupplierDialog,
                    icon: const Icon(Icons.person_add_alt_1),
                    label: const Text('مورد جديد'),
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 18,
                        vertical: 12,
                      ),
                      textStyle: theme.textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 20),
            if (_isLoadingBranches)
              const LinearProgressIndicator(minHeight: 2)
            else
              DropdownButtonFormField<int>(
                initialValue: _selectedBranchId,
                items: _branches
                    .map((branch) {
                      final id = _parseId(branch['id']);
                      if (id == null) return null;
                      final name = (branch['name'] ?? 'فرع').toString();
                      return DropdownMenuItem<int>(
                        value: id,
                        child: Text(name),
                      );
                    })
                    .whereType<DropdownMenuItem<int>>()
                    .toList(),
                decoration: InputDecoration(
                  labelText: 'اختر الفرع',
                  border: const OutlineInputBorder(),
                  prefixIcon: Icon(
                    Icons.account_tree,
                    color: colorScheme.primary,
                  ),
                  errorText: _branchError,
                ),
                dropdownColor: theme.cardColor,
                icon: Icon(Icons.arrow_drop_down, color: colorScheme.primary),
                onChanged: (value) {
                  setState(() {
                    _selectedBranchId = value;
                    _branchError = null;
                  });
                },
              ),
            const SizedBox(height: 16),
            DropdownButtonFormField<int>(
                  initialValue: _selectedSupplierId,
              items: _suppliers
                  .map(
                    (supplier) => DropdownMenuItem<int>(
                      value: supplier['id'] as int,
                      child: Text(supplier['name']?.toString() ?? 'بدون اسم'),
                    ),
                  )
                  .toList(),
              decoration: InputDecoration(
                labelText: 'اختر المورد',
                border: const OutlineInputBorder(),
                prefixIcon: Icon(
                  Icons.store_mall_directory,
                  color: colorScheme.primary,
                ),
                errorText: _supplierError,
              ),
              dropdownColor: theme.cardColor,
              icon: Icon(Icons.arrow_drop_down, color: colorScheme.primary),
              onChanged: (value) {
                setState(() {
                  _selectedSupplierId = value;
                  _supplierError = null;
                });
              },
            ),
            const SizedBox(height: 16),
            // Payment Method Dropdown
            if (_paymentMethods.isNotEmpty) ...[
              DropdownButtonFormField<int>(
                initialValue: _selectedPaymentMethodId,
                decoration: InputDecoration(
                  labelText: 'وسيلة الدفع',
                  border: const OutlineInputBorder(),
                  prefixIcon: Icon(
                    Icons.payment,
                    color: colorScheme.primary,
                  ),
                ),
                dropdownColor: theme.cardColor,
                icon: Icon(Icons.arrow_drop_down, color: colorScheme.primary),
                items: _paymentMethods
                    .map(
                      (method) => DropdownMenuItem<int>(
                        value: method['id'] as int,
                        child: Text(method['name']?.toString() ?? 'بدون اسم'),
                      ),
                    )
                    .toList(),
                onChanged: (value) {
                  setState(() {
                    _selectedPaymentMethodId = value;
                  });
                  if (value != null) {
                    _loadSafeBoxesForPaymentMethod(value);
                  }
                },
              ),
              const SizedBox(height: 16),
            ],
            Row(
              children: [
                OutlinedButton.icon(
                  onPressed: _loadSuppliers,
                  icon: const Icon(Icons.refresh),
                  label: const Text('تحديث قائمة الموردين'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 12,
                    ),
                  ),
                ),
                const Spacer(),
                if (_safeBoxes.isNotEmpty)
                  OutlinedButton.icon(
                    onPressed: () {
                      setState(() {
                        _showAdvancedPaymentOptions =
                            !_showAdvancedPaymentOptions;
                      });
                    },
                    icon: Icon(
                      _showAdvancedPaymentOptions
                          ? Icons.settings
                          : Icons.settings_outlined,
                      color: _showAdvancedPaymentOptions
                          ? colorScheme.primary
                          : colorScheme.primary.withValues(alpha: 0.6),
                    ),
                    label: Text(
                      _showAdvancedPaymentOptions
                          ? 'إخفاء خيارات الدفع'
                          : 'خيارات الدفع',
                    ),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 12,
                      ),
                    ),
                  ),
              ],
            ),
            if (_safeBoxes.isNotEmpty && _showAdvancedPaymentOptions) ...[
              const SizedBox(height: 20),
              DropdownButtonFormField<int>(
                initialValue: _selectedSafeBoxId,
                decoration: const InputDecoration(
                  labelText: 'الخزينة المستخدمة للدفع',
                  border: OutlineInputBorder(),
                ),
                items: _safeBoxes
                    .map(
                      (box) => DropdownMenuItem<int>(
                        value: box.id,
                        child: Row(
                          children: [
                            Icon(box.icon, color: box.typeColor, size: 18),
                            const SizedBox(width: 8),
                            Expanded(child: Text(box.name)),
                            if (box.isDefault)
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 6,
                                  vertical: 2,
                                ),
                                margin: const EdgeInsetsDirectional.only(
                                  start: 8,
                                ),
                                decoration: BoxDecoration(
                                  color: Colors.green.withValues(alpha: 0.15),
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: const Text(
                                  'افتراضي',
                                  style: TextStyle(
                                    fontSize: 11,
                                    color: Colors.green,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                    )
                    .toList(),
                onChanged: (value) {
                  setState(() {
                    _selectedSafeBoxId = value;
                  });
                },
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildGoldPriceCard() {
    if (_goldPrice == null) {
      return Card(
        color: const Color(0xFFFFF3CD),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: const [
              Text(
                'سعر الذهب',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
              SizedBox(height: 8),
              Text(
                'لم يتم تحميل سعر الذهب بعد. استخدم زر التحديث في الأعلى لإعادة المحاولة.',
              ),
            ],
          ),
        ),
      );
    }

    final chips = <Widget>[
      _buildPriceChip('عيار 24', _goldPrice!['price_24k']),
      _buildPriceChip('عيار 22', _goldPrice!['price_22k']),
      _buildPriceChip('عيار 21', _goldPrice!['price_21k']),
      _buildPriceChip('عيار 18', _goldPrice!['price_18k']),
    ];

    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Card(
      color: const Color(0xFFFAF5E4),
      elevation: isDark ? 1 : 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'سعر الذهب',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Wrap(spacing: 12, runSpacing: 8, children: chips),
          ],
        ),
      ),
    );
  }

  Widget _buildPriceChip(String label, dynamic value) {
    final price = _toDouble(value);
    final display = price > 0 ? price.toStringAsFixed(2) : '-';
    return Chip(
      label: Text('$label: $display ر.س'),
      backgroundColor: const Color(0xFFFFD700).withValues(alpha: 0.18),
    );
  }

  Widget _buildPricingModeCard() {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Card(
      elevation: isDark ? 1 : 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'طريقة التسعير',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            ToggleButtons(
              isSelected: [_manualPricing, !_manualPricing],
              borderRadius: BorderRadius.circular(12),
              onPressed: (index) {
                final manual = index == 0;
                if (manual == _manualPricing) return;
                setState(() {
                  _manualPricing = manual;
                  _applyCombinedTotals();
                });
              },
              children: const [
                Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16),
                  child: Text('تسعير يدوي لكل عيار'),
                ),
                Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16),
                  child: Text('تسعير تلقائي من سعر الذهب'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              _manualPricing
                  ? 'يمكنك إدخال القيم النقدية والضرائب لكل عيار يدوياً.'
                  : 'سيتم حساب قيمة الذهب والضرائب تلقائياً اعتماداً على الوزن وسعر الذهب الحالي.',
              style: const TextStyle(color: Colors.black54),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTotalsCard() {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Card(
      color: const Color(0xFFFFFAF0),
      elevation: isDark ? 1 : 3,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'ملخص الفاتورة',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            SwitchListTile.adaptive(
              contentPadding: EdgeInsets.zero,
              value: _applyVatOnGold,
              title: const Text('تطبيق ضريبة القيمة المضافة على قيمة الذهب'),
              subtitle: Text(
                _applyVatOnGold
                    ? 'سيتم احتساب الضريبة على قيمة الذهب وأجور المصنعية.'
                    : 'سيتم احتساب الضريبة على أجور المصنعية فقط.',
              ),
              onChanged: (value) {
                setState(() {
                  _applyVatOnGold = value;
                  _applyCombinedTotals();
                });
              },
            ),
            const SizedBox(height: 12),
            _buildSummaryRow('إجمالي الوزن', _formatWeight(_totalWeight)),
            _buildSummaryRow(
              'قيمة الذهب (قبل الضريبة)',
              _formatCurrency(_goldSubtotal),
            ),
            _buildSummaryRow('أجور المصنعية', _formatCurrency(_wageSubtotal)),
            const Divider(),
            _buildSummaryRow('ضريبة على الذهب', _formatCurrency(_goldTaxTotal)),
            _buildSummaryRow(
              'ضريبة على الأجور',
              _formatCurrency(_wageTaxTotal),
            ),
            const Divider(),
            _buildSummaryRow(
              'الإجمالي قبل الضريبة',
              _formatCurrency(_subtotal),
            ),
            _buildSummaryRow('إجمالي الضريبة', _formatCurrency(_taxTotal)),
            const Divider(),
            _buildSummaryRow(
              'الإجمالي الكلي',
              _formatCurrency(_grandTotal),
              highlight: true,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildWagePostingModeCard() {
    final selection = _wagePostingMode;
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Card(
      elevation: isDark ? 1 : 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'معالجة أجور المصنعية',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            ToggleButtons(
              isSelected: [selection == 'expense', selection == 'inventory'],
              borderRadius: BorderRadius.circular(12),
              onPressed: (index) {
                final mode = index == 0 ? 'expense' : 'inventory';
                if (mode == _wagePostingMode) {
                  return;
                }
                setState(() {
                  _wagePostingMode = mode;
                });
              },
              children: const [
                Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16),
                  child: Text('تحميل على المصروفات'),
                ),
                Padding(
                  padding: EdgeInsets.symmetric(horizontal: 16),
                  child: Text('رسملة ضمن المخزون'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              selection == 'inventory'
                  ? 'سيتم رسملة أجور المصنعية ضمن حساب المخزون أو الحساب المحدد في الربط المحاسبي.'
                  : 'سيتم تحميل أجور المصنعية مباشرةً على حساب المصروفات أو تكلفة المبيعات.',
              style: const TextStyle(color: Colors.black54),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSettlementCard() {
    final weightSummary = _aggregateWeightByKarat();
    final cashDue = _round(_wageSubtotal + _goldTaxTotal + _wageTaxTotal, 2);

    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Card(
      elevation: isDark ? 1 : 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'مستحقات المورد',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                _buildMetricTile(
                  icon: Icons.scale,
                  label: 'ذهب مستحق',
                  value: _totalWeight > 0
                      ? _formatWeight(_totalWeight)
                      : '0.000 جم',
                  iconColor: const Color(0xFFDAA520),
                ),
                _buildMetricTile(
                  icon: Icons.payments_outlined,
                  label: 'نقد مستحق',
                  value: _formatCurrency(cashDue),
                  iconColor: Colors.green.shade700,
                ),
                _buildMetricTile(
                  icon: Icons.design_services,
                  label: 'أجور مصنعية',
                  value: _formatCurrency(_wageSubtotal),
                ),
                _buildMetricTile(
                  icon: Icons.receipt_long,
                  label: 'إجمالي الضرائب',
                  value: _formatCurrency(_goldTaxTotal + _wageTaxTotal),
                ),
              ],
            ),
            if (weightSummary.isNotEmpty) ...[
              const SizedBox(height: 16),
              const Divider(),
              const SizedBox(height: 8),
              const Text(
                'توزيع العيارات',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: weightSummary.entries.map((entry) {
                  final karatLabel = entry.key;
                  final weightValue = entry.value;
                  return Chip(
                    backgroundColor: const Color(0xFFFFD700).withValues(alpha: 0.12),
                    label: Text(
                      'عيار $karatLabel: ${_formatWeight(weightValue)}',
                    ),
                  );
                }).toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildMetricTile({
    required IconData icon,
    required String label,
    required String value,
    Color? iconColor,
  }) {
    final Color resolvedIconColor = iconColor ?? Colors.blueGrey.shade600;
    return Container(
      constraints: const BoxConstraints(minWidth: 160),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.grey.shade100,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey.shade300),
      ),
      child: Row(
        children: [
          CircleAvatar(
            radius: 16,
            backgroundColor: resolvedIconColor.withValues(alpha: 0.12),
            child: Icon(icon, color: resolvedIconColor, size: 18),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  label,
                  style: const TextStyle(fontSize: 12, color: Colors.black54),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSummaryRow(
    String label,
    String value, {
    bool highlight = false,
  }) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: TextStyle(
              fontWeight: highlight ? FontWeight.bold : FontWeight.normal,
              color: isDark ? Colors.white : Colors.black87,
            ),
          ),
          Text(
            value,
            style: TextStyle(
              fontWeight: highlight ? FontWeight.bold : FontWeight.normal,
              color: highlight 
                  ? (isDark ? Colors.green[300] : Colors.green[700])
                  : (isDark ? Colors.white : Colors.black87),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInlineItemsSection() {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Card(
      elevation: isDark ? 1 : 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Text(
                        'الأصناف داخل الفاتورة',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                      ),
                      SizedBox(height: 4),
                      Text(
                        'أدخل وزناً واحداً للصنف أو ألصق عدة أوزان لنفس الصنف دفعة واحدة.',
                        style: TextStyle(color: Colors.black54),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    FilledButton.icon(
                      onPressed: _addInlineItem,
                      icon: const Icon(Icons.add_circle_outline),
                      label: const Text('إضافة وزن واحد'),
                    ),
                    OutlinedButton.icon(
                      onPressed: _addInlineItemsBulk,
                      icon: const Icon(Icons.playlist_add),
                      label: const Text('إضافة عدة أوزان'),
                    ),
                  ],
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (_inlineItems.isEmpty)
                  _buildInlineItemsEmptyState()
            else ...[
              _buildInlineItemsMetrics(),
              const SizedBox(height: 12),
              _buildInlineWeightChips(),
              const SizedBox(height: 12),
              _buildInlineItemsTable(),
            ],
            const SizedBox(height: 16),
            _buildSaveInvoiceButton(),
          ],
        ),
      ),
    );
  }

  Widget _buildSaveInvoiceButton() {
    final theme = Theme.of(context);
    return Align(
      alignment: AlignmentDirectional.centerEnd,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: FilledButton.icon(
          onPressed: _isSavingInvoice ? null : _saveInvoice,
          icon: _isSavingInvoice
              ? SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: theme.colorScheme.onPrimary,
                  ),
                )
              : const Icon(Icons.save_alt),
          label: Text(
            _isSavingInvoice ? 'جارٍ الحفظ...' : 'حفظ الفاتورة',
          ),
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(
              horizontal: 24,
              vertical: 16,
            ),
            textStyle: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildInlineItemsMetrics() {
    final entries = <Widget>[
      _buildInlineMetricChip('عدد الأصناف', _inlineItems.length.toString()),
      _buildInlineMetricChip('إجمالي الوزن', _formatWeight(_inlineTotalWeight)),
      _buildInlineMetricChip('أجور المصنعية', _formatCurrency(_inlineTotalWage)),
    ];

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: entries,
    );
  }

  Widget _buildInlineMetricChip(String label, String value) {
    return Chip(
      backgroundColor: const Color(0xFFFFD700).withValues(alpha: 0.14),
      label: Text('$label: $value'),
    );
  }

  Widget _buildInlineWeightChips() {
    final summary = _aggregateInlineWeightByKarat();
    if (summary.isEmpty) {
      return const SizedBox.shrink();
    }

    final entries = summary.entries.toList()
      ..sort(
        (a, b) => (double.tryParse(a.key) ?? 0).compareTo(
          double.tryParse(b.key) ?? 0,
        ),
      );

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: entries
          .map(
            (entry) => Chip(
              backgroundColor: const Color(0xFFFAF5E4),
              label: Text('عيار ${entry.key}: ${_formatWeight(entry.value)}'),
            ),
          )
          .toList(),
    );
  }

  Widget _buildInlineItemsEmptyState() {
    return Column(
      children: const [
        SizedBox(height: 16),
        Icon(Icons.inventory_outlined, size: 64, color: Colors.grey),
        SizedBox(height: 12),
        Text('لا توجد أصناف بعد. استخدم زر "إضافة وزن واحد" أو "إضافة عدة أوزان".'),
      ],
    );
  }

  Widget _buildInlineItemsTable() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        columns: const [
          DataColumn(label: Text('الصنف')),
          DataColumn(label: Text('العيار')),
          DataColumn(label: Text('الوزن (جم)')),
          DataColumn(label: Text('أجرة/جرام')),
          DataColumn(label: Text('أجور كلية')),
          DataColumn(label: Text('أحجار')),
          DataColumn(label: Text('ملاحظات')),
          DataColumn(label: Text('إجراءات')),
        ],
        rows: [
          for (int index = 0; index < _inlineItems.length; index++)
            _buildInlineItemRow(_inlineItems[index], index),
        ],
      ),
    );
  }

  int? _categoryIdForName(String? name) {
    if (name == null || name.isEmpty) return null;
    try {
      return _categories.firstWhere((category) => category.name == name).id;
    } catch (_) {
      return null;
    }
  }

  List<DropdownMenuItem<String?>> _buildCategoryDropdownItems() {
    final items = <DropdownMenuItem<String?>>[
      const DropdownMenuItem<String?>(
        value: null,
        child: Text('بدون تصنيف'),
      ),
    ];

    for (final category in _categories) {
      items.add(
        DropdownMenuItem<String?>(
          value: category.name,
          child: Text(category.name),
        ),
      );
    }

    return items;
  }

  InputDecoration _categoryDropdownDecoration({
    String labelText = 'التصنيف (اختياري)',
  }) {
    return InputDecoration(
      labelText: labelText,
      border: const OutlineInputBorder(),
      prefixIcon: const Icon(Icons.category_outlined),
      helperText: _categoriesError ??
          (_categories.isEmpty ? 'لا توجد تصنيفات متاحة حالياً.' : null),
    );
  }

  DataRow _buildInlineItemRow(PurchaseInlineItem item, int index) {
    return DataRow(
      cells: [
        DataCell(Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(item.name, style: const TextStyle(fontWeight: FontWeight.bold)),
            if (item.category?.isNotEmpty ?? false)
              Text('تصنيف: ${item.category}', style: const TextStyle(fontSize: 12)),
            if (item.itemCode?.isNotEmpty ?? false)
              Text('كود: ${item.itemCode}', style: const TextStyle(fontSize: 12)),
            if (item.barcode?.isNotEmpty ?? false)
              Text('باركود: ${item.barcode}', style: const TextStyle(fontSize: 12)),
          ],
        )),
        DataCell(Text(item.karat.toStringAsFixed(0))),
        DataCell(Text(item.weightGrams.toStringAsFixed(3))),
        DataCell(Text(item.wagePerGram.toStringAsFixed(2))),
        DataCell(Text((item.weightGrams * item.wagePerGram).toStringAsFixed(2))),
        DataCell(Text(item.hasStones ? 'نعم' : '-')),
        DataCell(
          item.description == null || item.description!.isEmpty
              ? const Text('-')
              : Tooltip(
                  message: item.description!,
                  child: Text(
                    item.description!,
                    overflow: TextOverflow.ellipsis,
                    maxLines: 1,
                  ),
                ),
        ),
        DataCell(Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            IconButton(
              icon: const Icon(Icons.edit),
              tooltip: 'تعديل',
              onPressed: () => _editInlineItem(index),
            ),
            IconButton(
              icon: const Icon(Icons.delete, color: Colors.red),
              tooltip: 'حذف',
              onPressed: () => _removeInlineItem(index),
            ),
          ],
        )),
      ],
    );
  }

  Future<PurchaseInlineItem?> _showInlineItemDialog({
    PurchaseInlineItem? existing,
  }) async {
    final nameController = TextEditingController(text: existing?.name ?? '');
    final weightController = TextEditingController(
      text: existing != null ? existing.weightGrams.toStringAsFixed(3) : '',
    );
    final wageController = TextEditingController(
      text: existing != null ? existing.wagePerGram.toStringAsFixed(2) : '0',
    );
    final descriptionController =
        TextEditingController(text: existing?.description ?? '');
    final itemCodeController =
        TextEditingController(text: existing?.itemCode ?? '');
    final barcodeController =
        TextEditingController(text: existing?.barcode ?? '');
    final stonesWeightController = TextEditingController(
      text: existing != null && existing.stonesWeight > 0
          ? existing.stonesWeight.toStringAsFixed(3)
          : '',
    );
    final stonesValueController = TextEditingController(
      text: existing != null && existing.stonesValue > 0
          ? existing.stonesValue.toStringAsFixed(2)
          : '',
    );

    nameController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: nameController.text.length,
    );
    weightController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: weightController.text.length,
    );
    wageController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: wageController.text.length,
    );
    descriptionController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: descriptionController.text.length,
    );
    itemCodeController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: itemCodeController.text.length,
    );
    barcodeController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: barcodeController.text.length,
    );
    stonesWeightController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: stonesWeightController.text.length,
    );
    stonesValueController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: stonesValueController.text.length,
    );

    double karat = existing?.karat ?? 21;
    bool hasStones = existing?.hasStones ?? false;
  String? selectedCategoryName =
    (existing?.category?.isNotEmpty ?? false) ? existing!.category : null;
  int? selectedCategoryId =
    existing?.categoryId ?? _categoryIdForName(selectedCategoryName);

    final result = await showDialog<PurchaseInlineItem>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            final weight = double.tryParse(weightController.text) ?? 0;
            final wagePerGram = double.tryParse(wageController.text) ?? 0;
            final stonesWeight =
                double.tryParse(stonesWeightController.text) ?? 0;
            final stonesValue =
                double.tryParse(stonesValueController.text) ?? 0;
            final categoryItems = _buildCategoryDropdownItems();
            final hasCategoryValue = categoryItems
                .any((item) => item.value == selectedCategoryName);
            final dropdownCategoryValue =
                hasCategoryValue ? selectedCategoryName : null;
            if (!hasCategoryValue && selectedCategoryName != null) {
              selectedCategoryName = null;
              selectedCategoryId = null;
            }

            return AlertDialog(
              title: Text(
                existing == null ? 'إضافة صنف' : 'تعديل الصنف',
              ),
              content: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      controller: nameController,
                      decoration: const InputDecoration(
                        labelText: 'اسم الصنف',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.title),
                      ),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<double>(
                      initialValue: karat,
                      decoration: const InputDecoration(
                        labelText: 'العيار',
                        border: OutlineInputBorder(),
                      ),
                      items: const [18.0, 21.0, 22.0, 24.0]
                          .map(
                            (value) => DropdownMenuItem<double>(
                              value: value,
                              child: Text(value.toStringAsFixed(0)),
                            ),
                          )
                          .toList(),
                      onChanged: (value) {
                        if (value == null) return;
                        setDialogState(() {
                          karat = value;
                        });
                      },
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: weightController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      inputFormatters: [
                        NormalizeNumberFormatter(),
                        FilteringTextInputFormatter.allow(
                          RegExp(r'^[0-9]*\.?[0-9]*$'),
                        ),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'الوزن (جرام)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.scale),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: wageController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      inputFormatters: [
                        NormalizeNumberFormatter(),
                        FilteringTextInputFormatter.allow(
                          RegExp(r'^[0-9]*\.?[0-9]*$'),
                        ),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'أجور المصنعية (ريال/جرام)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.design_services),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: descriptionController,
                      maxLines: 2,
                      decoration: const InputDecoration(
                        labelText: 'ملاحظات (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.sticky_note_2_outlined),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: itemCodeController,
                      decoration: const InputDecoration(
                        labelText: 'كود الصنف (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.tag),
                      ),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String?>(
                      initialValue: dropdownCategoryValue,
                      items: categoryItems,
                      isExpanded: true,
            onChanged: _isLoadingCategories
              ? null
              : (value) => setDialogState(() {
                selectedCategoryName = value;
                selectedCategoryId =
                  _categoryIdForName(value);
                }),
                      decoration: _categoryDropdownDecoration(),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: barcodeController,
                      decoration: const InputDecoration(
                        labelText: 'الباركود (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.qr_code_2),
                      ),
                    ),
                    const SizedBox(height: 12),
                    SwitchListTile(
                      title: const Text('يتضمن أحجاراً أو إضافات'),
                      contentPadding: EdgeInsets.zero,
                      value: hasStones,
                      onChanged: (value) => setDialogState(() {
                        hasStones = value;
                      }),
                    ),
                    if (hasStones) ...[
                      TextField(
                        controller: stonesWeightController,
                        keyboardType: const TextInputType.numberWithOptions(
                          decimal: true,
                        ),
                        inputFormatters: [
                          NormalizeNumberFormatter(),
                          FilteringTextInputFormatter.allow(
                            RegExp(r'^[0-9]*\.?[0-9]*$'),
                          ),
                        ],
                        decoration: const InputDecoration(
                          labelText: 'وزن الأحجار (جم)',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.diamond),
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: stonesValueController,
                        keyboardType: const TextInputType.numberWithOptions(
                          decimal: true,
                        ),
                        inputFormatters: [
                          NormalizeNumberFormatter(),
                          FilteringTextInputFormatter.allow(
                            RegExp(r'^[0-9]*\.?[0-9]*$'),
                          ),
                        ],
                        decoration: const InputDecoration(
                          labelText: 'قيمة الأحجار (ريال)',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.attach_money),
                        ),
                      ),
                    ],
                    const SizedBox(height: 16),
                    Card(
                      color: const Color(0xFFFAF5E4),
                      margin: EdgeInsets.zero,
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'معاينة سريعة',
                              style: TextStyle(fontWeight: FontWeight.bold),
                            ),
                            const SizedBox(height: 8),
                            _previewRow(
                              'الوزن',
                              _formatWeight(weight),
                            ),
                            _previewRow(
                              'أجور المصنعية',
                              _formatCurrency(weight * wagePerGram),
                            ),
                            if (hasStones)
                              _previewRow(
                                'وزن الأحجار',
                                _formatWeight(stonesWeight),
                              ),
                            if (hasStones)
                              _previewRow(
                                'قيمة الأحجار',
                                _formatCurrency(stonesValue),
                              ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: const Text('إلغاء'),
                ),
                FilledButton.icon(
                  onPressed: () {
                    final name = nameController.text.trim();
                    final parsedWeight =
                        double.tryParse(weightController.text) ?? 0;
                    final parsedWage =
                        double.tryParse(wageController.text) ?? 0;

                    if (name.isEmpty || parsedWeight <= 0) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content:
                              Text('الاسم والوزن مطلوبان لإضافة الصنف'),
                        ),
                      );
                      return;
                    }

                    Navigator.of(dialogContext).pop(
                      PurchaseInlineItem(
                        name: name,
                        karat: karat,
                        weightGrams: parsedWeight,
                        wagePerGram: parsedWage,
                        description:
                            descriptionController.text.trim().isEmpty
                                ? null
                                : descriptionController.text.trim(),
                        itemCode: itemCodeController.text.trim().isEmpty
                            ? null
                            : itemCodeController.text.trim(),
                        barcode: barcodeController.text.trim().isEmpty
                            ? null
                            : barcodeController.text.trim(),
                        category: selectedCategoryName,
                        categoryId: selectedCategoryId,
                        hasStones: hasStones,
                        stonesWeight: hasStones ? stonesWeight : 0,
                        stonesValue: hasStones ? stonesValue : 0,
                      ),
                    );
                  },
                  icon: const Icon(Icons.save),
                  label: Text(existing == null ? 'إضافة' : 'تحديث'),
                ),
              ],
            );
          },
        );
      },
    );

    nameController.dispose();
    weightController.dispose();
    wageController.dispose();
    descriptionController.dispose();
    itemCodeController.dispose();
    barcodeController.dispose();
    stonesWeightController.dispose();
    stonesValueController.dispose();

    return result;
  }

  Future<_InlineBulkResult?> _showInlineBulkDialog() async {
    final nameController = TextEditingController();
    final weightsController = TextEditingController();
    final wageController = TextEditingController(text: '0');
    final descriptionController = TextEditingController();
  final itemCodeController = TextEditingController();
  final barcodeController = TextEditingController();
  double karat = 21;
    String? selectedCategoryName;
  int? selectedCategoryId;
  final weightsFocusNode = FocusNode();

    wageController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: wageController.text.length,
    );

    List<double> parseWeights(String input) {
      final tokens = input
          .split(RegExp(r'[\s,;،]+'))
          .map((token) => token.trim())
          .where((token) => token.isNotEmpty)
          .toList();

      final values = <double>[];
      for (final token in tokens) {
        final normalized = token.replaceAll(',', '.');
        final parsed = double.tryParse(normalized);
        if (parsed != null && parsed > 0) {
          values.add(parsed);
        }
      }
      return values;
    }

    final parentContext = context;

    final result = await showDialog<_InlineBulkResult>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            final parsedWeights = parseWeights(weightsController.text);
            final totalWeight = parsedWeights.fold<double>(
              0,
              (sum, value) => sum + value,
            );
            final categoryItems = _buildCategoryDropdownItems();
            final hasCategoryValue = categoryItems
                .any((item) => item.value == selectedCategoryName);
            final dropdownCategoryValue =
                hasCategoryValue ? selectedCategoryName : null;
            if (!hasCategoryValue && selectedCategoryName != null) {
              selectedCategoryName = null;
              selectedCategoryId = null;
            }

            void handleInsertNewline() {
              final selection = weightsController.selection;
              final text = weightsController.text;
              final start = selection.isValid
                  ? selection.start
                  : text.length;
              final end = selection.isValid
                  ? selection.end
                  : text.length;

              final updatedText = text.replaceRange(start, end, '\n');
              final caretOffset = start + 1;

              weightsController.value = TextEditingValue(
                text: updatedText,
                selection: TextSelection.collapsed(offset: caretOffset),
              );

              setDialogState(() {});
              weightsFocusNode.requestFocus();
            }

            return AlertDialog(
              title: const Text('إضافة عدة أوزان لنفس الصنف'),
              content: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      controller: nameController,
                      decoration: const InputDecoration(
                        labelText: 'اسم الصنف',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.inventory_2_outlined),
                      ),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<double>(
                      initialValue: karat,
                      decoration: const InputDecoration(
                        labelText: 'العيار',
                        border: OutlineInputBorder(),
                      ),
                      items: const [18.0, 21.0, 22.0, 24.0]
                          .map(
                            (value) => DropdownMenuItem<double>(
                              value: value,
                              child: Text(value.toStringAsFixed(0)),
                            ),
                          )
                          .toList(),
                      onChanged: (value) {
                        if (value == null) return;
                        setDialogState(() {
                          karat = value;
                        });
                      },
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: wageController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      inputFormatters: [
                        NormalizeNumberFormatter(),
                        FilteringTextInputFormatter.allow(
                          RegExp(r'^[0-9]*\.?[0-9]*$'),
                        ),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'أجرة المصنعية (ريال/جرام)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.design_services),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Shortcuts(
                      shortcuts: const <ShortcutActivator, Intent>{
                        SingleActivator(LogicalKeyboardKey.enter):
                            _InsertNewlineIntent(),
                        SingleActivator(LogicalKeyboardKey.numpadEnter):
                            _InsertNewlineIntent(),
                      },
                      child: Actions(
                        actions: <Type, Action<Intent>>{
                          _InsertNewlineIntent:
                              CallbackAction<_InsertNewlineIntent>(
                            onInvoke: (intent) {
                              handleInsertNewline();
                              return null;
                            },
                          ),
                        },
                        child: TextField(
                          focusNode: weightsFocusNode,
                          controller: weightsController,
                          keyboardType:
                              const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          inputFormatters: [
                            NormalizeNumberFormatter(),
                            FilteringTextInputFormatter.allow(
                              RegExp('[0-9\u0660-\u0669\u06F0-\u06F9.,،؛;\\s]'),
                            ),
                          ],
                          textInputAction: TextInputAction.newline,
                          minLines: 3,
                          maxLines: 6,
                          decoration: const InputDecoration(
                            labelText: 'الأوزان المراد إضافتها',
                            hintText: 'مثال:\n10.500\n9.350\n8.125',
                            helperText:
                                'افصل بين الأوزان بسطر جديد أو فاصلة أو مسافة.',
                            alignLabelWithHint: true,
                            border: OutlineInputBorder(),
                          ),
                          onChanged: (_) => setDialogState(() {}),
                          onEditingComplete: handleInsertNewline,
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      parsedWeights.isEmpty
                          ? 'لم يتم التعرف على أي وزن بعد.'
                          : 'سيتم إضافة ${parsedWeights.length} وزنًا بإجمالي ${_formatWeight(totalWeight)}',
                      style: TextStyle(
                        color: parsedWeights.isEmpty
                            ? Colors.redAccent
                            : Colors.green.shade700,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: descriptionController,
                      maxLines: 2,
                      decoration: const InputDecoration(
                        labelText: 'ملاحظات (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.note_alt_outlined),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: itemCodeController,
                      decoration: const InputDecoration(
                        labelText: 'كود الصنف (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.tag),
                      ),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String?>(
                      initialValue: dropdownCategoryValue,
                      items: categoryItems,
                      isExpanded: true,
                      onChanged: _isLoadingCategories
                          ? null
                          : (value) => setDialogState(() {
                                selectedCategoryName = value;
                                selectedCategoryId =
                                    _categoryIdForName(value);
                              }),
                      decoration: _categoryDropdownDecoration(),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: barcodeController,
                      decoration: const InputDecoration(
                        labelText: 'الباركود (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.qr_code_2),
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: const Text('إلغاء'),
                ),
                FilledButton.icon(
                  onPressed: () {
                    final name = nameController.text.trim();
                    final weights = parseWeights(weightsController.text);
                    final wage = double.tryParse(wageController.text) ?? 0;

                    if (name.isEmpty) {
                      ScaffoldMessenger.of(parentContext).showSnackBar(
                        const SnackBar(
                          content: Text('اسم الصنف مطلوب'),
                        ),
                      );
                      return;
                    }

                    if (weights.isEmpty) {
                      ScaffoldMessenger.of(parentContext).showSnackBar(
                        const SnackBar(
                          content: Text('أدخل وزناً واحداً على الأقل'),
                        ),
                      );
                      return;
                    }

                    if (wage < 0) {
                      ScaffoldMessenger.of(parentContext).showSnackBar(
                        const SnackBar(
                          content:
                              Text('لا يمكن أن تكون أجرة المصنعية سالبة'),
                        ),
                      );
                      return;
                    }

                    Navigator.of(dialogContext).pop(
                      _InlineBulkResult(
                        name: name,
                        karat: karat,
                        wagePerGram: wage,
                        weights: weights,
                        description: descriptionController.text.trim().isEmpty
                            ? null
                            : descriptionController.text.trim(),
                        itemCode: itemCodeController.text.trim().isEmpty
                            ? null
                            : itemCodeController.text.trim(),
                        barcode: barcodeController.text.trim().isEmpty
                            ? null
                            : barcodeController.text.trim(),
                        category: selectedCategoryName,
                        categoryId: selectedCategoryId,
                      ),
                    );
                  },
                  icon: const Icon(Icons.save_alt),
                  label: const Text('إضافة الأوزان'),
                ),
              ],
            );
          },
        );
      },
    );

    nameController.dispose();
    weightsController.dispose();
    wageController.dispose();
    descriptionController.dispose();
    itemCodeController.dispose();
    barcodeController.dispose();
    weightsFocusNode.dispose();

    return result;
  }

  Widget _buildKaratLinesSection() {
    final snapshots = _karatLines.map(_snapshotFor).toList();

    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Card(
      elevation: isDark ? 1 : 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'الأوزان اليدوية (اختياري)',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 4),
            const Text(
              'استخدم هذا القسم لإدخال أوزان مستلمة مباشرة بدون إنشاء صنف داخل الفاتورة.',
              style: TextStyle(color: Colors.black54),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                FilledButton.icon(
                  onPressed: _addManualKaratLine,
                  icon: const Icon(Icons.add_circle_outline),
                  label: const Text('إضافة وزن'),
                ),
                OutlinedButton.icon(
                  onPressed: _addBulkWeights,
                  icon: const Icon(Icons.playlist_add),
                  label: const Text('إضافة عدة أوزان'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (_karatLines.isNotEmpty) _buildKaratSummaryChips(),
            if (_karatLines.isNotEmpty) const SizedBox(height: 12),
            if (snapshots.isEmpty)
              _buildKaratLinesEmptyState()
            else
              _buildKaratLinesTable(snapshots),
          ],
        ),
      ),
    );
  }

  Widget _buildKaratSummaryChips() {
    final summary = _aggregateManualWeightByKarat();
    final entries = summary.entries.toList()
      ..sort(
        (a, b) => (double.tryParse(a.key) ?? 0).compareTo(
          double.tryParse(b.key) ?? 0,
        ),
      );

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: entries
          .map(
            (entry) => Chip(
              backgroundColor: const Color(0xFFFFD700).withValues(alpha: 0.15),
              label: Text('عيار ${entry.key}: ${_formatWeight(entry.value)}'),
            ),
          )
          .toList(),
    );
  }

  Widget _buildKaratLinesEmptyState() {
    return Column(
      children: const [
        SizedBox(height: 16),
        Icon(Icons.balance, size: 64, color: Colors.grey),
        SizedBox(height: 12),
        Text('لم يتم إضافة أسطر عيار بعد.'),
      ],
    );
  }

  Widget _buildKaratLinesTable(List<_KaratLineSnapshot> snapshots) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        columns: const [
          DataColumn(label: Text('العيار')),
          DataColumn(label: Text('الوزن (جم)')),
          DataColumn(label: Text('سعر/جرام')),
          DataColumn(label: Text('قيمة الذهب')),
          DataColumn(label: Text('أجور المصنعية')),
          DataColumn(label: Text('ضريبة الذهب')),
          DataColumn(label: Text('ضريبة الأجور')),
          DataColumn(label: Text('الإجمالي')),
          DataColumn(label: Text('ملاحظات')),
          DataColumn(label: Text('إجراءات')),
        ],
        rows: [
          for (int index = 0; index < snapshots.length; index++)
            _buildKaratLineRow(snapshots[index], index),
        ],
      ),
    );
  }

  DataRow _buildKaratLineRow(_KaratLineSnapshot snapshot, int index) {
    final description = snapshot.line.description;
    return DataRow(
      cells: [
        DataCell(Text(snapshot.line.karat.toStringAsFixed(0))),
        DataCell(Text(snapshot.weight.toStringAsFixed(3))),
        DataCell(
          Text(
            snapshot.pricePerGram > 0
                ? snapshot.pricePerGram.toStringAsFixed(2)
                : '-',
          ),
        ),
        DataCell(Text(snapshot.goldValue.toStringAsFixed(2))),
        DataCell(Text(snapshot.wageCash.toStringAsFixed(2))),
        DataCell(Text(snapshot.goldTax.toStringAsFixed(2))),
        DataCell(Text(snapshot.wageTax.toStringAsFixed(2))),
        DataCell(Text(snapshot.total.toStringAsFixed(2))),
        DataCell(
          description == null || description.isEmpty
              ? const Text('-')
              : Tooltip(
                  message: description,
                  child: Text(
                    description,
                    overflow: TextOverflow.ellipsis,
                    maxLines: 1,
                  ),
                ),
        ),
        DataCell(
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              IconButton(
                tooltip: 'تعديل',
                icon: const Icon(Icons.edit),
                onPressed: () => _editKaratLine(index),
              ),
              IconButton(
                tooltip: 'حذف',
                icon: const Icon(Icons.delete, color: Colors.red),
                onPressed: () => _removeKaratLine(index),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Future<PurchaseKaratLine?> _showKaratLineDialog({
    PurchaseKaratLine? existing,
  }) async {
    final weightController = TextEditingController(
      text: existing != null ? existing.weightGrams.toStringAsFixed(3) : '',
    );
    final wagePerGramController = TextEditingController(
      text: existing != null ? existing.wagePerGram.toStringAsFixed(2) : '0',
    );
    final goldValueController = TextEditingController(
      text: existing?.goldValueOverride != null
          ? existing!.goldValueOverride!.toStringAsFixed(2)
          : '',
    );
    final wageCashController = TextEditingController(
      text: existing?.wageCashOverride != null
          ? existing!.wageCashOverride!.toStringAsFixed(2)
          : '',
    );
    final goldTaxController = TextEditingController(
      text: existing?.goldTaxOverride != null
          ? existing!.goldTaxOverride!.toStringAsFixed(2)
          : '',
    );
    final wageTaxController = TextEditingController(
      text: existing?.wageTaxOverride != null
          ? existing!.wageTaxOverride!.toStringAsFixed(2)
          : '',
    );
    final notesController = TextEditingController(
      text: existing?.description ?? '',
    );

    double karat = existing?.karat ?? 21;

    final result = await showDialog<PurchaseKaratLine>(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            final weight = double.tryParse(weightController.text) ?? 0;
            final wagePerGram =
                double.tryParse(wagePerGramController.text) ?? 0;
            final autoPricePerGram = _resolveGoldPrice(karat);
            final autoGoldValue = weight * autoPricePerGram;
            final autoWageCash = weight * wagePerGram;
            final vatRate = _vatRateFromSettings();
            final exemptKarats = _vatExemptKaratsFromSettings();
            final karatInt = karat.round();
            final isGoldVatExempt = exemptKarats.contains(karatInt);
            final autoGoldTax = (_applyVatOnGold && !isGoldVatExempt)
              ? autoGoldValue * vatRate
              : 0.0;
            final autoWageTax = autoWageCash * vatRate;

            final manualGoldValue = double.tryParse(goldValueController.text);
            final manualWageCash = double.tryParse(wageCashController.text);
            final manualGoldTax = double.tryParse(goldTaxController.text);
            final manualWageTax = double.tryParse(wageTaxController.text);

            final effectiveGoldValue = _manualPricing
                ? (manualGoldValue ?? autoGoldValue)
                : autoGoldValue;
            final effectiveWageCash = _manualPricing
                ? (manualWageCash ?? autoWageCash)
                : autoWageCash;
            final effectiveGoldTax = _manualPricing
                ? (manualGoldTax ?? autoGoldTax)
                : autoGoldTax;
            final effectiveWageTax = _manualPricing
                ? (manualWageTax ?? autoWageTax)
                : autoWageTax;
            final total =
                effectiveGoldValue +
                effectiveWageCash +
                effectiveGoldTax +
                effectiveWageTax;

            return AlertDialog(
              title: Text(existing == null ? 'إضافة وزن' : 'تعديل سطر العيار'),
              content: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    DropdownButtonFormField<double>(
                      initialValue: karat,
                      decoration: const InputDecoration(
                        labelText: 'العيار',
                        border: OutlineInputBorder(),
                      ),
                      items: const [18.0, 21.0, 22.0, 24.0]
                          .map(
                            (value) => DropdownMenuItem<double>(
                              value: value,
                              child: Text(value.toStringAsFixed(0)),
                            ),
                          )
                          .toList(),
                      onChanged: (value) {
                        if (value == null) return;
                        setDialogState(() {
                          karat = value;
                        });
                      },
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: weightController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      inputFormatters: [
                        NormalizeNumberFormatter(),
                        FilteringTextInputFormatter.allow(
                          RegExp(r'^[0-9]*\.?[0-9]*$'),
                        ),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'الوزن (جرام)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.scale),
                      ),
                      onChanged: (_) => setDialogState(() {}),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: wagePerGramController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      inputFormatters: [
                        NormalizeNumberFormatter(),
                        FilteringTextInputFormatter.allow(
                          RegExp(r'^[0-9]*\.?[0-9]*$'),
                        ),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'أجرة المصنعية (ريال/جرام)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.build),
                      ),
                      onChanged: (_) => setDialogState(() {}),
                    ),
                    if (_manualPricing) ...[
                      const SizedBox(height: 12),
                      TextField(
                        controller: goldValueController,
                        keyboardType: const TextInputType.numberWithOptions(
                          decimal: true,
                        ),
                        inputFormatters: [
                          NormalizeNumberFormatter(),
                          FilteringTextInputFormatter.allow(
                            RegExp(r'^[0-9]*\.?[0-9]*$'),
                          ),
                        ],
                        decoration: const InputDecoration(
                          labelText: 'قيمة الذهب (ريال)',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.attach_money),
                        ),
                        onChanged: (_) => setDialogState(() {}),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: wageCashController,
                        keyboardType: const TextInputType.numberWithOptions(
                          decimal: true,
                        ),
                        inputFormatters: [
                          NormalizeNumberFormatter(),
                          FilteringTextInputFormatter.allow(
                            RegExp(r'^[0-9]*\.?[0-9]*$'),
                          ),
                        ],
                        decoration: const InputDecoration(
                          labelText: 'أجور المصنعية (ريال)',
                          border: OutlineInputBorder(),
                          prefixIcon: Icon(Icons.construction),
                        ),
                        onChanged: (_) => setDialogState(() {}),
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: goldTaxController,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                    decimal: true,
                                  ),
                              inputFormatters: [
                                NormalizeNumberFormatter(),
                                FilteringTextInputFormatter.allow(
                                  RegExp(r'^[0-9]*\.?[0-9]*$'),
                                ),
                              ],
                              decoration: const InputDecoration(
                                labelText: 'ضريبة الذهب',
                                border: OutlineInputBorder(),
                              ),
                              onChanged: (_) => setDialogState(() {}),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: TextField(
                              controller: wageTaxController,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                    decimal: true,
                                  ),
                              inputFormatters: [
                                NormalizeNumberFormatter(),
                                FilteringTextInputFormatter.allow(
                                  RegExp(r'^[0-9]*\.?[0-9]*$'),
                                ),
                              ],
                              decoration: const InputDecoration(
                                labelText: 'ضريبة الأجور',
                                border: OutlineInputBorder(),
                              ),
                              onChanged: (_) => setDialogState(() {}),
                            ),
                          ),
                        ],
                      ),
                    ],
                    const SizedBox(height: 12),
                    TextField(
                      controller: notesController,
                      decoration: const InputDecoration(
                        labelText: 'ملاحظات (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.note_alt_outlined),
                      ),
                      maxLines: 2,
                    ),
                    const SizedBox(height: 16),
                    Card(
                      color: const Color(0xFFFAF5E4),
                      margin: EdgeInsets.zero,
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'معاينة السطر',
                              style: TextStyle(fontWeight: FontWeight.bold),
                            ),
                            const SizedBox(height: 8),
                            _previewRow(
                              'قيمة الذهب',
                              _formatCurrency(effectiveGoldValue),
                            ),
                            _previewRow(
                              'أجور المصنعية',
                              _formatCurrency(effectiveWageCash),
                            ),
                            _previewRow(
                              'ضريبة الذهب',
                              _formatCurrency(effectiveGoldTax),
                            ),
                            _previewRow(
                              'ضريبة الأجور',
                              _formatCurrency(effectiveWageTax),
                            ),
                            const Divider(),
                            _previewRow(
                              'الإجمالي',
                              _formatCurrency(total),
                              highlight: true,
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: const Text('إلغاء'),
                ),
                ElevatedButton(
                  onPressed: () {
                    final weightValue =
                        double.tryParse(weightController.text) ?? 0;
                    final wageValue =
                        double.tryParse(wagePerGramController.text) ?? 0;
                    if (weightValue <= 0) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('يرجى إدخال وزن صحيح')),
                      );
                      return;
                    }
                    if (wageValue < 0) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                          content: Text('لا يمكن أن تكون أجرة المصنعية سالبة'),
                        ),
                      );
                      return;
                    }

                    Navigator.of(dialogContext).pop(
                      PurchaseKaratLine(
                        karat: karat,
                        weightGrams: weightValue,
                        wagePerGram: wageValue,
                        goldValueOverride: _manualPricing
                            ? manualGoldValue
                            : null,
                        wageCashOverride: _manualPricing
                            ? manualWageCash
                            : null,
                        goldTaxOverride: _manualPricing ? manualGoldTax : null,
                        wageTaxOverride: _manualPricing ? manualWageTax : null,
                        description: notesController.text.trim().isEmpty
                            ? null
                            : notesController.text.trim(),
                      ),
                    );
                  },
                  child: Text(existing == null ? 'إضافة' : 'تحديث'),
                ),
              ],
            );
          },
        );
      },
    );

    weightController.dispose();
    wagePerGramController.dispose();
    goldValueController.dispose();
    wageCashController.dispose();
    goldTaxController.dispose();
    wageTaxController.dispose();
    notesController.dispose();

    return result;
  }

  Future<_BulkWeightEntry?> _showBulkWeightsDialog() async {
    final weightsController = TextEditingController();
    final wageController = TextEditingController(text: '0');
    final notesController = TextEditingController();
    double karat = 21;

    wageController.selection = TextSelection(
      baseOffset: 0,
      extentOffset: wageController.text.length,
    );

    List<double> parseWeights(String input) {
      final tokens = input
          .split(RegExp(r'[\s,;،]+'))
          .map((token) => token.trim())
          .where((token) => token.isNotEmpty)
          .toList();
      final values = <double>[];
      for (final token in tokens) {
        final normalized = token.replaceAll(',', '.');
        final parsed = double.tryParse(normalized);
        if (parsed != null && parsed > 0) {
          values.add(parsed);
        }
      }
      return values;
    }

    final parentContext = context;

    final result = await showDialog<_BulkWeightEntry>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            final parsedWeights = parseWeights(weightsController.text);
            final totalWeight = parsedWeights.fold<double>(
              0,
              (sum, value) => sum + value,
            );
            final statusText = parsedWeights.isEmpty
                ? 'أدخل الأوزان المطلوب إضافتها (سطر لكل وزن).'
                : 'سيتم إضافة ${parsedWeights.length} وزنًا بإجمالي ${_formatWeight(totalWeight)}';

            return AlertDialog(
              title: const Text('إضافة عدة أوزان دفعة واحدة'),
              content: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    DropdownButtonFormField<double>(
                      initialValue: karat,
                      decoration: const InputDecoration(
                        labelText: 'العيار',
                        border: OutlineInputBorder(),
                      ),
                      items: const [18.0, 21.0, 22.0, 24.0]
                          .map(
                            (value) => DropdownMenuItem<double>(
                              value: value,
                              child: Text(value.toStringAsFixed(0)),
                            ),
                          )
                          .toList(),
                      onChanged: (value) {
                        if (value == null) return;
                        setDialogState(() {
                          karat = value;
                        });
                      },
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: wageController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      inputFormatters: [
                        NormalizeNumberFormatter(),
                        FilteringTextInputFormatter.allow(
                          RegExp(r'^[0-9]*\.?[0-9]*$'),
                        ),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'أجرة المصنعية (ريال/جرام)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.design_services),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: weightsController,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      inputFormatters: [
                        NormalizeNumberFormatter(),
                        FilteringTextInputFormatter.allow(
                          RegExp('[0-9\u0660-\u0669\u06F0-\u06F9.,،؛;\\s]'),
                        ),
                      ],
                      minLines: 3,
                      maxLines: 6,
                      decoration: const InputDecoration(
                        labelText: 'الأوزان المراد إضافتها',
                        hintText: 'مثال:\n2.350\n1.780\n0.955',
                        helperText: 'افصل بين الأوزان بسطر جديد أو مسافة أو فاصلة.',
                        alignLabelWithHint: true,
                        border: OutlineInputBorder(),
                      ),
                      onChanged: (_) => setDialogState(() {}),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      statusText,
                      style: TextStyle(
                        color: parsedWeights.isEmpty
                            ? Colors.redAccent
                            : Colors.green.shade700,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: notesController,
                      maxLines: 2,
                      decoration: const InputDecoration(
                        labelText: 'ملاحظات (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.note_alt_outlined),
                      ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(),
                  child: const Text('إلغاء'),
                ),
                FilledButton.icon(
                  onPressed: () {
                    final weights = parseWeights(weightsController.text);
                    if (weights.isEmpty) {
                      ScaffoldMessenger.of(parentContext).showSnackBar(
                        const SnackBar(
                          content: Text('يجب إضافة وزن واحد على الأقل'),
                        ),
                      );
                      return;
                    }

                    final wagePerGram =
                        double.tryParse(wageController.text) ?? 0;
                    if (wagePerGram < 0) {
                      ScaffoldMessenger.of(parentContext).showSnackBar(
                        const SnackBar(
                          content: Text('لا يمكن أن تكون أجرة المصنعية سالبة'),
                        ),
                      );
                      return;
                    }

                    Navigator.of(dialogContext).pop(
                      _BulkWeightEntry(
                        karat: karat,
                        wagePerGram: wagePerGram,
                        weights: weights,
                        notes: notesController.text.trim().isEmpty
                            ? null
                            : notesController.text.trim(),
                      ),
                    );
                  },
                  icon: const Icon(Icons.save_alt),
                  label: const Text('إضافة الأوزان'),
                ),
              ],
            );
          },
        );
      },
    );

    weightsController.dispose();
    wageController.dispose();
    notesController.dispose();

    return result;
  }

  Widget _previewRow(String label, String value, {bool highlight = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label),
          Text(
            value,
            style: TextStyle(
              fontWeight: highlight ? FontWeight.bold : FontWeight.normal,
              color: highlight ? Colors.green[800] : Colors.black,
            ),
          ),
        ],
      ),
    );
  }
}

class PurchaseKaratLine {
  final double karat;
  final double weightGrams;
  final double wagePerGram;
  final double? goldValueOverride;
  final double? wageCashOverride;
  final double? goldTaxOverride;
  final double? wageTaxOverride;
  final String? description;

  const PurchaseKaratLine({
    required this.karat,
    required this.weightGrams,
    required this.wagePerGram,
    this.goldValueOverride,
    this.wageCashOverride,
    this.goldTaxOverride,
    this.wageTaxOverride,
    this.description,
  });

  PurchaseKaratLine copyWith({
    double? karat,
    double? weightGrams,
    double? wagePerGram,
    double? goldValueOverride,
    double? wageCashOverride,
    double? goldTaxOverride,
    double? wageTaxOverride,
    String? description,
  }) {
    return PurchaseKaratLine(
      karat: karat ?? this.karat,
      weightGrams: weightGrams ?? this.weightGrams,
      wagePerGram: wagePerGram ?? this.wagePerGram,
      goldValueOverride: goldValueOverride ?? this.goldValueOverride,
      wageCashOverride: wageCashOverride ?? this.wageCashOverride,
      goldTaxOverride: goldTaxOverride ?? this.goldTaxOverride,
      wageTaxOverride: wageTaxOverride ?? this.wageTaxOverride,
      description: description ?? this.description,
    );
  }
}

class _BulkWeightEntry {
  final double karat;
  final double wagePerGram;
  final List<double> weights;
  final String? notes;

  const _BulkWeightEntry({
    required this.karat,
    required this.wagePerGram,
    required this.weights,
    this.notes,
  });
}

class _KaratLineSnapshot {
  final PurchaseKaratLine line;
  final double pricePerGram;
  final double weight;
  final double goldValue;
  final double wageCash;
  final double goldTax;
  final double wageTax;

  _KaratLineSnapshot({
    required this.line,
    required this.pricePerGram,
    required this.weight,
    required this.goldValue,
    required this.wageCash,
    required this.goldTax,
    required this.wageTax,
  });

  double get total => goldValue + wageCash + goldTax + wageTax;
}

class _KaratTotals {
  final double totalWeight;
  final double goldSubtotal;
  final double wageSubtotal;
  final double goldTaxTotal;
  final double wageTaxTotal;

  const _KaratTotals({
    required this.totalWeight,
    required this.goldSubtotal,
    required this.wageSubtotal,
    required this.goldTaxTotal,
    required this.wageTaxTotal,
  });

  static const _KaratTotals zero = _KaratTotals(
    totalWeight: 0,
    goldSubtotal: 0,
    wageSubtotal: 0,
    goldTaxTotal: 0,
    wageTaxTotal: 0,
  );

  double get subtotal => goldSubtotal + wageSubtotal;
  double get taxTotal => goldTaxTotal + wageTaxTotal;
  double get grandTotal => subtotal + taxTotal;
}

class _InlineKaratAggregate {
  double weight = 0;
  double goldValue = 0;
  double wageCash = 0;
  double goldTax = 0;
  double wageTax = 0;

  void add(_KaratLineSnapshot snapshot) {
    weight += snapshot.weight;
    goldValue += snapshot.goldValue;
    wageCash += snapshot.wageCash;
    goldTax += snapshot.goldTax;
    wageTax += snapshot.wageTax;
  }
}

class PurchaseInlineItem {
  final String name;
  final double karat;
  final double weightGrams;
  final double wagePerGram;
  final String? description;
  final bool hasStones;
  final double stonesWeight;
  final double stonesValue;
  final String? itemCode;
  final String? barcode;
  final String? category;
  final int? categoryId;

  const PurchaseInlineItem({
    required this.name,
    required this.karat,
    required this.weightGrams,
    required this.wagePerGram,
    this.description,
    this.hasStones = false,
    this.stonesWeight = 0,
    this.stonesValue = 0,
    this.itemCode,
    this.barcode,
    this.category,
    this.categoryId,
  });

  PurchaseInlineItem copyWith({
    String? name,
    double? karat,
    double? weightGrams,
    double? wagePerGram,
    String? description,
    bool? hasStones,
    double? stonesWeight,
    double? stonesValue,
    String? itemCode,
    String? barcode,
    String? category,
    int? categoryId,
  }) {
    return PurchaseInlineItem(
      name: name ?? this.name,
      karat: karat ?? this.karat,
      weightGrams: weightGrams ?? this.weightGrams,
      wagePerGram: wagePerGram ?? this.wagePerGram,
      description: description ?? this.description,
      hasStones: hasStones ?? this.hasStones,
      stonesWeight: stonesWeight ?? this.stonesWeight,
      stonesValue: stonesValue ?? this.stonesValue,
      itemCode: itemCode ?? this.itemCode,
      barcode: barcode ?? this.barcode,
      category: category ?? this.category,
      categoryId: categoryId ?? this.categoryId,
    );
  }

  Map<String, dynamic> toPayload() {
    return {
      'name': name,
      'karat': karat,
      'weight': weightGrams,
      'wage': wagePerGram,
      'description': description,
      'item_code': itemCode,
      'barcode': barcode,
      'has_stones': hasStones,
      'stones_weight': stonesWeight,
      'stones_value': stonesValue,
      'category': category,
      'category_id': categoryId,
      'create_inline': true,
    }..removeWhere((key, value) => value == null);
  }
}

class _InlineBulkResult {
  final String name;
  final double karat;
  final double wagePerGram;
  final List<double> weights;
  final String? description;
  final String? itemCode;
  final String? barcode;
  final String? category;
  final int? categoryId;

  const _InlineBulkResult({
    required this.name,
    required this.karat,
    required this.wagePerGram,
    required this.weights,
    this.description,
    this.itemCode,
    this.barcode,
    this.category,
    this.categoryId,
  });
}

class _InsertNewlineIntent extends Intent {
  const _InsertNewlineIntent();
}
