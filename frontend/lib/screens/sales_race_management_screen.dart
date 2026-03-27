import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';

import '../api_service.dart';
import '../providers/auth_provider.dart';
import '../providers/sales_race_refresh_provider.dart';
import '../theme/app_theme.dart';

/// نظام إدارة سباق المبيعات المتكامل.
/// Tab 1 – لوحة المتابعة (متاح للجميع): الترتيب، هدف الأسبوع، بطل اليوم.
/// Tab 2 – الإعدادات (system.settings): تفعيل، فترة افتراضية، نقاط، هدف، خيارات عرض.
class SalesRaceManagementScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;

  const SalesRaceManagementScreen({
    super.key,
    required this.api,
    this.isArabic = true,
  });

  @override
  State<SalesRaceManagementScreen> createState() =>
      _SalesRaceManagementScreenState();
}

class _SalesRaceManagementScreenState
    extends State<SalesRaceManagementScreen> {
  // ── Leaderboard ──────────────────────────────────────────────────────────
  Map<String, dynamic>? _data;
  bool _loading = false;
  String? _error;
  String _period = 'today';
  String _metric = 'weight';
  DateTime? _fetchedAt;

  // ── Config ────────────────────────────────────────────────────────────────
  bool _configLoading = false;
  String? _configError;
  bool _configSaving = false;

  // Config form state
  bool _enabled = true;
  String _defaultPeriod = 'today';
  double _pointsPerGram = 10.0;
  bool _allowFallback = true;
  bool _showInvoiceCount = true;
  bool _showChampion = true;
  double _weeklyTarget = 2000.0;

  final TextEditingController _pointsCtrl = TextEditingController();
  final TextEditingController _weeklyTargetCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadLeaderboard();
    _loadConfig();
  }

  @override
  void dispose() {
    _pointsCtrl.dispose();
    _weeklyTargetCtrl.dispose();
    super.dispose();
  }

  // ── Data loaders ──────────────────────────────────────────────────────────

  Future<void> _loadLeaderboard() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await widget.api.getHomeLeaderboard(
        period: _period,
        metric: _metric,
      );
      if (!mounted) return;
      setState(() {
        _data = data;
        _fetchedAt = DateTime.now();
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadConfig() async {
    if (!mounted) return;
    setState(() {
      _configLoading = true;
      _configError = null;
    });
    try {
      final cfg = await widget.api.getSalesRaceConfig();
      if (!mounted) return;
      _applyConfig(cfg);
    } catch (e) {
      if (!mounted) return;
      setState(() => _configError = e.toString());
    } finally {
      if (mounted) setState(() => _configLoading = false);
    }
  }

  void _applyConfig(Map<String, dynamic> cfg) {
    _enabled = cfg['enabled'] as bool? ?? true;
    _defaultPeriod =
        (cfg['default_period'] as String?)?.trim().toLowerCase() == 'week'
            ? 'week'
            : 'today';
    _pointsPerGram =
        (cfg['points_per_gram'] as num?)?.toDouble() ?? 10.0;
    _allowFallback = cfg['allow_fallback_to_latest_period'] as bool? ?? true;
    _showInvoiceCount = cfg['show_invoice_count'] as bool? ?? true;
    _showChampion = cfg['show_champion'] as bool? ?? true;
    _weeklyTarget =
        (cfg['weekly_sales_target_weight'] as num?)?.toDouble() ?? 2000.0;
    _pointsCtrl.text = _pointsPerGram.toStringAsFixed(
        _pointsPerGram == _pointsPerGram.truncateToDouble() ? 0 : 1);
    _weeklyTargetCtrl.text = _weeklyTarget.toStringAsFixed(
        _weeklyTarget == _weeklyTarget.truncateToDouble() ? 0 : 1);
  }

  Future<void> _saveConfig() async {
    if (!mounted) return;
    // Validate numeric fields
    final parsedPoints = double.tryParse(_pointsCtrl.text.trim());
    final parsedTarget = double.tryParse(_weeklyTargetCtrl.text.trim());
    if (parsedPoints == null || parsedPoints < 0) {
      _showSnack(
        widget.isArabic ? 'قيمة النقاط غير صالحة' : 'Invalid points value',
        isError: true,
      );
      return;
    }
    if (parsedTarget == null || parsedTarget < 0) {
      _showSnack(
        widget.isArabic
            ? 'قيمة الهدف الأسبوعي غير صالحة'
            : 'Invalid weekly target value',
        isError: true,
      );
      return;
    }
    setState(() => _configSaving = true);
    try {
      final saved = await widget.api.updateSalesRaceConfig({
        'enabled': _enabled,
        'default_period': _defaultPeriod,
        'points_per_gram': parsedPoints,
        'allow_fallback_to_latest_period': _allowFallback,
        'show_invoice_count': _showInvoiceCount,
        'show_champion': _showChampion,
        'weekly_sales_target_weight': parsedTarget,
      });
      if (!mounted) return;
      _applyConfig(saved);
      // Notify home screen to refresh its leaderboard card.
      Provider.of<SalesRaceRefreshProvider>(context, listen: false)
          .notifySettingsChanged();
      _showSnack(
        widget.isArabic ? 'تم حفظ الإعدادات بنجاح' : 'Settings saved',
      );
    } catch (e) {
      if (!mounted) return;
      _showSnack(e.toString(), isError: true);
    } finally {
      if (mounted) setState(() => _configSaving = false);
    }
  }

  void _showSnack(String msg, {bool isError = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: isError ? Colors.red.shade700 : Colors.green.shade700,
      ),
    );
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    final auth = context.read<AuthProvider>();
    final canManage = auth.hasPermission('system.settings');

    return DefaultTabController(
      length: canManage ? 2 : 1,
      child: Scaffold(
        backgroundColor: Theme.of(context).scaffoldBackgroundColor,
        appBar: AppBar(
          title: Text(isAr ? 'سباق المبيعات' : 'Sales Race'),
          backgroundColor: AppColors.darkGold,
          actions: [
            IconButton(
              icon: _loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Icon(Icons.refresh_rounded),
              tooltip: isAr ? 'تحديث' : 'Refresh',
              onPressed: _loading ? null : _loadLeaderboard,
            ),
          ],
          bottom: TabBar(
            labelColor: Colors.black,
            indicatorColor: AppColors.primaryGold,
            tabs: [
              Tab(
                text: isAr ? 'لوحة المتابعة' : 'Live Board',
                icon: const Icon(Icons.leaderboard_rounded),
              ),
              if (canManage)
                Tab(
                  text: isAr ? 'الإعدادات' : 'Settings',
                  icon: const Icon(Icons.settings_rounded),
                ),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            _buildDashboardTab(isAr),
            if (canManage) _buildSettingsTab(isAr),
          ],
        ),
      ),
    );
  }

  // ── Tab 1: Dashboard ──────────────────────────────────────────────────────

  Widget _buildDashboardTab(bool isAr) {
    return RefreshIndicator(
      onRefresh: _loadLeaderboard,
      color: AppColors.primaryGold,
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildPeriodAndMetricSelectors(isAr),
            const SizedBox(height: 16),
            if (_loading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: 48),
                  child: CircularProgressIndicator(),
                ),
              )
            else if (_error != null)
              _buildErrorCard(isAr)
            else if (_data == null)
              const SizedBox.shrink()
            else ...[
              _buildChampionAndSummaryRow(isAr),
              const SizedBox(height: 16),
              if (_period == 'week') ...[
                _buildWeeklyGoalCard(isAr),
                const SizedBox(height: 16),
              ],
              _buildRankingCard(isAr),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildPeriodAndMetricSelectors(bool isAr) {
    return Wrap(
      spacing: 12,
      runSpacing: 10,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        // Period
        SegmentedButton<String>(
          segments: [
            ButtonSegment(
              value: 'today',
              label: Text(isAr ? 'اليوم' : 'Today'),
            ),
            ButtonSegment(
              value: 'week',
              label: Text(isAr ? 'الأسبوع' : 'Week'),
            ),
          ],
          selected: {_period},
          onSelectionChanged: _loading
              ? null
              : (s) {
                  final next = s.isNotEmpty ? s.first : _period;
                  if (next == _period) return;
                  setState(() => _period = next);
                  _loadLeaderboard();
                },
          showSelectedIcon: false,
          style: ButtonStyle(
            foregroundColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.selected)) return Colors.black;
              return null;
            }),
            backgroundColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.selected)) {
                return AppColors.primaryGold;
              }
              return null;
            }),
          ),
        ),
        // Metric
        SegmentedButton<String>(
          segments: [
            ButtonSegment(
              value: 'weight',
              label: Text(isAr ? 'الوزن' : 'Weight'),
            ),
            ButtonSegment(
              value: 'count',
              label: Text(isAr ? 'الفواتير' : 'Count'),
            ),
            ButtonSegment(
              value: 'points',
              label: Text(isAr ? 'النقاط' : 'Points'),
            ),
          ],
          selected: {_metric},
          onSelectionChanged: _loading
              ? null
              : (s) {
                  final next = s.isNotEmpty ? s.first : _metric;
                  if (next == _metric) return;
                  setState(() => _metric = next);
                  _loadLeaderboard();
                },
          showSelectedIcon: false,
          style: ButtonStyle(
            foregroundColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.selected)) return Colors.black;
              return null;
            }),
            backgroundColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.selected)) {
                return AppColors.primaryGold;
              }
              return null;
            }),
          ),
        ),
      ],
    );
  }

  Widget _buildChampionAndSummaryRow(bool isAr) {
    final data = _data!;
    final champion = data['champion'] as Map?;
    final adminSummary = data['admin_summary'] as Map?;
    final isFallback = data['is_fallback'] == true;
    final effectiveStartStr =
        (data['effective_start_date'] ?? '').toString();
    final effectiveDate = DateTime.tryParse(effectiveStartStr);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Fallback notice
        if (isFallback && effectiveDate != null)
          _buildNoticeCard(
            icon: Icons.history_toggle_off_rounded,
            message: _period == 'week'
                ? (isAr
                    ? 'لا توجد مبيعات هذا الأسبوع — يتم عرض آخر أسبوع بدأ في ${_fmt(effectiveDate)}'
                    : 'No sales this week — showing latest week starting ${_fmt(effectiveDate)}')
                : (isAr
                    ? 'لا توجد مبيعات اليوم — يتم عرض آخر يوم بتاريخ ${_fmt(effectiveDate)}'
                    : 'No sales today — showing latest day on ${_fmt(effectiveDate)}'),
          ),
        if (isFallback && effectiveDate != null)
          const SizedBox(height: 12),

        // Champion card + admin summary in a row on wide screens
        if (champion != null || adminSummary != null)
          LayoutBuilder(
            builder: (ctx, constraints) {
              final isWide = constraints.maxWidth >= 600;
              final widgets = <Widget>[
                if (champion != null)
                  Expanded(child: _buildChampionCard(isAr, champion)),
                if (adminSummary != null) ...[
                  if (isWide) const SizedBox(width: 12),
                  if (!isWide) const SizedBox(height: 12),
                  Expanded(child: _buildAdminSummaryCard(isAr, adminSummary)),
                ],
              ];
              if (isWide) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: widgets,
                );
              }
              return Column(children: widgets);
            },
          ),
      ],
    );
  }

  Widget _buildChampionCard(bool isAr, Map champion) {
    final name = (champion['name'] ?? '').toString();
    return _card(
      child: Row(
        children: [
          const Text('🥇', style: TextStyle(fontSize: 32)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isAr ? 'بطل اليوم' : "Today's Champion",
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context)
                        .colorScheme
                        .onSurface
                        .withValues(alpha: 0.6),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  name,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: AppColors.primaryGold,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAdminSummaryCard(bool isAr, Map summary) {
    final totalCash = (summary['total_cash'] as num?)?.toDouble();
    final totalProfit = (summary['total_profit'] as num?)?.toDouble();
    final currency = (summary['currency'] ?? 'SAR').toString();
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.bar_chart_rounded,
                  size: 20, color: AppColors.primaryGold),
              const SizedBox(width: 8),
              Text(
                isAr ? 'ملخص المبيعات' : 'Sales Summary',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: Theme.of(context)
                      .colorScheme
                      .onSurface
                      .withValues(alpha: 0.7),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (totalCash != null)
            _summaryRow(
              isAr ? 'إجمالي المبيعات' : 'Total Sales',
              '${totalCash.toStringAsFixed(2)} $currency',
              color: AppColors.info,
            ),
          if (totalProfit != null) ...[
            const SizedBox(height: 6),
            _summaryRow(
              isAr ? 'إجمالي الربح' : 'Total Profit',
              '${totalProfit.toStringAsFixed(2)} $currency',
              color: AppColors.success,
            ),
          ],
        ],
      ),
    );
  }

  Widget _summaryRow(String label, String value, {Color? color}) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: Theme.of(context)
                .colorScheme
                .onSurface
                .withValues(alpha: 0.6),
          ),
        ),
        Text(
          value,
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            color: color,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }

  Widget _buildWeeklyGoalCard(bool isAr) {
    final data = _data!;
    final metric = (data['metric'] ?? 'weight_g').toString();
    final teamWeight = (data['team_weight_g'] as num?)?.toDouble();
    final weeklyTarget = (data['weekly_target_weight_g'] as num?)?.toDouble();
    final teamPoints = (data['team_points'] as num?)?.toInt();
    final weeklyTargetPoints = (data['weekly_target_points'] as num?)?.toInt();
    final targetProgress =
        (data['target_progress'] as num?)?.toDouble() ?? 0.0;
    final remainingWeight = (data['remaining_weight_g'] as num?)?.toDouble();
    final remainingPoints = (data['remaining_points'] as num?)?.toInt();

    final isGoalAchieved = targetProgress >= 0.9999;
    final goalColor = isGoalAchieved
        ? AppColors.success
        : (targetProgress < 0.5 ? AppColors.warning : AppColors.info);

    final usePoints = metric == 'points';
    final teamVal =
        usePoints ? teamPoints?.toStringAsFixed(0) : teamWeight?.toStringAsFixed(1);
    final targetVal = usePoints
        ? weeklyTargetPoints?.toStringAsFixed(0)
        : weeklyTarget?.toStringAsFixed(0);
    final remainingVal =
        usePoints ? remainingPoints?.toStringAsFixed(0) : remainingWeight?.toStringAsFixed(1);
    final unit = usePoints
        ? (isAr ? ' نقطة' : ' pts')
        : (isAr ? ' جم' : ' g');

    if (teamVal == null || targetVal == null) return const SizedBox.shrink();

    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.flag_rounded, size: 20, color: goalColor),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  isAr ? 'هدف الفريق الأسبوعي' : 'Team Weekly Goal',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (isGoalAchieved) const Text('🎉', style: TextStyle(fontSize: 20)),
              const SizedBox(width: 8),
              Text(
                '${(targetProgress.clamp(0.0, 1.0) * 100).round()}%',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: goalColor,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: LinearProgressIndicator(
              value: targetProgress.clamp(0.0, 1.0),
              minHeight: 12,
              backgroundColor: Theme.of(context)
                  .colorScheme
                  .onSurface
                  .withValues(alpha: 0.08),
              valueColor: AlwaysStoppedAnimation<Color>(goalColor),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _summaryRow(
                isAr ? 'المحقق' : 'Achieved',
                '$teamVal$unit',
                color: goalColor,
              ),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                isAr ? 'الهدف' : 'Target',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context)
                      .colorScheme
                      .onSurface
                      .withValues(alpha: 0.6),
                ),
              ),
              Text(
                '$targetVal$unit',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          if (!isGoalAchieved && remainingVal != null) ...[
            const SizedBox(height: 4),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  isAr ? 'المتبقي' : 'Remaining',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context)
                        .colorScheme
                        .onSurface
                        .withValues(alpha: 0.6),
                  ),
                ),
                Text(
                  '$remainingVal$unit',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppColors.warning,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildRankingCard(bool isAr) {
    final data = _data!;
    final ranking = (data['ranking'] as List?) ?? const [];
    final config = data['config'] as Map?;
    final metric = (data['metric'] ?? 'weight_g').toString();
    final showInvoiceCount = config?['show_invoice_count'] != false;
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    if (ranking.isEmpty) {
      return _card(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 24),
            child: Column(
              children: [
                Icon(Icons.emoji_events_outlined,
                    size: 40,
                    color: colorScheme.onSurface.withValues(alpha: 0.35)),
                const SizedBox(height: 8),
                Text(
                  isAr
                      ? 'لا توجد مبيعات في هذه الفترة'
                      : 'No sales in this period',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: colorScheme.onSurface.withValues(alpha: 0.6),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    String rankLabel(int i) {
      if (i == 0) return '🥇';
      if (i == 1) return '🥈';
      if (i == 2) return '🥉';
      return '${i + 1}';
    }

    String metricText(Map row, int i) {
      final score = (row['score'] as num?)?.toDouble() ?? 0.0;
      final count = (row['count'] as num?)?.toInt() ?? 0;
      final invoiceLabel = isAr ? 'فاتورة' : (count == 1 ? 'invoice' : 'invoices');
      if (metric == 'count') {
        return isAr ? '$count فاتورة' : '$count $invoiceLabel';
      }
      if (metric == 'points') {
        final base = '${score.toStringAsFixed(0)} ${isAr ? 'نقطة' : 'pts'}';
        return showInvoiceCount ? '$base • $count $invoiceLabel' : base;
      }
      final base = '${score.toStringAsFixed(1)} ${isAr ? 'جم' : 'g'}';
      return showInvoiceCount ? '$base • $count $invoiceLabel' : base;
    }

    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                isAr ? 'ترتيب الموظفين' : 'Employee Rankings',
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
              ),
              Icon(Icons.emoji_events_rounded,
                  color: AppColors.primaryGold, size: 22),
            ],
          ),
          if (_fetchedAt != null) ...[
            const SizedBox(height: 4),
            Text(
              isAr
                  ? 'آخر تحديث: ${DateFormat('dd/MM HH:mm', 'en').format(_fetchedAt!)}'
                  : 'Updated: ${DateFormat('dd/MM HH:mm', 'en').format(_fetchedAt!)}',
              style: theme.textTheme.bodySmall?.copyWith(
                color: colorScheme.onSurface.withValues(alpha: 0.5),
              ),
            ),
          ],
          const SizedBox(height: 16),
          ...List.generate(ranking.length, (i) {
            final row = ranking[i] as Map;
            final name = (row['name'] ?? '').toString();
            final share = (row['share'] as num?)?.toDouble() ?? 0.0;
            final salesAmount = (row['sales_amount'] as num?)?.toDouble() ?? 0.0;
            final isLeader = i == 0;
            final Color valueColor = isLeader
                ? colorScheme.primary
                : colorScheme.secondary;
            final Color progressColor = switch (i) {
              1 => const Color(0xFF98A2B3),
              2 => const Color(0xFFCD7F32),
              _ => valueColor,
            };

            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: colorScheme.onSurface.withValues(alpha: 0.035),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(
                    color: colorScheme.onSurface.withValues(alpha: 0.08),
                  ),
                ),
                child: Row(
                  children: [
                    SizedBox(
                      width: 28,
                      child: Text(
                        rankLabel(i),
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodyMedium
                            ?.copyWith(fontWeight: FontWeight.w700),
                      ),
                    ),
                    const SizedBox(width: 8),
                    CircleAvatar(
                      radius: 16,
                      backgroundColor: valueColor.withValues(alpha: 0.12),
                      child: Text(
                        name.isNotEmpty ? name.characters.first : '?',
                        style: TextStyle(
                          color: valueColor,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment:
                                MainAxisAlignment.spaceBetween,
                            children: [
                              Expanded(
                                child: Text(
                                  name,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: theme.textTheme.bodyMedium
                                      ?.copyWith(fontWeight: FontWeight.w600),
                                ),
                              ),
                              const SizedBox(width: 12),
                              Text(
                                metricText(row, i),
                                style: theme.textTheme.bodyMedium?.copyWith(
                                  color: valueColor,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 4),
                          Text(
                            isAr
                                ? 'المبيعات: ${salesAmount.toStringAsFixed(2)}'
                                : 'Sales: ${salesAmount.toStringAsFixed(2)}',
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: AppColors.primaryGold,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const SizedBox(height: 6),
                          ClipRRect(
                            borderRadius: BorderRadius.circular(6),
                            child: LinearProgressIndicator(
                              value: share.clamp(0.0, 1.0),
                              minHeight: 8,
                              backgroundColor: colorScheme.onSurface
                                  .withValues(alpha: 0.08),
                              valueColor: AlwaysStoppedAnimation<Color>(
                                progressColor,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            );
          }),
        ],
      ),
    );
  }

  Widget _buildErrorCard(bool isAr) {
    return _card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.error_outline_rounded,
                  color: Theme.of(context).colorScheme.error),
              const SizedBox(width: 8),
              Text(
                isAr ? 'تعذر تحميل البيانات' : 'Failed to load data',
                style: TextStyle(
                    color: Theme.of(context).colorScheme.error,
                    fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ElevatedButton.icon(
            onPressed: _loadLeaderboard,
            icon: const Icon(Icons.refresh_rounded),
            label: Text(isAr ? 'إعادة المحاولة' : 'Retry'),
          ),
        ],
      ),
    );
  }

  // ── Tab 2: Settings ───────────────────────────────────────────────────────

  Widget _buildSettingsTab(bool isAr) {
    if (_configLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_configError != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_configError!,
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: _loadConfig,
              child: Text(isAr ? 'إعادة المحاولة' : 'Retry'),
            ),
          ],
        ),
      );
    }

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildSectionHeader(
            isAr ? 'الحالة العامة' : 'General Status',
            Icons.toggle_on_rounded,
          ),
          const SizedBox(height: 8),
          _card(
            child: SwitchListTile(
              title: Text(
                isAr ? 'تفعيل سباق المبيعات' : 'Enable Sales Race',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              subtitle: Text(
                isAr
                    ? 'يعرض لوحة الصدارة في الشاشة الرئيسية وهنا'
                    : 'Shows the leaderboard on home screen and here',
              ),
              value: _enabled,
              onChanged: (v) => setState(() => _enabled = v),
              activeColor: AppColors.primaryGold,
            ),
          ),
          const SizedBox(height: 20),
          _buildSectionHeader(
            isAr ? 'الفترة الافتراضية' : 'Default Period',
            Icons.calendar_today_rounded,
          ),
          const SizedBox(height: 8),
          _card(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isAr
                      ? 'الفترة المعروضة عند فتح لوحة الصدارة'
                      : 'Period shown when opening the leaderboard',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context)
                        .colorScheme
                        .onSurface
                        .withValues(alpha: 0.65),
                  ),
                ),
                const SizedBox(height: 12),
                SegmentedButton<String>(
                  segments: [
                    ButtonSegment(
                        value: 'today',
                        label: Text(isAr ? 'اليوم' : 'Today')),
                    ButtonSegment(
                        value: 'week',
                        label: Text(isAr ? 'الأسبوع' : 'Week')),
                  ],
                  selected: {_defaultPeriod},
                  onSelectionChanged: (s) {
                    if (s.isNotEmpty) setState(() => _defaultPeriod = s.first);
                  },
                  showSelectedIcon: false,
                  style: ButtonStyle(
                    foregroundColor:
                        WidgetStateProperty.resolveWith((states) {
                      if (states.contains(WidgetState.selected)) {
                        return Colors.black;
                      }
                      return null;
                    }),
                    backgroundColor:
                        WidgetStateProperty.resolveWith((states) {
                      if (states.contains(WidgetState.selected)) {
                        return AppColors.primaryGold;
                      }
                      return null;
                    }),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          _buildSectionHeader(
            isAr ? 'هدف الأسبوع بالجرام' : 'Weekly Target (grams)',
            Icons.flag_rounded,
          ),
          const SizedBox(height: 8),
          _card(
            child: TextField(
              controller: _weeklyTargetCtrl,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText: isAr ? 'الهدف الأسبوعي (جرام)' : 'Weekly target (g)',
                suffixText: isAr ? 'جم' : 'g',
                border: const OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(height: 20),
          _buildSectionHeader(
            isAr ? 'نقاط المقياس' : 'Points Metric',
            Icons.stars_rounded,
          ),
          const SizedBox(height: 8),
          _card(
            child: TextField(
              controller: _pointsCtrl,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(
                labelText:
                    isAr ? 'نقاط لكل جرام ربح' : 'Points per profit gram',
                suffixText: isAr ? 'نقطة/جم' : 'pts/g',
                border: const OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(height: 20),
          _buildSectionHeader(
            isAr ? 'خيارات العرض' : 'Display Options',
            Icons.visibility_rounded,
          ),
          const SizedBox(height: 8),
          _card(
            child: Column(
              children: [
                SwitchListTile(
                  title: Text(
                    isAr ? 'إظهار بطل اليوم' : 'Show Champion',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  value: _showChampion,
                  onChanged: (v) => setState(() => _showChampion = v),
                  activeColor: AppColors.primaryGold,
                ),
                const Divider(height: 1),
                SwitchListTile(
                  title: Text(
                    isAr ? 'إظهار عدد الفواتير مع النقاط' : 'Show Invoice Count with Score',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  value: _showInvoiceCount,
                  onChanged: (v) => setState(() => _showInvoiceCount = v),
                  activeColor: AppColors.primaryGold,
                ),
                const Divider(height: 1),
                SwitchListTile(
                  title: Text(
                    isAr
                        ? 'عرض آخر فترة عند انعدام المبيعات'
                        : 'Show Last Period When No Sales',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  subtitle: Text(
                    isAr
                        ? 'بدلاً من عرض لوحة فارغة'
                        : 'Instead of an empty leaderboard',
                  ),
                  value: _allowFallback,
                  onChanged: (v) => setState(() => _allowFallback = v),
                  activeColor: AppColors.primaryGold,
                ),
              ],
            ),
          ),
          const SizedBox(height: 32),
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton.icon(
              onPressed: _configSaving ? null : _saveConfig,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primaryGold,
                foregroundColor: Colors.black,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              icon: _configSaving
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.black,
                      ),
                    )
                  : const Icon(Icons.save_rounded),
              label: Text(
                isAr ? 'حفظ الإعدادات' : 'Save Settings',
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  Widget _card({required Widget child}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: Theme.of(context)
              .colorScheme
              .onSurface
              .withValues(alpha: 0.08),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: child,
    );
  }

  Widget _buildSectionHeader(String title, IconData icon) {
    return Row(
      children: [
        Icon(icon, size: 18, color: AppColors.primaryGold),
        const SizedBox(width: 8),
        Text(
          title,
          style: Theme.of(context).textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.bold,
            color: AppColors.primaryGold,
          ),
        ),
      ],
    );
  }

  Widget _buildNoticeCard({required IconData icon, required String message}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color:
              Theme.of(context).colorScheme.primary.withValues(alpha: 0.18),
        ),
      ),
      child: Row(
        children: [
          Icon(icon,
              size: 18, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.primary,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _fmt(DateTime dt) => DateFormat('dd/MM/yyyy', 'en').format(dt);
}
