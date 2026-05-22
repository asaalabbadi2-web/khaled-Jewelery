// frontend/lib/screens/bonus_analytics_screen.dart
//
// شاشة تحليلات المكافآت — احترافية
//
// المحتوى:
//   1. Period Filter (آخر 30/90/365 يوم)
//   2. Top Employees (أعلى 5 موظفين بمكافآت)
//   3. Distribution by Rule (donut)
//   4. Trend Chart (آخر 6 شهور)
//   5. Approval Rate (KPI ring)
//   6. By Department (متوسط لكل قسم)

import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;

import '../api_service.dart';
import '../models/employee_bonus_model.dart';
import '../theme/app_theme.dart';

enum _AnalyticsPeriod { last30, last90, lastYear }

class BonusAnalyticsScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;

  const BonusAnalyticsScreen({
    super.key,
    required this.api,
    required this.isArabic,
  });

  @override
  State<BonusAnalyticsScreen> createState() => _BonusAnalyticsScreenState();
}

class _BonusAnalyticsScreenState extends State<BonusAnalyticsScreen> {
  bool _loading = false;
  String? _error;

  List<EmployeeBonusModel> _bonuses = [];
  _AnalyticsPeriod _period = _AnalyticsPeriod.last30;

  // ─── دورة الحياة ────────────────────────────────────────
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final now = DateTime.now();
      DateTime start;
      switch (_period) {
        case _AnalyticsPeriod.last30:
          start = now.subtract(const Duration(days: 30));
          break;
        case _AnalyticsPeriod.last90:
          start = now.subtract(const Duration(days: 90));
          break;
        case _AnalyticsPeriod.lastYear:
          start = now.subtract(const Duration(days: 365));
          break;
      }

      // نحمّل سنة كاملة لرسم اتجاه آخر 6 شهور حتى لو الفلتر أصغر
      final yearStart = now.subtract(const Duration(days: 365));
      final data = await widget.api.getBonuses(
        dateFrom: yearStart.toIso8601String().split('T').first,
        dateTo: now.toIso8601String().split('T').first,
      );

