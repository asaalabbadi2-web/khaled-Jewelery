import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;

import '../theme/app_theme.dart';

class GoldPriceBar extends StatelessWidget {
  final double? goldPrice;
  final double? goldPriceOpening;
  final DateTime? goldPriceDate;
  final double exchangeRate;
  final int mainKarat;
  final bool isUpdating;
  final VoidCallback? onRefresh;

  const GoldPriceBar({
    super.key,
    this.goldPrice,
    this.goldPriceOpening,
    this.goldPriceDate,
    this.exchangeRate = 3.75,
    this.mainKarat = 21,
    this.isUpdating = false,
    this.onRefresh,
  });

  List<int> _otherKarats(int main) {
    const all = [18, 21, 22, 24];
    return all.where((k) => k != main).toList();
  }

  double _gramPrice(double ouncePrice, int karat) =>
      (ouncePrice / 31.1035) * (karat / 24.0) * exchangeRate;

  String _formatPrice(double value) => NumberFormat('#,##0.00', 'en').format(value);

  String _formatPercent(double? value) {
    final normalized = value ?? 0;
    return '${normalized.abs().toStringAsFixed(1)}%';
  }

  double? _changePercent() {
    if (goldPrice == null || goldPriceOpening == null || goldPriceOpening == 0) {
      return null;
    }
    return ((goldPrice! - goldPriceOpening!) / goldPriceOpening!) * 100;
  }

