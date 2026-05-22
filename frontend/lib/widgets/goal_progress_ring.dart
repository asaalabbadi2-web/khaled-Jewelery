import 'dart:math' as math;
import 'package:flutter/material.dart';

/// حلقة تقدم احترافية حول أفاتار الموظف في سباق الأداء.
///
/// [progress] : 0.0 → 1.0 (نسبة إنجاز الهدف الشخصي).
/// [hasGoal]  : إذا كان false لا تُرسم الحلقة (لم يُضبط هدف).
/// [radius]   : نصف قطر الأفاتار (الداخلي) — تُضاف سماكة الحلقة فوقه.
///
/// الألوان:
///   ≥ 1.0  → أخضر + توهّج  (الهدف محقَّق)
///   ≥ 0.5  → ذهبي / عنبري
///   < 0.5  → برتقالي / تحذيري
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
    if (p == null) return child;

    final Color arcColor;
    final Color trackColor;
    final bool achieved = p >= 1.0;

    if (achieved) {
      arcColor = const Color(0xFF22C55E);  // أخضر
      trackColor = const Color(0xFF22C55E).withValues(alpha: 0.18);
    } else if (p >= 0.5) {
      arcColor = const Color(0xFFD4AF37);  // ذهبي
      trackColor = const Color(0xFFD4AF37).withValues(alpha: 0.18);
    } else {
      arcColor = const Color(0xFFF97316);  // برتقالي
      trackColor = const Color(0xFFF97316).withValues(alpha: 0.18);
    }

    final totalSize = (avatarRadius + strokeWidth + 2) * 2;

    return SizedBox(
      width: totalSize,
      height: totalSize,
      child: CustomPaint(
        painter: _RingPainter(
          progress: p.clamp(0.0, 1.0),
          arcColor: arcColor,
          trackColor: trackColor,
          strokeWidth: strokeWidth,
          achieved: achieved,
        ),
        child: Center(child: child),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  final double progress;
  final Color arcColor;
  final Color trackColor;
  final double strokeWidth;
  final bool achieved;

  const _RingPainter({
    required this.progress,
    required this.arcColor,
    required this.trackColor,
    required this.strokeWidth,
    required this.achieved,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (size.width / 2) - strokeWidth / 2 - 1;

    // ── الحلقة الخلفية (المسار الرمادي / الشفاف) ──────────────────────────
    final trackPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round
      ..color = trackColor;

    canvas.drawCircle(center, radius, trackPaint);

    if (progress <= 0) return;

    // ── قوس التقدم (من 12 باتجاه عقارب الساعة) ────────────────────────────
    final arcPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    if (achieved) {
      // توهّج ناعم خلف القوس للهدف المحقق
      arcPaint.maskFilter = const MaskFilter.blur(BlurStyle.normal, 2.5);
      arcPaint.color = arcColor.withValues(alpha: 0.5);
      canvas.drawArc(
        Rect.fromCircle(center: center, radius: radius),
        -math.pi / 2,
        2 * math.pi * progress,
        false,
        arcPaint,
      );
      arcPaint.maskFilter = null;
    }

    arcPaint.color = arcColor;
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      -math.pi / 2,  // نبدأ من أعلى (12 o'clock)
      2 * math.pi * progress,
      false,
      arcPaint,
    );

    // ── نقطة صغيرة عند نهاية القوس (لمسة احترافية) ──────────────────────
    if (progress > 0.02 && progress < 0.99) {
      final angle = -math.pi / 2 + 2 * math.pi * progress;
      final dotPos = Offset(
        center.dx + radius * math.cos(angle),
        center.dy + radius * math.sin(angle),
      );
      final dotPaint = Paint()
        ..color = arcColor
        ..style = PaintingStyle.fill;
      canvas.drawCircle(dotPos, strokeWidth / 2.2, dotPaint);
    }
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.progress != progress || old.arcColor != arcColor;
}
