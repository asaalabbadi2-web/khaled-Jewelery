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

  static const _baseKarats = [24, 22, 21, 18];
  static const _significantChangeThresholdPct = 0.5;
  static const _displayZeroEpsilon = 0.00005;

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

  double _gramPrice(double ouncePrice, int karat) =>
      (ouncePrice / 31.1035) * (karat / 24.0) * exchangeRate;

  String _formatOunce(double value) =>
      NumberFormat('#,##0.00', 'en').format(value);

  String _formatPrice(double value) =>
      NumberFormat('#,##0.00', 'en').format(value);

  String _relativeTimeLabel() {
    if (goldPriceDate == null) return '';

    final diff = DateTime.now().difference(goldPriceDate!);
    if (diff.inMinutes < 1) return 'منذ لحظات';
    if (diff.inHours < 1) return 'منذ ${diff.inMinutes} دقيقة';
    if (diff.inHours < 24) return 'منذ ${diff.inHours} ساعة';
    return DateFormat('dd/MM HH:mm', 'en').format(goldPriceDate!);
  }

  List<int> _displayKarats() {
    final karats = {..._baseKarats, mainKarat}.toList()..sort();
    return karats;
  }

  double _normalizeDelta(double value) {
    return value.abs() < _displayZeroEpsilon ? 0.0 : value;
  }

  String _formatDelta(
    double value, {
    String suffix = '',
    bool includePlus = true,
  }) {
    final normalized = _normalizeDelta(value);
    final absolute = normalized.abs();
    final decimals = absolute > 0 && absolute < 0.01 ? 4 : 2;
    final sign = normalized > 0
        ? (includePlus ? '+' : '')
        : normalized < 0
        ? '-'
        : '';
    return '$sign${absolute.toStringAsFixed(decimals)}$suffix';
  }

  @override
  Widget build(BuildContext context) {
    final palette = _GoldPriceBarPalette.forBrightness(
      Theme.of(context).brightness == Brightness.dark,
    );

    final ouncePrice = goldPrice;
    final openingPrice = goldPriceOpening;
    final displayKarats = _displayKarats();

    double? changeAmount;
    double? changePercent;
    var priceUp = true;
    if (ouncePrice != null && openingPrice != null && openingPrice > 0) {
      final rawChangeAmount = ouncePrice - openingPrice;
      final rawChangePercent = (rawChangeAmount / openingPrice) * 100.0;
      changeAmount = _normalizeDelta(rawChangeAmount);
      changePercent = _normalizeDelta(rawChangePercent);
      priceUp = rawChangeAmount >= 0;
    }

    final showAlert =
        changePercent != null &&
        changePercent.abs() >= _significantChangeThresholdPct;
    final sarPerGramMain = ouncePrice != null
        ? _gramPrice(ouncePrice, mainKarat)
        : null;

    return Directionality(
      textDirection: TextDirection.rtl,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final minContentWidth = displayKarats.length > 4 ? 920.0 : 840.0;
          final contentWidth = constraints.maxWidth < minContentWidth
              ? minContentWidth
              : constraints.maxWidth;

          return Container(
            decoration: BoxDecoration(
              color: palette.background,
              border: Border(
                bottom: BorderSide(color: palette.bottomBorder, width: 0.5),
              ),
              boxShadow: [
                BoxShadow(
                  color: palette.shadow,
                  blurRadius: 4,
                  offset: const Offset(0, 1),
                ),
              ],
            ),
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: SizedBox(
                width: contentWidth,
                child: IntrinsicHeight(
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _OunceBlock(
                        palette: palette,
                        ouncePrice: ouncePrice,
                        sarPerGramMain: sarPerGramMain,
                        mainKarat: mainKarat,
                        changeAmount: changeAmount,
                        changePercent: changePercent,
                        priceUp: priceUp,
                        formatDelta: _formatDelta,
                        formatOunce: _formatOunce,
                        formatPrice: _formatPrice,
                        isUpdating: isUpdating,
                        onRefresh: onRefresh,
                      ),
                      Expanded(
                        child: _KaratGrid(
                          palette: palette,
                          ouncePrice: ouncePrice,
                          karats: displayKarats,
                          mainKarat: mainKarat,
                          gramPrice: _gramPrice,
                          formatPrice: _formatPrice,
                        ),
                      ),
                      _MetaBlock(
                        palette: palette,
                        relativeTimeLabel: _relativeTimeLabel(),
                        showAlert: showAlert,
                        changePercent: changePercent,
                        priceUp: priceUp,
                        formatDelta: _formatDelta,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _OunceBlock extends StatelessWidget {
  final _GoldPriceBarPalette palette;
  final double? ouncePrice;
  final double? sarPerGramMain;
  final int mainKarat;
  final double? changeAmount;
  final double? changePercent;
  final bool priceUp;
  final String Function(double, {String suffix, bool includePlus}) formatDelta;
  final String Function(double) formatOunce;
  final String Function(double) formatPrice;
  final bool isUpdating;
  final VoidCallback? onRefresh;

  const _OunceBlock({
    required this.palette,
    required this.ouncePrice,
    required this.sarPerGramMain,
    required this.mainKarat,
    required this.changeAmount,
    required this.changePercent,
    required this.priceUp,
    required this.formatDelta,
    required this.formatOunce,
    required this.formatPrice,
    required this.isUpdating,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    final changeColor = priceUp
        ? GoldPriceBarColors.upText
        : GoldPriceBarColors.downText;
    final changeBg = priceUp
        ? GoldPriceBarColors.upBg
        : GoldPriceBarColors.downBg;
    final changeBorder = priceUp
        ? GoldPriceBarColors.upBorder
        : GoldPriceBarColors.downBorder;

    final amountText = changeAmount == null ? null : formatDelta(changeAmount!);
    final percentText = changePercent == null
        ? null
        : '(${formatDelta(changePercent!, suffix: '%')})';

    return Container(
      constraints: const BoxConstraints(minWidth: 210),
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: palette.line, width: 0.5)),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            'سعر الأونصة',
            style: TextStyle(
              color: palette.textMuted,
              fontSize: 10,
              fontFamily: 'Cairo',
            ),
          ),
          const SizedBox(height: 2),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                ouncePrice != null ? '\$${formatOunce(ouncePrice!)}' : '—',
                style: TextStyle(
                  color: palette.gold,
                  fontSize: 22,
                  fontWeight: FontWeight.w700,
                  fontFamily: 'Cairo',
                  letterSpacing: -0.25,
                ),
              ),
              const SizedBox(width: 8),
              isUpdating
                  ? SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 1.5,
                        valueColor: AlwaysStoppedAnimation<Color>(palette.gold),
                      ),
                    )
                  : InkWell(
                      onTap: onRefresh,
                      borderRadius: BorderRadius.circular(12),
                      child: Padding(
                        padding: const EdgeInsets.all(2),
                        child: Icon(
                          Icons.refresh_rounded,
                          color: palette.textMuted,
                          size: 15,
                        ),
                      ),
                    ),
            ],
          ),
          if (sarPerGramMain != null) ...[
            const SizedBox(height: 2),
            Text(
              '${formatPrice(sarPerGramMain!)} ر.س/جم عيار $mainKarat',
              style: TextStyle(
                color: palette.textSoft,
                fontSize: 11,
                fontFamily: 'Cairo',
              ),
            ),
          ],
          if (amountText != null && percentText != null) ...[
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
              decoration: BoxDecoration(
                color: changeBg,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: changeBorder, width: 0.8),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    priceUp
                        ? Icons.arrow_upward_rounded
                        : Icons.arrow_downward_rounded,
                    color: changeColor,
                    size: 11,
                  ),
                  const SizedBox(width: 3),
                  Text(
                    '$amountText $percentText',
                    style: TextStyle(
                      color: changeColor,
                      fontSize: 10.5,
                      fontWeight: FontWeight.w700,
                      fontFamily: 'Cairo',
                    ),
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

class _KaratGrid extends StatelessWidget {
  final _GoldPriceBarPalette palette;
  final double? ouncePrice;
  final List<int> karats;
  final int mainKarat;
  final double Function(double, int) gramPrice;
  final String Function(double) formatPrice;

  const _KaratGrid({
    required this.palette,
    required this.ouncePrice,
    required this.karats,
    required this.mainKarat,
    required this.gramPrice,
    required this.formatPrice,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        textDirection: TextDirection.ltr,
        children: karats.asMap().entries.map((entry) {
          final index = entry.key;
          final karat = entry.value;
          final isMain = karat == mainKarat;
          final sellPrice = ouncePrice != null
              ? gramPrice(ouncePrice!, karat)
              : null;
          final buyPrice = sellPrice != null ? sellPrice * 0.98 : null;

          return Expanded(
            child: Container(
              margin: const EdgeInsets.symmetric(horizontal: 1.5),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              decoration: BoxDecoration(
                color: isMain ? palette.goldSoft : Colors.transparent,
                borderRadius: BorderRadius.circular(8),
                border: isMain
                    ? Border.all(color: palette.goldBorder, width: 0.5)
                    : index > 0
                    ? Border(
                        right: BorderSide(color: palette.lineSoft, width: 0.5),
                      )
                    : null,
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'عيار $karat',
                    style: TextStyle(
                      color: isMain ? palette.gold : palette.textMuted,
                      fontSize: 10,
                      fontWeight: isMain ? FontWeight.w700 : FontWeight.w500,
                      fontFamily: 'Cairo',
                    ),
                    textAlign: TextAlign.center,
                  ),
                  if (isMain) ...[
                    const SizedBox(height: 3),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 6,
                        vertical: 1,
                      ),
                      decoration: BoxDecoration(
                        color: palette.goldSoft,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        'الرئيسي',
                        style: TextStyle(
                          color: palette.gold,
                          fontSize: 8,
                          fontWeight: FontWeight.w700,
                          fontFamily: 'Cairo',
                        ),
                      ),
                    ),
                  ],
                  const SizedBox(height: 5),
                  Text(
                    'بيع',
                    style: TextStyle(
                      color: isMain ? palette.gold : palette.text,
                      fontSize: 9.5,
                      fontWeight: FontWeight.w700,
                      fontFamily: 'Cairo',
                    ),
                  ),
                  const SizedBox(height: 1),
                  Text(
                    sellPrice != null ? formatPrice(sellPrice) : '—',
                    style: TextStyle(
                      color: isMain ? palette.gold : palette.text,
                      fontSize: isMain ? 15 : 14,
                      fontWeight: FontWeight.w800,
                      fontFamily: 'Cairo',
                    ),
                    textAlign: TextAlign.center,
                    overflow: TextOverflow.ellipsis,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'شراء',
                    style: TextStyle(
                      color: palette.textMuted,
                      fontSize: 8.5,
                      fontWeight: FontWeight.w500,
                      fontFamily: 'Cairo',
                    ),
                  ),
                  const SizedBox(height: 1),
                  Text(
                    buyPrice != null ? formatPrice(buyPrice) : '—',
                    style: TextStyle(
                      color: palette.textSoft,
                      fontSize: isMain ? 11.5 : 11,
                      fontWeight: FontWeight.w500,
                      fontFamily: 'Cairo',
                    ),
                    textAlign: TextAlign.center,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _MetaBlock extends StatelessWidget {
  final _GoldPriceBarPalette palette;
  final String relativeTimeLabel;
  final bool showAlert;
  final double? changePercent;
  final bool priceUp;
  final String Function(double, {String suffix, bool includePlus}) formatDelta;

  const _MetaBlock({
    required this.palette,
    required this.relativeTimeLabel,
    required this.showAlert,
    required this.changePercent,
    required this.priceUp,
    required this.formatDelta,
  });

  @override
  Widget build(BuildContext context) {
    final alertColor = priceUp
        ? GoldPriceBarColors.upText
        : GoldPriceBarColors.downText;
    final alertBg = priceUp
        ? GoldPriceBarColors.upBg
        : GoldPriceBarColors.downBg;
    final alertBorder = priceUp
        ? GoldPriceBarColors.upBorder
        : GoldPriceBarColors.downBorder;

    return Container(
      constraints: const BoxConstraints(minWidth: 168, maxWidth: 190),
      padding: const EdgeInsets.fromLTRB(12, 12, 16, 12),
      decoration: BoxDecoration(
        border: Border(right: BorderSide(color: palette.line, width: 0.5)),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (showAlert && changePercent != null) ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
              decoration: BoxDecoration(
                color: alertBg,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: alertBorder, width: 0.9),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    priceUp
                        ? Icons.trending_up_rounded
                        : Icons.trending_down_rounded,
                    color: alertColor,
                    size: 15,
                  ),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      priceUp
                          ? 'تنبيه سعر: ارتفع ${formatDelta(changePercent!.abs(), suffix: '%', includePlus: false)} - راجع أسعار البيع'
                          : 'تنبيه سعر: انخفض ${formatDelta(changePercent!.abs(), suffix: '%', includePlus: false)} - راجع أسعار الشراء',
                      style: TextStyle(
                        color: alertColor,
                        fontSize: 9.8,
                        fontWeight: FontWeight.w800,
                        fontFamily: 'Cairo',
                        height: 1.35,
                      ),
                      textAlign: TextAlign.right,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 6),
          ],
          if (relativeTimeLabel.isNotEmpty)
            Text(
              relativeTimeLabel,
              style: TextStyle(
                color: palette.textMuted,
                fontSize: 10,
                fontFamily: 'Cairo',
              ),
              textAlign: TextAlign.right,
            ),
        ],
      ),
    );
  }
}

class _GoldPriceBarPalette {
  final Color background;
  final Color gold;
  final Color goldSoft;
  final Color goldBorder;
  final Color text;
  final Color textSoft;
  final Color textMuted;
  final Color line;
  final Color lineSoft;
  final Color bottomBorder;
  final Color shadow;

  const _GoldPriceBarPalette({
    required this.background,
    required this.gold,
    required this.goldSoft,
    required this.goldBorder,
    required this.text,
    required this.textSoft,
    required this.textMuted,
    required this.line,
    required this.lineSoft,
    required this.bottomBorder,
    required this.shadow,
  });

  factory _GoldPriceBarPalette.forBrightness(bool isDark) {
    if (isDark) {
      return const _GoldPriceBarPalette(
        background: Color(0xFF1A1200),
        gold: Color(0xFFF5C842),
        goldSoft: Color(0x1AF5C842),
        goldBorder: Color(0x33F5C842),
        text: Colors.white,
        textSoft: Color(0xFFD8BC7A),
        textMuted: Color(0x99FFFFFF),
        line: Color(0x1FFFFFFF),
        lineSoft: Color(0x12FFFFFF),
        bottomBorder: Color(0x26F5C842),
        shadow: Color(0x14000000),
      );
    }

    return const _GoldPriceBarPalette(
      background: Color(0xFFF9F3E5),
      gold: AppColors.deepGold,
      goldSoft: Color(0x22D4AF37),
      goldBorder: Color(0x38D4AF37),
      text: Color(0xFF3A2908),
      textSoft: Color(0xFF6B5220),
      textMuted: Color(0xFF8D7340),
      line: Color(0x22D4AF37),
      lineSoft: Color(0x18D4AF37),
      bottomBorder: Color(0x30D4AF37),
      shadow: Color(0x12D4AF37),
    );
  }
}

class GoldPriceBarColors {
  static const upText = Color(0xFF0E5240);
  static const upBg = Color(0xFFD4F0E5);
  static const upBorder = Color(0xFF6FBD9F);
  static const downText = Color(0xFF7A1A14);
  static const downBg = Color(0xFFF8D5CE);
  static const downBorder = Color(0xFFC97A6E);
}
