import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api_service.dart';
import '../models/inventory_models.dart';
import '../services/inventory_service.dart';
import '../theme/app_theme.dart';
import '../widgets/bucket_balance_card.dart';

/// Screen 2 — Count Session Workspace.
///
/// Design principles enforced here:
///   • Blind count by default: expected_weight hidden while session is open/counting.
///   • Save on blur/Enter only — never on keystroke — prevents partial values in DB.
///   • Per-row status indicator: idle / saving… / ✓ saved / ✗ failed (retry).
///   • counted_by shown per row for concurrent-count awareness.
///   • pull-to-refresh with timestamp for multi-device use without websockets.
///   • Approve dialog shows variance-only rows sorted to top + GL preview stub.
class InventoryCountScreen extends StatefulWidget {
  /// Pass an existing session ID to resume, or null to open the "new session" flow.
  final int? sessionId;

  const InventoryCountScreen({super.key, this.sessionId});

  @override
  State<InventoryCountScreen> createState() => _InventoryCountScreenState();
}

class _InventoryCountScreenState extends State<InventoryCountScreen> {
  final _svc = InventoryService(ApiService());

  CountSession? _session;
  bool _loading = true;
  String? _error;
  DateTime? _lastRefresh;

  // Lines state — maintained locally to avoid full-screen rebuilds on each entry
  late List<_LineState> _lineStates;

  @override
  void initState() {
    super.initState();
    if (widget.sessionId != null) {
      _loadSession(widget.sessionId!);
    } else {
      _showOpenSessionSheet();
    }
  }

  // ── Loading ───────────────────────────────────────────────────────────────

