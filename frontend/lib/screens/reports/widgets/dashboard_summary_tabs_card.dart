import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;

import '../../../theme/app_theme.dart';
import '../../../utils/currency_utils.dart' as cu;

enum _SummaryTab { sales, purchases, scrap, expenses }

typedef _SummaryTabInfo = ({
  String label,
  int count,
  double value,
  double weight,
  Color color,
  IconData icon,
  Map<String, dynamic> data,
});

/// A compact operations summary card with internal tabs.
class DashboardSummaryTabsCard extends StatefulWidget {
  final Map<String, dynamic> periodData;
  final bool isArabic;
  final NumberFormat currencyFormat;
  final String currencySymbol;
  final bool currencyIsNewSar;
  final NumberFormat weightFormat;
  final double Function(double) scale;

  const DashboardSummaryTabsCard({
    super.key,
    required this.periodData,
    required this.isArabic,
    required this.currencyFormat,
    this.currencySymbol = 'ر.س',
    this.currencyIsNewSar = false,
    required this.weightFormat,
    required this.scale,
  });

  @override
  State<DashboardSummaryTabsCard> createState() =>
      _DashboardSummaryTabsCardState();
}

class _DashboardSummaryTabsCardState extends State<DashboardSummaryTabsCard> {
  _SummaryTab _activeTab = _SummaryTab.sales;

  Map<String, dynamic> get _periodData => widget.periodData;

  double _asDouble(dynamic v) => v is num ? v.toDouble() : 0.0;
  double _s(double v) => widget.scale(v);

  String _formatCurrency(num v) {
    final formatted = widget.currencyFormat.format(v);
    if (formatted.contains(widget.currencySymbol)) return formatted;
    return '$formatted ${widget.currencySymbol}';
  }

  Widget _currencyAwareText(
    String text, {
    TextStyle? style,
    TextOverflow? overflow,
  }) {
    return cu.SarAwareText(
      text,
      isNewSar: widget.currencyIsNewSar,
      style: style,
      overflow: overflow,
    );
  }

  String _formatWeight(num v) =>
      '${widget.weightFormat.format(v)} ${widget.isArabic ? "جم" : "g"}';

  double? _changePct(double current, double previous) {
    if (previous.abs() < 0.001) return null;
    return ((current - previous) / previous.abs()) * 100;
  }

  double? _prevTabValue(_SummaryTab tab) {
    final prev = const <String, dynamic>{};
    if (prev.isEmpty) return null;
    switch (tab) {
      case _SummaryTab.sales:
        return _asDouble((prev['sales'] as Map?)?['total_value']);
      case _SummaryTab.purchases:
        return _asDouble((prev['purchases'] as Map?)?['total_value']);
      case _SummaryTab.scrap:
        return _asDouble((prev['scrap_purchases'] as Map?)?['total_value']);
      case _SummaryTab.expenses:
        return _asDouble((prev['expenses'] as Map?)?['total_value']);
    }
  }
  Color _tabColor(_SummaryTab tab, ThemeData theme) {
    switch (tab) {
      case _SummaryTab.sales:
        return AppColors.success;
      case _SummaryTab.purchases:
        return AppColors.info;
      case _SummaryTab.scrap:
        return theme.colorScheme.secondary;
      case _SummaryTab.expenses:
        return AppColors.warning;
    }
  }

