import 'dart:math' as math;
import 'package:flutter/material.dart';

/// حلقة تقدم احترافية حول أفاتار الموظف في سباق الأداء.
///
/// [progress] : النسبة الفعلية (score / goal_target).
///   - null     → لا حلقة (لم يُضبط هدف)
///   - 0.0–1.0  → قوس جزئي، لون متدرّج (برتقالي → ذهبي)
///   - ≥ 1.0    → حلقة مكتملة خضراء + شارة ✓
///   - ≥ 2.0    → حلقة مكتملة ذهبية ساطعة (تجاوز مضاعف)
///
/// [avatarRadius]: نصف قطر الأفاتار الداخلي.
class GoalProgressRing extends StatelessWidget {
  final Widget child;
  final double? progress; // null = لا هدف
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
  Widget build(BuildContext context) {
    final p = progress;
    if (p == null || p <= 0) return child;

    final bool exceeded  = p >= 1.0;
    final bool wayAhead  = p >= 2.0;

    final Color arcColor = wayAhead
        ? const Color(0xFFD4AF37)         // ذهبي لامع — تجاوز مضاعف
        : exceeded
            ? const Color(0xFF22C55E)     // أخضر — تم تحقيق الهدف
            : p >= 0.6
                ? const Color(0xFFD4AF37) // ذهبي — قريب
                : const Color(0xFFF97316);// برتقالي — تحت 60%

    final Color trackColor = arcColor.withValues(alpha: 0.15);

    // نُقيّد القوس بالدائرة الكاملة حتى لو تجاوزت 1.0
    final double arcSweep = math.min(p, 1.0);

    final double totalSize = (avatarRadius + strokeWidth + 2.5) * 2;

    return Stack(
      alignment: Alignment.center,
      children: [
        SizedBox(
          width: totalSize,
          height: totalSize,
          child: CustomPaint(
            painter: _RingPainter(
              progress: arcSweep,
              arcColor: arcColor,
              trackColor: trackColor,
              strokeWidth: strokeWidth,
              exceeded: exceeded,
              wayAhead: wayAhead,
            ),
            child: Center(child: child),
          ),
        ),
        // شارة ✓ صغيرة عند اكتمال الهدف
        if (exceeded)
          Positioned(
            bottom: 0,
            right: 0,
            child: Container(
              width: 14,
              height: 14,
              decoration: BoxDecoration(
                color: wayAhead ? const Color(0xFFD4AF37) : const Color(0xFF22C55E),
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white, width: 1.5),
                boxShadow: [
                  BoxShadow(
                    color: arcColor.withValues(alpha: 0.4),
                    blurRadius: 4,
                  ),
                ],
              ),
              child: const Icon(Icons.check, size: 9, color: Colors.white),
            ),
          ),
      ],
    );
  }
}

class _RingPainter extends CustomPainter {
  final double progress; // 0.0–1.0 (مُقيّد)
  final Color arcColor;
  final Color trackColor;
  final double strokeWidth;
  final bool exceeded;
  final bool wayAhead;

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

    // ── المسار الخلفي ──────────────────────────────────────────────────────
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

    // ── توهّج ناعم للأهداف المحققة ─────────────────────────────────────────
    if (exceeded) {
      canvas.drawArc(
        rect,
        startAngle,
        sweepAngle,
        false,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = strokeWidth + 2
          ..strokeCap = StrokeCap.round
          ..color = arcColor.withValues(alpha: 0.25)
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3),
      );
    }

    // ── قوس التقدم الرئيسي ─────────────────────────────────────────────────
    canvas.drawArc(
      rect,
      startAngle,
      sweepAngle,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round
        ..color = arcColor,
    );

    // ── نقطة عند نهاية القوس (فقط للتقدم الجزئي) ─────────────────────────
    if (!exceeded && progress > 0.03) {
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
      old.progress != progress || old.arcColor != arcColor;
}
