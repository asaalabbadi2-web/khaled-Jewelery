// ignore_for_file: non_constant_identifier_names

library;


class InventoryBucket {
  final int? branchId;
  final int? categoryId;
  final double karat;
  final double balance;
  final int? snapshotMaxLedgerId;
  final DateTime? updatedAt;

  const InventoryBucket({
    required this.branchId,
    required this.categoryId,
    required this.karat,
    required this.balance,
    this.snapshotMaxLedgerId,
    this.updatedAt,
  });

  factory InventoryBucket.fromJson(Map<String, dynamic> j) => InventoryBucket(
        branchId: j['branch_id'] as int?,
        categoryId: j['category_id'] as int?,
        karat: (j['karat'] as num).toDouble(),
        balance: (j['balance'] as num).toDouble(),
        snapshotMaxLedgerId: j['snapshot_max_ledger_id'] as int?,
        updatedAt: j['updated_at'] != null
            ? DateTime.tryParse(j['updated_at'] as String)
            : null,
      );
}

class InventoryBalanceSummary {
  final List<BranchTotal> byBranch;
  final List<KaratTotal> byKarat;
  final double grandTotalWeight;
  final DateTime generatedAt;

  const InventoryBalanceSummary({
    required this.byBranch,
    required this.byKarat,
    required this.grandTotalWeight,
    required this.generatedAt,
  });

  factory InventoryBalanceSummary.fromJson(Map<String, dynamic> j) =>
      InventoryBalanceSummary(
        byBranch: (j['by_branch'] as List)
            .map((e) => BranchTotal.fromJson(e as Map<String, dynamic>))
            .toList(),
        byKarat: (j['by_karat'] as List)
            .map((e) => KaratTotal.fromJson(e as Map<String, dynamic>))
            .toList(),
        grandTotalWeight: (j['grand_total_weight'] as num).toDouble(),
        generatedAt: DateTime.parse(j['generated_at'] as String),
      );
}

class BranchTotal {
  final int? branchId;
  final String branchName;
  final double totalWeight;
  const BranchTotal(
      {required this.branchId,
      required this.branchName,
      required this.totalWeight});
  factory BranchTotal.fromJson(Map<String, dynamic> j) => BranchTotal(
        branchId: j['branch_id'] as int?,
        branchName: j['branch_name'] as String? ?? '—',
        totalWeight: (j['total_weight'] as num).toDouble(),
      );
}

class KaratTotal {
  final double karat;
  final double totalWeight;
  const KaratTotal({required this.karat, required this.totalWeight});
  factory KaratTotal.fromJson(Map<String, dynamic> j) => KaratTotal(
        karat: (j['karat'] as num).toDouble(),
        totalWeight: (j['total_weight'] as num).toDouble(),
      );
}

// ── Count Sessions ────────────────────────────────────────────────────────────

class CountSession {
  final int id;
  final int? branchId;
  final String status; // open | counting | closed | approved | cancelled
  final String sessionType; // periodic | opening
  final bool blindCount;
  final int? snapshotLedgerId;
  final String? openedBy;
  final DateTime? openedAt;
  final DateTime? closedAt;
  final String? approvedBy;
  final DateTime? approvedAt;
  final String? notes;
  final List<CountLine> lines;

  const CountSession({
    required this.id,
    required this.branchId,
    required this.status,
    this.sessionType = 'periodic',
    required this.blindCount,
    this.snapshotLedgerId,
    this.openedBy,
    this.openedAt,
    this.closedAt,
    this.approvedBy,
    this.approvedAt,
    this.notes,
    this.lines = const [],
  });

  bool get isActive => status == 'open' || status == 'counting';
  bool get canClose => status == 'counting' || status == 'open';
  bool get canApprove => status == 'closed';
  bool get isOpening => sessionType == 'opening';