      if (!mounted) return;
      setState(() {
        _bonuses = data
            .map((j) =>
                EmployeeBonusModel.fromJson(j as Map<String, dynamic>))
            .where((b) => b.periodStart.isAfter(start) || _period == _AnalyticsPeriod.lastYear)
            .toList();
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  // ─── helpers ────────────────────────────────────────────
  String _periodLabel(BuildContext context) {
    final isAr = widget.isArabic;
    switch (_period) {
      case _AnalyticsPeriod.last30:
        return isAr ? 'آخر 30 يوم' : 'Last 30 days';
      case _AnalyticsPeriod.last90:
        return isAr ? 'آخر 90 يوم' : 'Last 90 days';
      case _AnalyticsPeriod.lastYear:
        return isAr ? 'آخر سنة' : 'Last year';
    }
  }

  String _formatCurrency(num value) {
    if (value.abs() >= 1000000) {
      return '${(value / 1000000).toStringAsFixed(1)}M';
    } else if (value.abs() >= 1000) {
      return '${(value / 1000).toStringAsFixed(0)}K';
    }
    return value.toStringAsFixed(0);
  }

  // ─── البناء ─────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isAr = widget.isArabic;

    if (_loading && _bonuses.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null && _bonuses.isEmpty) {
      return _buildError(theme, isAr);
    }

    if (_bonuses.isEmpty) {
      return _buildEmpty(theme, isAr);
    }

    return RefreshIndicator(
      onRefresh: _load,
      color: AppColors.primaryGold,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final isWide = constraints.maxWidth >= 760;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _buildPeriodSelector(theme, isAr),
              const SizedBox(height: 14),
              if (isWide) ..._buildWideLayout(theme, isAr) else ..._buildNarrowLayout(theme, isAr),
              const SizedBox(height: 16),
            ],
          );
        },
      ),
    );
  }

  // ─── Layouts ────────────────────────────────────────────
  List<Widget> _buildWideLayout(ThemeData theme, bool isAr) {
    return [
      Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(child: _buildTopEmployees(theme, isAr)),
          const SizedBox(width: 12),
          Expanded(child: _buildDistributionByRule(theme, isAr)),
        ],
      ),
      const SizedBox(height: 12),
      _buildTrendChart(theme, isAr),
      const SizedBox(height: 12),
      Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(child: _buildApprovalRate(theme, isAr)),
          const SizedBox(width: 12),
          Expanded(child: _buildByDepartment(theme, isAr)),
        ],
      ),
    ];
  }

  List<Widget> _buildNarrowLayout(ThemeData theme, bool isAr) {
    return [
      _buildTopEmployees(theme, isAr),
      const SizedBox(height: 12),
      _buildDistributionByRule(theme, isAr),
      const SizedBox(height: 12),
      _buildTrendChart(theme, isAr),
      const SizedBox(height: 12),
      _buildApprovalRate(theme, isAr),
      const SizedBox(height: 12),
      _buildByDepartment(theme, isAr),
    ];
  }

  // ═══════════════════════════════════════════════════════
  // Period Selector
  // ═══════════════════════════════════════════════════════
  Widget _buildPeriodSelector(ThemeData theme, bool isAr) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: _AnalyticsPeriod.values.map((p) {
          final isActive = _period == p;
          final label = switch (p) {
            _AnalyticsPeriod.last30 => isAr ? '30 يوم' : '30 days',
            _AnalyticsPeriod.last90 => isAr ? '90 يوم' : '90 days',
            _AnalyticsPeriod.lastYear => isAr ? 'سنة' : 'Year',
          };
          return Expanded(
            child: InkWell(
              onTap: () {
                setState(() => _period = p);
                _load();
              },
              borderRadius: BorderRadius.circular(6),
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 8),
                decoration: BoxDecoration(
                  color: isActive ? theme.cardColor : Colors.transparent,
                  borderRadius: BorderRadius.circular(6),
                  border: isActive
                      ? Border.all(
                          color: AppColors.primaryGold.withValues(alpha: 0.3),
                        )
                      : null,
                ),
                child: Text(
                  label,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: isActive
                        ? AppColors.primaryGold
                        : theme.hintColor,
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  // ═══════════════════════════════════════════════════════
  // 1. Top Employees
  // ═══════════════════════════════════════════════════════
  Widget _buildTopEmployees(ThemeData theme, bool isAr) {
    final byEmp = <String, double>{};
    for (final b in _bonuses) {
      final name = b.employee?.fullName ?? '—';
      byEmp[name] = (byEmp[name] ?? 0) + b.amount;
    }
    final sorted = byEmp.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final top = sorted.take(5).toList();
    final maxValue = top.isEmpty ? 1.0 : top.first.value;

    return _AnalyticsCard(
      icon: Icons.emoji_events_rounded,
      iconColor: AppColors.primaryGold,
      title: isAr ? 'أعلى الموظفين مكافآت' : 'Top employees',
      subtitle: _periodLabel(context),
      meta: '${top.length} ${isAr ? "موظفين" : "employees"}',
      child: top.isEmpty
          ? _miniEmpty(theme, isAr ? 'لا يوجد موظفين' : 'No employees')
          : Column(
              children: top.asMap().entries.map((e) {
                final rank = e.key + 1;
                final entry = e.value;
                final pct = maxValue > 0 ? entry.value / maxValue : 0.0;
                final medalColor = switch (rank) {
                  1 => AppColors.primaryGold,
                  2 => theme.hintColor,
                  3 => AppColors.invoicePurchaseScrap,
                  _ => theme.hintColor.withValues(alpha: 0.5),
                };
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 5),
                  child: Row(
                    children: [
                      Container(
                        width: 22,
                        height: 22,
                        decoration: BoxDecoration(
                          color: medalColor.withValues(alpha: 0.15),
                          shape: BoxShape.circle,
                          border: Border.all(
                            color: medalColor.withValues(alpha: 0.35),
                            width: 0.5,
                          ),
                        ),
                        child: Center(
                          child: Text(
                            '$rank',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w800,
                              color: medalColor,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 80,
                        child: Text(
                          entry.key,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: theme.textTheme.bodyLarge?.color,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(3),
                          child: LinearProgressIndicator(
                            value: pct,
                            minHeight: 5,
                            backgroundColor:
                                theme.dividerColor.withValues(alpha: 0.3),
                            valueColor: AlwaysStoppedAnimation<Color>(
                              rank == 1
                                  ? AppColors.primaryGold
                                  : medalColor,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 56,
                        child: Text(
                          _formatCurrency(entry.value),
                          textAlign: TextAlign.end,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            color: AppColors.primaryGold,
                            fontFeatures: const [FontFeature.tabularFigures()],
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              }).toList(),
            ),
    );
  }

  // ═══════════════════════════════════════════════════════
  // 2. Distribution by Rule (Donut)
  // ═══════════════════════════════════════════════════════
  Widget _buildDistributionByRule(ThemeData theme, bool isAr) {
    final byRule = <String, double>{};
    for (final b in _bonuses) {
      final key = b.bonusRule?.name ?? (isAr ? 'بدون قاعدة' : 'No rule');
      byRule[key] = (byRule[key] ?? 0) + b.amount;
    }
    final sorted = byRule.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final top = sorted.take(4).toList();
    final total = byRule.values.fold<double>(0, (s, v) => s + v);

    final colors = [
      AppColors.primaryGold,
      AppColors.success,
      AppColors.info,
      AppColors.invoicePurchaseNew,
    ];

    return _AnalyticsCard(
      icon: Icons.donut_large_rounded,
      iconColor: AppColors.invoicePurchaseNew,
      title: isAr ? 'التوزيع حسب القاعدة' : 'By rule',
      subtitle: '${isAr ? "الإجمالي" : "Total"} ${_formatCurrency(total)}',
      child: top.isEmpty
          ? _miniEmpty(theme, isAr ? 'لا توجد بيانات' : 'No data')
          : Row(
              children: [
                SizedBox(
                  width: 90,
                  height: 90,
                  child: PieChart(
                    PieChartData(
                      sectionsSpace: 1.5,
                      centerSpaceRadius: 24,
                      startDegreeOffset: -90,
                      sections: top.asMap().entries.map((e) {
                        final i = e.key;
                        final entry = e.value;
                        return PieChartSectionData(
                          value: entry.value,
                          color: colors[i % colors.length],
                          title: '',
                          radius: 18,
                          showTitle: false,
                          borderSide: BorderSide(
                            color: theme.cardColor,
                            width: 1.5,
                          ),
                        );
                      }).toList(),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: top.asMap().entries.map((e) {
                      final i = e.key;
                      final entry = e.value;
                      final pct = total > 0 ? (entry.value / total) * 100 : 0.0;
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 3),
                        child: Row(
                          children: [
                            Container(
                              width: 8,
                              height: 8,
                              decoration: BoxDecoration(
                                color: colors[i % colors.length],
                                shape: BoxShape.circle,
                              ),
                            ),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                entry.key,
                                style: TextStyle(
                                  fontSize: 10.5,
                                  color: theme.textTheme.bodyMedium?.color,
                                ),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            Text(
                              '${pct.toStringAsFixed(0)}%',
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w800,
                                color: colors[i % colors.length],
                                fontFeatures: const [FontFeature.tabularFigures()],
                              ),
                            ),
                          ],
                        ),
                      );
                    }).toList(),
                  ),
                ),
              ],
            ),
    );
  }

  // ═══════════════════════════════════════════════════════
  // 3. Trend Chart (last 6 months)
  // ═══════════════════════════════════════════════════════
  Widget _buildTrendChart(ThemeData theme, bool isAr) {
    final now = DateTime.now();
    final months = List.generate(6, (i) {
      final m = DateTime(now.year, now.month - 5 + i, 1);
      return m;
    });

    final monthTotals = <double>[];
    for (final m in months) {
      final next = DateTime(m.year, m.month + 1, 1);
      final total = _bonuses
          .where((b) =>
              b.periodStart.isAfter(m.subtract(const Duration(days: 1))) &&
              b.periodStart.isBefore(next))
          .fold<double>(0, (s, b) => s + b.amount);
      monthTotals.add(total);
    }

    final maxValue = monthTotals.isEmpty
        ? 1.0
        : monthTotals.reduce(math.max);
    final lastValue = monthTotals.isNotEmpty ? monthTotals.last : 0.0;
    final prevValue =
        monthTotals.length >= 2 ? monthTotals[monthTotals.length - 2] : 0.0;
    final pctChange = prevValue > 0
        ? ((lastValue - prevValue) / prevValue * 100)
        : null;

    final monthFmt = DateFormat.MMM(isAr ? 'ar' : 'en');

    return _AnalyticsCard(
      icon: Icons.trending_up_rounded,
      iconColor: AppColors.info,
      title: isAr ? 'اتجاه المكافآت' : 'Bonuses trend',
      subtitle: isAr ? 'آخر 6 شهور' : 'Last 6 months',
      meta: pctChange != null
          ? '${pctChange >= 0 ? "▲" : "▼"} ${pctChange.abs().toStringAsFixed(1)}%'
          : null,
      metaColor: pctChange != null
          ? (pctChange >= 0 ? AppColors.success : AppColors.error)
          : null,
      child: maxValue == 0
          ? _miniEmpty(theme, isAr ? 'لا توجد بيانات' : 'No data')
          : SizedBox(
              height: 130,
              child: BarChart(
                BarChartData(
                  alignment: BarChartAlignment.spaceAround,
                  maxY: maxValue * 1.15,
                  gridData: FlGridData(
                    show: true,
                    drawVerticalLine: false,
                    horizontalInterval: maxValue / 3,
                    getDrawingHorizontalLine: (_) => FlLine(
                      color: theme.dividerColor.withValues(alpha: 0.3),
                      strokeWidth: 0.5,
                      dashArray: [4, 4],
                    ),
                  ),
                  borderData: FlBorderData(show: false),
                  titlesData: FlTitlesData(
                    show: true,
                    leftTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false)),
                    rightTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false)),
                    topTitles: const AxisTitles(
                        sideTitles: SideTitles(showTitles: false)),
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 22,
                        getTitlesWidget: (value, meta) {
                          final i = value.toInt();
                          if (i < 0 || i >= months.length) {
                            return const SizedBox.shrink();
                          }
                          return Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              monthFmt.format(months[i]),
                              style: TextStyle(
                                fontSize: 9.5,
                                color: theme.hintColor,
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                  barTouchData: BarTouchData(
                    enabled: true,
                    touchTooltipData: BarTouchTooltipData(
                      getTooltipColor: (_) =>
                          AppColors.primaryGold.withValues(alpha: 0.95),
                      tooltipPadding:
                          const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      getTooltipItem: (group, _, rod, _) {
                        return BarTooltipItem(
                          _formatCurrency(rod.toY),
                          const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w800,
                            fontSize: 11,
                          ),
                        );
                      },
                    ),
                  ),
                  barGroups: monthTotals.asMap().entries.map((e) {
                    final i = e.key;
                    final value = e.value;
                    final isLast = i == monthTotals.length - 1;
                    return BarChartGroupData(
                      x: i,
                      barRods: [
                        BarChartRodData(
                          toY: value,
                          gradient: LinearGradient(
                            begin: Alignment.bottomCenter,
                            end: Alignment.topCenter,
                            colors: isLast
                                ? [
                                    AppColors.primaryGold,
                                    AppColors.darkGold,
                                  ]
                                : [
                                    AppColors.primaryGold
                                        .withValues(alpha: 0.5),
                                    AppColors.primaryGold
                                        .withValues(alpha: 0.7),
                                  ],
                          ),
                          width: 18,
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(4),
                          ),
                        ),
                      ],
                    );
                  }).toList(),
                ),
              ),
            ),
    );
  }

  // ═══════════════════════════════════════════════════════
  // 4. Approval Rate
  // ═══════════════════════════════════════════════════════
  Widget _buildApprovalRate(ThemeData theme, bool isAr) {
    final approved = _bonuses.where((b) => b.status == 'approved').length;
    final paid = _bonuses.where((b) => b.status == 'paid').length;
    final rejected = _bonuses.where((b) => b.status == 'rejected').length;
    final pending = _bonuses.where((b) => b.status == 'pending').length;
    final total = approved + paid + rejected;
    final rate = total > 0 ? ((approved + paid) / total * 100) : 0.0;

    return _AnalyticsCard(
      icon: Icons.verified_rounded,
      iconColor: AppColors.success,
      title: isAr ? 'معدل الاعتماد' : 'Approval rate',
      subtitle: isAr ? 'من المعالجة' : 'of processed',
      child: Row(
        children: [
          // Ring
          SizedBox(
            width: 80,
            height: 80,
            child: Stack(
              alignment: Alignment.center,
              children: [
                SizedBox(
                  width: 80,
                  height: 80,
                  child: CircularProgressIndicator(
                    value: rate / 100,
                    strokeWidth: 8,
                    backgroundColor:
                        theme.dividerColor.withValues(alpha: 0.3),
                    valueColor: AlwaysStoppedAnimation<Color>(
                      rate >= 75
                          ? AppColors.success
                          : rate >= 50
                              ? AppColors.warning
                              : AppColors.error,
                    ),
                  ),
                ),
                Text(
                  '${rate.toStringAsFixed(0)}%',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: rate >= 75
                        ? AppColors.success
                        : rate >= 50
                            ? AppColors.warning
                            : AppColors.error,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              mainAxisSize: MainAxisSize.min,
              children: [
                _statRow(theme, Icons.check_circle_rounded,
                    AppColors.success, isAr ? 'معتمدة' : 'Approved', '$approved'),
                const SizedBox(height: 5),
                _statRow(theme, Icons.task_alt_rounded,
                    AppColors.primaryGold, isAr ? 'مدفوعة' : 'Paid', '$paid'),
                const SizedBox(height: 5),
                _statRow(theme, Icons.cancel_rounded, AppColors.error,
                    isAr ? 'مرفوضة' : 'Rejected', '$rejected'),
                const SizedBox(height: 5),
                _statRow(
                    theme,
                    Icons.pending_actions_rounded,
                    AppColors.warning,
                    isAr ? 'معلّقة' : 'Pending',
                    '$pending'),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _statRow(ThemeData theme, IconData icon, Color color, String label,
      String value) {
    return Row(
      children: [
        Icon(icon, size: 13, color: color),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            label,
            style: TextStyle(
              fontSize: 10.5,
              color: theme.textTheme.bodyMedium?.color,
            ),
          ),
        ),
        Text(
          value,
          style: TextStyle(
            fontSize: 11.5,
            fontWeight: FontWeight.w800,
            color: color,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      ],
    );
  }

  // ═══════════════════════════════════════════════════════
  // 5. By Department
  // ═══════════════════════════════════════════════════════
  Widget _buildByDepartment(ThemeData theme, bool isAr) {
    final byDept = <String, List<double>>{};
    for (final b in _bonuses) {
      final dept = b.employee?.department ?? (isAr ? 'غير محدد' : 'Unspecified');
      byDept.putIfAbsent(dept, () => []).add(b.amount);
    }
    final sorted = byDept.entries.map((e) {
      final avg = e.value.isEmpty
          ? 0.0
          : e.value.reduce((a, b) => a + b) / e.value.length;
      return MapEntry(e.key, avg);
    }).toList()
      ..sort((a, b) => b.value.compareTo(a.value));

    final top = sorted.take(5).toList();
    final maxValue = top.isEmpty ? 1.0 : top.first.value;

    final colors = [
      AppColors.primaryGold,
      AppColors.success,
      AppColors.info,
      AppColors.invoicePurchaseNew,
      AppColors.invoiceSaleScrap,
    ];

    return _AnalyticsCard(
      icon: Icons.business_center_rounded,
      iconColor: AppColors.invoiceSaleScrap,
      title: isAr ? 'متوسط لكل قسم' : 'Avg by department',
      subtitle: '${top.length} ${isAr ? "أقسام" : "departments"}',
      child: top.isEmpty
          ? _miniEmpty(theme, isAr ? 'لا توجد أقسام' : 'No departments')
          : Column(
              children: top.asMap().entries.map((e) {
                final i = e.key;
                final entry = e.value;
                final pct = maxValue > 0 ? entry.value / maxValue : 0.0;
                final color = colors[i % colors.length];
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 5),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 80,
                        child: Text(
                          entry.key,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: theme.textTheme.bodyLarge?.color,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(3),
                          child: LinearProgressIndicator(
                            value: pct,
                            minHeight: 5,
                            backgroundColor:
                                theme.dividerColor.withValues(alpha: 0.3),
                            valueColor: AlwaysStoppedAnimation<Color>(color),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 56,
                        child: Text(
                          _formatCurrency(entry.value),
                          textAlign: TextAlign.end,
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            color: color,
                            fontFeatures: const [FontFeature.tabularFigures()],
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              }).toList(),
            ),
    );
  }

  // ═══════════════════════════════════════════════════════
  // Helpers
  // ═══════════════════════════════════════════════════════
  Widget _miniEmpty(ThemeData theme, String label) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 24),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.bar_chart_rounded,
              size: 32,
              color: theme.hintColor.withValues(alpha: 0.5),
            ),
            const SizedBox(height: 6),
            Text(
              label,
              style: TextStyle(
                fontSize: 11,
                color: theme.hintColor,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmpty(ThemeData theme, bool isAr) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              color: AppColors.primaryGold.withValues(alpha: 0.10),
              shape: BoxShape.circle,
            ),
            child: Icon(
              Icons.insights_rounded,
              size: 32,
              color: AppColors.primaryGold,
            ),
          ),
          const SizedBox(height: 14),
          Text(
            isAr ? 'لا توجد بيانات للتحليل' : 'No data to analyze',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: theme.textTheme.bodyLarge?.color,
            ),
          ),
          const SizedBox(height: 4),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              isAr
                  ? 'ستظهر التحليلات بمجرد إنشاء أول مجموعة من المكافآت'
                  : 'Analytics will appear once bonuses are created',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 12,
                color: theme.hintColor,
              ),
            ),
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _load,
            icon: const Icon(Icons.refresh_rounded, size: 16),
            label: Text(isAr ? 'تحديث' : 'Refresh'),
          ),
        ],
      ),
    );
  }

  Widget _buildError(ThemeData theme, bool isAr) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline_rounded,
              size: 48, color: AppColors.error.withValues(alpha: 0.7)),
          const SizedBox(height: 12),
          Text(
            isAr ? 'تعذّر تحميل التحليلات' : 'Failed to load analytics',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: theme.textTheme.bodyLarge?.color,
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _load,
            icon: const Icon(Icons.refresh_rounded, size: 16),
            label: Text(isAr ? 'إعادة المحاولة' : 'Try again'),
          ),
        ],
      ),
    );
  }
}


// ═══════════════════════════════════════════════════════════════
// Reusable Analytics Card
// ═══════════════════════════════════════════════════════════════
class _AnalyticsCard extends StatelessWidget {
  final IconData icon;
  final Color iconColor;
  final String title;
  final String? subtitle;
  final String? meta;
  final Color? metaColor;
  final Widget child;

  const _AnalyticsCard({
    required this.icon,
    required this.iconColor,
    required this.title,
    this.subtitle,
    this.meta,
    this.metaColor,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: theme.cardColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: theme.dividerColor.withValues(alpha: 0.4),
          width: 0.5,
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.02),
            blurRadius: 6,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: iconColor.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(7),
                ),
                child: Icon(icon, size: 15, color: iconColor),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      title,
                      style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w700,
                        color: theme.textTheme.bodyLarge?.color,
                      ),
                    ),
                    if (subtitle != null) ...[
                      const SizedBox(height: 1),
                      Text(
                        subtitle!,
                        style: TextStyle(
                          fontSize: 10,
                          color: theme.hintColor,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (meta != null)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 7,
                    vertical: 2.5,
                  ),
                  decoration: BoxDecoration(
                    color: (metaColor ?? theme.hintColor)
                        .withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    meta!,
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      color: metaColor ?? theme.hintColor,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }
}
