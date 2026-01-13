import 'package:flutter/material.dart';
import '../api_service.dart';
import '../models/safe_box_model.dart';
import '../theme/app_theme.dart';

/// شاشة تحويل الذهب بين الخزائن
/// تستخدم endpoint مخصص: POST /safe-boxes/transfer-voucher
class GoldSafeTransferScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;

  const GoldSafeTransferScreen({
    super.key,
    required this.api,
    this.isArabic = true,
  });

  @override
  State<GoldSafeTransferScreen> createState() => _GoldSafeTransferScreenState();
}

class _GoldSafeTransferScreenState extends State<GoldSafeTransferScreen> {
  final _formKey = GlobalKey<FormState>();
  
  // الخزائن المتاحة
  List<SafeBoxModel> _goldSafes = [];
  bool _isLoadingSafes = false;
  
  // الخزائن المختارة
  int? _fromSafeId;
  int? _toSafeId;
  
  // الأوزان
  final _weight24kController = TextEditingController();
  final _weight22kController = TextEditingController();
  final _weight21kController = TextEditingController();
  final _weight18kController = TextEditingController();
  
  // ملاحظات
  final _notesController = TextEditingController();
  
  // حالة الإرسال
  bool _isSubmitting = false;

  @override
  void initState() {
    super.initState();
    _loadGoldSafes();
  }

