import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/services.dart' show rootBundle;
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import '../providers/settings_provider.dart';

// ── PDF colour palette (matches Flutter preview design) ──────────────────────
class VColors {
  // Gold brand identity — aligned with account statement PDF design system
  static const amberDark   = PdfColor.fromInt(0xFF8B6914); // gold
  static const amberMid    = PdfColor.fromInt(0xFFA07820); // goldMid
  static const amberLight  = PdfColor.fromInt(0xFFFBF7EE); // goldBg
  static const amberBorder = PdfColor.fromInt(0xFFE8D899); // borderLight
  static const amberBadge  = PdfColor.fromInt(0xFFC9A84C); // goldLight
  static const orangeTitle = PdfColor.fromInt(0xFF8B1A1A); // negative — payment
  static const greenStatus = PdfColor.fromInt(0xFF1A5C35); // positive — receipt
  static const greenBg     = PdfColor.fromInt(0xFFE8F5EE);
  static const greenText   = PdfColor.fromInt(0xFF1A5C35); // positive green
  static const greenBorder = PdfColor.fromInt(0xFF5A9E72);
  static const greenTagBg  = PdfColor.fromInt(0xFFEAF5EF); // cash tag bg
  static const greenTagBdr = PdfColor.fromInt(0xFF8EC9A5); // cash tag border
  static const grayBg      = PdfColor.fromInt(0xFFF7F6F2);
  static const grayBorder  = PdfColor.fromInt(0xFFEBEBEB);
  static const grayText    = PdfColor.fromInt(0xFF999999);
  static const grayMuted   = PdfColor.fromInt(0xFFAAAAAA);
  static const cellBg      = PdfColor.fromInt(0xFFF7F6F2);
  static const cellBorder  = PdfColor.fromInt(0xFFEDEBE4);
  static const black       = PdfColor.fromInt(0xFF1A1A1A);
  static const white       = PdfColors.white;
  static const goldTagBg   = PdfColor.fromInt(0xFFFBF7EE); // goldBg
  static const goldTagBdr  = PdfColor.fromInt(0xFFE8D899); // borderLight
  static const grpHdrBg    = PdfColor.fromInt(0xFFFBF7EE); // goldBg
  static const grpHdrBdr   = PdfColor.fromInt(0xFFE8D899); // borderLight
}

/// شاشة معاينة وطباعة السندات (قبض/صرف)
class VoucherPrintScreen extends StatefulWidget {
  final Map<String, dynamic> voucher;
  final bool isArabic;
  final Map<String, dynamic>? printSettings;

  const VoucherPrintScreen({
    super.key,
    required this.voucher,
    this.isArabic = true,
    this.printSettings,
  });

  @override
  State<VoucherPrintScreen> createState() => _VoucherPrintScreenState();
}

class _VoucherPrintScreenState extends State<VoucherPrintScreen> {
  final bool _isGenerating = false;
  bool _includeAccountLines = false;

  late String _paperSize;
  late String _orientation;

  // ── Cached assets (loaded once, reused across PDF generations) ──────────
  Uint8List? _cachedFontRegBytes;
  Uint8List? _cachedFontBoldBytes;
  Uint8List? _cachedLogoBytes;
  bool _assetsPreloaded = false;

  @override
  void initState() {
    super.initState();
    _loadPrintSettings();
    _preloadAssets();
  }

  void _loadPrintSettings() {
    final settings = widget.printSettings ?? {};
    _paperSize = settings['paperSize'] ?? 'A4';
    _orientation = settings['orientation'] ?? 'portrait';
  }

  /// Pre-load fonts and logo once so subsequent PDF generations are instant.
  Future<void> _preloadAssets() async {
    if (_assetsPreloaded) return;
    try {
      _cachedFontRegBytes =
          (await rootBundle.load('assets/fonts/Cairo-Regular.ttf'))
              .buffer
              .asUint8List();
      _cachedFontBoldBytes =
          (await rootBundle.load('assets/fonts/Cairo-Bold.ttf'))
              .buffer
              .asUint8List();
    } catch (_) {}
    try {
      final raw =
          (await rootBundle.load('assets/KHGL.png')).buffer.asUint8List();
      // Resize to 128×128 — logo is rendered at ~36pt in PDF; 128px is ample
      // for print quality and avoids embedding the full 47 KB bitmap.
      _cachedLogoBytes = await _resizeImageBytes(raw, 128);
    } catch (_) {}
    _assetsPreloaded = true;
  }

  /// Resize [bytes] (PNG/JPEG/WebP) to a square of [targetSize] pixels.
  /// Returns the original bytes if decoding fails.
  Future<Uint8List> _resizeImageBytes(Uint8List bytes, int targetSize) async {
    try {
      final codec = await ui.instantiateImageCodec(
        bytes,
        targetWidth: targetSize,
        targetHeight: targetSize,
      );
      final frame = await codec.getNextFrame();
      final byteData =
          await frame.image.toByteData(format: ui.ImageByteFormat.png);
      frame.image.dispose();
      if (byteData != null) return byteData.buffer.asUint8List();
    } catch (_) {}
    return bytes; // fallback: original bytes
  }

  ({
    String typeKey,
    bool isReceipt,
    bool isPayment,
    bool isAdjustment,
    String titleAr,
    String titleEn,
    Color appColor,
    PdfColor headerBg,
    PdfColor accent,
    IconData icon,
  })
  _voucherMeta() {
    final typeKey = (widget.voucher['voucher_type']?.toString() ?? '')
        .trim()
        .toLowerCase();

    if (typeKey == 'receipt') {
      return (
        typeKey: typeKey,
        isReceipt: true,
        isPayment: false,
        isAdjustment: false,
        titleAr: 'سند قبض',
        titleEn: 'Receipt Voucher',
        appColor: Colors.green,
        headerBg: PdfColor.fromHex('#E8F5E9'),
        accent: PdfColor.fromHex('#2E7D32'),
        icon: Icons.arrow_downward,
      );
    }

    if (typeKey == 'payment') {
      return (
        typeKey: typeKey,
        isReceipt: false,
        isPayment: true,
        isAdjustment: false,
        titleAr: 'سند صرف',
        titleEn: 'Payment Voucher',
        appColor: Colors.orange,
        headerBg: PdfColor.fromHex('#FFF3E0'),
        accent: PdfColor.fromHex('#E65100'),
        icon: Icons.arrow_upward,
      );
    }

    // Adjustment / settlement voucher.
    return (
      typeKey: typeKey.isEmpty ? 'adjustment' : typeKey,
      isReceipt: false,
      isPayment: false,
      isAdjustment: true,
      titleAr: 'سند تسوية',
      titleEn: 'Adjustment Voucher',
      appColor: Colors.purple,
      headerBg: PdfColor.fromHex('#F3E5F5'),
      accent: PdfColor.fromHex('#6A1B9A'),
      icon: Icons.balance,
    );
  }

  String _fmtDate(dynamic raw) {
    if (raw == null) return '';
    final s = raw.toString();
    if (s.isEmpty) return '';
    try {
      final dt = DateTime.tryParse(s);
      if (dt == null) return s;
      return DateFormat('yyyy-MM-dd HH:mm').format(dt);
    } catch (_) {
      return s;
    }
  }

  String _partyDisplay(Map<String, dynamic> voucher) {
    final partyName = voucher['party_name']?.toString().trim();
    if (partyName != null && partyName.isNotEmpty) return partyName;

    final customer = voucher['customer'];
    if (customer is Map) {
      final name = customer['name']?.toString().trim();
      if (name != null && name.isNotEmpty) return name;
    }

    final supplier = voucher['supplier'];
    if (supplier is Map) {
      final name = supplier['name']?.toString().trim();
      if (name != null && name.isNotEmpty) return name;
    }

    final employee = voucher['employee'];
    if (employee is Map) {
      final name = employee['name']?.toString().trim();
      if (name != null && name.isNotEmpty) return name;
    }

    final description = voucher['description']?.toString().trim();
    if (description != null && description.isNotEmpty) return description;
    return '';
  }

  String _voucherQrPayload() {
    final voucherNumber = (widget.voucher['voucher_number'] ?? '').toString();
    final voucherId = (widget.voucher['id'] ?? '').toString();
    final party = _partyDisplay(widget.voucher);
    final date = _fmtDate(widget.voucher['date']);
    return [
      'voucher_number=$voucherNumber',
      'voucher_id=$voucherId',
      if (party.isNotEmpty) 'party=$party',
      if (date.isNotEmpty) 'date=$date',
      'type=${widget.voucher['voucher_type'] ?? ''}',
    ].join(';');
  }

  double _toDouble(dynamic value) {
    if (value is num) return value.toDouble();
    return double.tryParse(value?.toString() ?? '') ?? 0.0;
  }

  List<Map<String, dynamic>> _goldRows() {
    final accountLinesRaw = widget.voucher['account_lines'];
    final accountLines = accountLinesRaw is List
        ? accountLinesRaw.whereType<Map>().cast<Map<String, dynamic>>().toList()
        : <Map<String, dynamic>>[];
    final voucherType = (widget.voucher['voucher_type'] ?? '')
        .toString()
        .toLowerCase();
    final operationalLineType = voucherType == 'payment'
        ? 'credit'
        : voucherType == 'receipt'
        ? 'debit'
        : null;

    final rows = <Map<String, dynamic>>[];
    for (final line in accountLines) {
      if ((line['amount_type']?.toString().toLowerCase() ?? '') != 'gold') {
        continue;
      }
      if (operationalLineType != null &&
          (line['line_type']?.toString().toLowerCase() ?? '') !=
              operationalLineType) {
        continue;
      }

      final account = line['account'] is Map
          ? (line['account'] as Map).cast<dynamic, dynamic>()
          : const <dynamic, dynamic>{};
      final description =
          (line['description']?.toString().trim().isNotEmpty ?? false)
          ? line['description'].toString().trim()
          : (account['name']?.toString().trim().isNotEmpty ?? false)
          ? account['name'].toString().trim()
          : (widget.voucher['description']?.toString().trim() ?? 'سطر صرف ذهب');

      final weight = _toDouble(line['amount']);
      final netWeight = _toDouble(line['net_weight']);
      final stonesWeight = _toDouble(line['stones_weight']);
      final grossWeight = _toDouble(line['gross_weight']);
      final karatText = line['karat'] == null
          ? ((widget.voucher['gold_karat'] ?? '—').toString())
          : line['karat'].toString().replaceAll('.0', '');

      rows.add({
        'description': description,
        'karat': karatText,
        'grossWeight': grossWeight > 0 ? grossWeight : weight,
        'netWeight': netWeight > 0 ? netWeight : weight,
        'stonesWeight': stonesWeight,
        'estimatedCash': 0.0,
        'notes': (line['description']?.toString().trim() ?? '').isEmpty
            ? '—'
            : line['description'].toString().trim(),
      });
    }

    if (rows.isNotEmpty) {
      final totalCash = _toDouble(widget.voucher['amount_cash']);
      if (totalCash > 0) {
        final perRow = totalCash / rows.length;
        for (final row in rows) {
          row['estimatedCash'] = perRow;
        }
      }
      return rows;
    }

    final rawBreakdown = widget.voucher['gold_breakdown'];
    if (rawBreakdown is List) {
      for (final item in rawBreakdown.whereType<Map>()) {
        final karat = item['karat']?.toString().replaceAll('.0', '') ?? '—';
        final weight = _toDouble(item['weight']);
        rows.add({
          'description':
              widget.voucher['description']?.toString().trim().isNotEmpty ==
                  true
              ? widget.voucher['description'].toString().trim()
              : 'صرف ذهب',
          'karat': karat,
          'grossWeight': weight,
          'netWeight': weight,
          'stonesWeight': 0.0,
          'estimatedCash': 0.0,
          'notes': '—',
        });
      }
    }

    final totalCash = _toDouble(widget.voucher['amount_cash']);
    if (rows.isNotEmpty && totalCash > 0) {
      final perRow = totalCash / rows.length;
      for (final row in rows) {
        row['estimatedCash'] = perRow;
      }
    }

    return rows;
  }

