import 'package:flutter/material.dart';

enum AppLogoVariant { gold, white }

class AppLogo extends StatelessWidget {
  const AppLogo({
    super.key,
    required this.variant,
    this.width,
    this.height,
    this.fit = BoxFit.contain,
  });

  const AppLogo.gold({
    super.key,
    this.width,
    this.height,
    this.fit = BoxFit.contain,
  }) : variant = AppLogoVariant.gold;

  const AppLogo.white({
    super.key,
    this.width,
    this.height,
    this.fit = BoxFit.contain,
  }) : variant = AppLogoVariant.white;

  factory AppLogo.matchTextColor(
    Color textColor, {
    Key? key,
    double? width,
    double? height,
    BoxFit fit = BoxFit.contain,
  }) {
    return AppLogo(
      key: key,
      variant: _isNearWhite(textColor)
          ? AppLogoVariant.white
          : AppLogoVariant.gold,
      width: width,
      height: height,
      fit: fit,
    );
  }

  final AppLogoVariant variant;
  final double? width;
  final double? height;
  final BoxFit fit;

  static bool _isNearWhite(Color color) {
    // Distinguish true-white (used by AppBar text/icons) from gold.
    return color.alpha >= 200 &&
        color.red >= 240 &&
        color.green >= 240 &&
        color.blue >= 240;
  }

  @override
  Widget build(BuildContext context) {
    final assetPath = switch (variant) {
      AppLogoVariant.gold => 'assets/KHGL.png',
      AppLogoVariant.white => 'assets/KHWL.png',
    };

    return Image.asset(
      assetPath,
      width: width,
      height: height,
      fit: fit,
    );
  }
}
