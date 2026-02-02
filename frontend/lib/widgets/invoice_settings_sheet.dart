import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum InvoiceUiContext {
  saleNew,
  purchase,
  scrapSale,
  scrapPurchase,
  returns,
}

class InvoiceUiSettings {
  final bool lockPriceEdits;
  final bool disableVat;
  final bool autoOpenPrintAfterSave;
  final String paperSize;

  const InvoiceUiSettings({
    required this.lockPriceEdits,
    required this.disableVat,
    required this.autoOpenPrintAfterSave,
    required this.paperSize,
  });

  static const List<String> supportedPaperSizes = <String>[
    'A4',
    'A5',
    'Thermal',
    'Letter',
  ];

  static String _ctxKey(InvoiceUiContext ctx) => switch (ctx) {
        InvoiceUiContext.saleNew => 'sale_new',
        InvoiceUiContext.purchase => 'purchase',
        InvoiceUiContext.scrapSale => 'scrap_sale',
        InvoiceUiContext.scrapPurchase => 'scrap_purchase',
        InvoiceUiContext.returns => 'returns',
      };

  static String _k(InvoiceUiContext ctx, String key) {
    return 'invoice_ui_settings_v1.${_ctxKey(ctx)}.$key';
  }

  static String _global(String key) => 'invoice_ui_settings_v1.global.$key';

  static Future<InvoiceUiSettings> load(InvoiceUiContext ctx) async {
    final prefs = await SharedPreferences.getInstance();

    final paperSize =
        prefs.getString(_global('paper_size'))?.trim().isNotEmpty == true
            ? prefs.getString(_global('paper_size'))!.trim()
            : 'A4';

    return InvoiceUiSettings(
      lockPriceEdits: prefs.getBool(_k(ctx, 'lock_price_edits')) ?? false,
      disableVat: prefs.getBool(_k(ctx, 'disable_vat')) ?? false,
      autoOpenPrintAfterSave:
          prefs.getBool(_k(ctx, 'auto_open_print_after_save')) ?? false,
      paperSize:
          supportedPaperSizes.contains(paperSize) ? paperSize : 'A4',
    );
  }

  static Future<void> setLockPriceEdits(
    InvoiceUiContext ctx,
    bool value,
  ) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_k(ctx, 'lock_price_edits'), value);
  }

  static Future<void> setDisableVat(InvoiceUiContext ctx, bool value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_k(ctx, 'disable_vat'), value);
  }

  static Future<void> setAutoOpenPrintAfterSave(
    InvoiceUiContext ctx,
    bool value,
  ) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_k(ctx, 'auto_open_print_after_save'), value);
  }

  static Future<void> setPaperSize(String value) async {
    final cleaned = value.trim();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _global('paper_size'),
      supportedPaperSizes.contains(cleaned) ? cleaned : 'A4',
    );
  }

  Map<String, dynamic> toPrintSettings() => <String, dynamic>{
        'paperSize': paperSize,
      };
}

class InvoiceSettingsSheet extends StatefulWidget {
  final InvoiceUiContext contextType;

  final bool supportsVatToggle;
  final bool supportsLockEdits;
  final bool supportsAutoOpenPrint;

  final ValueChanged<InvoiceUiSettings>? onChanged;

  const InvoiceSettingsSheet({
    super.key,
    required this.contextType,
    required this.supportsVatToggle,
    required this.supportsLockEdits,
    required this.supportsAutoOpenPrint,
    this.onChanged,
  });

  static Future<void> show(
    BuildContext context, {
    required InvoiceUiContext contextType,
    required bool supportsVatToggle,
    required bool supportsLockEdits,
    required bool supportsAutoOpenPrint,
    ValueChanged<InvoiceUiSettings>? onChanged,
  }) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (ctx) {
        return InvoiceSettingsSheet(
          contextType: contextType,
          supportsVatToggle: supportsVatToggle,
          supportsLockEdits: supportsLockEdits,
          supportsAutoOpenPrint: supportsAutoOpenPrint,
          onChanged: onChanged,
        );
      },
    );
  }

  @override
  State<InvoiceSettingsSheet> createState() => _InvoiceSettingsSheetState();
}

