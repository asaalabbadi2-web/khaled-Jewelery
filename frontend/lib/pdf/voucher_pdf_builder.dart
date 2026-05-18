import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/services.dart' show rootBundle;
import 'package:intl/intl.dart';
import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../pdf/pdf_text_utils.dart';
import '../providers/settings_provider.dart';

// ── PDF colour palette (matches existing voucher/statement design) ───────────
class VoucherPdfColors {
  static const amberDark = PdfColor.fromInt(0xFF8B6914);
  static const amberMid = PdfColor.fromInt(0xFFA07820);
  static const amberLight = PdfColor.fromInt(0xFFFBF7EE);
  static const amberBorder = PdfColor.fromInt(0xFFE8D899);
  static const greenTagBg = PdfColor.fromInt(0xFFEAF5EF);
  static const grayBg = PdfColor.fromInt(0xFFF7F6F2);
  static const grayBorder = PdfColor.fromInt(0xFFEBEBEB);
  static const grayMuted = PdfColor.fromInt(0xFFAAAAAA);
  static const black = PdfColor.fromInt(0xFF1A1A1A);
}

class VoucherPdfOptions {
  final bool isArabic;
  final bool includeAccountLines;

  const VoucherPdfOptions({
    this.isArabic = true,
    this.includeAccountLines = false,
  });
}

class VoucherPdfBuilder {
  static PdfPageFormat pageFormatFromSettings({
    required String paperSize,
    required String orientation,
  }) {
    PdfPageFormat base;
    switch (paperSize) {
      case 'A5':
        base = PdfPageFormat.a5;
        break;
      case 'Letter':
        base = PdfPageFormat.letter;
        break;
      case 'Thermal':
        return const PdfPageFormat(80 * PdfPageFormat.mm, double.infinity);
      default:
        base = PdfPageFormat.a4;
    }

    if (orientation == 'landscape') return base.landscape;
    return base;
  }

