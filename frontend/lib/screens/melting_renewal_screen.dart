import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../api_service.dart';
import '../models/safe_box_model.dart';
import '../utils.dart';

/// شاشة التجديد والتكسير
/// تكسير: نقل ذهب من خزينة المعروض → صندوق الكسر، مع تسجيل فصوص خارجة
/// تجديد: نقل ذهب من خزينة المصدر → خزينة المعروض، مع تسجيل فصوص داخلة
class MeltingRenewalScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;

  const MeltingRenewalScreen({
    super.key,
    required this.api,
    this.isArabic = true,
  });

  @override
  State<MeltingRenewalScreen> createState() => _MeltingRenewalScreenState();
}

class _MeltingRenewalScreenState extends State<MeltingRenewalScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;

    const Color tabBg      = Color(0xFFB8860B); // ذهبي داكن
    const Color tabSelected = Colors.white;
    const Color tabUnselected = Color(0xFFFFE082); // ذهبي فاتح

    return Scaffold(
      appBar: AppBar(
        title: Text(isAr ? 'التجديد والتكسير' : 'Renewal & Melting'),
      ),
      body: Column(
        children: [
          // ── شريط التبويبات مستقل عن AppBar ────────────────────────
          Material(
            color: tabBg,
            elevation: 2,
            child: TabBar(
              controller: _tabController,
              labelColor: tabSelected,
              unselectedLabelColor: tabUnselected,
              labelStyle: const TextStyle(
                fontWeight: FontWeight.bold,
                fontSize: 15,
              ),
              unselectedLabelStyle: const TextStyle(
                fontWeight: FontWeight.normal,
                fontSize: 14,
              ),
              indicatorColor: Colors.white,
              indicatorWeight: 4,
              indicatorSize: TabBarIndicatorSize.tab,
              dividerColor: Colors.transparent,
              tabs: [
                Tab(
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.recycling, size: 22),
                      const SizedBox(width: 8),
                      Text(isAr ? 'تكسير المخزون' : 'Melting'),
                    ],
                  ),
                ),
                Tab(
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.auto_fix_high, size: 22),
                      const SizedBox(width: 8),
                      Text(isAr ? 'تجديد القطع' : 'Renewal'),
                    ],
                  ),
                ),
              ],
            ),
          ),

          // ── محتوى التبويبات ─────────────────────────────────────
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                _MeltingTab(api: widget.api, isArabic: isAr, opType: 'melting'),
                _MeltingTab(api: widget.api, isArabic: isAr, opType: 'renewal'),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ==================== تبويب موحد (تكسير أو تجديد) ====================
class _MeltingTab extends StatefulWidget {
  final ApiService api;
  final bool isArabic;
  final String opType; // 'melting' | 'renewal'

  const _MeltingTab({
    required this.api,
    required this.isArabic,
    required this.opType,
  });

  @override
  State<_MeltingTab> createState() => _MeltingTabState();
}

class _MeltingTabState extends State<_MeltingTab> {
  final _formKey = GlobalKey<FormState>();

  // خزائن
  List<SafeBoxModel> _goldSafes = [];
  int? _fromSafeId;
  int? _toSafeId;

  // عيارات
  static const List<int> _karats = [24, 22, 21, 18];
  int _fromKarat = 21;
  int _toKarat = 21;

  // أوزان
  final _goldWeightCtrl    = TextEditingController();
  final _stonesWeightCtrl  = TextEditingController();

  // حسابات الفصوص
  List<Map<String, dynamic>> _accounts = [];
  int? _stonesAccountId;

  // مصنعية تالفة (تكسير فقط) - مبلغ نقدي
  final _wageAmountCtrl = TextEditingController();
  List<Map<String, dynamic>> _wageAccounts = [];
  int? _wageAccountId;

  // ملاحظات
  final _notesCtrl = TextEditingController();

  bool _loading = false;
  bool _submitting = false;

  bool get _isMelting => widget.opType == 'melting';

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  @override
  void dispose() {
    _goldWeightCtrl.dispose();
    _stonesWeightCtrl.dispose();
    _wageAmountCtrl.dispose();
    _notesCtrl.dispose();
    super.dispose();
  }