  @override
  void dispose() {
    _weight24kController.dispose();
    _weight22kController.dispose();
    _weight21kController.dispose();
    _weight18kController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _loadGoldSafes() async {
    setState(() => _isLoadingSafes = true);
    try {
      final safes = await widget.api.getSafeBoxes(
        safeType: 'gold',
        isActive: true,
      );
      
      if (!mounted) return;
      
      setState(() {
        _goldSafes = safes;
        _isLoadingSafes = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoadingSafes = false);
      _showError('فشل تحميل الخزائن: $e');
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  void _showSuccess(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.green,
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

  bool _validateWeights() {
    final w24 = _parseDouble(_weight24kController.text);
    final w22 = _parseDouble(_weight22kController.text);
    final w21 = _parseDouble(_weight21kController.text);
    final w18 = _parseDouble(_weight18kController.text);
    
    return (w24 + w22 + w21 + w18) > 0;
  }

  Future<void> _submitTransfer() async {
    if (!_formKey.currentState!.validate()) return;
    
    if (_fromSafeId == null || _toSafeId == null) {
      _showError('يجب اختيار خزينة المصدر والوجهة');
      return;
    }
    
    if (_fromSafeId == _toSafeId) {
      _showError('لا يمكن التحويل إلى نفس الخزينة');
      return;
    }
    
    if (!_validateWeights()) {
      _showError('يجب إدخال وزن واحد على الأقل');
      return;
    }

    setState(() => _isSubmitting = true);

    try {
      final weights = <String, double>{};
      
      final w24 = _parseDouble(_weight24kController.text);
      final w22 = _parseDouble(_weight22kController.text);
      final w21 = _parseDouble(_weight21kController.text);
      final w18 = _parseDouble(_weight18kController.text);
      
      if (w24 > 0) weights['24k'] = w24;
      if (w22 > 0) weights['22k'] = w22;
      if (w21 > 0) weights['21k'] = w21;
      if (w18 > 0) weights['18k'] = w18;

      final result = await widget.api.createSafeBoxTransferVoucher(
        fromSafeBoxId: _fromSafeId!,
        toSafeBoxId: _toSafeId!,
        weights: weights,
        notes: _notesController.text.trim().isNotEmpty 
            ? _notesController.text.trim() 
            : null,
        date: DateTime.now(),
      );

      if (!mounted) return;

      _showSuccess('✅ تم إنشاء سند التحويل بنجاح');
      
      // إعادة تعيين النموذج
      setState(() {
        _fromSafeId = null;
        _toSafeId = null;
        _weight24kController.clear();
        _weight22kController.clear();
        _weight21kController.clear();
        _weight18kController.clear();
        _notesController.clear();
      });

      // عرض تفاصيل السند
      await showDialog(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('✅ تم إنشاء سند التحويل'),
          content: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('رقم السند: ${result['voucher']?['voucher_number'] ?? '-'}'),
                const SizedBox(height: 8),
                Text('من خزينة: ${_goldSafes.firstWhere((s) => s.id == _fromSafeId).name}'),
                Text('إلى خزينة: ${_goldSafes.firstWhere((s) => s.id == _toSafeId).name}'),
                const SizedBox(height: 8),
                const Text('الأوزان المحولة:', style: TextStyle(fontWeight: FontWeight.bold)),
                if (w24 > 0) Text('• عيار 24: ${w24.toStringAsFixed(3)} غرام'),
                if (w22 > 0) Text('• عيار 22: ${w22.toStringAsFixed(3)} غرام'),
                if (w21 > 0) Text('• عيار 21: ${w21.toStringAsFixed(3)} غرام'),
                if (w18 > 0) Text('• عيار 18: ${w18.toStringAsFixed(3)} غرام'),
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

    } catch (e) {
      if (!mounted) return;
      _showError('فشل إنشاء سند التحويل: $e');
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    
    return Scaffold(
      appBar: AppBar(
        title: Text(isAr ? 'تحويل ذهب بين الخزائن' : 'Gold Safe Transfer'),
        backgroundColor: AppColors.darkGold,
      ),
      body: _isLoadingSafes
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16.0),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // بطاقة معلومات
                    Card(
                      color: AppColors.lightGold.withOpacity(0.1),
                      child: Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: Row(
                          children: [
                            Icon(Icons.info_outline, color: AppColors.darkGold),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                'سند تحويل الذهب يقوم بنقل الأوزان بين خزائن الذهب وتحديث الدفاتر فوراً',
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
                    const SizedBox(height: 24),

                    // من خزينة
                    Text(
                      'من خزينة:',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    DropdownButtonFormField<int>(
                      value: _fromSafeId,
                      decoration: InputDecoration(
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.inventory_2, color: AppColors.darkGold),
                        filled: true,
                        fillColor: Colors.grey.shade50,
                      ),
                      hint: const Text('اختر خزينة المصدر'),
                      items: _goldSafes.map((safe) {
                        return DropdownMenuItem<int>(
                          value: safe.id,
                          child: Text('${safe.name} (ID: ${safe.id})'),
                        );
                      }).toList(),
                      onChanged: (value) {
                        setState(() => _fromSafeId = value);
                      },
                      validator: (value) {
                        if (value == null) return 'يجب اختيار خزينة المصدر';
                        return null;
                      },
                    ),
                    const SizedBox(height: 24),

                    // إلى خزينة
                    Text(
                      'إلى خزينة:',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 8),
                    DropdownButtonFormField<int>(
                      value: _toSafeId,
                      decoration: InputDecoration(
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.inventory, color: AppColors.darkGold),
                        filled: true,
                        fillColor: Colors.grey.shade50,
                      ),
                      hint: const Text('اختر خزينة الوجهة'),
                      items: _goldSafes.map((safe) {
                        return DropdownMenuItem<int>(
                          value: safe.id,
                          child: Text('${safe.name} (ID: ${safe.id})'),
                        );
                      }).toList(),
                      onChanged: (value) {
                        setState(() => _toSafeId = value);
                      },
                      validator: (value) {
                        if (value == null) return 'يجب اختيار خزينة الوجهة';
                        if (value == _fromSafeId) return 'لا يمكن التحويل لنفس الخزينة';
                        return null;
                      },
                    ),
                    const SizedBox(height: 24),

                    // الأوزان
                    Text(
                      'الأوزان المحولة (غرام):',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 12),

                    // عيار 24
                    TextField(
                      controller: _weight24kController,
                      decoration: InputDecoration(
                        labelText: 'عيار 24 (غرام)',
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.diamond, color: Colors.yellow.shade800),
                      ),
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    ),
                    const SizedBox(height: 12),

                    // عيار 22
                    TextField(
                      controller: _weight22kController,
                      decoration: InputDecoration(
                        labelText: 'عيار 22 (غرام)',
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.diamond, color: Colors.yellow.shade700),
                      ),
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    ),
                    const SizedBox(height: 12),

                    // عيار 21
                    TextField(
                      controller: _weight21kController,
                      decoration: InputDecoration(
                        labelText: 'عيار 21 (غرام)',
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.diamond, color: Colors.yellow.shade600),
                      ),
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    ),
                    const SizedBox(height: 12),

                    // عيار 18
                    TextField(
                      controller: _weight18kController,
                      decoration: InputDecoration(
                        labelText: 'عيار 18 (غرام)',
                        border: const OutlineInputBorder(),
                        prefixIcon: Icon(Icons.diamond, color: Colors.yellow.shade500),
                      ),
                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    ),
                    const SizedBox(height: 24),

                    // ملاحظات
                    TextField(
                      controller: _notesController,
                      decoration: const InputDecoration(
                        labelText: 'ملاحظات (اختياري)',
                        border: OutlineInputBorder(),
                        prefixIcon: Icon(Icons.note),
                      ),
                      maxLines: 3,
                    ),
                    const SizedBox(height: 32),

                    // زر الإرسال
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
                        _isSubmitting ? 'جاري التحويل...' : 'إنشاء سند التحويل',
                        style: const TextStyle(fontSize: 16),
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppColors.darkGold,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }
}
