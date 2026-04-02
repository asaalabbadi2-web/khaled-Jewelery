import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;

/// A compact, always-dark horizontal gold price strip.
///
/// Designed to sit directly below any AppBar and display live spot price,
/// per-karat sell/buy grid, change badge, and relative timestamp.
///
/// Colors are fixed dark (#1a1200) regardless of the app theme because
/// a dark ticker is the standard gold-market convention.
class GoldPriceBar extends StatelessWidget {
  final double? goldPrice;
  final double? goldPriceOpening;
  final DateTime? goldPriceDate;
  final double exchangeRate;
  final int mainKarat;
  final bool isUpdating;
  final VoidCallback? onRefresh;

  static const _karats = [24, 22, 21, 18];

  // ── Palette ────────────────────────────────────────────────────────
  static const _bg = Color(0xFF1A1200);
  static const _gold = Color(0xFFF5C842);
  static const _white55 = Color(0x8CFFFFFF); // 55%
  static const _white45 = Color(0x73FFFFFF); // 45%
  static const _white35 = Color(0x59FFFFFF); // 35%
  static const _white25 = Color(0x40FFFFFF); // 25%
  static const _white10 = Color(0x1AFFFFFF); // 10%
  static const _borderBottom = Color(0x26F5C842); // rgba(245,200,66,0.15)
  static const _colDivider = Color(0x0FFFFFFF); // rgba(255,255,255,0.06)
  static const _upGreen = Color(0xFF5DCAA5);
  static const _upBg = Color(0x261D9E75); // rgba(29,158,117,0.15)
  static const _dnRed = Color(0xFFF09595);
  static const _dnBg = Color(0x26E24B4A); // rgba(226,75,74,0.15)
  static const _dnBorder = Color(0x4DE24B4A); // rgba(226,75,74,0.30)
  static const _upBorder = Color(0x4D1D9E75);
  static const _k21Tint = Color(0x0FF5C842); // rgba(245,200,66,0.06)

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

  // ── Helpers ─────────────────────────────────────────────────────────
  double _gramPrice(double oz, int k) =>
      (oz / 31.1035) * (k / 24.0) * exchangeRate;

  String _fmt(double v) => NumberFormat('#,##0.##', 'en').format(v);

  String _sinceLabel() {
    if (goldPriceDate == null) return '';
    final diff = DateTime.now().difference(goldPriceDate!);
    if (diff.inMinutes < 1) return 'الآن';
    if (diff.inHours < 1) return 'منذ ${diff.inMinutes} د';
    if (diff.inHours < 24) return 'منذ ${diff.inHours} س';
    return DateFormat('dd/MM HH:mm', 'en').format(goldPriceDate!);
  }

  @override
  Widget build(BuildContext context) {
    final oz = goldPrice;
    final opening = goldPriceOpening;

    // ── Change ──────────────────────────────────────────────────────
    double? changeAbs;
    double? changePct;
    bool priceUp = true;
    if (oz != null && opening != null && opening > 0) {
      changeAbs = oz - opening;
      changePct = (changeAbs / opening) * 100.0;
      priceUp = changeAbs >= 0;
    }
    final bigChange = changePct != null && changePct.abs() >= 1.0;

    // SAR per gram for main karat
    final sarPerGram = oz != null ? _gramPrice(oz, mainKarat) : null;

    return Directionality(
      textDirection: TextDirection.ltr, // fixed layout regardless of locale
      child: Container(
        decoration: const BoxDecoration(
          color: _bg,
          border: Border(
            bottom: BorderSide(color: _borderBottom, width: 0.5),
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            // ── Ounce price block ─────────────────────────────────
            _OunceBlock(
              oz: oz,
              sarPerGram: sarPerGram,
              mainKarat: mainKarat,
              changeAbs: changeAbs,
              changePct: changePct,
              priceUp: priceUp,
              fmt: _fmt,
              isUpdating: isUpdating,
              onRefresh: onRefresh,
            ),

            // ── Karat grid ────────────────────────────────────────
            Expanded(
              child: _KaratGrid(
                oz: oz,
                karats: _karats,
                mainKarat: mainKarat,
                gramPrice: _gramPrice,
                fmt: _fmt,
              ),
            ),

            // ── Right: timestamp + alert ──────────────────────────
            _RightBlock(
              sinceLabel: _sinceLabel(),
              bigChange: bigChange,
              changePct: changePct,
              priceUp: priceUp,
            ),
          ],
        ),
      ),
    );
  }
}

