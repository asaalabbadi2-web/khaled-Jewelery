import 'dart:io';

import 'package:pdf/widgets.dart' as pw;
import 'package:pdf/pdf.dart' as pdf;

import 'package:frontend/pdf/pdf_text_utils.dart';

Future<void> main() async {
  final regularFontBytes = await File('assets/fonts/Cairo-Regular.ttf').readAsBytes();
  final boldFontBytes = await File('assets/fonts/Cairo-Bold.ttf').readAsBytes();

  final fontReg = pw.Font.ttf(regularFontBytes.buffer.asByteData());
  final fontBold = pw.Font.ttf(boldFontBytes.buffer.asByteData());

  final doc = pw.Document();

  final samples = <String>[
    'لازوردي',
    'كشف حساب المورد: لازوردي',
    'سجل تجاري',
    'ملخص الأرصدة',
    'تفاصيل الحركات',
    'ي',
    'في',
    'سند صرف',
    'ر.س',
    '(ر.س)',
    'مدين نقد (ر.س)',
    'ذهب - مورد (وزن)',
    '(وزن) ذهب - مورد',
    'التزام المورد - ذهب (وزن)',
  ];

  doc.addPage(
    pw.Page(
      pageFormat: pdf.PdfPageFormat.a4,
      build: (_) {
        return pw.Directionality(
          textDirection: pw.TextDirection.rtl,
          child: pw.Column(
            crossAxisAlignment: pw.CrossAxisAlignment.start,
            children: [
              for (final s in samples)
                pw.Padding(
                  padding: const pw.EdgeInsets.only(bottom: 8),
                  child: pw.Text(
                    pdfVisualArabic(s),
                    style: pw.TextStyle(font: fontReg, fontSize: 18),
                    textDirection: pw.TextDirection.ltr,
                  ),
                ),
              pw.SizedBox(height: 16),
              pw.Text(
                'Bold: ${pdfVisualArabic('لازوردي')}',
                style: pw.TextStyle(font: fontBold, fontSize: 18),
                textDirection: pw.TextDirection.ltr,
              ),
            ],
          ),
        );
      },
    ),
  );

  final outDir = Directory('devtools/samples');
  if (!outDir.existsSync()) outDir.createSync(recursive: true);
  final outFile = File('${outDir.path}/shape_smoke.pdf');
  await outFile.writeAsBytes(await doc.save());
  stdout.writeln('Wrote ${outFile.path}');
}