class _InvoiceSettingsSheetState extends State<InvoiceSettingsSheet> {
  InvoiceUiSettings? _settings;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final loaded = await InvoiceUiSettings.load(widget.contextType);
      if (!mounted) return;
      setState(() {
        _settings = loaded;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _settings = const InvoiceUiSettings(
          lockPriceEdits: false,
          disableVat: false,
          autoOpenPrintAfterSave: false,
          paperSize: 'A4',
        );
        _loading = false;
      });
    }
  }

  Future<void> _notify(InvoiceUiSettings next) async {
    widget.onChanged?.call(next);
  }

  Future<void> _setLock(bool value) async {
    final current = _settings;
    if (current == null) return;

    final next = InvoiceUiSettings(
      lockPriceEdits: value,
      disableVat: current.disableVat,
      autoOpenPrintAfterSave: current.autoOpenPrintAfterSave,
      paperSize: current.paperSize,
    );

    setState(() {
      _settings = next;
    });

    await InvoiceUiSettings.setLockPriceEdits(widget.contextType, value);
    await _notify(next);
  }

  Future<void> _setVatDisabled(bool value) async {
    final current = _settings;
    if (current == null) return;

    final next = InvoiceUiSettings(
      lockPriceEdits: current.lockPriceEdits,
      disableVat: value,
      autoOpenPrintAfterSave: current.autoOpenPrintAfterSave,
      paperSize: current.paperSize,
    );

    setState(() {
      _settings = next;
    });

    await InvoiceUiSettings.setDisableVat(widget.contextType, value);
    await _notify(next);
  }

  Future<void> _setAutoPrint(bool value) async {
    final current = _settings;
    if (current == null) return;

    final next = InvoiceUiSettings(
      lockPriceEdits: current.lockPriceEdits,
      disableVat: current.disableVat,
      autoOpenPrintAfterSave: value,
      paperSize: current.paperSize,
    );

    setState(() {
      _settings = next;
    });

    await InvoiceUiSettings.setAutoOpenPrintAfterSave(
      widget.contextType,
      value,
    );
    await _notify(next);
  }

  Future<void> _setPaperSize(String value) async {
    final current = _settings;
    if (current == null) return;

    final normalized = InvoiceUiSettings.supportedPaperSizes.contains(value)
        ? value
        : 'A4';

    final next = InvoiceUiSettings(
      lockPriceEdits: current.lockPriceEdits,
      disableVat: current.disableVat,
      autoOpenPrintAfterSave: current.autoOpenPrintAfterSave,
      paperSize: normalized,
    );

    setState(() {
      _settings = next;
    });

    await InvoiceUiSettings.setPaperSize(normalized);
    await _notify(next);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (_loading) {
      return const Padding(
        padding: EdgeInsets.all(24),
        child: Center(child: CircularProgressIndicator()),
      );
    }

    final settings = _settings ??
        const InvoiceUiSettings(
          lockPriceEdits: false,
          disableVat: false,
          autoOpenPrintAfterSave: false,
          paperSize: 'A4',
        );

    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 8,
        bottom: 16 + MediaQuery.of(context).viewInsets.bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'إعدادات الفاتورة',
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.bold,
            ),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 16),

          if (widget.supportsLockEdits)
            Card(
              child: SwitchListTile.adaptive(
                value: settings.lockPriceEdits,
                title: const Text('قفل تعديلات التسعير'),
                subtitle: const Text(
                  'يمنع تعديل الأسعار/الإجماليات من الشاشة لتفادي الأخطاء.',
                ),
                onChanged: _setLock,
              ),
            ),

          if (widget.supportsVatToggle)
            Card(
              child: SwitchListTile.adaptive(
                value: settings.disableVat,
                title: const Text('فاتورة بدون ضريبة'),
                subtitle: const Text(
                  'يطبق 0% VAT على هذه الفاتورة فقط (لا يغيّر إعدادات النظام).',
                ),
                onChanged: _setVatDisabled,
              ),
            ),

          if (widget.supportsAutoOpenPrint)
            Card(
              child: SwitchListTile.adaptive(
                value: settings.autoOpenPrintAfterSave,
                title: const Text('فتح الطباعة تلقائياً بعد الحفظ'),
                subtitle: const Text(
                  'يتجاوز سؤال "هل تريد الطباعة الآن؟" ويفتح شاشة الطباعة مباشرة.',
                ),
                onChanged: _setAutoPrint,
              ),
            ),

          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'الطباعة',
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    value: InvoiceUiSettings.supportedPaperSizes
                            .contains(settings.paperSize)
                        ? settings.paperSize
                        : 'A4',
                    decoration: const InputDecoration(
                      labelText: 'حجم الورق الافتراضي',
                      border: OutlineInputBorder(),
                    ),
                    items: InvoiceUiSettings.supportedPaperSizes
                        .map(
                          (size) => DropdownMenuItem<String>(
                            value: size,
                            child: Text(size),
                          ),
                        )
                        .toList(),
                    onChanged: (v) {
                      if (v == null) return;
                      _setPaperSize(v);
                    },
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'يُستخدم عند فتح شاشة الطباعة من الفواتير.',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ),

          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(Icons.done),
            label: const Text('تم'),
          ),
        ],
      ),
    );
  }
}