  Future<void> _loadSession(int id) async {
    setState(() { _loading = true; _error = null; });
    try {
      final s = await _svc.getSession(id);
      _applySession(s);
    } on InventoryApiException catch (e) {
      setState(() { _error = e.message; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  void _applySession(CountSession s) {
    setState(() {
      _session = s;
      _lineStates = s.lines.map((l) => _LineState(line: l)).toList();
      _loading = false;
      _lastRefresh = DateTime.now();
    });
  }

  Future<void> _refresh() async {
    if (_session == null) return;
    await _loadSession(_session!.id);
  }

  // ── Open Session Sheet ────────────────────────────────────────────────────

  void _showOpenSessionSheet() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      showModalBottomSheet(
        context: context,
        isScrollControlled: true,
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        builder: (_) => _OpenSessionSheet(
          svc: _svc,
          onOpened: (s) {
            Navigator.pop(context);
            _applySession(s);
          },
          onCancelled: () {
            Navigator.pop(context); // sheet
            Navigator.pop(context); // screen
          },
        ),
      );
    });
  }

  // ── Entry Save (blur / Enter) ─────────────────────────────────────────────

  Future<void> _saveEntry(_LineState ls, double value) async {
    if (_session == null) return;
    if (ls.line.categoryId == null) return;

    setState(() => ls.status = CountLineStatus.saving);
    try {
      final updated = await _svc.recordEntry(
        sessionId: _session!.id,
        categoryId: ls.line.categoryId!,
        karat: ls.line.karat,
        countedWeight: value,
      );
      // Refresh session to pick up status change (open→counting)
      final refreshed = await _svc.getSession(_session!.id);
      setState(() {
        ls.line = updated.copyWith(uiStatus: CountLineStatus.saved);
        ls.status = CountLineStatus.saved;
        _session = refreshed;
        _lastRefresh = DateTime.now();
      });
    } on InventoryApiException catch (e) {
      setState(() => ls.status = CountLineStatus.failed);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.message), backgroundColor: AppColors.error),
        );
      }
    }
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  Future<void> _closeSession() async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('إغلاق الجلسة'),
        content: Text(
          'سيتم إغلاق الجلسة وحساب الفروقات.\n'
          'الأصناف غير المعدودة: ${_lineStates.where((l) => !l.line.isCounted).length}',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('إلغاء')),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(backgroundColor: AppColors.primaryGold),
            child: const Text('إغلاق', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
    if (confirm != true || !mounted) return;

    setState(() => _loading = true);
    try {
      final s = await _svc.closeSession(_session!.id);
      _applySession(s);
    } on InventoryApiException catch (e) {
      setState(() => _loading = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.message), backgroundColor: AppColors.error),
        );
      }
    }
  }

  Future<void> _approveSession() async {
    if (_session == null) return;

    // Build variance-only rows, sorted by |variance| descending
    final varLines = _lineStates
        .where((l) => l.line.variance != null && l.line.variance != 0)
        .toList()
      ..sort((a, b) =>
          (b.line.variance!.abs()).compareTo(a.line.variance!.abs()));

    final approved = await showDialog<String?>(
      context: context,
      barrierDismissible: false,
      builder: (_) => _ApproveDialog(varLines: varLines, session: _session!),
    );
    if (approved == null || !mounted) return; // cancelled

    setState(() => _loading = true);
    try {
      final result = await _svc.approveSession(_session!.id, reason: approved);
      _applySession(result.session);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(result.adjustment != null
              ? 'تم الاعتماد — تسوية #${result.adjustment!.id} صدرت'
              : 'تم الاعتماد — لا توجد فروقات'),
          backgroundColor: AppColors.success,
        ));
      }
    } on InventoryApiException catch (e) {
      setState(() => _loading = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.message), backgroundColor: AppColors.error),
        );
      }
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(
          title: _session == null
              ? const Text('جلسة جرد جديدة')
              : Text('جلسة #${_session!.id}'),
          backgroundColor: AppColors.primaryGold,
          foregroundColor: Colors.white,
          actions: [
            if (_session != null && _session!.isActive)
              IconButton(
                icon: const Icon(Icons.refresh),
                onPressed: _refresh,
                tooltip: _lastRefresh != null
                    ? 'آخر تحديث ${_timeSince(_lastRefresh!)}'
                    : 'تحديث',
              ),
          ],
        ),
        body: _loading
            ? const Center(child: CircularProgressIndicator(color: AppColors.primaryGold))
            : _error != null
                ? _ErrorRetry(
                    message: _error!,
                    onRetry: _session != null
                        ? () => _loadSession(_session!.id)
                        : _showOpenSessionSheet,
                  )
                : _session == null
                    ? const SizedBox.shrink()
                    : _buildBody(),
        bottomNavigationBar: _session == null || _loading ? null : _buildBottomBar(),
      ),
    );
  }

  Widget _buildBody() {
    final s = _session!;
    return Column(
      children: [
        _SessionStatusBar(session: s, lastRefresh: _lastRefresh),
        Expanded(
          child: RefreshIndicator(
            onRefresh: _refresh,
            color: AppColors.primaryGold,
            child: _lineStates.isEmpty
                ? const Center(child: Text('لا توجد أصناف في هذا الفرع'))
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
                    itemCount: _lineStates.length,
                    separatorBuilder: (ctx, i) => const SizedBox(height: 8),
                    itemBuilder: (_, i) => _CountLineRow(
                      key: ValueKey(_lineStates[i].line.id),
                      ls: _lineStates[i],
                      session: s,
                      onSave: (val) => _saveEntry(_lineStates[i], val),
                      onRetry: (ls) {
                        if (ls.line.countedWeight != null) {
                          _saveEntry(ls, ls.line.countedWeight!);
                        }
                      },
                    ),
                  ),
          ),
        ),
      ],
    );
  }

  Widget _buildBottomBar() {
    final s = _session!;
    final countedCount = _lineStates.where((l) => l.line.isCounted).length;
    final total = _lineStates.length;

    return SafeArea(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: Theme.of(context).cardColor,
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.08), blurRadius: 8)],
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                'تم عدّ $countedCount / $total صنف',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ),
            if (s.status == 'open' || s.status == 'counting')
              ElevatedButton(
                onPressed: countedCount == total ? _closeSession : null,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primaryGold,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: Colors.grey[300],
                ),
                child: const Text('إغلاق والمراجعة'),
              ),
            if (s.status == 'closed')
              ElevatedButton.icon(
                onPressed: _approveSession,
                icon: const Icon(Icons.check_circle_outline),
                label: const Text('اعتماد الجرد'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.success,
                  foregroundColor: Colors.white,
                ),
              ),
            if (s.status == 'approved')
              const Chip(
                label: Text('معتمد ✓', style: TextStyle(color: Colors.white)),
                backgroundColor: AppColors.success,
              ),
          ],
        ),
      ),
    );
  }
}

