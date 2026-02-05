import 'package:flutter/material.dart';

import '../api_service.dart';
import '../models/safe_box_model.dart';
import '../theme/app_theme.dart';
import '../widgets/safe_box_picker_dialog.dart';

class WeightClosingExecuteScreen extends StatefulWidget {
  const WeightClosingExecuteScreen({super.key});

  @override
  State<WeightClosingExecuteScreen> createState() =>
      _WeightClosingExecuteScreenState();
}

class _WeightClosingExecuteScreenState extends State<WeightClosingExecuteScreen> {
  final ApiService _api = ApiService();
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();

  bool _isLoading = true;
  bool _isExecuting = false;

  List<Map<String, dynamic>> _profiles = const [];
  List<Map<String, dynamic>> _suppliers = const [];
  List<SafeBoxModel> _cashBankSafeBoxes = const [];

  String? _profileKey;
  int? _supplierId;
  int? _overrideCashSafeBoxId;

  final TextEditingController _cashAmountController = TextEditingController();
  final TextEditingController _weightMainController = TextEditingController();
  final TextEditingController _pricePerGramController = TextEditingController();
  final TextEditingController _notesController = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _cashAmountController.dispose();
    _weightMainController.dispose();
    _pricePerGramController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _isLoading = true);
    try {
      final profiles = await _api.getWeightClosingProfiles();
      final suppliersRaw = await _api.getSuppliers();
      final safes = await _api.getSafeBoxes(isActive: true, includeAccount: true);

      final suppliers = suppliersRaw
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();

      final cashBankSafes = safes
          .where((s) => (s.safeType == 'cash' || s.safeType == 'bank') && s.id != null)
          .toList()
        ..sort(
          (a, b) => a.safeType == b.safeType
              ? a.name.compareTo(b.name)
              : a.safeType.compareTo(b.safeType),
        );

      // Best-effort: fill price from gold price endpoint.
      try {
        final gold = await _api.getGoldPrice();
        final v = gold['price_per_gram_24k'];
        final price = (v is num) ? v.toDouble() : double.tryParse('$v');
        if (price != null && price > 0 && _pricePerGramController.text.isEmpty) {
          _pricePerGramController.text = price.toStringAsFixed(2);
        }
      } catch (_) {
        // ignore
      }

      if (!mounted) return;
      setState(() {
        _profiles = profiles;
        _suppliers = suppliers;
        _cashBankSafeBoxes = cashBankSafes;
        _profileKey = _profiles.isNotEmpty
            ? (_profiles.first['key']?.toString())
            : null;
      });
    } catch (e) {
      if (!mounted) return;
      _showSnack('تعذر تحميل بيانات التنفيذ: $e', isError: true);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Map<String, dynamic>? get _selectedProfile {
    final key = _profileKey;
    if (key == null) return null;
    try {
      return _profiles.firstWhere((p) => p['key']?.toString() == key);
    } catch (_) {
      return null;
    }
  }

  bool _profileFlag(String key) {
    final profile = _selectedProfile;
    if (profile == null) return false;

    final direct = profile[key];
    if (direct == true) return true;

    final meta = profile['meta'];
    if (meta is Map) {
      return meta[key] == true;
    }

    return false;
  }

  bool get _requiresCashAmount {
    return _profileFlag('requires_cash_amount');
  }

  bool get _requiresWeight {
    return _profileFlag('requires_weight');
  }

  String _profileDisplayName(Map<String, dynamic> profile) {
    final direct = profile['display_name']?.toString();
    if (direct != null && direct.trim().isNotEmpty) {
      return direct.trim();
    }

    final meta = profile['meta'];
    if (meta is Map) {
      final display = meta['display_name']?.toString();
      if (display != null && display.trim().isNotEmpty) {
        return display.trim();
      }
    }

    return profile['key']?.toString() ?? '';
  }

  Future<void> _pickCashSafeBox() async {
    if (_cashBankSafeBoxes.isEmpty) {
      _showSnack('لا توجد خزائن نقد/بنك فعالة', isError: true);
      return;
    }

    final chosen = await showDialog<SafeBoxModel>(
      context: context,
      builder: (_) => SafeBoxPickerDialog(
        safeBoxes: _cashBankSafeBoxes,
        selectedSafeBoxId: _overrideCashSafeBoxId,
        excludeGold: true,
      ),
    );

    if (!mounted || chosen == null) return;
    setState(() => _overrideCashSafeBoxId = chosen.id);
  }

  String _safeNameById(int? id) {
    if (id == null) return 'استخدم الافتراضي';
    final found = _cashBankSafeBoxes.where((s) => s.id == id).toList();
    if (found.isEmpty) return 'خزينة غير معروفة (#$id)';
    final sb = found.first;
    final typeLabel = sb.safeType == 'bank' ? 'بنك' : 'نقد';
    return '$typeLabel - ${sb.name}';
  }

  Future<void> _execute() async {
    if (_isExecuting) return;

    if (!_formKey.currentState!.validate()) {
      _showSnack('تحقق من الحقول المطلوبة', isError: true);
      return;
    }

    final profileKey = _profileKey;
    if (profileKey == null || profileKey.trim().isEmpty) {
      _showSnack('اختر بروفايل', isError: true);
      return;
    }

    final cashAmount = double.tryParse(_cashAmountController.text.trim());
    final weightMain = double.tryParse(_weightMainController.text.trim());
    final price = double.tryParse(_pricePerGramController.text.trim());

    if (_requiresCashAmount && (cashAmount == null || cashAmount <= 0)) {
      _showSnack('هذا البروفايل يتطلب مبلغ نقدي', isError: true);
      return;
    }

    if (_requiresWeight && (weightMain == null || weightMain <= 0)) {
      _showSnack('هذا البروفايل يتطلب وزن', isError: true);
      return;
    }

    setState(() => _isExecuting = true);
    try {
      final payload = <String, dynamic>{
        'profile_key': profileKey,
        if (_supplierId != null) 'supplier_id': _supplierId,
        if (_overrideCashSafeBoxId != null)
          'cash_safe_box_id': _overrideCashSafeBoxId,
        if (cashAmount != null && cashAmount > 0) 'cash_amount': cashAmount,
        if (weightMain != null && weightMain > 0)
          'weight_main_karat': weightMain,
        if (price != null && price > 0) 'price_per_gram': price,
        if (_notesController.text.trim().isNotEmpty)
          'notes': _notesController.text.trim(),
      };

      final resp = await _api.executeWeightClosingProfile(payload);
      if (!mounted) return;

      final profile = resp['profile'] is Map
          ? Map<String, dynamic>.from(resp['profile'] as Map)
          : <String, dynamic>{};
      final je = (resp['journal_entry'] as Map?) ?? const {};
      final entryNumber = je['entry_number']?.toString() ?? '';
      _showSnack(
        entryNumber.isNotEmpty
            ? '✅ تم التنفيذ بنجاح - قيد: $entryNumber'
            : '✅ تم التنفيذ بنجاح',
        isError: false,
      );

      showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('نتيجة التنفيذ'),
          content: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'البروفايل: ${profile['display_name']?.toString().trim().isNotEmpty == true ? profile['display_name'] : profileKey}',
                ),
                if (resp['cash_safe_box_id'] != null)
                  Text(
                    'خزينة التسوية: ${_safeNameById((resp['cash_safe_box_id'] as num?)?.toInt())}',
                  ),
                if (resp['cash_amount'] != null)
                  Text('المبلغ: ${resp['cash_amount']}'),
                if (resp['weight_main_karat'] != null)
                  Text('الوزن (عيار 21): ${resp['weight_main_karat']}'),
                if (resp['price_per_gram'] != null)
                  Text('السعر: ${resp['price_per_gram']}'),
                if (entryNumber.isNotEmpty) Text('القيد: $entryNumber'),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('إغلاق'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      _showSnack('فشل التنفيذ: $e', isError: true);
    } finally {
      if (mounted) setState(() => _isExecuting = false);
    }
  }

  void _showSnack(String message, {required bool isError}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? AppColors.error : AppColors.success,
      ),
    );
  }

  void _showInfoDialog() {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('ما هو التسكير الوزني؟'),
        content: const SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'هذه الشاشة لتنفيذ “بروفايل تسكير وزني” بشكل يدوي عند الحاجة. التنفيذ يقوم بإنشاء قيد يومية (Journal Entry) لتسوية فروقات/إغلاقات مبنية على الوزن، مع إمكانية تحديد خزينة التسوية (نقد/بنك).',
              ),
              SizedBox(height: 12),
              Text('متى نحتاجها؟', style: TextStyle(fontWeight: FontWeight.bold)),
              SizedBox(height: 6),
              Text('• عند وجود “تسكير وزني” مطلوب ولم يتم تلقائياً.'),
              Text('• عند الرغبة بتغيير خزينة التسوية لهذه المرة فقط (Override).'),
              Text('• عند تصحيح/إعادة تنفيذ تسوية بإدخالات محددة (مبلغ/وزن/سعر).'),
              SizedBox(height: 12),
              Text('ملاحظات مهمة', style: TextStyle(fontWeight: FontWeight.bold)),
              SizedBox(height: 6),
              Text('• ليست نفس شاشة “حجز ذهب خام / التسكير - حجز ذهب خام”.'),
              Text('• الحقول المطلوبة تختلف حسب البروفايل المختار (قد يتطلب مبلغاً فقط أو وزناً فقط أو الاثنين).'),
              Text('• “خزينة التسوية” هنا تتجاوز إعدادات المورد/الإعدادات العامة لهذه العملية فقط.'),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('حسناً'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('تنفيذ بروفايل التسكير الوزني'),
        backgroundColor: AppColors.darkGold,
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            icon: const Icon(Icons.info_outline),
            tooltip: 'معلومات',
            onPressed: _showInfoDialog,
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'تحديث',
            onPressed: _isLoading || _isExecuting ? null : _load,
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Card(
                      color: AppColors.lightGold.withValues(alpha: 0.35),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'تنفيذ يدوي لتسكير وزني (ينشئ قيد يومية).',
                              style: theme.textTheme.titleMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                            const SizedBox(height: 6),
                            Text(
                              'اختر البروفايل ثم أدخل المطلوب (مبلغ/وزن/سعر) وحدد خزينة التسوية إذا رغبت.',
                              style: theme.textTheme.bodyMedium,
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('البروفايل', style: theme.textTheme.titleMedium),
                            const SizedBox(height: 8),
                            DropdownButtonFormField<String>(
                              value: _profileKey,
                              decoration: const InputDecoration(
                                border: OutlineInputBorder(),
                                prefixIcon: Icon(Icons.rule_folder_outlined),
                              ),
                              isExpanded: true,
                              items: _profiles
                                  .map(
                                    (p) => DropdownMenuItem<String>(
                                      value: p['key']?.toString(),
                                      child: Text(_profileDisplayName(p)),
                                    ),
                                  )
                                  .toList(),
                              onChanged: (value) => setState(() => _profileKey = value),
                              validator: (value) {
                                if (value == null || value.trim().isEmpty) {
                                  return 'اختر بروفايل';
                                }
                                return null;
                              },
                            ),
                            const SizedBox(height: 12),
                            Text('المورد (اختياري)',
                                style: theme.textTheme.titleMedium),
                            const SizedBox(height: 8),
                            DropdownButtonFormField<int>(
                              value: _supplierId,
                              decoration: const InputDecoration(
                                border: OutlineInputBorder(),
                                prefixIcon: Icon(Icons.person_outline),
                              ),
                              isExpanded: true,
                              items: [
                                const DropdownMenuItem<int>(
                                  value: null,
                                  child: Text('بدون'),
                                ),
                                ..._suppliers.map(
                                  (s) => DropdownMenuItem<int>(
                                    value: (s['id'] as num?)?.toInt(),
                                    child: Text(s['name']?.toString() ?? ''),
                                  ),
                                ),
                              ],
                              onChanged: (value) => setState(() => _supplierId = value),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('التسوية النقدية',
                                style: theme.textTheme.titleMedium),
                            const SizedBox(height: 8),
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              leading: const Icon(Icons.account_balance_wallet_outlined),
                              title: Text(_safeNameById(_overrideCashSafeBoxId)),
                              subtitle: const Text(
                                'يمكن اختيار خزينة هنا لتجاوز الإعدادات/المورد.',
                              ),
                              trailing: Wrap(
                                spacing: 8,
                                children: [
                                  TextButton(
                                    onPressed: _pickCashSafeBox,
                                    child: const Text('اختيار'),
                                  ),
                                  if (_overrideCashSafeBoxId != null)
                                    TextButton(
                                      onPressed: () =>
                                          setState(() => _overrideCashSafeBoxId = null),
                                      child: const Text('مسح'),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('المدخلات', style: theme.textTheme.titleMedium),
                            const SizedBox(height: 12),
                            TextFormField(
                              controller: _cashAmountController,
                              decoration: InputDecoration(
                                labelText: _requiresCashAmount
                                    ? 'المبلغ النقدي (مطلوب)'
                                    : 'المبلغ النقدي (اختياري)',
                                border: const OutlineInputBorder(),
                                prefixIcon: const Icon(Icons.payments_outlined),
                              ),
                              keyboardType:
                                  const TextInputType.numberWithOptions(decimal: true),
                            ),
                            const SizedBox(height: 12),
                            TextFormField(
                              controller: _weightMainController,
                              decoration: InputDecoration(
                                labelText: _requiresWeight
                                    ? 'الوزن (عيار 21) (مطلوب)'
                                    : 'الوزن (عيار 21) (اختياري)',
                                border: const OutlineInputBorder(),
                                prefixIcon: const Icon(Icons.scale_outlined),
                              ),
                              keyboardType:
                                  const TextInputType.numberWithOptions(decimal: true),
                            ),
                            const SizedBox(height: 12),
                            TextFormField(
                              controller: _pricePerGramController,
                              decoration: const InputDecoration(
                                labelText: 'سعر الجرام (24k)',
                                border: OutlineInputBorder(),
                                prefixIcon: Icon(Icons.attach_money_outlined),
                              ),
                              keyboardType:
                                  const TextInputType.numberWithOptions(decimal: true),
                              validator: (value) {
                                final text = (value ?? '').trim();
                                if (text.isEmpty) return null;
                                final parsed = double.tryParse(text);
                                if (parsed == null || parsed <= 0) {
                                  return 'سعر غير صالح';
                                }
                                return null;
                              },
                            ),
                            const SizedBox(height: 12),
                            TextFormField(
                              controller: _notesController,
                              decoration: const InputDecoration(
                                labelText: 'ملاحظات (اختياري)',
                                border: OutlineInputBorder(),
                                prefixIcon: Icon(Icons.note_outlined),
                              ),
                              maxLines: 2,
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),
                    ElevatedButton.icon(
                      onPressed: _isExecuting ? null : _execute,
                      icon: const Icon(Icons.play_circle_outline),
                      label: Text(
                        _isExecuting ? 'جارٍ التنفيذ...' : 'تنفيذ',
                        style: const TextStyle(fontSize: 18),
                      ),
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.all(16),
                        backgroundColor: AppColors.primaryGold,
                        foregroundColor: Colors.white,
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}
