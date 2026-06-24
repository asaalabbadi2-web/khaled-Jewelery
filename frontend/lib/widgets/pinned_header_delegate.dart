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

/// A pinned sliver header whose height animates smoothly when it changes,
/// instead of snapping instantly. [PinnedHeaderDelegate]'s height is
/// normally re-measured after each render and fed back via setState (since
/// a sliver header's extent must be known before its content is measured
/// directly) -- the very first time the true height differs from the
/// initial guess (or whenever content grows/shrinks, e.g. a "مسح الفلاتر"
/// button appearing), that produces a visible jump/snap on open. Wrapping
/// the height in a [TweenAnimationBuilder] turns that into a smooth resize.
class AnimatedPinnedHeader extends StatelessWidget {
  const AnimatedPinnedHeader({
    super.key,
    required this.height,
    required this.child,
    required this.backgroundColor,
    this.duration = const Duration(milliseconds: 220),
  });

  final double height;
  final Widget child;
  final Color backgroundColor;
  final Duration duration;

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween<double>(end: height),
      duration: duration,
      curve: Curves.easeOutCubic,
      builder: (context, animatedHeight, _) {
        return SliverPersistentHeader(
          pinned: true,
          floating: true,
          delegate: PinnedHeaderDelegate(
            height: animatedHeight,
            backgroundColor: backgroundColor,
            child: child,
          ),
        );
      },
    );
  }
}
