import 'dart:convert';
import '../api_service.dart';
import '../models/inventory_models.dart';

/// Inventory Engine API client.
///
/// All methods throw [InventoryApiException] on non-2xx responses.
/// Callers should catch and display the [message] field.
class InventoryService {
  InventoryService(this._api);
  final ApiService _api;

  // ── Balance ───────────────────────────────────────────────────────────────

  Future<List<InventoryBucket>> getBalance({
    int? branchId,
    int? categoryId,
    double? karat,
  }) async {
    final params = <String, String>{};
    if (branchId != null) params['branch_id'] = '$branchId';
    if (categoryId != null) params['category_id'] = '$categoryId';
    if (karat != null) params['karat'] = '$karat';

    final resp = await _api.authedGet('/inventory/balance', queryParams: params);
    _check(resp, 'تعذّر تحميل الأرصدة');
    final list = jsonDecode(resp.body) as List;
    return list
        .map((e) => InventoryBucket.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<InventoryBalanceSummary> getBalanceSummary() async {
    final resp = await _api.authedGet('/inventory/balance/summary');
    _check(resp, 'تعذّر تحميل ملخص الأرصدة');
    return InventoryBalanceSummary.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  // ── Count Sessions ────────────────────────────────────────────────────────

  Future<List<CountSession>> listSessions({
    int? branchId,
    String? status,
  }) async {
    final params = <String, String>{};
    if (branchId != null) params['branch_id'] = '$branchId';
    if (status != null) params['status'] = status;

    final resp = await _api.authedGet('/inventory/count', queryParams: params);
    _check(resp, 'تعذّر تحميل جلسات الجرد');
    final list = jsonDecode(resp.body) as List;
    return list
        .map((e) => CountSession.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<CountSession> openSession({
    required int branchId,
    bool blindCount = true,
    String sessionType = 'periodic',
    String? notes,
  }) async {
    final resp = await _api.authedPost(
      '/inventory/count',
      body: jsonEncode({
        'branch_id': branchId,
        'blind_count': blindCount,
        'session_type': sessionType,
        if (notes != null && notes.isNotEmpty) 'notes': notes,
      }),
    );
    _check(resp, 'تعذّر فتح جلسة الجرد');
    return CountSession.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  Future<CountSession> getSession(int sessionId) async {
    final resp = await _api.authedGet('/inventory/count/$sessionId');
    _check(resp, 'تعذّر تحميل جلسة الجرد');
    return CountSession.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  Future<CountLine> recordEntry({
    required int sessionId,
    required int categoryId,
    required double karat,
    required double countedWeight,
  }) async {
    final resp = await _api.authedPut(
      '/inventory/count/$sessionId/entry',
      body: jsonEncode({
        'category_id': categoryId,
        'karat': karat,
        'counted_weight': countedWeight,
      }),
    );
    _check(resp, 'تعذّر حفظ القراءة');
    return CountLine.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  Future<({CountSession session, int uncountedLines})> closeSession(
    int sessionId, {
    bool force = false,
    bool zeroUncounted = false,
  }) async {
    final Map<String, dynamic> body = {};
    if (force) body['force'] = true;
    if (zeroUncounted) body['zero_uncounted'] = true;
    final resp = await _api.authedPost(
      '/inventory/count/$sessionId/close',
      body: body.isNotEmpty ? jsonEncode(body) : null,
    );
    _check(resp, 'تعذّر إغلاق الجلسة');
    final j = jsonDecode(resp.body) as Map<String, dynamic>;
    final warning = j['warning'] as String?;
    final uncounted = warning != null
        ? int.tryParse(RegExp(r'\d+').stringMatch(warning) ?? '0') ?? 0
        : 0;
    return (
      session: CountSession.fromJson(j),
      uncountedLines: uncounted,
    );
  }

  Future<CountSession> cancelSession(int sessionId) async {
    final resp = await _api.authedPost('/inventory/count/$sessionId/cancel');
    _check(resp, 'تعذّر إلغاء الجلسة');
    return CountSession.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  Future<({CountSession session, InventoryAdjustment? adjustment})>
      approveSession(
    int sessionId, {
    String reasonCode = 'OTHER',
    String note = '',
  }) async {
    final body = <String, dynamic>{'reason_code': reasonCode};
    if (note.isNotEmpty) body['note'] = note;
    final resp = await _api.authedPost(
      '/inventory/count/$sessionId/approve',
      body: jsonEncode(body),
    );
    _check(resp, 'تعذّر اعتماد الجلسة');
    final j = jsonDecode(resp.body) as Map<String, dynamic>;
    return (
      session: CountSession.fromJson(j['session'] as Map<String, dynamic>),
      adjustment: j['adjustment'] != null
          ? InventoryAdjustment.fromJson(
              j['adjustment'] as Map<String, dynamic>)
          : null,
    );
  }

  // ── Adjustments ───────────────────────────────────────────────────────────

  Future<InventoryAdjustment> createManualAdjustment({
    required int branchId,
    required String reason,
    required List<Map<String, dynamic>> lines,
    bool autoPost = true,
  }) async {
    final resp = await _api.authedPost(
      '/inventory/adjustment',
      body: jsonEncode({
        'branch_id': branchId,
        'reason': reason,
        'lines': lines,
        'auto_post': autoPost,
      }),
    );
    _check(resp, 'تعذّر إنشاء التسوية');
    return InventoryAdjustment.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  Future<InventoryAdjustment> getAdjustment(int adjustmentId) async {
    final resp = await _api.authedGet('/inventory/adjustment/$adjustmentId');
    _check(resp, 'تعذّر تحميل التسوية');
    return InventoryAdjustment.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  // ── Reports ───────────────────────────────────────────────────────────────

  Future<ReconciliationReport> getReconciliation() async {
    final resp = await _api.authedGet('/inventory/reconciliation');
    _check(resp, 'تعذّر تحميل تقرير المطابقة');
    return ReconciliationReport.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  Future<HealthReport> getHealth() async {
    final resp = await _api.authedGet('/inventory/health');
    _check(resp, 'تعذّر تحميل تقرير الصحة');
    return HealthReport.fromJson(
        jsonDecode(resp.body) as Map<String, dynamic>);
  }

  Future<List<AdjustmentReason>> getAdjustmentReasons() async {
    final resp = await _api.authedGet('/inventory/adjustment-reasons');
    _check(resp, 'تعذّر تحميل أسباب التسوية');
    final list = jsonDecode(resp.body) as List;
    return list
        .map((e) => AdjustmentReason.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  void _check(dynamic resp, String context) {
    if (resp.statusCode >= 200 && resp.statusCode < 300) return;
    String detail = '';
    try {
      final j = jsonDecode(resp.body as String) as Map<String, dynamic>;
      detail = j['error'] as String? ?? '';
    } catch (_) {}
    throw InventoryApiException(
      '$context${detail.isNotEmpty ? ': $detail' : ''}',
      statusCode: resp.statusCode as int,
    );
  }
}

class InventoryApiException implements Exception {
  final String message;
  final int statusCode;
  const InventoryApiException(this.message, {required this.statusCode});
  @override
  String toString() => 'InventoryApiException($statusCode): $message';
}