  static Future<Uint8List> buildBytes({
    required Map<String, dynamic> voucher,
    required PdfPageFormat format,
    required VoucherPdfOptions options,
    SettingsProvider? settings,
  }) async {
    // Fonts
    pw.Font fontReg;
    pw.Font fontBold;
    try {
      final reg = (await rootBundle.load('assets/fonts/Cairo-Regular.ttf'))
          .buffer
          .asUint8List();
      final bold = (await rootBundle.load('assets/fonts/Cairo-Bold.ttf'))
          .buffer
          .asUint8List();
      fontReg = pw.Font.ttf(reg.buffer.asByteData());
      fontBold = pw.Font.ttf(bold.buffer.asByteData());
    } catch (_) {
      // Fallback font if bundled Cairo assets are missing.
      fontReg = pw.Font.helvetica();
      fontBold = pw.Font.helveticaBold();
    }

    final bool isA5 =
      (format.width <= PdfPageFormat.a5.width + 1 &&
        format.height <= PdfPageFormat.a5.height + 1) ||
      (format.height <= PdfPageFormat.a5.width + 1 &&
        format.width <= PdfPageFormat.a5.height + 1);

    final currencyFmt = NumberFormat('#,##0.00', 'ar');
    final goldFmt = NumberFormat('#,##0.000', 'ar');

    String fmtDate(dynamic raw) {
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

    String fmtHumanDate(dynamic raw) {
      if (raw == null) return '';
      final s = raw.toString();
      if (s.isEmpty) return '';
      try {
        final dt = DateTime.tryParse(s);
        if (dt == null) return s;
        // Force Western digits in header dates to avoid mixed Arabic-Indic/Latin
        // digit rendering issues in PDFs.
        return DateFormat('yyyy/MM/dd HH:mm', 'en').format(dt);
      } catch (_) {
        return s;
      }
    }

    String partyDisplay(Map<String, dynamic> voucher) {
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

      // Fallback for 'other' party type: resolve account name from the party-side line.
      final partyType = (voucher['party_type'] ?? '').toString().trim();
      if (partyType == 'other') {
        final vType = (voucher['voucher_type'] ?? '').toString();
        final partyLT = vType == 'receipt' ? 'credit' : 'debit';
        final lines = (voucher['account_lines'] as List?) ?? [];
        for (final line in lines) {
          if (line is Map && (line['line_type'] ?? '') == partyLT) {
            final acc = line['account'];
            final name = (acc is Map ? acc['name'] : null)?.toString().trim();
            if (name != null && name.isNotEmpty) return name;
          }
        }
      }

      final description = voucher['description']?.toString().trim();
      if (description != null && description.isNotEmpty) return description;
      return '';
    }

    String voucherQrPayload(Map<String, dynamic> voucher) {
      final voucherNumber = (voucher['voucher_number'] ?? '').toString();
      final voucherId = (voucher['id'] ?? '').toString();
      final party = partyDisplay(voucher);
      final date = fmtDate(voucher['date']);
      return [
        'voucher_number=$voucherNumber',
        'voucher_id=$voucherId',
        if (party.isNotEmpty) 'party=$party',
        if (date.isNotEmpty) 'date=$date',
        'type=${voucher['voucher_type'] ?? ''}',
      ].join(';');
    }

    double toDouble(dynamic value) {
      if (value is num) return value.toDouble();
      return double.tryParse(value?.toString() ?? '') ?? 0.0;
    }

    ({
      bool isReceipt,
      bool isPayment,
      bool isAdjustment,
      String titleAr,
      String titleEn,
    }) voucherMeta(Map<String, dynamic> voucher) {
      final typeKey = (voucher['voucher_type']?.toString() ?? '')
          .trim()
          .toLowerCase();
      if (typeKey == 'receipt') {
        return (
          isReceipt: true,
          isPayment: false,
          isAdjustment: false,
          titleAr: 'سند قبض',
          titleEn: 'Receipt Voucher',
        );
      }
      if (typeKey == 'payment') {
        return (
          isReceipt: false,
          isPayment: true,
          isAdjustment: false,
          titleAr: 'سند صرف',
          titleEn: 'Payment Voucher',
        );
      }
      return (
        isReceipt: false,
        isPayment: false,
        isAdjustment: true,
        titleAr: 'سند تسوية',
        titleEn: 'Adjustment Voucher',
      );
    }

    ({
      int background,
      int foreground,
      int dot,
      String label,
    }) statusPresentation(Map<String, dynamic> voucher) {
      final raw = voucher['status']?.toString().trim() ?? '';
      final normalized = raw.toLowerCase();
      final isApproved =
          normalized == 'approved' || raw == 'معتمد' || raw == 'approved';
      final isDraft = normalized == 'draft' || raw == 'مسودة';
      final isRejected = normalized == 'rejected' || raw == 'مرفوض';

      if (isApproved) {
        return (
          background: 0xFFEAF3DE,
          foreground: 0xFF27500A,
          dot: 0xFF3B6D11,
          label: options.isArabic ? 'معتمد ومُصادق عليه' : 'Approved & Verified',
        );
      }
      if (isDraft) {
        return (
          background: 0xFFFFF3D9,
          foreground: 0xFF8A5A00,
          dot: 0xFFBA7517,
          label: options.isArabic ? 'مسودة' : 'Draft',
        );
      }
      if (isRejected) {
        return (
          background: 0xFFFFE2DE,
          foreground: 0xFF842F1F,
          dot: 0xFFC0392B,
          label: options.isArabic ? 'مرفوض' : 'Rejected',
        );
      }

      return (
        background: 0xFFF5F5F5,
        foreground: 0xFF666666,
        dot: 0xFF999999,
        label: raw,
      );
    }

    Future<Uint8List?> resizeImageBytes(Uint8List bytes, int targetSize) async {
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
      return null;
    }

    final meta = voucherMeta(voucher);
    final webStatus = statusPresentation(voucher);

    final party = partyDisplay(voucher);
    final voucherNum =
        (voucher['voucher_number']?.toString().trim().isNotEmpty ?? false)
            ? voucher['voucher_number'].toString().trim()
            : '#${voucher['id'] ?? ''}';
    final createdBy = voucher['created_by']?.toString().trim() ?? '';
    final approvedBy = voucher['approved_by']?.toString().trim() ?? '';
    final description =
        (voucher['description']?.toString().trim().isNotEmpty ?? false)
            ? voucher['description'].toString().trim()
            : '—';
    final statusText = webStatus.label;
    final dateText = fmtHumanDate(voucher['date']);
    final printDate = fmtHumanDate(DateTime.now().toIso8601String());
    final title = options.isArabic ? meta.titleAr : meta.titleEn;

    final cashAmt = toDouble(voucher['amount_cash']);
    final goldAmt = toDouble(voucher['amount_gold']);
    final equivWeight = toDouble(voucher['amount_gold_main_karat']);
    final mainKarat = toDouble(voucher['main_karat']);

    final hasCash = cashAmt.abs() > 0.000001;
    final hasGold = goldAmt.abs() > 0.000001;

    final companyName = (settings?.companyName.trim() ?? '').isNotEmpty
        ? settings!.companyName.trim()
        : (options.isArabic ? 'خالد للمجوهرات' : 'Khaled Jewelry');
    final companyCr = (settings?.companyCrNumber.trim() ?? '');
    final companyVat = (settings?.companyTaxNumber.trim() ?? '');
    final companyPhone = (settings?.companyPhone.trim() ?? '');
    final companyAddr = (settings?.companyAddress.trim() ?? '');
    final showLogo = settings?.showCompanyLogo ?? true;
    final logoBase64 =
        (settings?.settings['company_logo_base64'] ?? '').toString().trim();

    pw.MemoryImage? logoImage;
    if (showLogo && logoBase64.isNotEmpty) {
      try {
        var payload = logoBase64;
        final commaIdx = payload.indexOf(',');
        if (payload.startsWith('data:') && commaIdx >= 0) {
          payload = payload.substring(commaIdx + 1);
        }
        final rawLogoBytes = base64Decode(payload);
        if (rawLogoBytes.isNotEmpty) {
          final resized = await resizeImageBytes(rawLogoBytes, 128);
          logoImage = pw.MemoryImage(resized ?? rawLogoBytes);
        }
      } catch (_) {}
    }
    if (logoImage == null && showLogo) {
      try {
        final raw = (await rootBundle.load('assets/KHGL.png'))
            .buffer
            .asUint8List();
        final resized = await resizeImageBytes(raw, 128);
        logoImage = pw.MemoryImage(resized ?? raw);
      } catch (_) {}
    }

    // Gold rows from account_lines / gold_breakdown
    List<Map<String, dynamic>> goldRows() {
      final accountLinesRaw = voucher['account_lines'];
      final accountLines = accountLinesRaw is List
          ? accountLinesRaw
              .whereType<Map>()
              .cast<Map<String, dynamic>>()
              .toList()
          : <Map<String, dynamic>>[];

      final voucherType =
          (voucher['voucher_type'] ?? '').toString().toLowerCase();
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

        final lineDesc =
            (line['description']?.toString().trim().isNotEmpty ?? false)
                ? line['description'].toString().trim()
                : (account['name']?.toString().trim().isNotEmpty ?? false)
                    ? account['name'].toString().trim()
                    : (voucher['description']?.toString().trim() ?? 'سطر ذهب');

        final weight = toDouble(line['amount']);
        final netWeight = toDouble(line['net_weight']);
        final stonesWeight = toDouble(line['stones_weight']);
        final grossWeight = toDouble(line['gross_weight']);

        final karatText = line['karat'] == null
            ? ((voucher['gold_karat'] ?? '—').toString())
            : line['karat'].toString().replaceAll('.0', '');

        rows.add({
          'description': lineDesc,
          'karat': karatText,
          'grossWeight': grossWeight > 0 ? grossWeight : weight,
          'netWeight': netWeight > 0 ? netWeight : weight,
          'stonesWeight': stonesWeight,
        });
      }

      if (rows.isNotEmpty) return rows;

      final rawBreakdown = voucher['gold_breakdown'];
      if (rawBreakdown is List) {
        for (final item in rawBreakdown.whereType<Map>()) {
          final karat = item['karat']?.toString().replaceAll('.0', '') ?? '—';
          final weight = toDouble(item['weight']);
          rows.add({
            'description': (voucher['description']?.toString().trim().isNotEmpty ??
                    false)
                ? voucher['description'].toString().trim()
                : 'ذهب',
            'karat': karat,
            'grossWeight': weight,
            'netWeight': weight,
            'stonesWeight': 0.0,
          });
        }
      }

      return rows;
    }

    final goldRowsList = goldRows();

    // Account lines (optional)
    final accountLinesRaw = voucher['account_lines'];
    final accountLines = accountLinesRaw is List
        ? accountLinesRaw.whereType<Map<String, dynamic>>().toList()
        : <Map<String, dynamic>>[];
    final bool compactAL = isA5 || accountLines.length > 8;
    final int maxAL = compactAL ? (isA5 ? 9 : 12) : 14;
    final visibleAL = accountLines.take(maxAL).toList();
    final int hiddenAL = accountLines.length > maxAL ? accountLines.length - maxAL : 0;

    pw.TextStyle ts({
      double size = 10,
      bool bold = false,
      PdfColor color = VoucherPdfColors.black,
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
      PdfColor color = VoucherPdfColors.black,
      pw.TextAlign? align,
    }) =>
        pw.Text(
          pdfVisualArabic(t),
          style: ts(size: size, bold: bold, color: color),
          textDirection: pw.TextDirection.ltr,
          textAlign: align,
        );

    pw.Widget sectionTitle(String t) => pw.Padding(
          padding: const pw.EdgeInsets.only(bottom: 8),
          child: pw.Align(
            alignment: pw.Alignment.centerRight,
            child: txt(
              t,
              size: isA5 ? 7.5 : 8.5,
              bold: true,
              color: VoucherPdfColors.amberMid,
            ),
          ),
        );

    pw.Widget section(pw.Widget child, {bool last = false}) => pw.Container(
          decoration: pw.BoxDecoration(
            border: last
                ? null
                : const pw.Border(
                    bottom: pw.BorderSide(
                      color: VoucherPdfColors.grayBorder,
                      width: 0.5,
                    ),
                  ),
          ),
          padding: pw.EdgeInsets.symmetric(
            horizontal: isA5 ? 12 : 16,
            vertical: isA5 ? 8 : 10,
          ),
          child: child,
        );

    pw.Widget buildHeader() {
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
            color: VoucherPdfColors.amberBorder,
          );

      pw.Widget infoLine(String label, String value) => pw.Padding(
            padding: const pw.EdgeInsets.only(bottom: 3),
            child: pw.Row(
              mainAxisSize: pw.MainAxisSize.min,
              children: [
                pw.Text(
                  pdfVisualArabic('$label:'),
                  textDirection: pw.TextDirection.ltr,
                  style: pw.TextStyle(
                    font: fontReg,
                    fontSize: 8,
                    color: PdfColor.fromInt(0xFF444444),
                  ),
                ),
                pw.SizedBox(width: 6),
                pw.Text(
                  pdfVisualArabic(value),
                  textDirection: pw.TextDirection.ltr,
                  style: pw.TextStyle(
                    font: fontReg,
                    fontSize: 8,
                    color: PdfColor.fromInt(0xFF666666),
                  ),
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
          pw.SizedBox(
            height: isA5 ? 108 : 128,
            child: pw.Stack(
              children: [
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
                          child: pw.Text(
                            pdfVisualArabic('رقم السند'),
                            textDirection: pw.TextDirection.ltr,
                            style: pw.TextStyle(
                              font: fontReg,
                              fontSize: 7,
                              color: PdfColor.fromInt(0xFF666666),
                            ),
                          ),
                        ),
                        pw.SizedBox(height: 1),
                        pw.Align(
                          alignment: pw.Alignment.centerLeft,
                          child: pw.Text(
                            voucherNum,
                            style: pw.TextStyle(
                              font: fontBold,
                              fontSize: 8.5,
                              color: PdfColor.fromInt(0xFF222222),
                            ),
                          ),
                        ),
                        pw.SizedBox(height: 6),
                        pw.Align(
                          alignment: pw.Alignment.centerLeft,
                          child: pw.Text(
                            pdfVisualArabic('التاريخ'),
                            textDirection: pw.TextDirection.ltr,
                            style: pw.TextStyle(
                              font: fontReg,
                              fontSize: 7,
                              color: PdfColor.fromInt(0xFF666666),
                            ),
                          ),
                        ),
                        pw.SizedBox(height: 1),
                        pw.Align(
                          alignment: pw.Alignment.centerLeft,
                          child: pw.Text(
                            dateText.isEmpty ? '—' : dateText,
                            textDirection: pw.TextDirection.ltr,
                            style: pw.TextStyle(
                              font: fontBold,
                              fontSize: 8.5,
                              color: PdfColor.fromInt(0xFF222222),
                            ),
                          ),
                        ),
                        if (party.isNotEmpty) ...[
                          pw.SizedBox(height: 6),
                          pw.Container(
                            height: 0.6,
                            color: VoucherPdfColors.amberBorder,
                          ),
                          pw.SizedBox(height: 6),
                          pw.Align(
                            alignment: pw.Alignment.centerLeft,
                            child: pw.Text(
                              pdfVisualArabic('الطرف'),
                              textDirection: pw.TextDirection.ltr,
                              style: pw.TextStyle(
                                font: fontReg,
                                fontSize: 7,
                                color: PdfColor.fromInt(0xFF666666),
                              ),
                            ),
                          ),
                          pw.SizedBox(height: 1),
                          pw.Align(
                            alignment: pw.Alignment.centerLeft,
                            child: pw.Text(
                              pdfVisualArabic(party),
                              textDirection: pw.TextDirection.ltr,
                              style: pw.TextStyle(
                                font: fontBold,
                                fontSize: 8.5,
                                color: PdfColor.fromInt(0xFF222222),
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),

                pw.Positioned(
                  top: 8,
                  left: isA5 ? 124.0 : 152.0,
                  right: isA5 ? 124.0 : 164.0,
                  child: pw.Column(
                    crossAxisAlignment: pw.CrossAxisAlignment.center,
                    children: [
                      pw.Text(
                        pdfVisualArabic(title),
                        textDirection: pw.TextDirection.ltr,
                        style: pw.TextStyle(
                          font: fontBold,
                          fontSize: isA5 ? 18 : 22,
                          color: PdfColor.fromInt(0xFF111111),
                        ),
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
                                  color: VoucherPdfColors.amberDark,
                                  width: 0.8,
                                ),
                              ),
                              child: pw.BarcodeWidget(
                                barcode: pw.Barcode.qrCode(),
                                data: voucherQrPayload(voucher),
                                color: VoucherPdfColors.amberDark,
                              ),
                            ),
                            pw.SizedBox(height: 3),
                            pw.Text(
                              pdfVisualArabic(
                                options.isArabic ? 'تحقق من السند' : 'Verify Voucher',
                              ),
                              textDirection: pw.TextDirection.ltr,
                              style: pw.TextStyle(
                                font: fontReg,
                                fontSize: 6,
                                color: PdfColor.fromInt(0xFF666666),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),

                pw.Positioned(
                  top: 0,
                  right: 0,
                  child: pw.SizedBox(
                    width: isA5 ? 120 : 160,
                    child: pw.Column(
                      crossAxisAlignment: pw.CrossAxisAlignment.end,
                      children: [
                        pw.Align(
                          alignment: pw.Alignment.centerRight,
                          child: pw.Directionality(
                            textDirection: pw.TextDirection.rtl,
                            child: pw.Row(
                              mainAxisSize: pw.MainAxisSize.min,
                              crossAxisAlignment: pw.CrossAxisAlignment.center,
                              children: [
                                if (logoImage != null)
                                  pw.Image(
                                    logoImage,
                                    width: 38,
                                    height: 38,
                                    fit: pw.BoxFit.contain,
                                  ),
                                if (logoImage != null) pw.SizedBox(width: 6),
                                if (companyName.trim().isNotEmpty)
                                  pw.Text(
                                    pdfVisualArabic(companyName.trim()),
                                    textDirection: pw.TextDirection.ltr,
                                    style: pw.TextStyle(
                                      font: fontBold,
                                      fontSize: 14,
                                      color: PdfColor.fromInt(0xFF111111),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ),
                        pw.SizedBox(height: 5),
                        pw.Container(
                          height: 0.6,
                          color: VoucherPdfColors.amberBorder,
                        ),
                        pw.SizedBox(height: 5),
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
          pw.SizedBox(height: 6),
          pw.Container(height: 0.8, color: VoucherPdfColors.amberBorder),
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
      final PdfColor stripBg = PdfColor.fromInt(webStatus.background);
      final PdfColor dotColor = PdfColor.fromInt(webStatus.dot);
      final PdfColor textColor = PdfColor.fromInt(webStatus.foreground);
      return pw.Padding(
        padding: pw.EdgeInsets.symmetric(
          horizontal: isA5 ? 12 : 16,
          vertical: isA5 ? 4 : 6,
        ),
        child: pw.Align(
          alignment: pw.Alignment.centerRight,
          child: pw.Container(
            padding: pw.EdgeInsets.symmetric(
              horizontal: isA5 ? 10 : 12,
              vertical: isA5 ? 5 : 6,
            ),
            decoration: pw.BoxDecoration(
              color: stripBg,
              borderRadius: pw.BorderRadius.circular(isA5 ? 10 : 12),
              border: pw.Border.all(
                color: VoucherPdfColors.grayBorder,
                width: 0.5,
              ),
            ),
            child: pw.Row(
              mainAxisSize: pw.MainAxisSize.min,
              children: [
                pw.Container(
                  width: 7,
                  height: 7,
                  decoration: pw.BoxDecoration(
                    color: dotColor,
                    shape: pw.BoxShape.circle,
                  ),
                ),
                pw.SizedBox(width: 6),
                txt(
                  statusText,
                  size: isA5 ? 8 : 9,
                  bold: true,
                  color: textColor,
                ),
              ],
            ),
          ),
        ),
      );
    }

    pw.Widget buildDetails() => section(
          pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.stretch,
            children: [
              sectionTitle(options.isArabic ? 'تفاصيل السند' : 'Voucher Details'),
              pw.Padding(
                padding: pw.EdgeInsets.only(top: isA5 ? 2 : 4),
                child: pw.Column(
                  crossAxisAlignment: pw.CrossAxisAlignment.stretch,
                  children: [
                    pw.Align(
                      alignment: options.isArabic
                          ? pw.Alignment.centerRight
                          : pw.Alignment.centerLeft,
                      child: pw.Text(
                        pdfVisualArabic(
                          '${options.isArabic ? 'الطرف' : 'Party'}: '
                          '${party.isEmpty ? '—' : party}',
                        ),
                        textDirection: pw.TextDirection.ltr,
                        textAlign: options.isArabic
                            ? pw.TextAlign.right
                            : pw.TextAlign.left,
                        style: pw.TextStyle(
                          font: fontReg,
                          fontSize: isA5 ? 9 : 10,
                          color: PdfColor.fromInt(0xFF222222),
                        ),
                      ),
                    ),
                    pw.SizedBox(height: isA5 ? 4 : 6),
                    pw.Align(
                      alignment: options.isArabic
                          ? pw.Alignment.centerRight
                          : pw.Alignment.centerLeft,
                      child: pw.Text(
                        pdfVisualArabic(
                          '${options.isArabic ? 'السبب' : 'Reason'}: '
                          '${description.trim().isEmpty ? '—' : description.trim()}',
                        ),
                        textDirection: pw.TextDirection.ltr,
                        textAlign: options.isArabic
                            ? pw.TextAlign.right
                            : pw.TextAlign.left,
                        style: pw.TextStyle(
                          font: fontReg,
                          fontSize: isA5 ? 9 : 10,
                          color: PdfColor.fromInt(0xFF222222),
                        ),
                      ),
                    ),
                    pw.SizedBox(height: isA5 ? 4 : 6),
                    pw.Align(
                      alignment: options.isArabic
                          ? pw.Alignment.centerRight
                          : pw.Alignment.centerLeft,
                      child: pw.Text(
                        pdfVisualArabic(
                          '${options.isArabic ? 'أنشئ بواسطة' : 'Created by'}: '
                          '${createdBy.isEmpty ? 'system' : createdBy}',
                        ),
                        textDirection: pw.TextDirection.ltr,
                        textAlign: options.isArabic
                            ? pw.TextAlign.right
                            : pw.TextAlign.left,
                        style: pw.TextStyle(
                          font: fontReg,
                          fontSize: isA5 ? 9 : 10,
                          color: PdfColor.fromInt(0xFF222222),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );

    pw.Widget amtRow(String label, String mainVal, String subText, bool isLast) =>
        pw.Container(
          padding: pw.EdgeInsets.symmetric(
            horizontal: isA5 ? 12 : 16,
            vertical: isA5 ? 8 : 10,
          ),
          decoration: isLast
              ? null
              : const pw.BoxDecoration(
                  border: pw.Border(
                    bottom: pw.BorderSide(
                      color: VoucherPdfColors.amberBorder,
                      width: 0.5,
                    ),
                  ),
                ),
          child: pw.Row(
            children: [
              pw.Expanded(
                flex: 6,
                child: pw.Column(
                  crossAxisAlignment: pw.CrossAxisAlignment.start,
                  children: [
                    txt(
                      mainVal,
                      size: isA5 ? 14 : 16,
                      bold: true,
                      color: VoucherPdfColors.amberDark,
                    ),
                    if (subText.isNotEmpty) ...[
                      pw.SizedBox(height: 2),
                      txt(
                        subText,
                        size: isA5 ? 7 : 8,
                        color: VoucherPdfColors.amberMid,
                      ),
                    ],
                  ],
                ),
              ),
              pw.Expanded(
                flex: 4,
                child: pw.Align(
                  alignment: pw.Alignment.centerRight,
                  child: txt(
                    label,
                    size: isA5 ? 8 : 9,
                    bold: true,
                    color: VoucherPdfColors.amberMid,
                  ),
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
        final totalSub = equivWeight > 0
            ? (options.isArabic
                  ? 'المكافئ عيار $mk: ${goldFmt.format(equivWeight)} جرام'
                  : 'Karat $mk equivalent: ${goldFmt.format(equivWeight)} g')
            : '';
        rows.add(
          amtRow(
            options.isArabic ? 'وزن الذهب الإجمالي' : 'Total Gold Weight',
            '${goldFmt.format(goldAmt)} ${options.isArabic ? 'جرام' : 'g'}$karatSuffix',
            totalSub,
            !hasCash,
          ),
        );
      }

      if (hasCash) {
        rows.add(
          amtRow(
            options.isArabic ? 'المبلغ النقدي' : 'Cash Amount',
            '${currencyFmt.format(cashAmt)} ${options.isArabic ? 'ريال' : 'SAR'}',
            _amountInWords(options.isArabic, cashAmt),
            true,
          ),
        );
      }

      if (rows.isEmpty) return pw.SizedBox.shrink();

      // Cash-only vouchers: centered hero
      if (hasCash && !hasGold && goldRowsList.isEmpty) {
        final heroTitle = meta.isReceipt
            ? (options.isArabic ? 'المبلغ المستلم' : 'Received Amount')
            : meta.isPayment
                ? (options.isArabic ? 'المبلغ المدفوع' : 'Paid Amount')
                : (options.isArabic ? 'المبلغ' : 'Amount');
        final heroAmount =
            '${currencyFmt.format(cashAmt)} ${options.isArabic ? 'ريال' : 'SAR'}';
        final heroWords = _amountInWords(options.isArabic, cashAmt);

        return section(
          pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.stretch,
            children: [
              pw.SizedBox(height: isA5 ? 2 : 4),
              pw.Align(
                alignment: pw.Alignment.center,
                child: pw.Column(
                  children: [
                    pw.Text(
                      pdfVisualArabic(heroTitle),
                      textDirection: pw.TextDirection.ltr,
                      style: pw.TextStyle(
                        font: fontBold,
                        fontSize: isA5 ? 10 : 12,
                        color: VoucherPdfColors.amberMid,
                      ),
                    ),
                    pw.SizedBox(height: isA5 ? 8 : 10),
                    pw.Text(
                      pdfVisualArabic(heroAmount),
                      textDirection: pw.TextDirection.ltr,
                      style: pw.TextStyle(
                        font: fontBold,
                        fontSize: isA5 ? 26 : 32,
                        color: VoucherPdfColors.amberDark,
                      ),
                    ),
                    pw.SizedBox(height: isA5 ? 6 : 8),
                    pw.Text(
                      pdfVisualArabic('($heroWords)'),
                      textDirection: pw.TextDirection.ltr,
                      style: pw.TextStyle(
                        font: fontReg,
                        fontSize: isA5 ? 8 : 9,
                        color: VoucherPdfColors.grayMuted,
                      ),
                    ),
                  ],
                ),
              ),
              pw.SizedBox(height: isA5 ? 2 : 4),
            ],
          ),
        );
      }

      return section(
        pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.stretch,
          children: [
            sectionTitle(options.isArabic ? 'المبالغ' : 'Amounts'),
            pw.Container(
              decoration: pw.BoxDecoration(
                color: VoucherPdfColors.amberLight,
                border: pw.Border.all(
                  color: VoucherPdfColors.amberBorder,
                  width: 0.5,
                ),
                borderRadius: pw.BorderRadius.circular(8),
              ),
              child: pw.Column(children: rows),
            ),
          ],
        ),
      );
    }

    // Table: show ONLY when multiple gold karats exist; remove karat group header row;
    // do not repeat currency row inside table.
    pw.Widget buildGoldDisbursementTable() {
      if (goldRowsList.isEmpty) return pw.SizedBox.shrink();
      final uniqueKarats = <String>{};
      for (final row in goldRowsList) {
        final k = (row['karat']?.toString().trim().isNotEmpty ?? false)
            ? row['karat'].toString().trim()
            : '—';
        uniqueKarats.add(k);
      }
      if (uniqueKarats.length <= 1) return pw.SizedBox.shrink();

      pw.Widget tCell(
        String text, {
        bool bold = false,
        PdfColor? bg,
        PdfColor textColor = VoucherPdfColors.black,
      }) =>
          pw.Container(
            color: bg,
            padding: pw.EdgeInsets.symmetric(
              horizontal: isA5 ? 7 : 9,
              vertical: isA5 ? 5 : 7,
            ),
            alignment: pw.Alignment.centerRight,
            child: txt(
              text,
              size: isA5 ? 8 : 9,
              bold: bold,
              color: textColor,
            ),
          );

      final tableRows = <pw.TableRow>[];

      tableRows.add(
        pw.TableRow(
          decoration: pw.BoxDecoration(
            color: VoucherPdfColors.grayBg,
            border: const pw.Border(
              bottom: pw.BorderSide(
                color: VoucherPdfColors.grayBorder,
                width: 1,
              ),
            ),
          ),
          children: [
            tCell(
              options.isArabic ? 'البيان' : 'Description',
              bold: true,
              bg: VoucherPdfColors.grayBg,
            ),
            tCell(
              options.isArabic ? 'العيار' : 'Karat',
              bold: true,
              bg: VoucherPdfColors.grayBg,
            ),
            tCell(
              options.isArabic ? 'الصافي' : 'Net',
              bold: true,
              bg: VoucherPdfColors.grayBg,
            ),
            tCell(
              options.isArabic ? 'ملاحظة' : 'Note',
              bold: true,
              bg: VoucherPdfColors.grayBg,
            ),
          ],
        ),
      );

      for (final row in goldRowsList) {
        final karatKey = (row['karat']?.toString().trim().isNotEmpty ?? false)
            ? row['karat'].toString().trim()
            : '—';
        final netW = toDouble(row['netWeight']);
        tableRows.add(
          pw.TableRow(
            decoration: const pw.BoxDecoration(
              border: pw.Border(
                bottom: pw.BorderSide(
                  color: VoucherPdfColors.grayBorder,
                  width: 0.3,
                ),
              ),
            ),
            children: [
              tCell(row['description']?.toString() ?? '—'),
              tCell(karatKey),
              tCell('${goldFmt.format(netW)} ${options.isArabic ? 'جم' : 'g'}'),
              tCell('—', textColor: VoucherPdfColors.grayMuted),
            ],
          ),
        );
      }

      return section(
        pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.stretch,
          children: [
            sectionTitle(options.isArabic ? 'جدول الصرف' : 'Disbursement Table'),
            pw.Container(
              decoration: pw.BoxDecoration(
                border: pw.Border.all(
                  color: VoucherPdfColors.grayBorder,
                  width: 0.5,
                ),
                borderRadius: pw.BorderRadius.circular(6),
              ),
              child: pw.Table(
                columnWidths: const {
                  0: pw.FlexColumnWidth(3.2),
                  1: pw.FlexColumnWidth(1.3),
                  2: pw.FlexColumnWidth(2.0),
                  3: pw.FlexColumnWidth(2.0),
                },
                children: tableRows,
              ),
            ),
          ],
        ),
      );
    }

    pw.Widget buildAccountLines() {
      if (visibleAL.isEmpty) return pw.SizedBox.shrink();

      Map<int, T> reverseMap<T>(Map<int, T> map, int count) {
        final r = <int, T>{};
        for (final e in map.entries) {
          r[(count - 1) - e.key] = e.value;
        }
        return r;
      }

      final baseHeaders = compactAL
          ? [
              options.isArabic ? 'الحساب' : 'Account',
              options.isArabic ? 'النوع' : 'Type',
              options.isArabic ? 'القيمة' : 'Amount',
              options.isArabic ? 'عيار' : 'Karat',
            ]
          : [
              options.isArabic ? 'الحساب' : 'Account',
              options.isArabic ? 'مدين نقد' : 'Cash Dr',
              options.isArabic ? 'دائن نقد' : 'Cash Cr',
              options.isArabic ? 'مدين ذهب' : 'Gold Dr',
              options.isArabic ? 'دائن ذهب' : 'Gold Cr',
              options.isArabic ? 'عيار' : 'Karat',
            ];

      List<String> rowFor(Map<String, dynamic> line) {
        final account = (line['account'] is Map) ? (line['account'] as Map) : const {};
        final accountName = account['name']?.toString() ?? '';
        final accountNumber = account['account_number']?.toString() ?? '';
        final display = accountNumber.isNotEmpty ? '$accountNumber - $accountName' : accountName;
        final lineType = line['line_type']?.toString().toLowerCase();
        final amtType = line['amount_type']?.toString().toLowerCase();
        final amt = (line['amount'] is num)
            ? (line['amount'] as num).toDouble()
            : double.tryParse(line['amount']?.toString() ?? '0') ?? 0;
        final k = line['karat']?.toString();

        if (compactAL) {
          String cType = '', cAmt = '';
          if (amtType == 'cash') {
            cType = lineType == 'debit'
                ? (options.isArabic ? 'نقد مدين' : 'Cash Dr')
                : (options.isArabic ? 'نقد دائن' : 'Cash Cr');
            cAmt = currencyFmt.format(amt);
          } else if (amtType == 'gold') {
            cType = lineType == 'debit'
                ? (options.isArabic ? 'ذهب مدين' : 'Gold Dr')
                : (options.isArabic ? 'ذهب دائن' : 'Gold Cr');
            cAmt = goldFmt.format(amt);
          }
          return [display, cType, cAmt, amtType == 'gold' ? (k ?? '') : '—'];
        }

        String cashDr = '', cashCr = '', goldDr = '', goldCr = '';
        if (amtType == 'cash') {
          if (lineType == 'debit') {
            cashDr = currencyFmt.format(amt);
          } else {
            cashCr = currencyFmt.format(amt);
          }
        } else if (amtType == 'gold') {
          if (lineType == 'debit') {
            goldDr = goldFmt.format(amt);
          } else {
            goldCr = goldFmt.format(amt);
          }
        }
        return [
          display,
          cashDr,
          cashCr,
          goldDr,
          goldCr,
          amtType == 'gold' ? (k ?? '') : '',
        ];
      }

      final rows = visibleAL.map(rowFor).toList();
      final headers = options.isArabic ? baseHeaders.reversed.toList() : baseHeaders;
      final data = options.isArabic
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

      final cw = options.isArabic ? reverseMap(baseCW, baseHeaders.length) : baseCW;
      final ca = options.isArabic ? reverseMap(baseCa, baseHeaders.length) : baseCa;

      return section(
        pw.Column(
          crossAxisAlignment: pw.CrossAxisAlignment.stretch,
          children: [
            sectionTitle(options.isArabic ? 'سطور الحسابات' : 'Account Lines'),
            pw.Container(
              padding: pw.EdgeInsets.all(isA5 ? 8 : 10),
              decoration: pw.BoxDecoration(
                border: pw.Border.all(color: VoucherPdfColors.grayBorder, width: 0.5),
                borderRadius: pw.BorderRadius.circular(6),
              ),
              child: pw.TableHelper.fromTextArray(
                headers: headers,
                data: data,
                headerDecoration: pw.BoxDecoration(color: VoucherPdfColors.grayBg),
                headerStyle: pw.TextStyle(
                  fontWeight: pw.FontWeight.bold,
                  fontSize: isA5 ? 7.8 : 10.5,
                ),
                cellStyle: pw.TextStyle(fontSize: isA5 ? 7.4 : 10.2),
                cellPadding: pw.EdgeInsets.symmetric(
                  horizontal: isA5 ? 2 : 4,
                  vertical: isA5 ? 2 : 3,
                ),
                border: pw.TableBorder.all(color: VoucherPdfColors.grayBorder),
                columnWidths: cw,
                cellAlignments: ca,
              ),
            ),
            if (hiddenAL > 0) ...[
              pw.SizedBox(height: 4),
              txt(
                options.isArabic
                    ? '... تم إخفاء $hiddenAL سطر لضمان الطباعة في صفحة واحدة'
                    : '... $hiddenAL lines hidden to fit single page',
                size: isA5 ? 7.5 : 9,
                color: VoucherPdfColors.grayMuted,
              ),
            ],
          ],
        ),
      );
    }

    pw.Widget sigCell(String sigTitle, String name) => pw.Expanded(
          child: pw.Column(
            children: [
              txt(
                sigTitle,
                size: isA5 ? 8 : 9,
                color: const PdfColor.fromInt(0xFF777777),
              ),
              pw.SizedBox(height: isA5 ? 18 : 22),
              pw.Container(
                decoration: const pw.BoxDecoration(
                  border: pw.Border(
                    top: pw.BorderSide(color: VoucherPdfColors.grayMuted, width: 0.8),
                  ),
                ),
                padding: const pw.EdgeInsets.only(top: 4),
                child: pw.Center(
                  child: txt(
                    name,
                    size: isA5 ? 7 : 8,
                    color: VoucherPdfColors.grayMuted,
                  ),
                ),
              ),
            ],
          ),
        );

    pw.Widget buildSignatures() {
      final sigs = [
        (
          title: options.isArabic ? 'توقيع المستلم' : 'Receiver',
          name: (voucher['receiver_name']?.toString().trim().isNotEmpty == true)
              ? voucher['receiver_name'].toString().trim()
              : (party.isEmpty ? '—' : party),
        ),
        (
          title: options.isArabic ? 'توقيع المسلم' : 'Delivered By',
          name: createdBy.isNotEmpty ? createdBy : companyName,
        ),
        (
          title: options.isArabic ? 'اعتماد السند' : 'Approved By',
          name: approvedBy.isEmpty ? '—' : approvedBy,
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
            sectionTitle(options.isArabic ? 'التوقيعات' : 'Signatures'),
            pw.Row(children: rowChildren),
          ],
        ),
        last: true,
      );
    }

    pw.Widget buildFooter() => pw.Container(
          padding: pw.EdgeInsets.symmetric(
            horizontal: isA5 ? 12 : 16,
            vertical: isA5 ? 5 : 7,
          ),
          decoration: const pw.BoxDecoration(
            color: VoucherPdfColors.grayBg,
            border: pw.Border(
              top: pw.BorderSide(color: VoucherPdfColors.grayBorder, width: 0.5),
            ),
          ),
          child: pw.Row(
            mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
            children: [
              txt(voucherNum, size: isA5 ? 7 : 8, color: VoucherPdfColors.grayMuted),
              txt(
                '$companyName — ${options.isArabic ? 'جميع الحقوق محفوظة' : 'All rights reserved'}',
                size: isA5 ? 7 : 8,
                color: VoucherPdfColors.grayMuted,
              ),
              txt(
                '${options.isArabic ? 'طُبع بتاريخ' : 'Printed'}: $printDate',
                size: isA5 ? 7 : 8,
                color: VoucherPdfColors.grayMuted,
              ),
            ],
          ),
        );

    final double hMargin = isA5 ? 10 * PdfPageFormat.mm : 14 * PdfPageFormat.mm;
    final double vMargin = isA5 ? 8 * PdfPageFormat.mm : 12 * PdfPageFormat.mm;

    final doc = pw.Document(title: title, author: companyName);

    final bool showGoldTable = goldRowsList.isNotEmpty;
    final bool showAccountLines = options.includeAccountLines && visibleAL.isNotEmpty;
    final int contentComplexity =
        (showGoldTable ? goldRowsList.length : 0) + (showAccountLines ? visibleAL.length : 0);
    final bool useMultiPage =
        contentComplexity > (isA5 ? 8 : 10) || (description.trim().length > 220);

    if (!useMultiPage) {
      doc.addPage(
        pw.Page(
          pageFormat: format,
          margin: pw.EdgeInsets.symmetric(horizontal: hMargin, vertical: vMargin),
          textDirection: options.isArabic ? pw.TextDirection.rtl : pw.TextDirection.ltr,
          theme: pw.ThemeData.withFont(base: fontReg, bold: fontBold),
          build: (ctx) => pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.stretch,
            children: [
              buildHeader(),
              buildStatusStrip(),
              buildDetails(),
              buildAmounts(),
              buildGoldDisbursementTable(),
              if (options.includeAccountLines && visibleAL.isNotEmpty) buildAccountLines(),
              pw.Spacer(),
              buildSignatures(),
              buildFooter(),
            ],
          ),
        ),
      );
    } else {
      doc.addPage(
        pw.MultiPage(
          pageFormat: format,
          margin: pw.EdgeInsets.symmetric(horizontal: hMargin, vertical: vMargin),
          textDirection: options.isArabic ? pw.TextDirection.rtl : pw.TextDirection.ltr,
          theme: pw.ThemeData.withFont(base: fontReg, bold: fontBold),
          footer: (ctx) {
            if (ctx.pageNumber != ctx.pagesCount) return pw.SizedBox.shrink();
            return buildFooter();
          },
          build: (ctx) => <pw.Widget>[
            buildHeader(),
            buildStatusStrip(),
            buildDetails(),
            buildAmounts(),
            buildGoldDisbursementTable(),
            if (options.includeAccountLines && visibleAL.isNotEmpty) buildAccountLines(),
            buildSignatures(),
          ],
        ),
      );
    }

    return doc.save();
  }

  static String _amountInWords(bool isArabic, double amount) {
    if (!isArabic) return '';

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
      return 'صفر ريال سعودي فقط لا غير';
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
}
