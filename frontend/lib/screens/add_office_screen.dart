import 'package:flutter/material.dart';
import '../api_service.dart';
import '../models/safe_box_model.dart';
import '../theme/app_theme.dart';
import '../utils.dart';

/// شاشة إضافة أو تعديل مكتب
class AddOfficeScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;
  final Map<String, dynamic>? office; // null = إضافة جديد، موجود = تعديل

  const AddOfficeScreen({
    super.key,
    required this.api,
    this.isArabic = true,
    this.office,
  });

  @override
  State<AddOfficeScreen> createState() => _AddOfficeScreenState();
}

class _AddOfficeScreenState extends State<AddOfficeScreen> {
  final _formKey = GlobalKey<FormState>();
  bool _isLoading = false;

  bool _isLoadingSafeBoxes = false;
  List<SafeBoxModel> _safeBoxes = const [];
  int? _selectedSafeBoxId;

  bool _ensureSupplierAccounts = true;

  // Controllers
  final _nameController = TextEditingController();
  final _phoneController = TextEditingController();
  final _emailController = TextEditingController();
  final _contactPersonController = TextEditingController();
  final _addressLine1Controller = TextEditingController();
  final _addressLine2Controller = TextEditingController();
  final _cityController = TextEditingController();
  final _stateController = TextEditingController();
  final _postalCodeController = TextEditingController();
  final _licenseNumberController = TextEditingController();
  final _taxNumberController = TextEditingController();
  final _notesController = TextEditingController();

  String _country = 'Saudi Arabia';
  bool _active = true;

  @override
  void initState() {
    super.initState();
    if (widget.office != null) {
      _loadOfficeData();
    }

    _loadSafeBoxes();
  }

  Future<void> _loadSafeBoxes() async {
    setState(() => _isLoadingSafeBoxes = true);
    try {
      final boxes = await widget.api.getSafeBoxes(
        safeType: 'cash',
        isActive: true,
      );
      if (!mounted) return;
      setState(() {
        _safeBoxes = boxes;
      });
    } catch (e) {
      if (!mounted) return;
      _showMessage('خطأ في تحميل الخزائن: $e', isError: true);
    } finally {
      if (!mounted) return;
      setState(() => _isLoadingSafeBoxes = false);
    }
  }

  void _loadOfficeData() {
    final office = widget.office!;
    _nameController.text = office['name'] ?? '';
    _phoneController.text = office['phone'] ?? '';
    _emailController.text = office['email'] ?? '';
    _contactPersonController.text = office['contact_person'] ?? '';
    _addressLine1Controller.text = office['address_line_1'] ?? '';
    _addressLine2Controller.text = office['address_line_2'] ?? '';
    _cityController.text = office['city'] ?? '';
    _stateController.text = office['state'] ?? '';
    _postalCodeController.text = office['postal_code'] ?? '';
    _country = office['country'] ?? 'Saudi Arabia';
    _licenseNumberController.text = office['license_number'] ?? '';
    _taxNumberController.text = office['tax_number'] ?? '';
    _notesController.text = office['notes'] ?? '';
    _active = office['active'] ?? true;

    final rawSafeBoxId = office['supplier_default_safe_box_id'];
    if (rawSafeBoxId is int) {
      _selectedSafeBoxId = rawSafeBoxId;
    } else {
      _selectedSafeBoxId = int.tryParse((rawSafeBoxId ?? '').toString());
    }
  }

  @override
  void dispose() {
    _nameController.dispose();
    _phoneController.dispose();
    _emailController.dispose();
    _contactPersonController.dispose();
    _addressLine1Controller.dispose();
    _addressLine2Controller.dispose();
    _cityController.dispose();
    _stateController.dispose();
    _postalCodeController.dispose();
    _licenseNumberController.dispose();
    _taxNumberController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  Future<void> _saveOffice() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() => _isLoading = true);

