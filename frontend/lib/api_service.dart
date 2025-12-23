import 'dart:convert';

import 'package:flutter/foundation.dart' show TargetPlatform, defaultTargetPlatform, kIsWeb;
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'models/app_user_model.dart';
import 'models/attendance_model.dart';
import 'models/employee_model.dart';
import 'models/payroll_model.dart';
import 'models/safe_box_model.dart';

const String _envApiBaseUrl = String.fromEnvironment('API_BASE_URL', defaultValue: '');

String _resolveApiBaseUrl() {
  if (_envApiBaseUrl.isNotEmpty) {
    return _envApiBaseUrl;
  }

  if (kIsWeb) {
    return 'http://127.0.0.1:8001/api';
  }

  if (defaultTargetPlatform == TargetPlatform.android) {
    // عندما نعمل من داخل محاكي أندرويد نحتاج 10.0.2.2 للإشارة إلى جهاز التطوير
    return 'http://10.0.2.2:8001/api';
  }

  return 'http://127.0.0.1:8001/api';
}

class ApiService {
  final String _baseUrl;

  ApiService({String? baseUrl}) : _baseUrl = baseUrl ?? _resolveApiBaseUrl();

  // Customer Methods
  Future<List<dynamic>> getCustomers() async {
    final response = await http.get(Uri.parse('$_baseUrl/customers'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load customers');
    }
  }

  Future<Map<String, dynamic>> addCustomer(
    Map<String, dynamic> customerData,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/customers'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(customerData),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to add customer: ${response.body}');
    }
  }

  Future<void> deleteCustomer(int id) async {
    final response = await http.delete(Uri.parse('$_baseUrl/customers/$id'));
    if (response.statusCode != 200) {
      // Changed from 204 to 200
      throw Exception('Failed to delete customer');
    }
  }

  Future<void> updateCustomer(int id, Map<String, dynamic> customerData) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/customers/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(customerData),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to update customer');
    }
  }

  // Supplier Methods
  Future<List<dynamic>> getSuppliers() async {
    final response = await http.get(Uri.parse('$_baseUrl/suppliers'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load suppliers');
    }
  }

  Future<Map<String, dynamic>> addSupplier(
    Map<String, dynamic> supplierData,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/suppliers'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(supplierData),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to add supplier: ${response.body}');
    }
  }

  Future<void> updateSupplier(int id, Map<String, dynamic> supplierData) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/suppliers/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(supplierData),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to update supplier');
    }
  }

  Future<void> deleteSupplier(int id) async {
    final response = await http.delete(Uri.parse('$_baseUrl/suppliers/$id'));
    if (response.statusCode != 200) {
      throw Exception('Failed to delete supplier');
    }
  }

  // Office Methods (مكاتب بيع وشراء الذهب الخام)
  Future<List<dynamic>> getOffices({bool? activeOnly}) async {
    String url = '$_baseUrl/offices';
    if (activeOnly != null) {
      url += '?active=$activeOnly';
    }
    final response = await http.get(Uri.parse(url));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load offices');
    }
  }

  Future<Map<String, dynamic>> getOffice(int id) async {
    final response = await http.get(Uri.parse('$_baseUrl/offices/$id'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load office');
    }
  }

  Future<Map<String, dynamic>> addOffice(
    Map<String, dynamic> officeData,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/offices'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(officeData),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to add office: ${response.body}');
    }
  }

  Future<void> updateOffice(int id, Map<String, dynamic> officeData) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/offices/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(officeData),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to update office');
    }
  }

  Future<void> deleteOffice(int id) async {
    final response = await http.delete(Uri.parse('$_baseUrl/offices/$id'));
    if (response.statusCode != 200) {
      throw Exception('Failed to delete office');
    }
  }

  Future<void> activateOffice(int id) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/offices/$id/activate'),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to activate office');
    }
  }

  Future<Map<String, dynamic>> getOfficeBalance(int id) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/offices/$id/balance'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load office balance');
    }
  }

  Future<Map<String, dynamic>> getOfficesStatistics() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/offices/statistics'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load offices statistics');
    }
  }

  // Office Reservations (حجوزات الذهب للمكاتب)
  Future<Map<String, dynamic>> getOfficeReservations({
    int? officeId,
    String? status,
    String? paymentStatus,
    String? dateFrom,
    String? dateTo,
    int? limit,
    int? page,
    int? perPage,
    String? orderBy,
    String? orderDirection,
  }) async {
    final queryParams = <String, String>{};
    if (officeId != null) queryParams['office_id'] = officeId.toString();
    if (status != null && status.isNotEmpty) queryParams['status'] = status;
    if (paymentStatus != null && paymentStatus.isNotEmpty) {
      queryParams['payment_status'] = paymentStatus;
    }
    if (limit != null) queryParams['limit'] = limit.toString();
    if (dateFrom != null && dateFrom.isNotEmpty) queryParams['date_from'] = dateFrom;
    if (dateTo != null && dateTo.isNotEmpty) queryParams['date_to'] = dateTo;
    if (page != null) queryParams['page'] = page.toString();
    if (perPage != null) queryParams['per_page'] = perPage.toString();
    if (orderBy != null && orderBy.isNotEmpty) queryParams['order_by'] = orderBy;
    if (orderDirection != null && orderDirection.isNotEmpty) {
      queryParams['order_direction'] = orderDirection;
    }

    final uri = Uri.parse('$_baseUrl/office-reservations').replace(
      queryParameters: queryParams.isEmpty ? null : queryParams,
    );

    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load office reservations');
    }
  }

  Future<Map<String, dynamic>> getOfficeReservation(int id) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/office-reservations/$id'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load office reservation');
    }
  }

  Future<Map<String, dynamic>> createOfficeReservation(
    Map<String, dynamic> reservationData,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/office-reservations'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(reservationData),
    );
    if (response.statusCode == 201) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to create office reservation: ${response.body}');
    }
  }

  // Item Methods
  Future<List<dynamic>> getItems({bool? inStockOnly}) async {
    Uri uri = Uri.parse('$_baseUrl/items');
    if (inStockOnly != null) {
      uri = uri.replace(queryParameters: {
        'in_stock_only': inStockOnly ? 'true' : 'false',
      });
    }
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load items');
    }
  }

  /// 🆕 البحث عن صنف بالباركود
  Future<Map<String, dynamic>> searchItemByBarcode(String barcode) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/items/search/barcode/$barcode'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else if (response.statusCode == 404) {
      throw Exception('الصنف غير موجود');
    } else {
      throw Exception('Failed to search item by barcode');
    }
  }

  Future<Map<String, dynamic>> addItem(Map<String, dynamic> itemData) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/items'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(itemData),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to add item');
    }
  }

  /// 🚀 إضافة سريعة لعدة أصناف
  Future<Map<String, dynamic>> quickAddItems(Map<String, dynamic> data) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/items/quick-add'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(data),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      final errorBody = json.decode(response.body);
      throw Exception(errorBody['error'] ?? 'Failed to quick add items');
    }
  }

  /// ♻️ إعادة مزامنة حالة توافر الأصناف
  Future<Map<String, dynamic>> rebuildItemStockStatus() async {
    final response = await http.post(
      Uri.parse('$_baseUrl/items/rebuild-stock'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final errorBody = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(errorBody['error'] ?? 'Failed to rebuild item stock status');
    }
  }

  /// 🔄 استنساخ صنف موجود
  Future<Map<String, dynamic>> cloneItem(int id, Map<String, dynamic> data) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/items/$id/clone'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(data),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      final errorBody = json.decode(response.body);
      throw Exception(errorBody['error'] ?? 'Failed to clone item');
    }
  }

  Future<Map<String, dynamic>> updateItem(
    int id,
    Map<String, dynamic> itemData,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/items/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(itemData),
    );
    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to update item');
    }
  }

  Future<void> deleteItem(int id) async {
    final response = await http.delete(Uri.parse('$_baseUrl/items/$id'));
    if (response.statusCode != 200) {
      // Changed from 204 to 200
      throw Exception('Failed to delete item');
    }
  }

  // ============================================
  // 📁 Category Methods - تصنيفات الأصناف
  // ============================================

  /// جلب جميع التصنيفات
  Future<List<dynamic>> getCategories() async {
    final response = await http.get(Uri.parse('$_baseUrl/categories'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load categories');
    }
  }

  /// جلب تصنيف واحد
  Future<Map<String, dynamic>> getCategory(int id) async {
    final response = await http.get(Uri.parse('$_baseUrl/categories/$id'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load category');
    }
  }

  /// إضافة تصنيف جديد
  Future<Map<String, dynamic>> addCategory(
      Map<String, dynamic> categoryData) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/categories'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(categoryData),
    );
    if (response.statusCode == 201) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['error'] ?? 'Failed to add category');
    }
  }

  /// تعديل تصنيف
  Future<Map<String, dynamic>> updateCategory(
      int id, Map<String, dynamic> categoryData) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/categories/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(categoryData),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['error'] ?? 'Failed to update category');
    }
  }

  /// حذف تصنيف
  Future<void> deleteCategory(int id) async {
    final response = await http.delete(Uri.parse('$_baseUrl/categories/$id'));
    if (response.statusCode != 200) {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['error'] ?? 'Failed to delete category');
    }
  }

  // Invoice Methods
  Future<Map<String, dynamic>> getInvoices({
    int page = 1,
    int perPage = 10,
    String sortBy = 'date',
    String sortOrder = 'desc',
    String search = '',
    String status = 'all',
    String? invoiceType,
    DateTime? dateFrom,
    DateTime? dateTo,
  }) async {
    final Map<String, String> queryParameters = {
      'page': page.toString(),
      'per_page': perPage.toString(),
      'sort_by': sortBy,
      'sort_order': sortOrder,
      'search': search,
      'status': status,
    };

    if (invoiceType != null && invoiceType != 'الكل') {
      queryParameters['invoice_type'] = invoiceType;
    }
    if (dateFrom != null) {
      queryParameters['date_from'] = dateFrom.toIso8601String();
    }
    if (dateTo != null) {
      queryParameters['date_to'] = dateTo.toIso8601String();
    }

    final uri = Uri.parse(
      '$_baseUrl/invoices',
    ).replace(queryParameters: queryParameters);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load invoices');
    }
  }

  /// Get invoice details by ID (includes items and payments)
  Future<Map<String, dynamic>> getInvoiceById(int invoiceId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/invoices/$invoiceId'),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception(
        'Failed to load invoice details (status: ${response.statusCode})',
      );
    }
  }

  Future<Map<String, dynamic>> addInvoice(Map<String, dynamic> invoice) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/invoices'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(invoice),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      throw Exception(
        'Failed to create invoice. Status: ${response.statusCode}, Body: ${response.body}',
      );
    }
  }

  Future<void> deleteInvoice(int invoiceId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/invoices/$invoiceId'),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to delete invoice: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> updateInvoiceStatus(
    int invoiceId,
    String status,
  ) async {
    final response = await http.patch(
      Uri.parse('$_baseUrl/invoices/$invoiceId/status'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({'status': status}),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception(
        'Failed to update invoice status: ${response.statusCode} ${response.body}',
      );
    }
  }

  // Gold Price Methods
  Future<Map<String, dynamic>> getGoldPrice() async {
    final response = await http.get(Uri.parse('$_baseUrl/gold_price'));
    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to load gold price');
    }
  }

  Future<Map<String, dynamic>> updateGoldPrice() async {
    final response = await http.post(
      Uri.parse('$_baseUrl/gold_price/update'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
    );
    if (response.statusCode == 200) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to update gold price');
    }
  }

  // Gold Costing (Moving Average)
  Future<Map<String, dynamic>> getGoldCostingSnapshot() async {
    final response = await http.get(Uri.parse('$_baseUrl/gold-costing'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load gold costing snapshot: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> calculateGoldCostingCogs(double weightGrams) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/gold-costing/cogs'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({'weight_grams': weightGrams}),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to calculate gold costing COGS: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> recomputeGoldCosting({int? limit}) async {
    Uri uri = Uri.parse('$_baseUrl/gold-costing/recompute');
    if (limit != null) {
      uri = uri.replace(queryParameters: {'limit': limit.toString()});
    }

    final response = await http.post(uri);
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to recompute gold costing: ${response.body}');
    }
  }

  // Statement Methods
  Future<Map<String, dynamic>> getAccountStatement(int accountId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/accounts/$accountId/statement'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load account statement');
    }
  }

  Future<Map<String, dynamic>> getCustomerStatement(int customerId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/customers/$customerId/statement'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load customer statement: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getSupplierStatement(int supplierId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/suppliers/$supplierId/statement'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load supplier statement: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getSupplierLedger(
    int supplierId, {
    int page = 1,
    int perPage = 50,
    DateTime? dateFrom,
    DateTime? dateTo,
  }) async {
    final queryParameters = <String, String>{
      'page': page.toString(),
      'per_page': perPage.toString(),
    };

    if (dateFrom != null) {
      queryParameters['date_from'] = dateFrom.toIso8601String();
    }
    if (dateTo != null) {
      queryParameters['date_to'] = dateTo.toIso8601String();
    }

    final uri = Uri.parse(
      '$_baseUrl/suppliers/$supplierId/ledger',
    ).replace(queryParameters: queryParameters);
    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load supplier ledger: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getSupplierBalance(int supplierId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/suppliers/$supplierId/balance'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load supplier balance: ${response.body}');
    }
  }

  // Account Methods
  Future<List<dynamic>> getAccounts() async {
    try {
      final response = await http
          .get(Uri.parse('$_baseUrl/accounts'))
          .timeout(
            const Duration(seconds: 10),
            onTimeout: () {
              throw Exception('Connection timeout - تأكد من تشغيل Backend');
            },
          );

      if (response.statusCode == 200) {
        return json.decode(utf8.decode(response.bodyBytes));
      } else {
        throw Exception('Failed to load accounts: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('خطأ في الاتصال بالـ API: $e');
    }
  }

  Future<Map<String, dynamic>> getAccountsBalances() async {
    try {
      final response = await http
          .get(Uri.parse('$_baseUrl/accounts/balances'))
          .timeout(
            const Duration(seconds: 10),
            onTimeout: () {
              throw Exception('Connection timeout - تأكد من تشغيل Backend');
            },
          );

      if (response.statusCode == 200) {
        return json.decode(utf8.decode(response.bodyBytes));
      } else {
        throw Exception('Failed to load balances: ${response.statusCode}');
      }
    } catch (e) {
      throw Exception('خطأ في جلب الأرصدة: $e');
    }
  }

  Future<Map<String, dynamic>> addAccount(
    Map<String, dynamic> accountData,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/accounts'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(accountData),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to add account');
    }
  }

  Future<void> updateAccount(int id, Map<String, dynamic> accountData) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/accounts/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(accountData),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to update account');
    }
  }

  Future<void> deleteAccount(int id) async {
    final response = await http.delete(Uri.parse('$_baseUrl/accounts/$id'));
    if (response.statusCode != 200) {
      // Changed from 204 to 200
      throw Exception('Failed to delete account');
    }
  }

  // Journal Entry Methods
  Future<List<dynamic>> getJournalEntries() async {
    final response = await http.get(Uri.parse('$_baseUrl/journal_entries'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load journal entries');
    }
  }

  Future<Map<String, dynamic>> addJournalEntry(
    Map<String, dynamic> entryData,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/journal_entries'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(entryData),
    );
    if (response.statusCode == 201) {
      return json.decode(response.body);
    } else {
      throw Exception('Failed to add journal entry: ${response.body}');
    }
  }

  Future<void> updateJournalEntry(
    int id,
    Map<String, dynamic> entryData,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/journal_entries/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(entryData),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to update journal entry: ${response.body}');
    }
  }

  // ===== نظام الحذف الآمن (Soft Delete) =====

  Future<Map<String, dynamic>> softDeleteJournalEntry(
    int id,
    String deletedBy,
    String reason,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/journal_entries/$id/soft_delete'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'deleted_by': deletedBy, 'reason': reason}),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['error'] ?? 'فشل حذف القيد');
    }
  }

  Future<Map<String, dynamic>> restoreJournalEntry(
    int id,
    String restoredBy,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/journal_entries/$id/restore'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'restored_by': restoredBy}),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['error'] ?? 'فشل استرجاع القيد');
    }
  }

  Future<List<dynamic>> getDeletedJournalEntries() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/journal_entries/deleted'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load deleted journal entries');
    }
  }

  Future<void> deleteJournalEntry(int id) async {
    // الحذف النهائي (Hard Delete) - للاستخدام الإداري فقط
    final response = await http.delete(
      Uri.parse('$_baseUrl/journal_entries/$id'),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to delete journal entry');
    }
  }

  // General Ledger
  // General Ledger - Updated with filters
  Future<Map<String, dynamic>> getGeneralLedgerAll({
    int? accountId,
    String? startDate,
    String? endDate,
    bool showBalances = true,
    bool karatDetail = false,
  }) async {
    final queryParams = <String, String>{};

    if (accountId != null) queryParams['account_id'] = accountId.toString();
    if (startDate != null) queryParams['start_date'] = startDate;
    if (endDate != null) queryParams['end_date'] = endDate;
    queryParams['show_balances'] = showBalances.toString();
    queryParams['karat_detail'] = karatDetail.toString();

    final uri = Uri.parse(
      '$_baseUrl/general_ledger_all',
    ).replace(queryParameters: queryParams);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load general ledger');
    }
  }

  // Account Ledger - New endpoint
  Future<Map<String, dynamic>> getAccountLedger(
    int accountId, {
    String? startDate,
    String? endDate,
    bool karatDetail = true,
  }) async {
    final queryParams = <String, String>{};

    if (startDate != null) queryParams['start_date'] = startDate;
    if (endDate != null) queryParams['end_date'] = endDate;
    queryParams['karat_detail'] = karatDetail.toString();

    final uri = Uri.parse(
      '$_baseUrl/account_ledger/$accountId',
    ).replace(queryParameters: queryParams);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load account ledger');
    }
  }

  // Trial Balance
  Future<Map<String, dynamic>> getTrialBalance({
    String? startDate,
    String? endDate,
    bool karatDetail = false,
  }) async {
    // Build query parameters
    final queryParams = <String, String>{};
    if (startDate != null) queryParams['start_date'] = startDate;
    if (endDate != null) queryParams['end_date'] = endDate;
    if (karatDetail) queryParams['karat_detail'] = 'true';

    final uri = Uri.parse(
      '$_baseUrl/trial_balance',
    ).replace(queryParameters: queryParams);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load trial balance');
    }
  }

  Future<Map<String, dynamic>> getSalesOverviewReport({
    DateTime? startDate,
    DateTime? endDate,
    String groupBy = 'day',
    bool includeUnposted = false,
    String? goldType,
  }) async {
    final queryParams = <String, String>{
      'group_by': groupBy,
    };

    if (startDate != null) {
      queryParams['start_date'] = startDate.toIso8601String().split('T').first;
    }

    if (endDate != null) {
      queryParams['end_date'] = endDate.toIso8601String().split('T').first;
    }

    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }

    if (goldType != null && goldType.isNotEmpty) {
      queryParams['gold_type'] = goldType;
    }

    final uri = Uri.parse('$_baseUrl/reports/sales_overview')
        .replace(queryParameters: queryParams.isNotEmpty ? queryParams : null);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load sales overview report: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getIncomeStatementReport({
    DateTime? startDate,
    DateTime? endDate,
    String groupBy = 'month',
    bool includeUnposted = false,
  }) async {
    final queryParams = <String, String>{
      'group_by': groupBy,
    };

    if (startDate != null) {
      queryParams['start_date'] = startDate.toIso8601String().split('T').first;
    }

    if (endDate != null) {
      queryParams['end_date'] = endDate.toIso8601String().split('T').first;
    }

    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }

    final uri = Uri.parse('$_baseUrl/reports/income_statement')
        .replace(queryParameters: queryParams);

    Map<String, dynamic> ensureWeightExpenseFields(Map<String, dynamic> payload) {
      payload.putIfAbsent('weight_expenses_posted', () => payload['weight_expenses'] ?? 0.0);
      payload.putIfAbsent('weight_expenses_pending', () => 0.0);
      payload.putIfAbsent('weight_expenses_pending_cash', () => 0.0);
      payload.putIfAbsent('weight_expenses', () => payload['weight_expenses_posted'] ?? 0.0);
      payload.putIfAbsent('manufacturing_wage_expense', () => 0.0);
      payload.putIfAbsent('operating_expenses_excl_wage', () => payload['operating_expenses'] ?? 0.0);
      payload.putIfAbsent('operating_expenses', () => payload['operating_expenses_excl_wage'] ?? 0.0);
      payload.putIfAbsent('weight_net_profit', () => 0.0);
      return payload;
    }

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      final decoded = json.decode(utf8.decode(response.bodyBytes));
      if (decoded is Map<String, dynamic>) {
    final summary = Map<String, dynamic>.from(decoded['summary'] ?? {});
    decoded['summary'] = ensureWeightExpenseFields(summary);

        final dynamic rawSeries = decoded['series'];
        if (rawSeries is List) {
          decoded['series'] = rawSeries
      .map((entry) => ensureWeightExpenseFields(Map<String, dynamic>.from(entry ?? {})))
              .toList();
        }

        return decoded;
      }
      return {'summary': {}, 'series': []};
    } else {
      throw Exception('Failed to load income statement report: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getSalesByCustomerReport({
    DateTime? startDate,
    DateTime? endDate,
    bool includeUnposted = false,
    int limit = 25,
    String orderBy = 'net_value',
    bool ascending = false,
  }) async {
    final queryParams = <String, String>{
      'limit': limit.toString(),
      'order_by': orderBy,
      'order_direction': ascending ? 'asc' : 'desc',
    };

    if (startDate != null) {
      queryParams['start_date'] = startDate.toIso8601String().split('T').first;
    }

    if (endDate != null) {
      queryParams['end_date'] = endDate.toIso8601String().split('T').first;
    }

    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }

    final uri = Uri.parse('$_baseUrl/reports/sales_by_customer')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception(
        'Failed to load sales by customer report: ${response.body}',
      );
    }
  }

  Future<Map<String, dynamic>> getSalesByItemReport({
    DateTime? startDate,
    DateTime? endDate,
    bool includeUnposted = false,
    int limit = 25,
    String orderBy = 'net_value',
    bool ascending = false,
  }) async {
    final queryParams = <String, String>{
      'limit': limit.toString(),
      'order_by': orderBy,
      'order_direction': ascending ? 'asc' : 'desc',
    };

    if (startDate != null) {
      queryParams['start_date'] = startDate.toIso8601String().split('T').first;
    }

    if (endDate != null) {
      queryParams['end_date'] = endDate.toIso8601String().split('T').first;
    }

    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }

    final uri = Uri.parse('$_baseUrl/reports/sales_by_item')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load sales by item report: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getInventoryStatusReport({
    List<num>? karats,
    bool includeZeroStock = false,
    bool includeUnposted = false,
    int? limit,
    String orderBy = 'market_value',
    bool ascending = false,
    int slowDays = 45,
  }) async {
    final queryParams = <String, String>{
      'order_by': orderBy,
      'order_direction': ascending ? 'asc' : 'desc',
      'slow_days': slowDays.toString(),
    };

    if (limit != null) {
      queryParams['limit'] = limit.toString();
    }

    if (karats != null && karats.isNotEmpty) {
      queryParams['karats'] = karats.map((k) => k.toString()).join(',');
    }

    if (includeZeroStock) {
      queryParams['include_zero_stock'] = 'true';
    }

    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }

    final uri = Uri.parse('$_baseUrl/reports/inventory_status')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception(
        'Failed to load inventory status report: ${response.body}',
      );
    }
  }

  Future<Map<String, dynamic>> getLowStockReport({
    bool includeZeroStock = false,
    bool includeUnposted = false,
    List<num>? karats,
    int? officeId,
    double? thresholdQuantity,
    double? thresholdWeight,
    int limit = 150,
    String sortBy = 'severity',
    bool ascending = false,
  }) async {
    final queryParams = <String, String>{
      'limit': limit.toString(),
      'sort_by': sortBy,
      'sort_direction': ascending ? 'asc' : 'desc',
    };

    if (includeZeroStock) {
      queryParams['include_zero_stock'] = 'true';
    }

    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }

    if (karats != null && karats.isNotEmpty) {
      queryParams['karats'] = karats.map((k) => k.toString()).join(',');
    }

    if (officeId != null) {
      queryParams['office_id'] = officeId.toString();
    }

    if (thresholdQuantity != null) {
      queryParams['threshold_quantity'] = thresholdQuantity.toString();
    }

    if (thresholdWeight != null) {
      queryParams['threshold_weight'] = thresholdWeight.toString();
    }

    final uri = Uri.parse('$_baseUrl/reports/low_stock')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load low stock report: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getInventoryMovementReport({
    DateTime? startDate,
    DateTime? endDate,
    String groupInterval = 'day',
    bool includeUnposted = false,
    bool includeReturns = true,
    List<num>? karats,
    List<int>? officeIds,
    int movementsLimit = 200,
  }) async {
    final queryParams = <String, String>{
      'group_interval': groupInterval,
      'movements_limit': movementsLimit.toString(),
    };

    if (startDate != null) {
      queryParams['start_date'] = startDate.toIso8601String().split('T').first;
    }

    if (endDate != null) {
      queryParams['end_date'] = endDate.toIso8601String().split('T').first;
    }

    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }

    if (!includeReturns) {
      queryParams['include_returns'] = 'false';
    }

    if (karats != null && karats.isNotEmpty) {
      queryParams['karats'] = karats.map((k) => k.toString()).join(',');
    }

    if (officeIds != null && officeIds.isNotEmpty) {
      queryParams['office_ids'] = officeIds.map((id) => id.toString()).join(',');
    }

    final uri = Uri.parse('$_baseUrl/reports/inventory_movement')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception(
        'Failed to load inventory movement report: ${response.body}',
      );
    }
  }

  Future<Map<String, dynamic>> getSalesVsPurchasesTrend({
    DateTime? startDate,
    DateTime? endDate,
    String groupInterval = 'day',
    bool includeUnposted = false,
    String? goldType,
  }) async {
    final queryParams = <String, String>{
      'group_interval': groupInterval,
    };

    if (startDate != null) {
      queryParams['start_date'] = startDate.toIso8601String().split('T').first;
    }
    if (endDate != null) {
      queryParams['end_date'] = endDate.toIso8601String().split('T').first;
    }
    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }
    if (goldType != null && goldType.isNotEmpty) {
      queryParams['gold_type'] = goldType;
    }

    final uri = Uri.parse('$_baseUrl/reports/sales_vs_purchases_trend')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load sales vs purchases trend: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> getCustomerBalancesAgingReport({
    DateTime? cutoffDate,
    bool includeZeroBalances = false,
    bool includeUnposted = false,
    int? customerGroupId,
    int topLimit = 5,
  }) async {
    final queryParams = <String, String>{
      'top_limit': topLimit.toString(),
    };

    if (cutoffDate != null) {
      queryParams['cutoff_date'] = cutoffDate.toIso8601String().split('T').first;
    }

    if (includeZeroBalances) {
      queryParams['include_zero_balances'] = 'true';
    }

    if (includeUnposted) {
      queryParams['include_unposted'] = 'true';
    }

    if (customerGroupId != null) {
      queryParams['customer_group_id'] = customerGroupId.toString();
    }

    final uri = Uri.parse('$_baseUrl/reports/customer_balances_aging')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception(
        'Failed to load customer balances aging report: ${response.body}',
      );
    }
  }

  Future<Map<String, dynamic>> getGoldPriceHistoryReport({
    DateTime? startDate,
    DateTime? endDate,
    String groupInterval = 'day',
    int limit = 180,
  }) async {
    final queryParams = <String, String>{
      'group_interval': groupInterval,
      'limit': limit.toString(),
    };

    if (startDate != null) {
      queryParams['start_date'] = startDate.toIso8601String().split('T').first;
    }

    if (endDate != null) {
      queryParams['end_date'] = endDate.toIso8601String().split('T').first;
    }

    final uri = Uri.parse('$_baseUrl/reports/gold_price_history')
        .replace(queryParameters: queryParams);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception(
        'Failed to load gold price history report: ${response.body}',
      );
    }
  }

  Future<Map<String, dynamic>> getGoldPositionReport({
    bool includeZero = false,
    double? minVariance,
    List<String>? safeTypes,
    List<int>? officeIds,
    List<num>? karats,
  }) async {
    final queryParams = <String, String>{};

    if (includeZero) {
      queryParams['include_zero'] = 'true';
    }

    if (minVariance != null) {
      queryParams['min_variance'] = minVariance.toString();
    }

    if (safeTypes != null && safeTypes.isNotEmpty) {
      queryParams['safe_types'] = safeTypes.join(',');
    }

    if (officeIds != null && officeIds.isNotEmpty) {
      queryParams['office_ids'] = officeIds.map((id) => id.toString()).join(',');
    }

    if (karats != null && karats.isNotEmpty) {
      queryParams['karats'] = karats.map((k) => k.toString()).join(',');
    }

    final uri = Uri.parse('$_baseUrl/reports/gold_position')
        .replace(queryParameters: queryParams.isEmpty ? null : queryParams);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load gold position report: ${response.body}');
    }
  }

  // Hybrid System - Customer & Supplier Code Methods

  /// Get next available customer code (C-000001, C-000002, ...)
  Future<Map<String, dynamic>> getNextCustomerCode() async {
    final response = await http.get(Uri.parse('$_baseUrl/customers/next-code'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to get next customer code');
    }
  }

  /// Get next available supplier code (S-000001, S-000002, ...)
  Future<Map<String, dynamic>> getNextSupplierCode() async {
    final response = await http.get(Uri.parse('$_baseUrl/suppliers/next-code'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to get next supplier code');
    }
  }

  // Settings Methods
  Future<Map<String, dynamic>> getSettings() async {
    final response = await http.get(Uri.parse('$_baseUrl/settings'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load settings');
    }
  }

  Future<void> updateSettings(Map<String, dynamic> settingsData) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/settings'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(settingsData),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to update settings: ${response.body}');
    }
  }

  /// إعدادات التسكير الوزني (auto-close)
  Future<Map<String, dynamic>> getWeightClosingSettings() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/weight-closing/settings'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load weight closing settings');
    }
  }

  Future<Map<String, dynamic>> updateWeightClosingSettings(
    Map<String, dynamic> payload,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/weight-closing/settings'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(payload),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to update weight closing settings: ${response.body}');
    }
  }

  // System Methods

  /// إعادة تهيئة النظام مع دعم خيارات متعددة
  Future<Map<String, dynamic>> resetSystem({String? resetType}) async {
    final body = resetType != null ? {'reset_type': resetType} : {};

    final response = await http.post(
      Uri.parse('$_baseUrl/system/reset'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(body),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to reset system: ${response.body}');
    }
  }

  /// الحصول على معلومات النظام قبل إعادة التهيئة
  Future<Map<String, dynamic>> getSystemResetInfo() async {
    final response = await http.get(Uri.parse('$_baseUrl/system/reset/info'));

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to get system info: ${response.body}');
    }
  }

  /// تصفير أو إعادة بناء متوسط التكلفة المتحرك
  Future<Map<String, dynamic>> resetGoldCosting({required String mode, int? limit}) async {
    final Map<String, dynamic> payload = {'mode': mode};
    if (limit != null) {
      payload['limit'] = limit;
    }

    final response = await http.post(
      Uri.parse('$_baseUrl/gold-costing/reset'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(payload),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to reset gold costing: ${response.body}');
    }
  }

  // Return Invoice Methods (New)

  /// Get returnable invoices with optional filters
  Future<Map<String, dynamic>> getReturnableInvoices({
    String? invoiceType,
    int? customerId,
    int? supplierId,
  }) async {
    final Map<String, String> queryParams = {};
    if (invoiceType != null) queryParams['invoice_type'] = invoiceType;
    if (customerId != null) queryParams['customer_id'] = customerId.toString();
    if (supplierId != null) queryParams['supplier_id'] = supplierId.toString();

    final uri = Uri.parse(
      '$_baseUrl/invoices/returnable',
    ).replace(queryParameters: queryParams.isNotEmpty ? queryParams : null);

    final response = await http.get(uri);
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load returnable invoices');
    }
  }

  /// Check if an invoice can be returned
  Future<Map<String, dynamic>> checkCanReturn(int invoiceId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/invoices/$invoiceId/can-return'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to check return status');
    }
  }

  /// Get all returns for a specific invoice
  Future<Map<String, dynamic>> getInvoiceReturns(int invoiceId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/invoices/$invoiceId/returns'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load invoice returns');
    }
  }

  // ============================================================================
  // Vouchers Methods (سندات القبض والصرف)
  // ============================================================================

  /// Get all vouchers with optional filters and pagination
  Future<Map<String, dynamic>> getVouchers({
    int page = 1,
    int perPage = 20,
    String? type, // receipt, payment, adjustment
    String? status, // active, cancelled
    String? dateFrom,
    String? dateTo,
    String? search,
  }) async {
    final Map<String, String> queryParameters = {
      'page': page.toString(),
      'per_page': perPage.toString(),
    };

    if (type != null && type != 'all') {
      queryParameters['type'] = type;
    }
    if (status != null && status != 'all') {
      queryParameters['status'] = status;
    }
    if (dateFrom != null) {
      queryParameters['date_from'] = dateFrom;
    }
    if (dateTo != null) {
      queryParameters['date_to'] = dateTo;
    }
    if (search != null && search.isNotEmpty) {
      queryParameters['search'] = search;
    }

    final uri = Uri.parse(
      '$_baseUrl/vouchers',
    ).replace(queryParameters: queryParameters);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load vouchers');
    }
  }

  /// Get single voucher by ID
  Future<Map<String, dynamic>> getVoucher(int voucherId) async {
    final response = await http.get(Uri.parse('$_baseUrl/vouchers/$voucherId'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load voucher');
    }
  }

  /// Create new voucher
  Future<Map<String, dynamic>> createVoucher(
    Map<String, dynamic> voucherData,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/vouchers'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(voucherData),
    );
    if (response.statusCode == 201) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to create voucher: ${response.body}');
    }
  }

  /// Approve a pending voucher (creates journal entry on backend)
  Future<Map<String, dynamic>> approveVoucher(
    int voucherId, {
    String? approvedBy,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/vouchers/$voucherId/approve'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({'approved_by': approvedBy ?? 'user'}),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to approve voucher: ${response.body}');
    }
  }

  /// Update existing voucher
  Future<Map<String, dynamic>> updateVoucher(
    int voucherId,
    Map<String, dynamic> voucherData,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/vouchers/$voucherId'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(voucherData),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to update voucher: ${response.body}');
    }
  }

  /// Delete voucher
  Future<void> deleteVoucher(int voucherId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/vouchers/$voucherId'),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to delete voucher');
    }
  }

  /// Cancel voucher
  Future<Map<String, dynamic>> cancelVoucher(
    int voucherId,
    String reason,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/vouchers/$voucherId/cancel'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({'reason': reason}),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to cancel voucher: ${response.body}');
    }
  }

  /// Get vouchers statistics
  Future<Map<String, dynamic>> getVouchersStats() async {
    final response = await http.get(Uri.parse('$_baseUrl/vouchers/stats'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load vouchers stats');
    }
  }

  // ========================================
  // 💳 Payment Methods APIs
  // ========================================

  /// جلب جميع وسائل الدفع
  Future<List<dynamic>> getPaymentMethods() async {
    final response = await http.get(Uri.parse('$_baseUrl/payment-methods'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load payment methods');
    }
  }

  /// جلب وسائل الدفع النشطة فقط
  Future<List<dynamic>> getActivePaymentMethods() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/payment-methods/active'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load active payment methods');
    }
  }

  /// جلب الحسابات البنكية المتاحة
  Future<List<dynamic>> getBankAccounts() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/payment-methods/bank-accounts'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load bank accounts');
    }
  }

  /// جلب أنواع الفواتير المتاحة لوسائل الدفع
  Future<Map<String, dynamic>> getPaymentInvoiceTypeOptions() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/payment-methods/invoice-types'),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load payment invoice types: ${response.body}');
    }
  }

  /// إضافة وسيلة دفع جديدة
  Future<Map<String, dynamic>> createPaymentMethod({
    required String paymentType,
    required String name,
    int? parentAccountId, // 🆕 أصبح اختياري للتوافق
    int? defaultSafeBoxId, // 🆕 الخزينة الافتراضية
    double commissionRate = 0.0,
    int settlementDays = 0, // 🆕
    bool isActive = true,
    List<String>? applicableInvoiceTypes,
  }) async {
    final payload = <String, dynamic>{
      'payment_type': paymentType,
      'name': name,
      'commission_rate': commissionRate,
      'settlement_days': settlementDays, // 🆕
      'is_active': isActive,
    };

    // 🆕 إرسال الخزينة الافتراضية (أولوية)
    if (defaultSafeBoxId != null) {
      payload['default_safe_box_id'] = defaultSafeBoxId;
    } else if (parentAccountId != null) {
      // للتوافق مع الكود القديم
      payload['parent_account_id'] = parentAccountId;
    }

    if (applicableInvoiceTypes != null && applicableInvoiceTypes.isNotEmpty) {
      payload['applicable_invoice_types'] = applicableInvoiceTypes;
    }

    final response = await http.post(
      Uri.parse('$_baseUrl/payment-methods'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(payload),
    );
    if (response.statusCode == 201) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to create payment method: ${response.body}');
    }
  }

  /// تعديل وسيلة دفع
  Future<Map<String, dynamic>> updatePaymentMethod(
    int id, {
    required String paymentType,
    required String name,
    required double commissionRate,
    required bool isActive,
    List<String>? applicableInvoiceTypes,
  }) async {
    final payload = <String, dynamic>{
      'payment_type': paymentType,
      'name': name,
      'commission_rate': commissionRate,
      'is_active': isActive,
    };

    if (applicableInvoiceTypes != null && applicableInvoiceTypes.isNotEmpty) {
      payload['applicable_invoice_types'] = applicableInvoiceTypes;
    }

    final response = await http.put(
      Uri.parse('$_baseUrl/payment-methods/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(payload),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to update payment method: ${response.body}');
    }
  }

  /// حذف وسيلة دفع
  Future<void> deletePaymentMethod(int id) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/payment-methods/$id'),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to delete payment method');
    }
  }

  /// حفظ ترتيب طرق الدفع
  Future<void> updatePaymentMethodsOrder(
    List<Map<String, dynamic>> methods,
  ) async {
    // تحديث display_order لكل طريقة دفع
    final updates = methods.asMap().entries.map((entry) {
      return {
        'id': entry.value['id'],
        'display_order': entry.key + 1, // الترتيب يبدأ من 1
      };
    }).toList();

    final response = await http.put(
      Uri.parse('$_baseUrl/payment-methods/update-order'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({'methods': updates}),
    );

    if (response.statusCode != 200) {
      throw Exception(
        'Failed to update payment methods order: ${response.body}',
      );
    }
  }

  /// جلب أنواع وسائل الدفع (ديناميكي من القاعدة)
  Future<List<dynamic>> getPaymentTypes() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/payment-types'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
    );

    if (response.statusCode == 200) {
      return json.decode(response.body) as List<dynamic>;
    } else {
      throw Exception('Failed to load payment types');
    }
  }

  // ==================== Accounting Mapping Methods ====================

  /// الحصول على جميع إعدادات الربط المحاسبي
  Future<List<dynamic>> getAccountingMappings({String? operationType}) async {
    String url = '$_baseUrl/accounting-mappings';
    if (operationType != null) {
      url += '?operation_type=$operationType';
    }

    final response = await http.get(
      Uri.parse(url),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes)) as List<dynamic>;
    } else {
      throw Exception('Failed to load accounting mappings');
    }
  }

  /// إنشاء أو تحديث إعداد ربط محاسبي
  Future<Map<String, dynamic>> createAccountingMapping({
    required String operationType,
    required String accountType,
    required int accountId,
    double? allocationPercentage,
    String? description,
    bool isActive = true,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/accounting-mappings'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({
        'operation_type': operationType,
        'account_type': accountType,
        'account_id': accountId,
        'allocation_percentage': allocationPercentage,
        'description': description,
        'is_active': isActive,
      }),
    );

    if (response.statusCode == 200 || response.statusCode == 201) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to create accounting mapping: ${response.body}');
    }
  }

  /// إنشاء عدة إعدادات ربط دفعة واحدة
  Future<Map<String, dynamic>> batchCreateAccountingMappings(
    List<Map<String, dynamic>> mappings,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/accounting-mappings/batch'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({'mappings': mappings}),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception(
        'Failed to batch create accounting mappings: ${response.body}',
      );
    }
  }

  /// حذف إعداد ربط محاسبي
  Future<void> deleteAccountingMapping(int mappingId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/accounting-mappings/$mappingId'),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to delete accounting mapping');
    }
  }

  /// الحصول على الحساب المرتبط لعملية معينة
  Future<Map<String, dynamic>> getMappedAccount({
    required String operationType,
    required String accountType,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/accounting-mappings/get-account'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({
        'operation_type': operationType,
        'account_type': accountType,
      }),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to get mapped account: ${response.body}');
    }
  }

  // ---------------------------------------------------------------------------
  // Employees API
  // ---------------------------------------------------------------------------

  Future<Map<String, dynamic>> getEmployees({
    int page = 1,
    int perPage = 20,
    String? search,
    String? department,
    bool? isActive,
  }) async {
    final queryParameters = <String, String>{
      'page': page.toString(),
      'per_page': perPage.toString(),
    };

    if (search != null && search.isNotEmpty) {
      queryParameters['search'] = search;
    }
    if (department != null && department.isNotEmpty) {
      queryParameters['department'] = department;
    }
    if (isActive != null) {
      queryParameters['is_active'] = isActive ? 'true' : 'false';
    }

    final uri = Uri.parse(
      '$_baseUrl/employees',
    ).replace(queryParameters: queryParameters);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      final raw =
          json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final employeesJson = raw['employees'] as List<dynamic>? ?? [];
      final employees = employeesJson
          .map((e) => EmployeeModel.fromJson(e as Map<String, dynamic>))
          .toList();

      return {
        'employees': employees,
        'total': raw['total'] ?? employees.length,
        'pages': raw['pages'] ?? 1,
        'current_page': raw['current_page'] ?? page,
        'per_page': raw['per_page'] ?? perPage,
      };
    } else {
      throw Exception('Failed to load employees: ${response.body}');
    }
  }

  Future<EmployeeModel> getEmployee(int employeeId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/employees/$employeeId'),
    );

    if (response.statusCode == 200) {
      return EmployeeModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to load employee: ${response.body}');
    }
  }

  Future<EmployeeModel> createEmployee(Map<String, dynamic> payload) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/employees'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(_normalizePayload(payload)),
    );

    if (response.statusCode == 201) {
      return EmployeeModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to create employee: ${response.body}');
    }
  }

  Future<EmployeeModel> updateEmployee(
    int employeeId,
    Map<String, dynamic> payload,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/employees/$employeeId'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(_normalizePayload(payload)),
    );

    if (response.statusCode == 200) {
      return EmployeeModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to update employee: ${response.body}');
    }
  }

  Future<void> deleteEmployee(int employeeId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/employees/$employeeId'),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to delete employee: ${response.body}');
    }
  }

  Future<bool> toggleEmployeeActive(int employeeId) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/employees/$employeeId/toggle-active'),
    );
    if (response.statusCode == 200) {
      final raw =
          json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      return raw['is_active'] as bool? ?? false;
    } else {
      throw Exception('Failed to toggle employee status: ${response.body}');
    }
  }

  Future<List<PayrollModel>> getEmployeePayroll(int employeeId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/employees/$employeeId/payroll'),
    );
    if (response.statusCode == 200) {
      final raw = json.decode(utf8.decode(response.bodyBytes)) as List<dynamic>;
      return raw
          .map((e) => PayrollModel.fromJson(e as Map<String, dynamic>))
          .toList();
    } else {
      throw Exception('Failed to load employee payroll: ${response.body}');
    }
  }

  Future<List<AttendanceModel>> getEmployeeAttendance(
    int employeeId, {
    DateTime? startDate,
    DateTime? endDate,
  }) async {
    final queryParameters = <String, String>{};
    if (startDate != null) {
      queryParameters['start_date'] = startDate
          .toIso8601String()
          .split('T')
          .first;
    }
    if (endDate != null) {
      queryParameters['end_date'] = endDate.toIso8601String().split('T').first;
    }

    final uri = Uri.parse(
      '$_baseUrl/employees/$employeeId/attendance',
    ).replace(queryParameters: queryParameters);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      final raw = json.decode(utf8.decode(response.bodyBytes)) as List<dynamic>;
      return raw
          .map((e) => AttendanceModel.fromJson(e as Map<String, dynamic>))
          .toList();
    } else {
      throw Exception('Failed to load attendance: ${response.body}');
    }
  }

  // ---------------------------------------------------------------------------
  // Users & Authentication API
  // ---------------------------------------------------------------------------

  Future<List<AppUserModel>> getUsers({
    bool? isActive,
    String? role,
    String? search,
  }) async {
    final queryParameters = <String, String>{};
    if (isActive != null) {
      queryParameters['is_active'] = isActive ? 'true' : 'false';
    }
    if (role != null && role.isNotEmpty) {
      queryParameters['role'] = role;
    }
    if (search != null && search.isNotEmpty) {
      queryParameters['search'] = search;
    }

    final uri = Uri.parse(
      '$_baseUrl/users',
    ).replace(queryParameters: queryParameters);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      final raw = json.decode(utf8.decode(response.bodyBytes)) as List<dynamic>;
      return raw
          .map((e) => AppUserModel.fromJson(e as Map<String, dynamic>))
          .toList();
    } else {
      throw Exception('Failed to load users: ${response.body}');
    }
  }

  Future<AppUserModel> createUser(Map<String, dynamic> payload) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/users'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(_normalizePayload(payload)),
    );

    if (response.statusCode == 201) {
      return AppUserModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to create user: ${response.body}');
    }
  }

  Future<AppUserModel> updateUser(
    int userId,
    Map<String, dynamic> payload,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/users/$userId'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(_normalizePayload(payload)),
    );

    if (response.statusCode == 200) {
      return AppUserModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to update user: ${response.body}');
    }
  }

  Future<void> deleteUser(int userId) async {
    final response = await http.delete(Uri.parse('$_baseUrl/users/$userId'));
    if (response.statusCode != 200) {
      throw Exception('Failed to delete user: ${response.body}');
    }
  }

  Future<bool> toggleUserActive(int userId) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/users/$userId/toggle-active'),
    );
    if (response.statusCode == 200) {
      final raw =
          json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      return raw['is_active'] as bool? ?? false;
    } else {
      throw Exception('Failed to toggle user status: ${response.body}');
    }
  }

  Future<void> resetUserPassword(int userId, String newPassword) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/users/$userId/reset-password'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({'new_password': newPassword}),
    );

    if (response.statusCode != 200) {
      throw Exception('Failed to reset password: ${response.body}');
    }
  }

  Future<AppUserModel> login(String username, String password) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({'username': username, 'password': password}),
    );

    if (response.statusCode == 200) {
      final raw =
          json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      if (raw['user'] is Map<String, dynamic>) {
        return AppUserModel.fromJson(raw['user'] as Map<String, dynamic>);
      }
      throw Exception('Unexpected login response');
    } else {
      throw Exception('Login failed: ${response.body}');
    }
  }

  Future<Map<String, dynamic>> checkSetup() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/auth/check-setup'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes))
          as Map<String, dynamic>;
    } else {
      throw Exception('Check setup failed: ${response.body}');
    }
  }

  // ---------------------------------------------------------------------------
  // Payroll API
  // ---------------------------------------------------------------------------

  Future<List<PayrollModel>> getPayroll({
    int? employeeId,
    int? year,
    int? month,
    String? status,
  }) async {
    final queryParameters = <String, String>{};
    if (employeeId != null) {
      queryParameters['employee_id'] = employeeId.toString();
    }
    if (year != null) {
      queryParameters['year'] = year.toString();
    }
    if (month != null) {
      queryParameters['month'] = month.toString();
    }
    if (status != null && status.isNotEmpty) {
      queryParameters['status'] = status;
    }

    final uri = Uri.parse(
      '$_baseUrl/payroll',
    ).replace(queryParameters: queryParameters);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      final raw = json.decode(utf8.decode(response.bodyBytes)) as List<dynamic>;
      return raw
          .map((e) => PayrollModel.fromJson(e as Map<String, dynamic>))
          .toList();
    } else {
      throw Exception('Failed to load payroll: ${response.body}');
    }
  }

  Future<PayrollModel> createPayroll(Map<String, dynamic> payload) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/payroll'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(_normalizePayload(payload)),
    );

    if (response.statusCode == 201) {
      return PayrollModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to create payroll entry: ${response.body}');
    }
  }

  Future<PayrollModel> updatePayroll(
    int payrollId,
    Map<String, dynamic> payload,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/payroll/$payrollId'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(_normalizePayload(payload)),
    );

    if (response.statusCode == 200) {
      return PayrollModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to update payroll entry: ${response.body}');
    }
  }

  Future<void> deletePayroll(int payrollId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/payroll/$payrollId'),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to delete payroll entry: ${response.body}');
    }
  }

  /// الحصول على حسابات الدفع المتاحة (نقدية، بنك، شيك)
  Future<List<Map<String, dynamic>>> getPaymentAccounts() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/payroll/payment-accounts'),
    );
    if (response.statusCode == 200) {
      final List<dynamic> data = json.decode(utf8.decode(response.bodyBytes));
      return data.cast<Map<String, dynamic>>();
    } else {
      throw Exception('Failed to fetch payment accounts: ${response.body}');
    }
  }

  Future<PayrollModel> markPayrollPaid(
    int payrollId, {
    DateTime? paidDate,
    int? voucherId,
    int? paymentAccountId, // ✅ حساب الدفع (نقدية/بنك/شيك)
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/payroll/$payrollId/mark-paid'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(
        {
          'paid_date': paidDate?.toIso8601String().split('T').first,
          'voucher_id': voucherId,
          'payment_account_id': paymentAccountId, // ✅ إرسال حساب الدفع
        }..removeWhere((key, value) => value == null),
      ),
    );

    if (response.statusCode == 200) {
      return PayrollModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to mark payroll as paid: ${response.body}');
    }
  }

  // ---------------------------------------------------------------------------
  // Attendance API
  // ---------------------------------------------------------------------------

  Future<List<AttendanceModel>> getAttendance({
    int? employeeId,
    DateTime? startDate,
    DateTime? endDate,
    String? status,
  }) async {
    final queryParameters = <String, String>{};
    if (employeeId != null) {
      queryParameters['employee_id'] = employeeId.toString();
    }
    if (startDate != null) {
      queryParameters['start_date'] = startDate
          .toIso8601String()
          .split('T')
          .first;
    }
    if (endDate != null) {
      queryParameters['end_date'] = endDate.toIso8601String().split('T').first;
    }
    if (status != null && status.isNotEmpty) {
      queryParameters['status'] = status;
    }

    final uri = Uri.parse(
      '$_baseUrl/attendance',
    ).replace(queryParameters: queryParameters);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      final raw = json.decode(utf8.decode(response.bodyBytes)) as List<dynamic>;
      return raw
          .map((e) => AttendanceModel.fromJson(e as Map<String, dynamic>))
          .toList();
    } else {
      throw Exception('Failed to load attendance list: ${response.body}');
    }
  }

  Future<AttendanceModel> createAttendance(Map<String, dynamic> payload) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/attendance'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(_normalizePayload(payload)),
    );

    if (response.statusCode == 201) {
      return AttendanceModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to create attendance record: ${response.body}');
    }
  }

  Future<AttendanceModel> updateAttendance(
    int attendanceId,
    Map<String, dynamic> payload,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/attendance/$attendanceId'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(_normalizePayload(payload)),
    );

    if (response.statusCode == 200) {
      return AttendanceModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to update attendance record: ${response.body}');
    }
  }

  Future<void> deleteAttendance(int attendanceId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/attendance/$attendanceId'),
    );
    if (response.statusCode != 200) {
      throw Exception('Failed to delete attendance record: ${response.body}');
    }
  }

  // ---------------------------------------------------------------------------
  // SafeBox API (إدارة الخزائن)
  // ---------------------------------------------------------------------------

  /// الحصول على جميع الخزائن أو حسب النوع
  Future<List<SafeBoxModel>> getSafeBoxes({
    String? safeType,
    bool? isActive,
    int? karat,
    bool includeAccount = false,
    bool includeBalance = false,
  }) async {
    final queryParams = <String, String>{};
    if (safeType != null) queryParams['safe_type'] = safeType;
    if (isActive != null) queryParams['is_active'] = isActive.toString();
    if (karat != null) queryParams['karat'] = karat.toString();
    if (includeAccount) queryParams['include_account'] = 'true';
    if (includeBalance) queryParams['include_balance'] = 'true';

    final uri = Uri.parse(
      '$_baseUrl/safe-boxes',
    ).replace(queryParameters: queryParams);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      final List<dynamic> data = json.decode(utf8.decode(response.bodyBytes));
      return data
          .map((json) => SafeBoxModel.fromJson(json as Map<String, dynamic>))
          .toList();
    } else {
      throw Exception('Failed to load safe boxes: ${response.body}');
    }
  }

  /// الحصول على خزينة محددة
  Future<SafeBoxModel> getSafeBox(int id, {bool includeBalance = true}) async {
    final queryParams = <String, String>{};
    if (includeBalance) queryParams['include_balance'] = 'true';
    queryParams['include_account'] = 'true';

    final uri = Uri.parse(
      '$_baseUrl/safe-boxes/$id',
    ).replace(queryParameters: queryParams);
    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return SafeBoxModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to load safe box: ${response.body}');
    }
  }

  /// إنشاء خزينة جديدة
  Future<SafeBoxModel> createSafeBox(SafeBoxModel safeBox) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/safe-boxes'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(safeBox.toJson()),
    );

    if (response.statusCode == 201) {
      return SafeBoxModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to create safe box: ${response.body}');
    }
  }

  /// تحديث خزينة
  Future<SafeBoxModel> updateSafeBox(int id, SafeBoxModel safeBox) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/safe-boxes/$id'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(safeBox.toJson()),
    );

    if (response.statusCode == 200) {
      return SafeBoxModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to update safe box: ${response.body}');
    }
  }

  /// حذف خزينة
  Future<void> deleteSafeBox(int id) async {
    final response = await http.delete(Uri.parse('$_baseUrl/safe-boxes/$id'));
    if (response.statusCode != 200) {
      throw Exception('Failed to delete safe box: ${response.body}');
    }
  }

  /// الحصول على الخزينة الافتراضية حسب النوع
  Future<SafeBoxModel> getDefaultSafeBox(String safeType) async {
    final response = await http.get(
      Uri.parse(
        '$_baseUrl/safe-boxes/default/$safeType?include_balance=true&include_account=true',
      ),
    );

    if (response.statusCode == 200) {
      return SafeBoxModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to load default safe box: ${response.body}');
    }
  }

  /// الحصول على خزينة الذهب حسب العيار
  Future<SafeBoxModel> getGoldSafeBox(int karat) async {
    final response = await http.get(
      Uri.parse(
        '$_baseUrl/safe-boxes/gold/$karat?include_balance=true&include_account=true',
      ),
    );

    if (response.statusCode == 200) {
      return SafeBoxModel.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
      );
    } else {
      throw Exception('Failed to load gold safe box: ${response.body}');
    }
  }

  /// الحصول على خزائن الدفع النشطة (نقدي + بنكي)
  Future<List<SafeBoxModel>> getPaymentSafeBoxes() async {
    final safeBoxes = await getSafeBoxes(
      isActive: true,
      includeAccount: true,
      includeBalance: true,
    );

    // فلترة الخزائن النقدية والبنكية فقط
    return safeBoxes
        .where((sb) => sb.safeType == 'cash' || sb.safeType == 'bank')
        .toList();
  }

  Map<String, dynamic> _normalizePayload(Map<String, dynamic> payload) {
    final normalized = <String, dynamic>{};
    payload.forEach((key, value) {
      if (value is DateTime) {
        normalized[key] = value.toIso8601String();
      } else if (value is bool) {
        normalized[key] = value;
      } else {
        normalized[key] = value;
      }
    });
    normalized.removeWhere((key, value) => value == null);
    return normalized;
  }

  // Generic HTTP Methods
  Future<dynamic> get(String endpoint) async {
    final response = await http.get(Uri.parse('$_baseUrl$endpoint'));
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('GET request failed: ${response.body}');
    }
  }

  Future<dynamic> post(String endpoint, Map<String, dynamic> data) async {
    final response = await http.post(
      Uri.parse('$_baseUrl$endpoint'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(data),
    );
    if (response.statusCode == 200 || response.statusCode == 201) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('POST request failed: ${response.body}');
    }
  }

  Future<dynamic> put(String endpoint, Map<String, dynamic> data) async {
    final response = await http.put(
      Uri.parse('$_baseUrl$endpoint'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode(data),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('PUT request failed: ${response.body}');
    }
  }

  Future<void> delete(String endpoint) async {
    final response = await http.delete(Uri.parse('$_baseUrl$endpoint'));
    if (response.statusCode != 200 && response.statusCode != 204) {
      throw Exception('DELETE request failed: ${response.body}');
    }
  }

  // =========================================
  // Posting Management Methods
  // =========================================

  /// Get posting statistics (no auth required)
  Future<Map<String, dynamic>> getPostingStats() async {
    final response = await http.get(
      Uri.parse('$_baseUrl/posting/stats'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load posting stats');
    }
  }

  /// Get unposted invoices
  Future<Map<String, dynamic>> getUnpostedInvoices() async {
    final token = await _requireAuthToken();
    
    final response = await http.get(
      Uri.parse('$_baseUrl/invoices/unposted'),
      headers: _jsonHeaders(token: token),
    );
    
    if (response.statusCode == 401) {
      throw Exception('انتهت صلاحية الجلسة. الرجاء تسجيل الدخول مرة أخرى');
    } else if (response.statusCode == 403) {
      throw Exception('ليس لديك صلاحية الوصول لهذه الميزة');
    } else if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final errorData = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(errorData['message'] ?? 'فشل تحميل الفواتير غير المرحلة');
    }
  }

  /// Get posted invoices
  Future<Map<String, dynamic>> getPostedInvoices() async {
    final token = await _requireAuthToken();
    
    final response = await http.get(
      Uri.parse('$_baseUrl/invoices/posted'),
      headers: _jsonHeaders(token: token),
    );
    
    if (response.statusCode == 401) {
      throw Exception('انتهت صلاحية الجلسة. الرجاء تسجيل الدخول مرة أخرى');
    } else if (response.statusCode == 403) {
      throw Exception('ليس لديك صلاحية الوصول لهذه الميزة');
    } else if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final errorData = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(errorData['message'] ?? 'فشل تحميل الفواتير المرحلة');
    }
  }

  /// Get unposted journal entries
  Future<Map<String, dynamic>> getUnpostedJournalEntries() async {
    final token = await _requireAuthToken();
    
    final response = await http.get(
      Uri.parse('$_baseUrl/journal-entries/unposted'),
      headers: _jsonHeaders(token: token),
    );
    
    if (response.statusCode == 401) {
      throw Exception('انتهت صلاحية الجلسة. الرجاء تسجيل الدخول مرة أخرى');
    } else if (response.statusCode == 403) {
      throw Exception('ليس لديك صلاحية الوصول لهذه الميزة');
    } else if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final errorData = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(errorData['message'] ?? 'فشل تحميل القيود غير المرحلة');
    }
  }

  /// Get posted journal entries
  Future<Map<String, dynamic>> getPostedJournalEntries() async {
    final token = await _requireAuthToken();
    
    final response = await http.get(
      Uri.parse('$_baseUrl/journal-entries/posted'),
      headers: _jsonHeaders(token: token),
    );
    
    if (response.statusCode == 401) {
      throw Exception('انتهت صلاحية الجلسة. الرجاء تسجيل الدخول مرة أخرى');
    } else if (response.statusCode == 403) {
      throw Exception('ليس لديك صلاحية الوصول لهذه الميزة');
    } else if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final errorData = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(errorData['message'] ?? 'فشل تحميل القيود المرحلة');
    }
  }

  /// Post a single invoice
  Future<Map<String, dynamic>> postInvoice(int invoiceId, String postedBy) async {
    final token = await _requireAuthToken();
    
    final response = await http.post(
      Uri.parse('$_baseUrl/invoices/post/$invoiceId'),
      headers: _jsonHeaders(token: token),
      body: json.encode({'posted_by': postedBy}),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to post invoice: ${response.body}');
    }
  }

  /// Post multiple invoices
  Future<Map<String, dynamic>> postInvoicesBatch(
    List<int> invoiceIds,
    String postedBy,
  ) async {
    final token = await _requireAuthToken();
    
    final response = await http.post(
      Uri.parse('$_baseUrl/invoices/post-batch'),
      headers: _jsonHeaders(token: token),
      body: json.encode({
        'invoice_ids': invoiceIds,
        'posted_by': postedBy,
      }),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to post invoices batch: ${response.body}');
    }
  }

  /// Unpost an invoice
  Future<Map<String, dynamic>> unpostInvoice(int invoiceId) async {
    final token = await _requireAuthToken();
    
    final response = await http.post(
      Uri.parse('$_baseUrl/invoices/unpost/$invoiceId'),
      headers: _jsonHeaders(token: token),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to unpost invoice: ${response.body}');
    }
  }

  /// Post a single journal entry
  Future<Map<String, dynamic>> postJournalEntry(
    int entryId,
    String postedBy,
  ) async {
    final token = await _requireAuthToken();
    
    final response = await http.post(
      Uri.parse('$_baseUrl/journal-entries/post/$entryId'),
      headers: _jsonHeaders(token: token),
      body: json.encode({'posted_by': postedBy}),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to post journal entry: ${response.body}');
    }
  }

  /// Post multiple journal entries
  Future<Map<String, dynamic>> postJournalEntriesBatch(
    List<int> entryIds,
    String postedBy,
  ) async {
    final token = await _requireAuthToken();
    
    final response = await http.post(
      Uri.parse('$_baseUrl/journal-entries/post-batch'),
      headers: _jsonHeaders(token: token),
      body: json.encode({
        'entry_ids': entryIds,
        'posted_by': postedBy,
      }),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to post journal entries batch: ${response.body}');
    }
  }

  /// Unpost a journal entry
  Future<Map<String, dynamic>> unpostJournalEntry(int entryId) async {
    final token = await _requireAuthToken();
    
    final response = await http.post(
      Uri.parse('$_baseUrl/journal-entries/unpost/$entryId'),
      headers: _jsonHeaders(token: token),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to unpost journal entry: ${response.body}');
    }
  }

  // ==========================================
  // 📋 Audit Log APIs
  // ==========================================

  /// Get audit logs with optional filters
  Future<Map<String, dynamic>> getAuditLogs({
    int limit = 100,
    String? userName,
    String? action,
    String? entityType,
    int? entityId,
    bool? success,
    String? fromDate,
    String? toDate,
  }) async {
    final queryParams = <String, String>{
      'limit': limit.toString(),
    };
    
    if (userName != null) queryParams['user_name'] = userName;
    if (action != null) queryParams['action'] = action;
    if (entityType != null) queryParams['entity_type'] = entityType;
    if (entityId != null) queryParams['entity_id'] = entityId.toString();
    if (success != null) queryParams['success'] = success.toString();
    if (fromDate != null) queryParams['from_date'] = fromDate;
    if (toDate != null) queryParams['to_date'] = toDate;
    
    final token = await _requireAuthToken();
    final uri = Uri.parse('$_baseUrl/audit-logs').replace(queryParameters: queryParams);
    final response = await http.get(
      uri,
      headers: _jsonHeaders(token: token),
    );
    
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load audit logs');
    }
  }

  /// Get audit log detail
  Future<Map<String, dynamic>> getAuditLogDetail(int logId) async {
    final token = await _requireAuthToken();
    
    final response = await http.get(
      Uri.parse('$_baseUrl/audit-logs/$logId'),
      headers: _jsonHeaders(token: token),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load audit log detail');
    }
  }

  /// Get audit logs by entity
  Future<Map<String, dynamic>> getAuditLogsByEntity(
    String entityType,
    int entityId,
  ) async {
    final token = await _requireAuthToken();
    
    final response = await http.get(
      Uri.parse('$_baseUrl/audit-logs/entity/$entityType/$entityId'),
      headers: _jsonHeaders(token: token),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load audit logs by entity');
    }
  }

  /// Get audit logs by user
  Future<Map<String, dynamic>> getAuditLogsByUser(
    String userName, {
    int limit = 100,
  }) async {
    final token = await _requireAuthToken();
    
    final uri = Uri.parse('$_baseUrl/audit-logs/user/$userName')
        .replace(queryParameters: {'limit': limit.toString()});
    final response = await http.get(
      uri,
      headers: _jsonHeaders(token: token),
    );
    
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load audit logs by user');
    }
  }

  /// Get failed audit logs
  Future<Map<String, dynamic>> getFailedAuditLogs({int limit = 50}) async {
    final token = await _requireAuthToken();
    
    final uri = Uri.parse('$_baseUrl/audit-logs/failed')
        .replace(queryParameters: {'limit': limit.toString()});
    final response = await http.get(
      uri,
      headers: _jsonHeaders(token: token),
    );
    
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load failed audit logs');
    }
  }

  /// Get audit log statistics
  Future<Map<String, dynamic>> getAuditStats() async {
    final token = await _requireAuthToken();
    
    final response = await http.get(
      Uri.parse('$_baseUrl/audit-logs/stats'),
      headers: _jsonHeaders(token: token),
    );
    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load audit stats');
    }
  }

  // ==========================================
  // 🔐 Authentication & Authorization Methods
  // ==========================================

  /// Login user with JWT authentication and get token
  Future<Map<String, dynamic>> loginWithToken(String username, String password) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json; charset=UTF-8'},
      body: json.encode({
        'username': username,
        'password': password,
      }),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل تسجيل الدخول');
    }
  }

  /// Get current user info
  Future<Map<String, dynamic>> getCurrentUser(String token) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/auth/me'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to get current user');
    }
  }

  /// Change password
  Future<Map<String, dynamic>> changePassword(
    String token,
    String oldPassword,
    String newPassword,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/auth/change-password'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
      body: json.encode({
        'old_password': oldPassword,
        'new_password': newPassword,
      }),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل تغيير كلمة المرور');
    }
  }

  /// Get all roles
  Future<Map<String, dynamic>> getRoles(String token, {bool includeUsers = false}) async {
    final uri = Uri.parse('$_baseUrl/roles').replace(
      queryParameters: {'include_users': includeUsers.toString()},
    );
    
    final response = await http.get(
      uri,
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load roles');
    }
  }

  /// Get role by ID
  Future<Map<String, dynamic>> getRole(String token, int roleId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/roles/$roleId'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load role');
    }
  }

  /// Create new role
  Future<Map<String, dynamic>> createRole(
    String token,
    String name,
    String nameAr,
    String? description,
    List<int> permissionIds,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/roles'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
      body: json.encode({
        'name': name,
        'name_ar': nameAr,
        'description': description,
        'permission_ids': permissionIds,
      }),
    );

    if (response.statusCode == 201) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل إنشاء الدور');
    }
  }

  /// Update role
  Future<Map<String, dynamic>> updateRole(
    String token,
    int roleId,
    Map<String, dynamic> roleData,
  ) async {
    final response = await http.put(
      Uri.parse('$_baseUrl/roles/$roleId'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
      body: json.encode(roleData),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل تحديث الدور');
    }
  }

  /// Delete role
  Future<Map<String, dynamic>> deleteRole(String token, int roleId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/roles/$roleId'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل حذف الدور');
    }
  }

  /// Get all permissions
  Future<Map<String, dynamic>> getPermissions(String token, {String? category}) async {
    final uri = category != null
        ? Uri.parse('$_baseUrl/permissions').replace(
            queryParameters: {'category': category},
          )
        : Uri.parse('$_baseUrl/permissions');

    final response = await http.get(
      uri,
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load permissions');
    }
  }

  /// Manage user roles (add or remove)
  Future<Map<String, dynamic>> manageUserRoles(
    String token,
    int userId,
    String action, // 'add' or 'remove'
    List<int> roleIds,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/users/$userId/roles'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
      body: json.encode({
        'action': action,
        'role_ids': roleIds,
      }),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل إدارة أدوار المستخدم');
    }
  }

  /// Get user permissions
  Future<Map<String, dynamic>> getUserPermissions(String token, int userId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/users/$userId/permissions'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      throw Exception('Failed to load user permissions');
    }
  }

  // ==========================================
  // 👤 إدارة المستخدمين (JWT)
  // ==========================================

  /// List users with JWT authentication
  Future<Map<String, dynamic>> listUsersWithAuth(
    String token, {
    String? search,
    bool? isActive,
    String? role,
    int page = 1,
    int perPage = 50,
  }) async {
    final queryParams = <String, String>{
      'page': page.toString(),
      'per_page': perPage.toString(),
    };

    if (search != null && search.isNotEmpty) {
      queryParams['search'] = search;
    }
    if (isActive != null) {
      queryParams['is_active'] = isActive.toString();
    }
    if (role != null && role.isNotEmpty) {
      queryParams['role'] = role;
    }

    final uri = Uri.parse('$_baseUrl/users').replace(queryParameters: queryParams);

    final response = await http.get(
      uri,
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل تحميل المستخدمين');
    }
  }

  /// Get single user by ID with JWT
  Future<Map<String, dynamic>> getUserById(String token, int userId) async {
    final response = await http.get(
      Uri.parse('$_baseUrl/users/$userId'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل تحميل المستخدم');
    }
  }

  /// Create new user with JWT
  Future<Map<String, dynamic>> createUserWithAuth(
    String token, {
    required String username,
    required String password,
    required String fullName,
    bool isAdmin = false,
    bool isActive = true,
    List<int>? roleIds,
  }) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/users'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
      body: json.encode({
        'username': username,
        'password': password,
        'full_name': fullName,
        'is_admin': isAdmin,
        'is_active': isActive,
        if (roleIds != null) 'role_ids': roleIds,
      }),
    );

    if (response.statusCode == 201) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل إنشاء المستخدم');
    }
  }

  /// Update user with JWT
  Future<Map<String, dynamic>> updateUserWithAuth(
    String token,
    int userId, {
    String? fullName,
    bool? isAdmin,
    bool? isActive,
    String? password,
  }) async {
    final body = <String, dynamic>{};
    if (fullName != null) body['full_name'] = fullName;
    if (isAdmin != null) body['is_admin'] = isAdmin;
    if (isActive != null) body['is_active'] = isActive;
    if (password != null && password.isNotEmpty) body['password'] = password;

    final response = await http.put(
      Uri.parse('$_baseUrl/users/$userId'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
      body: json.encode(body),
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل تحديث المستخدم');
    }
  }

  /// Delete user with JWT
  Future<Map<String, dynamic>> deleteUserWithAuth(String token, int userId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/users/$userId'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل حذف المستخدم');
    }
  }

  /// Toggle user active status with JWT
  Future<Map<String, dynamic>> toggleUserActiveWithAuth(
    String token,
    int userId,
  ) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/users/$userId/toggle-active'),
      headers: {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': 'Bearer $token',
      },
    );

    if (response.statusCode == 200) {
      return json.decode(utf8.decode(response.bodyBytes));
    } else {
      final error = json.decode(utf8.decode(response.bodyBytes));
      throw Exception(error['message'] ?? 'فشل تغيير حالة المستخدم');
    }
  }

  // ==========================================
  // 🔐 Helpers: Token Handling
  // ==========================================

  Future<String> _requireAuthToken() async {
    final prefs = await SharedPreferences.getInstance();
    final jwtToken = prefs.getString('jwt_token');
    if (jwtToken != null && jwtToken.isNotEmpty) {
      return jwtToken;
    }

    final legacyToken = prefs.getString('auth_token');
    if (legacyToken != null && legacyToken.isNotEmpty) {
      // مهاجرة التوكن القديم إلى المفتاح الجديد لضمان التوافق
      await prefs.setString('jwt_token', legacyToken);
      return legacyToken;
    }

    throw Exception('يجب تسجيل الدخول أولاً. الرجاء تسجيل الخروج والدخول مرة أخرى');
  }

  Map<String, String> _jsonHeaders({String? token}) {
    return {
      'Content-Type': 'application/json; charset=UTF-8',
      if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
    };
  }
}
