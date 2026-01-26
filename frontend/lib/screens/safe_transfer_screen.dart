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

  @override
  void initState() {
    super.initState();
    _mode = widget.initialMode;
    _loadSafes();
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
      if (_mode == 'gold') {
        final safes = await widget.api.getSafeBoxes(
          safeType: 'gold',
          isActive: true,
        );
        final usable = safes.where((s) => s.id != null).toList();
        if (!mounted) return;
        setState(() {
          _safes = usable;
          _isLoadingSafes = false;
        });
        return;
      }

      final all = await widget.api.getSafeBoxes(
        safeType: null,
        isActive: true,
      );
      final nonGold = all
          .where((s) => s.id != null)
          .where((s) => s.safeType.toLowerCase() != 'gold');
      final sorted = nonGold.toList()
        ..sort((a, b) {
          final ta = a.safeType.toLowerCase();
          final tb = b.safeType.toLowerCase();
          final byType = ta.compareTo(tb);
          if (byType != 0) return byType;
          return a.name.compareTo(b.name);
        });

      if (!mounted) return;
      setState(() {
        _safes = sorted;
        _isLoadingSafes = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoadingSafes = false);
      _showSnack(widget.isArabic ? 'فشل تحميل الخزائن: $e' : 'Failed to load safes: $e', isError: true);
    }
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

                    const SizedBox(height: 16),

                    if (_mode == 'cash') ...[
                      TextField(
                        controller: _amountCashController,
                        decoration: InputDecoration(
                          labelText: isAr ? 'المبلغ (ر.س)' : 'Amount',
                          border: const OutlineInputBorder(),
                          prefixIcon: Icon(Icons.payments, color: AppColors.darkGold),
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
