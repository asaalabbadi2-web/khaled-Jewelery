import 'package:flutter/material.dart';

import '../api_service.dart';
import '../models/safe_box_model.dart';
import '../theme/app_theme.dart';

class SafeTransferScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;
  final String initialMode; // gold | cash

  const SafeTransferScreen({
    super.key,
    required this.api,
    this.isArabic = true,
    this.initialMode = 'gold',
  });

  @override
  State<SafeTransferScreen> createState() => _SafeTransferScreenState();
}

class _SafeTransferScreenState extends State<SafeTransferScreen> {
  final _formKey = GlobalKey<FormState>();

  late String _mode; // gold | cash

  List<SafeBoxModel> _safes = <SafeBoxModel>[];
  final Map<int, SafeBoxModel> _safeById = <int, SafeBoxModel>{};
  bool _isLoadingSafes = false;

  int? _fromSafeId;
  int? _toSafeId;

  final _amountCashController = TextEditingController();

  final _weight24kController = TextEditingController();
  final _weight22kController = TextEditingController();
  final _weight21kController = TextEditingController();
  final _weight18kController = TextEditingController();

  final _notesController = TextEditingController();

  bool _isSubmitting = false;

  static const double _epsilon = 0.0001;

  @override
  void initState() {
    super.initState();
    _mode = widget.initialMode;

    _amountCashController.addListener(_onInputChanged);
    _weight24kController.addListener(_onInputChanged);
    _weight22kController.addListener(_onInputChanged);
    _weight21kController.addListener(_onInputChanged);
    _weight18kController.addListener(_onInputChanged);

    _loadSafes();
  }

  void _onInputChanged() {
    if (!mounted) return;
    setState(() {});
  }