    try {
      final officeData = {
        'name': _nameController.text.trim(),
        'phone': _phoneController.text.trim(),
        'email': _emailController.text.trim(),
        'contact_person': _contactPersonController.text.trim(),
        'address_line_1': _addressLine1Controller.text.trim(),
        'address_line_2': _addressLine2Controller.text.trim(),
        'city': _cityController.text.trim(),
        'state': _stateController.text.trim(),
        'postal_code': _postalCodeController.text.trim(),
        'country': _country,
        'license_number': _licenseNumberController.text.trim(),
        'tax_number': _taxNumberController.text.trim(),
        'notes': _notesController.text.trim(),
        'active': _active,

        // Applies to the linked supplier (closing office supplier)
        'supplier_default_safe_box_id': _selectedSafeBoxId,
        'ensure_supplier_accounts': _ensureSupplierAccounts,
      };

      if (widget.office == null) {
        // إضافة جديد
        await widget.api.addOffice(officeData);
        _showMessage('تم إضافة المكتب بنجاح', isError: false);
      } else {
        // تعديل
        await widget.api.updateOffice(widget.office!['id'], officeData);
        _showMessage('تم تحديث المكتب بنجاح', isError: false);
      }

      Navigator.pop(context, true);
    } catch (e) {
      _showMessage('خطأ: $e', isError: true);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  void _showMessage(String message, {required bool isError}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? AppColors.error : AppColors.success,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    final isEdit = widget.office != null;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          isEdit
              ? (isAr ? 'تعديل مكتب' : 'Edit Office')
              : (isAr ? 'إضافة مكتب جديد' : 'Add New Office'),
        ),
        backgroundColor: AppColors.darkGold,
        foregroundColor: Colors.white,
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
                    // معلومات أساسية
                    _buildSectionTitle(
                      isAr ? 'المعلومات الأساسية' : 'Basic Information',
                    ),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _nameController,
                      decoration: InputDecoration(
                        labelText: '${isAr ? "اسم المكتب" : "Office Name"} *',
                        prefixIcon: const Icon(Icons.store),
                        border: const OutlineInputBorder(),
                      ),
                      validator: (value) {
                        if (value == null || value.trim().isEmpty) {
                          return isAr
                              ? 'الرجاء إدخال اسم المكتب'
                              : 'Please enter office name';
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: 16),

                    DropdownButtonFormField<int?>(
                      value: _selectedSafeBoxId,
                      decoration: InputDecoration(
                        labelText: isAr
                            ? 'الخزنة الافتراضية (تسويات)'
                            : 'Default SafeBox (settlements)',
                        prefixIcon: const Icon(Icons.account_balance_wallet),
                        border: const OutlineInputBorder(),
                        helperText: _isLoadingSafeBoxes
                            ? (isAr
                                  ? 'جارٍ تحميل الخزائن...'
                                  : 'Loading safeboxes...')
                            : null,
                      ),
                      items: [
                        DropdownMenuItem<int?>(
                          value: null,
                          child: Text(isAr ? 'بدون خزنة' : 'No SafeBox'),
                        ),
                        ..._safeBoxes.map((sb) {
                          return DropdownMenuItem<int?>(
                            value: sb.id,
                            child: Text(sb.name),
                          );
                        }),
                      ],
                      onChanged: _isLoadingSafeBoxes
                          ? null
                          : (value) {
                              setState(() => _selectedSafeBoxId = value);
                            },
                    ),
                    const SizedBox(height: 12),

                    SwitchListTile.adaptive(
                      value: _ensureSupplierAccounts,
                      onChanged: (v) =>
                          setState(() => _ensureSupplierAccounts = v),
                      title: Text(
                        isAr
                            ? 'إنشاء/ربط حسابات المورد تلقائياً (مالي + مذكرة)'
                            : 'Ensure supplier accounts (financial + memo)',
                      ),
                      subtitle: Text(
                        isAr
                            ? 'مفيد لتفعيل كشف الحساب المدمج وربط المذكرة'
                            : 'Helps enable merged statements and memo linking',
                      ),
                      contentPadding: EdgeInsets.zero,
                    ),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _phoneController,
                      decoration: InputDecoration(
                        labelText: isAr ? 'رقم الهاتف' : 'Phone Number',
                        prefixIcon: const Icon(Icons.phone),
                        border: const OutlineInputBorder(),
                      ),
                      keyboardType: TextInputType.phone,
                    ),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _emailController,
                      decoration: InputDecoration(
                        labelText: isAr ? 'البريد الإلكتروني' : 'Email',
                        prefixIcon: const Icon(Icons.email),
                        border: const OutlineInputBorder(),
                      ),
                      keyboardType: TextInputType.emailAddress,
                    ),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _contactPersonController,
                      decoration: InputDecoration(
                        labelText: isAr ? 'الشخص المسؤول' : 'Contact Person',
                        prefixIcon: const Icon(Icons.person),
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 24),

