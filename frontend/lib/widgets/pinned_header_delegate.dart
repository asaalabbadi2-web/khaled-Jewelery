import 'package:flutter/material.dart';

/// A [SliverPersistentHeaderDelegate] for a fixed-height pinned sliver header
/// whose height is determined at runtime (e.g. measured via [GlobalKey]).
class PinnedHeaderDelegate extends SliverPersistentHeaderDelegate {
  PinnedHeaderDelegate({
    required this.height,
    required this.child,
    required this.backgroundColor,
  });

  final double height;
  final Widget child;
  final Color backgroundColor;

  @override
  double get minExtent => height;

  @override
  double get maxExtent => height;

  @override
  Widget build(BuildContext context, double shrinkOffset, bool overlapsContent) {
    return ColoredBox(color: backgroundColor, child: child);
  }

  @override
  bool shouldRebuild(covariant PinnedHeaderDelegate oldDelegate) {
    return oldDelegate.height != height ||
        oldDelegate.backgroundColor != backgroundColor ||
        oldDelegate.child != child;
  }
}
