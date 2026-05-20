// frontend/lib/widgets/goal_achievement_celebration.dart
//
// 🎉 احتفالية تحقيق هدف الموظف — Full-screen Overlay
//
// الأجزاء:
//   1. GoalAchievement           — نموذج البيانات
//   2. GoalAchievementOverlay    — Widget الـ overlay الكامل
//   3. _ConfettiPainter          — رسم الـ confetti بـ CustomPainter
//   4. _ConfettiParticle         — جسيم واحد مع physics حقيقية
//   5. show() static method      — لعرض الـ overlay بسهولة

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_theme.dart';

// ═══════════════════════════════════════════════════════════════
// PART 1 — Data Model
// ═══════════════════════════════════════════════════════════════

class GoalAchievement {
  final int? id;
  final String employeeName;
  final String? department;
  final String? position;
  final String goalName;
  final String? goalDescription;
  final double bonusAmount;
  final String currency;
  final Map<String, dynamic> metrics;
  final DateTime achievedAt;
  // 🗓️ الفترة: 'daily' | 'weekly' | 'monthly'
  final String? period;

  const GoalAchievement({
    this.id,
    required this.employeeName,
    this.department,
    this.position,
    required this.goalName,
    this.goalDescription,
    required this.bonusAmount,
    this.currency = 'ر.س',
    this.metrics = const {},
    required this.achievedAt,
    this.period,
  });

  /// Arabic/English initials from name
  String get initials {
    final parts = employeeName.trim().split(RegExp(r'\s+'));
    if (parts.isEmpty) return '?';
    if (parts.length == 1) return parts[0].substring(0, 1);
    return '${parts[0].substring(0, 1)}.${parts[1].substring(0, 1)}';
  }

