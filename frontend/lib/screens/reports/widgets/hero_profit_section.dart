import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;

import '../../../../theme/app_theme.dart';

class HeroProfitSection extends StatelessWidget {
  final Map<String, dynamic> kpis;
  final Map<String, dynamic> liquidity;
  final Map<String, dynamic> salesPurchasesSummary;
  final bool isArabic;
  final double Function(double) scale;
  final NumberFormat currencyFormat;
  /// 'today' | 'month' | 'year'
  final String summaryPeriod;

  const HeroProfitSection({
    super.key,
    required this.kpis,
    required this.liquidity,
    required this.salesPurchasesSummary,
    required this.isArabic,
    required this.scale,
    required this.currencyFormat,
    required this.summaryPeriod,
  });

  double _asDouble(dynamic v) => v is num ? v.toDouble() : 0.0;
  double? _asDoubleOrNull(dynamic v) => v is num ? v.toDouble() : null;
  String _fmtC(double v) => currencyFormat.format(v);
  double _s(double v) => scale(v);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    final periodData = (salesPurchasesSummary[summaryPeriod] as Map<String, dynamic>?) ?? {};
    final salesData = (periodData['sales'] as Map<String, dynamic>?) ?? {};
    final purchasesData = (periodData['purchases'] as Map<String, dynamic>?) ?? {};
    final expensesData = (periodData['expenses'] as Map<String, dynamic>?) ?? {};

    final periodSales = _asDouble(salesData['total_value']);
    final periodPurchases = _asDouble(purchasesData['total_value']);
    final periodExpenses = _asDouble(expensesData['total_value']);
    final periodProfit = periodSales - periodPurchases - periodExpenses;
    final periodMargin = periodSales > 0 ? (periodProfit / periodSales) * 100 : null;
    final cashAvailable = _asDouble(liquidity['cash_available']);

    final vsYesterdayPct = summaryPeriod == 'today'
        ? _asDoubleOrNull(kpis['today_profit_vs_yesterday_pct'])
        : null;

    final isProfit = periodProfit >= 0;
    final profitColor = isProfit ? AppColors.success : Colors.red.shade600;

    final String periodTitle;
    switch (summaryPeriod) {
      case 'month':
        periodTitle = isArabic ? 'صافي ربح الشهر' : 'Monthly Net Profit';
        break;
      case 'year':
        periodTitle = isArabic ? 'صافي ربح السنة' : 'Yearly Net Profit';
        break;
      default:
        periodTitle = isArabic ? 'صافي ربح اليوم' : "Today's Net Profit";
    }

    String insightText;
    if (vsYesterdayPct != null) {
      final dir = vsYesterdayPct >= 0
          ? (isArabic ? 'ارتفع' : 'Up')
          : (isArabic ? 'انخفض' : 'Down');
      insightText = isArabic
          ? 'الربح $dir ${vsYesterdayPct.abs().toStringAsFixed(1)}% مقارنة بالأمس'
          : 'Profit $dir ${vsYesterdayPct.abs().toStringAsFixed(1)}% vs yesterday';
    } else if (isProfit) {
      insightText = isArabic ? 'النتيجة: ربح ✓' : 'Result: Profit ✓';
    } else {
      insightText = isArabic ? 'المصروفات تفوق المبيعات' : 'Expenses exceed sales';
    }

    return Padding(
      padding: EdgeInsets.fromLTRB(_s(16), _s(8), _s(16), 0),
      child: Container(
        padding: EdgeInsets.all(_s(20)),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topRight,
            end: Alignment.bottomLeft,
            colors: isProfit
                ? [AppColors.success.withValues(alpha: 0.10), theme.cardColor]
                : [Colors.red.shade600.withValues(alpha: 0.08), theme.cardColor],
          ),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: profitColor.withValues(alpha: 0.25), width: 1.5),
          boxShadow: [
            BoxShadow(
              color: profitColor.withValues(alpha: 0.08),
              blurRadius: 16,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  isProfit ? Icons.trending_up : Icons.trending_down,
                  color: profitColor,
                  size: _s(20),
                ),
                SizedBox(width: _s(6)),
                Text(
                  periodTitle,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: theme.textTheme.bodySmall?.color,
                  ),
                ),
                const Spacer(),
                if (vsYesterdayPct != null)
                  Container(
                    padding: EdgeInsets.symmetric(horizontal: _s(8), vertical: _s(3)),
                    decoration: BoxDecoration(
                      color: (vsYesterdayPct >= 0 ? Colors.green : Colors.red)
                          .withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          vsYesterdayPct >= 0 ? Icons.arrow_upward : Icons.arrow_downward,
                          size: _s(12),
                          color: vsYesterdayPct >= 0
                              ? Colors.green.shade700
                              : Colors.red.shade600,
                        ),
                        SizedBox(width: _s(2)),
                        Text(
                          '${vsYesterdayPct.abs().toStringAsFixed(1)}%',
                          style: TextStyle(
                            fontSize: _s(11),
                            fontWeight: FontWeight.bold,
                            color: vsYesterdayPct >= 0
                                ? Colors.green.shade700
                                : Colors.red.shade600,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            SizedBox(height: _s(10)),
            Text(
              _fmtC(periodProfit),
              style: theme.textTheme.displaySmall?.copyWith(
                fontWeight: FontWeight.w900,
                color: profitColor,
                fontSize: _s(30),
                letterSpacing: -0.5,
              ),
            ),
            if (periodMargin != null) ...[
              SizedBox(height: _s(4)),
              Container(
                padding: EdgeInsets.symmetric(horizontal: _s(8), vertical: _s(3)),
                decoration: BoxDecoration(
                  color: profitColor.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${periodMargin.toStringAsFixed(1)}% ${isArabic ? "هامش ربح" : "margin"}',
                  style: TextStyle(
                    fontSize: _s(11),
                    fontWeight: FontWeight.bold,
                    color: profitColor,
                  ),
                ),
              ),
            ],
            SizedBox(height: _s(10)),
            if (insightText.isNotEmpty)
              Row(
                children: [
                  Icon(Icons.lightbulb_outline, size: _s(13), color: theme.hintColor),
                  SizedBox(width: _s(4)),
                  Text(
                    insightText,
                    style: theme.textTheme.bodySmall?.copyWith(
                      fontSize: _s(11),
                      color: theme.hintColor,
                    ),
                  ),
                ],
              ),
            SizedBox(height: _s(14)),
            Wrap(
              spacing: _s(8),
              runSpacing: _s(6),
              children: [
                _chip(context, Icons.account_balance_wallet_outlined,
                    isArabic ? 'السيولة' : 'Cash', _fmtC(cashAvailable), AppColors.primaryGold),
                _chip(context, Icons.arrow_upward,
                    isArabic ? 'مبيعات' : 'Sales', _fmtC(periodSales), const Color(0xFF1B9E4B)),
                _chip(context, Icons.arrow_downward,
                    isArabic ? 'مشتريات' : 'Purch.', _fmtC(periodPurchases), Colors.orange.shade700),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _chip(BuildContext context, IconData icon, String label, String value, Color color) {
    final theme = Theme.of(context);
    return Container(
      padding: EdgeInsets.symmetric(horizontal: _s(10), vertical: _s(6)),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.18)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: _s(12), color: color),
          SizedBox(width: _s(4)),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: TextStyle(fontSize: _s(9), color: theme.hintColor)),
              Text(value, style: TextStyle(fontSize: _s(11), fontWeight: FontWeight.bold, color: color)),
            ],
          ),
        ],
      ),
    );
  }
}
