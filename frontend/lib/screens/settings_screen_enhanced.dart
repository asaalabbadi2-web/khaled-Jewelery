import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api_service.dart';
import '../providers/settings_provider.dart';
import 'accounting_mapping_screen_enhanced.dart';
import 'payment_methods_screen_enhanced.dart';
import 'safe_boxes_screen.dart';
import 'gold_price_manual_screen_enhanced.dart';
import 'system_reset_screen.dart';
import 'template_designer_screen.dart';
import 'weight_closing_settings_screen.dart';
import '../utils.dart';

enum SettingsEntry { goldPrice, weightClosing, systemReset, printerSettings, about }

class SettingsScreenEnhanced extends StatefulWidget {
  static const int systemTabIndex = 5;

  final int initialTabIndex;
  final SettingsEntry? focusEntry;

  const SettingsScreenEnhanced({
    super.key,
    this.initialTabIndex = 0,
    this.focusEntry,
  });

  @override
  State<SettingsScreenEnhanced> createState() => _SettingsScreenEnhancedState();
}

class _SettingsScreenEnhancedState extends State<SettingsScreenEnhanced>
    with SingleTickerProviderStateMixin {
  late final ApiService _apiService;
  late final TabController _tabController;
  static const int _tabCount = 6;

  final ScrollController _systemScrollController = ScrollController();
  late final Map<SettingsEntry, GlobalKey> _systemSectionKeys = {
    SettingsEntry.goldPrice: GlobalKey(),
    SettingsEntry.weightClosing: GlobalKey(),
    SettingsEntry.systemReset: GlobalKey(),
    SettingsEntry.printerSettings: GlobalKey(),
    SettingsEntry.about: GlobalKey(),
  };

  SettingsEntry? _pendingFocusEntry;

  int get _systemTabIndex => SettingsScreenEnhanced.systemTabIndex;

  final TextEditingController _currencyController = TextEditingController();
  final TextEditingController _companyNameController = TextEditingController();
  final TextEditingController _companyAddressController =
      TextEditingController();
  final TextEditingController _companyPhoneController = TextEditingController();
  final TextEditingController _companyTaxNumberController =
      TextEditingController();
  final TextEditingController _invoicePrefixController =
      TextEditingController();

  final List<int> _karatOptions = const [18, 21, 22, 24];
  final List<int> _decimalOptions = const [2, 3, 4];
  final List<String> _dateFormats = const [
    'DD/MM/YYYY',
    'MM/DD/YYYY',
    'YYYY-MM-DD',
  ];

  bool _isInitialized = false;
  bool _isLoading = true;
  bool _isSaving = false;

  int _mainKarat = 21;
  int _decimalPlaces = 2;
  String _dateFormat = 'DD/MM/YYYY';

  bool _taxEnabled = true;
  double _taxRatePercent = 15.0;

  bool _showCompanyLogo = true;
  bool _allowDiscount = true;
  double _defaultDiscountPercent = 0.0;
  bool _allowManualInvoiceItems = false;

  bool _voucherAutoPost = false;

  bool _printerAutoConnect = true;
  bool _printerShowPreview = false;
  bool _printerAutoCut = true;
  String _printerPaperSize = '80 مم';
  final List<String> _printerPaperOptions = const ['58 مم', '80 مم', 'A4'];

  @override
  void initState() {
    super.initState();
    _apiService = ApiService();
    _pendingFocusEntry = widget.focusEntry;

    int initialTab = widget.initialTabIndex;
    if (_pendingFocusEntry != null) {
      initialTab = _systemTabIndex;
    }
    if (initialTab < 0) {
      initialTab = 0;
    } else if (initialTab >= _tabCount) {
      initialTab = _tabCount - 1;
    }

    _tabController = TabController(
      length: _tabCount,
      vsync: this,
      initialIndex: initialTab,
    );
    _loadInitialData();
  }

  @override
  void dispose() {
    _systemScrollController.dispose();
    _tabController.dispose();
    _currencyController.dispose();
    _companyNameController.dispose();
    _companyAddressController.dispose();
    _companyPhoneController.dispose();
    _companyTaxNumberController.dispose();
    _invoicePrefixController.dispose();
    super.dispose();
  }

  ColorScheme get _colors => Theme.of(context).colorScheme;
  bool get _isDark => Theme.of(context).brightness == Brightness.dark;

  Color get _primaryColor => _colors.primary;
  Color get _accentColor => _colors.secondary;
  Color get _successColor => _colors.tertiary;
  Color get _errorColor => _colors.error;
  Color get _surfaceColor => _colors.surface;
  Color get _outlineColor => _colors.outline;

  Color get _mutedTextColor =>
      _isDark ? _colors.onSurfaceVariant : _colors.onSurfaceVariant;
  Color get _strongTextColor => _isDark ? _colors.onSurface : _colors.onSurface;
  Color get _cardColor => _isDark
      ? Color.alphaBlend(
          _withOpacity(_colors.surfaceContainerHighest, 0.45),
          _surfaceColor,
        )
      : Color.alphaBlend(_withOpacity(_colors.primary, 0.06), _surfaceColor);

  String get _currencySymbol => _currencyController.text.trim().isEmpty
      ? 'ر.س'
      : _currencyController.text.trim();

  Future<void> _loadInitialData() async {
    setState(() {
      _isLoading = true;
    });

    try {
      final settings = await _apiService.getSettings();

      if (!mounted) return;

      _currencyController.text =
          settings['currency_symbol']?.toString() ?? 'ر.س';
      _companyNameController.text = settings['company_name']?.toString() ?? '';
      _companyAddressController.text =
          settings['company_address']?.toString() ?? '';
      _companyPhoneController.text =
          settings['company_phone']?.toString() ?? '';
      _companyTaxNumberController.text =
          settings['company_tax_number']?.toString() ?? '';
      _invoicePrefixController.text =
          settings['invoice_prefix']?.toString() ?? 'INV';

      setState(() {
        _isInitialized = true;
        _mainKarat = _safeInt(settings['main_karat'], fallback: 21);
        _decimalPlaces = _safeInt(
          settings['decimal_places'],
          fallback: 2,
        ).clamp(2, 4);
        _dateFormat =
            settings['date_format']?.toString().toUpperCase() ?? 'DD/MM/YYYY';

        _taxEnabled = _safeBool(settings['tax_enabled'], fallback: true);
        _taxRatePercent = _normalizePercent(
          settings['tax_rate'],
          fallbackPercent: 15,
        );

        _showCompanyLogo = _safeBool(
          settings['show_company_logo'],
          fallback: true,
        );
        _allowDiscount = _safeBool(settings['allow_discount'], fallback: true);
        _allowManualInvoiceItems = _safeBool(
          settings['allow_manual_invoice_items'],
          fallback: false,
        );
        _defaultDiscountPercent = _normalizePercent(
          settings['default_discount_rate'],
          fallbackPercent: 0,
        );

        _voucherAutoPost = _safeBool(
          settings['voucher_auto_post'],
          fallback: false,
        );
      });
    } catch (error) {
      if (!mounted) return;
      _showSnack('تعذر تحميل الإعدادات: $error', isError: true);
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
        if (_pendingFocusEntry != null) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!mounted || _pendingFocusEntry == null) return;
            _scrollToSystemEntry(_pendingFocusEntry!);
          });
        }
      }
    }
  }

  Future<void> _saveSettings() async {
    if (_isSaving) return;
    FocusScope.of(context).unfocus();

    setState(() {
      _isSaving = true;
    });

    final payload = <String, dynamic>{
      'main_karat': _mainKarat,
      'currency_symbol': _currencySymbol,
      'decimal_places': _decimalPlaces,
      'date_format': _dateFormat,
      'tax_enabled': _taxEnabled,
      'tax_rate': _taxRatePercent / 100,
      'allow_discount': _allowDiscount,
  'allow_manual_invoice_items': _allowManualInvoiceItems,
      'default_discount_rate': _defaultDiscountPercent / 100,
      'invoice_prefix': _invoicePrefixController.text.trim(),
      'show_company_logo': _showCompanyLogo,
      'company_name': _companyNameController.text.trim(),
      'company_address': _companyAddressController.text.trim(),
      'company_phone': _companyPhoneController.text.trim(),
      'company_tax_number': _companyTaxNumberController.text.trim(),
      'voucher_auto_post': _voucherAutoPost,
    };

    try {
      final settingsProvider = Provider.of<SettingsProvider>(
        context,
        listen: false,
      );
      await settingsProvider.updateSettings(payload);

      if (!mounted) return;
      _showSnack('✅ تم حفظ الإعدادات وتطبيقها على جميع الشاشات');
    } catch (error) {
      if (!mounted) return;
      _showSnack('تعذر حفظ الإعدادات: $error', isError: true);
    } finally {
      if (mounted) {
        setState(() {
          _isSaving = false;
        });
      }
    }
  }

  void _showSnack(String message, {bool isError = false}) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(message, textAlign: TextAlign.center),
          backgroundColor: isError ? _errorColor : _primaryColor,
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('إعدادات النظام'),
        bottom: TabBar(
          controller: _tabController,
          isScrollable: true,
          tabs: const [
            Tab(icon: Icon(Icons.tune), text: 'عام'),
            Tab(icon: Icon(Icons.business), text: 'الشركة والفواتير'),
            Tab(icon: Icon(Icons.payments), text: 'المدفوعات'),
            Tab(icon: Icon(Icons.account_tree), text: 'محاسبة'),
            Tab(icon: Icon(Icons.print), text: 'الطباعة'),
            Tab(icon: Icon(Icons.settings_applications), text: 'النظام'),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsetsDirectional.only(
              end: 16,
              top: 8,
              bottom: 8,
            ),
            child: FilledButton.icon(
              onPressed: (_isSaving || !_isInitialized) ? null : _saveSettings,
              icon: _isSaving
                  ? SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(
                          _colors.onPrimary,
                        ),
                      ),
                    )
                  : const Icon(Icons.save_outlined, size: 18),
              label: Text(_isSaving ? 'جار الحفظ...' : 'حفظ'),
            ),
          ),
        ],
      ),
      body: _isLoading
          ? _buildLoading(theme)
          : TabBarView(
              controller: _tabController,
              children: [
                _buildGeneralTab(),
                _buildCompanyAndInvoicesTab(),
                _buildPaymentTab(),
                _buildAccountingTab(),
                _buildPrintingTab(),
                _buildSystemTab(),
              ],
            ),
    );
  }

  Widget _buildLoading(ThemeData theme) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          CircularProgressIndicator(color: _primaryColor),
          const SizedBox(height: 16),
          Text('جار تحميل الإعدادات...', style: theme.textTheme.bodyMedium),
        ],
      ),
    );
  }

  Widget _buildGeneralTab() {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        _buildSectionCard(
          icon: Icons.diamond_outlined,
          iconColor: _primaryColor,
          title: 'إعدادات الذهب',
          children: [
            Text('العيار الرئيسي', style: _fieldLabelStyle()),
            const SizedBox(height: 12),
            Directionality(
              textDirection: TextDirection.rtl,
              child: DropdownMenu<int>(
                initialSelection: _mainKarat,
                onSelected: (value) {
                  if (value == null) return;
                  setState(() => _mainKarat = value);
                },
                leadingIcon: Icon(Icons.scale, color: _primaryColor),
                trailingIcon: const Icon(Icons.keyboard_arrow_down),
                textStyle: Theme.of(context).textTheme.bodyLarge,
                enableSearch: false,
                inputDecorationTheme: _dropdownDecoration(
                  accentColor: _primaryColor,
                ),
                dropdownMenuEntries: _karatOptions
                    .map(
                      (karat) => DropdownMenuEntry<int>(
                        value: karat,
                        label: 'عيار $karat',
                      ),
                    )
                    .toList(),
              ),
            ),
          ],
        ),
        const SizedBox(height: 20),
        _buildSectionCard(
          icon: Icons.style,
          iconColor: _accentColor,
          title: 'التنسيق والعملة',
          children: [
            Text('رمز العملة', style: _fieldLabelStyle()),
            const SizedBox(height: 12),
            TextFormField(
              controller: _currencyController,
              textDirection: TextDirection.rtl,
              decoration: _inputDecoration(
                icon: Icons.attach_money,
                accentColor: _accentColor,
              ),
            ),
            const SizedBox(height: 20),
            Text('عدد المنازل العشرية', style: _fieldLabelStyle()),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: _decimalOptions
                  .map(
                    (value) => ChoiceChip(
                      label: Text('$value'),
                      selected: _decimalPlaces == value,
                      onSelected: (_) => setState(() => _decimalPlaces = value),
                      selectedColor: _blendOnSurface(_accentColor, 0.4),
                      labelStyle: TextStyle(
                        color: _decimalPlaces == value
                            ? _colors.onPrimary
                            : _mutedTextColor,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  )
                  .toList(),
            ),
            const SizedBox(height: 20),
            Text('تنسيق التاريخ', style: _fieldLabelStyle()),
            const SizedBox(height: 12),
            Directionality(
              textDirection: TextDirection.rtl,
              child: DropdownMenu<String>(
                initialSelection: _dateFormat,
                onSelected: (value) {
                  if (value == null) return;
                  setState(() => _dateFormat = value);
                },
                leadingIcon: Icon(Icons.calendar_month, color: _accentColor),
                trailingIcon: const Icon(Icons.keyboard_arrow_down),
                textStyle: Theme.of(context).textTheme.bodyLarge,
                enableSearch: false,
                inputDecorationTheme: _dropdownDecoration(
                  accentColor: _accentColor,
                ),
                dropdownMenuEntries: _dateFormats
                    .map(
                      (format) => DropdownMenuEntry<String>(
                        value: format,
                        label: format,
                      ),
                    )
                    .toList(),
              ),
            ),
          ],
        ),
        const SizedBox(height: 20),
        _buildSectionCard(
          icon: Icons.percent,
          iconColor: _successColor,
          title: 'الخصومات',
          children: [
            SwitchListTile.adaptive(
              value: _allowDiscount,
              onChanged: (value) => setState(() => _allowDiscount = value),
              thumbColor: _thumbColorFor(_successColor),
              trackColor: _trackColorFor(_successColor),
              title: Text(
                'السماح بالخصم على الفواتير',
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            AnimatedOpacity(
              opacity: _allowDiscount ? 1 : 0.4,
              duration: const Duration(milliseconds: 200),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('نسبة الخصم الافتراضية', style: _fieldLabelStyle()),
                  SliderTheme(
                    data: SliderTheme.of(context).copyWith(
                      activeTrackColor: _successColor,
                      inactiveTrackColor: _withOpacity(_successColor, 0.3),
                      thumbColor: _successColor,
                      overlayColor: _withOpacity(_successColor, 0.15),
                    ),
                    child: Slider(
                      value: _defaultDiscountPercent,
                      min: 0,
                      max: 50,
                      divisions: 100,
                      label: '${_defaultDiscountPercent.toStringAsFixed(1)}%',
                      onChanged:
                          _allowDiscount
                              ? (value) =>
                                    setState(() => _defaultDiscountPercent = value)
                              : null,
                    ),
                  ),
                  Align(
                    alignment: AlignmentDirectional.centerEnd,
                    child: Text(
                      '${_defaultDiscountPercent.toStringAsFixed(1)}%',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: _successColor,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildCompanyAndInvoicesTab() {
    final examples = [1000, 5000, 10000];
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        _buildSectionCard(
          icon: Icons.business,
          iconColor: _accentColor,
          title: 'بيانات الشركة',
          children: [
            TextFormField(
              controller: _companyNameController,
              decoration: _inputDecoration(
                icon: Icons.business_center,
                label: 'اسم الشركة',
                accentColor: _accentColor,
              ),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _companyPhoneController,
              keyboardType: TextInputType.phone,
              decoration: _inputDecoration(
                icon: Icons.phone,
                label: 'رقم الهاتف',
                accentColor: _accentColor,
              ),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _companyAddressController,
              maxLines: 2,
              decoration: _inputDecoration(
                icon: Icons.location_on,
                label: 'العنوان',
                accentColor: _accentColor,
              ),
            ),
          ],
        ),
        const SizedBox(height: 20),
        _buildSectionCard(
          icon: Icons.receipt_long_outlined,
          iconColor: _colors.tertiary,
          title: 'إعدادات الضريبة والفواتير',
          children: [
            TextFormField(
              controller: _companyTaxNumberController,
              keyboardType: TextInputType.number,
              inputFormatters: [NormalizeNumberFormatter()],
              decoration: _inputDecoration(
                icon: Icons.badge_outlined,
                label: 'الرقم الضريبي',
                accentColor: _colors.tertiary,
              ),
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _invoicePrefixController,
              decoration: _inputDecoration(
                icon: Icons.confirmation_number,
                label: 'بادئة رقم الفاتورة',
                accentColor: _colors.tertiary,
              ),
            ),
            const SizedBox(height: 12),
            SwitchListTile.adaptive(
              value: _showCompanyLogo,
              onChanged: (value) => setState(() => _showCompanyLogo = value),
              thumbColor: _thumbColorFor(_colors.tertiary),
              trackColor: _trackColorFor(_colors.tertiary),
              title: Text(
                'عرض شعار الشركة على الفواتير',
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            const SizedBox(height: 8),
            SwitchListTile.adaptive(
              value: _allowManualInvoiceItems,
              onChanged: (value) => setState(() => _allowManualInvoiceItems = value),
              thumbColor: _thumbColorFor(_colors.tertiary),
              trackColor: _trackColorFor(_colors.tertiary),
              title: Text(
                'السماح بإضافة صنف يدوي من شاشة الفاتورة',
                style: Theme.of(context).textTheme.titleSmall,
              ),
              subtitle: const Text(
                'عند التفعيل يظهر زر لإدخال صنف ببيانات مخصصة (اسم، وزن، عيار) أثناء إنشاء فاتورة بيع.',
              ),
            ),
            const Divider(height: 32),
            SwitchListTile.adaptive(
              value: _taxEnabled,
              onChanged: (value) => setState(() => _taxEnabled = value),
              thumbColor: _thumbColorFor(_colors.tertiary),
              trackColor: _trackColorFor(_colors.tertiary),
              title: Text(
                'تفعيل احتساب الضريبة',
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            const SizedBox(height: 16),
            AnimatedOpacity(
              opacity: _taxEnabled ? 1.0 : 0.4,
              duration: const Duration(milliseconds: 200),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('نسبة الضريبة (%)', style: _fieldLabelStyle()),
                  const SizedBox(height: 12),
                   SliderTheme(
                          data: SliderTheme.of(context).copyWith(
                            activeTrackColor: _colors.tertiary,
                            inactiveTrackColor: _withOpacity(
                              _colors.tertiary,
                              0.3,
                            ),
                            thumbColor: _colors.tertiary,
                            overlayColor: _withOpacity(_colors.tertiary, 0.15),
                          ),
                          child: Slider(
                            value: _taxRatePercent,
                            min: 0,
                            max: 30,
                            divisions: 300,
                            label: '${_taxRatePercent.toStringAsFixed(1)}%',
                            onChanged:
                                _taxEnabled
                                    ? (value) =>
                                          setState(() => _taxRatePercent = value)
                                    : null,
                          ),
                        ),
                  Align(
                    alignment: AlignmentDirectional.centerEnd,
                    child: Text(
                      '${_taxRatePercent.toStringAsFixed(1)}%',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: _colors.tertiary,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
         const SizedBox(height: 20),
        _buildSectionCard(
          icon: Icons.calculate_outlined,
          iconColor: _accentColor,
          title: 'أمثلة حسابية للضريبة',
          children: [...examples.map(_buildTaxExampleRow)],
        ),
      ],
    );
  }

  Widget _buildPaymentTab() {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        _buildSectionCard(
          icon: Icons.payments_outlined,
          iconColor: _accentColor,
          title: 'إدارة المدفوعات',
          children: [
             Text(
            'أدر طرق الدفع والخزائن المرتبطة بها لتبسيط عمليات الدفع والتحصيل.',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 20),
            FilledButton.icon(
              icon: const Icon(Icons.credit_card),
              label: const Text('إدارة وسائل الدفع'),
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => const PaymentMethodsScreenEnhanced(),
                  ),
                );
              },
            ),
            const SizedBox(height: 12),
            FilledButton.tonalIcon(
              icon: const Icon(Icons.account_balance_wallet),
              label: const Text('إدارة الخزائن'),
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => SafeBoxesScreen(api: _apiService),
                  ),
                );
              },
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildAccountingTab() {
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
         _buildSectionCard(
          icon: Icons.rule_folder_outlined,
          iconColor: _primaryColor,
          title: 'سير العمل المحاسبي',
          children: [
             SwitchListTile.adaptive(
              value: _voucherAutoPost,
              onChanged: (value) => setState(() => _voucherAutoPost = value),
              title: const Text('ترحيل السندات تلقائياً عند الحفظ'),
              subtitle: const Text(
                'عند التفعيل سيتم إنشاء قيد محاسبي فور حفظ السند. عند الإيقاف ستُحفظ السندات كمسودة وتحتاج للموافقة يدوياً.',
              ),
              thumbColor: _thumbColorFor(_primaryColor),
              trackColor: _trackColorFor(_primaryColor),
            ),
          ],
        ),
        const SizedBox(height: 20),
        _buildSectionCard(
          icon: Icons.account_tree_outlined,
          iconColor: _accentColor,
          title: 'الربط المحاسبي',
          children: [
            Text(
              'قم بإدارة ربط العمليات المحاسبية بالحسابات بسهولة لضمان دقة القيود.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => const AccountingMappingScreenEnhanced(),
                  ),
                );
              },
              icon: const Icon(Icons.open_in_new),
              label: const Text('فتح شاشة الربط المحاسبي'),
            ),
          ],
        ),
      ],
    );
  }
  
  Widget _buildPrintingTab() {
     return ListView(
      padding: const EdgeInsets.all(20),
      children: [
         _buildSectionCard(
          icon: Icons.print_outlined,
          iconColor: _primaryColor,
          title: 'إعدادات الطابعة',
          children: [
            SwitchListTile.adaptive(
              value: _printerAutoConnect,
              onChanged: (value) => setState(() => _printerAutoConnect = value),
              title: const Text('الاتصال التلقائي عند فتح التطبيق'),
              subtitle: const Text(
                'يبحث النظام عن الطابعة المفضلة ويحاول الاتصال مباشرة.',
              ),
              thumbColor: _thumbColorFor(_primaryColor),
              trackColor: _trackColorFor(_primaryColor),
            ),
            SwitchListTile.adaptive(
              value: _printerShowPreview,
              onChanged: (value) => setState(() => _printerShowPreview = value),
              title: const Text('عرض معاينة قبل الطباعة'),
              subtitle: const Text(
                'يعرض نسخة رقمية قبل تأكيد إرسال أمر الطباعة.',
              ),
              thumbColor: _thumbColorFor(_primaryColor),
              trackColor: _trackColorFor(_primaryColor),
            ),
            SwitchListTile.adaptive(
              value: _printerAutoCut,
              onChanged: (value) => setState(() => _printerAutoCut = value),
              title: const Text('تشغيل القطع التلقائي بعد الطباعة'),
              subtitle: const Text(
                'يعمل مع الطابعات الحرارية الداعمة لخاصية القطع.',
              ),
              thumbColor: _thumbColorFor(_primaryColor),
              trackColor: _trackColorFor(_primaryColor),
            ),
            const SizedBox(height: 12),
            Text('مقاس الورق الافتراضي', style: _fieldLabelStyle()),
            const SizedBox(height: 10),
            Directionality(
              textDirection: TextDirection.rtl,
              child: DropdownMenu<String>(
                initialSelection: _printerPaperSize,
                onSelected: (value) {
                  if (value == null) return;
                  setState(() => _printerPaperSize = value);
                },
                leadingIcon: Icon(Icons.straighten, color: _primaryColor),
                trailingIcon: const Icon(Icons.keyboard_arrow_down),
                enableSearch: false,
                textStyle: Theme.of(context).textTheme.bodyLarge,
                inputDecorationTheme: _dropdownDecoration(
                  accentColor: _primaryColor,
                ),
                dropdownMenuEntries: _printerPaperOptions
                    .map(
                      (option) => DropdownMenuEntry<String>(
                        value: option,
                        label: option,
                      ),
                    )
                    .toList(),
              ),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _showPrinterSetupSheet,
              icon: const Icon(Icons.print_rounded),
              label: const Text('إدارة الطابعات المتاحة'),
            ),
          ],
        ),
        const SizedBox(height: 20),
        _buildSectionCard(
          icon: Icons.design_services_outlined,
          iconColor: const Color(0xFFD4AF37),
          title: 'مصمم القوالب',
          children: [
            Text(
              'صمم قوالب احترافية مخصصة للفواتير والسندات والقيود وكشوفات الحساب.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _openTemplateDesigner,
              icon: const Icon(Icons.palette),
              label: const Text('فتح مصمم القوالب'),
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFD4AF37),
              ),
            ),
          ],
        ),
      ]
    );
  }

  Widget _buildSystemTab() {
    final settingsProvider = Provider.of<SettingsProvider>(context);
    final weightConfig = settingsProvider.weightClosingSettings;
    final bool weightEnabled = weightConfig['enabled'] == true;
    final String weightPriceSource =
        (weightConfig['price_source']?.toString() ?? 'live');
    final bool weightAllowOverride =
        weightConfig['allow_override'] != false;

    return ListView(
      controller: _systemScrollController,
      padding: const EdgeInsets.all(20),
      children: [
        _buildSectionCard(
          sectionKey: _systemSectionKeys[SettingsEntry.goldPrice],
          icon: Icons.monetization_on_outlined,
          iconColor: _accentColor,
          title: 'أسعار الذهب',
          children: [
            Text(
              'تابع آخر تحديثات أسعار الذهب وقم بالمزامنة اليدوية عند الحاجة.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _openGoldPriceManager,
              icon: const Icon(Icons.sync_alt),
              label: const Text('تحديث سعر الذهب'),
            ),
          ],
        ),
        const SizedBox(height: 20),
        _buildSectionCard(
          sectionKey: _systemSectionKeys[SettingsEntry.weightClosing],
          icon: Icons.scale_outlined,
          iconColor: _successColor,
          title: 'التسكير الوزني الآلي',
          children: [
             Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _buildConfigChip(
                  icon: weightEnabled
                      ? Icons.check_circle
                      : Icons.pause_circle_filled,
                  label: weightEnabled ? 'مفعل' : 'متوقف مؤقتاً',
                  color: weightEnabled ? _successColor : _outlineColor,
                ),
                _buildConfigChip(
                  icon: Icons.price_change,
                  label:
                      'المصدر: ${_weightClosingPriceSourceLabel(weightPriceSource)}',
                  color: _accentColor,
                ),
                _buildConfigChip(
                  icon: weightAllowOverride
                      ? Icons.edit_attributes
                      : Icons.lock_outline,
                  label:
                      weightAllowOverride ? 'يسمح بالتعديل' : 'سعر ثابت',
                  color: weightAllowOverride ? _primaryColor : _errorColor,
                ),
              ],
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _openWeightClosingSettings,
              icon: const Icon(Icons.settings_suggest_outlined),
              label: const Text('فتح إعدادات التسكير'),
            ),
          ],
        ),
        const SizedBox(height: 20),
        _buildSectionCard(
          sectionKey: _systemSectionKeys[SettingsEntry.systemReset],
          icon: Icons.restore_outlined,
          iconColor: _errorColor,
          title: 'إعادة تهيئة النظام',
          children: [
            Text(
              'استخدم هذه الأداة لمسح البيانات وإعادة ضبط النظام.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            FilledButton.tonalIcon(
              style: FilledButton.styleFrom(foregroundColor: _errorColor),
              onPressed: _openSystemReset,
              icon: const Icon(Icons.security_update_warning),
              label: const Text('فتح شاشة إعادة التهيئة'),
            ),
          ],
        ),
        const SizedBox(height: 20),
        _buildSectionCard(
          sectionKey: _systemSectionKeys[SettingsEntry.about],
          icon: Icons.info_outline,
          iconColor: _successColor,
          title: 'حول النظام',
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: CircleAvatar(
                radius: 26,
                backgroundColor: _blendOnSurface(_successColor, 0.18),
                child: Icon(Icons.diamond, color: _successColor, size: 28),
              ),
              title: Text(
                'نظام الياسر للذهب والمجوهرات',
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: _strongTextColor,
                ),
              ),
              subtitle: Text(
                'إصدار 2.1 — منصة متكاملة لإدارة محلات الذهب.',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: _mutedTextColor),
              ),
            ),
            const SizedBox(height: 16),
            FilledButton.tonalIcon(
              onPressed: _showAboutDialog,
              icon: const Icon(Icons.article_outlined),
              label: const Text('عرض تفاصيل أكثر'),
            ),
          ],
        ),
      ],
    );
  }

  void _scrollToSystemEntry(SettingsEntry entry) {
    final key = _systemSectionKeys[entry];
    if (key?.currentContext == null) return;
    Scrollable.ensureVisible(
      key!.currentContext!,
      duration: const Duration(milliseconds: 450),
      curve: Curves.easeOutCubic,
      alignment: 0.08,
    );
  }

  Future<void> _openGoldPriceManager() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => GoldPriceManualScreenEnhanced()),
    );
  }

  Future<void> _openSystemReset() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => SystemResetScreen()),
    );
  }

  Future<void> _openTemplateDesigner() async {
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => const TemplateDesignerScreen(),
      ),
    );
  }

  Future<void> _openWeightClosingSettings() async {
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => const WeightClosingSettingsScreen(),
      ),
    );
  }

  Future<void> _showPrinterSetupSheet() async {
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
             Text('إدارة الطابعات', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 16),
            _buildInfoBanner(
              icon: Icons.info_outline,
              color: _primaryColor,
              text: 'سيتم توفير دعم الطابعات الحرارية والبلوتوث في التحديثات القادمة.',
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _showAboutDialog() async {
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('حول التطبيق'),
        content: const Text('الإصدار: 2.1\nنظام متكامل لإدارة محلات الذهب والمجوهرات.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('حسناً'),
          ),
        ],
      ),
    );
  }

  Widget _buildConfigChip({
    required IconData icon,
    required String label,
    required Color color,
  }) {
    return Chip(
      avatar: CircleAvatar(
        radius: 14,
        backgroundColor: color,
        child: Icon(icon, size: 16, color: _colors.onPrimary),
      ),
      label: Text(label, style: Theme.of(context).textTheme.bodyMedium),
      backgroundColor: _blendOnSurface(color, 0.1),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
    );
  }

  String _weightClosingPriceSourceLabel(String source) {
    switch (source.toLowerCase()) {
      case 'average': return 'متوسط التكلفة';
      case 'invoice': return 'سعر الفاتورة';
      default: return 'السعر المباشر';
    }
  }

  Widget _buildSectionCard({
    Key? sectionKey,
    required IconData icon,
    required Color iconColor,
    required String title,
    required List<Widget> children,
  }) {
    return Card(
      key: sectionKey,
      elevation: 0,
      color: _cardColor,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(icon, color: iconColor, size: 24),
              const SizedBox(width: 12),
              Expanded(child: Text(title, style: Theme.of(context).textTheme.titleLarge)),
            ]),
            const SizedBox(height: 20),
            ...children,
          ],
        ),
      ),
    );
  }

  Widget _buildInfoBanner({
    required IconData icon,
    required Color color,
    required String text,
  }) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _blendOnSurface(color, 0.1),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 18),
          const SizedBox(width: 12),
          Expanded(child: Text(text, style: Theme.of(context).textTheme.bodySmall)),
        ],
      ),
    );
  }


  Widget _buildTaxExampleRow(int amount) {
    final double taxValue = _taxRatePercent / 100 * amount;
    final double total = amount + taxValue;

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: _blendOnSurface(_colors.secondary, 0.08),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                '${amount.toStringAsFixed(0)} $_currencySymbol',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ),
            Icon(Icons.arrow_forward_ios, size: 16, color: _mutedTextColor),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'ضريبة: ${taxValue.toStringAsFixed(2)} $_currencySymbol',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: _colors.tertiary,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            Icon(Icons.arrow_forward_ios, size: 16, color: _mutedTextColor),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'الإجمالي: ${total.toStringAsFixed(2)} $_currencySymbol',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: _primaryColor,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  TextStyle _fieldLabelStyle() {
    return Theme.of(context).textTheme.titleSmall?.copyWith(
          fontWeight: FontWeight.w700,
          color: _strongTextColor,
        ) ??
        const TextStyle(fontWeight: FontWeight.w700);
  }

  InputDecoration _inputDecoration({
    IconData? icon,
    Color? accentColor,
    String? label,
  }) {
    return InputDecoration(
      labelText: label,
      prefixIcon: icon == null
          ? null
          : Icon(icon, color: accentColor ?? _primaryColor),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(
          color: _withOpacity(accentColor ?? _outlineColor, 0.3),
        ),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: accentColor ?? _primaryColor, width: 2),
      ),
      filled: true,
      fillColor: _blendOnSurface(accentColor ?? _outlineColor, 0.05),
    );
  }

  InputDecorationTheme _dropdownDecoration({Color? accentColor}) {
    final Color color = accentColor ?? _primaryColor;
    return InputDecorationTheme(
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: _withOpacity(color, 0.3)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: color, width: 2),
      ),
      filled: true,
      fillColor: _blendOnSurface(color, 0.05),
      prefixIconColor: color,
      suffixIconColor: _mutedTextColor,
      helperStyle: TextStyle(color: _mutedTextColor),
    );
  }

  double _normalizePercent(dynamic value, {required double fallbackPercent}) {
    if (value is num) {
      final double doubleValue = value.toDouble();
      if (doubleValue <= 1.0) {
        return doubleValue * 100;
      }
      return doubleValue;
    }
    return fallbackPercent;
  }

  int _safeInt(dynamic value, {int fallback = 0}) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    if (value is String) {
      final parsed = int.tryParse(value);
      if (parsed != null) return parsed;
    }
    return fallback;
  }


  bool _safeBool(dynamic value, {required bool fallback}) {
    if (value is bool) return value;
    if (value is num) return value != 0;
    if (value is String) return value.toLowerCase() == 'true';
    return fallback;
  }
  
  WidgetStateProperty<Color?> _thumbColorFor(Color color) {
    return WidgetStateProperty.resolveWith((states) {
      if (states.contains(WidgetState.selected)) return color;
      return null;
    });
  }

  WidgetStateProperty<Color?> _trackColorFor(Color color) {
    return WidgetStateProperty.resolveWith((states) {
      if (states.contains(WidgetState.selected)) return color.withOpacity(0.5);
      return null;
    });
  }

  Color _withOpacity(Color color, double opacity) => color.withOpacity(opacity.clamp(0.0, 1.0));

  Color _blendOnSurface(Color color, double opacity) {
    return Color.alphaBlend(color.withOpacity(opacity), _surfaceColor);
  }
}