  /// مفاتيح SharedPreferences (مختلفة لكل نوع عملية)
  String get _prefKeyFrom => 'mr_from_safe_${widget.opType}';
  String get _prefKeyTo   => 'mr_to_safe_${widget.opType}';

  /// يحفظ الخزائن المختارة بعد الإرسال الناجح
  Future<void> _saveLastUsed() async {
    final prefs = await SharedPreferences.getInstance();
    if (_fromSafeId != null) await prefs.setInt(_prefKeyFrom, _fromSafeId!);
    if (_toSafeId   != null) await prefs.setInt(_prefKeyTo,   _toSafeId!);
  }

  Future<void> _loadData() async {
    setState(() => _loading = true);
    try {
      final safes    = await widget.api.getSafeBoxBalances();
      final accounts = await widget.api.getAccounts();
      final prefs    = await SharedPreferences.getInstance();

      setState(() {
        _goldSafes = safes.where((s) => s.safeType == 'gold').toList();
        _accounts  = accounts
            .whereType<Map<String, dynamic>>()
            .where((a) {
              final t = (a['type'] ?? '').toString().toLowerCase();
              if (_isMelting) return t == 'expense' || t == 'asset';
              return t == 'revenue' || t == 'income';
            })
            .toList();

        // حسابات المصنعية التالفة: مصروف فقط
        _wageAccounts = accounts
            .whereType<Map<String, dynamic>>()
            .where((a) {
              final t = (a['type'] ?? '').toString().toLowerCase();
              return t == 'expense';
            })
            .toList();

        // ── الاختيار التلقائي ────────────────────────────────────
        // أولاً: جرّب الخزائن المستخدمة سابقاً (الأكثر اختياراً)
        final savedFrom = prefs.getInt(_prefKeyFrom);
        final savedTo   = prefs.getInt(_prefKeyTo);
        final validIds  = _goldSafes.map((s) => s.id).toSet();
        if (savedFrom != null && validIds.contains(savedFrom)) {
          _fromSafeId = savedFrom;
        }
        if (savedTo != null && validIds.contains(savedTo)) {
          _toSafeId = savedTo;
        }

        // ثانياً: كمل الناقص بالقواعد الافتراضية
        _autoSelectDefaults();
      });
    } catch (e) {
      _snack('خطأ في تحميل البيانات: $e', isError: true);
    } finally {
      setState(() => _loading = false);
    }
  }

  /// يكمل الاختيار التلقائي لأي خزينة لم تُختر بعد:
  /// • من:  آخر خزينة مُستخدمة (من prefs)، وإلا الأولى في القائمة
  /// • إلى: الخزينة الافتراضية (isDefault) أو التي تحوي "كسر" لعمليات التكسير
  /// • العيار: العيار ذو أعلى رصيد في الخزينة المصدر
  void _autoSelectDefaults() {
    if (_goldSafes.isEmpty) return;

    // خزينة المصدر: إن لم تُختر بعد، خذ الأولى في القائمة
    _fromSafeId ??= _goldSafes.first.id;

    // خزينة الوجهة للتكسير: isDefault أو اسمها يحوي "كسر"
    if (_isMelting) {
      final meltingBox = _goldSafes.firstWhere(
        (s) => s.isDefault,
        orElse: () => _goldSafes.firstWhere(
          (s) => s.name.contains('كسر') || s.name.toLowerCase().contains('scrap'),
          orElse: () => _goldSafes.last,
        ),
      );
      if (_toSafeId == null && meltingBox.id != _fromSafeId) {
        _toSafeId = meltingBox.id;
      }
    } else {
      // خزينة الوجهة للتجديد: isDefault
      final displayBox = _goldSafes.firstWhere(
        (s) => s.isDefault,
        orElse: () => _goldSafes.first,
      );
      if (_toSafeId == null && displayBox.id != _fromSafeId) {
        _toSafeId = displayBox.id;
      }
    }

    // إذا لم تُختر وجهة (كل الخزائن متشابهة في الشروط) نأخذ الأولى المختلفة عن المصدر
    if (_toSafeId == null || _toSafeId == _fromSafeId) {
      final other = _goldSafes.firstWhere(
        (s) => s.id != _fromSafeId,
        orElse: () => _goldSafes.first,
      );
      _toSafeId = other.id;
    }

    // العيار: أعلى عيار رصيداً في خزينة المصدر
    _autoSelectKarat();
  }