  @override
  Widget build(BuildContext context) {
    final meta = _voucherMeta();

    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.isArabic ? 'طباعة ${meta.titleAr}' : 'Print ${meta.titleEn}',
        ),
        backgroundColor: meta.appColor,
        actions: [
          IconButton(
            icon: const Icon(Icons.print),
            onPressed: _printPdf,
            tooltip: widget.isArabic ? 'طباعة' : 'Print',
          ),
          IconButton(
            icon: const Icon(Icons.download),
            onPressed: _downloadPdf,
            tooltip: widget.isArabic ? 'تحميل PDF' : 'Download PDF',
          ),
        ],
      ),
      body: _isGenerating
          ? const Center(child: CircularProgressIndicator())
          : kIsWeb
          ? _buildWebPreview(meta)
          : Column(
              children: [
                _buildIncludeAccountLinesToggleBar(),
                Expanded(
                  child: PdfPreview(
                    build: (format) => _generatePdf(format),
                    canChangePageFormat: true,
                    allowPrinting: true,
                    allowSharing: true,
                    initialPageFormat: _getPdfPageFormat(),
                    pdfFileName:
                        'voucher_${widget.voucher['id']}_${DateFormat('yyyyMMdd').format(DateTime.now())}.pdf',
                  ),
                ),
              ],
            ),
    );
  }

  Widget _buildIncludeAccountLinesToggleBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: Colors.grey.shade300)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              widget.isArabic
                  ? 'نسخة الأرشفة: إظهار سطور الحسابات'
                  : 'Archive copy: show account lines',
              style: const TextStyle(fontSize: 12, color: Colors.black54),
            ),
          ),
          Switch(
            value: _includeAccountLines,
            onChanged: (value) {
              setState(() => _includeAccountLines = value);
            },
          ),
        ],
      ),
    );
  }

  Widget _buildWebPreview(
    ({
      String typeKey,
      bool isReceipt,
      bool isPayment,
      bool isAdjustment,
      String titleAr,
      String titleEn,
      Color appColor,
      PdfColor headerBg,
      PdfColor accent,
      IconData icon,
    })
    meta,
  ) {
    final accentColor = _webAccentColor(meta);

    return Container(
      color: const Color(0xFFF5F5F0),
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 860),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    ElevatedButton.icon(
                      onPressed: _downloadPdf,
                      icon: const Icon(Icons.download_rounded),
                      label: Text(
                        widget.isArabic
                            ? 'تحميل السند PDF'
                            : 'Download Voucher PDF',
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: accentColor,
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(
                          horizontal: 18,
                          vertical: 14,
                        ),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    OutlinedButton.icon(
                      onPressed: _printPdf,
                      icon: const Icon(Icons.print_rounded),
                      label: Text(widget.isArabic ? 'طباعة' : 'Print'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: accentColor,
                        padding: const EdgeInsets.symmetric(
                          horizontal: 18,
                          vertical: 14,
                        ),
                        side: BorderSide(color: accentColor),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Align(
                        alignment: AlignmentDirectional.centerEnd,
                        child: Wrap(
                          crossAxisAlignment: WrapCrossAlignment.center,
                          spacing: 8,
                          children: [
                            Text(
                              widget.isArabic
                                  ? 'نسخة الأرشفة: سطور الحسابات'
                                  : 'Archive: account lines',
                              style: const TextStyle(
                                fontSize: 12,
                                color: Colors.black54,
                              ),
                            ),
                            Switch(
                              value: _includeAccountLines,
                              onChanged: (value) {
                                setState(() => _includeAccountLines = value);
                              },
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Container(
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(
                      color: const Color(0xFFD3B87A),
                      width: 1,
                    ),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  clipBehavior: Clip.hardEdge,
                  child: Column(
                    children: [
                      _buildWebVoucherHeader(meta),
                      _buildWebStatusStrip(meta),
                      _buildWebSection(
                        widget.isArabic ? 'تفاصيل السند' : 'Voucher Details',
                        _buildWebDetailsSection(),
                      ),
                      _buildWebSection(
                        widget.isArabic ? 'المبالغ' : 'Amounts',
                        _buildWebAmountSection(meta),
                      ),
                      if (_goldRows().isNotEmpty)
                        _buildWebSection(
                          widget.isArabic ? 'جدول الصرف' : 'Disbursement Table',
                          _buildWebGoldBreakdownSection(),
                        ),
                      if ((widget.voucher['account_lines'] as List?)
                              ?.isNotEmpty ??
                          false)
                        if (_includeAccountLines)
                          _buildWebSection(
                            widget.isArabic ? 'سطور الحسابات' : 'Account Lines',
                            _buildWebAccountLinesSection(),
                          ),
                      _buildWebSection(
                        widget.isArabic ? 'التوقيعات' : 'Signatures',
                        _buildWebSignaturesSection(),
                      ),
                      _buildWebFooter(),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Color _webAccentColor(
    ({
      String typeKey,
      bool isReceipt,
      bool isPayment,
      bool isAdjustment,
      String titleAr,
      String titleEn,
      Color appColor,
      PdfColor headerBg,
      PdfColor accent,
      IconData icon,
    })
    meta,
  ) {
    if (meta.isReceipt) return const Color(0xFF1A5C35);
    if (meta.isPayment) return const Color(0xFF8B1A1A);
    return const Color(0xFF8B6914);
  }

  ({Color background, Color foreground, Color dot, String label})
  _webStatusPresentation() {
    final raw = widget.voucher['status']?.toString().trim() ?? '';
    final normalized = raw.toLowerCase();
    final isApproved =
        normalized == 'approved' || raw == 'معتمد' || raw == 'approved';
    final isDraft = normalized == 'draft' || raw == 'مسودة';
    final isRejected = normalized == 'rejected' || raw == 'مرفوض';

    if (isApproved) {
      return (
        background: const Color(0xFFEAF3DE),
        foreground: const Color(0xFF27500A),
        dot: const Color(0xFF3B6D11),
        label: widget.isArabic ? 'معتمد ومُصادق عليه' : 'Approved & Verified',
      );
    }
    if (isDraft) {
      return (
        background: const Color(0xFFFFF3D9),
        foreground: const Color(0xFF8A5A00),
        dot: const Color(0xFFBA7517),
        label: widget.isArabic ? 'مسودة' : 'Draft',
      );
    }
    if (isRejected) {
      return (
        background: const Color(0xFFFFE2DE),
        foreground: const Color(0xFF842F1F),
        dot: const Color(0xFFC0392B),
        label: widget.isArabic ? 'مرفوض' : 'Rejected',
      );
    }
    return (
      background: const Color(0xFFF1F0FA),
      foreground: const Color(0xFF5E4A86),
      dot: const Color(0xFF7A4BA0),
      label: raw.isEmpty ? (widget.isArabic ? 'غير محدد' : 'Unspecified') : raw,
    );
  }

  String _fmtHumanDate(dynamic raw) {
    if (raw == null) return '';
    final parsed = DateTime.tryParse(raw.toString());
    if (parsed == null) return raw.toString();
    try {
      return DateFormat(
        'd MMMM yyyy',
        widget.isArabic ? 'ar' : 'en',
      ).format(parsed);
    } catch (_) {
      return DateFormat('yyyy-MM-dd').format(parsed);
    }
  }

  String _amountInWords(double amount) {
    final rounded = amount.toStringAsFixed(2);
    final parts = rounded.split('.');
    final whole = int.tryParse(parts[0]) ?? 0;
    final fraction = int.tryParse(parts[1]) ?? 0;
    final ones = <String>[
      '',
      'واحد',
      'اثنان',
      'ثلاثة',
      'أربعة',
      'خمسة',
      'ستة',
      'سبعة',
      'ثمانية',
      'تسعة',
      'عشرة',
      'أحد عشر',
      'اثنا عشر',
      'ثلاثة عشر',
      'أربعة عشر',
      'خمسة عشر',
      'ستة عشر',
      'سبعة عشر',
      'ثمانية عشر',
      'تسعة عشر',
    ];
    final tens = <String>[
      '',
      'عشرة',
      'عشرون',
      'ثلاثون',
      'أربعون',
      'خمسون',
      'ستون',
      'سبعون',
      'ثمانون',
      'تسعون',
    ];
    final hundreds = <String>[
      '',
      'مائة',
      'مئتان',
      'ثلاثمائة',
      'أربعمائة',
      'خمسمائة',
      'ستمائة',
      'سبعمائة',
      'ثمانمائة',
      'تسعمائة',
    ];

    if (whole == 0) {
      return widget.isArabic
          ? 'صفر ريال سعودي فقط لا غير'
          : 'Zero Saudi Riyals only';
    }

    String numberToArabic(int value) {
      if (value < 20) return ones[value];
      if (value < 100) {
        final one = value % 10;
        final ten = value ~/ 10;
        if (one == 0) return tens[ten];
        return '${ones[one]} و${tens[ten]}';
      }
      if (value < 1000) {
        final hundred = value ~/ 100;
        final remainder = value % 100;
        if (remainder == 0) return hundreds[hundred];
        return '${hundreds[hundred]} و${numberToArabic(remainder)}';
      }
      if (value < 1000000) {
        final thousand = value ~/ 1000;
        final remainder = value % 1000;
        final thousandWord = thousand == 1
            ? 'ألف'
            : thousand == 2
            ? 'ألفان'
            : thousand < 11
            ? '${numberToArabic(thousand)} آلاف'
            : '${numberToArabic(thousand)} ألف';
        if (remainder == 0) return thousandWord;
        return '$thousandWord و${numberToArabic(remainder)}';
      }
      return value.toString();
    }

    final wholeText = numberToArabic(whole);
    if (fraction == 0) return '$wholeText ريال سعودي فقط لا غير';
    return '$wholeText ريال و${numberToArabic(fraction)} هللة فقط لا غير';
  }

  Widget _buildWebVoucherHeader(
    ({
      String typeKey,
      bool isReceipt,
      bool isPayment,
      bool isAdjustment,
      String titleAr,
      String titleEn,
      Color appColor,
      PdfColor headerBg,
      PdfColor accent,
      IconData icon,
    })
    meta,
  ) {
    final accentColor = _webAccentColor(meta);
    final voucherNumber =
        (widget.voucher['voucher_number']?.toString().trim().isNotEmpty ??
            false)
        ? widget.voucher['voucher_number'].toString().trim()
        : 'PV-${widget.voucher['id'] ?? ''}';

    final badgeLabel = widget.isArabic
        ? (meta.isPayment
              ? 'نموذج صرف رسمي'
              : meta.isReceipt
              ? 'نموذج قبض رسمي'
              : 'نموذج سند رسمي')
        : (meta.isPayment
              ? 'Official Payment Voucher'
              : meta.isReceipt
              ? 'Official Receipt Voucher'
              : 'Official Voucher');

    return Container(
      color: const Color(0xFFFAEEDA),
      padding: const EdgeInsets.all(20),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final stacked = constraints.maxWidth < 560;
          final qr = Column(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  color: Colors.white,
                  border: Border.all(color: const Color(0xFFD3B87A)),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const CustomPaint(
                  painter: _VoucherQrPlaceholderPainter(),
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'رمز التحقق',
                style: TextStyle(fontSize: 10, color: Color(0xFF854F0B)),
              ),
            ],
          );

          final titleBlock = Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFBA7517),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        badgeLabel,
                        style: const TextStyle(
                          fontSize: 11,
                          color: Color(0xFFFAEEDA),
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      const SizedBox(width: 5),
                      Transform.rotate(
                        angle: 0.785,
                        child: Container(
                          width: 6,
                          height: 6,
                          color: const Color(0xFFFAEEDA),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  widget.isArabic ? 'خالد للمجوهرات' : 'Khaled Jewelry',
                  style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w500,
                    color: Color(0xFF412402),
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  widget.isArabic ? meta.titleAr : meta.titleEn,
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                    color: accentColor,
                  ),
                ),
                const SizedBox(height: 4),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 9,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFAC775),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    voucherNumber,
                    style: const TextStyle(
                      fontSize: 12,
                      color: Color(0xFF854F0B),
                    ),
                  ),
                ),
              ],
            ),
          );

          if (stacked) {
            return Column(
              children: [
                Align(alignment: AlignmentDirectional.centerEnd, child: qr),
                const SizedBox(height: 16),
                Row(children: [titleBlock]),
              ],
            );
          }

          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [qr, const SizedBox(width: 16), titleBlock],
          );
        },
      ),
    );
  }

  Widget _buildWebStatusStrip(
    ({
      String typeKey,
      bool isReceipt,
      bool isPayment,
      bool isAdjustment,
      String titleAr,
      String titleEn,
      Color appColor,
      PdfColor headerBg,
      PdfColor accent,
      IconData icon,
    })
    meta,
  ) {
    final status = _webStatusPresentation();
    return Container(
      color: status.background,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 7),
      child: Row(
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(
              color: status.dot,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            status.label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: status.foreground,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWebDetailsSection() {
    final voucher = widget.voucher;
    final party = _partyDisplay(voucher);
    final entries = <({String label, String value, Color? valueColor})>[
      (
        label: widget.isArabic ? 'التاريخ' : 'Date',
        value: _fmtHumanDate(voucher['date']),
        valueColor: null,
      ),
      (
        label: widget.isArabic ? 'الحالة' : 'Status',
        value: _webStatusPresentation().label,
        valueColor: _webStatusPresentation().dot,
      ),
      (
        label: widget.isArabic ? 'الطرف' : 'Party',
        value: party.isEmpty ? '—' : party,
        valueColor: null,
      ),
      (
        label: widget.isArabic ? 'أنشئ بواسطة' : 'Created by',
        value: (voucher['created_by']?.toString().trim().isNotEmpty ?? false)
            ? voucher['created_by'].toString().trim()
            : (widget.isArabic ? 'النظام' : 'System'),
        valueColor: null,
      ),
      (
        label: widget.isArabic ? 'اعتمد بواسطة' : 'Approved by',
        value: (voucher['approved_by']?.toString().trim().isNotEmpty ?? false)
            ? voucher['approved_by'].toString().trim()
            : '—',
        valueColor: null,
      ),
      (
        label: widget.isArabic ? 'البيان' : 'Description',
        value: (voucher['description']?.toString().trim().isNotEmpty ?? false)
            ? voucher['description'].toString().trim()
            : '—',
        valueColor: null,
      ),
    ];

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final availableWidth = constraints.maxWidth;
          final columns = availableWidth < 560
              ? 1
              : availableWidth < 760
              ? 2
              : 3;
          final spacing = 8.0;
          final itemWidth = columns == 1
              ? availableWidth
              : (availableWidth - ((columns - 1) * spacing)) / columns;

          return Wrap(
            spacing: spacing,
            runSpacing: spacing,
            children: entries
                .map(
                  (entry) => SizedBox(
                    width: itemWidth,
                    child: _buildWebDetailCell(
                      label: entry.label,
                      value: entry.value,
                      valueColor: entry.valueColor,
                    ),
                  ),
                )
                .toList(),
          );
        },
      ),
    );
  }

  Widget _buildWebDetailCell({
    required String label,
    required String value,
    Color? valueColor,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F7F5),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            label,
            style: const TextStyle(fontSize: 10, color: Color(0xFF888888)),
          ),
          const SizedBox(height: 3),
          Text(
            value,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w500,
              color: valueColor ?? const Color(0xFF222222),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWebAmountSection(
    ({
      String typeKey,
      bool isReceipt,
      bool isPayment,
      bool isAdjustment,
      String titleAr,
      String titleEn,
      Color appColor,
      PdfColor headerBg,
      PdfColor accent,
      IconData icon,
    })
    meta,
  ) {
    final voucher = widget.voucher;
    final currencyFormat = NumberFormat('#,##0.00', 'ar');
    final goldFormat = NumberFormat('#,##0.000', 'ar');
    final cashAmount = _toDouble(voucher['amount_cash']);
    final goldAmount = _toDouble(voucher['amount_gold']);
    final equivalentWeight = _toDouble(voucher['amount_gold_main_karat']);
    final mainKaratLabel = _toDouble(voucher['main_karat']);

    final extraRows = <Widget>[];
    if (goldAmount > 0) {
      extraRows.add(
        _buildWebAmountMetaRow(
          widget.isArabic ? 'وزن الذهب' : 'Gold Weight',
          '${goldFormat.format(goldAmount)} ${widget.isArabic ? 'جرام' : 'g'}',
        ),
      );
    }
    if (equivalentWeight > 0) {
      extraRows.add(
        _buildWebAmountMetaRow(
          widget.isArabic
              ? 'الوزن المكافئ (العيار الرئيسي)'
              : 'Equivalent weight (main karat)',
          '${goldFormat.format(equivalentWeight)} ${widget.isArabic ? 'جرام' : 'g'}${mainKaratLabel > 0 ? ' (${mainKaratLabel.toStringAsFixed(mainKaratLabel == mainKaratLabel.roundToDouble() ? 0 : 3)})' : ''}',
        ),
      );
    }

    final primaryLabel = cashAmount > 0
        ? (widget.isArabic ? 'المبلغ نقداً' : 'Cash Amount')
        : (widget.isArabic ? 'وزن الذهب' : 'Gold Weight');
    final primaryValue = cashAmount > 0
        ? '${currencyFormat.format(cashAmount)} ${widget.isArabic ? 'ريال' : 'SAR'}'
        : '${goldFormat.format(goldAmount)} ${widget.isArabic ? 'جرام' : 'g'}';
    final words = cashAmount > 0 ? _amountInWords(cashAmount) : null;

    // ── Clean Luxury redesign: top-border only, no heavy box ──────────────
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 18),
      decoration: const BoxDecoration(
        color: Color(0xFFFAFAF8),
        border: Border(
          top: BorderSide(color: Color(0xFFD4B76A), width: 2),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Primary amount row — value on the right for RTL
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              // Value block (right/end side visually)
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      primaryValue,
                      textAlign: TextAlign.end,
                      style: const TextStyle(
                        fontSize: 26,
                        fontWeight: FontWeight.w600,
                        letterSpacing: -0.5,
                        color: Color(0xFF2C1A00),
                      ),
                    ),
                    if (words != null) ...[
                      const SizedBox(height: 3),
                      Text(
                        words,
                        textAlign: TextAlign.end,
                        style: const TextStyle(
                          fontSize: 11,
                          color: Color(0xFF8B6914),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 14),
              // Label (left side)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  primaryLabel,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFF999999),
                  ),
                ),
              ),
            ],
          ),
          if (extraRows.isNotEmpty) ...[
            const SizedBox(height: 14),
            Container(height: 0.8, color: const Color(0xFFE2D9C5)),
            const SizedBox(height: 12),
            ...extraRows,
          ],
        ],
      ),
    );
  }

  Widget _buildWebAmountMetaRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(fontSize: 11, color: Color(0xFF999999)),
          ),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.end,
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: Color(0xFF2C1A00),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWebSignaturesSection() {
    final voucher = widget.voucher;
    final party = _partyDisplay(voucher);
    final signatures = <({String title, String name})>[
      (
        title: widget.isArabic ? 'توقيع المسلّم' : 'Delivered By',
        name: (voucher['created_by']?.toString().trim().isNotEmpty ?? false)
            ? voucher['created_by'].toString().trim()
            : (widget.isArabic
                  ? 'النظام / خالد للمجوهرات'
                  : 'System / Khaled Jewelry'),
      ),
      (
        title: widget.isArabic ? 'توقيع المستلم' : 'Receiver Signature',
        name: (voucher['receiver_name']?.toString().trim().isNotEmpty ?? false)
            ? voucher['receiver_name'].toString().trim()
            : (party.isEmpty ? '—' : party),
      ),
      (
        title: widget.isArabic ? 'اعتماد السند' : 'Approved By',
        name: (voucher['approved_by']?.toString().trim().isNotEmpty ?? false)
            ? voucher['approved_by'].toString().trim()
            : '—',
      ),
    ];

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final stacked = constraints.maxWidth < 680;
          return Column(
            children: [
              stacked
                  ? Column(
                      children: signatures
                          .map(
                            (signature) => Padding(
                              padding: const EdgeInsets.only(bottom: 12),
                              child: _buildWebSignatureCell(
                                title: signature.title,
                                name: signature.name,
                              ),
                            ),
                          )
                          .toList(),
                    )
                  : Row(
                      children: [
                        for (
                          var index = 0;
                          index < signatures.length;
                          index++
                        ) ...[
                        Expanded(
                          child: _buildWebSignatureCell(
                            title: signatures[index].title,
                            name: signatures[index].name,
                          ),
                        ),
                          if (index < signatures.length - 1)
                            const SizedBox(width: 12),
                        ],
                      ],
                    ),
              const SizedBox(height: 12),
              Container(
                height: 52,
                decoration: BoxDecoration(
                  border: Border.all(color: const Color(0xFFCCCCCC)),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Center(
                  child: Text(
                    widget.isArabic ? 'ختم المؤسسة' : 'Company Stamp',
                    style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xFFAAAAAA),
                    ),
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildWebGoldBreakdownSection() {
    final rows = _goldRows();
    final goldFormat = NumberFormat('#,##0.000', 'ar');
    final currencyFormat = NumberFormat('#,##0.00', 'ar');

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        children: [
          _buildWebTableHeader([
            widget.isArabic ? 'البيان' : 'Description',
            widget.isArabic ? 'العيار' : 'Karat',
            widget.isArabic ? 'الصافي' : 'Net',
            widget.isArabic ? 'تقديري' : 'Est.',
          ]),
          ...rows
              .take(6)
              .map(
                (row) => _buildWebTableRow([
                  row['description']?.toString() ?? '—',
                  row['karat']?.toString() ?? '—',
                  '${goldFormat.format(_toDouble(row['netWeight']))} ${widget.isArabic ? 'جم' : 'g'}',
                  _toDouble(row['estimatedCash']) > 0
                      ? '${currencyFormat.format(_toDouble(row['estimatedCash']))} ${widget.isArabic ? 'ر.س' : 'SAR'}'
                      : '—',
                ]),
              ),
        ],
      ),
    );
  }

  Widget _buildWebAccountLinesSection() {
    final raw = widget.voucher['account_lines'];
    final lines = raw is List
        ? raw.whereType<Map>().cast<Map<String, dynamic>>().toList()
        : <Map<String, dynamic>>[];
    final currencyFormat = NumberFormat('#,##0.00', 'ar');
    final goldFormat = NumberFormat('#,##0.000', 'ar');

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        children: [
          _buildWebTableHeader([
            widget.isArabic ? 'الحساب' : 'Account',
            widget.isArabic ? 'النوع' : 'Type',
            widget.isArabic ? 'القيمة' : 'Amount',
            widget.isArabic ? 'العيار' : 'Karat',
          ]),
          ...lines.take(6).map((line) {
            final account = line['account'] is Map
                ? (line['account'] as Map).cast<dynamic, dynamic>()
                : const <dynamic, dynamic>{};
            final amountType = (line['amount_type']?.toString() ?? '')
                .toLowerCase();
            final amount = _toDouble(line['amount']);
            final amountText = amountType == 'gold'
                ? '${goldFormat.format(amount)} ${widget.isArabic ? 'جم' : 'g'}'
                : '${currencyFormat.format(amount)} ${widget.isArabic ? 'ر.س' : 'SAR'}';
            final typeText =
                '${line['line_type'] ?? '—'} / ${line['amount_type'] ?? '—'}';
            return _buildWebTableRow([
              account['name']?.toString() ?? '—',
              typeText,
              amountText,
              line['karat']?.toString() ?? '—',
            ]);
          }),
        ],
      ),
    );
  }

  Widget _buildWebTableHeader(List<String> columns) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFFF7F7F5),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        children: [
          for (var index = 0; index < columns.length; index++) ...[
            Expanded(
              child: Text(
                columns[index],
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF854F0B),
                ),
              ),
            ),
            if (index < columns.length - 1) const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }

  Widget _buildWebTableRow(List<String> values) {
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: const Color(0xFFE7E0CF)),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        children: [
          for (var index = 0; index < values.length; index++) ...[
            Expanded(
              child: Text(
                values[index],
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 11, color: Color(0xFF444444)),
              ),
            ),
            if (index < values.length - 1) const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }

  Widget _buildWebSignatureCell({required String title, required String name}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          title,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 11, color: Color(0xFF666666)),
        ),
        const SizedBox(height: 28),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.only(top: 5),
          decoration: const BoxDecoration(
            border: Border(top: BorderSide(color: Color(0xFFCCCCCC))),
          ),
          child: Text(
            name,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 10, color: Color(0xFF888888)),
          ),
        ),
      ],
    );
  }

  Widget _buildWebFooter() {
    final voucherNumber =
        (widget.voucher['voucher_number']?.toString().trim().isNotEmpty ??
            false)
        ? widget.voucher['voucher_number'].toString().trim()
        : 'PV-${widget.voucher['id'] ?? ''}';

    return Container(
      color: const Color(0xFFF7F7F5),
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final items = <Widget>[
            Text(
              '${widget.isArabic ? 'طُبع بتاريخ' : 'Printed on'}: ${_fmtHumanDate(DateTime.now().toIso8601String())}',
              style: const TextStyle(fontSize: 10, color: Color(0xFFAAAAAA)),
            ),
            Text(
              widget.isArabic
                  ? 'خالد للمجوهرات — جميع الحقوق محفوظة'
                  : 'Khaled Jewelry — All rights reserved',
              style: const TextStyle(fontSize: 10, color: Color(0xFFAAAAAA)),
            ),
            Text(
              voucherNumber,
              style: const TextStyle(fontSize: 10, color: Color(0xFFAAAAAA)),
            ),
          ];

          if (constraints.maxWidth < 640) {
            return Wrap(
              spacing: 12,
              runSpacing: 6,
              alignment: WrapAlignment.spaceBetween,
              children: items,
            );
          }

          return Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: items,
          );
        },
      ),
    );
  }

  Widget _buildWebSection(String title, Widget child) {
    return Container(
      decoration: const BoxDecoration(
        border: Border(
          bottom: BorderSide(color: Color(0xFFE0E0E0), width: 0.5),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 8),
            child: Text(
              title,
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w500,
                color: Color(0xFFBA7517),
                letterSpacing: 0.07,
              ),
            ),
          ),
          child,
          const SizedBox(height: 14),
        ],
      ),
    );
  }

  /// Show a non-dismissible loading dialog and return its navigator for
  /// popping later.
  NavigatorState _showLoadingDialog() {
    final rootNav = Navigator.of(context, rootNavigator: true);
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      useRootNavigator: true,
      builder: (_) => AlertDialog(
        content: Row(
          children: [
            const SizedBox(
              width: 22, height: 22,
              child: CircularProgressIndicator(strokeWidth: 2.5),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Text(
                widget.isArabic
                    ? 'جارٍ تجهيز السند...'
                    : 'Preparing voucher...',
              ),
            ),
          ],
        ),
      ),
    );
    return rootNav;
  }

  Future<void> _downloadPdf() async {
    final rootNav = _showLoadingDialog();
    try {
      final pdf = await _generatePdf(_getPdfPageFormat());
      if (mounted) rootNav.pop();

      await Printing.sharePdf(
        bytes: pdf,
        filename: 'voucher_${widget.voucher['id']}.pdf',
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              widget.isArabic
                  ? '✓ تم تحميل السند بنجاح'
                  : '✓ Voucher downloaded successfully',
            ),
            backgroundColor: Colors.green,
          ),
        );
      }
    } catch (e) {
      if (mounted) rootNav.pop();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${widget.isArabic ? 'خطأ' : 'Error'}: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> _printPdf() async {
    final rootNav = _showLoadingDialog();
    try {
      // Pre-generate the PDF bytes under the loading dialog, then hand off.
      final pdfBytes = await _generatePdf(_getPdfPageFormat());
      if (mounted) rootNav.pop();

      await Printing.layoutPdf(
        onLayout: (_) async => pdfBytes,
        name: 'voucher_${widget.voucher['id']}.pdf',
      );

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              widget.isArabic
                  ? '✓ تم إرسال السند للطباعة'
                  : '✓ Voucher sent to printer',
            ),
            backgroundColor: Colors.green,
          ),
        );
      }
    } catch (e) {
      if (mounted) rootNav.pop();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${widget.isArabic ? 'خطأ' : 'Error'}: $e'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  PdfPageFormat _getPdfPageFormat() {
    PdfPageFormat base;
    switch (_paperSize) {
      case 'A5':
        base = PdfPageFormat.a5;
        break;
      case 'Letter':
        base = PdfPageFormat.letter;
        break;
      case 'Thermal':
        // Thermal is typically portrait only.
        return const PdfPageFormat(80 * PdfPageFormat.mm, double.infinity);
      default:
        base = PdfPageFormat.a4;
    }

    if (_orientation == 'landscape') return base.landscape;
    return base;
  }

  Future<Uint8List> _generatePdf(PdfPageFormat format) async {
    // ── 1. Fonts: use pre-cached bytes (no async I/O on rebuild) ──────────
    await _preloadAssets();
    pw.Font fontReg, fontBold;
    if (_cachedFontRegBytes != null && _cachedFontBoldBytes != null) {
      fontReg  = pw.Font.ttf(_cachedFontRegBytes!.buffer.asByteData());
      fontBold = pw.Font.ttf(_cachedFontBoldBytes!.buffer.asByteData());
    } else {
      fontReg  = await PdfGoogleFonts.cairoRegular();
      fontBold = await PdfGoogleFonts.cairoBold();
    }

    // ── 2. Dynamic data ────────────────────────────────────────────────────
    final voucher     = widget.voucher;
    final meta        = _voucherMeta();
    final webStatus   = _webStatusPresentation();
    final bool isA5Format = ((format.width  <= PdfPageFormat.a5.width  + 1 &&
            format.height <= PdfPageFormat.a5.height + 1) ||
        _paperSize == 'A5');
    final bool isA5 = isA5Format;

    final currencyFmt = NumberFormat('#,##0.00', 'ar');
    final goldFmt     = NumberFormat('#,##0.000', 'ar');

    final party       = _partyDisplay(voucher);
    final voucherNum  = (voucher['voucher_number']?.toString().trim().isNotEmpty ?? false)
        ? voucher['voucher_number'].toString().trim()
        : '#${voucher['id'] ?? ''}';
    final createdBy   = voucher['created_by']?.toString().trim() ?? '';
    final approvedBy  = voucher['approved_by']?.toString().trim() ?? '';
    final description = (voucher['description']?.toString().trim().isNotEmpty ?? false)
        ? voucher['description'].toString().trim()
        : '\u2014';
    final statusText  = webStatus.label;
    final dateText    = _fmtHumanDate(voucher['date']);
    final printDate   = _fmtHumanDate(DateTime.now().toIso8601String());
    final title       = widget.isArabic ? meta.titleAr : meta.titleEn;

    final cashAmt     = _toDouble(voucher['amount_cash']);
    final goldAmt     = _toDouble(voucher['amount_gold']);
    final equivWeight = _toDouble(voucher['amount_gold_main_karat']);
    final mainKarat   = _toDouble(voucher['main_karat']);
    final goldRows    = _goldRows();
    final hasCash     = cashAmt.abs() > 0.000001;
    final hasGold     = goldAmt.abs() > 0.000001;

    // ── Company branding from SettingsProvider ────────────────────────────
    SettingsProvider? sp;
    try { sp = context.read<SettingsProvider>(); } catch (_) {}
    final spName     = (sp?.companyName.trim() ?? '');
    final company    = spName.isNotEmpty
        ? spName
        : (widget.isArabic ? '\u062e\u0627\u0644\u062f \u0644\u0644\u0645\u062c\u0648\u0647\u0631\u0627\u062a' : 'Khaled Jewelry');
    final companyCr      = (sp?.companyCrNumber.trim() ?? '');
    final companyVat     = (sp?.companyTaxNumber.trim() ?? '');
    final companyPhone   = (sp?.companyPhone.trim() ?? '');
    final companyAddr    = (sp?.companyAddress.trim() ?? '');
    final showLogo       = sp?.showCompanyLogo ?? true;
    final logoBase64     = (sp?.settings['company_logo_base64'] ?? '').toString().trim();
    pw.MemoryImage? logoImage;
    if (showLogo && logoBase64.isNotEmpty) {
      try {
        var logoPayload = logoBase64;
        final commaIdx = logoPayload.indexOf(',');
        if (logoPayload.startsWith('data:') && commaIdx >= 0) logoPayload = logoPayload.substring(commaIdx + 1);
        final rawLogoBytes = base64Decode(logoPayload);
        if (rawLogoBytes.isNotEmpty) {
          final resized = await _resizeImageBytes(rawLogoBytes, 128);
          logoImage = pw.MemoryImage(resized);
        }
      } catch (_) {}
    }
    // Fallback: use pre-cached bundled logo (already resized to 128×128)
    if (logoImage == null && showLogo && _cachedLogoBytes != null) {
      logoImage = pw.MemoryImage(_cachedLogoBytes!);
    }

    // Account lines (archive toggle)
    final accountLinesRaw = voucher['account_lines'];
    final accountLines    = accountLinesRaw is List
        ? accountLinesRaw.whereType<Map<String, dynamic>>().toList()
        : <Map<String, dynamic>>[];
    final bool compactAL = isA5 || accountLines.length > 8;
    final int  maxAL     = compactAL ? (isA5 ? 9 : 12) : 14;
    final visibleAL      = accountLines.take(maxAL).toList();
    final int  hiddenAL  = accountLines.length > maxAL ? accountLines.length - maxAL : 0;

    // \u2500\u2500 3. Text helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    pw.TextStyle ts({
      double size = 10,
      bool bold = false,
      PdfColor color = VColors.black,
    }) =>
        pw.TextStyle(
          font: bold ? fontBold : fontReg,
          fontSize: size,
          color: color,
        );

    pw.Widget txt(
      String t, {
      double size = 10,
      bool bold = false,
      PdfColor color = VColors.black,
    }) =>
        pw.Text(
          t,
          style: ts(size: size, bold: bold, color: color),
          textDirection: pw.TextDirection.rtl,
        );

    // \u2500\u2500 4. Section helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    pw.Widget sectionTitle(String t) => pw.Padding(
          padding: const pw.EdgeInsets.only(bottom: 8),
          child: pw.Align(
            alignment: pw.Alignment.centerRight,
            child: txt(t,
                size: isA5 ? 7.5 : 8.5, bold: true, color: VColors.amberMid),
          ),
        );

    pw.Widget section(pw.Widget child, {bool last = false}) => pw.Container(
          decoration: pw.BoxDecoration(
            border: last
                ? null
                : const pw.Border(
                    bottom:
                        pw.BorderSide(color: VColors.grayBorder, width: 0.5)),
          ),
          padding: pw.EdgeInsets.symmetric(
            horizontal: isA5 ? 12 : 16,
            vertical:   isA5 ?  8 : 10,
          ),
          child: child,
        );

    // ── 5. HEADER (exact account-statement identity) ──────────────────────────────────
    pw.Widget buildHeader() {
      // Local helpers matching AccountStatementPdfBuilder
      pw.Widget goldRule({double height = 4}) => pw.Container(
        height: height,
        decoration: const pw.BoxDecoration(
          gradient: pw.LinearGradient(
            colors: [
              PdfColor.fromInt(0xFF8B6914),
              PdfColor.fromInt(0xFFC9A84C),
              PdfColor.fromInt(0xFFE8C97A),
              PdfColor.fromInt(0xFFC9A84C),
              PdfColor.fromInt(0xFF8B6914),
            ],
          ),
        ),
      );

      pw.Widget thinRule() => pw.Container(
        height: 0.8,
        color: VColors.amberBorder,
      );

      // infoLine — matches AccountStatementPdfBuilder._infoLine exactly:
      // plain Row (no Directionality wrapper), value on LEFT, label on RIGHT,
      // both with textDirection:rtl so Arabic shaping applies correctly.
      pw.Widget infoLine(String label, String value) => pw.Padding(
        padding: const pw.EdgeInsets.only(bottom: 3),
        child: pw.Row(
          mainAxisSize: pw.MainAxisSize.min,
          children: [
            pw.Text(
              '$label:',
              textDirection: pw.TextDirection.rtl,
              style: pw.TextStyle(
                  font: fontReg, fontSize: 8,
                  color: PdfColor.fromInt(0xFF444444)),
            ),
            pw.SizedBox(width: 6),
            pw.Text(
              value,
              textDirection: pw.TextDirection.rtl,
              style: pw.TextStyle(
                  font: fontReg, fontSize: 8,
                  color: PdfColor.fromInt(0xFF666666)),
            ),
          ],
        ),
      );

      final subtitleEn = meta.isPayment
          ? 'Payment Voucher'
          : meta.isReceipt
              ? 'Receipt Voucher'
              : 'Adjustment Voucher';

      return pw.Column(
        crossAxisAlignment: pw.CrossAxisAlignment.stretch,
        children: [
          goldRule(height: 4),
          pw.SizedBox(height: 8),

          // 3-zone Stack — no background container, sits on white page
          pw.SizedBox(
            height: isA5 ? 108 : 128,
            child: pw.Stack(
              children: [

                // ── LEFT ZONE (w:148) — رقم السند / التاريخ / الطرف ──
                pw.Positioned(
                  top: 0,
                  left: 0,
                  child: pw.SizedBox(
                    width: isA5 ? 120 : 148,
                    child: pw.Column(
                      crossAxisAlignment: pw.CrossAxisAlignment.start,
                      children: [
                        pw.Align(
                          alignment: pw.Alignment.centerLeft,
                          child: pw.Text('رقم السند',
                            textDirection: pw.TextDirection.rtl,
                            style: pw.TextStyle(font: fontReg, fontSize: 7,
                                color: PdfColor.fromInt(0xFF666666))),
                        ),
                        pw.SizedBox(height: 1),
                        pw.Align(
                          alignment: pw.Alignment.centerLeft,
                          child: pw.Text(voucherNum,
                            style: pw.TextStyle(font: fontBold, fontSize: 8.5,
                                color: PdfColor.fromInt(0xFF222222))),
                        ),
                        pw.SizedBox(height: 6),
                        pw.Align(
                          alignment: pw.Alignment.centerLeft,
                          child: pw.Text('التاريخ',
                            textDirection: pw.TextDirection.rtl,
                            style: pw.TextStyle(font: fontReg, fontSize: 7,
                                color: PdfColor.fromInt(0xFF666666))),
                        ),
                        pw.SizedBox(height: 1),
                        pw.Align(
                          alignment: pw.Alignment.centerLeft,
                          child: pw.Text(dateText.isEmpty ? '—' : dateText,
                            textDirection: pw.TextDirection.rtl,
                            style: pw.TextStyle(font: fontBold, fontSize: 8.5,
                                color: PdfColor.fromInt(0xFF222222))),
                        ),
                        if (party.isNotEmpty) ...[
                          pw.SizedBox(height: 6),
                          pw.Container(height: 0.6, color: VColors.amberBorder),
                          pw.SizedBox(height: 6),
                          pw.Align(
                            alignment: pw.Alignment.centerLeft,
                            child: pw.Text('الطرف',
                              textDirection: pw.TextDirection.rtl,
                              style: pw.TextStyle(font: fontReg, fontSize: 7,
                                  color: PdfColor.fromInt(0xFF666666))),
                          ),
                          pw.SizedBox(height: 1),
                          pw.Align(
                            alignment: pw.Alignment.centerLeft,
                            child: pw.Text(party,
                              textDirection: pw.TextDirection.rtl,
                              style: pw.TextStyle(font: fontBold, fontSize: 8.5,
                                  color: PdfColor.fromInt(0xFF222222))),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),

                // ── CENTER ZONE — title + subtitle + QR ──
                pw.Positioned(
                  top: 8,
                  left: isA5 ? 124.0 : 152.0,
                  right: isA5 ? 124.0 : 164.0,
                  child: pw.Column(
                    crossAxisAlignment: pw.CrossAxisAlignment.center,
                    children: [
                      pw.Text(
                        title,
                        textDirection: pw.TextDirection.rtl,
                        style: pw.TextStyle(
                            font: fontBold,
                            fontSize: isA5 ? 18 : 22,
                            color: PdfColor.fromInt(0xFF111111)),
                      ),
                      pw.SizedBox(height: 3),
                      pw.Text(
                        subtitleEn,
                        style: pw.TextStyle(
                          font: fontReg,
                          fontSize: 8.5,
                          color: PdfColor.fromInt(0xFF666666),
                          letterSpacing: 1.8,
                        ),
                      ),
                      pw.SizedBox(height: 8),
                      pw.Align(
                        alignment: pw.Alignment.center,
                        child: pw.Column(
                          children: [
                            pw.Container(
                              width: 50,
                              height: 50,
                              padding: const pw.EdgeInsets.all(2),
                              decoration: pw.BoxDecoration(
                                border: pw.Border.all(
                                    color: VColors.amberDark, width: 0.8),
                              ),
                              child: pw.BarcodeWidget(
                                barcode: pw.Barcode.qrCode(),
                                data: _voucherQrPayload(),
                                color: VColors.amberDark,
                              ),
                            ),
                            pw.SizedBox(height: 3),
                            pw.Text(
                              widget.isArabic ? 'تحقق من السند' : 'Verify Voucher',
                              textDirection: pw.TextDirection.rtl,
                              style: pw.TextStyle(font: fontReg, fontSize: 6,
                                  color: PdfColor.fromInt(0xFF666666)),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),

                // ── RIGHT ZONE (w:160) — company logo+name + separator + branding details ──
                pw.Positioned(
                  top: 0,
                  right: 0,
                  child: pw.SizedBox(
                    width: isA5 ? 120 : 160,
                    child: pw.Column(
                      crossAxisAlignment: pw.CrossAxisAlignment.end,
                      children: [
                        // Logo + company name — aligned to right edge
                        pw.Align(
                          alignment: pw.Alignment.centerRight,
                          child: pw.Directionality(
                            textDirection: pw.TextDirection.rtl,
                            child: pw.Row(
                              mainAxisSize: pw.MainAxisSize.min,
                              crossAxisAlignment: pw.CrossAxisAlignment.center,
                              children: [
                                if (logoImage != null)
                                  pw.Image(logoImage,
                                      width: 38, height: 38,
                                      fit: pw.BoxFit.contain),
                                if (logoImage != null) pw.SizedBox(width: 6),
                                if (company.trim().isNotEmpty)
                                  pw.Text(
                                    company.trim(),
                                    style: pw.TextStyle(font: fontBold,
                                        fontSize: 14,
                                        color: PdfColor.fromInt(0xFF111111)),
                                  ),
                              ],
                            ),
                          ),
                        ),
                        pw.SizedBox(height: 5),
                        pw.Container(height: 0.6, color: VColors.amberBorder),
                        pw.SizedBox(height: 5),
                        // Company details (CR / VAT / phone / address)
                        if (companyCr.isNotEmpty)
                          pw.Align(
                            alignment: pw.Alignment.centerRight,
                            child: infoLine('سجل تجاري ', companyCr),
                          ),
                        if (companyVat.isNotEmpty)
                          pw.Align(
                            alignment: pw.Alignment.centerRight,
                            child: infoLine('الرقم الضريبي', companyVat),
                          ),
                        if (companyPhone.isNotEmpty)
                          pw.Align(
                            alignment: pw.Alignment.centerRight,
                            child: infoLine('الجوال', companyPhone),
                          ),
                        if (companyAddr.isNotEmpty)
                          pw.Align(
                            alignment: pw.Alignment.centerRight,
                            child: infoLine('العنوان', companyAddr),
                          ),
                      ],
                    ),
                  ),
                ),

              ],
            ),
          ),

          // Post-header separators (exact account-statement sequence)
          pw.SizedBox(height: 6),
          pw.Container(height: 0.8, color: VColors.amberBorder),
          pw.SizedBox(height: 10),
          goldRule(height: 3),
          pw.SizedBox(height: 1),
          thinRule(),
          pw.SizedBox(height: 10),
        ],
      );
    }

    pw.Widget buildStatusStrip() {
      final raw = voucher['status']?.toString().trim() ?? '';
      if (raw.isEmpty) return pw.SizedBox.shrink();
      final PdfColor stripBg   = PdfColor.fromInt(webStatus.background.value);
      final PdfColor dotColor  = PdfColor.fromInt(webStatus.dot.value);
      final PdfColor textColor = PdfColor.fromInt(webStatus.foreground.value);
      return pw.Container(
        padding: pw.EdgeInsets.symmetric(
            horizontal: isA5 ? 12 : 16, vertical: isA5 ? 5 : 6),
        decoration: pw.BoxDecoration(
          color: stripBg,
          border: const pw.Border(
              bottom: pw.BorderSide(color: VColors.grayBorder, width: 0.5)),
        ),
        child: pw.Row(
          mainAxisAlignment: pw.MainAxisAlignment.end,
          children: [
            txt(statusText, size: isA5 ? 8 : 9, bold: true, color: textColor),
            pw.SizedBox(width: 6),
            pw.Container(
              width: 7,
              height: 7,
              decoration:
                  pw.BoxDecoration(color: dotColor, shape: pw.BoxShape.circle),
            ),
          ],
        ),
      );
    }

    // \u2500\u2500 7. DETAILS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    pw.Widget detCell(String label, String value, {PdfColor? valueColor}) =>
        pw.Expanded(
          child: pw.Container(
            padding: pw.EdgeInsets.symmetric(
                horizontal: isA5 ? 7 : 9, vertical: isA5 ? 5 : 7),
            decoration: pw.BoxDecoration(
              color: const PdfColor.fromInt(0xFFFAFAF8),
              border: pw.Border(
                top: pw.BorderSide(color: VColors.amberBorder, width: 1.5),
              ),
            ),
            child: pw.Column(
              crossAxisAlignment: pw.CrossAxisAlignment.start,
              children: [
                txt(label, size: isA5 ? 6.5 : 7.5, color: VColors.grayText),
                pw.SizedBox(height: 2),
                txt(value,
                    size: isA5 ? 8.5 : 10,
                    bold: true,
                    color: valueColor ?? VColors.black),
              ],
            ),
          ),
        );

    pw.Widget buildDetails() => section(
          pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.stretch,
            children: [
              sectionTitle(
                  widget.isArabic ? '\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0633\u0646\u062f' : 'Voucher Details'),
              pw.Row(children: [
                detCell(widget.isArabic ? '\u0627\u0644\u062a\u0627\u0631\u064a\u062e' : 'Date',
                    dateText.isEmpty ? '\u2014' : dateText),
                pw.SizedBox(width: 4),
                detCell(
                  widget.isArabic ? '\u0627\u0644\u062d\u0627\u0644\u0629' : 'Status',
                  statusText,
                  valueColor: PdfColor.fromInt(webStatus.dot.value),
                ),
                pw.SizedBox(width: 4),
                detCell(widget.isArabic ? '\u0627\u0644\u0637\u0631\u0641' : 'Party',
                    party.isEmpty ? '\u2014' : party),
              ]),
              pw.SizedBox(height: 4),
              pw.Row(children: [
                detCell(
                  widget.isArabic ? '\u0623\u0646\u0634\u0626 \u0628\u0648\u0627\u0633\u0637\u0629' : 'Created by',
                  createdBy.isEmpty
                      ? (widget.isArabic ? '\u0627\u0644\u0646\u0638\u0627\u0645' : 'System')
                      : createdBy,
                ),
                pw.SizedBox(width: 4),
                detCell(widget.isArabic ? '\u0627\u0639\u062a\u0645\u062f \u0628\u0648\u0627\u0633\u0637\u0629' : 'Approved by',
                    approvedBy.isEmpty ? '\u2014' : approvedBy),
                pw.SizedBox(width: 4),
                detCell(widget.isArabic ? '\u0627\u0644\u0628\u064a\u0627\u0646' : 'Description', description),
              ]),
            ],
          ),
        );

    // \u2500\u2500 8. AMOUNTS \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    pw.Widget amtRow(
            String label, String mainVal, String subText, bool isLast) =>
        pw.Container(
          padding: pw.EdgeInsets.symmetric(
              horizontal: isA5 ? 12 : 16, vertical: isA5 ? 8 : 10),
          decoration: isLast
              ? null
              : const pw.BoxDecoration(
                  border: pw.Border(
                      bottom: pw.BorderSide(
                          color: VColors.amberBorder, width: 0.5))),
          child: pw.Row(
            children: [
              pw.Expanded(
                flex: 6,
                child: pw.Column(
                  crossAxisAlignment: pw.CrossAxisAlignment.start,
                  children: [
                    txt(mainVal,
                        size: isA5 ? 14 : 16,
                        bold: true,
                        color: VColors.amberDark),
                    if (subText.isNotEmpty) ...[
                      pw.SizedBox(height: 2),
                      txt(subText, size: isA5 ? 7 : 8, color: VColors.amberMid),
                    ],
                  ],
                ),
              ),
              pw.Expanded(
                flex: 4,
                child: pw.Align(
                  alignment: pw.Alignment.centerRight,
                  child: txt(label,
                      size: isA5 ? 8 : 9,
                      bold: true,
                      color: VColors.amberMid),
                ),
              ),
            ],
          ),
        );

    pw.Widget buildAmounts() {
      final rows = <pw.Widget>[];

      if (hasGold) {
        final karatSuffix =
            (voucher['gold_karat']?.toString().trim().isNotEmpty ?? false)
                ? ' (${voucher['gold_karat'].toString().trim()})'
                : '';
        final mk = mainKarat > 0 ? mainKarat.toStringAsFixed(0) : '';
        if (equivWeight > 0) {
          // Primary = equivalent weight in main karat; total weight is secondary
          final totalSub = widget.isArabic
              ? '\u0627\u0644\u0648\u0632\u0646 \u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a: ${goldFmt.format(goldAmt)} \u062c\u0631\u0627\u0645$karatSuffix'
              : 'Total weight: ${goldFmt.format(goldAmt)} g$karatSuffix';
          rows.add(amtRow(
            widget.isArabic
                ? '\u0627\u0644\u0648\u0632\u0646 \u0627\u0644\u0645\u0643\u0627\u0641\u0626 (\u0639\u064a\u0627\u0631 $mk)'
                : 'Equiv. Weight (Karat $mk)',
            '${goldFmt.format(equivWeight)} ${widget.isArabic ? '\u062c\u0631\u0627\u0645' : 'g'}',
            totalSub,
            !hasCash,
          ));
        } else {
          // No equiv weight — show total as primary
          rows.add(amtRow(
            widget.isArabic ? '\u0648\u0632\u0646 \u0627\u0644\u0630\u0647\u0628 \u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a' : 'Total Gold Weight',
            '${goldFmt.format(goldAmt)} ${widget.isArabic ? '\u062c\u0631\u0627\u0645' : 'g'}$karatSuffix',
            '',
            !hasCash,
          ));
        }
      }

      if (hasCash) {
        rows.add(amtRow(
          widget.isArabic ? '\u0627\u0644\u0645\u0628\u0644\u063a \u0627\u0644\u0646\u0642\u062f\u064a' : 'Cash Amount',
          '${currencyFmt.format(cashAmt)} ${widget.isArabic ? '\u0631\u064a\u0627\u0644' : 'SAR'}',
          _amountInWords(cashAmt),
          true,
        ));
      }

      if (rows.isEmpty) return pw.SizedBox.shrink();

      return section(
        pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.stretch,
          children: [
            sectionTitle(widget.isArabic ? '\u0627\u0644\u0645\u0628\u0627\u0644\u063a' : 'Amounts'),
            pw.Container(
              decoration: pw.BoxDecoration(
                color: VColors.amberLight,
                border: pw.Border.all(color: VColors.amberBorder, width: 0.5),
                borderRadius: pw.BorderRadius.circular(8),
              ),
              child: pw.Column(children: rows),
            ),
          ],
        ),
      );
    }

    // \u2500\u2500 9. DISBURSEMENT TABLE \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    pw.Widget tCell(
      String text, {
      bool bold = false,
      PdfColor? bg,
      PdfColor textColor = VColors.black,
    }) =>
        pw.Container(
          color: bg,
          padding: pw.EdgeInsets.symmetric(
              horizontal: isA5 ? 7 : 9, vertical: isA5 ? 5 : 7),
          alignment: pw.Alignment.centerRight,
          child: txt(text,
              size: isA5 ? 8 : 9, bold: bold, color: textColor),
        );

    pw.Widget tagCell(String text, {required bool isCash}) => pw.Container(
          padding: pw.EdgeInsets.symmetric(
              horizontal: isA5 ? 7 : 9, vertical: isA5 ? 3 : 5),
          alignment: pw.Alignment.centerRight,
          child: pw.Container(
            padding:
                const pw.EdgeInsets.symmetric(horizontal: 7, vertical: 2),
            decoration: pw.BoxDecoration(
              color:  isCash ? VColors.greenTagBg  : VColors.goldTagBg,
              border: pw.Border.all(
                color: isCash ? VColors.greenTagBdr : VColors.goldTagBdr,
                width: 0.5,
              ),
              borderRadius: pw.BorderRadius.circular(8),
            ),
            child: txt(
              text,
              size: isA5 ? 7 : 8,
              bold: true,
              color: isCash
                  ? VColors.greenText
                  : VColors.amberDark,
            ),
          ),
        );

    pw.Widget buildTable() {
      if (goldRows.isEmpty && !hasCash) return pw.SizedBox.shrink();

      final karatGroups = <String, List<Map<String, dynamic>>>{};
      for (final row in goldRows) {
        final k = row['karat']?.toString() ?? '\u2014';
        karatGroups.putIfAbsent(k, () => []).add(row);
      }

      final tableRows = <pw.TableRow>[];

      tableRows.add(pw.TableRow(
        decoration: pw.BoxDecoration(
          color: VColors.grayBg,
          border: const pw.Border(
              bottom: pw.BorderSide(color: VColors.grayBorder, width: 1)),
        ),
        children: [
          tCell(widget.isArabic ? '\u0627\u0644\u0628\u064a\u0627\u0646' : 'Description',
              bold: true, bg: VColors.grayBg),
          tCell(widget.isArabic ? '\u0627\u0644\u0639\u064a\u0627\u0631 / \u0627\u0644\u0639\u0645\u0644\u0629' : 'Karat / Currency',
              bold: true, bg: VColors.grayBg),
          tCell(widget.isArabic ? '\u0627\u0644\u0635\u0627\u0641\u064a' : 'Net',
              bold: true, bg: VColors.grayBg),
          tCell(widget.isArabic ? '\u062a\u0642\u062f\u064a\u0631\u064a' : 'Est.',
              bold: true, bg: VColors.grayBg),
        ],
      ));

      for (final entry in karatGroups.entries) {
        final karatKey = entry.key;
        tableRows.add(pw.TableRow(
          decoration: pw.BoxDecoration(
            color: VColors.grpHdrBg,
            border: const pw.Border(
                bottom:
                    pw.BorderSide(color: VColors.grpHdrBdr, width: 0.5)),
          ),
          children: [
            pw.Padding(
              padding: pw.EdgeInsets.symmetric(
                  horizontal: isA5 ? 8 : 10, vertical: isA5 ? 4 : 6),
              child: pw.Row(
                mainAxisAlignment: pw.MainAxisAlignment.end,
                children: [
                  txt(
                    '${widget.isArabic ? '\u0639\u064a\u0627\u0631' : 'Karat'} $karatKey'
                    ' \u2014 ${widget.isArabic ? '\u0630\u0647\u0628' : 'Gold'}',
                    size: isA5 ? 8 : 9,
                    color: VColors.amberDark,
                  ),
                  pw.SizedBox(width: 6),
                  pw.Container(
                    padding: const pw.EdgeInsets.symmetric(
                        horizontal: 8, vertical: 2),
                    decoration: pw.BoxDecoration(
                      color: VColors.amberMid,
                      borderRadius: pw.BorderRadius.circular(10),
                    ),
                    child: txt(
                      '${widget.isArabic ? '\u0639\u064a\u0627\u0631' : 'K'} $karatKey',
                      size: isA5 ? 7 : 8,
                      bold: true,
                      color: VColors.amberLight,
                    ),
                  ),
                ],
              ),
            ),
            pw.SizedBox.shrink(),
            pw.SizedBox.shrink(),
            pw.SizedBox.shrink(),
          ],
        ));
        for (final row in entry.value) {
          final netW = _toDouble(row['netWeight']);
          tableRows.add(pw.TableRow(
            decoration: const pw.BoxDecoration(
              border: pw.Border(
                  bottom:
                      pw.BorderSide(color: VColors.grayBorder, width: 0.3)),
            ),
            children: [
              tCell(row['description']?.toString() ?? '\u2014'),
              tagCell('${widget.isArabic ? '\u0639\u064a\u0627\u0631' : 'K'} $karatKey',
                  isCash: false),
              tCell('${goldFmt.format(netW)} ${widget.isArabic ? '\u062c\u0645' : 'g'}'),
              tCell('\u2014', textColor: VColors.grayMuted),
            ],
          ));
        }
      }

      if (hasCash && goldRows.isNotEmpty) {
        tableRows.add(pw.TableRow(
          decoration: pw.BoxDecoration(
            color: VColors.greenTagBg,
            border: const pw.Border(
                bottom:
                    pw.BorderSide(color: VColors.greenTagBdr, width: 0.3)),
          ),
          children: [
            tCell(widget.isArabic ? '\u0646\u0642\u062f \u0645\u0631\u0627\u0641\u0642' : 'Cash',
                textColor: VColors.greenText),
            tagCell(widget.isArabic ? '\u0646\u0642\u062f \u2014 \u0631\u064a\u0627\u0644' : 'Cash \u2014 SAR',
                isCash: true),
            tCell(
              '${currencyFmt.format(cashAmt)} ${widget.isArabic ? '\u0631\u064a\u0627\u0644' : 'SAR'}',
              textColor: VColors.greenText,
            ),
            tCell('\u2014', textColor: VColors.grayMuted),
          ],
        ));
      }

      return section(
        pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.stretch,
          children: [
            sectionTitle(
                widget.isArabic ? '\u062c\u062f\u0648\u0644 \u0627\u0644\u0635\u0631\u0641' : 'Disbursement Table'),
            pw.Container(
              decoration: pw.BoxDecoration(
                border: pw.Border.all(color: VColors.grayBorder, width: 0.5),
                borderRadius: pw.BorderRadius.circular(6),
              ),
              child: pw.Table(
                columnWidths: const {
                  0: pw.FlexColumnWidth(3.0),
                  1: pw.FlexColumnWidth(2.8),
                  2: pw.FlexColumnWidth(2.2),
                  3: pw.FlexColumnWidth(2.0),
                },
                children: tableRows,
              ),
            ),
          ],
        ),
      );
    }

    // \u2500\u2500 10. ACCOUNT LINES (archive toggle) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    pw.Widget buildAccountLines() {
      if (visibleAL.isEmpty) return pw.SizedBox.shrink();

      Map<int, T> reverseMap<T>(Map<int, T> map, int count) {
        final r = <int, T>{};
        for (final e in map.entries) { r[(count - 1) - e.key] = e.value; }
        return r;
      }

      final baseHeaders = compactAL
          ? [
              widget.isArabic ? '\u0627\u0644\u062d\u0633\u0627\u0628' : 'Account',
              widget.isArabic ? '\u0627\u0644\u0646\u0648\u0639' : 'Type',
              widget.isArabic ? '\u0627\u0644\u0642\u064a\u0645\u0629' : 'Amount',
              widget.isArabic ? '\u0639\u064a\u0627\u0631' : 'Karat',
            ]
          : [
              widget.isArabic ? '\u0627\u0644\u062d\u0633\u0627\u0628' : 'Account',
              widget.isArabic ? '\u0645\u062f\u064a\u0646 \u0646\u0642\u062f' : 'Cash Dr',
              widget.isArabic ? '\u062f\u0627\u0626\u0646 \u0646\u0642\u062f' : 'Cash Cr',
              widget.isArabic ? '\u0645\u062f\u064a\u0646 \u0630\u0647\u0628' : 'Gold Dr',
              widget.isArabic ? '\u062f\u0627\u0626\u0646 \u0630\u0647\u0628' : 'Gold Cr',
              widget.isArabic ? '\u0639\u064a\u0627\u0631' : 'Karat',
            ];

      List<String> rowFor(Map<String, dynamic> line) {
        final account =
            (line['account'] is Map) ? (line['account'] as Map) : const {};
        final accountName   = account['name']?.toString() ?? '';
        final accountNumber = account['account_number']?.toString() ?? '';
        final display = accountNumber.isNotEmpty
            ? '$accountNumber - $accountName'
            : accountName;
        final lineType = line['line_type']?.toString().toLowerCase();
        final amtType  = line['amount_type']?.toString().toLowerCase();
        final amt      = (line['amount'] is num)
            ? (line['amount'] as num).toDouble()
            : double.tryParse(line['amount']?.toString() ?? '0') ?? 0;
        final k = line['karat']?.toString();

        if (compactAL) {
          String cType = '', cAmt = '';
          if (amtType == 'cash') {
            cType = lineType == 'debit'
                ? (widget.isArabic ? '\u0646\u0642\u062f \u0645\u062f\u064a\u0646' : 'Cash Dr')
                : (widget.isArabic ? '\u0646\u0642\u062f \u062f\u0627\u0626\u0646' : 'Cash Cr');
            cAmt = currencyFmt.format(amt);
          } else if (amtType == 'gold') {
            cType = lineType == 'debit'
                ? (widget.isArabic ? '\u0630\u0647\u0628 \u0645\u062f\u064a\u0646' : 'Gold Dr')
                : (widget.isArabic ? '\u0630\u0647\u0628 \u062f\u0627\u0626\u0646' : 'Gold Cr');
            cAmt = goldFmt.format(amt);
          }
          return [display, cType, cAmt, amtType == 'gold' ? (k ?? '') : '\u2014'];
        }

        String cashDr = '', cashCr = '', goldDr = '', goldCr = '';
        if (amtType == 'cash') {
          if (lineType == 'debit') { cashDr = currencyFmt.format(amt); }
          else { cashCr = currencyFmt.format(amt); }
        } else if (amtType == 'gold') {
          if (lineType == 'debit') { goldDr = goldFmt.format(amt); }
          else { goldCr = goldFmt.format(amt); }
        }
        return [
          display, cashDr, cashCr, goldDr, goldCr,
          amtType == 'gold' ? (k ?? '') : '',
        ];
      }

      final rows    = visibleAL.map(rowFor).toList();
      final headers = widget.isArabic ? baseHeaders.reversed.toList() : baseHeaders;
      final data    = widget.isArabic
          ? rows.map((r) => r.reversed.toList()).toList()
          : rows;

      final baseCW = compactAL
          ? <int, pw.TableColumnWidth>{
              0: const pw.FlexColumnWidth(3.2),
              1: pw.FixedColumnWidth(isA5 ? 46 : 60),
              2: pw.FixedColumnWidth(isA5 ? 42 : 58),
              3: pw.FixedColumnWidth(isA5 ? 24 : 36),
            }
          : <int, pw.TableColumnWidth>{
              0: const pw.FlexColumnWidth(3),
              1: pw.FixedColumnWidth(isA5 ? 36 : 55),
              2: pw.FixedColumnWidth(isA5 ? 36 : 55),
              3: pw.FixedColumnWidth(isA5 ? 36 : 55),
              4: pw.FixedColumnWidth(isA5 ? 36 : 55),
              5: pw.FixedColumnWidth(isA5 ? 26 : 40),
            };

      final baseCa = compactAL
          ? <int, pw.Alignment>{
              0: pw.Alignment.centerRight,
              1: pw.Alignment.center,
              2: pw.Alignment.center,
              3: pw.Alignment.center,
            }
          : <int, pw.Alignment>{
              0: pw.Alignment.centerRight,
              1: pw.Alignment.center,
              2: pw.Alignment.center,
              3: pw.Alignment.center,
              4: pw.Alignment.center,
              5: pw.Alignment.center,
            };

      final cw = widget.isArabic ? reverseMap(baseCW, baseHeaders.length) : baseCW;
      final ca = widget.isArabic ? reverseMap(baseCa, baseHeaders.length) : baseCa;

      return section(
        pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.stretch,
          children: [
            sectionTitle(widget.isArabic ? '\u0633\u0637\u0648\u0631 \u0627\u0644\u062d\u0633\u0627\u0628\u0627\u062a' : 'Account Lines'),
            pw.Container(
              padding: pw.EdgeInsets.all(isA5 ? 8 : 10),
              decoration: pw.BoxDecoration(
                border: pw.Border.all(color: VColors.grayBorder, width: 0.5),
                borderRadius: pw.BorderRadius.circular(6),
              ),
              child: pw.TableHelper.fromTextArray(
                headers: headers,
                data: data,
                headerDecoration: pw.BoxDecoration(color: VColors.grayBg),
                headerStyle: pw.TextStyle(
                    fontWeight: pw.FontWeight.bold,
                    fontSize: isA5 ? 7.8 : 10.5),
                cellStyle: pw.TextStyle(fontSize: isA5 ? 7.4 : 10.2),
                cellPadding: pw.EdgeInsets.symmetric(
                    horizontal: isA5 ? 2 : 4, vertical: isA5 ? 2 : 3),
                border: pw.TableBorder.all(color: VColors.grayBorder),
                columnWidths: cw,
                cellAlignments: ca,
              ),
            ),
            if (hiddenAL > 0) ...[
              pw.SizedBox(height: 4),
              txt(
                widget.isArabic
                    ? '... \u062a\u0645 \u0625\u062e\u0641\u0627\u0621 $hiddenAL \u0633\u0637\u0631 \u0644\u0636\u0645\u0627\u0646 \u0627\u0644\u0637\u0628\u0627\u0639\u0629 \u0641\u064a \u0635\u0641\u062d\u0629 \u0648\u0627\u062d\u062f\u0629'
                    : '... $hiddenAL lines hidden to fit single page',
                size: isA5 ? 7.5 : 9,
                color: VColors.grayMuted,
              ),
            ],
          ],
        ),
      );
    }

    // \u2500\u2500 11. SIGNATURES \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    pw.Widget sigCell(String sigTitle, String name) => pw.Expanded(
          child: pw.Column(
            children: [
              txt(sigTitle,
                  size: isA5 ? 8 : 9,
                  color: const PdfColor.fromInt(0xFF777777)),
              pw.SizedBox(height: isA5 ? 18 : 22),
              pw.Container(
                decoration: const pw.BoxDecoration(
                  border: pw.Border(
                      top: pw.BorderSide(color: VColors.grayMuted, width: 0.8)),
                ),
                padding: const pw.EdgeInsets.only(top: 4),
                child: pw.Center(
                  child: txt(name,
                      size: isA5 ? 7 : 8, color: VColors.grayMuted),
                ),
              ),
            ],
          ),
        );

    pw.Widget buildSignatures() {
      final sigs = [
        (
          title: widget.isArabic ? '\u062a\u0648\u0642\u064a\u0639 \u0627\u0644\u0645\u0633\u0644\u0651\u0645' : 'Delivered By',
          name:  createdBy.isNotEmpty ? createdBy : company,
        ),
        (
          title: widget.isArabic ? '\u062a\u0648\u0642\u064a\u0639 \u0627\u0644\u0645\u0633\u062a\u0644\u0650\u0645' : 'Receiver',
          name:  (voucher['receiver_name']?.toString().trim().isNotEmpty == true)
                 ? voucher['receiver_name'].toString().trim()
                 : (party.isEmpty ? '\u2014' : party),
        ),
        (
          title: widget.isArabic ? '\u0627\u0639\u062a\u0645\u0627\u062f \u0627\u0644\u0633\u0646\u062f' : 'Approved By',
          name:  approvedBy.isEmpty ? '\u2014' : approvedBy,
        ),
      ];

      final rowChildren = <pw.Widget>[];
      for (var i = 0; i < sigs.length; i++) {
        if (i > 0) rowChildren.add(pw.SizedBox(width: isA5 ? 6 : 10));
        rowChildren.add(sigCell(sigs[i].title, sigs[i].name));
      }

      return section(
        pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.stretch,
          children: [
            sectionTitle(widget.isArabic ? '\u0627\u0644\u062a\u0648\u0642\u064a\u0639\u0627\u062a' : 'Signatures'),
            pw.Row(children: rowChildren),
            pw.SizedBox(height: isA5 ? 8 : 10),
            pw.Container(
              height: isA5 ? 40 : 48,
              decoration: pw.BoxDecoration(
                border: pw.Border.all(
                  color: VColors.grayMuted,
                  width: 0.8,
                  style: pw.BorderStyle.dashed,
                ),
                borderRadius: pw.BorderRadius.circular(6),
              ),
              alignment: pw.Alignment.center,
              child: txt(
                widget.isArabic ? '\u062e\u062a\u0645 \u0627\u0644\u0645\u0624\u0633\u0633\u0629' : 'Company Stamp',
                size: isA5 ? 8 : 9,
                color: VColors.grayMuted,
              ),
            ),
          ],
        ),
        last: true,
      );
    }

    // \u2500\u2500 12. FOOTER \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    pw.Widget buildFooter() => pw.Container(
          padding: pw.EdgeInsets.symmetric(
              horizontal: isA5 ? 12 : 16, vertical: isA5 ? 5 : 7),
          decoration: const pw.BoxDecoration(
            color: VColors.grayBg,
            border: pw.Border(
                top: pw.BorderSide(color: VColors.grayBorder, width: 0.5)),
          ),
          child: pw.Row(
            mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
            children: [
              txt(voucherNum, size: isA5 ? 7 : 8, color: VColors.grayMuted),
              txt(
                '$company \u2014 ${widget.isArabic ? '\u062c\u0645\u064a\u0639 \u0627\u0644\u062d\u0642\u0648\u0642 \u0645\u062d\u0641\u0648\u0638\u0629' : 'All rights reserved'}',
                size: isA5 ? 7 : 8,
                color: VColors.grayMuted,
              ),
              txt(
                '${widget.isArabic ? '\u0637\u064f\u0628\u0639 \u0628\u062a\u0627\u0631\u064a\u062e' : 'Printed'}: $printDate',
                size: isA5 ? 7 : 8,
                color: VColors.grayMuted,
              ),
            ],
          ),
        );

    // \u2500\u2500 PAGE LAYOUT \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    final double hMargin =
        isA5 ? 10 * PdfPageFormat.mm : 14 * PdfPageFormat.mm;
    final double vMargin =
        isA5 ?  8 * PdfPageFormat.mm : 12 * PdfPageFormat.mm;

    final doc = pw.Document(title: title, author: company);
    doc.addPage(pw.Page(
      pageFormat: format,
      margin: pw.EdgeInsets.symmetric(horizontal: hMargin, vertical: vMargin),
      textDirection:
          widget.isArabic ? pw.TextDirection.rtl : pw.TextDirection.ltr,
      theme: pw.ThemeData.withFont(base: fontReg, bold: fontBold),
      build: (ctx) => pw.Column(
        crossAxisAlignment: pw.CrossAxisAlignment.stretch,
        children: [
            buildHeader(),
            buildStatusStrip(),
            buildDetails(),
            buildAmounts(),
            if (goldRows.isNotEmpty) buildTable(),
            if (_includeAccountLines && visibleAL.isNotEmpty)
              buildAccountLines(),
            buildSignatures(),
            buildFooter(),
          ],
        ),
    ));

    return doc.save();
  }


}