  factory GoalAchievement.fromJson(Map<String, dynamic> json) {
    return GoalAchievement(
      id: json['id'] as int?,
      employeeName: json['employee_name']?.toString() ?? '—',
      department: json['department']?.toString(),
      position: json['position']?.toString(),
      goalName: json['goal_name']?.toString() ?? '',
      goalDescription: json['goal_description']?.toString(),
      bonusAmount: (json['bonus_amount'] as num?)?.toDouble() ?? 0.0,
      currency: json['currency']?.toString() ?? 'ر.س',
      metrics: (json['metrics'] as Map<String, dynamic>?) ?? {},
      achievedAt: DateTime.tryParse(json['achieved_at']?.toString() ?? '') ??
          DateTime.now(),
      period: json['goal_period']?.toString(),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// PART 2 — Confetti System
// ═══════════════════════════════════════════════════════════════

class _ConfettiParticle {
  double x;
  double y;
  final double startX;
  final double speedY;
  final double speedX;
  final double rotation;
  final double rotationSpeed;
  final Color color;
  final double size;
  final bool isCircle;
  final double delay;

  _ConfettiParticle({
    required this.x,
    required this.y,
    required this.startX,
    required this.speedY,
    required this.speedX,
    required this.rotation,
    required this.rotationSpeed,
    required this.color,
    required this.size,
    required this.isCircle,
    required this.delay,
  });

  factory _ConfettiParticle.random(math.Random random, Size canvasSize) {
    const colors = [
      Color(0xFFFFD700), // gold
      Color(0xFFFF6B6B), // coral
      Color(0xFF4ECDC4), // teal
      Color(0xFF9B59B6), // purple
      Color(0xFFFF9F1C), // orange
      Color(0xFFFFFFFF), // white
      Color(0xFFFFE4B5), // peach
      AppColors.primaryGold,
      AppColors.success,
      AppColors.info,
    ];

    final startX = random.nextDouble() * canvasSize.width;
    return _ConfettiParticle(
      x: startX,
      y: -20 - random.nextDouble() * 40,
      startX: startX,
      speedY: 60 + random.nextDouble() * 80,
      speedX: (random.nextDouble() - 0.5) * 30,
      rotation: random.nextDouble() * math.pi * 2,
      rotationSpeed: (random.nextDouble() - 0.5) * 4,
      color: colors[random.nextInt(colors.length)],
      size: 6 + random.nextDouble() * 6,
      isCircle: random.nextBool(),
      delay: random.nextDouble() * 1.5,
    );
  }

  void update(double dt, double elapsedSeconds, Size canvasSize, math.Random rng) {
    if (elapsedSeconds < delay) return;
    y += speedY * dt;
    x += speedX * dt;
    // ♻️ Recycle particle when it exits the bottom — keeps confetti going forever
    if (y > canvasSize.height + 60) {
      y = -20 - rng.nextDouble() * 60;
      x = rng.nextDouble() * canvasSize.width;
    }
  }
}

class _ConfettiPainter extends CustomPainter {
  final List<_ConfettiParticle> particles;
  final double progress;

  const _ConfettiPainter({required this.particles, required this.progress});

  @override
  void paint(Canvas canvas, Size size) {
    for (final p in particles) {
      if (p.y > size.height + 50 || p.y < -50) continue;

      final fadeStart = size.height * 0.7;
      final opacity = p.y > fadeStart
          ? (1.0 - ((p.y - fadeStart) / (size.height - fadeStart)))
              .clamp(0.0, 1.0)
          : 1.0;

      final paint = Paint()
        ..color = p.color.withValues(alpha: opacity)
        ..style = PaintingStyle.fill;

      canvas.save();
      canvas.translate(p.x, p.y);
      canvas.rotate(p.rotation + p.rotationSpeed * progress * 2 * math.pi);

      if (p.isCircle) {
        canvas.drawCircle(Offset.zero, p.size / 2, paint);
      } else {
        canvas.drawRect(
          Rect.fromCenter(
            center: Offset.zero,
            width: p.size,
            height: p.size * 1.4,
          ),
          paint,
        );
      }
      canvas.restore();
    }
  }

  @override
  bool shouldRepaint(_ConfettiPainter oldDelegate) => true;
}

// ═══════════════════════════════════════════════════════════════
// PART 3 — The Overlay Widget
// ═══════════════════════════════════════════════════════════════

class GoalAchievementOverlay extends StatefulWidget {
  final GoalAchievement achievement;
  final VoidCallback? onDismiss;
  final VoidCallback? onViewDetails;
  final bool isArabic;

  const GoalAchievementOverlay({
    super.key,
    required this.achievement,
    this.onDismiss,
    this.onViewDetails,
    this.isArabic = true,
  });

  /// Shows the overlay on top of the entire screen
  static Future<void> show(
    BuildContext context, {
    required GoalAchievement achievement,
    VoidCallback? onDismiss,
    VoidCallback? onViewDetails,
    bool isArabic = true,
  }) {
    HapticFeedback.heavyImpact();

    return showGeneralDialog(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'Achievement',
      barrierColor: Colors.black.withValues(alpha: 0.65),
      transitionDuration: const Duration(milliseconds: 400),
      pageBuilder: (ctx, animation, secondaryAnimation) {
        return GoalAchievementOverlay(
          achievement: achievement,
          onDismiss: onDismiss,
          onViewDetails: onViewDetails,
          isArabic: isArabic,
        );
      },
      transitionBuilder: (ctx, animation, secondaryAnimation, child) {
        return FadeTransition(
          opacity: animation,
          child: child,
        );
      },
    );
  }

  @override
  State<GoalAchievementOverlay> createState() => _GoalAchievementOverlayState();
}

class _GoalAchievementOverlayState extends State<GoalAchievementOverlay>
    with TickerProviderStateMixin {
  late final AnimationController _confettiController;
  late final AnimationController _modalController;
  late final AnimationController _trophyController;
  late final AnimationController _glowController;

  late final Animation<double> _modalScale;
  late final Animation<double> _modalSlide;
  late final Animation<double> _trophyRotation;
  late final Animation<double> _glowValue;

  final List<_ConfettiParticle> _particles = [];
  final math.Random _random = math.Random();
  double _elapsedSeconds = 0;
  DateTime? _confettiStartTime;

  @override
  void initState() {
    super.initState();

    // ── Confetti — repeats indefinitely until overlay is closed ──
    _confettiController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 10),
    )..addListener(_updateConfetti);

    // ── Modal entrance ──
    _modalController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _modalScale = Tween<double>(begin: 0.7, end: 1.0).animate(
      CurvedAnimation(parent: _modalController, curve: Curves.elasticOut),
    );
    _modalSlide = Tween<double>(begin: 60.0, end: 0.0).animate(
      CurvedAnimation(parent: _modalController, curve: Curves.easeOutCubic),
    );

    // ── Trophy sway ──
    _trophyController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 4),
    )..repeat(reverse: true);
    _trophyRotation = Tween<double>(begin: -0.15, end: 0.15).animate(
      CurvedAnimation(parent: _trophyController, curve: Curves.easeInOut),
    );

