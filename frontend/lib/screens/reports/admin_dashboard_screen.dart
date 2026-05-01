import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';

import '../../api_service.dart';
import '../../providers/settings_provider.dart';
import '../../theme/app_theme.dart';
import '../audit_log_screen.dart';
import '../employees_screen.dart';
import '../safe_boxes_dashboard_screen.dart';
import '../shift_closing_screen.dart';
import 'gold_price_history_report_screen.dart';
import 'system_alerts_screen.dart';
import 'widgets/dashboard_summary_tabs_card.dart';
import 'widgets/hero_profit_section.dart';
import 'widgets/kpi_cards.dart';
import 'widgets/sensitive_operations_section.dart';
import 'widgets/vaults_section.dart';

enum _TimeRange { today, month, year }

class AdminDashboardScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;

  const AdminDashboardScreen({
    super.key,
    required this.api,
    this.isArabic = true,
  });

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  Map<String, dynamic>? _response;
  bool _isLoading = false;
  String? _error;

  _TimeRange _timeRange = _TimeRange.today;

  // ── Gram Profit KPI ─────────────────────────────────────────────────────
  Map<String, dynamic>? _gramProfitData;
  bool _gramProfitLoading = false;

  // ── Overlay alert state ──────────────────────────────────────────────────
  final Set<String> _dismissedAlertKeys = {};
  OverlayEntry? _toastOverlayEntry;

  /// Maps the unified top-level time selector to the backend summary key.
  String get _summaryPeriod {
    switch (_timeRange) {
      case _TimeRange.today:
        return 'today';
      case _TimeRange.month:
        return 'month';
      case _TimeRange.year:
        return 'year';
    }
  }

  double _uiScale(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    if (width >= 1200) return 1.20;
    if (width >= 900) return 1.12;
    if (width >= 600) return 1.04;
    return 1.0;
  }

  double _s(double value) => value * _uiScale(context);

  String _currencySymbol = 'ر.س';
  int _currencyDecimals = 2;

  late NumberFormat _currencyFormat;
  late NumberFormat _weightFormat;

  @override
  void initState() {
    super.initState();
    _currencyFormat = NumberFormat.currency(
      locale: widget.isArabic ? 'ar' : 'en',
      symbol: _currencySymbol,
      decimalDigits: _currencyDecimals,
    );
    _weightFormat = NumberFormat('#,##0.000');
    _loadData();
  }

  @override
  void dispose() {
    _toastOverlayEntry?.remove();
    _toastOverlayEntry = null;
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final settings = Provider.of<SettingsProvider>(context);
    final symbol = settings.currencySymbol;
    final decimals = settings.decimalPlaces;

    if (symbol != _currencySymbol || decimals != _currencyDecimals) {
      setState(() {
        _currencySymbol = symbol;
        _currencyDecimals = decimals;
        _currencyFormat = NumberFormat.currency(
          locale: widget.isArabic ? 'ar' : 'en',
          symbol: _currencySymbol,
          decimalDigits: _currencyDecimals,
        );
      });
    }
  }

  Future<void> _loadData() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final result = await widget.api.getAdminDashboard();
      if (!mounted) return;
      setState(() => _response = result);
      _loadGramProfit();
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _updateToastOverlay();
        });
      }
    }
  }

  Future<void> _loadGramProfit() async {
    try {
      setState(() => _gramProfitLoading = true);
      final now = DateTime.now();
      final DateTime start;
      switch (_timeRange) {
        case _TimeRange.today:
          start = DateTime(now.year, now.month, now.day);
          break;
        case _TimeRange.month:
          start = DateTime(now.year, now.month, 1);
          break;
        case _TimeRange.year:
          start = DateTime(now.year, 1, 1);
          break;
      }
      final data = await widget.api.getGramProfitReport(
        startDate: start,
        endDate: now,
      );
      if (mounted) setState(() => _gramProfitData = data);
    } catch (e) {
      debugPrint('❌ Gram profit load error: $e');
    } finally {
      if (mounted) setState(() => _gramProfitLoading = false);
    }
  }

  void _updateToastOverlay() {
    _toastOverlayEntry?.remove();
    _toastOverlayEntry = null;
    if (!mounted) return;
    final alerts = _getAllAlerts();
    if (alerts.isEmpty) return;
    final entry = OverlayEntry(
      builder: (ctx) => Positioned(
        bottom: 24,
        left: 16,
        child: Material(
          color: Colors.transparent,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: alerts
                .map((a) => _buildToastCard(a, onDismiss: () {
                      setState(() => _dismissedAlertKeys.add(a.text));
                      _updateToastOverlay();
                    }))
                .toList(),
          ),
        ),
      ),
    );
    _toastOverlayEntry = entry;
    Overlay.of(context, rootOverlay: true).insert(entry);
  }

  double _asDouble(dynamic value) => value is num ? value.toDouble() : 0.0;

  String _formatCurrency(num value) => _currencyFormat.format(value);
  String _formatWeight(num value) => '${_weightFormat.format(value)} جم';

  @override
  Widget build(BuildContext context) {
    final isArabic = widget.isArabic;

    return Directionality(
      textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        body: SafeArea(
          child: _isLoading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? _buildErrorState()
              : _buildContent(),
        ),
      ),
    );
  }

  Widget _buildErrorState() {
    final isArabic = widget.isArabic;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, size: _s(52), color: Colors.red.shade400),
          SizedBox(height: _s(12)),
          Text(
            isArabic ? 'تعذّر تحميل البيانات' : 'Failed to load data',
            style: TextStyle(fontSize: _s(18), fontWeight: FontWeight.bold),
          ),
          SizedBox(height: _s(8)),
          Padding(
            padding: EdgeInsets.symmetric(horizontal: _s(24)),
            child: Text(
              _error ?? '',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey, fontSize: _s(12)),
            ),
          ),
          SizedBox(height: _s(16)),
          ElevatedButton.icon(
            onPressed: _loadData,
            icon: const Icon(Icons.refresh),
            label: Text(isArabic ? 'إعادة المحاولة' : 'Try Again'),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    final globalSnapshot =
        (_response?['global_snapshot'] as Map<String, dynamic>?) ?? {};
    final kpis = (_response?['kpis'] as Map<String, dynamic>?) ?? {};
    final valuation = (_response?['valuation'] as Map<String, dynamic>?) ?? {};
    final liquidity = (_response?['liquidity'] as Map<String, dynamic>?) ?? {};
    final safeBoxes = (_response?['safe_boxes'] as List?) ?? [];
    final sensitiveOps = (_response?['sensitive_operations'] as List?) ?? [];
    final series = (_response?['series'] as Map<String, dynamic>?) ?? {};
    final salesPurchasesSummary =
        (_response?['sales_purchases_summary'] as Map<String, dynamic>?) ?? {};

    final goldByKarat = (kpis['gold_by_karat'] as Map<String, dynamic>?) ?? {};
    final rangeSelectorHeight =
      MediaQuery.sizeOf(context).width < 760 ? _s(96) : _s(56);

    return RefreshIndicator(
      onRefresh: _loadData,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          // === 1. Global Snapshot Header ===
          SliverToBoxAdapter(
            child: _buildGlobalSnapshotHeader(
              globalSnapshot,
              valuation,
              series,
            ),
          ),

          // === 2. Time Range Selector (TOP) ===
          SliverPersistentHeader(
            pinned: true,
            delegate: _StickyRangeSelectorDelegate(
              child: _buildRangeSelector(),
              backgroundColor: Theme.of(context).scaffoldBackgroundColor,
              height: rangeSelectorHeight,
              horizontalPadding: _s(16),
              verticalPadding: _s(8),
            ),
          ),

          // === 2b. Critical Alerts Banner ===
          SliverToBoxAdapter(child: _buildCriticalAlertsBanner()),

          // === 2c. Admin Quick Actions ===
          SliverToBoxAdapter(child: _buildAdminQuickActionsBar()),

          // === 3. Time-range-dependent content ===
          SliverToBoxAdapter(
            child: Column(
              children: [
                // Gram Profit KPI (weight hero — top)
                Padding(
                  padding: EdgeInsets.fromLTRB(_s(16), _s(8), _s(16), 0),
                  child: _buildGramProfitKpi(),
                ),

                // Cash Profit Card (follows time range)
                HeroProfitSection(
                  kpis: kpis,
                  liquidity: liquidity,
                  salesPurchasesSummary: salesPurchasesSummary,
                  isArabic: widget.isArabic,
                  scale: _s,
                  currencyFormat: _currencyFormat,
                  summaryPeriod: _summaryPeriod,
                ),

                // KPI Grid
                Padding(
                  padding: EdgeInsets.all(_s(16)),
                  child: _buildKpiGrid(
                    goldByKarat: goldByKarat,
                    liquidity: liquidity,
                  ),
                ),
                // Sales / Purchases / Expenses Summary
                Padding(
                  padding: EdgeInsets.symmetric(
                    horizontal: _s(16),
                    vertical: _s(8),
                  ),
                  child: DashboardSummaryTabsCard(
                    periodData: (salesPurchasesSummary[_summaryPeriod]
                            as Map<String, dynamic>?) ??
                        {},
                    prevData: (salesPurchasesSummary['prev_$_summaryPeriod']
                            as Map<String, dynamic>?) ??
                        {},
                    isArabic: widget.isArabic,
                    currencyFormat: _currencyFormat,
                    weightFormat: _weightFormat,
                    scale: _s,
                  ),
                ),
              ],
            ),
          ),

          // === 4. Vaults & Custody (Horizontal List) ===
          SliverToBoxAdapter(
            child: VaultsSection(
              safeBoxes: safeBoxes,
              api: widget.api,
              isArabic: widget.isArabic,
              scale: _s,
              currencyFormat: _currencyFormat,
              weightFormat: _weightFormat,
            ),
          ),

          // === 5. Sensitive Operations Feed ===
          SliverToBoxAdapter(
            child: SensitiveOperationsSection(
              operations: sensitiveOps,
              isArabic: widget.isArabic,
              scale: _s,
            ),
          ),

          SliverToBoxAdapter(child: SizedBox(height: _s(24))),
        ],
      ),
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // 1. GLOBAL SNAPSHOT HEADER
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildGlobalSnapshotHeader(
    Map<String, dynamic> snapshot,
    Map<String, dynamic> valuation,
    Map<String, dynamic> series,
  ) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final netPosition = _asDouble(snapshot['net_financial_position']);
    final goldPrice = _asDouble(snapshot['gold_price_24k']);
    final goldChange = snapshot['gold_price_change_pct'];

    final changeValue = goldChange is num ? goldChange.toDouble() : null;
    final isPositive = (changeValue ?? 0) >= 0;

    final goldPriceSeries = _extractSeries(series, const [
      'gold_price',
      'gold_price_24k',
      'gold_price_series',
      'gold_price_trend',
    ]);

    final isCompact = MediaQuery.of(context).size.width < 700;
    final isDark = theme.brightness == Brightness.dark;

    return Container(
      padding: EdgeInsets.fromLTRB(_s(16), _s(12), _s(16), _s(16)),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: isDark
              ? [
                  AppColors.primaryGold.withValues(alpha: 0.20),
                  theme.scaffoldBackgroundColor.withValues(alpha: 0.95),
                  AppColors.darkGold.withValues(alpha: 0.08),
                ]
              : [
                  AppColors.primaryGold.withValues(alpha: 0.22),
                  const Color(0xFFFFFBF0),
                  AppColors.lightGold.withValues(alpha: 0.35),
                ],
        ),
        border: Border(
          bottom: BorderSide(
            color: AppColors.primaryGold.withValues(
              alpha: isDark ? 0.28 : 0.35,
            ),
            width: 1.5,
          ),
        ),
      ),
      child: Column(
        children: [
          // Top Row: Title + Actions
          Row(
            children: [
              IconButton(
                icon: Icon(Icons.arrow_forward_ios, size: _s(20)),
                onPressed: () => Navigator.of(context).pop(),
              ),
              const Spacer(),
              Text(
                isArabic ? 'لوحة تحكم المدير' : 'Admin Dashboard',
                style: theme.textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
              ),
              const Spacer(),
              IconButton(
                icon: Icon(Icons.notifications_outlined, size: _s(22)),
                onPressed: () async {
                  await Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => SystemAlertsScreen(
                        api: widget.api,
                        isArabic: widget.isArabic,
                      ),
                    ),
                  );
                  _loadData();
                },
              ),
              IconButton(
                icon: Icon(Icons.refresh, size: _s(22)),
                onPressed: _isLoading ? null : _loadData,
              ),
            ],
          ),
          SizedBox(height: _s(16)),

          // Main Snapshot Row
          if (isCompact)
            Column(
              children: [
                _buildNetPositionCard(theme, isArabic, netPosition),
                SizedBox(height: _s(12)),
                _buildGoldPriceCard(
                  theme,
                  isPositive,
                  goldPrice,
                  changeValue,
                  goldPriceSeries: goldPriceSeries,
                ),
              ],
            )
          else
            Row(
              children: [
                Expanded(
                  flex: 3,
                  child: _buildNetPositionCard(theme, isArabic, netPosition),
                ),
                SizedBox(width: _s(12)),
                Expanded(
                  flex: 2,
                  child: _buildGoldPriceCard(
                    theme,
                    isPositive,
                    goldPrice,
                    changeValue,
                    goldPriceSeries: goldPriceSeries,
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _buildRangeSelector() {
    final isArabic = widget.isArabic;

    return Row(
      children: [
        Expanded(
          child: Wrap(
            spacing: _s(8),
            runSpacing: _s(8),
            children: [
              ChoiceChip(
                label: Text(isArabic ? 'اليوم' : 'Today'),
                selected: _timeRange == _TimeRange.today,
                onSelected: (_) {
                  setState(() => _timeRange = _TimeRange.today);
                  _loadGramProfit();
                },
              ),
              ChoiceChip(
                label: Text(isArabic ? 'هذا الشهر' : 'This Month'),
                selected: _timeRange == _TimeRange.month,
                onSelected: (_) {
                  setState(() => _timeRange = _TimeRange.month);
                  _loadGramProfit();
                },
              ),
              ChoiceChip(
                label: Text(isArabic ? 'هذه السنة' : 'This Year'),
                selected: _timeRange == _TimeRange.year,
                onSelected: (_) {
                  setState(() => _timeRange = _TimeRange.year);
                  _loadGramProfit();
                },
              ),
            ],
          ),
        ),
        TextButton.icon(
          onPressed: _isLoading ? null : _loadData,
          icon: Icon(Icons.refresh, size: _s(20)),
          label: Text(isArabic ? 'تحديث' : 'Refresh'),
        ),
      ],
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // CRITICAL ALERTS BANNER
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildCriticalAlertsBanner() {
    final alerts = _getAllAlerts();
    if (alerts.isEmpty) return const SizedBox.shrink();

    final hasCritical = alerts.any((a) => a.color == Colors.red);
    final bannerColor = hasCritical ? Colors.red : Colors.orange;
    final isAr = widget.isArabic;
    final first = alerts.first;

    return Padding(
      padding: EdgeInsets.fromLTRB(_s(16), _s(6), _s(16), 0),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(_s(10)),
          onTap: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => SystemAlertsScreen(
                api: widget.api,
                isArabic: isAr,
              ),
            ),
          ),
          child: Container(
            padding: EdgeInsets.symmetric(
              horizontal: _s(12),
              vertical: _s(9),
            ),
            decoration: BoxDecoration(
              color: bannerColor.withValues(alpha: 0.10),
              borderRadius: BorderRadius.circular(_s(10)),
              border: Border.all(
                color: bannerColor.withValues(alpha: 0.35),
                width: 1,
              ),
            ),
            child: Row(
              children: [
                Icon(first.icon, color: bannerColor, size: _s(17)),
                SizedBox(width: _s(8)),
                Expanded(
                  child: Text(
                    first.text,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: _s(12),
                      fontWeight: FontWeight.w600,
                      fontFamily: 'Cairo',
                      color: bannerColor,
                    ),
                  ),
                ),
                if (alerts.length > 1) ...[
                  SizedBox(width: _s(6)),
                  Container(
                    padding: EdgeInsets.symmetric(
                      horizontal: _s(6),
                      vertical: _s(2),
                    ),
                    decoration: BoxDecoration(
                      color: bannerColor,
                      borderRadius: BorderRadius.circular(_s(20)),
                    ),
                    child: Text(
                      '+${alerts.length - 1}',
                      style: TextStyle(
                        fontSize: _s(10),
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ],
                SizedBox(width: _s(6)),
                Icon(
                  Icons.arrow_forward_ios_rounded,
                  size: _s(12),
                  color: bannerColor,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // ADMIN QUICK ACTIONS BAR
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildAdminQuickActionsBar() {
    final isAr = widget.isArabic;
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    final actions = [
      (
        icon: Icons.point_of_sale_outlined,
        label: isAr ? 'إغلاق الوردية' : 'Shift Close',
        color: Colors.indigo,
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => ShiftClosingScreen(
              api: widget.api,
              isArabic: isAr,
            ),
          ),
        ),
      ),
      (
        icon: Icons.account_balance_outlined,
        label: isAr ? 'الخزائن' : 'Safe Boxes',
        color: Colors.teal,
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => const SafeBoxesDashboardScreen(),
          ),
        ),
      ),
      (
        icon: Icons.people_outline_rounded,
        label: isAr ? 'الموظفون' : 'Employees',
        color: Colors.deepPurple,
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => EmployeesScreen(
              api: widget.api,
              isArabic: isAr,
            ),
          ),
        ),
      ),
      (
        icon: Icons.notifications_outlined,
        label: isAr ? 'التنبيهات' : 'Alerts',
        color: Colors.orange,
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => SystemAlertsScreen(
              api: widget.api,
              isArabic: isAr,
            ),
          ),
        ),
      ),
      (
        icon: Icons.history_rounded,
        label: isAr ? 'سجل العمليات' : 'Audit Log',
        color: Colors.blueGrey,
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const AuditLogScreen()),
        ),
      ),
    ];

    return Padding(
      padding: EdgeInsets.fromLTRB(_s(16), _s(10), _s(16), 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            isAr ? 'إجراءات سريعة' : 'Quick Actions',
            style: theme.textTheme.labelSmall?.copyWith(
              fontWeight: FontWeight.w700,
              fontSize: _s(11),
              color: theme.hintColor,
              fontFamily: 'Cairo',
            ),
          ),
          SizedBox(height: _s(8)),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: actions.map((a) {
                return Padding(
                  padding: EdgeInsets.only(left: isAr ? 0 : _s(8), right: isAr ? _s(8) : 0),
                  child: _buildQuickActionChip(
                    icon: a.icon,
                    label: a.label,
                    color: a.color,
                    isDark: isDark,
                    onTap: a.onTap,
                  ),
                );
              }).toList(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildQuickActionChip({
    required IconData icon,
    required String label,
    required Color color,
    required bool isDark,
    required VoidCallback onTap,
  }) {
    return Material(
      color: color.withValues(alpha: isDark ? 0.15 : 0.09),
      borderRadius: BorderRadius.circular(_s(10)),
      child: InkWell(
        borderRadius: BorderRadius.circular(_s(10)),
        onTap: onTap,
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: _s(12), vertical: _s(8)),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, color: color, size: _s(16)),
              SizedBox(width: _s(6)),
              Text(
                label,
                style: TextStyle(
                  fontSize: _s(12),
                  fontWeight: FontWeight.w600,
                  fontFamily: 'Cairo',
                  color: color,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildKpiGrid({
    required Map<String, dynamic> goldByKarat,
    required Map<String, dynamic> liquidity,
  }) {
    return Row(
      children: [
        Expanded(
          child: KaratDistributionCard(
            goldByKarat: goldByKarat,
            isArabic: widget.isArabic,
            scale: _s,
            weightFormat: _weightFormat,
          ),
        ),
        SizedBox(width: _s(12)),
        Expanded(
          child: LiquidityBreakdownCard(
            liquidity: liquidity,
            isArabic: widget.isArabic,
            scale: _s,
            currencyFormat: _currencyFormat,
          ),
        ),
      ],
    );
  }

  Widget _buildNetPositionCard(
    ThemeData theme,
    bool isArabic,
    double netPosition,
  ) {
    final isDark = theme.brightness == Brightness.dark;
    return Container(
      padding: EdgeInsets.all(_s(16)),
      decoration: BoxDecoration(
        color: theme.cardColor,
        borderRadius: BorderRadius.circular(16),
        border: isDark
            ? Border.all(
                color: AppColors.primaryGold.withValues(alpha: 0.25),
              )
            : Border.all(
                color: AppColors.primaryGold.withValues(alpha: 0.50),
                width: 1.2,
              ),
        boxShadow: [
          BoxShadow(
            color: AppColors.primaryGold.withValues(
              alpha: isDark ? 0.10 : 0.14,
            ),
            blurRadius: 16,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.account_balance,
                color: AppColors.primaryGold,
                size: _s(20),
              ),
              SizedBox(width: _s(6)),
              Text(
                isArabic ? 'صافي المركز المالي' : 'Net Position',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.hintColor,
                  fontSize: _s(12),
                ),
              ),
            ],
          ),
          SizedBox(height: _s(8)),
          Text(
            _formatCurrency(netPosition),
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.bold,
              color: AppColors.primaryGold,
              fontSize: _s(22),
            ),
          ),
          Text(
            isArabic ? '(نقد + قيمة الذهب)' : '(Cash + Gold Value)',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.hintColor,
              fontSize: _s(11),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGoldPriceCard(
    ThemeData theme,
    bool isPositive,
    double goldPrice,
    double? changeValue, {
    List<double>? goldPriceSeries,
  }) {
    return GestureDetector(
      onTap: () {
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => GoldPriceHistoryReportScreen(
              api: widget.api,
              isArabic: widget.isArabic,
            ),
          ),
        );
      },
      child: Container(
        padding: EdgeInsets.all(_s(16)),
        decoration: BoxDecoration(
          color: theme.cardColor,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: (isPositive ? Colors.green : Colors.red).withValues(
              alpha: theme.brightness == Brightness.dark ? 0.40 : 0.55,
            ),
            width: 1.2,
          ),
          boxShadow: [
            BoxShadow(
              color: (isPositive ? Colors.green : Colors.red).withValues(
                alpha: theme.brightness == Brightness.dark ? 0.10 : 0.12,
              ),
              blurRadius: 14,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.show_chart,
                  color: isPositive ? Colors.green : Colors.red,
                  size: _s(20),
                ),
                SizedBox(width: _s(6)),
                Text(
                  '24K',
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ],
            ),
            SizedBox(height: _s(10)),
            Text(
              goldPrice > 0
                  ? '${goldPrice.toStringAsFixed(0)} $_currencySymbol'
                  : '-',
              style: theme.textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.bold,
                fontSize: _s(20),
              ),
            ),
            if (changeValue != null)
              Row(
                children: [
                  Icon(
                    isPositive ? Icons.arrow_upward : Icons.arrow_downward,
                    size: _s(14),
                    color: isPositive ? Colors.green : Colors.red,
                  ),
                  Text(
                    '${changeValue.abs().toStringAsFixed(1)}%',
                    style: TextStyle(
                      fontSize: _s(12),
                      fontWeight: FontWeight.bold,
                      color: isPositive ? Colors.green : Colors.red,
                    ),
                  ),
                ],
              ),
            if ((goldPriceSeries ?? const []).isNotEmpty) ...[
              SizedBox(height: _s(10)),
              SizedBox(
                height: _s(44),
                child: LineChart(
                  LineChartData(
                    gridData: const FlGridData(show: false),
                    titlesData: const FlTitlesData(show: false),
                    borderData: FlBorderData(show: false),
                    lineTouchData: const LineTouchData(enabled: false),
                    lineBarsData: [
                      LineChartBarData(
                        spots: _toSpots(
                          goldPriceSeries!.take(24).toList(),
                          goldPriceSeries.take(24).length,
                        ),
                        isCurved: true,
                        color: isPositive ? Colors.green : Colors.red,
                        barWidth: _s(2),
                        dotData: const FlDotData(show: false),
                        belowBarData: BarAreaData(
                          show: true,
                          color: (isPositive ? Colors.green : Colors.red)
                              .withValues(alpha: 0.12),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
            SizedBox(height: _s(8)),
            Text(
              widget.isArabic ? 'اضغط للتفاصيل' : 'Tap for details',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.hintColor,
                fontSize: _s(11),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── macOS-style floating notification toasts ──────────────────────────────
  /// Collects all current alerts from response data, filters dismissed ones.
  List<_AlertItem> _getAllAlerts() {
    if (_response == null) return [];
    final isArabic = widget.isArabic;
    final alerts = (_response!['alerts'] as Map<String, dynamic>?) ?? {};
    final items = <_AlertItem>[];

    // Critical bar alerts
    final rawItems = (alerts['critical_bar'] as List?) ?? [];
    for (final raw in rawItems) {
      final item = raw is Map ? raw : <String, dynamic>{};
      final severity = (item['severity']?.toString().toLowerCase() ?? 'warning');
      final isCrit = severity == 'critical';
      final msg = (isArabic
              ? item['message_ar']?.toString()
              : item['message_en']?.toString()) ??
          item['message']?.toString() ??
          '';
      if (msg.isNotEmpty) {
        items.add(_AlertItem(
          icon: isCrit ? Icons.error_outline : Icons.warning_amber_rounded,
          color: isCrit ? Colors.red : Colors.orange,
          text: msg,
        ));
      }
    }

    // Audit zone alerts
    final criticalCount = alerts['critical_unreviewed_count'];
    final unpostedCount = alerts['unposted_invoices_count'];
    final lastShift = alerts['last_shift_closing'] as Map<String, dynamic>?;
    final cashDiff = lastShift?['cash_difference'];
    final goldDiff = lastShift?['gold_pure_24k_difference'];

    final cCount = criticalCount is num ? criticalCount.toInt() : 0;
    final uCount = unpostedCount is num ? unpostedCount.toInt() : 0;
    final cDiff = cashDiff is num ? cashDiff.toDouble() : 0.0;
    final gDiff = goldDiff is num ? goldDiff.toDouble() : 0.0;

    if (cCount > 0) {
      items.add(_AlertItem(
        icon: Icons.warning_amber_rounded,
        color: Colors.red,
        text: isArabic
            ? '$cCount تنبيهات حرجة بانتظار المراجعة'
            : '$cCount critical alerts pending',
      ));
    }
    if (cDiff.abs() > 0.01) {
      items.add(_AlertItem(
        icon: Icons.account_balance_wallet,
        color: Colors.orange,
        text: isArabic
            ? 'فرق نقدي (${_formatCurrency(cDiff)}) في آخر إغلاق'
            : 'Cash difference (${_formatCurrency(cDiff)}) in last closing',
      ));
    }
    if (gDiff.abs() > 0.001) {
      items.add(_AlertItem(
        icon: Icons.auto_awesome,
        color: Colors.orange,
        text: isArabic
            ? 'فرق ذهب (${_formatWeight(gDiff)}) في آخر إغلاق'
            : 'Gold difference (${_formatWeight(gDiff)}) in last closing',
      ));
    }
    if (uCount > 0) {
      items.add(_AlertItem(
        icon: Icons.pending_actions,
        color: Colors.blue,
        text: isArabic
            ? '$uCount فاتورة بانتظار الترحيل'
            : '$uCount invoices pending posting',
      ));
    }

    return items.where((a) => !_dismissedAlertKeys.contains(a.text)).toList();
  }

  Widget _buildToastCard(_AlertItem alert, {required VoidCallback onDismiss}) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    // Accent color band: slightly tinted background based on alert color
    final bgColor = isDark
        ? Color.lerp(const Color(0xFF2C2C2E), alert.color, 0.06)!
        : Color.lerp(Colors.white, alert.color, 0.05)!;

    return TweenAnimationBuilder<double>(
      key: Key('toast_${alert.text.hashCode}'),
      tween: Tween(begin: 0.0, end: 1.0),
      duration: const Duration(milliseconds: 420),
      curve: Curves.easeOutCubic,
      builder: (context, t, child) => Transform.translate(
        offset: Offset(-40 * (1 - t), 0),
        child: Opacity(opacity: t, child: child),
      ),
      child: Container(
        width: 300,
        margin: const EdgeInsets.only(bottom: 8),
        decoration: BoxDecoration(
          color: bgColor,
          borderRadius: BorderRadius.circular(12),
          border: Border(
            left: BorderSide(color: alert.color, width: 4),
            top: BorderSide(
              color: alert.color.withValues(alpha: 0.22),
              width: 0.8,
            ),
            right: BorderSide(
              color: alert.color.withValues(alpha: 0.22),
              width: 0.8,
            ),
            bottom: BorderSide(
              color: alert.color.withValues(alpha: 0.22),
              width: 0.8,
            ),
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: isDark ? 0.45 : 0.18),
              blurRadius: 20,
              spreadRadius: 0,
              offset: const Offset(0, 6),
            ),
            BoxShadow(
              color: alert.color.withValues(alpha: 0.12),
              blurRadius: 10,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 12, 8, 12),
              child: Icon(alert.icon, color: alert.color, size: 18),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 11),
                child: Text(
                  alert.text,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: isDark
                        ? Colors.white.withValues(alpha: 0.92)
                        : const Color(0xFF1C1C1E),
                    fontSize: 12.5,
                    fontWeight: FontWeight.w500,
                    height: 1.4,
                  ),
                ),
              ),
            ),
            GestureDetector(
              onTap: onDismiss,
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: Icon(
                  Icons.close,
                  size: 14,
                  color: (isDark ? Colors.white : Colors.black)
                      .withValues(alpha: 0.40),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<double> _extractSeries(
    Map<String, dynamic> series,
    List<String> directKeys,
  ) {
    // 1) direct keys
    for (final key in directKeys) {
      final list = _castNumberList(series[key]);
      if (list.isNotEmpty) return list;
    }

    // 2) common composite container
    final composite = series['sales_vs_purchases'];
    if (composite is Map<String, dynamic>) {
      final list = _extractSeries(composite, directKeys);
      if (list.isNotEmpty) return list;
    }

    // 3) range keyed containers
    for (final rangeKey in _rangeKeyCandidates(_timeRange)) {
      final ranged = series[rangeKey];
      if (ranged is Map<String, dynamic>) {
        final list = _extractSeries(ranged, directKeys);
        if (list.isNotEmpty) return list;
      }
    }

    return const [];
  }

  List<String> _rangeKeyCandidates(_TimeRange range) {
    switch (range) {
      case _TimeRange.today:
        return const ['today', '1d', 'day', 'last_1_day', 'last_24_hours'];
      case _TimeRange.month:
        return const ['month', '30d', 'last_30_days', 'last30', 'last_month'];
      case _TimeRange.year:
        return const ['year', '12m', 'last_year', 'ytd', 'annual'];
    }
  }

  List<double> _castNumberList(dynamic value) {
    if (value is List) {
      return value
          .map((e) => e is num ? e.toDouble() : null)
          .whereType<double>()
          .toList();
    }
    return const [];
  }

  List<FlSpot> _toSpots(List<double> series, int length) {
    if (series.isEmpty) return const [];
    final spots = <FlSpot>[];
    for (var i = 0; i < length; i++) {
      final value = i < series.length ? series[i] : series.last;
      spots.add(FlSpot(i.toDouble(), value));
    }
    return spots;
  }



  Widget _heroChip({
    required IconData icon,
    required String label,
    required String value,
    required Color color,
  }) {
    final theme = Theme.of(context);
    return Container(
      padding: EdgeInsets.symmetric(horizontal: _s(10), vertical: _s(6)),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.18)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: _s(12), color: color),
          SizedBox(width: _s(4)),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: TextStyle(
                  fontSize: _s(9),
                  color: theme.hintColor,
                ),
              ),
              Text(
                value,
                style: TextStyle(
                  fontSize: _s(11),
                  fontWeight: FontWeight.bold,
                  color: color,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _layerChip({
    required String label,
    required double value,
    required bool isPositive,
    required ThemeData theme,
  }) {
    final color = isPositive
        ? (value >= 0 ? const Color(0xFF1B9E4B) : Colors.red.shade600)
        : Colors.red.shade600;
    final sign = isPositive ? '+' : '−';
    return Column(
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: _s(9),
            color: theme.hintColor,
            fontWeight: FontWeight.w500,
          ),
        ),
        SizedBox(height: _s(2)),
        Text(
          '$sign${_formatWeight(value.abs())}',
          style: TextStyle(
            fontSize: _s(11),
            fontWeight: FontWeight.bold,
            color: color,
          ),
        ),
      ],
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // 3b. GRAM PROFIT KPI  (follows time range)
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildGramProfitKpi() {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    if (_gramProfitLoading && _gramProfitData == null) {
      return Container(
        height: _s(100),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(_s(20)),
          color: theme.cardColor,
        ),
        child: Center(
          child: CircularProgressIndicator(color: AppColors.primaryGold),
        ),
      );
    }

    final g = _gramProfitData;
    if (g == null) return const SizedBox.shrink();

    double gd(String k) => (g[k] is num) ? (g[k] as num).toDouble() : 0.0;

    final netProfit = gd('net_profit');
    final netProfitWeight = gd('net_profit_weight');
    final avgSell = gd('avg_sell_per_gram');
    final avgBuy = gd('avg_buy_per_gram');
    final marginPerGram = gd('margin_per_gram');
    final netMarginPct = gd('net_margin_pct');
    final weightSold = gd('weight_sold');
    final tradingProfitWeight = gd('trading_profit_weight');
    final extraRevenueWeight = gd('total_extra_revenue_weight');
    final expenseWeightDirect = gd('expense_weight_direct');
    final expenseCashWeight = gd('expense_cash_as_weight');
    final totalExpensesWeight = expenseWeightDirect + expenseCashWeight;
    final mainKarat = g['main_karat']?.toString() ?? '21';
    final isProfit = netProfitWeight >= 0;

    final profitColor = isProfit ? AppColors.success : Colors.red.shade600;

    // Dynamic period label
    final String periodLabel;
    switch (_timeRange) {
      case _TimeRange.today:
        periodLabel = isArabic ? 'اليوم' : 'Today';
        break;
      case _TimeRange.month:
        periodLabel = isArabic ? 'هذا الشهر' : 'This month';
        break;
      case _TimeRange.year:
        periodLabel = isArabic ? 'هذه السنة' : 'This year';
        break;
    }

    return Container(
      padding: EdgeInsets.all(_s(20)),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [
            AppColors.primaryGold.withValues(alpha: 0.08),
            theme.cardColor,
          ],
        ),
        borderRadius: BorderRadius.circular(_s(20)),
        border: Border.all(
          color: AppColors.primaryGold.withValues(alpha: 0.20),
          width: 1.5,
        ),
        boxShadow: [
          BoxShadow(
            color: AppColors.primaryGold.withValues(alpha: 0.06),
            blurRadius: 16,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Title row ────────────────────────────────────────
          Row(
            children: [
              Icon(
                Icons.auto_graph,
                color: AppColors.primaryGold,
                size: _s(20),
              ),
              SizedBox(width: _s(6)),
              Text(
                isArabic ? 'ربح الجرام الذهبي' : 'Gold Gram Profit',
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: theme.textTheme.bodySmall?.color,
                ),
              ),
              const Spacer(),
              Container(
                padding: EdgeInsets.symmetric(
                  horizontal: _s(8),
                  vertical: _s(3),
                ),
                decoration: BoxDecoration(
                  color: AppColors.primaryGold.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  periodLabel,
                  style: TextStyle(
                    fontSize: _s(10),
                    fontWeight: FontWeight.w600,
                    color: AppColors.primaryGold,
                  ),
                ),
              ),
            ],
          ),
          SizedBox(height: _s(10)),

          // ── Hero number: WEIGHT PROFIT ───────────────────────
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                _formatWeight(netProfitWeight),
                style: theme.textTheme.displaySmall?.copyWith(
                  fontWeight: FontWeight.w900,
                  color: profitColor,
                  fontSize: _s(30),
                  letterSpacing: -0.5,
                ),
              ),
              SizedBox(width: _s(6)),
              Padding(
                padding: EdgeInsets.only(bottom: _s(4)),
                child: Text(
                  isArabic ? 'عيار ($mainKarat)' : 'k($mainKarat)',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: profitColor.withValues(alpha: 0.7),
                    fontWeight: FontWeight.w600,
                    fontSize: _s(13),
                  ),
                ),
              ),
            ],
          ),

          // ── Cash equivalent + Margin badge row ───────────────
          SizedBox(height: _s(4)),
          Row(
            children: [
              Container(
                padding: EdgeInsets.symmetric(
                  horizontal: _s(8),
                  vertical: _s(3),
                ),
                decoration: BoxDecoration(
                  color: profitColor.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '≈ ${_formatCurrency(netProfit)}',
                  style: TextStyle(
                    fontSize: _s(11),
                    fontWeight: FontWeight.bold,
                    color: profitColor,
                  ),
                ),
              ),
              SizedBox(width: _s(6)),
              Container(
                padding: EdgeInsets.symmetric(
                  horizontal: _s(8),
                  vertical: _s(3),
                ),
                decoration: BoxDecoration(
                  color: profitColor.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  '${netMarginPct.toStringAsFixed(1)}% ${isArabic ? "هامش" : "margin"}',
                  style: TextStyle(
                    fontSize: _s(11),
                    fontWeight: FontWeight.bold,
                    color: profitColor,
                  ),
                ),
              ),
            ],
          ),

          SizedBox(height: _s(14)),

          // ── Chips row ────────────────────────────────────────
          Wrap(
            spacing: _s(8),
            runSpacing: _s(6),
            children: [
              _heroChip(
                icon: Icons.trending_up,
                label: isArabic ? 'بيع/جم' : 'Sell/g',
                value: _formatCurrency(avgSell),
                color: const Color(0xFF1B9E4B),
              ),
              _heroChip(
                icon: Icons.trending_down,
                label: isArabic ? 'شراء/جم' : 'Buy/g',
                value: _formatCurrency(avgBuy),
                color: Colors.orange.shade700,
              ),
              _heroChip(
                icon: Icons.swap_horiz,
                label: isArabic ? 'فارق/جم' : 'Margin/g',
                value: _formatCurrency(marginPerGram),
                color: marginPerGram >= 0 ? Colors.teal : Colors.red,
              ),
              _heroChip(
                icon: Icons.monitor_weight_outlined,
                label: isArabic ? 'المباع' : 'Sold',
                value: _formatWeight(weightSold),
                color: Colors.blue,
              ),
            ],
          ),

          // ── Layer breakdown row ──────────────────────────────
          if (tradingProfitWeight.abs() > 0.001 || extraRevenueWeight.abs() > 0.001 || totalExpensesWeight.abs() > 0.001) ...[
            SizedBox(height: _s(12)),
            Container(
              padding: EdgeInsets.symmetric(horizontal: _s(10), vertical: _s(8)),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
                borderRadius: BorderRadius.circular(_s(10)),
                border: Border.all(
                  color: AppColors.primaryGold.withValues(alpha: 0.10),
                ),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: _layerChip(
                      label: isArabic ? 'متاجرة' : 'Trading',
                      value: tradingProfitWeight,
                      isPositive: true,
                      theme: theme,
                    ),
                  ),
                  if (extraRevenueWeight.abs() > 0.001) ...[
                    SizedBox(width: _s(4)),
                    Expanded(
                      child: _layerChip(
                        label: isArabic ? 'إيرادات' : 'Revenue',
                        value: extraRevenueWeight,
                        isPositive: true,
                        theme: theme,
                      ),
                    ),
                  ],
                  SizedBox(width: _s(4)),
                  Expanded(
                    child: _layerChip(
                      label: isArabic ? 'مصاريف' : 'Expenses',
                      value: totalExpensesWeight,
                      isPositive: false,
                      theme: theme,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}


class _StickyRangeSelectorDelegate extends SliverPersistentHeaderDelegate {
  final Widget child;
  final Color backgroundColor;
  final double height;
  final double horizontalPadding;
  final double verticalPadding;

  _StickyRangeSelectorDelegate({
    required this.child,
    required this.backgroundColor,
    required this.height,
    required this.horizontalPadding,
    required this.verticalPadding,
  });

  @override
  double get minExtent => height;

  @override
  double get maxExtent => height;

  @override
  Widget build(
    BuildContext context,
    double shrinkOffset,
    bool overlapsContent,
  ) {
    final isScrolled = overlapsContent || shrinkOffset > 0;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      padding: EdgeInsets.fromLTRB(
        horizontalPadding,
        verticalPadding,
        horizontalPadding,
        verticalPadding,
      ),
      decoration: BoxDecoration(
        color: backgroundColor,
        boxShadow: isScrolled
            ? [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.04),
                  blurRadius: 6,
                  offset: const Offset(0, 2),
                ),
              ]
            : const [],
        border: isScrolled
            ? Border(
                bottom: BorderSide(
                  color: Theme.of(context).dividerColor.withValues(alpha: 0.3),
                ),
              )
            : null,
      ),
      alignment: Alignment.centerLeft,
      child: child,
    );
  }

  @override
  bool shouldRebuild(covariant _StickyRangeSelectorDelegate oldDelegate) {
    return oldDelegate.child != child ||
        oldDelegate.backgroundColor != backgroundColor ||
        oldDelegate.height != height ||
        oldDelegate.horizontalPadding != horizontalPadding ||
        oldDelegate.verticalPadding != verticalPadding;
  }
}

class _AlertItem {
  final IconData icon;
  final Color color;
  final String text;

  _AlertItem({required this.icon, required this.color, required this.text});
}
