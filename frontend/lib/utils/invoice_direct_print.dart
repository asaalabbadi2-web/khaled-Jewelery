import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:pdf/pdf.dart';
import 'package:printing/printing.dart';
import 'package:provider/provider.dart';

import '../pdf/invoice_pdf_builder.dart';
import '../providers/settings_provider.dart';

Future<void> printInvoiceDirect({
  required BuildContext context,
  required Map<String, dynamic> invoice,
  String? paperSize,
  bool isArabic = true,
}) async {
  SettingsProvider? sp;
  try {
    sp = context.read<SettingsProvider>();
  } catch (_) {}

  String filename() {
    final numStr = (invoice['invoice_type_id'] ?? '').toString().trim();
    final idStr = (invoice['id'] ?? '').toString().trim();
    final base = numStr.isNotEmpty
        ? 'invoice_$numStr'
        : (idStr.isNotEmpty ? 'invoice_$idStr' : 'invoice');
    return '$base.pdf';
  }

  try {
    await Printing.layoutPdf(
      name: filename(),
      onLayout: (format) async {
        final opts = InvoicePdfOptions(isArabic: isArabic);
        return InvoicePdfBuilder.buildBytes(
          invoice: invoice,
          format: format,
          options: opts,
          settings: sp,
        );
      },
    );
  } catch (_) {
    // Let the caller handle UI messaging if needed.
    rethrow;
  }
}

Future<Uint8List> buildInvoicePdfBytes({
  required BuildContext context,
  required Map<String, dynamic> invoice,
  required PdfPageFormat format,
  bool isArabic = true,
}) async {
  SettingsProvider? sp;
  try {
    sp = context.read<SettingsProvider>();
  } catch (_) {}

  return InvoicePdfBuilder.buildBytes(
    invoice: invoice,
    format: format,
    options: InvoicePdfOptions(isArabic: isArabic),
    settings: sp,
  );
}