  String _relativeTimeLabel() {
    if (goldPriceDate == null) return 'منذ لحظات';
    final diff = DateTime.now().difference(goldPriceDate!);
    if (diff.inMinutes < 1) return 'منذ لحظات';
    if (diff.inHours < 1) return 'منذ ${diff.inMinutes} دقيقة';
    if (diff.inHours < 24) return 'منذ ${diff.inHours} ساعة';
    return DateFormat('dd/MM HH:mm', 'en').format(goldPriceDate!);
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final palette = _GoldBarPalette(isDark: isDark);
    final changePercent = _changePercent();
    final isUp = (changePercent ?? 0) >= 0;

    return Directionality(
      textDirection: TextDirection.rtl,
      child: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topRight,
            end: Alignment.bottomLeft,
            colors: [palette.surface3, palette.surface],
          ),
          border: Border(
            bottom: BorderSide(color: palette.divider, width: 1),
          ),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth <= 1100;

            if (compact) {
              return _buildPrimaryCard(
                palette: palette,
                ouncePrice: goldPrice,
                changePercent: changePercent,
                isUp: isUp,
              );
            }

            return Row(
              children: [
                _buildRefreshBlock(
                  palette: palette,
                  label: _relativeTimeLabel(),
                ),
                const SizedBox(width: 14),
                Expanded(
                  flex: 22,
                  child: _buildPrimaryCard(
                    palette: palette,
                    ouncePrice: goldPrice,
                    changePercent: changePercent,
                    isUp: isUp,
                  ),
                ),
                ..._otherKarats(mainKarat).asMap().entries.expand((entry) {
                  final idx = entry.key;
                  final k = entry.value;
                  const colors = [
                    Color(0xFFFF6B6B),
                    Color(0xFF4ECDC4),
                    Color(0xFF9B59B6),
                    Color(0xFF2ECC71),
                  ];
                  return [
                    const SizedBox(width: 14),
                    Expanded(
                      flex: 10,
                      child: _buildOtherKaratCard(
                        palette: palette,
                        karat: k,
                        color: colors[idx % colors.length],
                        ouncePrice: goldPrice,
                        trendText: _formatPercent(changePercent),
                        isUp: isUp,
                      ),
                    ),
                  ];
                }),
                const SizedBox(width: 14),
                _buildOunceBlock(
                  palette: palette,
                  ouncePrice: goldPrice,
                  openingPrice: goldPriceOpening,
                  isUp: isUp,
                  changePercent: changePercent,
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildRefreshBlock({
    required _GoldBarPalette palette,
    required String label,
  }) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        InkWell(
          onTap: onRefresh,
          borderRadius: BorderRadius.circular(999),
          child: Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: palette.surface2,
              shape: BoxShape.circle,
            ),
            child: Center(
              child: isUpdating
                  ? SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 1.8,
                        valueColor: AlwaysStoppedAnimation<Color>(palette.textMuted),
                      ),
                    )
                  : Icon(Icons.refresh_rounded, size: 18, color: palette.textMuted),
            ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(
            fontSize: 9.5,
            color: palette.textSoft,
            fontFamily: 'Cairo',
          ),
        ),
      ],
    );
  }

  Widget _buildPrimaryCard({
    required _GoldBarPalette palette,
    required double? ouncePrice,
    required double? changePercent,
    required bool isUp,
  }) {
    final sell = ouncePrice != null ? _gramPrice(ouncePrice, mainKarat) : null;
    final buy = sell != null ? sell * 0.98 : null;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [
            palette.lightGold,
            palette.primaryGold.withValues(alpha: 0.15),
          ],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: palette.primaryGold, width: 1.5),
        boxShadow: [
          BoxShadow(
            color: palette.darkGold.withValues(alpha: 0.15),
            blurRadius: 10,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsetsDirectional.only(start: 12),
            decoration: BoxDecoration(
              border: Border(
                left: BorderSide(
                  color: palette.primaryGold.withValues(alpha: 0.4),
                ),
              ),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(
                    color: palette.primaryGold,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Center(
                    child: Text(
                      '${mainKarat}K',
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                        fontSize: 12,
                        fontFamily: 'Cairo',
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 4),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    'الأساسي',
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w700,
                      color: palette.darkGold,
                      fontFamily: 'Cairo',
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Row(
              children: [
                Expanded(
                  child: _buildPrimaryValue(
                    palette: palette,
                    label: 'بيع / جم',
                    value: sell,
                    unit: 'ريال',
                    color: AppColors.success,
                    changePercent: _formatPercent(changePercent),
                    isUp: isUp,
                  ),
                ),
                const SizedBox(width: 20),
                Expanded(
                  child: _buildPrimaryValue(
                    palette: palette,
                    label: 'شراء / جم',
                    value: buy,
                    unit: 'ريال',
                    color: const Color(0xFF5E35B1),
                    changePercent: _formatPercent(changePercent),
                    isUp: isUp,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 14),
          SizedBox(
            width: 150,
            height: 44,
            child: Stack(
              children: [
                Positioned(
                  top: 0,
                  right: 0,
                  child: Text(
                    'آخر 24س',
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w600,
                      color: palette.textSoft,
                      fontFamily: 'Cairo',
                    ),
                  ),
                ),
                Positioned.fill(
                  top: 12,
                  child: CustomPaint(
                    painter: _SparklinePainter(color: palette.darkGold),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPrimaryValue({
    required _GoldBarPalette palette,
    required String label,
    required double? value,
    required String unit,
    required Color color,
    required String changePercent,
    required bool isUp,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: 10,
            color: palette.textMuted,
            fontWeight: FontWeight.w600,
            fontFamily: 'Cairo',
          ),
        ),
        const SizedBox(height: 2),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(
              value != null ? _formatPrice(value) : '—',
              style: TextStyle(
                fontSize: 21,
                fontWeight: FontWeight.w900,
                color: color,
                fontFamily: 'Cairo',
                height: 1,
              ),
            ),
            const SizedBox(width: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
              decoration: BoxDecoration(
                color: (isUp ? AppColors.success : AppColors.error).withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(3),
              ),
              child: Text(
                '${isUp ? '▲' : '▼'} $changePercent',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: isUp ? AppColors.success : AppColors.error,
                  fontFamily: 'Cairo',
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 3),
        Text(
          unit,
          style: TextStyle(
            fontSize: 10,
            color: palette.textSoft,
            fontFamily: 'Cairo',
          ),
        ),
      ],
    );
  }

  Widget _buildOtherKaratCard({
    required _GoldBarPalette palette,
    required int karat,
    required Color color,
    required double? ouncePrice,
    required String trendText,
    required bool isUp,
  }) {
    final sell = ouncePrice != null ? _gramPrice(ouncePrice, karat) : null;
    final buy = sell != null ? sell * 0.98 : null;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: palette.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: palette.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Row(
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      'عيار $karat',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: palette.text,
                        fontFamily: 'Cairo',
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                decoration: BoxDecoration(
                  color: (isUp ? AppColors.success : AppColors.error).withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(3),
                ),
                child: Text(
                  '${isUp ? '▲' : '▼'} $trendText',
                  style: TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    color: isUp ? AppColors.success : AppColors.error,
                    fontFamily: 'Cairo',
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Text(
                sell != null ? _formatPrice(sell) : '—',
                style: TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w700,
                  color: AppColors.success,
                  fontFamily: 'Cairo',
                ),
              ),
              Text(
                ' / ',
                style: TextStyle(
                  fontSize: 11,
                  color: palette.textSoft,
                  fontFamily: 'Cairo',
                ),
              ),
              Text(
                buy != null ? _formatPrice(buy) : '—',
                style: const TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF5E35B1),
                  fontFamily: 'Cairo',
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildOunceBlock({
    required _GoldBarPalette palette,
    required double? ouncePrice,
    required double? openingPrice,
    required bool isUp,
    required double? changePercent,
  }) {
    final amount = ouncePrice != null && openingPrice != null
        ? (ouncePrice - openingPrice).abs()
        : null;

    return Container(
      width: 150,
      padding: const EdgeInsetsDirectional.only(start: 14),
      decoration: BoxDecoration(
        border: Border(
          left: BorderSide(color: palette.divider),
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [palette.primaryGold, palette.darkGold],
              ),
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Icon(Icons.currency_exchange, color: Colors.white, size: 18),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'الأونصة',
                  style: TextStyle(
                    fontSize: 10,
                    color: palette.textSoft,
                    fontWeight: FontWeight.w600,
                    fontFamily: 'Cairo',
                  ),
                ),
                Text(
                  ouncePrice != null ? '\$${_formatPrice(ouncePrice)}' : '—',
                  style: TextStyle(
                    fontSize: 14,
                    color: palette.text,
                    fontWeight: FontWeight.w800,
                    fontFamily: 'Cairo',
                  ),
                ),
                Text(
                  amount != null && changePercent != null
                      ? '${isUp ? '▲' : '▼'} ${_formatPrice(amount)} (${changePercent.abs().toStringAsFixed(2)}%)'
                      : '—',
                  style: TextStyle(
                    fontSize: 10.5,
                    color: isUp ? AppColors.success : AppColors.error,
                    fontWeight: FontWeight.w700,
                    fontFamily: 'Cairo',
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _GoldBarPalette {
  final bool isDark;

  _GoldBarPalette({required this.isDark});

  Color get primaryGold => const Color(0xFFD4AF37);
  Color get darkGold => const Color(0xFFB8860B);
  Color get lightGold => const Color(0xFFF4E4C1);
  Color get surface => isDark ? const Color(0xFF2D2D2D) : Colors.white;
  Color get surface2 => isDark ? const Color(0xFF252525) : const Color(0xFFF5F5F5);
  Color get surface3 => isDark ? const Color(0xFF333028) : const Color(0xFFFAF8F2);
  Color get text => isDark ? const Color(0xFFE8E8E8) : const Color(0xFF212121);
  Color get textMuted => isDark ? const Color(0xFFBDBDBD) : const Color(0xFF616161);
  Color get textSoft => isDark ? const Color(0xFF757575) : const Color(0xFF9E9E9E);
  Color get divider => isDark ? const Color(0xFF3D3D3D) : const Color(0xFFE0E0E0);
  Color get border => isDark ? const Color(0xFF3D3D3D) : const Color(0xFFE0E0E0);
}

class _SparklinePainter extends CustomPainter {
  final Color color;

  const _SparklinePainter({required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final points = <Offset>[
      Offset(0, size.height * 0.75),
      Offset(size.width * 0.10, size.height * 0.65),
      Offset(size.width * 0.20, size.height * 0.70),
      Offset(size.width * 0.30, size.height * 0.50),
      Offset(size.width * 0.40, size.height * 0.60),
      Offset(size.width * 0.50, size.height * 0.40),
      Offset(size.width * 0.60, size.height * 0.45),
      Offset(size.width * 0.70, size.height * 0.28),
      Offset(size.width * 0.80, size.height * 0.33),
      Offset(size.width * 0.90, size.height * 0.18),
      Offset(size.width, size.height * 0.22),
    ];

    final fillPath = Path()..moveTo(points.first.dx, size.height);
    for (final point in points) {
      fillPath.lineTo(point.dx, point.dy);
    }
    fillPath
      ..lineTo(size.width, size.height)
      ..close();

    final fillPaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [
          color.withValues(alpha: 0.40),
          color.withValues(alpha: 0.0),
        ],
      ).createShader(Offset.zero & size);

    final strokePaint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    final linePath = Path()..moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      linePath.lineTo(point.dx, point.dy);
    }

    canvas.drawPath(fillPath, fillPaint);
    canvas.drawPath(linePath, strokePaint);
    canvas.drawCircle(points.last, 3, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _SparklinePainter oldDelegate) =>
      oldDelegate.color != color;
}
