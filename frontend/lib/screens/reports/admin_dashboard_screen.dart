import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';

import '../../api_service.dart';
import '../../providers/settings_provider.dart';
import 'system_alerts_screen.dart';

class AdminDashboardScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;

  const AdminDashboardScreen({
    super.key,
    required this.api,
    this.isArabic = true,
  });

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  Map<String, dynamic>? _response;
  bool _isLoading = false;
  String? _error;

  String _currencySymbol = 'ر.س';
  int _currencyDecimals = 2;

  late NumberFormat _currencyFormat;
  late NumberFormat _weightFormat;

  @override
  void initState() {
    super.initState();

    _currencyFormat = NumberFormat.currency(
      locale: widget.isArabic ? 'ar' : 'en',
      symbol: _currencySymbol,
      decimalDigits: _currencyDecimals,
    );
    _weightFormat = NumberFormat('#,##0.000');

    _loadData();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final settings = Provider.of<SettingsProvider>(context);

    final symbol = settings.currencySymbol;
    final decimals = settings.decimalPlaces;

    if (symbol != _currencySymbol || decimals != _currencyDecimals) {
      setState(() {
        _currencySymbol = symbol;
        _currencyDecimals = decimals;
        _currencyFormat = NumberFormat.currency(
          locale: widget.isArabic ? 'ar' : 'en',
          symbol: _currencySymbol,
          decimalDigits: _currencyDecimals,
        );
      });
    }
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final result = await widget.api.getAdminDashboard();
      if (!mounted) return;
      setState(() {
        _response = result;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  double _asDouble(dynamic value) {
    if (value is num) return value.toDouble();
    return 0.0;
  }

  int _asInt(dynamic value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return 0;
  }

  String _formatCurrency(num value) => _currencyFormat.format(value);

  String _formatWeight(num value) => '${_weightFormat.format(value)} جم';

  @override
  Widget build(BuildContext context) {
    final isArabic = widget.isArabic;

    final alerts =
        (_response?['alerts'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    final criticalCount = _asInt(alerts['critical_unreviewed_count']);

    return Directionality(
      textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        appBar: AppBar(
          title: Text(isArabic ? 'لوحة تحكم المدير' : 'Admin Dashboard'),
          actions: [
            _buildBellAction(criticalCount),
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: isArabic ? 'تحديث' : 'Refresh',
              onPressed: _isLoading ? null : _loadData,
            ),
          ],
        ),
        body: SafeArea(
          child: _isLoading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? _buildErrorState()
              : _buildContent(),
        ),
      ),
    );
  }

  Widget _buildErrorState() {
    final isArabic = widget.isArabic;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, size: 48, color: Colors.red.shade400),
          const SizedBox(height: 12),
          Text(
            isArabic ? 'تعذّر تحميل لوحة التحكم' : 'Failed to load dashboard',
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Text(
              _error ?? '',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.grey),
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _loadData,
            icon: const Icon(Icons.refresh),
            label: Text(isArabic ? 'إعادة المحاولة' : 'Try Again'),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    final isArabic = widget.isArabic;

    final kpis =
        (_response?['kpis'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    final series =
        (_response?['series'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    final alerts =
        (_response?['alerts'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    final valuation =
        (_response?['valuation'] as Map<String, dynamic>?) ??
        <String, dynamic>{};

    final cashBalance = _asDouble(kpis['cash_balance']);
    final goldPure24 = _asDouble(kpis['gold_pure_24k']);

    final salesToday =
        (kpis['sales_today'] as Map<String, dynamic>?) ?? <String, dynamic>{};
    final salesTodayValue = _asDouble(salesToday['net_value']);
    final salesTodayWeight = _asDouble(salesToday['net_weight']);
    final salesTodayDocs = _asInt(salesToday['documents']);

    final last7 = (series['last_7_days_sales'] as List?) ?? const [];

    final lastShift = alerts['last_shift_closing'] as Map<String, dynamic>?;

    final spotPrice = _asDouble(valuation['spot_price_24k_per_gram']);
    final inventoryValue = _asDouble(valuation['inventory_value']);

    return RefreshIndicator(
      onRefresh: _loadData,
      child: ListView(
        padding: const EdgeInsets.all(16),
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          Row(
            children: [
              Expanded(
                child: _buildKpiCard(
                  title: isArabic ? 'الرصيد النقدي' : 'Cash Balance',
                  value: _formatCurrency(cashBalance),
                  icon: Icons.account_balance_wallet_outlined,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: _buildKpiCard(
                  title: isArabic ? 'الذهب الصافي (24k)' : 'Pure Gold (24k)',
                  value: _formatWeight(goldPure24),
                  icon: Icons.auto_awesome,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _buildKpiCard(
            title: isArabic
                ? 'قيمة الذهب الصافي الآن'
                : 'Pure Gold Value (Now)',
            value: (inventoryValue > 0)
                ? _formatCurrency(inventoryValue)
                : (isArabic ? 'غير متاح' : 'N/A'),
            subtitle: (spotPrice > 0)
                ? (isArabic
                      ? 'بناءً على سعر البورصة الحالي: ${_formatCurrency(spotPrice)} / جم (24k)'
                      : 'Based on spot: ${_formatCurrency(spotPrice)} / g (24k)')
                : (isArabic
                      ? 'سعر البورصة غير متاح'
                      : 'Spot price unavailable'),
            icon: Icons.trending_up,
          ),
          const SizedBox(height: 12),
          _buildKpiCard(
            title: isArabic ? 'مبيعات اليوم' : 'Today Sales',
            value:
                '${_formatCurrency(salesTodayValue)} • ${_formatWeight(salesTodayWeight)}',
            subtitle: isArabic
                ? 'عدد الفواتير: $salesTodayDocs'
                : 'Documents: $salesTodayDocs',
            icon: Icons.point_of_sale_outlined,
          ),
          const SizedBox(height: 16),
          _buildChartCard(isArabic, last7),
          const SizedBox(height: 16),
          _buildAlertsCard(isArabic, lastShift),
        ],
      ),
    );
  }

  Widget _buildKpiCard({
    required String title,
    required String value,
    String? subtitle,
    required IconData icon,
  }) {
    final theme = Theme.of(context);

    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Icon(icon, color: theme.colorScheme.primary),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: theme.textTheme.titleMedium),
                  const SizedBox(height: 6),
                  Text(
                    value,
                    style: theme.textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  if (subtitle != null) ...[
                    const SizedBox(height: 6),
                    Text(
                      subtitle,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.hintColor,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBellAction(int criticalCount) {
    final theme = Theme.of(context);
    final badgeColor = theme.colorScheme.error;
    final showBadge = criticalCount > 0;
    final badgeText = criticalCount > 99 ? '99+' : '$criticalCount';

    return Padding(
      padding: const EdgeInsetsDirectional.only(end: 4),
      child: Stack(
        alignment: Alignment.center,
        children: [
          IconButton(
            icon: const Icon(Icons.notifications_none_outlined),
            tooltip: widget.isArabic ? 'تنبيهات' : 'Alerts',
            onPressed: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => SystemAlertsScreen(
                    api: widget.api,
                    isArabic: widget.isArabic,
                  ),
                ),
              );
              if (!mounted) return;
              await _loadData();
            },
          ),
          if (showBadge)
            PositionedDirectional(
              top: 8,
              end: 8,
              child: Container(
                constraints: const BoxConstraints(minWidth: 18, minHeight: 18),
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: badgeColor,
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(
                    color: theme.colorScheme.surface,
                    width: 2,
                  ),
                ),
                child: Text(
                  badgeText,
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: theme.colorScheme.onError,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildChartCard(bool isArabic, List<dynamic> series) {
    final theme = Theme.of(context);

    final points = <_DayPoint>[];
    for (final item in series) {
      if (item is Map<String, dynamic>) {
        final period = (item['period'] ?? '').toString();
        final netValue = _asDouble(item['net_value']);
        points.add(_DayPoint(period: period, netValue: netValue));
      }
    }

    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              isArabic ? 'صافي المبيعات آخر 7 أيام' : 'Net Sales (Last 7 Days)',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 12),
            SizedBox(
              height: 220,
              child: points.isEmpty
                  ? Center(
                      child: Text(
                        isArabic ? 'لا توجد بيانات' : 'No data',
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.hintColor,
                        ),
                      ),
                    )
                  : BarChart(
                      BarChartData(
                        alignment: BarChartAlignment.spaceAround,
                        maxY: _maxY(points),
                        gridData: const FlGridData(show: false),
                        borderData: FlBorderData(show: false),
                        titlesData: FlTitlesData(
                          leftTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false),
                          ),
                          rightTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false),
                          ),
                          topTitles: const AxisTitles(
                            sideTitles: SideTitles(showTitles: false),
                          ),
                          bottomTitles: AxisTitles(
                            sideTitles: SideTitles(
                              showTitles: true,
                              getTitlesWidget: (value, meta) {
                                final idx = value.toInt();
                                if (idx < 0 || idx >= points.length) {
                                  return const SizedBox.shrink();
                                }
                                final p = points[idx];
                                final label = _shortDateLabel(p.period);
                                return Padding(
                                  padding: const EdgeInsets.only(top: 8),
                                  child: Text(
                                    label,
                                    style: theme.textTheme.bodySmall?.copyWith(
                                      color: theme.hintColor,
                                    ),
                                  ),
                                );
                              },
                            ),
                          ),
                        ),
                        barGroups: List.generate(points.length, (i) {
                          return BarChartGroupData(
                            x: i,
                            barRods: [
                              BarChartRodData(
                                toY: points[i].netValue,
                                color: theme.colorScheme.primary,
                                width: 14,
                                borderRadius: BorderRadius.circular(4),
                              ),
                            ],
                          );
                        }),
                      ),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  double _maxY(List<_DayPoint> points) {
    double maxY = 0.0;
    for (final p in points) {
      if (p.netValue > maxY) maxY = p.netValue;
    }
    if (maxY <= 0) return 1;
    return maxY * 1.15;
  }

  String _shortDateLabel(String isoDate) {
    // isoDate expected: YYYY-MM-DD
    final parts = isoDate.split('-');
    if (parts.length != 3) return isoDate;
    return '${parts[2]}/${parts[1]}';
  }

  Widget _buildAlertsCard(bool isArabic, Map<String, dynamic>? lastShift) {
    final theme = Theme.of(context);

    final cashDiff = _asNullableDouble(lastShift?['cash_difference']);
    final goldDiff = _asNullableDouble(lastShift?['gold_pure_24k_difference']);

    final hasAny =
        (cashDiff != null && cashDiff.abs() > 0.0001) ||
        (goldDiff != null && goldDiff.abs() > 0.0001);

    return Card(
      elevation: 0,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              isArabic ? 'تنبيهات' : 'Alerts',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            if (!hasAny)
              Text(
                isArabic
                    ? 'لا توجد تنبيهات من آخر إغلاق وردية.'
                    : 'No alerts from the last shift closing.',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.hintColor,
                ),
              )
            else ...[
              if (cashDiff != null && cashDiff.abs() > 0.0001)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    Icons.warning_amber_rounded,
                    color: theme.colorScheme.error,
                  ),
                  title: Text(
                    isArabic
                        ? 'فرق نقدي في آخر إغلاق'
                        : 'Cash difference in last closing',
                  ),
                  subtitle: Text(
                    isArabic
                        ? 'الفرق: ${_formatCurrency(cashDiff)}'
                        : 'Diff: ${_formatCurrency(cashDiff)}',
                  ),
                ),
              if (goldDiff != null && goldDiff.abs() > 0.0001)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    Icons.warning_amber_rounded,
                    color: theme.colorScheme.error,
                  ),
                  title: Text(
                    isArabic
                        ? 'فرق ذهب صافي (24k) في آخر إغلاق'
                        : 'Pure gold (24k) diff in last closing',
                  ),
                  subtitle: Text(
                    isArabic
                        ? 'الفرق: ${_formatWeight(goldDiff)}'
                        : 'Diff: ${_formatWeight(goldDiff)}',
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }

  double? _asNullableDouble(dynamic value) {
    if (value == null) return null;
    if (value is num) return value.toDouble();
    return double.tryParse(value.toString());
  }
}

class _DayPoint {
  final String period;
  final double netValue;

  _DayPoint({required this.period, required this.netValue});
}
