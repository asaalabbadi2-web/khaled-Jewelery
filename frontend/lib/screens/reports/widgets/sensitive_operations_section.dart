import 'package:flutter/material.dart';

import '../../audit_log_screen.dart';

class SensitiveOperationsSection extends StatelessWidget {
  final List<dynamic> operations;
  final bool isArabic;
  final double Function(double) scale;

  const SensitiveOperationsSection({
    super.key,
    required this.operations,
    required this.isArabic,
    required this.scale,
  });

  double _s(double v) => scale(v);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(height: _s(16)),
        Padding(
          padding: EdgeInsets.symmetric(horizontal: _s(16)),
          child: Row(
            children: [
              Icon(Icons.history, color: Colors.purple, size: _s(22)),
              SizedBox(width: _s(8)),
              Text(
                isArabic ? 'العمليات الحساسة' : 'Audit Trail',
                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold),
              ),
              const Spacer(),
              TextButton(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const AuditLogScreen()),
                ),
                child: Text(isArabic ? 'السجل' : 'Log'),
              ),
            ],
          ),
        ),
        SizedBox(height: _s(8)),
        if (operations.isEmpty)
          Container(
            margin: EdgeInsets.symmetric(horizontal: _s(16)),
            padding: EdgeInsets.all(_s(12)),
            decoration: BoxDecoration(
              color: Colors.purple.withValues(alpha: 0.05),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.purple.withValues(alpha: 0.1)),
            ),
            child: Row(
              children: [
                Icon(Icons.shield_outlined, color: Colors.purple.shade300, size: _s(22)),
                SizedBox(width: _s(10)),
                Expanded(
                  child: Text(
                    isArabic
                        ? 'لا توجد عمليات حساسة للعرض حالياً'
                        : 'No sensitive operations to show',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.hintColor,
                      fontSize: _s(12),
                    ),
                  ),
                ),
                TextButton(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AuditLogScreen()),
                  ),
                  child: Text(isArabic ? 'فتح السجل' : 'Open log'),
                ),
              ],
            ),
          )
        else
          ...operations.take(5).map((op) {
            final opMap = op as Map<String, dynamic>;
            final desc = opMap['description'] ?? '-';
            final user = opMap['user_name'] ?? '-';
            final timeAgo = opMap['time_ago'] ?? '';
            final entityNumber = opMap['entity_number'];

            return InkWell(
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const AuditLogScreen()),
              ),
              borderRadius: BorderRadius.circular(8),
              child: Container(
                margin: EdgeInsets.symmetric(horizontal: _s(16), vertical: _s(4)),
                padding: EdgeInsets.all(_s(10)),
                decoration: BoxDecoration(
                  color: Colors.purple.withValues(alpha: 0.05),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.purple.withValues(alpha: 0.1)),
                ),
                child: Row(
                  children: [
                    Icon(Icons.security, color: Colors.purple.shade300, size: _s(18)),
                    SizedBox(width: _s(8)),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '$desc ${entityNumber != null ? "#$entityNumber" : ""}',
                            style: theme.textTheme.bodySmall?.copyWith(
                              fontWeight: FontWeight.w600,
                              fontSize: _s(12),
                            ),
                          ),
                          Text(
                            '$user • $timeAgo',
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.hintColor,
                              fontSize: _s(11),
                            ),
                          ),
                        ],
                      ),
                    ),
                    Icon(Icons.chevron_left, size: _s(20), color: theme.hintColor),
                  ],
                ),
              ),
            );
          }),
      ],
    );
  }
}
