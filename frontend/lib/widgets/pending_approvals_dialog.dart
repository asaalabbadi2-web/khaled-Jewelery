import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:flutter_staggered_animations/flutter_staggered_animations.dart';
import 'package:provider/provider.dart';
import '../api_service.dart';
import '../theme/app_theme.dart';
import '../providers/auth_provider.dart';
import '../screens/invoices_list_screen.dart';
import '../screens/posting_management_screen.dart';

class PendingApprovalsDialog extends StatefulWidget {
  final ApiService api;
  final bool isArabic;
  /// يُستدعى بعد كل ترحيل ناجح لتحديث الـ badge في الرئيسية
  final VoidCallback? onCountChanged;

  const PendingApprovalsDialog({
    super.key,
    required this.api,
    required this.isArabic,
    this.onCountChanged,
  });

  /// Helper لفتح الـ Dialog من أي مكان
  static Future<void> show({
    required BuildContext context,
    required ApiService api,
    required bool isArabic,
    VoidCallback? onCountChanged,
  }) {
    return showDialog(
      context: context,
      barrierDismissible: true,
      barrierColor: Colors.black.withValues(alpha: 0.50),
      builder: (_) => Directionality(
        textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
        child: PendingApprovalsDialog(
          api: api,
          isArabic: isArabic,
          onCountChanged: onCountChanged,
        ),
      ),
    );
  }

  @override
  State<PendingApprovalsDialog> createState() => _PendingApprovalsDialogState();
}

class _PendingApprovalsDialogState extends State<PendingApprovalsDialog> {
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _invoices = [];
  int _total = 0;
  final Set<int> _postingIds = {};
  final Set<int> _justPostedIds = {};

  @override
  void initState() {
    super.initState();
    _loadList();
  }

  Future<void> _loadList() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.api.getPendingPostInvoices(limit: 10);
      if (!mounted) return;
      setState(() {
        _invoices = (result['invoices'] as List? ?? [])
            .map((e) => Map<String, dynamic>.from(e as Map))
            .toList();
        _total = (result['total'] as num?)?.toInt() ?? 0;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _postInvoice(Map<String, dynamic> invoice) async {
    final id = invoice['id'] as int;
    if (_postingIds.contains(id)) return;

    final String postedBy =
        Provider.of<AuthProvider>(context, listen: false).username;

    setState(() => _postingIds.add(id));

    try {
      await widget.api.postInvoice(id, postedBy);

      if (!mounted) return;

      setState(() => _justPostedIds.add(id));
      await Future.delayed(const Duration(milliseconds: 280));

      if (!mounted) return;
      setState(() {
        _invoices.removeWhere((inv) => inv['id'] == id);
        _total = (_total - 1).clamp(0, 9999);
        _postingIds.remove(id);
        _justPostedIds.remove(id);
      });

      widget.onCountChanged?.call();

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              widget.isArabic
                  ? 'تم ترحيل ${invoice['invoice_number']}'
                  : 'Posted ${invoice['invoice_number']}',
              style: const TextStyle(fontFamily: 'Cairo'),
            ),
            backgroundColor: AppColors.success,
            behavior: SnackBarBehavior.floating,
            duration: const Duration(seconds: 2),
          ),
        );
      }

