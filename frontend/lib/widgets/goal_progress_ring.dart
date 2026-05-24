import 'dart:math' as math;
import 'package:flutter/material.dart';

/// حلقة تقدم احترافية حول أفاتار الموظف في سباق الأداء.
///
/// الألوان حسب نسبة التقدم:
///   0 < p < 0.30  → أحمر
///   0.30–0.60     → برتقالي
///   0.60–1.0      → ذهبي
///   ≥ 1.0         → أخضر فاخر متوهج + شارة ✓
///   ≥ 2.0         → ذهبي فاخر متوهج  + شارة ✓
class GoalProgressRing extends StatefulWidget {
  final Widget child;
  final double? progress;
  final double avatarRadius;
  final double strokeWidth;

  const GoalProgressRing({
    super.key,
    required this.child,
    required this.progress,
    required this.avatarRadius,
    this.strokeWidth = 3.2,
  });

  @override
  State<GoalProgressRing> createState() => _GoalProgressRingState();
}

class _GoalProgressRingState extends State<GoalProgressRing>
    with TickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final AnimationController _pulseCtrl;
  late final Animation<double> _anim;
  late final Animation<double> _pulse;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1100),
    );
    _anim = CurvedAnimation(parent: _ctrl, curve: Curves.easeOutCubic);

    _pulseCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1600),
    );
    _pulse = CurvedAnimation(parent: _pulseCtrl, curve: Curves.easeInOut);

    _startAnimation();
  }

  @override
  void didUpdateWidget(GoalProgressRing old) {
    super.didUpdateWidget(old);
    if (old.progress != widget.progress) {
      _pulseCtrl
        ..stop()
        ..reset();
      _ctrl.reset();
      _startAnimation();
    }
  }

  void _startAnimation() {
    final p = widget.progress;
    if (p == null || p <= 0) return;
    _ctrl.forward().then((_) {
      if (mounted && (widget.progress ?? 0) >= 1.0) {
        _pulseCtrl.repeat(reverse: true);
      }
    });
  }

  @override
  void dispose() {
    _ctrl.dispose();
    _pulseCtrl.dispose();
    super.dispose();
  }

  static Color _colorFor(double p) {
    if (p >= 2.0) return const Color(0xFFD4AF37); // ذهبي فاخر (تجاوز الضعفين)
    if (p >= 1.0) return const Color(0xFF22C55E); // أخضر فاخر (تحقق الهدف)
    if (p >= 0.60) return const Color(0xFFD4AF37); // ذهبي
    if (p >= 0.30) return const Color(0xFFF97316); // برتقالي
    return const Color(0xFFEF4444);                // أحمر
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.progress;
    if (p == null || p <= 0) return widget.child;

    final bool exceeded = p >= 1.0;
    final bool wayAhead = p >= 2.0;
    final Color arcColor = _colorFor(p);

    final double totalSize =
        (widget.avatarRadius + widget.strokeWidth + 2.5) * 2;

    return AnimatedBuilder(
      animation: Listenable.merge([_anim, _pulse]),
      builder: (context, child) {
        final double animatedSweep = _anim.value * math.min(p, 1.0);
        final double glowIntensity =
            (exceeded && _anim.value > 0.95) ? _pulse.value : 0.0;

        final double badgeScale = exceeded
            ? ((_anim.value > 0.8 ? (_anim.value - 0.8) / 0.2 : 0.0)
                .clamp(0.0, 1.0))
            : 0.0;

        return Stack(
          alignment: Alignment.center,
          children: [
            SizedBox(
              width: totalSize,
              height: totalSize,
              child: CustomPaint(
                painter: _RingPainter(
                  progress: animatedSweep,
                  arcColor: arcColor,
                  trackColor: arcColor.withValues(alpha: 0.15),
                  strokeWidth: widget.strokeWidth,
                  exceeded: exceeded && _anim.value > 0.95,
                  wayAhead: wayAhead,
                  glowIntensity: glowIntensity,
                ),
                child: Center(child: child),
              ),
            ),
            if (exceeded && badgeScale > 0)
              Positioned(
                bottom: 0,
                right: 0,
                child: Transform.scale(
                  scale: badgeScale,
                  child: Container(
                    width: 14,
                    height: 14,
                    decoration: BoxDecoration(
                      color: wayAhead
                          ? const Color(0xFFD4AF37)
                          : const Color(0xFF22C55E),
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 1.5),
                      boxShadow: [
                        BoxShadow(
                          color: arcColor.withValues(
                              alpha: 0.45 + glowIntensity * 0.25),
                          blurRadius: 4 + glowIntensity * 4,
                        ),
                      ],
                    ),
                    child:
                        const Icon(Icons.check, size: 9, color: Colors.white),
                  ),
                ),
              ),
          ],
        );
      },
      child: widget.child,
    );
  }
}

