import 'package:flutter/material.dart';
import '../api_service.dart';

/// Widget مشترك لاختيار الفاتورة الأصلية للمرتجعات
/// يعرض dialog مع قائمة الفواتير القابلة للإرجاع
class OriginalInvoiceSelector extends StatelessWidget {
  final ApiService api;
  final String invoiceType;
  final int? customerId;
  final int? supplierId;
  final Map<String, dynamic>? selectedInvoice;
  final ValueChanged<Map<String, dynamic>> onInvoiceSelected;

  const OriginalInvoiceSelector({
    super.key,
    required this.api,
    required this.invoiceType,
    this.customerId,
    this.supplierId,
    this.selectedInvoice,
    required this.onInvoiceSelected,
  });

  Future<void> _showSelectDialog(BuildContext context) async {
    final bool isAr = Localizations.localeOf(context).languageCode == 'ar';

    try {
      // Fetch returnable invoices
      final response = await api.getReturnableInvoices(
        invoiceType: invoiceType,
        customerId: customerId,
        supplierId: supplierId,
      );

      if (!context.mounted) return;

      final invoices = response['invoices'] as List<dynamic>;

      if (invoices.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              isAr
                  ? 'لا توجد فواتير قابلة للإرجاع'
                  : 'No returnable invoices found',
            ),
          ),
        );
        return;
      }

      final result = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (dialogContext) {
          String searchQuery = '';
          List<dynamic> filtered = List.from(invoices);

          void applyFilter(String query, StateSetter setDialogState) {
            final q = query.trim().toLowerCase();
            setDialogState(() {
              searchQuery = q;
              if (q.isEmpty) {
                filtered = List.from(invoices);
              } else {
                // Try parsing as number for amount/weight comparison
                final qNum = double.tryParse(q.replaceAll(',', ''));
                filtered = invoices.where((inv) {
                  final name = (inv['customer_name'] ?? inv['supplier_name'] ?? '')
                      .toString()
                      .toLowerCase();
                  final id = (inv['id'] ?? '').toString();
                  final date = (inv['date'] ?? '').toString();
                  if (name.contains(q) || id.contains(q) || date.contains(q)) {
                    return true;
                  }
                  if (qNum != null) {
                    final total = (inv['total'] ?? 0.0) as num;
                    final weight = (inv['total_weight'] ?? inv['weight'] ?? -1) as num;
                    if ((total - qNum).abs() < 0.01) return true;
                    if (weight >= 0 && (weight - qNum).abs() < 0.001) return true;
                  }
                  return false;
                }).toList();
              }
            });
          }

          return StatefulBuilder(
            builder: (context, setDialogState) {
              return AlertDialog(
                title: Text(
                  isAr ? 'اختر الفاتورة الأصلية' : 'Select Original Invoice',
                ),
                content: SizedBox(
                  width: double.maxFinite,
                  height: 500,
                  child: Column(
                    children: [
                      // --- حقل البحث ---
                      TextField(
                        autofocus: false,
                        decoration: InputDecoration(
                          labelText: isAr ? 'بحث (اسم، رقم، تاريخ، مبلغ، وزن)' : 'Search (name, ID, date, amount, weight)',
                          prefixIcon: const Icon(Icons.search),
                          suffixIcon: searchQuery.isNotEmpty
                              ? IconButton(
                                  icon: const Icon(Icons.clear),
                                  onPressed: () => applyFilter('', setDialogState),
                                )
                              : null,
                          border: const OutlineInputBorder(),
                          isDense: true,
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 10,
                          ),
                        ),
                        onChanged: (v) => applyFilter(v, setDialogState),
                      ),
                      const SizedBox(height: 6),
                      // --- عداد النتائج ---
                      Align(
                        alignment: isAr
                            ? Alignment.centerRight
                            : Alignment.centerLeft,
                        child: Text(
                          isAr
                              ? '${filtered.length} فاتورة'
                              : '${filtered.length} invoice(s)',
                          style: const TextStyle(
                            fontSize: 12,
                            color: Colors.grey,
                          ),
                        ),
                      ),
                      const SizedBox(height: 4),
                      // --- قائمة الفواتير ---
                      Expanded(
                        child: filtered.isEmpty
                            ? Center(
                                child: Text(
                                  isAr
                                      ? 'لا توجد نتائج'
                                      : 'No results found',
                                  style: const TextStyle(color: Colors.grey),
                                ),
                              )
                            : ListView.builder(
                                itemCount: filtered.length,
                                itemBuilder: (context, index) {
                                  final invoice = filtered[index];
                                  final canReturn =
                                      invoice['can_return'] ?? true;
                                  final invoiceDate = invoice['date'] ?? '';
                                  final invoiceTotal =
                                      (invoice['total'] ?? 0.0) as num;
                                  final invoiceNumber =
                                      _displayInvoiceNumber(invoice);

                                  return Card(
                                    elevation: 2,
                                    margin: const EdgeInsets.symmetric(
                                      vertical: 4,
                                    ),
                                    child: ListTile(
                                      leading: CircleAvatar(
                                        backgroundColor: canReturn
                                            ? Colors.green.shade100
                                            : Colors.red.shade100,
                                        child: Text(
                                          invoiceNumber,
                                          style: TextStyle(
                                            color: canReturn
                                                ? Colors.green.shade800
                                                : Colors.red.shade800,
                                            fontWeight: FontWeight.bold,
                                            fontSize: 12,
                                          ),
                                        ),
                                      ),
                                      title: Text(
                                        invoice['customer_name'] ??
                                            invoice['supplier_name'] ??
                                            (isAr ? 'غير محدد' : 'Unknown'),
                                        style: const TextStyle(
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                      subtitle: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            '${isAr ? "التاريخ" : "Date"}: $invoiceDate',
                                            style: const TextStyle(
                                              fontSize: 12,
                                            ),
                                          ),
                                          Text(
                                            '${isAr ? "المبلغ" : "Total"}: ${invoiceTotal.toStringAsFixed(2)}',
                                            style: const TextStyle(
                                              fontSize: 12,
                                            ),
                                          ),
                                        ],
                                      ),
                                      trailing: Icon(
                                        canReturn
                                            ? Icons.check_circle
                                            : Icons.block,
                                        color: canReturn
                                            ? Colors.green
                                            : Colors.red,
                                      ),
                                      enabled: canReturn,
                                      onTap: canReturn
                                          ? () => Navigator.of(
                                                context,
                                              ).pop(invoice)
                                          : null,
                                    ),
                                  );
                                },
                              ),
                      ),
                    ],
                  ),
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: Text(isAr ? 'إلغاء' : 'Cancel'),
                  ),
                ],
              );
            },
          );
        },
      );

      if (result != null) {
        onInvoiceSelected(result);
      }
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            isAr ? 'خطأ في تحميل الفواتير: $e' : 'Error loading invoices: $e',
          ),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final bool isAr = Localizations.localeOf(context).languageCode == 'ar';

    return Card(
      elevation: 2,
      child: ListTile(
        leading: const Icon(Icons.receipt_long, color: Color(0xFFF7C873)),
        title: Text(
          selectedInvoice != null
              ? '${isAr ? "الفاتورة" : "Invoice"} ${_displayInvoiceNumber(selectedInvoice)}'
              : (isAr ? 'اختر الفاتورة الأصلية' : 'Select Original Invoice'),
          style: TextStyle(
            fontWeight: selectedInvoice != null
                ? FontWeight.bold
                : FontWeight.normal,
          ),
        ),
        subtitle: selectedInvoice != null
            ? Text(
                selectedInvoice!['customer_name'] ??
                    selectedInvoice!['supplier_name'] ??
                    (isAr ? 'غير محدد' : 'Unknown'),
              )
            : Text(
                isAr
                    ? 'اضغط لاختيار الفاتورة الأصلية'
                    : 'Tap to select original invoice',
              ),
        trailing: Icon(
          selectedInvoice != null
              ? Icons.check_circle
              : Icons.arrow_forward_ios,
          color: selectedInvoice != null
              ? Colors.green
              : const Color(0xFFF7C873),
        ),
        onTap: () => _showSelectDialog(context),
      ),
    );
  }

  String _displayInvoiceNumber(Map<String, dynamic>? invoice) {
    if (invoice == null) {
      return '#---';
    }

    final rawNumber = invoice['invoice_number'];
    if (rawNumber != null) {
      final trimmed = rawNumber.toString().trim();
      if (trimmed.isNotEmpty) {
        return trimmed;
      }
    }

    final id = invoice['id'];
    return id != null ? '#${id.toString()}' : '#---';
  }
}