  factory CountSession.fromJson(Map<String, dynamic> j) => CountSession(
        id: j['id'] as int,
        branchId: j['branch_id'] as int?,
        status: j['status'] as String,
        sessionType: j['session_type'] as String? ?? 'periodic',
        blindCount: j['blind_count'] as bool? ?? true,
        snapshotLedgerId: j['snapshot_ledger_id'] as int?,
        openedBy: j['opened_by'] as String?,
        openedAt: j['opened_at'] != null
            ? DateTime.tryParse(j['opened_at'] as String)
            : null,
        closedAt: j['closed_at'] != null
            ? DateTime.tryParse(j['closed_at'] as String)
            : null,
        approvedBy: j['approved_by'] as String?,
        approvedAt: j['approved_at'] != null
            ? DateTime.tryParse(j['approved_at'] as String)
            : null,
        notes: j['notes'] as String?,
        lines: (j['lines'] as List? ?? [])
            .map((e) => CountLine.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class CountLine {
  final int id;
  final int sessionId;
  final int? branchId;
  final int? categoryId;
  final String? categoryName;
  final double karat;
  // null when blind_count=true and session is still open/counting
  final double? expectedWeight;
  final double? countedWeight;
  final double? variance;
  final String? countedBy;
  final DateTime? countedAt;
  final String? notes;

  // UI-only state — not from API
  final CountLineStatus uiStatus;

  const CountLine({
    required this.id,
    required this.sessionId,
    required this.branchId,
    required this.categoryId,
    this.categoryName,
    required this.karat,
    this.expectedWeight,
    this.countedWeight,
    this.variance,
    this.countedBy,
    this.countedAt,
    this.notes,
    this.uiStatus = CountLineStatus.idle,
  });

  bool get isCounted => countedWeight != null;

  CountLine copyWith({
    double? countedWeight,
    double? variance,
    double? expectedWeight,
    CountLineStatus? uiStatus,
    String? countedBy,
    DateTime? countedAt,
  }) =>
      CountLine(
        id: id,
        sessionId: sessionId,
        branchId: branchId,
        categoryId: categoryId,
        categoryName: categoryName,
        karat: karat,
        expectedWeight: expectedWeight ?? this.expectedWeight,
        countedWeight: countedWeight ?? this.countedWeight,
        variance: variance ?? this.variance,
        countedBy: countedBy ?? this.countedBy,
        countedAt: countedAt ?? this.countedAt,
        notes: notes,
        uiStatus: uiStatus ?? this.uiStatus,
      );

  factory CountLine.fromJson(Map<String, dynamic> j) => CountLine(
        id: j['id'] as int,
        sessionId: j['session_id'] as int,
        branchId: j['branch_id'] as int?,
        categoryId: j['category_id'] as int?,
        categoryName: j['category_name'] as String?,
        karat: (j['karat'] as num).toDouble(),
        expectedWeight: j['expected_weight'] != null
            ? (j['expected_weight'] as num).toDouble()
            : null,
        countedWeight: j['counted_weight'] != null
            ? (j['counted_weight'] as num).toDouble()
            : null,
        variance: j['variance'] != null
            ? (j['variance'] as num).toDouble()
            : null,
        countedBy: j['counted_by'] as String?,
        countedAt: j['counted_at'] != null
            ? DateTime.tryParse(j['counted_at'] as String)
            : null,
        notes: j['notes'] as String?,
      );
}

enum CountLineStatus { idle, saving, saved, failed }

class AdjustmentReason {
  final String code;
  final String label;
  final bool requiresNote;
  const AdjustmentReason({
    required this.code,
    required this.label,
    this.requiresNote = false,
  });
  factory AdjustmentReason.fromJson(Map<String, dynamic> j) => AdjustmentReason(
        code: j['code'] as String,
        label: j['label'] as String,
        requiresNote: (j['requires_note'] as bool?) ?? false,
      );

  static const List<AdjustmentReason> fallback = [
    AdjustmentReason(code: 'COUNT_ERROR', label: 'خطأ عدّ'),
    AdjustmentReason(code: 'LOSS',        label: 'فاقد',        requiresNote: true),
    AdjustmentReason(code: 'NEW_ITEM',    label: 'قطعة جديدة'),
    AdjustmentReason(code: 'OTHER',       label: 'سبب آخر',     requiresNote: true),
  ];
}

// ── Adjustment ────────────────────────────────────────────────────────────────

class InventoryAdjustment {
  final int id;
  final int? branchId;
  final String adjustmentType;
  final String status;
  final String? reasonCode;
  final String? note;
  final String? createdBy;
  final DateTime? createdAt;
  final String? postedBy;
  final DateTime? postedAt;
  final List<AdjustmentLine> lines;

  const InventoryAdjustment({
    required this.id,
    required this.branchId,
    required this.adjustmentType,
    required this.status,
    this.reasonCode,
    this.note,
    this.createdBy,
    this.createdAt,
    this.postedBy,
    this.postedAt,
    this.lines = const [],
  });

  factory InventoryAdjustment.fromJson(Map<String, dynamic> j) =>
      InventoryAdjustment(
        id: j['id'] as int,
        branchId: j['branch_id'] as int?,
        adjustmentType: j['adjustment_type'] as String? ?? 'manual',
        status: j['status'] as String? ?? 'draft',
        reasonCode: (j['reason_code'] ?? j['reason']) as String?,
        note: j['note'] as String?,
        createdBy: j['created_by'] as String?,
        createdAt: j['created_at'] != null
            ? DateTime.tryParse(j['created_at'] as String)
            : null,
        postedBy: j['posted_by'] as String?,
        postedAt: j['posted_at'] != null
            ? DateTime.tryParse(j['posted_at'] as String)
            : null,
        lines: (j['lines'] as List? ?? [])
            .map((e) => AdjustmentLine.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class AdjustmentLine {
  final int id;
  final int? categoryId;
  final double karat;
  final double expectedWeight;
  final double countedWeight;
  final double varianceWeight;

  const AdjustmentLine({
    required this.id,
    required this.categoryId,
    required this.karat,
    required this.expectedWeight,
    required this.countedWeight,
    required this.varianceWeight,
  });

  factory AdjustmentLine.fromJson(Map<String, dynamic> j) => AdjustmentLine(
        id: j['id'] as int,
        categoryId: j['category_id'] as int?,
        karat: (j['karat'] as num).toDouble(),
        expectedWeight: (j['expected_weight'] as num).toDouble(),
        countedWeight: (j['counted_weight'] as num).toDouble(),
        varianceWeight: (j['variance_weight'] as num).toDouble(),
      );
}

// ── Reconciliation ────────────────────────────────────────────────────────────

class ReconciliationReport {
  final DateTime generatedAt;
  final bool glAvailable;
  final bool isClean;
  final int totalBuckets;
  final int mismatchCount;
  final int countDriftBuckets;
  final List<ReconciliationRow> rows;

  const ReconciliationReport({
    required this.generatedAt,
    required this.glAvailable,
    required this.isClean,
    required this.totalBuckets,
    required this.mismatchCount,
    required this.countDriftBuckets,
    required this.rows,
  });

  factory ReconciliationReport.fromJson(Map<String, dynamic> j) =>
      ReconciliationReport(
        generatedAt: DateTime.parse(j['generated_at'] as String),
        glAvailable: j['gl_available'] as bool? ?? false,
        isClean: j['is_clean'] as bool? ?? true,
        totalBuckets: j['total_buckets'] as int? ?? 0,
        mismatchCount: j['mismatches'] as int? ?? 0,
        countDriftBuckets: j['count_drift_buckets'] as int? ?? 0,
        rows: (j['rows'] as List? ?? [])
            .map((e) => ReconciliationRow.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class ReconciliationRow {
  final int? branchId;
  final int? categoryId;
  final double karat;
  final double ledgerSum;
  final double balance;
  final double? lastCountWeight;
  final double? lastCountVariance;
  final DateTime? lastCountAt;
  final bool ledgerVsBalanceOk;
  final bool? ledgerVsCountOk;

  const ReconciliationRow({
    required this.branchId,
    required this.categoryId,
    required this.karat,
    required this.ledgerSum,
    required this.balance,
    required this.ledgerVsBalanceOk,
    this.lastCountWeight,
    this.lastCountVariance,
    this.lastCountAt,
    this.ledgerVsCountOk,
  });

  bool get hasMismatch => !ledgerVsBalanceOk;
  bool get hasCountDrift => ledgerVsCountOk == false;

  factory ReconciliationRow.fromJson(Map<String, dynamic> j) =>
      ReconciliationRow(
        branchId: j['branch_id'] as int?,
        categoryId: j['category_id'] as int?,
        karat: (j['karat'] as num).toDouble(),
        ledgerSum: (j['ledger_sum'] as num).toDouble(),
        balance: (j['balance'] as num).toDouble(),
        ledgerVsBalanceOk: j['ledger_vs_balance_ok'] as bool? ?? true,
        lastCountWeight: j['last_count_weight'] != null
            ? (j['last_count_weight'] as num).toDouble()
            : null,
        lastCountVariance: j['last_count_variance'] != null
            ? (j['last_count_variance'] as num).toDouble()
            : null,
        lastCountAt: j['last_count_at'] != null
            ? DateTime.tryParse(j['last_count_at'] as String)
            : null,
        ledgerVsCountOk: j['ledger_vs_count_ok'] as bool?,
      );
}

// ── Health ────────────────────────────────────────────────────────────────────

class HealthReport {
  final bool hasIssues;
  final DateTime generatedAt;
  final List<HealthMetric> metrics;

  const HealthReport({
    required this.hasIssues,
    required this.generatedAt,
    required this.metrics,
  });

  HealthMetric? metric(String key) =>
      metrics.where((m) => m.key == key).firstOrNull;

  factory HealthReport.fromJson(Map<String, dynamic> j) => HealthReport(
        hasIssues: j['has_issues'] as bool? ?? false,
        generatedAt: j['generated_at'] != null
            ? DateTime.parse(j['generated_at'] as String)
            : DateTime.now(),
        metrics: (j['metrics'] as List? ?? [])
            .map((e) => HealthMetric.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class HealthMetric {
  final String key;
  final String label;
  final String detail;
  final bool ok;

  const HealthMetric(
      {required this.key,
      required this.label,
      required this.detail,
      required this.ok});

  factory HealthMetric.fromJson(Map<String, dynamic> j) => HealthMetric(
        key: j['key'] as String,
        label: j['label'] as String,
        detail: j['detail'] as String,
        ok: j['ok'] as bool? ?? true,
      );
}