// ── Session Status Bar ────────────────────────────────────────────────────────

class _SessionStatusBar extends StatelessWidget {
  const _SessionStatusBar({required this.session, required this.lastRefresh});
  final CountSession session;
  final DateTime? lastRefresh;

  @override
  Widget build(BuildContext context) {
    final statusColor = _statusColor(session.status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: statusColor.withOpacity(0.08),
      child: Row(
        children: [
          Container(
            width: 8, height: 8,
            decoration: BoxDecoration(color: statusColor, shape: BoxShape.circle),
          ),
          const SizedBox(width: 8),
          Text(
            _statusLabel(session.status),
            style: TextStyle(color: statusColor, fontWeight: FontWeight.bold, fontSize: 13),
          ),
          if (session.blindCount && session.isActive) ...[
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: AppColors.info.withOpacity(0.12),
                borderRadius: BorderRadius.circular(6),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.visibility_off, size: 12, color: AppColors.info),
                  SizedBox(width: 4),
                  Text('جرد أعمى', style: TextStyle(fontSize: 11, color: AppColors.info)),
                ],
              ),
            ),
          ],
          const Spacer(),
          if (lastRefresh != null)
            Text(
              'آخر تحديث ${_timeSince(lastRefresh!)}',
              style: TextStyle(fontSize: 11, color: Colors.grey[500]),
            ),
        ],
      ),
    );
  }

  static Color _statusColor(String s) => switch (s) {
        'open' => AppColors.info,
        'counting' => AppColors.warning,
        'closed' => AppColors.primaryGold,
        'approved' => AppColors.success,
        _ => Colors.grey,
      };

  static String _statusLabel(String s) => switch (s) {
        'open' => 'مفتوحة',
        'counting' => 'قيد العدّ',
        'closed' => 'مغلقة — بانتظار الاعتماد',
        'approved' => 'معتمدة',
        _ => s,
      };
}

// ── Count Line Row ────────────────────────────────────────────────────────────

class _CountLineRow extends StatefulWidget {
  const _CountLineRow({
    super.key,
    required this.ls,
    required this.session,
    required this.onSave,
    required this.onRetry,
  });
  final _LineState ls;
  final CountSession session;
  final ValueChanged<double> onSave;
  final ValueChanged<_LineState> onRetry;

  @override
  State<_CountLineRow> createState() => _CountLineRowState();
}

