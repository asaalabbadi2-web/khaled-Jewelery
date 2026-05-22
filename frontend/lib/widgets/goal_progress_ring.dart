import 'dart:math' as math;
import 'package:flutter/material.dart';

/// حلقة تقدم احترافية حول أفاتار الموظف في سباق الأداء.
///
/// عند تغيير [progress] (مثلاً عند التبديل بين الفترات)، تُعاد
/// الأنيميشن من الصفر تلقائياً.
///
/// [progress] : نسبة الأداء الفعلية (score / goal_target).
///   null / ≤0  → لا حلقة
///   0–1.0      → قوس جزئي (برتقالي → ذهبي)
///   ≥1.0       → حلقة مكتملة خضراء + شارة ✓
///   ≥2.0       → حلقة ذهبية + شارة ✓ (تجاوز مضاعف)
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
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _anim;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1100),
    );
    _anim = CurvedAnimation(parent: _ctrl, curve: Curves.easeOutCubic);
    _startAnimation();
  }

  @override
  void didUpdateWidget(GoalProgressRing old) {
    super.didUpdateWidget(old);
    // أعد الأنيميشن عند تغيير الفترة (قيمة progress)
    if (old.progress != widget.progress) {
      _ctrl.reset();
      _startAnimation();
    }
  }

  void _startAnimation() {
    final p = widget.progress;
    if (p != null && p > 0) {
      _ctrl.forward();
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.progress;
    if (p == null || p <= 0) return widget.child;

    final bool exceeded = p >= 1.0;
    final bool wayAhead = p >= 2.0;

    final Color arcColor = wayAhead
        ? const Color(0xFFD4AF37)
        : exceeded
            ? const Color(0xFF22C55E)
            : p >= 0.6
                ? const Color(0xFFD4AF37)
                : const Color(0xFFF97316);

    final double totalSize = (widget.avatarRadius + widget.strokeWidth + 2.5) * 2;

    return AnimatedBuilder(
      animation: _anim,
      builder: (context, child) {
        // القوس يتحرك من 0 إلى المقدار المُقيّد بالدائرة الكاملة
        final double animatedSweep = _anim.value * math.min(p, 1.0);

        // الشارة تظهر بتكبير ناعم في الـ 20% الأخيرة من الأنيميشن
        final double badgeScale = exceeded
            ? (_anim.value > 0.8 ? (_anim.value - 0.8) / 0.2 : 0.0)
                .clamp(0.0, 1.0)
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
                ),
                child: Center(child: child),
              ),
            ),
            // شارة ✓ تظهر بعد اكتمال القوس
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
                          color: arcColor.withValues(alpha: 0.45),
                          blurRadius: 4,
                        ),
                      ],
                    ),
                    child: const Icon(Icons.check, size: 9, color: Colors.white),
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
  final double progress; // 0.0–1.0 (القوس الحالي للأنيميشن)
  final Color arcColor;
  final Color trackColor;
  final double strokeWidth;
  final bool exceeded; // هل اكتمل الهدف (لتفعيل التوهّج)
  final bool wayAhead; // هل تجاوز الضعفين

  const _RingPainter({
    required this.progress,
    required this.arcColor,
    required this.trackColor,
    required this.strokeWidth,
    required this.exceeded,
    required this.wayAhead,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (size.width / 2) - strokeWidth / 2 - 1;

    // ── مسار خلفي ─────────────────────────────────────────────────────────
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
    const startAngle = -math.pi / 2; // 12 o'clock
    final sweepAngle = 2 * math.pi * progress;

    // ── توهّج عند الاكتمال ────────────────────────────────────────────────
    if (exceeded) {
      canvas.drawArc(
        rect, startAngle, sweepAngle, false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = strokeWidth + 2
          ..strokeCap = StrokeCap.round
          ..color = arcColor.withValues(alpha: 0.22)
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3),
      );
    }

    // ── القوس الرئيسي ──────────────────────────────────────────────────────
    canvas.drawArc(
      rect, startAngle, sweepAngle, false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round
        ..color = arcColor,
    );

    // ── نقطة عند طرف القوس (تقدم جزئي فقط) ───────────────────────────────
    if (!exceeded && progress > 0.03 && progress < 0.99) {
      final angle = startAngle + sweepAngle;
      canvas.drawCircle(
        Offset(center.dx + radius * math.cos(angle),
               center.dy + radius * math.sin(angle)),
        strokeWidth / 2.2,
        Paint()..color = arcColor..style = PaintingStyle.fill,
      );
    }
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.progress != progress ||
      old.arcColor != arcColor ||
      old.exceeded != exceeded;
}