// ── Sub-widgets ─────────────────────────────────────────────────────────

class _OunceBlock extends StatelessWidget {
  final double? oz;
  final double? sarPerGram;
  final int mainKarat;
  final double? changeAbs;
  final double? changePct;
  final bool priceUp;
  final String Function(double) fmt;
  final bool isUpdating;
  final VoidCallback? onRefresh;

  const _OunceBlock({
    required this.oz,
    required this.sarPerGram,
    required this.mainKarat,
    required this.changeAbs,
    required this.changePct,
    required this.priceUp,
    required this.fmt,
    required this.isUpdating,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    final upC = GoldPriceBar._upGreen;
    final dnC = GoldPriceBar._dnRed;
    final changeC = changePct == null ? GoldPriceBar._white35 : (priceUp ? upC : dnC);
    final changeBg = changePct == null
        ? Colors.transparent
        : (priceUp ? GoldPriceBar._upBg : GoldPriceBar._dnBg);
    final changeBorder = changePct == null
        ? Colors.transparent
        : (priceUp ? GoldPriceBar._upBorder : GoldPriceBar._dnBorder);

    final absStr = changeAbs != null
        ? '${priceUp ? '+' : ''}${fmt(changeAbs!)}'
        : null;
    final pctStr = changePct != null
        ? '(${priceUp ? '+' : ''}${changePct!.toStringAsFixed(2)}%)'
        : null;

    return Container(
      constraints: const BoxConstraints(minWidth: 160),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: const BoxDecoration(
        border: Border(
          right: BorderSide(color: GoldPriceBar._white10, width: 0.5),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: [
          // USD price
          Row(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Text(
                oz != null ? '\$${fmt(oz!)}' : '—',
                style: const TextStyle(
                  color: GoldPriceBar._gold,
                  fontSize: 22,
                  fontWeight: FontWeight.w500,
                  fontFamily: 'Cairo',
                  letterSpacing: -0.3,
                ),
              ),
              const SizedBox(width: 8),
              // Refresh icon
              isUpdating
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 1.5,
                        valueColor: AlwaysStoppedAnimation(GoldPriceBar._gold),
                      ),
                    )
                  : GestureDetector(
                      onTap: onRefresh,
                      child: const Icon(
                        Icons.refresh_rounded,
                        color: GoldPriceBar._white35,
                        size: 14,
                      ),
                    ),
            ],
          ),
          // SAR per gram
          if (sarPerGram != null) ...[
            const SizedBox(height: 1),
            Directionality(
              textDirection: TextDirection.rtl,
              child: Text(
                '${fmt(sarPerGram!)} ر.س/جم $mainKarat',
                style: const TextStyle(
                  color: GoldPriceBar._white55,
                  fontSize: 11,
                  fontFamily: 'Cairo',
                ),
              ),
            ),
          ],
          // Change badge
          if (absStr != null && pctStr != null) ...[
            const SizedBox(height: 5),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: changeBg,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: changeBorder, width: 0.5),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    priceUp ? Icons.arrow_upward : Icons.arrow_downward,
                    color: changeC,
                    size: 10,
                  ),
                  const SizedBox(width: 3),
                  Text(
                    '$absStr  $pctStr',
                    style: TextStyle(
                      color: changeC,
                      fontSize: 10,
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
  final double? oz;
  final List<int> karats;
  final int mainKarat;
  final double Function(double, int) gramPrice;
  final String Function(double) fmt;

  const _KaratGrid({
    required this.oz,
    required this.karats,
    required this.mainKarat,
    required this.gramPrice,
    required this.fmt,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 0),
      child: Row(
        children: karats.asMap().entries.map((entry) {
          final idx = entry.key;
          final k = entry.value;
          final isMain = k == mainKarat;
          final sell = oz != null ? gramPrice(oz!, k) : null;
          final buy = sell != null ? sell * 0.98 : null;

          return Expanded(
            child: Container(
              decoration: BoxDecoration(
                color: isMain ? GoldPriceBar._k21Tint : Colors.transparent,
                border: idx > 0
                    ? const Border(
                        left: BorderSide(
                          color: GoldPriceBar._colDivider,
                          width: 0.5,
                        ),
                      )
                    : null,
                borderRadius: isMain ? BorderRadius.circular(6) : null,
              ),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 8),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                mainAxisSize: MainAxisSize.min,
                children: [
                  // Karat label
                  Text(
                    '$k',
                    style: TextStyle(
                      color: isMain ? GoldPriceBar._gold : GoldPriceBar._white35,
                      fontSize: 9.5,
                      fontWeight: isMain ? FontWeight.w700 : FontWeight.w400,
                      fontFamily: 'Cairo',
                    ),
                  ),
                  const SizedBox(height: 2),
                  // Sell price
                  Text(
                    sell != null ? fmt(sell) : '—',
                    style: TextStyle(
                      color: isMain ? GoldPriceBar._gold : Colors.white,
                      fontSize: 12.5,
                      fontWeight: FontWeight.w500,
                      fontFamily: 'Cairo',
                    ),
                    textAlign: TextAlign.center,
                    overflow: TextOverflow.ellipsis,
                  ),
                  // Buy price (dimmer)
                  Text(
                    buy != null ? fmt(buy) : '—',
                    style: const TextStyle(
                      color: GoldPriceBar._white45,
                      fontSize: 10.5,
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

class _RightBlock extends StatelessWidget {
  final String sinceLabel;
  final bool bigChange;
  final double? changePct;
  final bool priceUp;

  const _RightBlock({
    required this.sinceLabel,
    required this.bigChange,
    required this.changePct,
    required this.priceUp,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 130),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: const BoxDecoration(
        border: Border(
          left: BorderSide(color: GoldPriceBar._white10, width: 0.5),
        ),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          // Smart alert — only when |change| >= 1%
          if (bigChange && changePct != null) ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
              decoration: BoxDecoration(
                color: priceUp ? GoldPriceBar._upBg : GoldPriceBar._dnBg,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(
                  color: priceUp ? GoldPriceBar._upBorder : GoldPriceBar._dnBorder,
                  width: 0.5,
                ),
              ),
              child: Directionality(
                textDirection: TextDirection.rtl,
                child: Text(
                  priceUp
                      ? 'ارتفع ${changePct!.abs().toStringAsFixed(1)}%\nراجع أسعار البيع'
                      : 'انخفض ${changePct!.abs().toStringAsFixed(1)}%\nراجع أسعار الشراء',
                  style: TextStyle(
                    color: priceUp ? GoldPriceBar._upGreen : GoldPriceBar._dnRed,
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    fontFamily: 'Cairo',
                    height: 1.4,
                  ),
                  textAlign: TextAlign.right,
                ),
              ),
            ),
            const SizedBox(height: 5),
          ],
          // Relative timestamp
          if (sinceLabel.isNotEmpty)
            Directionality(
              textDirection: TextDirection.rtl,
              child: Text(
                sinceLabel,
                style: const TextStyle(
                  color: GoldPriceBar._white25,
                  fontSize: 9.5,
                  fontFamily: 'Cairo',
                ),
                textAlign: TextAlign.right,
              ),
            ),
        ],
      ),
    );
  }
}
