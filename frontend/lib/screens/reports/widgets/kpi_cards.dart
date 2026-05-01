import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;

import '../../../../theme/app_theme.dart';

// ─── shared card wrapper ──────────────────────────────────────────────────────
Widget _kpiCardWrapper({
  required BuildContext context,
  required Widget child,
  required double Function(double) scale,
  VoidCallback? onTap,
}) {
  final theme = Theme.of(context);
  final isDark = theme.brightness == Brightness.dark;
  return GestureDetector(
    onTap: onTap,
    child: Container(
      padding: EdgeInsets.all(scale(12)),
      decoration: BoxDecoration(
        color: isDark ? theme.cardColor : Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: isDark
            ? Border.all(
                color: AppColors.primaryGold.withValues(alpha: 0.22),
                width: 1,
              )
            : Border.all(
                color: AppColors.primaryGold.withValues(alpha: 0.45),
                width: 1.2,
              ),
        boxShadow: isDark
            ? [
                BoxShadow(
                  color: AppColors.primaryGold.withValues(alpha: 0.09),
                  blurRadius: 16,
                ),
              ]
            : [
                BoxShadow(
                  color: AppColors.primaryGold.withValues(alpha: 0.15),
                  blurRadius: 14,
                  offset: const Offset(0, 4),
                ),
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.04),
                  blurRadius: 6,
                  offset: const Offset(0, 2),
                ),
              ],
      ),
      child: child,
    ),
  );
}

// ─── Karat Distribution Card ──────────────────────────────────────────────────
class KaratDistributionCard extends StatelessWidget {
  final Map<String, dynamic> goldByKarat;
  final bool isArabic;
  final double Function(double) scale;
  final NumberFormat weightFormat;

  const KaratDistributionCard({
    super.key,
    required this.goldByKarat,
    required this.isArabic,
    required this.scale,
    required this.weightFormat,
  });

  double _asDouble(dynamic v) => v is num ? v.toDouble() : 0.0;
  String _fmt(double v) => '${weightFormat.format(v)} ${isArabic ? "جم" : "g"}';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final k18 = _asDouble(goldByKarat['18k']);
    final k21 = _asDouble(goldByKarat['21k']);
    final k22 = _asDouble(goldByKarat['22k']);
    final k24 = _asDouble(goldByKarat['24k']);
    final total = k18 + k21 + k22 + k24;

    return _kpiCardWrapper(
      context: context,
      scale: scale,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.pie_chart, color: AppColors.primaryGold, size: scale(20)),
              SizedBox(width: scale(6)),
              Text(
                isArabic ? 'توزيع العيارات' : 'Karat Mix',
                style: theme.textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontSize: scale(12),
                ),
              ),
            ],
          ),
          SizedBox(height: scale(12)),
          if (total == 0)
            Center(
              child: Text(
                isArabic ? 'لا يوجد ذهب' : 'No gold',
                style: theme.textTheme.bodySmall?.copyWith(color: theme.hintColor),
              ),
            )
          else
            Row(
              children: [
                SizedBox(
                  width: scale(70),
                  height: scale(70),
                  child: PieChart(
                    PieChartData(
                      sectionsSpace: 1,
                      centerSpaceRadius: scale(18),
                      sections: [
                        PieChartSectionData(value: k24, color: AppColors.primaryGold, radius: scale(15), showTitle: false),
                        PieChartSectionData(value: k22, color: Colors.amber.shade600, radius: scale(15), showTitle: false),
                        PieChartSectionData(value: k21, color: Colors.orange.shade600, radius: scale(15), showTitle: false),
                        PieChartSectionData(value: k18, color: Colors.deepOrange.shade400, radius: scale(15), showTitle: false),
                      ],
                    ),
                  ),
                ),
                SizedBox(width: scale(10)),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _legendItem('24K', k24, AppColors.primaryGold, total),
                      _legendItem('22K', k22, Colors.amber.shade600, total),
                      _legendItem('21K', k21, Colors.orange.shade600, total),
                      _legendItem('18K', k18, Colors.deepOrange.shade400, total),
                    ],
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _legendItem(String label, double value, Color color, double total) {
    final pct = total > 0 ? (value / total * 100).toStringAsFixed(0) : '0';
    return Padding(
      padding: EdgeInsets.only(bottom: scale(2)),
      child: Row(
        children: [
          Container(
            width: scale(9),
            height: scale(9),
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          SizedBox(width: scale(6)),
          Expanded(
            child: Text(
              '$label: ${_fmt(value)} • $pct%',
              style: TextStyle(fontSize: scale(11)),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Liquidity Breakdown Card ─────────────────────────────────────────────────
class LiquidityBreakdownCard extends StatelessWidget {
  final Map<String, dynamic> liquidity;
  final bool isArabic;
  final double Function(double) scale;
  final NumberFormat currencyFormat;

  const LiquidityBreakdownCard({
    super.key,
    required this.liquidity,
    required this.isArabic,
    required this.scale,
    required this.currencyFormat,
  });

  double _asDouble(dynamic v) => v is num ? v.toDouble() : 0.0;
  String _fmt(double v) => currencyFormat.format(v);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cashInHand = _asDouble(liquidity['cash_in_hand']);
    final cashInBanks = _asDouble(liquidity['cash_in_banks']);
    final receivables = _asDouble(liquidity['receivables']);
    final total = cashInHand + cashInBanks + receivables;

    return _kpiCardWrapper(
      context: context,
      scale: scale,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.water_drop, color: Colors.blue, size: scale(20)),
              SizedBox(width: scale(6)),
              Text(
                isArabic ? 'مركز السيولة' : 'Liquidity',
                style: theme.textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontSize: scale(12),
                ),
              ),
            ],
          ),
          SizedBox(height: scale(12)),
          _row(context, isArabic ? 'نقدية' : 'Cash', cashInHand, Colors.green, total),
          SizedBox(height: scale(4)),
          _row(context, isArabic ? 'بنوك' : 'Banks', cashInBanks, Colors.blue, total),
          SizedBox(height: scale(4)),
          _row(context, isArabic ? 'ذمم' : 'Receiv.', receivables, Colors.orange, total),
        ],
      ),
    );
  }

  Widget _row(BuildContext context, String label, double value, Color color, double total) {
    final pct = total > 0 ? value / total : 0.0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: TextStyle(fontSize: scale(11))),
            Text(_fmt(value), style: TextStyle(fontSize: scale(11), fontWeight: FontWeight.bold)),
          ],
        ),
        SizedBox(height: scale(2)),
        ClipRRect(
          borderRadius: BorderRadius.circular(scale(2)),
          child: LinearProgressIndicator(
            value: pct,
            minHeight: scale(4),
            backgroundColor: color.withValues(alpha: 0.15),
            valueColor: AlwaysStoppedAnimation<Color>(color),
          ),
        ),
      ],
    );
  }
}