    // ── Glow pulse ──
    _glowController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
    _glowValue = Tween<double>(begin: 0.4, end: 1.0).animate(
      CurvedAnimation(parent: _glowController, curve: Curves.easeInOut),
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final size = MediaQuery.sizeOf(context);
      for (int i = 0; i < 40; i++) {
        _particles.add(_ConfettiParticle.random(_random, size));
      }
    });

    _confettiController.repeat(); // يتوقف تلقائياً بعد 5 ثوانٍ
    _modalController.forward();

    // ── أداء: إيقاف الكونفيتي تلقائياً بعد 5 ثوانٍ ──
    Future.delayed(const Duration(seconds: 15), () {
      if (mounted) _confettiController.stop();
    });
  }

  void _updateConfetti() {
    if (!mounted) return;
    // Use wall-clock time so elapsed always increases even when repeat() loops
    _confettiStartTime ??= DateTime.now();
    final newElapsed =
        DateTime.now().difference(_confettiStartTime!).inMilliseconds / 1000.0;
    final dt = (newElapsed - _elapsedSeconds).clamp(0.0, 0.05); // cap to avoid jumps
    _elapsedSeconds = newElapsed;
    final size = MediaQuery.sizeOf(context);
    for (final p in _particles) {
      p.update(dt, _elapsedSeconds, size, _random);
    }
    setState(() {});
  }

  @override
  void dispose() {
    _confettiController.dispose();
    _modalController.dispose();
    _trophyController.dispose();
    _glowController.dispose();
    super.dispose();
  }

  Future<void> _dismiss() async {
    await _modalController.reverse();
    if (!mounted) return;
    Navigator.of(context).pop();
    widget.onDismiss?.call();
  }

  String _formatBonus(double value) {
    if (value.abs() >= 1000000) {
      return '${(value / 1000000).toStringAsFixed(1)}M';
    } else if (value.abs() >= 1000) {
      return '${(value / 1000).toStringAsFixed(0)}K';
    }
    return value.toStringAsFixed(0);
  }

  String _formatMetric(dynamic value) {
    if (value is num) {
      if (value.abs() >= 1000) {
        return '${(value / 1000).toStringAsFixed(1)}K';
      }
      return value.toStringAsFixed(value == value.toInt() ? 0 : 1);
    }
    return value?.toString() ?? '-';
  }

  String _localizeMetricKey(String key, bool isAr) {
    if (!isAr) return key;
    const translations = {
      'points': 'النقاط',
      'invoices': 'الفواتير',
      'rank': 'المرتبة',
      'sales': 'المبيعات',
      'weight': 'الوزن',
      'count': 'العدد',
      'amount': 'المبلغ',
      'percentage': 'النسبة',
      'target': 'الهدف',
      'progress': 'التقدّم',
      'metric': 'المقياس',
      'period': 'الفترة',
      'race_rank': 'المرتبة في السباق',
      'race_total': 'المشاركون',
      'race_beaten': 'تفوقت على',
      'race_points': 'أعلى نقاط',
      'race_weight': 'أعلى وزن',
      'race_invoices': 'أعلى فواتير',
      'race_top_name': 'صاحب المرتبة الأولى',
      'race_is_champion': 'البطولة',
    };
    return translations[key.toLowerCase()] ?? key;
  }

  /// يُعيد حقول السباق من metrics إن وُجدت.
  bool _hasRaceData(GoalAchievement a) =>
      a.metrics.containsKey('race_rank');

  Widget _buildRaceRow(ThemeData theme, bool isAr, GoalAchievement achievement) {
    final m = achievement.metrics;
    final rank = m['race_rank'] as int?;
    final total = m['race_total'] as int?;
    final beaten = m['race_beaten'] as int?;
    final isChampion = m['race_is_champion'] == true;
    final topName = m['race_top_name']?.toString() ?? '';
    if (rank == null) return const SizedBox.shrink();

    final medal = rank == 1 ? '🥇' : rank == 2 ? '🥈' : rank == 3 ? '🥉' : '🏅';
    final rankLabel = isAr ? 'المرتبة $rank من ${total ?? '?'}' : 'Rank $rank of ${total ?? '?'}';
    final beatenLabel = beaten != null && beaten > 0
        ? (isAr ? 'تفوقت على $beaten موظف' : 'Beat $beaten employees')
        : null;
    final championLabel = isChampion
        ? (isAr ? 'أنت بطل هذه الفترة! 🏆' : 'You are the champion! 🏆')
        : (topName.isNotEmpty
            ? (isAr ? 'المتصدر: $topName' : 'Leader: $topName')
            : null);

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: isChampion
              ? [const Color(0xFFFFD700).withValues(alpha: 0.18), const Color(0xFFFFF3CD).withValues(alpha: 0.35)]
              : [theme.colorScheme.surface, theme.colorScheme.surface.withValues(alpha: 0.7)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isChampion
              ? AppColors.primaryGold.withValues(alpha: 0.6)
              : theme.dividerColor.withValues(alpha: 0.25),
          width: isChampion ? 1.5 : 1.0,
        ),
      ),
      child: Row(
        children: [
          Text(medal, style: const TextStyle(fontSize: 26)),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  rankLabel,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                    color: isChampion ? AppColors.darkGold : theme.colorScheme.onSurface,
                  ),
                ),
                if (beatenLabel != null) ...[const SizedBox(height: 2), Text(beatenLabel, style: TextStyle(fontSize: 12, color: theme.colorScheme.onSurface.withValues(alpha: 0.6)))],
                if (championLabel != null) ...[const SizedBox(height: 2), Text(championLabel, style: TextStyle(fontSize: 12, color: isChampion ? AppColors.primaryGold : theme.colorScheme.onSurface.withValues(alpha: 0.55)))],
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final achievement = widget.achievement;

    return Directionality(
      textDirection: isAr ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: Stack(
          children: [
            // ── Confetti layer ──
            Positioned.fill(
              child: IgnorePointer(
                child: AnimatedBuilder(
                  animation: _confettiController,
                  builder: (_, __) => CustomPaint(
                    painter: _ConfettiPainter(
                      particles: _particles,
                      progress: _confettiController.value,
                    ),
                  ),
                ),
              ),
            ),

            // ── Tap outside to dismiss ──
            Positioned.fill(
              child: GestureDetector(
                onTap: _dismiss,
                behavior: HitTestBehavior.translucent,
              ),
            ),

            // ── Centered modal ──
            Center(
              child: AnimatedBuilder(
                animation: _modalController,
                builder: (_, child) => Transform.translate(
                  offset: Offset(0, _modalSlide.value),
                  child: Transform.scale(
                    scale: _modalScale.value,
                    child: child,
                  ),
                ),
                child: _buildModal(theme, isAr, achievement),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ═══════════════════════════════════════════════════
  // Modal card
  // ═══════════════════════════════════════════════════
  Widget _buildModal(ThemeData theme, bool isAr, GoalAchievement achievement) {
    final size = MediaQuery.sizeOf(context);
    final maxWidth = math.min(460.0, size.width - 32);

    return ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: maxWidth,
        maxHeight: size.height - 64,
      ),
      child: Material(
        color: Colors.transparent,
        child: Container(
          decoration: BoxDecoration(
            color: theme.cardColor,
            borderRadius: BorderRadius.circular(20),
            boxShadow: [
              BoxShadow(
                color: AppColors.primaryGold.withValues(alpha: 0.3),
                blurRadius: 40,
                offset: const Offset(0, 20),
              ),
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.2),
                blurRadius: 20,
                spreadRadius: 4,
              ),
            ],
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(20),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _buildHeader(theme, isAr, achievement),
                  _buildBody(theme, isAr, achievement),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  // ═══════════════════════════════════════════════════
  // Header: gradient + trophy + title
  // ═══════════════════════════════════════════════════
  Widget _buildHeader(ThemeData theme, bool isAr, GoalAchievement achievement) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(24, 36, 24, 30),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppColors.darkGold,
            AppColors.primaryGold,
            Color(0xFFFFD700),
          ],
        ),
      ),
      child: Stack(
        clipBehavior: Clip.none,
        alignment: Alignment.center,
        children: [
          // Decorative mini-confetti
          ..._buildMiniConfetti(),

          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Trophy in glowing circle
              AnimatedBuilder(
                animation: Listenable.merge([_trophyController, _glowController]),
                builder: (_, __) => Transform.rotate(
                  angle: _trophyRotation.value,
                  child: Container(
                    width: 80,
                    height: 80,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: Colors.white.withValues(alpha: 0.15),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.white.withValues(alpha: _glowValue.value * 0.5),
                          blurRadius: 24 * _glowValue.value,
                          spreadRadius: 4 * _glowValue.value,
                        ),
                      ],
                    ),
                    child: const Center(
                      child: Text(
                        '🏆',
                        style: TextStyle(fontSize: 40),
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              // Goal name
              Text(
                achievement.goalName,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  shadows: [Shadow(blurRadius: 4, color: Colors.black26)],
                ),
              ),
              const SizedBox(height: 3),
              // Tagline
              Text(
                isAr ? '🎉 تهانينا! لقد حققت هدفك' : '🎉 Congratulations! Goal Achieved',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.9),
                  fontSize: 13,
                ),
              ),
            ],
          ),

          // Close button
          Positioned(
            top: -18,
            left: isAr ? 0 : null,
            right: isAr ? null : 0,
            child: IconButton(
              onPressed: _dismiss,
              icon: Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.25),
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.close, color: Colors.white, size: 18),
              ),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _buildMiniConfetti() {
    final pieces = [
      (l: 0.05, t: 0.05, color: const Color(0xFFFFFFFF), w: 8.0, h: 12.0),
      (l: 0.15, t: 0.18, color: const Color(0xFFFFE4B5), w: 6.0, h: 6.0),
      (l: 0.28, t: 0.08, color: const Color(0xFF4ECDC4), w: 8.0, h: 12.0),
      (l: 0.42, t: 0.22, color: const Color(0xFFFF6B6B), w: 6.0, h: 6.0),
      (l: 0.58, t: 0.06, color: const Color(0xFFFFFFFF), w: 8.0, h: 12.0),
      (l: 0.72, t: 0.20, color: const Color(0xFF9B59B6), w: 6.0, h: 6.0),
      (l: 0.85, t: 0.10, color: const Color(0xFFFFE4B5), w: 8.0, h: 12.0),
      (l: 0.95, t: 0.25, color: const Color(0xFF4ECDC4), w: 6.0, h: 6.0),
    ];

    return pieces.map((p) {
      return Positioned(
        left: p.l * 420,
        top: p.t * 200,
        child: AnimatedBuilder(
          animation: _confettiController,
          builder: (_, __) {
            final offset = math.sin(
                  _confettiController.value * math.pi * 3 + p.l * math.pi,
                ) *
                8;
            return Transform.translate(
              offset: Offset(0, offset),
              child: Transform.rotate(
                angle: _confettiController.value * math.pi * 2 * (p.l > 0.5 ? 1 : -1),
                child: Container(
                  width: p.w,
                  height: p.h,
                  decoration: BoxDecoration(
                    color: p.color.withValues(alpha: 0.7),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
            );
          },
        ),
      );
    }).toList();
  }

  // ═══════════════════════════════════════════════════
  // Body: avatar + name + goal + stats + actions
  // ═══════════════════════════════════════════════════
  Widget _buildBody(ThemeData theme, bool isAr, GoalAchievement achievement) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 22),
      child: Column(
        children: [
          // Avatar overlapping header
          Transform.translate(
            offset: const Offset(0, -28),
            child: Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: const LinearGradient(
                  colors: [AppColors.darkGold, AppColors.primaryGold],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                border: Border.all(color: Colors.white, width: 3),
                boxShadow: [
                  BoxShadow(
                    color: AppColors.primaryGold.withValues(alpha: 0.4),
                    blurRadius: 12,
                    spreadRadius: 2,
                  ),
                ],
              ),
              child: Center(
                child: Text(
                  achievement.initials,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
          ),

          // Name + role
          Transform.translate(
            offset: const Offset(0, -18),
            child: Column(
              children: [
                Text(
                  achievement.employeeName,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    color: theme.colorScheme.onSurface,
                  ),
                ),
                if (achievement.department != null ||
                    achievement.position != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    [achievement.position, achievement.department]
                        .where((s) => s != null && s.isNotEmpty)
                        .join(' · '),
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 12,
                      color: theme.colorScheme.onSurface.withValues(alpha: 0.6),
                    ),
                  ),
                ],
              ],
            ),
          ),

          const SizedBox(height: 4),

          // Goal card with bonus
          Container(
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              color: AppColors.primaryGold.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: AppColors.primaryGold.withValues(alpha: 0.25),
              ),
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: AppColors.primaryGold.withValues(alpha: 0.15),
                    shape: BoxShape.circle,
                  ),
                  child: const Icon(
                    Icons.star_rounded,
                    color: AppColors.primaryGold,
                    size: 20,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (achievement.goalDescription != null &&
                          achievement.goalDescription!.isNotEmpty)
                        Text(
                          achievement.goalDescription!,
                          style: TextStyle(
                            fontSize: 12,
                            color: theme.colorScheme.onSurface
                                .withValues(alpha: 0.65),
                          ),
                        ),
                      Text(
                        isAr ? 'المكافأة المستحقة' : 'Bonus Earned',
                        style: TextStyle(
                          fontSize: 11,
                          color: theme.colorScheme.onSurface
                              .withValues(alpha: 0.5),
                        ),
                      ),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      _formatBonus(achievement.bonusAmount),
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: AppColors.darkGold,
                      ),
                    ),
                    Text(
                      achievement.currency,
                      style: TextStyle(
                        fontSize: 11,
                        color: AppColors.darkGold.withValues(alpha: 0.7),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),

          const SizedBox(height: 14),

          // Race rank row (shown first if race data present)
          if (_hasRaceData(achievement))
            _buildRaceRow(theme, isAr, achievement),

          // Stats row (exclude race/internal keys)
          if (achievement.metrics.entries
              .where((e) => !e.key.startsWith('race_') && e.key != 'period_key' && e.key != 'metric')
              .isNotEmpty)
            _buildStatsRow(theme, isAr, achievement),

          const SizedBox(height: 16),

          // Action buttons
          Row(
            children: [
              if (widget.onViewDetails != null) ...[
                Expanded(
                  child: ElevatedButton(
                    onPressed: () {
                      Navigator.of(context).pop();
                      widget.onViewDetails?.call();
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.primaryGold,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 13),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                      elevation: 2,
                    ),
                    child: Text(
                      isAr ? 'عرض التفاصيل' : 'View Details',
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 14,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
              ],
              Expanded(
                child: OutlinedButton(
                  onPressed: _dismiss,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.darkGold,
                    side: const BorderSide(color: AppColors.primaryGold),
                    padding: const EdgeInsets.symmetric(vertical: 13),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  child: Text(
                    isAr ? 'إغلاق' : 'Close',
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 14,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatsRow(
      ThemeData theme, bool isAr, GoalAchievement achievement) {
    // استبعاد مفاتيح السباق والمفاتيح الداخلية من الصف الإحصائي
    const hiddenKeys = {'period_key', 'metric', 'race_rank', 'race_total',
        'race_beaten', 'race_points', 'race_weight', 'race_invoices',
        'race_top_name', 'race_is_champion'};
    final entries = achievement.metrics.entries
        .where((e) => !hiddenKeys.contains(e.key))
        .take(4)
        .toList();
    if (entries.isEmpty) return const SizedBox.shrink();

    return Row(
      children: entries.asMap().entries.map((e) {
        final i = e.key;
        final entry = e.value;
        return Expanded(
          child: Padding(
            padding: EdgeInsets.only(
              left: i == 0 ? 0 : 4,
              right: i == entries.length - 1 ? 0 : 4,
            ),
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 6),
              decoration: BoxDecoration(
                color: theme.colorScheme.surface,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: theme.dividerColor.withValues(alpha: 0.3),
                ),
              ),
              child: Column(
                children: [
                  Text(
                    _formatMetric(entry.value),
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                      color: AppColors.primaryGold,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    _localizeMetricKey(entry.key, isAr),
                    style: TextStyle(
                      fontSize: 11,
                      color: theme.colorScheme.onSurface.withValues(alpha: 0.55),
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}