class _CountLineRowState extends State<_CountLineRow> {
  late final TextEditingController _ctrl;
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(
      text: widget.ls.line.countedWeight?.toStringAsFixed(2) ?? '',
    );
    _focus.addListener(() {
      if (!_focus.hasFocus) _commit();
    });
  }

  @override
  void didUpdateWidget(_CountLineRow old) {
    super.didUpdateWidget(old);
    // When pull-to-refresh brings a new countedWeight from another device,
    // update the text field only if it doesn't have focus (user isn't typing).
    final newWeight = widget.ls.line.countedWeight;
    final oldWeight = old.ls.line.countedWeight;
    if (newWeight != oldWeight && !_focus.hasFocus) {
      _ctrl.text = newWeight?.toStringAsFixed(2) ?? '';
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _commit() {
    final val = double.tryParse(_ctrl.text.trim());
    if (val == null) return;
    if (val == widget.ls.line.countedWeight) return; // no change
    widget.onSave(val);
  }

  bool get _editable =>
      widget.session.status == 'open' || widget.session.status == 'counting';

  @override
  Widget build(BuildContext context) {
    final ls = widget.ls;
    final line = ls.line;
    final karatColor = AppColors.karatColorFor(line.karat);
    final blind = widget.session.blindCount && widget.session.isActive;

    // Variance row (revealed after close)
    final showVariance = line.variance != null && !blind;
    final hasVariance = showVariance && line.variance != 0;

    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: hasVariance
            ? AppColors.warning.withOpacity(0.06)
            : Theme.of(context).cardColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: hasVariance
              ? AppColors.warning.withOpacity(0.4)
              : ls.status == CountLineStatus.failed
                  ? AppColors.error.withOpacity(0.5)
                  : Colors.grey.shade200,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Top row: karat + category info + status indicator
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: karatColor.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  'عيار ${line.karat.toStringAsFixed(0)}',
                  style: TextStyle(
                    color: karatColor,
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'تصنيف #${line.categoryId ?? "—"}',
                  style: const TextStyle(fontSize: 13),
                ),
              ),
              _StatusDot(status: ls.status),
            ],
          ),
          const SizedBox(height: 10),
          // Input row
          Row(
            children: [
              // Expected weight (hidden during blind count)
              if (!blind) ...[
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('المتوقع', style: TextStyle(fontSize: 10, color: Colors.grey[500])),
                    Text(
                      line.expectedWeight != null
                          ? '${formatWeight(line.expectedWeight!)} جم'
                          : '—',
                      style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
                const SizedBox(width: 16),
              ],
              // Counted input
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('المعدود', style: TextStyle(fontSize: 10, color: Colors.grey[500])),
                    _editable
                        ? TextField(
                            controller: _ctrl,
                            focusNode: _focus,
                            keyboardType: const TextInputType.numberWithOptions(decimal: true),
                            inputFormatters: [
                              FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                            ],
                            textInputAction: TextInputAction.done,
                            onSubmitted: (_) => _commit(),
                            decoration: InputDecoration(
                              suffixText: 'جم',
                              isDense: true,
                              contentPadding: const EdgeInsets.symmetric(
                                  horizontal: 10, vertical: 8),
                              border: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                              focusedBorder: OutlineInputBorder(
                                borderRadius: BorderRadius.circular(8),
                                borderSide: BorderSide(color: karatColor, width: 2),
                              ),
                            ),
                          )
                        : Text(
                            line.countedWeight != null
                                ? '${formatWeight(line.countedWeight!)} جم'
                                : '—',
                            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                          ),
                  ],
                ),
              ),
              // Variance (revealed after close)
              if (showVariance) ...[
                const SizedBox(width: 16),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('الفرق', style: TextStyle(fontSize: 10, color: Colors.grey[500])),
                    Text(
                      '${line.variance! >= 0 ? '+' : ''}${formatWeight(line.variance!)} جم',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.bold,
                        color: line.variance! > 0
                            ? AppColors.success
                            : line.variance! < 0
                                ? AppColors.error
                                : Colors.grey,
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
          // Counted-by footer (shows other counter's name for awareness)
          if (line.countedBy != null) ...[
            const SizedBox(height: 6),
            Row(
              children: [
                Icon(Icons.person_outline, size: 12, color: Colors.grey[400]),
                const SizedBox(width: 4),
                Text(
                  line.countedBy!,
                  style: TextStyle(fontSize: 10, color: Colors.grey[500]),
                ),
                if (line.countedAt != null) ...[
                  const SizedBox(width: 6),
                  Text(
                    _timeSince(line.countedAt!),
                    style: TextStyle(fontSize: 10, color: Colors.grey[400]),
                  ),
                ],
              ],
            ),
          ],
          // Retry button on failure
          if (ls.status == CountLineStatus.failed) ...[
            const SizedBox(height: 6),
            GestureDetector(
              onTap: () => widget.onRetry(ls),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.replay, size: 14, color: AppColors.error),
                  SizedBox(width: 4),
                  Text(
                    'فشل الحفظ — اضغط لإعادة المحاولة',
                    style: TextStyle(fontSize: 11, color: AppColors.error),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

// ── Status Dot ────────────────────────────────────────────────────────────────

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.status});
  final CountLineStatus status;

  @override
  Widget build(BuildContext context) {
    return switch (status) {
      CountLineStatus.saving => const SizedBox(
          width: 16, height: 16,
          child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.primaryGold),
        ),
      CountLineStatus.saved => const Icon(Icons.check_circle, size: 16, color: AppColors.success),
      CountLineStatus.failed => const Icon(Icons.error_outline, size: 16, color: AppColors.error),
      CountLineStatus.idle => const SizedBox(width: 16),
    };
  }
}