      if (_invoices.isEmpty && mounted) {
        await Future.delayed(const Duration(milliseconds: 300));
        if (mounted) Navigator.of(context).pop();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _postingIds.remove(id));
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            widget.isArabic ? 'فشل الترحيل: $e' : 'Posting failed: $e',
            style: const TextStyle(fontFamily: 'Cairo'),
          ),
          backgroundColor: AppColors.error,
          behavior: SnackBarBehavior.floating,
        ),
      );
    }
  }

  Future<void> _viewDetails(Map<String, dynamic> invoice) async {
    Navigator.of(context).pop();
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => InvoicesListScreen(isArabic: widget.isArabic),
      ),
    );
    widget.onCountChanged?.call();
  }

  Future<void> _openPostingManagement() async {
    Navigator.of(context).pop();
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => PostingManagementScreen(isArabic: widget.isArabic),
      ),
    );
    widget.onCountChanged?.call();
  }

  // ─────────────── Build ───────────────

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final isAr = widget.isArabic;

    return Dialog(
      insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
      backgroundColor: Colors.transparent,
      elevation: 0,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520, maxHeight: 600),
        child: Container(
          decoration: BoxDecoration(
            color: isDark ? const Color(0xFF1E1E1E) : Colors.white,
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.20),
                blurRadius: 24,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _buildHeader(theme, isDark, isAr),
              Flexible(child: _buildBody(theme, isDark, isAr)),
              _buildFooter(theme, isDark, isAr),
            ],
          ),
        ),
      ),
    );
  }

  // ─────────────── Header ───────────────

  Widget _buildHeader(ThemeData theme, bool isDark, bool isAr) {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 18, 16, 18),
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(
            color: isDark ? const Color(0xFF3D3D3D) : const Color(0xFFEEEEEE),
          ),
        ),
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: AppColors.error.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.pending_actions_rounded,
              color: AppColors.error,
              size: 22,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  isAr ? 'بانتظار اعتمادك' : 'Pending Your Approval',
                  style: TextStyle(
                    fontFamily: 'Cairo',
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: isDark ? Colors.white : const Color(0xFF212121),
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  _loading
                      ? (isAr ? 'جارِ التحميل...' : 'Loading...')
                      : (isAr
                          ? '$_total ${_total == 1 ? 'عملية تحتاج' : 'عمليات تحتاج'} مراجعتك'
                          : '$_total ${_total == 1 ? 'item needs' : 'items need'} review'),
                  style: TextStyle(
                    fontFamily: 'Cairo',
                    fontSize: 12,
                    color: isDark
                        ? const Color(0xFFBDBDBD)
                        : const Color(0xFF757575),
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.close_rounded, size: 22),
            onPressed: () => Navigator.of(context).pop(),
            tooltip: isAr ? 'إغلاق' : 'Close',
            color: isDark ? const Color(0xFFBDBDBD) : const Color(0xFF616161),
          ),
        ],
      ),
    );
  }

  // ─────────────── Body ───────────────

  Widget _buildBody(ThemeData theme, bool isDark, bool isAr) {
    if (_loading) {
      return SizedBox(
        height: 200,
        child: Center(
          child: CircularProgressIndicator(
            color: AppColors.primaryGold,
            strokeWidth: 2.5,
          ),
        ),
      );
    }

    if (_error != null) {
      return _buildErrorState(theme, isAr);
    }

    if (_invoices.isEmpty) {
      return _buildEmptyState(theme, isAr);
    }

    return AnimationLimiter(
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
        shrinkWrap: true,
        itemCount: _invoices.length,
        separatorBuilder: (_, idx) => Divider(
          height: 1,
          color: isDark ? const Color(0xFF2D2D2D) : const Color(0xFFF0F0F0),
        ),
        itemBuilder: (context, index) {
          return AnimationConfiguration.staggeredList(
            position: index,
            duration: const Duration(milliseconds: 240),
            child: SlideAnimation(
              verticalOffset: 12,
              child: FadeInAnimation(
                child: _buildInvoiceRow(_invoices[index], isDark, isAr),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildInvoiceRow(
    Map<String, dynamic> invoice,
    bool isDark,
    bool isAr,
  ) {
    final id = invoice['id'] as int;
    final isPosting = _postingIds.contains(id);
    final isJustPosted = _justPostedIds.contains(id);

    final type = (invoice['invoice_type'] ?? '').toString();
    final number = (invoice['invoice_number'] ?? '—').toString();
    final amount = (invoice['total_amount'] as num?)?.toDouble() ?? 0;
    final party = (invoice['party_name'] ?? '—').toString();
    final createdBy = (invoice['created_by_name'] ?? '—').toString();
    final createdAt = invoice['created_at']?.toString();

    final (typeLabel, typeColor) = _getTypeInfo(type, isAr);
    final relativeTime = _formatRelativeTime(createdAt, isAr);

    return AnimatedOpacity(
      duration: const Duration(milliseconds: 280),
      opacity: isJustPosted ? 0 : 1,
      child: AnimatedSlide(
        duration: const Duration(milliseconds: 280),
        offset: isJustPosted ? Offset(isAr ? 1 : -1, 0) : Offset.zero,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── type badge ──
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: typeColor.withValues(alpha: 0.13),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Center(
                  child: Text(
                    typeLabel,
                    style: TextStyle(
                      fontFamily: 'Cairo',
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      color: typeColor,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 12),

              // ── row content ──
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // line 1: number + amount
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            number,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontFamily: 'Cairo',
                              fontSize: 13,
                              fontWeight: FontWeight.w700,
                              color: isDark
                                  ? Colors.white
                                  : const Color(0xFF212121),
                            ),
                          ),
                        ),
                        Text(
                          NumberFormat('#,##0', 'en').format(amount.round()),
                          style: TextStyle(
                            fontFamily: 'Cairo',
                            fontSize: 14,
                            fontWeight: FontWeight.w800,
                            color: typeColor,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 3),

                    // line 2: party · creator · time
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            '$party · $createdBy',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontFamily: 'Cairo',
                              fontSize: 11,
                              color: isDark
                                  ? const Color(0xFFBDBDBD)
                                  : const Color(0xFF757575),
                            ),
                          ),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          relativeTime,
                          style: const TextStyle(
                            fontFamily: 'Cairo',
                            fontSize: 10.5,
                            color: Color(0xFF9E9E9E),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),

                    // line 3: action buttons
                    Row(
                      children: [
                        _buildActionButton(
                          label: isPosting
                              ? (isAr ? 'جارِ الترحيل...' : 'Posting...')
                              : (isAr ? '✓ ترحيل مباشر' : '✓ Post Now'),
                          color: AppColors.success,
                          isPrimary: true,
                          isLoading: isPosting,
                          onTap: isPosting ? null : () => _postInvoice(invoice),
                        ),
                        const SizedBox(width: 6),
                        _buildActionButton(
                          label: isAr ? 'التفاصيل' : 'Details',
                          color: isDark
                              ? const Color(0xFFBDBDBD)
                              : const Color(0xFF616161),
                          isPrimary: false,
                          isLoading: false,
                          onTap: isPosting ? null : () => _viewDetails(invoice),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildActionButton({
    required String label,
    required Color color,
    required bool isPrimary,
    required bool isLoading,
    required VoidCallback? onTap,
  }) {
    return InkWell(
      borderRadius: BorderRadius.circular(6),
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: isPrimary
              ? color.withValues(alpha: isLoading ? 0.10 : 0.15)
              : color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(6),
          border: isPrimary
              ? Border.all(color: color.withValues(alpha: 0.30))
              : null,
        ),
        child: isLoading
            ? SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(
                  strokeWidth: 1.8,
                  valueColor: AlwaysStoppedAnimation(color),
                ),
              )
            : Text(
                label,
                style: TextStyle(
                  fontFamily: 'Cairo',
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: color,
                ),
              ),
      ),
    );
  }

  // ─────────────── Empty / Error ───────────────

  Widget _buildEmptyState(ThemeData theme, bool isAr) {
    final isDark = theme.brightness == Brightness.dark;
    return Padding(
      padding: const EdgeInsets.all(40),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              color: AppColors.success.withValues(alpha: 0.12),
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.check_circle_rounded,
              size: 36,
              color: AppColors.success,
            ),
          ),
          const SizedBox(height: 16),
          Text(
            isAr ? 'كل شيء مرحّل!' : 'All caught up!',
            style: TextStyle(
              fontFamily: 'Cairo',
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: isDark ? Colors.white : const Color(0xFF212121),
            ),
          ),
          const SizedBox(height: 6),
          Text(
            isAr
                ? 'لا توجد فواتير بانتظار الترحيل حالياً'
                : 'No invoices pending approval',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontFamily: 'Cairo',
              fontSize: 12,
              color: isDark ? const Color(0xFFBDBDBD) : const Color(0xFF757575),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildErrorState(ThemeData theme, bool isAr) {
    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline_rounded, size: 40, color: AppColors.error),
          const SizedBox(height: 12),
          Text(
            isAr ? 'تعذر التحميل' : 'Could not load',
            style: const TextStyle(
              fontFamily: 'Cairo',
              fontSize: 14,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _loadList,
            icon: const Icon(Icons.refresh_rounded, size: 16),
            label: Text(
              isAr ? 'إعادة المحاولة' : 'Retry',
              style: const TextStyle(fontFamily: 'Cairo'),
            ),
          ),
        ],
      ),
    );
  }

  // ─────────────── Footer ───────────────

  Widget _buildFooter(ThemeData theme, bool isDark, bool isAr) {
    final hasMore = _total > _invoices.length;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(
            color: isDark ? const Color(0xFF3D3D3D) : const Color(0xFFEEEEEE),
          ),
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            isAr
                ? 'يعرض ${_invoices.length} من $_total'
                : 'Showing ${_invoices.length} of $_total',
            style: TextStyle(
              fontFamily: 'Cairo',
              fontSize: 11.5,
              color: isDark ? const Color(0xFFBDBDBD) : const Color(0xFF757575),
              fontWeight: FontWeight.w500,
            ),
          ),
          if (hasMore || _invoices.isNotEmpty)
            InkWell(
              borderRadius: BorderRadius.circular(6),
              onTap: _openPostingManagement,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      isAr ? 'فتح إدارة الترحيل' : 'Open Posting Management',
                      style: const TextStyle(
                        fontFamily: 'Cairo',
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppColors.darkGold,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Icon(
                      isAr
                          ? Icons.arrow_back_ios_new_rounded
                          : Icons.arrow_forward_ios_rounded,
                      size: 11,
                      color: AppColors.darkGold,
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  // ─────────────── Helpers ───────────────

  (String, Color) _getTypeInfo(String type, bool isAr) {
    switch (type) {
      case 'بيع':
      case 'sale':
        return (isAr ? 'بيع' : 'Sale', AppColors.success);
      case 'scrap_sale':
        return (isAr ? 'بيع كسر' : 'Scrap Sale', const Color(0xFF00897B));
      case 'شراء':
      case 'purchase':
        return (isAr ? 'شراء' : 'Purchase', const Color(0xFF5E35B1));
      case 'شراء من عميل':
        return (isAr ? 'شراء عميل' : 'Cust. Buy', const Color(0xFF5E35B1));
      case 'scrap_purchase':
      case 'شراء خردة':
        return (isAr ? 'شراء كسر' : 'Scrap Buy', const Color(0xFFD84315));
      case 'مرتجع بيع':
      case 'sales_return':
        return (isAr ? 'مرتجع بيع' : 'Sale Ret.', const Color(0xFFE53935));
      case 'مرتجع شراء':
      case 'purchase_return':
        return (isAr ? 'مرتجع شراء' : 'Purch. Ret.', const Color(0xFFFB8C00));
      default:
        return (isAr ? 'فاتورة' : 'Invoice', AppColors.darkGold);
    }
  }

  String _formatRelativeTime(String? iso, bool isAr) {
    if (iso == null) return '';
    final dt = DateTime.tryParse(iso);
    if (dt == null) return '';
    final diff = DateTime.now().difference(dt);
    if (diff.inMinutes < 1) return isAr ? 'الآن' : 'now';
    if (diff.inMinutes < 60) {
      return isAr ? 'منذ ${diff.inMinutes} د' : '${diff.inMinutes}m ago';
    }
    if (diff.inHours < 24) {
      return isAr ? 'منذ ${diff.inHours} س' : '${diff.inHours}h ago';
    }
    if (diff.inDays < 7) {
      return isAr ? 'منذ ${diff.inDays} ي' : '${diff.inDays}d ago';
    }
    return DateFormat('dd/MM', 'en').format(dt);
  }
}