  @override
  void dispose() {
    _amountCashController.dispose();
    _weight24kController.dispose();
    _weight22kController.dispose();
    _weight21kController.dispose();
    _weight18kController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  String _typeLabel(String? safeType) {
    final isAr = widget.isArabic;
    switch ((safeType ?? '').toLowerCase()) {
      case 'gold':
        return isAr ? 'ذهب' : 'Gold';
      case 'cash':
        return isAr ? 'نقدي' : 'Cash';
      case 'bank':
        return isAr ? 'بنك' : 'Bank';
      case 'clearing':
        return isAr ? 'تحصيل' : 'Clearing';
      case 'check':
        return isAr ? 'شيكات' : 'Checks';
      default:
        return isAr ? 'أخرى' : 'Other';
    }
  }

  Future<void> _loadSafes() async {
    setState(() => _isLoadingSafes = true);
    try {
      // Prefer ledger-based balances so we can show available balance per safe.
      final rows = await widget.api.getSafeBoxBalances(
        type: _mode == 'gold' ? 'gold' : null,
        isActive: true,
      );

      final usable = rows.where((s) => s.id != null).toList();
      final filtered = _mode == 'gold'
          ? usable
          : usable.where((s) => s.safeType.toLowerCase() != 'gold').toList();

      filtered.sort((a, b) {
        if (_mode == 'gold') {
          final ka = a.karat ?? 0;
          final kb = b.karat ?? 0;
          final byKarat = ka.compareTo(kb);
          if (byKarat != 0) return byKarat;
          return a.name.compareTo(b.name);
        }

        final ta = a.safeType.toLowerCase();
        final tb = b.safeType.toLowerCase();
        final byType = ta.compareTo(tb);
        if (byType != 0) return byType;
        return a.name.compareTo(b.name);
      });

      if (!mounted) return;
      setState(() {
        _safes = filtered;
        _safeById
          ..clear()
          ..addEntries(
            filtered
                .where((s) => s.id != null)
                .map((s) => MapEntry<int, SafeBoxModel>(s.id!, s)),
          );
        _isLoadingSafes = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoadingSafes = false);
      _showSnack(widget.isArabic ? 'فشل تحميل الخزائن: $e' : 'Failed to load safes: $e', isError: true);
    }
  }

  SafeBoxModel? _safeByIdOrNull(int? id) {
    if (id == null) return null;
    return _safeById[id];
  }

  String _fmtCash(double value) {
    return value.toStringAsFixed(2);
  }

  String _fmtWeight(double value) {
    return value.toStringAsFixed(3);
  }

  Widget _balanceCard({required String title, required SafeBoxModel safe}) {
    final isAr = widget.isArabic;

    final content = _mode == 'cash'
        ? Text(
            isAr
                ? 'الرصيد المتاح: ${_fmtCash(safe.cashBalance)} ر.س'
                : 'Available: ${_fmtCash(safe.cashBalance)}',
            style: TextStyle(color: Colors.grey.shade800),
          )
        : Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                isAr ? 'الرصيد المتاح (غرام):' : 'Available (g):',
                style: TextStyle(color: Colors.grey.shade800),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _karatChip('24k', safe.goldBalance24k, Colors.yellow.shade800),
                  _karatChip('22k', safe.goldBalance22k, Colors.yellow.shade700),
                  _karatChip('21k', safe.goldBalance21k, Colors.yellow.shade600),
                  _karatChip('18k', safe.goldBalance18k, Colors.yellow.shade500),
                ],
              ),
            ],
          );

    return Card(
      color: AppColors.lightGold.withOpacity(0.08),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: AppColors.darkGold,
              ),
            ),
            const SizedBox(height: 8),
            content,
          ],
        ),
      ),
    );
  }

  Widget _karatChip(String label, double value, Color color) {
    return Chip(
      avatar: Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(
          color: color,
          shape: BoxShape.circle,
        ),
      ),
      label: Text(
        '$label: ${_fmtWeight(value)}',
        style: const TextStyle(
          color: Colors.black87,
          fontWeight: FontWeight.w700,
        ),
      ),
      backgroundColor: color.withValues(alpha: 0.22),
      side: BorderSide(color: color.withValues(alpha: 0.85), width: 1),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      visualDensity: VisualDensity.compact,
    );
  }

  void _showSnack(String message, {bool isError = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? Colors.red : Colors.green,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  double _parseDouble(String value) {
    try {
      return double.parse(value.trim());
    } catch (_) {
      return 0.0;
    }
  }

  bool _validateGoldWeights() {
    final w24 = _parseDouble(_weight24kController.text);
    final w22 = _parseDouble(_weight22kController.text);
    final w21 = _parseDouble(_weight21kController.text);
    final w18 = _parseDouble(_weight18kController.text);
    return (w24 + w22 + w21 + w18) > 0;
  }

  String? _cashOverdraftError() {
    if (_mode != 'cash') return null;
    final fromSafe = _safeByIdOrNull(_fromSafeId);
    if (fromSafe == null) return null;
    final amount = _parseDouble(_amountCashController.text);
    if (amount <= 0) return null;
    if (amount > fromSafe.cashBalance + _epsilon) {
      return widget.isArabic
          ? 'المبلغ أكبر من الرصيد المتاح (${_fmtCash(fromSafe.cashBalance)} ر.س)'
          : 'Exceeds available (${_fmtCash(fromSafe.cashBalance)})';
    }
    return null;
  }

  String? _goldOverdraftError(String karat) {
    if (_mode != 'gold') return null;
    final fromSafe = _safeByIdOrNull(_fromSafeId);
    if (fromSafe == null) return null;

    final entered = switch (karat) {
      '24k' => _parseDouble(_weight24kController.text),
      '22k' => _parseDouble(_weight22kController.text),
      '21k' => _parseDouble(_weight21kController.text),
      '18k' => _parseDouble(_weight18kController.text),
      _ => 0.0,
    };
    if (entered <= 0) return null;

    final available = switch (karat) {
      '24k' => fromSafe.goldBalance24k,
      '22k' => fromSafe.goldBalance22k,
      '21k' => fromSafe.goldBalance21k,
      '18k' => fromSafe.goldBalance18k,
      _ => 0.0,
    };

    if (entered > available + _epsilon) {
      return widget.isArabic
          ? 'أكبر من المتاح (${_fmtWeight(available)} g)'
          : 'Exceeds (${_fmtWeight(available)} g)';
    }
    return null;
  }

  Future<void> _submitTransfer() async {
    if (!_formKey.currentState!.validate()) return;

    if (_fromSafeId == null || _toSafeId == null) {
      _showSnack(widget.isArabic ? 'يجب اختيار خزينة المصدر والوجهة' : 'Select both source and destination', isError: true);
      return;
    }

    if (_fromSafeId == _toSafeId) {
      _showSnack(widget.isArabic ? 'لا يمكن التحويل إلى نفس الخزينة' : 'Cannot transfer to the same safe', isError: true);
      return;
    }

    if (_mode == 'gold' && !_validateGoldWeights()) {
      _showSnack(widget.isArabic ? 'يجب إدخال وزن واحد على الأقل' : 'Enter at least one weight', isError: true);
      return;
    }

    if (_mode == 'cash') {
      final amount = _parseDouble(_amountCashController.text);
      if (amount <= 0) {
        _showSnack(widget.isArabic ? 'يجب إدخال مبلغ صحيح' : 'Enter a valid amount', isError: true);
        return;
      }

      final fromSafe = _safeByIdOrNull(_fromSafeId);
      if (fromSafe != null && amount > fromSafe.cashBalance + 0.0001) {
        _showSnack(
          widget.isArabic
              ? 'المبلغ أكبر من رصيد الخزينة المتاح (${_fmtCash(fromSafe.cashBalance)} ر.س)'
              : 'Amount exceeds available balance (${_fmtCash(fromSafe.cashBalance)})',
          isError: true,
        );
        return;
      }
    }

    if (_mode == 'gold') {
      final fromSafe = _safeByIdOrNull(_fromSafeId);
      if (fromSafe != null) {
        final w24 = _parseDouble(_weight24kController.text);
        final w22 = _parseDouble(_weight22kController.text);
        final w21 = _parseDouble(_weight21kController.text);
        final w18 = _parseDouble(_weight18kController.text);

        final over24 = w24 > fromSafe.goldBalance24k + 0.0001;
        final over22 = w22 > fromSafe.goldBalance22k + 0.0001;
        final over21 = w21 > fromSafe.goldBalance21k + 0.0001;
        final over18 = w18 > fromSafe.goldBalance18k + 0.0001;

        if (over24 || over22 || over21 || over18) {
          _showSnack(
            widget.isArabic
                ? 'أحد الأوزان المدخلة أكبر من الرصيد المتاح في خزينة المصدر'
                : 'One of the entered weights exceeds available balance',
            isError: true,
          );
          return;
        }
      }
    }

    setState(() => _isSubmitting = true);

    try {
      final notes = _notesController.text.trim().isNotEmpty ? _notesController.text.trim() : null;

      Map<String, dynamic> result;
      if (_mode == 'gold') {
        final weights = <String, double>{};

        final w24 = _parseDouble(_weight24kController.text);
        final w22 = _parseDouble(_weight22kController.text);
        final w21 = _parseDouble(_weight21kController.text);
        final w18 = _parseDouble(_weight18kController.text);

        if (w24 > 0) weights['24k'] = w24;
        if (w22 > 0) weights['22k'] = w22;
        if (w21 > 0) weights['21k'] = w21;
        if (w18 > 0) weights['18k'] = w18;

        result = await widget.api.createSafeBoxTransferVoucher(
          fromSafeBoxId: _fromSafeId!,
          toSafeBoxId: _toSafeId!,
          weights: weights,
          notes: notes,
          date: DateTime.now(),
        );
      } else {
        final amount = _parseDouble(_amountCashController.text);
        result = await widget.api.createSafeBoxTransferVoucher(
          fromSafeBoxId: _fromSafeId!,
          toSafeBoxId: _toSafeId!,
          amountCash: amount,
          notes: notes,
          date: DateTime.now(),
        );
      }

      if (!mounted) return;

      _showSnack(widget.isArabic ? 'تم إنشاء سند التحويل بنجاح' : 'Transfer voucher created');

      // Reset
      setState(() {
        _fromSafeId = null;
        _toSafeId = null;
        _amountCashController.clear();
        _weight24kController.clear();
        _weight22kController.clear();
        _weight21kController.clear();
        _weight18kController.clear();
        _notesController.clear();
      });

      await showDialog<void>(
        context: context,
        builder: (context) {
          final voucher = result['voucher'] as Map<String, dynamic>?;
          final transfer = result['transfer'] as Map<String, dynamic>?;
          return AlertDialog(
            title: Text(widget.isArabic ? 'تم إنشاء سند التحويل' : 'Transfer Voucher Created'),
            content: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(widget.isArabic ? 'رقم السند: ${voucher?['voucher_number'] ?? '-'}' : 'Voucher: ${voucher?['voucher_number'] ?? '-'}'),
                  const SizedBox(height: 8),
                  if (_mode == 'cash')
                    Text(
                      widget.isArabic
                          ? 'المبلغ: ${transfer?['amount_cash'] ?? '-'} ر.س'
                          : 'Amount: ${transfer?['amount_cash'] ?? '-'}',
                    ),
                  if (_mode == 'gold') ...[
                    Text(widget.isArabic ? 'الأوزان:' : 'Weights:'),
                    const SizedBox(height: 4),
                    Text('24k: ${(transfer?['weights']?['24k'] ?? 0).toString()}'),
                    Text('22k: ${(transfer?['weights']?['22k'] ?? 0).toString()}'),
                    Text('21k: ${(transfer?['weights']?['21k'] ?? 0).toString()}'),
                    Text('18k: ${(transfer?['weights']?['18k'] ?? 0).toString()}'),
                  ],
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: Text(widget.isArabic ? 'حسناً' : 'OK'),
              ),
            ],
          );
        },
      );
    } catch (e) {
      if (!mounted) return;
      _showSnack(widget.isArabic ? 'فشل إنشاء سند التحويل: $e' : 'Failed to create transfer: $e', isError: true);
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;

    final fromSafe = _safeByIdOrNull(_fromSafeId);
    final toSafe = _safeByIdOrNull(_toSafeId);

    final cashOverdraft = _cashOverdraftError();
    final goldOver24 = _goldOverdraftError('24k');
    final goldOver22 = _goldOverdraftError('22k');
    final goldOver21 = _goldOverdraftError('21k');
    final goldOver18 = _goldOverdraftError('18k');

    return Scaffold(
      appBar: AppBar(
        title: Text(isAr ? 'إدارة التحويل بين الخزائن' : 'Safe Transfer'),
        backgroundColor: AppColors.darkGold,
      ),
      body: _isLoadingSafes
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Card(
                      color: AppColors.lightGold.withOpacity(0.1),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Row(
                          children: [
                            Icon(Icons.info_outline, color: AppColors.darkGold),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                isAr
                                    ? 'يمكنك التحويل بين خزائن الذهب (بالوزن) أو بين الخزائن النقدية/البنكية وغيرها (بالمبلغ)'
                                    : 'Transfer between gold safes (weights) or cash/bank/other safes (amount)',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: Colors.grey.shade700,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    DropdownButtonFormField<String>(
                      value: _mode,
                      decoration: InputDecoration(
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.swap_horiz, color: AppColors.darkGold),
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        labelText: isAr ? 'نوع التحويل' : 'Transfer Type',
                      ),
                      items: [
                        DropdownMenuItem(
                          value: 'gold',
                          child: Text(isAr ? 'تحويل ذهب (بالوزن)' : 'Gold transfer (weights)'),
                        ),
                        DropdownMenuItem(
                          value: 'cash',
                          child: Text(isAr ? 'تحويل نقدي/بنكي (بالمبلغ)' : 'Cash/Bank transfer (amount)'),
                        ),
                      ],
                      onChanged: (value) {
                        if (value == null || value == _mode) return;
                        setState(() {
                          _mode = value;
                          _fromSafeId = null;
                          _toSafeId = null;
                          _amountCashController.clear();
                          _weight24kController.clear();
                          _weight22kController.clear();
                          _weight21kController.clear();
                          _weight18kController.clear();
                        });
                        _loadSafes();
                      },
                    ),

                    const SizedBox(height: 16),

                    DropdownButtonFormField<int>(
                      value: _fromSafeId,
                      decoration: InputDecoration(
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.inventory_2, color: AppColors.darkGold),
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        labelText: isAr ? 'من خزينة' : 'From Safe',
                      ),
                      items: _safes
                          .map(
                            (safe) => DropdownMenuItem<int>(
                              value: safe.id!,
                              child: Text(
                                _mode == 'cash'
                                    ? '${safe.name} (${_typeLabel(safe.safeType)})'
                                    : safe.name,
                              ),
                            ),
                          )
                          .toList(),
                      onChanged: (value) => setState(() => _fromSafeId = value),
                      validator: (value) => value == null ? (isAr ? 'مطلوب' : 'Required') : null,
                    ),

                    if (fromSafe != null) ...[
                      const SizedBox(height: 10),
                      _balanceCard(
                        title: isAr ? 'رصيد خزينة المصدر' : 'Source Balance',
                        safe: fromSafe,
                      ),
                    ],

                    const SizedBox(height: 16),

                    DropdownButtonFormField<int>(
                      value: _toSafeId,
                      decoration: InputDecoration(
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.inventory_2_outlined, color: AppColors.darkGold),
                        filled: true,
                        fillColor: Colors.grey.shade50,
                        labelText: isAr ? 'إلى خزينة' : 'To Safe',
                      ),
                      items: _safes
                          .map(
                            (safe) => DropdownMenuItem<int>(
                              value: safe.id!,
                              child: Text(
                                _mode == 'cash'
                                    ? '${safe.name} (${_typeLabel(safe.safeType)})'
                                    : safe.name,
                              ),
                            ),
                          )
                          .toList(),
                      onChanged: (value) => setState(() => _toSafeId = value),
                      validator: (value) {
                        if (value == null) return isAr ? 'مطلوب' : 'Required';
                        if (value == _fromSafeId) {
                          return isAr ? 'لا يمكن نفس الخزينة' : 'Cannot be same safe';
                        }
                        return null;
                      },
                    ),

                    if (toSafe != null) ...[
                      const SizedBox(height: 10),
                      _balanceCard(
                        title: isAr ? 'رصيد خزينة الوجهة' : 'Destination Balance',
                        safe: toSafe,
                      ),
                    ],

                    const SizedBox(height: 16),

                    if (_mode == 'cash') ...[
                      TextField(
                        controller: _amountCashController,
                        decoration: InputDecoration(
                          labelText: isAr ? 'المبلغ (ر.س)' : 'Amount',
                          border: const OutlineInputBorder(),
                          prefixIcon: Icon(Icons.payments, color: AppColors.darkGold),
                          errorText: cashOverdraft,
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      ),
                      const SizedBox(height: 16),
                    ],

                    if (_mode == 'gold') ...[
                      Text(
                        isAr ? 'الأوزان (غرام)' : 'Weights (g)',
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        controller: _weight24kController,
                        decoration: InputDecoration(
                          labelText: isAr ? 'عيار 24' : '24k',
                          border: const OutlineInputBorder(),
                          prefixIcon: Icon(Icons.diamond, color: Colors.yellow.shade800),
                          errorText: goldOver24,
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _weight22kController,
                        decoration: InputDecoration(
                          labelText: isAr ? 'عيار 22' : '22k',
                          border: const OutlineInputBorder(),
                          prefixIcon: Icon(Icons.diamond, color: Colors.yellow.shade700),
                          errorText: goldOver22,
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _weight21kController,
                        decoration: InputDecoration(
                          labelText: isAr ? 'عيار 21' : '21k',
                          border: const OutlineInputBorder(),
                          prefixIcon: Icon(Icons.diamond, color: Colors.yellow.shade600),
                          errorText: goldOver21,
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _weight18kController,
                        decoration: InputDecoration(
                          labelText: isAr ? 'عيار 18' : '18k',
                          border: const OutlineInputBorder(),
                          prefixIcon: Icon(Icons.diamond, color: Colors.yellow.shade500),
                          errorText: goldOver18,
                        ),
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                      ),
                      const SizedBox(height: 16),
                    ],

                    TextField(
                      controller: _notesController,
                      decoration: InputDecoration(
                        labelText: isAr ? 'ملاحظات (اختياري)' : 'Notes (optional)',
                        border: const OutlineInputBorder(),
                        prefixIcon: const Icon(Icons.note),
                      ),
                      maxLines: 3,
                    ),

                    const SizedBox(height: 24),

                    ElevatedButton.icon(
                      onPressed: _isSubmitting ? null : _submitTransfer,
                      icon: _isSubmitting
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                              ),
                            )
                          : const Icon(Icons.swap_horiz),
                      label: Text(
                        _isSubmitting
                            ? (isAr ? 'جاري التحويل...' : 'Transferring...')
                            : (isAr ? 'إنشاء سند التحويل' : 'Create Transfer Voucher'),
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.darkGold,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}