  _SummaryTabInfo _getTabInfo(_SummaryTab tab, ThemeData theme) {
    final isAr = widget.isArabic;
    switch (tab) {
      case _SummaryTab.sales:
        final d = (_periodData['sales'] as Map<String, dynamic>?) ?? {};
        return (
          label: isAr ? 'المبيعات' : 'Sales',
          count: (d['docs'] as int?) ?? 0,
          value: _asDouble(d['total_value']),
          weight: _asDouble(d['total_weight']),
          color: _tabColor(tab, theme),
          icon: Icons.trending_up_rounded,
          data: d,
        );
      case _SummaryTab.purchases:
        final d =
            (_periodData['purchases'] as Map<String, dynamic>?) ?? {};
        return (
          label: isAr ? 'المشتريات' : 'Purchases',
          count: (d['docs'] as int?) ?? 0,
          value: _asDouble(d['total_value']),
          weight: _asDouble(d['total_weight']),
          color: _tabColor(tab, theme),
          icon: Icons.trending_down_rounded,
          data: d,
        );
      case _SummaryTab.scrap:
        final d = (_periodData['scrap_purchases']
                as Map<String, dynamic>?) ??
            {};
        return (
          label: isAr ? 'الكسر' : 'Scrap',
          count: (d['docs'] as int?) ?? 0,
          value: _asDouble(d['total_value']),
          weight: _asDouble(d['total_weight']),
          color: _tabColor(tab, theme),
          icon: Icons.recycling_rounded,
          data: d,
        );
      case _SummaryTab.expenses:
        final d =
            (_periodData['expenses'] as Map<String, dynamic>?) ?? {};
        return (
          label: isAr ? 'المصروفات' : 'Expenses',
          count: (d['docs'] as int?) ?? 0,
          value: _asDouble(d['total_value']),
          weight: 0,
          color: _tabColor(tab, theme),
          icon: Icons.receipt_long_rounded,
          data: d,
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isAr = widget.isArabic;

    return Container(
      decoration: BoxDecoration(
        color: theme.cardColor,
        borderRadius: BorderRadius.circular(_s(16)),
        border: Border.all(
          color: theme.dividerColor.withValues(alpha: 0.25),
        ),
        boxShadow: [
          BoxShadow(
            color: AppColors.primaryGold.withValues(alpha: 0.06),
            blurRadius: 8,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(_s(16), _s(14), _s(16), _s(8)),
            child: Row(
              children: [
                Icon(
                  Icons.bar_chart_rounded,
                  size: _s(20),
                  color: AppColors.primaryGold,
                ),
                SizedBox(width: _s(8)),
                Expanded(
                  child: Text(
                    isAr ? 'ملخص العمليات' : 'Operations Summary',
                    style: TextStyle(
                      fontSize: _s(14),
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
          ),
          _buildTabsBar(theme),
          AnimatedSize(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 220),
              transitionBuilder: (child, animation) {
                return FadeTransition(
                  opacity: animation,
                  child: SlideTransition(
                    position: Tween<Offset>(
                      begin: const Offset(0.04, 0),
                      end: Offset.zero,
                    ).animate(animation),
                    child: child,
                  ),
                );
              },
              child: Padding(
                key: ValueKey(_activeTab),
                padding: EdgeInsets.all(_s(16)),
                child: _buildTabContent(_activeTab, theme),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTabsBar(ThemeData theme) {
    final isDark = theme.brightness == Brightness.dark;
    return Container(
      decoration: BoxDecoration(
        color: isDark
            ? theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.30)
            : theme.colorScheme.surfaceContainerLowest,
        border: Border(
          bottom: BorderSide(
            color: theme.dividerColor.withValues(alpha: 0.30),
          ),
        ),
      ),
      child: Row(
        children: _SummaryTab.values.map((tab) {
          final info = _getTabInfo(tab, theme);
          final isActive = _activeTab == tab;
          return Expanded(
            child: InkWell(
              onTap: () => setState(() => _activeTab = tab),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                padding: EdgeInsets.symmetric(
                  vertical: _s(11),
                  horizontal: _s(6),
                ),
                decoration: BoxDecoration(
                  color: isActive ? theme.cardColor : Colors.transparent,
                  border: Border(
                    bottom: BorderSide(
                      color: isActive ? info.color : Colors.transparent,
                      width: 2.5,
                    ),
                  ),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    if (info.count > 0) ...[
                      Container(
                        padding: EdgeInsets.symmetric(
                          horizontal: _s(5),
                          vertical: _s(1),
                        ),
                        decoration: BoxDecoration(
                          color: isActive
                              ? info.color.withValues(alpha: 0.15)
                              : theme.colorScheme.surfaceContainerHighest
                                  .withValues(alpha: 0.6),
                          borderRadius: BorderRadius.circular(_s(3)),
                        ),
                        child: Text(
                          '${info.count}',
                          style: TextStyle(
                            fontSize: _s(10),
                            fontWeight: FontWeight.w700,
                            color: isActive
                                ? info.color
                                : theme.textTheme.bodySmall?.color,
                          ),
                        ),
                      ),
                      SizedBox(width: _s(5)),
                    ],
                    Flexible(
                      child: Text(
                        info.label,
                        style: TextStyle(
                          fontSize: _s(12),
                          fontWeight: FontWeight.w600,
                          color: isActive
                              ? info.color
                              : theme.textTheme.bodySmall?.color,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildTabContent(_SummaryTab tab, ThemeData theme) {
    final info = _getTabInfo(tab, theme);
    final isAr = widget.isArabic;

    if (info.count == 0) {
      return _buildEmptyTab(info, theme);
    }

    final byKarat = (info.data['by_karat'] as List?) ?? [];
    final byUser = (info.data['by_user'] as List?) ?? [];
    final byAccount = (info.data['by_account'] as List?) ?? [];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildTopMetrics(info, tab, theme, isAr),
        SizedBox(height: _s(14)),
        if (tab != _SummaryTab.expenses && byKarat.isNotEmpty) ...[
          _buildSectionHeader(isAr ? 'توزيع العيارات' : 'By Karat', theme),
          _buildKaratList(byKarat, info.color, theme, isAr),
          SizedBox(height: _s(14)),
        ],
        if ((tab == _SummaryTab.sales || tab == _SummaryTab.purchases) &&
            byUser.isNotEmpty) ...[
          _buildSectionHeader(
            isAr ? 'أداء الموظفين' : 'Staff Performance',
            theme,
          ),
          _buildUsersList(byUser, info.color, theme, isAr),
        ],
        if (tab == _SummaryTab.expenses && byAccount.isNotEmpty) ...[
          _buildSectionHeader(isAr ? 'حسب الحساب' : 'By Account', theme),
          _buildAccountsList(byAccount, info.color, theme),
        ],
      ],
    );
  }

  Widget _buildTopMetrics(
    _SummaryTabInfo info,
    _SummaryTab tab,
    ThemeData theme,
    bool isAr,
  ) {
    final hasWeight = info.weight > 0;
    final docsColor = theme.colorScheme.secondary;

    final prevValue = _prevTabValue(tab);
    final changePct = prevValue != null ? _changePct(info.value, prevValue) : null;

    Widget metric({
      required String label,
      required String value,
      required String? sub,
      required Color color,
      required IconData icon,
      double? changePct,
    }) {
      return Container(
        padding: EdgeInsets.all(_s(11)),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.07),
          borderRadius: BorderRadius.circular(_s(10)),
          border: Border.all(color: color.withValues(alpha: 0.18)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: _s(13), color: color),
                SizedBox(width: _s(5)),
                Flexible(
                  child: Text(
                    label,
                    style: TextStyle(
                      fontSize: _s(10.5),
                      color: theme.textTheme.bodySmall?.color,
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                if (changePct != null) ...[
                  SizedBox(width: _s(4)),
                  _buildChangePill(changePct),
                ],
              ],
            ),
            SizedBox(height: _s(5)),
            _currencyAwareText(
              value,
              style: TextStyle(
                fontSize: _s(13),
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
            if (sub != null && sub.isNotEmpty) ...[
              SizedBox(height: _s(1)),
              _currencyAwareText(
                sub,
                style: TextStyle(
                  fontSize: _s(9.5),
                  color: theme.textTheme.bodySmall?.color,
                ),
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ],
        ),
      );
    }

    final avgValue = info.count > 0 ? info.value / info.count : 0.0;

    return Row(
      children: [
        Expanded(
          child: metric(
            label: isAr ? 'القيمة' : 'Value',
            value: _formatCurrency(info.value),
            sub: info.count > 0
                ? '${isAr ? "متوسط" : "Avg"} ${_formatCurrency(avgValue)}'
                : null,
            color: info.color,
            icon: Icons.payments_outlined,
            changePct: changePct,
          ),
        ),
        if (hasWeight) ...[
          SizedBox(width: _s(8)),
          Expanded(
            child: metric(
              label: isAr ? 'الوزن' : 'Weight',
              value: _formatWeight(info.weight),
              sub: info.count > 0
                  ? '${isAr ? "متوسط" : "Avg"} ${_formatWeight(info.weight / info.count)}'
                  : null,
              color: AppColors.primaryGold,
              icon: Icons.scale_outlined,
            ),
          ),
        ],
        SizedBox(width: _s(8)),
        Expanded(
          child: metric(
            label: isAr ? 'الفواتير' : 'Docs',
            value: '${info.count}',
            sub: null,
            color: docsColor,
            icon: Icons.description_outlined,
          ),
        ),
      ],
    );
  }

  Widget _buildChangePill(double pct) {
    final isUp = pct >= 0;
    final color = isUp ? AppColors.success : AppColors.error;
    return Container(
      padding: EdgeInsets.symmetric(horizontal: _s(4), vertical: _s(1)),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.13),
        borderRadius: BorderRadius.circular(_s(3)),
      ),
      child: Text(
        '${isUp ? '▲' : '▼'} ${pct.abs().toStringAsFixed(1)}%',
        style: TextStyle(
          fontSize: _s(8.5),
          fontWeight: FontWeight.w700,
          color: color,
          fontFamily: 'Cairo',
        ),
      ),
    );
  }

  Widget _buildSectionHeader(String title, ThemeData theme) {
    return Padding(
      padding: EdgeInsets.only(bottom: _s(8)),
      child: Row(
        children: [
          Container(
            width: _s(3),
            height: _s(11),
            decoration: BoxDecoration(
              color: AppColors.primaryGold,
              borderRadius: BorderRadius.circular(_s(2)),
            ),
          ),
          SizedBox(width: _s(8)),
          Text(
            title,
            style: TextStyle(
              fontSize: _s(11.5),
              fontWeight: FontWeight.w600,
              color: theme.textTheme.bodySmall?.color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildKaratList(
    List items,
    Color accent,
    ThemeData theme,
    bool isAr,
  ) {
    return Column(
      children: items.map((k) {
        final karat = k['karat'] as String? ?? '?';
        final weight = _asDouble(k['weight']);
        final value = _asDouble(k['value']);
        final karatColor = AppColors.karatColorFor(karat);
        return Padding(
          padding: EdgeInsets.symmetric(vertical: _s(5)),
          child: Row(
            children: [
              Container(
                padding: EdgeInsets.symmetric(
                  horizontal: _s(7),
                  vertical: _s(2),
                ),
                decoration: BoxDecoration(
                  color: karatColor.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(_s(4)),
                ),
                child: Text(
                  karat,
                  style: TextStyle(
                    fontSize: _s(11),
                    fontWeight: FontWeight.bold,
                    color: karatColor,
                  ),
                ),
              ),
              SizedBox(width: _s(8)),
              Expanded(
                child: Text(
                  _formatWeight(weight),
                  style: TextStyle(
                    fontSize: _s(11),
                    color: theme.textTheme.bodySmall?.color,
                  ),
                ),
              ),
              _currencyAwareText(
                _formatCurrency(value),
                style: TextStyle(
                  fontSize: _s(12),
                  fontWeight: FontWeight.w700,
                  color: accent,
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildUsersList(
    List items,
    Color accent,
    ThemeData theme,
    bool isAr,
  ) {
    final maxValue = items.take(5).fold<double>(
          0,
          (m, u) => _asDouble(u is Map ? u['value'] : 0) > m
              ? _asDouble(u['value'])
              : m,
        );

    return Column(
      children: items.take(5).toList().asMap().entries.map((entry) {
        final rank = entry.key + 1;
        final u = entry.value;
        final user = (u['user'] ?? '—').toString();
        final value = _asDouble(u['value']);
        final weight = _asDouble(u['weight']);
        final docs = (u['docs'] as int?) ?? 0;
        final pct = maxValue > 0 ? (value / maxValue).clamp(0.0, 1.0) : 0.0;

        final Color medalColor;
        switch (rank) {
          case 1:
            medalColor = AppColors.primaryGold;
            break;
          case 2:
            medalColor = const Color(0xFF9E9E9E); // silver
            break;
          case 3:
            medalColor = const Color(0xFFCD7F32); // bronze
            break;
          default:
            medalColor = theme.hintColor;
        }

        return Container(
          margin: EdgeInsets.only(bottom: _s(6)),
          padding: EdgeInsets.all(_s(8)),
          decoration: BoxDecoration(
            color: accent.withValues(alpha: 0.04),
            borderRadius: BorderRadius.circular(_s(8)),
            border: Border.all(color: accent.withValues(alpha: 0.14)),
          ),
          child: Column(
            children: [
              Row(
                children: [
                  if (rank == 1)
                    Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          '👑',
                          style: TextStyle(
                            fontSize: _s(9),
                            height: 1.1,
                          ),
                        ),
                        Container(
                          width: _s(22),
                          height: _s(22),
                          decoration: BoxDecoration(
                            color: medalColor.withValues(alpha: 0.09),
                            shape: BoxShape.circle,
                            border: Border.all(
                              color: medalColor.withValues(alpha: 0.28),
                              width: 1.0,
                            ),
                          ),
                          child: Center(
                            child: Text(
                              '1',
                              style: TextStyle(
                                fontSize: _s(10),
                                fontWeight: FontWeight.bold,
                                color: medalColor,
                              ),
                            ),
                          ),
                        ),
                      ],
                    )
                  else
                    Container(
                      width: _s(22),
                      height: _s(22),
                      decoration: BoxDecoration(
                        color: medalColor.withValues(alpha: 0.09),
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: medalColor.withValues(alpha: 0.28),
                          width: 1.0,
                        ),
                      ),
                      child: Center(
                        child: Text(
                          '$rank',
                          style: TextStyle(
                            fontSize: _s(10),
                            fontWeight: FontWeight.bold,
                            color: medalColor,
                          ),
                        ),
                      ),
                    ),
                  SizedBox(width: _s(8)),
                  Expanded(
                    child: Text(
                      user,
                      style: TextStyle(
                        fontSize: _s(11.5),
                        fontWeight: FontWeight.w600,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      _currencyAwareText(
                        _formatCurrency(value),
                        style: TextStyle(
                          fontSize: _s(12),
                          fontWeight: FontWeight.w700,
                          color: accent,
                        ),
                      ),
                      Text(
                        weight > 0
                            ? '${_formatWeight(weight)} · $docs ${isAr ? "فا" : "inv"}'
                            : '$docs ${isAr ? "فاتورة" : "inv"}',
                        style: TextStyle(
                          fontSize: _s(9.5),
                          color: theme.textTheme.bodySmall?.color,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              SizedBox(height: _s(6)),
              ClipRRect(
                borderRadius: BorderRadius.circular(_s(2)),
                child: LinearProgressIndicator(
                  value: pct,
                  minHeight: _s(3),
                  backgroundColor: accent.withValues(alpha: 0.10),
                  valueColor: AlwaysStoppedAnimation<Color>(
                    rank == 1 ? AppColors.primaryGold : accent,
                  ),
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildAccountsList(List items, Color accent, ThemeData theme) {
    return Column(
      children: items.take(8).map((e) {
        final acc = (e['account'] ?? '—').toString();
        final value = _asDouble(e['value']);
        return Padding(
          padding: EdgeInsets.symmetric(vertical: _s(5)),
          child: Row(
            children: [
              Icon(
                Icons.receipt_outlined,
                size: _s(13),
                color: accent.withValues(alpha: 0.6),
              ),
              SizedBox(width: _s(6)),
              Expanded(
                child: Text(
                  acc,
                  style: TextStyle(fontSize: _s(11.5)),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              _currencyAwareText(
                _formatCurrency(value),
                style: TextStyle(
                  fontSize: _s(12),
                  fontWeight: FontWeight.w700,
                  color: accent,
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildEmptyTab(_SummaryTabInfo info, ThemeData theme) {
    final isAr = widget.isArabic;
    return Padding(
      padding: EdgeInsets.symmetric(vertical: _s(28)),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: _s(48),
            height: _s(48),
            decoration: BoxDecoration(
              color: info.color.withValues(alpha: 0.08),
              shape: BoxShape.circle,
            ),
            child: Icon(info.icon, color: info.color, size: _s(22)),
          ),
          SizedBox(height: _s(10)),
          Text(
            isAr ? 'لا توجد ${info.label}' : 'No ${info.label}',
            style: TextStyle(
              fontSize: _s(12),
              color: theme.textTheme.bodySmall?.color,
              fontWeight: FontWeight.w500,
            ),
          ),
          SizedBox(height: _s(2)),
          Text(
            isAr
                ? 'لا توجد عمليات في هذه الفترة'
                : 'No transactions in this period',
            style: TextStyle(
              fontSize: _s(10.5),
              color: theme.textTheme.bodySmall?.color,
            ),
          ),
        ],
      ),
    );
  }
}