                    // العنوان
                    _buildSectionTitle(isAr ? 'العنوان' : 'Address'),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _addressLine1Controller,
                      decoration: InputDecoration(
                        labelText: isAr ? 'العنوان - سطر 1' : 'Address Line 1',
                        prefixIcon: const Icon(Icons.location_on),
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _addressLine2Controller,
                      decoration: InputDecoration(
                        labelText: isAr ? 'العنوان - سطر 2' : 'Address Line 2',
                        prefixIcon: const Icon(Icons.location_on_outlined),
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 16),

                    Row(
                      children: [
                        Expanded(
                          child: TextFormField(
                            controller: _cityController,
                            decoration: InputDecoration(
                              labelText: isAr ? 'المدينة' : 'City',
                              prefixIcon: const Icon(Icons.location_city),
                              border: const OutlineInputBorder(),
                            ),
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: TextFormField(
                            controller: _stateController,
                            decoration: InputDecoration(
                              labelText: isAr ? 'المنطقة' : 'State/Region',
                              prefixIcon: const Icon(Icons.map),
                              border: const OutlineInputBorder(),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    Row(
                      children: [
                        Expanded(
                          child: TextFormField(
                            controller: _postalCodeController,
                            decoration: InputDecoration(
                              labelText: isAr ? 'الرمز البريدي' : 'Postal Code',
                              prefixIcon: const Icon(Icons.markunread_mailbox),
                              border: const OutlineInputBorder(),
                            ),
                            keyboardType: TextInputType.number,
                            inputFormatters: [NormalizeNumberFormatter()],
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: DropdownButtonFormField<String>(
                            initialValue: _country,
                            decoration: InputDecoration(
                              labelText: isAr ? 'الدولة' : 'Country',
                              prefixIcon: const Icon(Icons.public),
                              border: const OutlineInputBorder(),
                            ),
                            items:
                                [
                                  'Saudi Arabia',
                                  'UAE',
                                  'Kuwait',
                                  'Bahrain',
                                  'Qatar',
                                  'Oman',
                                ].map((country) {
                                  return DropdownMenuItem(
                                    value: country,
                                    child: Text(country),
                                  );
                                }).toList(),
                            onChanged: (value) {
                              setState(() => _country = value!);
                            },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 24),

                    // معلومات رسمية
                    _buildSectionTitle(
                      isAr ? 'المعلومات الرسمية' : 'Official Information',
                    ),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _licenseNumberController,
                      decoration: InputDecoration(
                        labelText: isAr ? 'رقم الترخيص' : 'License Number',
                        prefixIcon: const Icon(Icons.badge),
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _taxNumberController,
                      decoration: InputDecoration(
                        labelText: isAr ? 'الرقم الضريبي' : 'Tax Number',
                        prefixIcon: const Icon(Icons.receipt_long),
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 24),

                    // ملاحظات
                    _buildSectionTitle(isAr ? 'ملاحظات' : 'Notes'),
                    const SizedBox(height: 16),

                    TextFormField(
                      controller: _notesController,
                      decoration: InputDecoration(
                        labelText: isAr ? 'ملاحظات إضافية' : 'Additional Notes',
                        prefixIcon: const Icon(Icons.note),
                        border: const OutlineInputBorder(),
                      ),
                      maxLines: 3,
                    ),
                    const SizedBox(height: 24),

                    // الحالة
                    if (isEdit)
                      SwitchListTile(
                        title: Text(isAr ? 'مكتب نشط' : 'Active Office'),
                        subtitle: Text(
                          isAr ? 'تفعيل/تعطيل المكتب' : 'Enable/Disable office',
                        ),
                        value: _active,
                        onChanged: (value) {
                          setState(() => _active = value);
                        },
                        activeThumbColor: AppColors.primaryGold,
                      ),
                    const SizedBox(height: 24),

                    // زر الحفظ
                    ElevatedButton.icon(
                      onPressed: _isLoading ? null : _saveOffice,
                      icon: const Icon(Icons.save),
                      label: Text(
                        isEdit
                            ? (isAr ? 'حفظ التعديلات' : 'Save Changes')
                            : (isAr ? 'إضافة المكتب' : 'Add Office'),
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

  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: const TextStyle(
        fontSize: 18,
        fontWeight: FontWeight.bold,
        color: AppColors.darkGold,
      ),
    );
  }
}