class _RingPainter extends CustomPainter {
  final double progress;
  final Color arcColor;
  final Color trackColor;
  final double strokeWidth;
  final bool exceeded;
  final bool wayAhead;
  final double glowIntensity; // 0.0–1.0 من أنيميشن النبض

  const _RingPainter({
    required this.progress,
    required this.arcColor,
    required this.trackColor,
    required this.strokeWidth,
    required this.exceeded,
    required this.wayAhead,
    required this.glowIntensity,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (size.width / 2) - strokeWidth / 2 - 1;

    // مسار خلفي
    canvas.drawCircle(
      center,
      radius,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..color = trackColor,
    );

    if (progress <= 0) return;

    final rect = Rect.fromCircle(center: center, radius: radius);
    const startAngle = -math.pi / 2;
    final sweepAngle = 2 * math.pi * progress;

    // طبقات التوهّج عند تحقق الهدف
    if (exceeded) {
      final g = glowIntensity;

      // للهدف المضاعف: طبقة ذهبية خارجية إضافية
      if (wayAhead) {
        canvas.drawArc(
          rect, startAngle, sweepAngle, false,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = strokeWidth + 7 + g * 7
            ..strokeCap = StrokeCap.round
            ..color = const Color(0xFFFFD700).withValues(alpha: 0.07 + g * 0.09)
            ..maskFilter = MaskFilter.blur(BlurStyle.normal, 9 + g * 7),
        );
      }

      // توهّج ناعم خارجي (يتنفس)
      canvas.drawArc(
        rect, startAngle, sweepAngle, false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = strokeWidth + 3 + g * 5
          ..strokeCap = StrokeCap.round
          ..color = arcColor.withValues(alpha: 0.11 + g * 0.13)
          ..maskFilter = MaskFilter.blur(BlurStyle.normal, 5 + g * 6),
      );

      // توهّج داخلي محكم
      canvas.drawArc(
        rect, startAngle, sweepAngle, false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = strokeWidth + 1.5
          ..strokeCap = StrokeCap.round
          ..color = arcColor.withValues(alpha: 0.30 + g * 0.28)
          ..maskFilter = MaskFilter.blur(BlurStyle.normal, 2 + g * 2.5),
      );
    }

    // القوس الرئيسي
    canvas.drawArc(
      rect, startAngle, sweepAngle, false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round
        ..color = arcColor,
    );

    // نقطة عند طرف القوس (تقدم جزئي فقط)
    if (!exceeded && progress > 0.03 && progress < 0.99) {
      final angle = startAngle + sweepAngle;
      canvas.drawCircle(
        Offset(center.dx + radius * math.cos(angle),
            center.dy + radius * math.sin(angle)),
        strokeWidth / 2.2,
        Paint()
          ..color = arcColor
          ..style = PaintingStyle.fill,
      );
    }
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.progress != progress ||
      old.arcColor != arcColor ||
      old.exceeded != exceeded ||
      old.glowIntensity != glowIntensity;
}