// ── Approve Dialog ────────────────────────────────────────────────────────────

class _ApproveDialog extends StatefulWidget {
  const _ApproveDialog({required this.varLines, required this.session});
  final List<_LineState> varLines;
  final CountSession session;

  @override
  State<_ApproveDialog> createState() => _ApproveDialogState();
}

class _ApproveDialogState extends State<_ApproveDialog> {
  final _reasonCtrl = TextEditingController(text: 'تسوية جرد دوري');

  @override
  void dispose() {
    _reasonCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hasVariance = widget.varLines.isNotEmpty;

    return AlertDialog(
      title: const Text('اعتماد جلسة الجرد'),
      content: SizedBox(
        width: double.maxFinite,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!hasVariance)
              const _InfoChip(
                icon: Icons.check_circle_outline,
                label: 'لا توجد فروقات — الجرد مطابق تماماً',
                color: AppColors.success,
              )
            else ...[
              _InfoChip(
                icon: Icons.warning_amber_rounded,
                label: '${widget.varLines.length} صنف فيه فرق — سيتم إنشاء قيد تسوية',
                color: AppColors.warning,
              ),
              const SizedBox(height: 10),
              // Variance rows sorted by magnitude (already sorted by caller)
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 200),
                child: ListView(
                  shrinkWrap: true,
                  children: widget.varLines.map((ls) {
                    final v = ls.line.variance!;
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Row(
                        children: [
                          Text(
                            'عيار ${ls.line.karat.toStringAsFixed(0)} / #${ls.line.categoryId}',
                            style: const TextStyle(fontSize: 13),
                          ),
                          const Spacer(),
                          Text(
                            '${v >= 0 ? '+' : ''}${formatWeight(v)} جم',
                            style: TextStyle(
                              fontWeight: FontWeight.bold,
                              color: v > 0 ? AppColors.success : AppColors.error,
                            ),
                          ),
                        ],
                      ),
                    );
                  }).toList(),
                ),
              ),
              // GL preview stub — shows that a JE will be created in Phase 5
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppColors.info.withOpacity(0.06),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AppColors.info.withOpacity(0.2)),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.receipt_long_outlined, size: 14, color: AppColors.info),
                    SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        'سيُنشأ قيد تسوية في الدفتر العام عند الترحيل (المرحلة 5)',
                        style: TextStyle(fontSize: 11, color: AppColors.info),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 14),
            TextField(
              controller: _reasonCtrl,
              decoration: InputDecoration(
                labelText: 'سبب التسوية',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                isDense: true,
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context, null),
          child: const Text('إلغاء'),
        ),
        ElevatedButton.icon(
          onPressed: () => Navigator.pop(context, _reasonCtrl.text.trim()),
          icon: const Icon(Icons.check),
          label: Text(hasVariance ? 'اعتماد وترحيل' : 'اعتماد'),
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.primaryGold,
            foregroundColor: Colors.white,
          ),
        ),
      ],
    );
  }
}

