import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'template_positioning_screen.dart';

class TemplateStudioScreen extends StatelessWidget {
  final bool isArabic;

  const TemplateStudioScreen({super.key, required this.isArabic});

  static const double _mmPerInch = 25.4;
  static const double _pointsPerInch = 72.0;

  static double _mmToPoints(double mm) => (mm / _mmPerInch) * _pointsPerInch;

  List<_TemplatePreset> _presets() {
    return [
      _TemplatePreset(
        key: 'a4_portrait',
        titleAr: 'A4 (عمودي)',
        titleEn: 'A4 (Portrait)',
        widthPoints: 595.0,
        heightPoints: 842.0,
      ),
      _TemplatePreset(
        key: 'a5_portrait',
        titleAr: 'A5 (عمودي)',
        titleEn: 'A5 (Portrait)',
        widthPoints: 420.0,
        heightPoints: 595.0,
      ),
      _TemplatePreset(
        key: 'thermal_80x200',
        titleAr: 'حراري 80×200 مم',
        titleEn: 'Thermal 80×200 mm',
        widthPoints: _mmToPoints(80),
        heightPoints: _mmToPoints(200),
      ),
    ];
  }

  static const String _activePresetKeyStorage = 'template_active_preset_key_v1';

  Future<void> _setActivePreset(_TemplatePreset preset) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_activePresetKeyStorage, preset.key);
  }

  void _openPositioning(BuildContext context, _TemplatePreset preset) {
    _setActivePreset(preset);
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => TemplatePositioningScreen(
          isArabic: isArabic,
          presetKey: preset.key,
          presetTitleAr: preset.titleAr,
          presetTitleEn: preset.titleEn,
          pageWidthPoints: preset.widthPoints,
          pageHeightPoints: preset.heightPoints,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final presets = _presets();

    return Directionality(
      textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        appBar: AppBar(
          title: Text(isArabic ? 'موزع عناصر الفاتورة' : 'Invoice Layout'),
        ),
        body: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Card(
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(18),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(18),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                            Icons.auto_awesome_mosaic_outlined,
                            color: theme.colorScheme.primary,
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              isArabic
                                  ? 'قوالب جاهزة بمقاسات طباعة معروفة'
                                  : 'Ready templates with known print sizes',
                              style: theme.textTheme.titleMedium,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(
                        isArabic
                            ? 'اختر مقاساً جاهزاً ثم وزّع عناصر الفاتورة عليه.'
                            : 'Pick a preset size, then position invoice elements.',
                        style: theme.textTheme.bodySmall,
                      ),
                      const SizedBox(height: 14),
                      Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        children: presets.map((preset) {
                          return SizedBox(
                            width: 320,
                            child: Card(
                              color: theme.colorScheme.surfaceContainerHighest,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(16),
                              ),
                              child: Padding(
                                padding: const EdgeInsets.all(14),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      isArabic
                                          ? preset.titleAr
                                          : preset.titleEn,
                                      style: theme.textTheme.titleSmall
                                          ?.copyWith(
                                            fontWeight: FontWeight.w700,
                                          ),
                                    ),
                                    const SizedBox(height: 10),
                                    Row(
                                      children: [
                                        Expanded(
                                          child: ElevatedButton.icon(
                                            onPressed: () => _openPositioning(
                                              context,
                                              preset,
                                            ),
                                            icon: const Icon(
                                              Icons.grid_view_outlined,
                                            ),
                                            label: Text(
                                              isArabic
                                                  ? 'توزيع عناصر الفاتورة'
                                                  : 'Position invoice elements',
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          );
                        }).toList(),
                      ),
                    ],
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

class _TemplatePreset {
  final String key;
  final String titleAr;
  final String titleEn;
  final double widthPoints;
  final double heightPoints;

  const _TemplatePreset({
    required this.key,
    required this.titleAr,
    required this.titleEn,
    required this.widthPoints,
    required this.heightPoints,
  });
}