  /// يختار العيار ذا أعلى رصيد في الخزينة المصدر الحالية
  void _autoSelectKarat() {
    if (_fromSafeId == null) return;
    final safe = _goldSafes.firstWhere(
      (s) => s.id == _fromSafeId,
      orElse: () => _goldSafes.first,
    );
    final balances = {
      24: safe.goldBalance24k,
      22: safe.goldBalance22k,
      21: safe.goldBalance21k,
      18: safe.goldBalance18k,
    };
    final best = balances.entries
        .where((e) => e.value > 0)
        .fold<MapEntry<int, double>?>(
          null,
          (prev, e) => prev == null || e.value > prev.value ? e : prev,
        );
    if (best != null) {
      _fromKarat = best.key;
      _toKarat   = best.key;
    }
  }

  void _snack(String msg, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: isError ? Colors.red : Colors.green,
    ));
  }

  /// رصيد العيار المحدد في الخزينة المصدر
  double _fromAvailable() {
    if (_fromSafeId == null) return 0.0;
    final safe = _goldSafes.firstWhere(
      (s) => s.id == _fromSafeId,
      orElse: () => _goldSafes.first,
    );
    switch (_fromKarat) {
      case 18: return safe.goldBalance18k;
      case 21: return safe.goldBalance21k;
      case 22: return safe.goldBalance22k;
      case 24: return safe.goldBalance24k;
      default: return 0.0;
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_fromSafeId == null) {
      _snack(widget.isArabic ? 'اختر خزينة المصدر' : 'Select source safe', isError: true);
      return;
    }
    if (_toSafeId == null) {
      _snack(widget.isArabic ? 'اختر خزينة الوجهة' : 'Select destination safe', isError: true);
      return;
    }
    if (_fromSafeId == _toSafeId) {
      _snack(widget.isArabic ? 'المصدر والوجهة لا يمكن أن تكونا نفس الخزينة' : 'Source and destination must differ', isError: true);
      return;
    }

    final goldW   = double.tryParse(_goldWeightCtrl.text.trim()) ?? 0.0;
    final stonesW = double.tryParse(_stonesWeightCtrl.text.trim()) ?? 0.0;
    final wageAmt = double.tryParse(_wageAmountCtrl.text.trim()) ?? 0.0;

    if (goldW <= 0) {
      _snack(widget.isArabic ? 'أدخل وزن الذهب' : 'Enter gold weight', isError: true);
      return;
    }

    final available = _fromAvailable();
    if (goldW > available + 1e-6) {
      _snack(
        widget.isArabic
            ? 'الوزن المطلوب ($goldW جم) أكبر من الرصيد المتاح (${available.toStringAsFixed(3)} جم)'
            : 'Weight ($goldW g) exceeds available (${available.toStringAsFixed(3)} g)',
        isError: true,
      );
      return;
    }

    final opAr = _isMelting ? 'التكسير' : 'التجديد';
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(widget.isArabic ? 'تأكيد $opAr' : 'Confirm ${widget.opType}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _confirmRow(widget.isArabic ? 'وزن الذهب' : 'Gold weight', '${goldW.toStringAsFixed(3)} جم'),
            if (stonesW > 0) _confirmRow(widget.isArabic ? 'وزن الفصوص' : 'Stones weight', '${stonesW.toStringAsFixed(3)} جم'),
            if (wageAmt > 0) _confirmRow(widget.isArabic ? 'مصنعية تالفة' : 'Damaged wage', wageAmt.toStringAsFixed(2)),
            _confirmRow(widget.isArabic ? 'العيار الخارج' : 'From karat', '${_fromKarat}k'),
            _confirmRow(widget.isArabic ? 'العيار الداخل' : 'To karat', '${_toKarat}k'),
            const SizedBox(height: 10),
            if (_isMelting)
              Text(
                widget.isArabic
                    ? 'سيُقتطع الوزن من خزينة المعروض ويُنقل لصندوق الكسر'
                    : 'Weight will be moved from display safe to melting box',
                style: const TextStyle(fontSize: 12, color: Colors.orange),
              )
            else
              Text(
                widget.isArabic
                    ? 'سيُقتطع الوزن من المصدر ويُضاف لخزينة المعروض'
                    : 'Weight will be moved from source to display safe',
                style: const TextStyle(fontSize: 12, color: Colors.blue),
              ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(widget.isArabic ? 'إلغاء' : 'Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: _isMelting ? FilledButton.styleFrom(backgroundColor: Colors.orange[800]) : null,
            child: Text(widget.isArabic ? 'تأكيد' : 'Confirm'),
          ),
        ],
      ),
    );

    if (confirm != true || !mounted) return;
    setState(() => _submitting = true);
    try {
      final result = await widget.api.createMeltingRenewal(
        operationType: widget.opType,
        fromSafeBoxId: _fromSafeId!,
        toSafeBoxId: _toSafeId!,
        fromKarat: _fromKarat,
        toKarat: _toKarat,
        goldWeight: goldW,
        stonesWeight: stonesW > 0 ? stonesW : null,
        stonesRevenueAccountId: (!_isMelting && stonesW > 0) ? _stonesAccountId : null,
        stonesExpenseAccountId: (_isMelting && stonesW > 0) ? _stonesAccountId : null,
        damageWageAmount: (_isMelting && wageAmt > 0) ? wageAmt : null,
        damageWageAccountId: (_isMelting && wageAmt > 0) ? _wageAccountId : null,
        notes: _notesCtrl.text.trim().isEmpty ? null : _notesCtrl.text.trim(),
      );
      if (!mounted) return;
      final voucher = result['voucher'] as Map<String, dynamic>?;
      await _saveLastUsed(); // حفظ الاختيار للمرة القادمة
      _snack('${widget.isArabic ? "تم" : "Done"}: ${voucher?['voucher_number'] ?? ""}');
      _reset();
      _loadData(); // تحديث الأرصدة
    } catch (e) {
      if (!mounted) return;
      _snack('${widget.isArabic ? "فشل" : "Failed"}: $e', isError: true);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Widget _confirmRow(String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: const TextStyle(color: Colors.grey)),
        Text(value, style: const TextStyle(fontWeight: FontWeight.bold)),
      ],
    ),
  );

  void _reset() {
    setState(() {
      _fromSafeId = null;
      _toSafeId = null;
      _fromKarat = 21;
      _toKarat = 21;
      _stonesAccountId = null;
      _wageAmountCtrl.clear();
      _wageAccountId   = null;
      _goldWeightCtrl.clear();
      _stonesWeightCtrl.clear();
      _notesCtrl.clear();
      // إعادة الاختيار التلقائي
      _autoSelectDefaults();
    });
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);

    if (_loading) return const Center(child: CircularProgressIndicator());

    final available = _fromAvailable();
    final goldW = double.tryParse(_goldWeightCtrl.text.trim()) ?? 0.0;
    final overGold = goldW > 0 && goldW > available + 1e-6;

    return Form(
      key: _formKey,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [

          // ── معلومة توضيحية ──────────────────────────────────────────
          Card(
            color: _isMelting ? Colors.orange[50] : Colors.blue[50],
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(children: [
                Icon(
                  _isMelting ? Icons.delete_sweep : Icons.auto_fix_high,
                  color: _isMelting ? Colors.orange[700] : Colors.blue[700],
                ),
                const SizedBox(width: 10),
                Expanded(child: Text(
                  isAr
                      ? (_isMelting
                          ? 'نقل ذهب من خزينة المعروض إلى صندوق الكسر. الفصوص الخارجة تُسجَّل كمصروف وزني.'
                          : 'نقل ذهب من مصدر إلى خزينة المعروض. الفصوص الداخلة تُسجَّل كإيراد وزني.')
                      : (_isMelting
                          ? 'Move gold from display safe to melting box. Outgoing stones recorded as weight expense.'
                          : 'Move gold from source to display safe. Incoming stones recorded as weight revenue.'),
                  style: TextStyle(
                    color: _isMelting ? Colors.orange[900] : Colors.blue[900],
                    fontSize: 12,
                  ),
                )),
              ]),
            ),
          ),

          const SizedBox(height: 16),

          // ── خزينة المصدر ────────────────────────────────────────────
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    isAr ? 'خزينة المصدر (الخروج)' : 'Source Safe (Out)',
                    style: theme.textTheme.titleSmall,
                  ),
                  const SizedBox(height: 10),
                  DropdownButtonFormField<int>(
                    value: _fromSafeId,
                    decoration: InputDecoration(
                      labelText: isAr ? 'من خزينة' : 'From Safe',
                      prefixIcon: const Icon(Icons.lock_open),
                      border: const OutlineInputBorder(),
                    ),
                    items: _goldSafes.map((s) => DropdownMenuItem(
                      value: s.id,
                      child: Text(s.name),
                    )).toList(),
                    onChanged: (v) => setState(() { _fromSafeId = v; _autoSelectKarat(); }),
                    validator: (v) => v == null ? (isAr ? 'مطلوب' : 'Required') : null,
                  ),
                  const SizedBox(height: 8),

                  // عيار الخروج
                  DropdownButtonFormField<int>(
                    value: _fromKarat,
                    decoration: InputDecoration(
                      labelText: isAr ? 'العيار الخارج' : 'From Karat',
                      prefixIcon: const Icon(Icons.star_outline),
                      border: const OutlineInputBorder(),
                    ),
                    items: _karats.map((k) => DropdownMenuItem(
                      value: k,
                      child: Text('عيار $k'),
                    )).toList(),
                    onChanged: (v) => setState(() { _fromKarat = v ?? 21; }),
                  ),

                  // رصيد متاح
                  if (_fromSafeId != null) ...[
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: available > 0 ? Colors.green[50] : Colors.red[50],
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(children: [
                        Icon(Icons.info_outline,
                            size: 16, color: available > 0 ? Colors.green[700] : Colors.red),
                        const SizedBox(width: 6),
                        Text(
                          '${isAr ? 'الرصيد المتاح' : 'Available'}: ${available.toStringAsFixed(3)} جم (${_fromKarat}k)',
                          style: TextStyle(
                            fontSize: 12,
                            color: available > 0 ? Colors.green[900] : Colors.red,
                          ),
                        ),
                      ]),
                    ),
                  ],
                ],
              ),
            ),
          ),

          const SizedBox(height: 12),

          // ── خزينة الوجهة ────────────────────────────────────────────
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    isAr ? 'خزينة الوجهة (الدخول)' : 'Destination Safe (In)',
                    style: theme.textTheme.titleSmall,
                  ),
                  const SizedBox(height: 10),
                  DropdownButtonFormField<int>(
                    value: _toSafeId,
                    decoration: InputDecoration(
                      labelText: isAr ? 'إلى خزينة' : 'To Safe',
                      prefixIcon: const Icon(Icons.lock),
                      border: const OutlineInputBorder(),
                    ),
                    items: _goldSafes
                        .map((s) => DropdownMenuItem(
                          value: s.id,
                          child: Text(s.name),
                        ))
                        .toList(),
                    onChanged: (v) => setState(() { _toSafeId = v; }),
                    validator: (v) {
                      if (v == null) return isAr ? 'مطلوب' : 'Required';
                      if (v == _fromSafeId) return isAr ? 'يجب أن تختلف عن المصدر' : 'Must differ from source';
                      return null;
                    },
                  ),
                  const SizedBox(height: 8),

                  // عيار الدخول
                  DropdownButtonFormField<int>(
                    value: _toKarat,
                    decoration: InputDecoration(
                      labelText: isAr ? 'العيار الداخل' : 'To Karat',
                      prefixIcon: const Icon(Icons.star),
                      border: const OutlineInputBorder(),
                    ),
                    items: _karats.map((k) => DropdownMenuItem(
                      value: k,
                      child: Text('عيار $k'),
                    )).toList(),
                    onChanged: (v) => setState(() { _toKarat = v ?? 21; }),
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 12),

          // ── الأوزان ────────────────────────────────────────────────
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(isAr ? 'الأوزان' : 'Weights', style: theme.textTheme.titleSmall),
                  const SizedBox(height: 10),

                  // وزن الذهب
                  TextFormField(
                    controller: _goldWeightCtrl,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    inputFormatters: [NormalizeNumberFormatter()],
                    decoration: InputDecoration(
                      labelText: isAr ? 'وزن الذهب (جم)' : 'Gold Weight (g)',
                      prefixIcon: const Icon(Icons.scale),
                      suffixText: 'جم',
                      border: const OutlineInputBorder(),
                      errorText: overGold
                          ? (isAr
                              ? 'يتجاوز الرصيد المتاح (${available.toStringAsFixed(3)} جم)'
                              : 'Exceeds available (${available.toStringAsFixed(3)} g)')
                          : null,
                    ),
                    onChanged: (_) => setState(() {}),
                    validator: (v) {
                      if (v == null || v.trim().isEmpty) return isAr ? 'مطلوب' : 'Required';
                      final d = double.tryParse(v.trim());
                      if (d == null || d <= 0) return isAr ? 'وزن غير صحيح' : 'Invalid weight';
                      return null;
                    },
                  ),

                  const SizedBox(height: 12),

                  // وزن الفصوص (اختياري)
                  TextFormField(
                    controller: _stonesWeightCtrl,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    inputFormatters: [NormalizeNumberFormatter()],
                    decoration: InputDecoration(
                      labelText: isAr
                          ? (_isMelting ? 'وزن الفصوص الخارجة (اختياري)' : 'وزن الفصوص الداخلة (اختياري)')
                          : (_isMelting ? 'Outgoing stones weight (optional)' : 'Incoming stones weight (optional)'),
                      prefixIcon: const Icon(Icons.diamond_outlined),
                      suffixText: 'جم',
                      border: const OutlineInputBorder(),
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                ],
              ),
            ),
          ),

          // ── حساب الفصوص (يظهر فقط إذا أُدخل وزن فصوص) ──────────
          if ((double.tryParse(_stonesWeightCtrl.text.trim()) ?? 0) > 0) ...[
            const SizedBox(height: 12),
            Card(
              color: Colors.amber[50],
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      isAr
                          ? (_isMelting ? 'حساب مصروف الفصوص الخارجة' : 'حساب إيراد الفصوص الداخلة')
                          : (_isMelting ? 'Stones Expense Account' : 'Stones Revenue Account'),
                      style: theme.textTheme.titleSmall,
                    ),
                    const SizedBox(height: 10),
                    DropdownButtonFormField<int>(
                      value: _stonesAccountId,
                      decoration: InputDecoration(
                        labelText: isAr
                            ? (_isMelting ? 'حساب المصروف الوزني' : 'حساب الإيراد الوزني')
                            : (_isMelting ? 'Weight Expense Account' : 'Weight Revenue Account'),
                        prefixIcon: const Icon(Icons.account_balance_wallet_outlined),
                        border: const OutlineInputBorder(),
                      ),
                      items: _accounts.map((a) => DropdownMenuItem<int>(
                        value: a['id'] as int?,
                        child: Text(
                          '${a['account_number'] ?? ''} - ${a['name'] ?? ''}',
                          overflow: TextOverflow.ellipsis,
                        ),
                      )).toList(),
                      onChanged: (v) => setState(() { _stonesAccountId = v; }),
                    ),
                  ],
                ),
              ),
            ),
          ],

          // ── مصنعية تالفة (تكسير فقط) ──────────────────────────────
          if (_isMelting) ...[
            const SizedBox(height: 12),
            TextFormField(
              controller: _wageAmountCtrl,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              inputFormatters: [NormalizeNumberFormatter()],
              decoration: InputDecoration(
                labelText: isAr ? 'مبلغ المصنعية التالفة (اختياري)' : 'Damaged wage amount (optional)',
                prefixIcon: const Icon(Icons.construction_outlined),
                suffixText: 'ر.س',
                border: const OutlineInputBorder(),
                helperText: isAr
                    ? 'قيمة أجرة الصنعة المهدرة بسبب التكسير'
                    : 'Cash value of manufacturing wage lost due to melting',
              ),
              onChanged: (_) => setState(() {}),
            ),

            // حساب مصروف المصنعية التالفة (يظهر فقط إذا أُدخل مبلغ)
            if ((double.tryParse(_wageAmountCtrl.text.trim()) ?? 0) > 0) ...[
              const SizedBox(height: 12),
              Card(
                color: Colors.red[50],
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.warning_amber_rounded, color: Colors.deepOrange, size: 18),
                          const SizedBox(width: 6),
                          Text(
                            isAr ? 'حساب مصروف المصنعية التالفة' : 'Damaged Wage Expense Account',
                            style: theme.textTheme.titleSmall?.copyWith(color: Colors.deepOrange[800]),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      DropdownButtonFormField<int>(
                        value: _wageAccountId,
                        decoration: InputDecoration(
                          labelText: isAr ? 'حساب مصروف أجور المصنعية' : 'Manufacturing Wage Expense',
                          prefixIcon: const Icon(Icons.account_balance_outlined),
                          border: const OutlineInputBorder(),
                        ),
                        items: _wageAccounts.map((a) => DropdownMenuItem<int>(
                          value: a['id'] as int?,
                          child: Text(
                            '${a['account_number'] ?? ''} - ${a['name'] ?? ''}',
                            overflow: TextOverflow.ellipsis,
                          ),
                        )).toList(),
                        onChanged: (v) => setState(() { _wageAccountId = v; }),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ],

          const SizedBox(height: 12),

          // ── ملاحظات ────────────────────────────────────────────────
          TextFormField(
            controller: _notesCtrl,
            maxLines: 2,
            decoration: InputDecoration(
              labelText: isAr ? 'ملاحظات (اختياري)' : 'Notes (optional)',
              prefixIcon: const Icon(Icons.note_outlined),
              border: const OutlineInputBorder(),
            ),
          ),

          const SizedBox(height: 24),

          // ── أزرار ─────────────────────────────────────────────────
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _reset,
                icon: const Icon(Icons.clear),
                label: Text(isAr ? 'إعادة تعيين' : 'Reset'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              flex: 2,
              child: FilledButton.icon(
                onPressed: _submitting ? null : _submit,
                icon: _submitting
                    ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : Icon(_isMelting ? Icons.delete_sweep : Icons.auto_fix_high),
                style: _isMelting
                    ? FilledButton.styleFrom(backgroundColor: Colors.orange[800])
                    : null,
                label: Text(isAr
                    ? (_isMelting ? 'تنفيذ التكسير' : 'تنفيذ التجديد')
                    : (_isMelting ? 'Execute Melting' : 'Execute Renewal')),
              ),
            ),
          ]),

          const SizedBox(height: 32),
        ],
      ),
    );
  }
}

// ==================== Models (legacy - kept for compatibility) ====================

class RenewalItem {
  final String description;
  final double weight;
  final int karat;
  final double purchaseValue;

  RenewalItem({
    required this.description,
    required this.weight,
    required this.karat,
    required this.purchaseValue,
  });

  Map<String, dynamic> toJson() => {
    'description': description,
    'weight': weight,
    'karat': karat,
    'purchase_value': purchaseValue,
  };
}

class InventoryItem {
  final int itemId;
  final String itemCode;
  final String name;
  final double weight;
  final int karat;
  int quantity;

  InventoryItem({
    required this.itemId,
    required this.itemCode,
    required this.name,
    required this.weight,
    required this.karat,
    this.quantity = 1,
  });

  Map<String, dynamic> toJson() => {
    'item_id': itemId,
    'item_code': itemCode,
    'name': name,
    'weight': weight,
    'karat': karat,
    'quantity': quantity,
  };
}