class _InfoChip extends StatelessWidget {
  const _InfoChip({required this.icon, required this.label, required this.color});
  final IconData icon;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: color.withOpacity(0.08),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withOpacity(0.25)),
      ),
      child: Row(
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 8),
          Expanded(child: Text(label, style: TextStyle(fontSize: 12, color: color))),
        ],
      ),
    );
  }
}

// ── Open Session Sheet ────────────────────────────────────────────────────────

class _OpenSessionSheet extends StatefulWidget {
  const _OpenSessionSheet({
    required this.svc,
    required this.onOpened,
    required this.onCancelled,
  });
  final InventoryService svc;
  final ValueChanged<CountSession> onOpened;
  final VoidCallback onCancelled;

  @override
  State<_OpenSessionSheet> createState() => _OpenSessionSheetState();
}

class _OpenSessionSheetState extends State<_OpenSessionSheet> {
  bool _blindCount = true;
  bool _loading = false;
  String? _error;

  // In a real app, branches would be loaded from BranchProvider.
  // Using a simple text field for branch ID here as a placeholder.
  final _branchCtrl = TextEditingController();

  @override
  void dispose() {
    _branchCtrl.dispose();
    super.dispose();
  }

  Future<void> _open() async {
    final branchId = int.tryParse(_branchCtrl.text.trim());
    if (branchId == null) {
      setState(() => _error = 'أدخل رقم الفرع');
      return;
    }
    setState(() { _loading = true; _error = null; });
    try {
      final s = await widget.svc.openSession(
        branchId: branchId,
        blindCount: _blindCount,
      );
      widget.onOpened(s);
    } on InventoryApiException catch (e) {
      setState(() { _error = e.message; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Padding(
        padding: EdgeInsets.only(
          bottom: MediaQuery.of(context).viewInsets.bottom + 24,
          top: 24, left: 24, right: 24,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                width: 40, height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey[300],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 20),
            const Text(
              'فتح جلسة جرد',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _branchCtrl,
              keyboardType: TextInputType.number,
              decoration: InputDecoration(
                labelText: 'رقم الفرع',
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                errorText: _error,
              ),
            ),
            const SizedBox(height: 14),
            SwitchListTile(
              value: _blindCount,
              onChanged: (v) => setState(() => _blindCount = v),
              title: const Text('جرد أعمى', style: TextStyle(fontWeight: FontWeight.w600)),
              subtitle: const Text(
                'الرصيد المتوقع مخفي أثناء العدّ — موصى به',
                style: TextStyle(fontSize: 12),
              ),
              activeColor: AppColors.primaryGold,
              contentPadding: EdgeInsets.zero,
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _loading ? null : _open,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primaryGold,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                child: _loading
                    ? const SizedBox(
                        height: 20, width: 20,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white),
                      )
                    : const Text('بدء الجرد', style: TextStyle(fontSize: 16)),
              ),
            ),
            TextButton(
              onPressed: widget.onCancelled,
              child: const Text('إلغاء', style: TextStyle(color: Colors.grey)),
            ),
          ],
        ),
      ),
    );
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

class _LineState {
  CountLine line;
  CountLineStatus status = CountLineStatus.idle;
  _LineState({required this.line});
}

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            ElevatedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('إعادة المحاولة'),
              style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.primaryGold,
                  foregroundColor: Colors.white),
            ),
          ],
        ),
      );
}

String _timeSince(DateTime dt) {
  final d = DateTime.now().difference(dt);
  if (d.inSeconds < 60) return 'الآن';
  if (d.inMinutes < 60) return 'منذ ${d.inMinutes} د';
  return 'منذ ${d.inHours} س';
}