class _VoucherQrPlaceholderPainter extends CustomPainter {
  const _VoucherQrPlaceholderPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final fill = Paint()..color = const Color(0xFF412402);
    final stroke = Paint()
      ..color = const Color(0xFF412402)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;

    final s = size.width / 100;

    canvas.drawRect(Rect.fromLTWH(10 * s, 10 * s, 30 * s, 30 * s), stroke);
    canvas.drawRect(Rect.fromLTWH(17 * s, 17 * s, 16 * s, 16 * s), fill);

    canvas.drawRect(Rect.fromLTWH(60 * s, 10 * s, 30 * s, 30 * s), stroke);
    canvas.drawRect(Rect.fromLTWH(67 * s, 17 * s, 16 * s, 16 * s), fill);

    canvas.drawRect(Rect.fromLTWH(10 * s, 60 * s, 30 * s, 30 * s), stroke);
    canvas.drawRect(Rect.fromLTWH(17 * s, 67 * s, 16 * s, 16 * s), fill);

    for (final point in const [
      [60, 60],
      [72, 60],
      [84, 60],
      [60, 72],
      [76, 72],
      [60, 84],
      [84, 84],
      [44, 10],
      [44, 44],
      [10, 44],
      [34, 44],
    ]) {
      canvas.drawRect(
        Rect.fromLTWH(point[0] * s, point[1] * s, 8 * s, 8 * s),
        fill,
      );
    }

    canvas.drawRect(Rect.fromLTWH(44 * s, 22 * s, 8 * s, 16 * s), fill);
    canvas.drawRect(Rect.fromLTWH(76 * s, 72 * s, 16 * s, 8 * s), fill);
    canvas.drawRect(Rect.fromLTWH(60 * s, 84 * s, 20 * s, 8 * s), fill);
    canvas.drawRect(Rect.fromLTWH(10 * s, 44 * s, 20 * s, 8 * s), fill);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
