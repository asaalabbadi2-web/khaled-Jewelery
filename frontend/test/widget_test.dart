import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:frontend/widgets/invoice_type_banner.dart';

void main() {
  testWidgets('InvoiceTypeBanner renders content', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: InvoiceTypeBanner(
            title: 'فاتورة بيع',
            subtitle: 'نص توضيحي',
            color: Colors.amber,
            icon: Icons.receipt_long,
          ),
        ),
      ),
    );

    expect(find.text('فاتورة بيع'), findsOneWidget);
    expect(find.text('نص توضيحي'), findsOneWidget);
    expect(find.byIcon(Icons.receipt_long), findsOneWidget);
  });
}
