import 'dart:ui' show ImageFilter;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_staggered_animations/flutter_staggered_animations.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../api_service.dart';
import '../../models/safe_box_model.dart';
import '../../providers/settings_provider.dart';
import '../../theme/app_theme.dart';
import '../audit_log_screen.dart';
import '../safe_boxes_screen.dart';
import 'gold_price_history_report_screen.dart';
import 'sales_vs_purchases_trend_report_screen.dart';
import 'system_alerts_screen.dart';

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
  Map<String, dynamic>? _safeBoxRecon;
  bool _isLoading = false;
  String? _error;
  String? _safeBoxReconError;

  int? _expandedVaultSafeBoxId;
  int? _pressedVaultSafeBoxId;

  _TimeRange _timeRange = _TimeRange.today;

  // ── Overlay alert state ──────────────────────────────────────────────────
  /// Alerts that the user has manually dismissed (by id/text key).
  final Set<String> _dismissedAlertKeys = {};

  // ── Vault ordering ────────────────────────────────────────────────────────
  /// Local ordered list of safe-box ids (persisted in SharedPreferences).
  List<int> _vaultOrder = [];
  /// Safe-box ids that were opened in the current session ("recently used").
  final Set<int> _recentVaultIds = {};
  static const String _kVaultOrderKey = 'dashboard_vault_order';
  /// Horizontal scroll controller for the vault list (mouse wheel support).
  final ScrollController _vaultScrollController = ScrollController();
  /// When true the vault list becomes a drag-and-drop reorderable list.
  bool _isReorderingVaults = false;

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
    _loadVaultOrder();
    _loadData();
  }

  // ── Vault order persistence ──────────────────────────────────────────────
  Future<void> _loadVaultOrder() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getStringList(_kVaultOrderKey) ?? [];
      if (mounted) {
        setState(() {
          _vaultOrder = raw
              .map((s) => int.tryParse(s))
              .whereType<int>()
              .toList();
        });
      }
    } catch (_) {}
  }

  Future<void> _saveVaultOrder() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setStringList(
        _kVaultOrderKey,
        _vaultOrder.map((id) => id.toString()).toList(),
      );
    } catch (_) {}
  }

  /// Returns safe-box list sorted: recently-used first, then user order.
  List<Map<String, dynamic>> _sortedVaults(List<dynamic> raw) {
    final maps = raw.whereType<Map<String, dynamic>>().toList();

    // Seed _vaultOrder with any new ids not yet stored
    final knownIds = _vaultOrder.toSet();
    for (final sb in maps) {
      final id = sb['id'];
      final sbId = id is int ? id : int.tryParse(id?.toString() ?? '');
      if (sbId != null && !knownIds.contains(sbId)) {
        _vaultOrder.add(sbId);
        knownIds.add(sbId);
      }
    }

    maps.sort((a, b) {
      final aId = a['id'] is int ? a['id'] as int : int.tryParse(a['id']?.toString() ?? '') ?? -1;
      final bId = b['id'] is int ? b['id'] as int : int.tryParse(b['id']?.toString() ?? '') ?? -1;

      final aRecent = _recentVaultIds.contains(aId);
      final bRecent = _recentVaultIds.contains(bId);
      if (aRecent && !bRecent) return -1;
      if (!aRecent && bRecent) return 1;

      final aPos = _vaultOrder.indexOf(aId);
      final bPos = _vaultOrder.indexOf(bId);
      final aRank = aPos < 0 ? 9999 : aPos;
      final bRank = bPos < 0 ? 9999 : bPos;
      return aRank.compareTo(bRank);
    });

    return maps;
  }

  @override
  void dispose() {
    _vaultScrollController.dispose();
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
      _safeBoxReconError = null;
    });

    try {
      final dashboardFuture = widget.api.getAdminDashboard();
      final reconFuture = widget.api.getSafeBoxesReconciliation(
        safeType: 'cash',
      );

      final result = await dashboardFuture;
      if (!mounted) return;

      Map<String, dynamic>? recon;
      String? reconError;
      try {
        recon = await reconFuture;
      } catch (e) {
        reconError = e.toString();
      }

      if (!mounted) return;
      setState(() {
        _response = result;
        _safeBoxRecon = recon;
        _safeBoxReconError = reconError;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  double _asDouble(dynamic value) => value is num ? value.toDouble() : 0.0;

  double? _asDoubleOrNull(dynamic value) =>
      value is num ? value.toDouble() : null;

  int _asInt(dynamic value) =>
      value is int ? value : (value is num ? value.toInt() : 0);

  String _formatCurrency(num value) => _currencyFormat.format(value);
  String _formatWeight(num value) => '${_weightFormat.format(value)} جم';

  @override
  Widget build(BuildContext context) {
    final isArabic = widget.isArabic;

    return Directionality(
      textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        body: Stack(
          children: [
            SafeArea(
              child: _isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
                  ? _buildErrorState()
                  : _buildContent(),
            ),
            // macOS-style floating notification toasts (bottom-left corner)
            if (!_isLoading && _error == null)
              PositionedDirectional(
                bottom: 24,
                start: 16,
                child: SafeArea(
                  child: _buildFloatingAlerts(),
                ),
              ),
          ],
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
          SliverToBoxAdapter(
            child: Padding(
              padding: EdgeInsets.fromLTRB(_s(16), _s(4), _s(16), 0),
              child: _buildRangeSelector(),
            ),
          ),

          // === 3. HERO Profit Card (always TODAY, range-independent) ===
          SliverToBoxAdapter(
            child: _buildHeroProfitSection(kpis, liquidity),
          ),

          // === 4. Safe Box Reconciliation ===
          SliverToBoxAdapter(
            child: Padding(
              padding: EdgeInsets.fromLTRB(_s(16), _s(4), _s(16), 0),
              child: _buildSafeBoxReconciliationCard(),
            ),
          ),

          // === 5. Time-range-dependent content (animated on switch) ===
          SliverToBoxAdapter(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 300),
              transitionBuilder: (child, animation) => FadeTransition(
                opacity: animation,
                child: child,
              ),
              child: Column(
                key: ValueKey(_timeRange),
                children: [
                  // KPI Grid
                  Padding(
                    padding: EdgeInsets.all(_s(16)),
                    child: _buildKpiGrid(
                      kpis: kpis,
                      series: series,
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
                    child: _buildSalesSummaryCard(salesPurchasesSummary),
                  ),
                ],
              ),
            ),
          ),

          // === 6. Vaults & Custody (Horizontal List) ===
          SliverToBoxAdapter(child: _buildVaultsSection(safeBoxes)),

          // === 7. Sensitive Operations Feed ===
          SliverToBoxAdapter(
            child: _buildSensitiveOperationsSection(sensitiveOps),
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
                onSelected: (_) =>
                    setState(() => _timeRange = _TimeRange.today),
              ),
              ChoiceChip(
                label: Text(isArabic ? 'هذا الشهر' : 'This Month'),
                selected: _timeRange == _TimeRange.month,
                onSelected: (_) =>
                    setState(() => _timeRange = _TimeRange.month),
              ),
              ChoiceChip(
                label: Text(isArabic ? 'هذه السنة' : 'This Year'),
                selected: _timeRange == _TimeRange.year,
                onSelected: (_) =>
                    setState(() => _timeRange = _TimeRange.year),
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
  // SALES / PURCHASES / EXPENSES SUMMARY CARD
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildSalesSummaryCard(Map<String, dynamic> summary) {
    final isArabic = widget.isArabic;
    final theme = Theme.of(context);

    final periodData =
        (summary[_summaryPeriod] as Map<String, dynamic>?) ?? {};
    final sales = (periodData['sales'] as Map<String, dynamic>?) ?? {};
    final purchases = (periodData['purchases'] as Map<String, dynamic>?) ?? {};
    final expenses = (periodData['expenses'] as Map<String, dynamic>?) ?? {};
    final scrapData = (periodData['scrap_purchases'] as Map<String, dynamic>?) ?? {};

    final salesValue = _asDouble(sales['total_value']);
    final salesWeight = _asDouble(sales['total_weight']);
    final salesDocs = sales['docs'] as int? ?? 0;

    final purchasesValue = _asDouble(purchases['total_value']);
    final purchasesWeight = _asDouble(purchases['total_weight']);
    final purchasesDocs = purchases['docs'] as int? ?? 0;

    final expensesValue = _asDouble(expenses['total_value']);

    final scrapValue = _asDouble(scrapData['total_value']);
    final scrapWeight = _asDouble(scrapData['total_weight']);
    final scrapDocs = scrapData['docs'] as int? ?? 0;
    final scrapAvgRate = _asDouble(scrapData['avg_rate']);
    final scrapCumWeight = _asDouble(scrapData['cumulative_weight']);

    const scrapColor = Color(0xFF7B4F2E);

    final byKaratSales = (sales['by_karat'] as List?) ?? [];
    final byKaratPurchases = (purchases['by_karat'] as List?) ?? [];
    final byUserSales = (sales['by_user'] as List?) ?? [];
    final byUserPurchases = (purchases['by_user'] as List?) ?? [];
    final expByAccount = (expenses['by_account'] as List?) ?? [];

    Widget metricTile(
      String label,
      String value,
      String sub,
      IconData icon,
      Color color,
    ) {
      return Container(
        padding: EdgeInsets.all(_s(12)),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: color.withValues(alpha: 0.2)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: _s(16), color: color),
                SizedBox(width: _s(6)),
                Text(
                  label,
                  style: TextStyle(
                    fontSize: _s(11),
                    color: theme.textTheme.bodySmall?.color,
                  ),
                ),
              ],
            ),
            SizedBox(height: _s(6)),
            Text(
              value,
              style: TextStyle(
                fontSize: _s(15),
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
            if (sub.isNotEmpty)
              Text(
                sub,
                style: TextStyle(
                  fontSize: _s(10),
                  color: theme.textTheme.bodySmall?.color,
                ),
              ),
          ],
        ),
      );
    }

    // Subtle full-width underline beneath each row
    final rowDivider = BorderSide(
      color: theme.dividerColor.withValues(alpha: 0.25),
      width: 0.7,
    );

    Widget karatChips(List items) {
      if (items.isEmpty) {
        return Text(
          isArabic ? 'لا يوجد' : 'None',
          style: TextStyle(
            fontSize: _s(11),
            color: theme.textTheme.bodySmall?.color,
          ),
        );
      }
      return Column(
        children: items.map((k) {
          final karat = k['karat'] as String? ?? '?';
          final weight = _asDouble(k['weight']);
          final value = _asDouble(k['value']);
          return Container(
            decoration: BoxDecoration(
              border: Border(bottom: rowDivider),
            ),
            padding: EdgeInsets.symmetric(vertical: _s(5)),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Container(
                  padding: EdgeInsets.symmetric(
                    horizontal: _s(7),
                    vertical: _s(2),
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.primaryGold.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    karat,
                    style: TextStyle(
                      fontSize: _s(11),
                      color: AppColors.primaryGold,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
                SizedBox(width: _s(6)),
                Expanded(
                  child: Text(
                    '${_weightFormat.format(weight)} ${isArabic ? "جم" : "g"}',
                    style: TextStyle(
                      fontSize: _s(10),
                      color: theme.textTheme.bodySmall?.color,
                    ),
                  ),
                ),
                Text(
                  _currencyFormat.format(value),
                  style: TextStyle(
                    fontSize: _s(12),
                    fontWeight: FontWeight.w700,
                    color: AppColors.primaryGold,
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      );
    }

    Widget userRows(List items, Color accentColor) {
      if (items.isEmpty) {
        return Text(
          isArabic ? 'لا يوجد' : 'None',
          style: TextStyle(
            fontSize: _s(11),
            color: theme.textTheme.bodySmall?.color,
          ),
        );
      }
      final maxValue = items.take(5).fold<double>(
        0,
        (m, u) => (u is Map ? _asDouble(u['value']) : 0.0) > m
            ? _asDouble(u['value'])
            : m,
      );
      final isDark = theme.brightness == Brightness.dark;
      return Column(
        children: items.take(5).toList().asMap().entries.map((entry) {
          final rank = entry.key + 1;
          final u = entry.value;
          final user = u['user'] as String? ?? '—';
          final value = _asDouble(u['value']);
          final weight = _asDouble(u['weight']);
          final docs = u['docs'] as int? ?? 0;
          final pct = maxValue > 0 ? (value / maxValue).clamp(0.0, 1.0) : 0.0;

          // Medal color for top 3
          final Color rankColor;
          switch (rank) {
            case 1:
              rankColor = AppColors.primaryGold;
              break;
            case 2:
              rankColor = Colors.blueGrey.shade300;
              break;
            case 3:
              rankColor = Colors.brown.shade300;
              break;
            default:
              rankColor = theme.hintColor;
          }

          return Container(
            margin: EdgeInsets.only(bottom: _s(6)),
            padding: EdgeInsets.all(_s(8)),
            decoration: BoxDecoration(
              color: isDark
                  ? accentColor.withValues(alpha: 0.06)
                  : accentColor.withValues(alpha: 0.04),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: accentColor.withValues(alpha: 0.12),
              ),
            ),
            child: Column(
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    // Rank badge
                    Container(
                      width: _s(22),
                      height: _s(22),
                      decoration: BoxDecoration(
                        color: rankColor.withValues(alpha: 0.15),
                        shape: BoxShape.circle,
                        border: Border.all(
                            color: rankColor.withValues(alpha: 0.4), width: 1),
                      ),
                      child: Center(
                        child: Text(
                          '$rank',
                          style: TextStyle(
                            fontSize: _s(10),
                            fontWeight: FontWeight.bold,
                            color: rankColor,
                          ),
                        ),
                      ),
                    ),
                    SizedBox(width: _s(6)),
                    Expanded(
                      child: Text(
                        user,
                        style: TextStyle(
                          fontSize: _s(11),
                          fontWeight: FontWeight.w600,
                        ),
                        overflow: TextOverflow.ellipsis,
                        maxLines: 1,
                      ),
                    ),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          _currencyFormat.format(value),
                          style: TextStyle(
                            fontSize: _s(12),
                            fontWeight: FontWeight.w700,
                            color: accentColor,
                          ),
                        ),
                        Text(
                          '${_weightFormat.format(weight)}${isArabic ? "جم" : "g"} · $docs ${isArabic ? "فاتورة" : "inv"}',
                          style: TextStyle(
                            fontSize: _s(9),
                            color: theme.textTheme.bodySmall?.color,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
                SizedBox(height: _s(5)),
                // Performance bar
                ClipRRect(
                  borderRadius: BorderRadius.circular(_s(3)),
                  child: LinearProgressIndicator(
                    value: pct,
                    minHeight: _s(4),
                    backgroundColor: accentColor.withValues(alpha: 0.12),
                    valueColor: AlwaysStoppedAnimation<Color>(
                      rank == 1
                          ? AppColors.primaryGold
                          : accentColor,
                    ),
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      );
    }

    Widget expenseRows(List items) {
      if (items.isEmpty) {
        return Text(
          isArabic ? 'لا يوجد' : 'None',
          style: TextStyle(
            fontSize: _s(11),
            color: theme.textTheme.bodySmall?.color,
          ),
        );
      }
      return Column(
        children: items.take(6).map((e) {
          final acc = e['account'] as String? ?? '—';
          final value = _asDouble(e['value']);
          return Container(
            decoration: BoxDecoration(
              border: Border(bottom: rowDivider),
            ),
            padding: EdgeInsets.symmetric(vertical: _s(5)),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Icon(Icons.receipt_long_outlined,
                    size: _s(13), color: Colors.orange),
                SizedBox(width: _s(4)),
                Expanded(
                  child: Text(
                    acc,
                    style: TextStyle(fontSize: _s(11)),
                    overflow: TextOverflow.ellipsis,
                    maxLines: 1,
                  ),
                ),
                Text(
                  _currencyFormat.format(value),
                  style: TextStyle(
                    fontSize: _s(12),
                    color: Colors.orange,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      );
    }

    return Container(
      padding: EdgeInsets.all(_s(16)),
      decoration: BoxDecoration(
        color: theme.cardColor,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: AppColors.primaryGold.withValues(alpha: 0.08),
            blurRadius: 8,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header row
          Row(
            children: [
              Icon(Icons.bar_chart_rounded,
                  size: _s(20), color: AppColors.primaryGold),
              SizedBox(width: _s(8)),
              Expanded(
                child: Text(
                  isArabic
                      ? 'ملخص المبيعات والمشتريات والمصروفات'
                      : 'Sales, Purchases & Expenses Summary',
                  style: TextStyle(
                    fontSize: _s(14),
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
          SizedBox(height: _s(14)),

          // Metric tiles row
          LayoutBuilder(
            builder: (ctx, constraints) {
              final w = constraints.maxWidth;
              if (w >= 700) {
                return Row(
                  children: [
                    Expanded(
                      child: metricTile(
                        isArabic ? 'إجمالي المبيعات' : 'Total Sales',
                        _currencyFormat.format(salesValue),
                        '${_weightFormat.format(salesWeight)} ${isArabic ? "جم" : "g"} · $salesDocs ${isArabic ? "فاتورة" : "inv"}',
                        Icons.trending_up,
                        Colors.green,
                      ),
                    ),
                    SizedBox(width: _s(10)),
                    Expanded(
                      child: metricTile(
                        isArabic ? 'مشتريات الموردين' : 'Supplier Purchases',
                        _currencyFormat.format(purchasesValue),
                        '${_weightFormat.format(purchasesWeight)} ${isArabic ? "جم" : "g"} · $purchasesDocs ${isArabic ? "فاتورة" : "inv"}',
                        Icons.trending_down,
                        Colors.blue,
                      ),
                    ),
                    SizedBox(width: _s(10)),
                    Expanded(
                      child: metricTile(
                        isArabic ? 'إجمالي المصروفات' : 'Total Expenses',
                        _currencyFormat.format(expensesValue),
                        '',
                        Icons.receipt_long_outlined,
                        Colors.orange,
                      ),
                    ),
                  ],
                );
              } else {
                return Column(
                  children: [
                    metricTile(
                      isArabic ? 'إجمالي المبيعات' : 'Total Sales',
                      _currencyFormat.format(salesValue),
                      '${_weightFormat.format(salesWeight)} ${isArabic ? "جم" : "g"} · $salesDocs ${isArabic ? "فاتورة" : "inv"}',
                      Icons.trending_up,
                      Colors.green,
                    ),
                    SizedBox(height: _s(8)),
                    metricTile(
                      isArabic ? 'مشتريات الموردين' : 'Supplier Purchases',
                      _currencyFormat.format(purchasesValue),
                      '${_weightFormat.format(purchasesWeight)} ${isArabic ? "جم" : "g"} · $purchasesDocs ${isArabic ? "فاتورة" : "inv"}',
                      Icons.trending_down,
                      Colors.blue,
                    ),
                    SizedBox(height: _s(8)),
                    metricTile(
                      isArabic ? 'إجمالي المصروفات' : 'Total Expenses',
                      _currencyFormat.format(expensesValue),
                      '',
                      Icons.receipt_long_outlined,
                      Colors.orange,
                    ),
                  ],
                );
              }
            },
          ),
          SizedBox(height: _s(10)),

          // ── بطاقة مشتريات الكسر والتسكير ─────────────────────────────
          Container(
            padding: EdgeInsets.all(_s(12)),
            decoration: BoxDecoration(
              color: scrapColor.withValues(alpha: 0.07),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: scrapColor.withValues(alpha: 0.25)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.recycling_rounded, size: _s(16), color: scrapColor),
                    SizedBox(width: _s(6)),
                    Text(
                      isArabic ? 'مشتريات الكسر والتسكير' : 'Scrap & Settlement Purchases',
                      style: TextStyle(
                        fontSize: _s(12),
                        fontWeight: FontWeight.bold,
                        color: scrapColor,
                      ),
                    ),
                    const Spacer(),
                    Container(
                      padding: EdgeInsets.symmetric(horizontal: _s(7), vertical: _s(2)),
                      decoration: BoxDecoration(
                        color: scrapColor.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        '$scrapDocs ${isArabic ? "فاتورة" : "inv"}',
                        style: TextStyle(fontSize: _s(10), color: scrapColor, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
                ),
                SizedBox(height: _s(10)),
                LayoutBuilder(
                  builder: (ctx, bc) {
                    final wide = bc.maxWidth >= 500;
                    final chips = [
                      _ScrapChip(
                        label: isArabic ? 'إجمالي المبلغ' : 'Total Value',
                        value: _currencyFormat.format(scrapValue),
                        unit: isArabic ? 'ر.س' : 'SAR',
                        icon: Icons.payments_outlined,
                        color: scrapColor,
                        scale: _s(1),
                      ),
                      _ScrapChip(
                        label: isArabic ? 'الوزن المشترى' : 'Weight Bought',
                        value: _weightFormat.format(scrapWeight),
                        unit: isArabic ? 'جم' : 'g',
                        icon: Icons.scale_outlined,
                        color: scrapColor,
                        scale: _s(1),
                      ),
                      _ScrapChip(
                        label: isArabic ? 'المعدل الحالي' : 'Current Avg Rate',
                        value: _currencyFormat.format(scrapAvgRate),
                        unit: isArabic ? 'ر.س/جم' : 'SAR/g',
                        icon: Icons.show_chart_rounded,
                        color: scrapColor,
                        scale: _s(1),
                      ),
                      _ScrapChip(
                        label: isArabic ? 'قاعدة المعدل (كلي)' : 'Avg Base (total)',
                        value: _weightFormat.format(scrapCumWeight),
                        unit: isArabic ? 'جم · منذ البداية' : 'g · all time',
                        icon: Icons.inventory_2_outlined,
                        color: scrapColor,
                        scale: _s(1),
                      ),
                    ];
                    if (wide) {
                      return Row(
                        children: chips
                            .map((c) => Expanded(child: c))
                            .toList()
                            .fold<List<Widget>>([], (list, w) =>
                              list.isEmpty ? [w] : [...list, SizedBox(width: _s(8)), w]),
                      );
                    } else {
                      return Column(
                        children: [
                          Row(children: [Expanded(child: chips[0]), SizedBox(width: _s(8)), Expanded(child: chips[1])]),
                          SizedBox(height: _s(8)),
                          Row(children: [Expanded(child: chips[2]), SizedBox(width: _s(8)), Expanded(child: chips[3])]),
                        ],
                      );
                    }
                  },
                ),
              ],
            ),
          ),
          SizedBox(height: _s(16)),

          // Karat breakdown
          _SummarySection(
            title: isArabic ? 'توزيع المبيعات بالعيار (وزن + قيمة)' : 'Sales by Karat (weight + value)',
            scale: _s(1),
            child: karatChips(byKaratSales),
          ),
          SizedBox(height: _s(10)),
          _SummarySection(
            title: isArabic ? 'توزيع مشتريات الموردين بالعيار (وزن + قيمة)' : 'Supplier Purchases by Karat',
            scale: _s(1),
            child: karatChips(byKaratPurchases),
          ),
          SizedBox(height: _s(10)),

          // By user
          _SummarySection(
            title: isArabic ? 'أداء الموظفين — المبيعات' : 'Staff Performance — Sales',
            scale: _s(1),
            child: userRows(byUserSales, Colors.green),
          ),
          SizedBox(height: _s(10)),
          _SummarySection(
            title: isArabic ? 'أداء الموظفين — المشتريات' : 'Staff Performance — Purchases',
            scale: _s(1),
            child: userRows(byUserPurchases, Colors.blue),
          ),
          SizedBox(height: _s(10)),

          // Expenses by account
          _SummarySection(
            title: isArabic ? 'المصروفات بالحساب' : 'Expenses by Account',
            scale: _s(1),
            child: expenseRows(expByAccount),
          ),
        ],
      ),
    );
  }

  Widget _buildKpiGrid({
    required Map<String, dynamic> kpis,
    required Map<String, dynamic> series,
    required Map<String, dynamic> goldByKarat,
    required Map<String, dynamic> liquidity,
  }) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        int crossAxisCount;
        double ratio;

        if (width >= 1200) {
          crossAxisCount = 3;
          ratio = 1.55;
        } else if (width >= 900) {
          crossAxisCount = 3;
          ratio = 1.45;
        } else if (width >= 600) {
          crossAxisCount = 2;
          ratio = 1.35;
        } else {
          crossAxisCount = 1;
          ratio = 1.25;
        }

        return GridView.count(
          crossAxisCount: crossAxisCount,
          childAspectRatio: ratio,
          mainAxisSpacing: _s(12),
          crossAxisSpacing: _s(12),
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          children: [
            _buildSalesVsPurchasesCard(kpis, series),
            _buildKaratDistributionCard(goldByKarat),
            _buildLiquidityBreakdownCard(liquidity),
          ],
        );
      },
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

  Widget _buildSafeBoxReconciliationCard() {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    if (_safeBoxRecon == null && _safeBoxReconError == null) {
      return const SizedBox.shrink();
    }

    if (_safeBoxReconError != null) {
      return Container(
        padding: EdgeInsets.all(_s(12)),
        decoration: BoxDecoration(
          color: theme.cardColor,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.orange.shade200),
        ),
        child: Row(
          children: [
            Icon(Icons.warning_amber_rounded, color: Colors.orange, size: _s(20)),
            SizedBox(width: _s(8)),
            Expanded(
              child: Text(
                isArabic
                    ? 'تعذّر تحميل مطابقة الخزن مع دفتر الأستاذ'
                    : 'Failed to load SafeBox reconciliation',
                style: theme.textTheme.bodyMedium,
              ),
            ),
          ],
        ),
      );
    }

    final data = _safeBoxRecon ?? <String, dynamic>{};
    final mismatchCount = _asInt(data['mismatch_count']);
    final threshold = _asDouble(data['threshold']);
    final summary = (data['summary'] as List?) ?? const [];

    final mismatches = <Map<String, dynamic>>[];
    for (final row in summary) {
      if (row is! Map) continue;
      final r = row.cast<String, dynamic>();
      final diff = _asDouble(r['diff']);
      if (diff.abs() > threshold) {
        mismatches.add(r);
      }
    }
    mismatches.sort((a, b) {
      final ad = _asDouble(a['abs_diff']);
      final bd = _asDouble(b['abs_diff']);
      return bd.compareTo(ad);
    });
    final top = mismatches.take(3).toList();

    final ok = mismatchCount <= 0;
    final headerColor = ok ? Colors.green.shade700 : Colors.red.shade700;
    final borderColor = ok ? Colors.green.shade200 : Colors.red.shade200;

    return Container(
      padding: EdgeInsets.all(_s(12)),
      decoration: BoxDecoration(
        color: theme.cardColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.account_balance, color: headerColor, size: _s(20)),
              SizedBox(width: _s(8)),
              Expanded(
                child: Text(
                  isArabic
                      ? 'مطابقة الخزن مع دفتر الأستاذ (GL)'
                      : 'SafeBox vs GL Reconciliation',
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: headerColor,
                  ),
                ),
              ),
              TextButton(
                onPressed: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => SafeBoxesScreen(
                        api: widget.api,
                        isArabic: widget.isArabic,
                        balancesView: true,
                        initialFilterType: 'cash',
                        lockFilterType: true,
                        titleOverride: isArabic ? 'خزن النقد - مطابقة' : 'Cash Safes - Reconcile',
                      ),
                    ),
                  );
                },
                child: Text(isArabic ? 'عرض الخزن' : 'Open safes'),
              ),
            ],
          ),
          SizedBox(height: _s(8)),
          Row(
            children: [
              Icon(
                ok ? Icons.check_circle : Icons.error,
                color: ok ? Colors.green : Colors.red,
                size: _s(18),
              ),
              SizedBox(width: _s(8)),
              Expanded(
                child: Text(
                  ok
                      ? (isArabic
                          ? 'كل خزن النقد مطابقة مع القيود'
                          : 'All cash safes match the ledger')
                      : (isArabic
                          ? 'يوجد $mismatchCount خزنة غير مطابقة'
                          : '$mismatchCount safes mismatched'),
                  style: theme.textTheme.bodyMedium,
                ),
              ),
            ],
          ),
          if (!ok && top.isNotEmpty) ...[
            SizedBox(height: _s(8)),
            ...top.map((r) {
              final name = (r['safe_box_name'] ?? '').toString();
              final diff = _asDouble(r['diff']);
              return Padding(
                padding: EdgeInsets.only(top: _s(4)),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        name.isEmpty
                            ? (isArabic ? 'خزنة' : 'Safe')
                            : name,
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                    Text(
                      _formatCurrency(diff),
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: diff >= 0 ? Colors.green : Colors.red,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
        ],
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

  Widget _buildFloatingAlerts() {
    final toasts = _getAllAlerts();
    if (toasts.isEmpty) return const SizedBox.shrink();

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: toasts.map((alert) => _buildToastCard(alert)).toList(),
    );
  }

  Widget _buildToastCard(_AlertItem alert) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    final isArabic = widget.isArabic;

    return TweenAnimationBuilder<Offset>(
      key: Key('toast_${alert.text.hashCode}'),
      tween: Tween(
        begin: Offset(isArabic ? -1.2 : 1.2, 0.0),
        end: Offset.zero,
      ),
      duration: const Duration(milliseconds: 380),
      curve: Curves.easeOutCubic,
      builder: (context, offset, child) => FractionalTranslation(
        translation: offset,
        child: child,
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
          child: Container(
            width: 300,
            margin: const EdgeInsets.only(bottom: 8),
            decoration: BoxDecoration(
              color: isDark
                  ? const Color(0xFF2A2A2A).withValues(alpha: 0.88)
                  : Colors.white.withValues(alpha: 0.82),
              borderRadius: BorderRadius.circular(12),
              border: Border(
                // Accent line on the END side (right in LTR, left in RTL)
                right: isArabic
                    ? BorderSide(color: alert.color, width: 4)
                    : BorderSide(color: alert.color.withValues(alpha: 0.2), width: 0.8),
                left: isArabic
                    ? BorderSide(color: alert.color.withValues(alpha: 0.2), width: 0.8)
                    : BorderSide(color: alert.color, width: 4),
                top: BorderSide(
                  color: alert.color.withValues(alpha: 0.20),
                  width: 0.8,
                ),
                bottom: BorderSide(
                  color: alert.color.withValues(alpha: 0.20),
                  width: 0.8,
                ),
              ),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: isDark ? 0.40 : 0.14),
                  blurRadius: 20,
                  spreadRadius: 0,
                  offset: const Offset(0, 6),
                ),
                BoxShadow(
                  color: alert.color.withValues(alpha: 0.10),
                  blurRadius: 12,
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
                            ? Colors.white.withValues(alpha: 0.88)
                            : const Color(0xFF1C1C1E),
                        fontSize: 12.5,
                        fontWeight: FontWeight.w500,
                        height: 1.4,
                      ),
                    ),
                  ),
                ),
                GestureDetector(
                  onTap: () =>
                      setState(() => _dismissedAlertKeys.add(alert.text)),
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
        ),
      ),
    );
  }

  Widget _buildTrendPill({
    required double? value,
    required Color positiveColor,
    required Color negativeColor,
    required String label,
  }) {
    final theme = Theme.of(context);
    final hasValue = value != null;
    final isUp = hasValue ? (value >= 0) : true;
    final color = hasValue
        ? (isUp ? positiveColor : negativeColor)
        : Colors.blueGrey;
    final icon = hasValue
        ? (isUp ? Icons.trending_up : Icons.trending_down)
        : Icons.remove;

    return Container(
      padding: EdgeInsets.symmetric(horizontal: _s(8), vertical: _s(3)),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(_s(999)),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: _s(14), color: color),
          SizedBox(width: _s(4)),
          Text(
            hasValue ? '${value.abs().toStringAsFixed(1)}% $label' : '— $label',
            style: theme.textTheme.bodySmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: color,
              fontSize: _s(10.5),
            ),
          ),
        ],
      ),
    );
  }

  List<double> _seriesFromRows(dynamic rows, {required String field}) {
    if (rows is! List) return const [];
    final out = <double>[];
    for (final r in rows) {
      if (r is Map) {
        final v = r[field];
        if (v is num) out.add(v.toDouble());
      }
    }
    return out;
  }

  // ══════════════════════════════════════════════════════════════════════════
  // 3. CORE KPI CARDS
  // ══════════════════════════════════════════════════════════════════════════

  // Sales vs Purchases Sparkline Card
  Widget _buildSalesVsPurchasesCard(
    Map<String, dynamic> kpis,
    Map<String, dynamic> series,
  ) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final salesToday = (kpis['sales_today'] as Map<String, dynamic>?) ?? {};
    final purchasesToday =
        (kpis['purchases_today'] as Map<String, dynamic>?) ?? {};
    final salesWeight = _asDouble(salesToday['net_weight']);
    final purchasesWeight = _asDouble(purchasesToday['net_weight']);

    final salesTrendPct = _asDoubleOrNull(
      salesToday['change_pct_weight'] ?? salesToday['change_pct'],
    );
    final purchasesTrendPct = _asDoubleOrNull(
      purchasesToday['change_pct_weight'] ?? purchasesToday['change_pct'],
    );

    final netFlow = salesWeight - purchasesWeight;

    var salesSeries = _extractSeries(series, const [
      'sales',
      'sales_series',
      'sales_weights',
      'sales_values',
    ]);
    var purchasesSeries = _extractSeries(series, const [
      'purchases',
      'purchases_series',
      'purchases_weights',
      'purchases_values',
    ]);

    // Backend canonical shape: series.last_7_days_sales/purchases is a list of rows
    if (salesSeries.isEmpty) {
      salesSeries = _seriesFromRows(
        series['last_7_days_sales'],
        field: 'net_weight',
      );
    }
    if (purchasesSeries.isEmpty) {
      purchasesSeries = _seriesFromRows(
        series['last_7_days_purchases'],
        field: 'net_weight',
      );
    }

    return _buildKpiCardWrapper(
      onTap: () {
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => SalesVsPurchasesTrendReportScreen(
              api: widget.api,
              isArabic: widget.isArabic,
            ),
          ),
        );
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.swap_vert_circle_outlined,
                  color: AppColors.primaryGold, size: _s(20)),
              SizedBox(width: _s(6)),
              Expanded(
                child: Text(
                  isArabic ? 'حركة الذهب اليوم' : 'Gold Movement Today',
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    fontSize: _s(12),
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          SizedBox(height: _s(12)),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.arrow_downward,
                          size: _s(12), color: Colors.red.shade600),
                      SizedBox(width: _s(2)),
                      Text(
                        isArabic ? 'خرج (مبيعات)' : 'OUT (Sales)',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: Colors.red.shade600,
                          fontSize: _s(11),
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  Text(
                    _formatWeight(salesWeight),
                    style: TextStyle(
                      color: Colors.red.shade600,
                      fontWeight: FontWeight.bold,
                      fontSize: _s(14),
                    ),
                  ),
                  SizedBox(height: _s(4)),
                  _buildTrendPill(
                    value: salesTrendPct,
                    positiveColor: Colors.red,
                    negativeColor: Colors.green,
                    label: isArabic ? 'عن أمس' : 'vs yesterday',
                  ),
                ],
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Row(
                    children: [
                      Icon(Icons.arrow_upward,
                          size: _s(12), color: Colors.green.shade600),
                      SizedBox(width: _s(2)),
                      Text(
                        isArabic ? 'دخل (مشتريات)' : 'IN (Purch.)',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: Colors.green.shade600,
                          fontSize: _s(11),
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  Text(
                    _formatWeight(purchasesWeight),
                    style: TextStyle(
                      color: Colors.green.shade600,
                      fontWeight: FontWeight.bold,
                      fontSize: _s(14),
                    ),
                  ),
                  SizedBox(height: _s(4)),
                  _buildTrendPill(
                    value: purchasesTrendPct,
                    positiveColor: Colors.green,
                    negativeColor: Colors.red,
                    label: isArabic ? 'عن أمس' : 'vs yesterday',
                  ),
                ],
              ),
            ],
          ),
          SizedBox(height: _s(8)),
          Container(
            padding: EdgeInsets.symmetric(horizontal: _s(8), vertical: _s(4)),
            decoration: BoxDecoration(
              color: (netFlow >= 0 ? Colors.green : Colors.red).withValues(
                alpha: 0.1,
              ),
              borderRadius: BorderRadius.circular(_s(6)),
              border: Border.all(
                color: (netFlow >= 0 ? Colors.green : Colors.red)
                    .withValues(alpha: 0.25),
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  netFlow >= 0 ? Icons.trending_up : Icons.trending_down,
                  size: _s(14),
                  color: netFlow >= 0 ? Colors.green.shade600 : Colors.red.shade600,
                ),
                SizedBox(width: _s(4)),
                Text(
                  '${isArabic ? "صافي الحركة: " : "Net: "}${netFlow >= 0 ? "+" : "-"}${_formatWeight(netFlow.abs())}',
                  style: TextStyle(
                    fontSize: _s(11),
                    fontWeight: FontWeight.bold,
                    color: netFlow >= 0
                        ? Colors.green.shade600
                        : Colors.red.shade600,
                  ),
                ),
              ],
            ),
          ),
          SizedBox(height: _s(10)),
          Expanded(
            child: _buildSalesVsPurchasesSparkline(
              salesSeries: salesSeries,
              purchasesSeries: purchasesSeries,
            ),
          ),
        ],
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

  Widget _buildSalesVsPurchasesSparkline({
    required List<double> salesSeries,
    required List<double> purchasesSeries,
  }) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    if (salesSeries.isEmpty && purchasesSeries.isEmpty) {
      return Container(
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceVariant.withValues(alpha: 0.4),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          isArabic ? 'لا توجد بيانات للرسم' : 'No chart data',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.hintColor,
            fontSize: _s(11),
          ),
        ),
      );
    }

    final maxLength = salesSeries.length > purchasesSeries.length
        ? salesSeries.length
        : purchasesSeries.length;
    final spotsSales = _toSpots(salesSeries, maxLength);
    final spotsPurchases = _toSpots(purchasesSeries, maxLength);

    final values = [...salesSeries, ...purchasesSeries];
    final minY = values.isEmpty ? 0.0 : values.reduce((a, b) => a < b ? a : b);
    final maxY = values.isEmpty ? 1.0 : values.reduce((a, b) => a > b ? a : b);
    final padding = (maxY - minY).abs() * 0.2;

    return ClipRRect(
      borderRadius: BorderRadius.circular(_s(8)),
      child: LineChart(
        LineChartData(
          gridData: const FlGridData(show: false),
          titlesData: const FlTitlesData(show: false),
          borderData: FlBorderData(show: false),
          lineTouchData: const LineTouchData(enabled: false),
          minX: 0,
          maxX: maxLength > 0 ? (maxLength - 1).toDouble() : 1,
          minY: minY - padding,
          maxY: maxY + padding,
          lineBarsData: [
            if (spotsSales.isNotEmpty)
              LineChartBarData(
                spots: spotsSales,
                isCurved: true,
                color: Colors.red.shade500,
                barWidth: _s(2),
                dotData: const FlDotData(show: false),
                belowBarData: BarAreaData(
                  show: true,
                  color: Colors.red.withValues(alpha: 0.10),
                ),
              ),
            if (spotsPurchases.isNotEmpty)
              LineChartBarData(
                spots: spotsPurchases,
                isCurved: true,
                color: Colors.green.shade600,
                barWidth: _s(2),
                dotData: const FlDotData(show: false),
                belowBarData: BarAreaData(
                  show: true,
                  color: Colors.green.withValues(alpha: 0.10),
                ),
              ),
          ],
        ),
      ),
    );
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

  // Karat Distribution Donut Card
  Widget _buildKaratDistributionCard(Map<String, dynamic> goldByKarat) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final k18 = _asDouble(goldByKarat['18k']);
    final k21 = _asDouble(goldByKarat['21k']);
    final k22 = _asDouble(goldByKarat['22k']);
    final k24 = _asDouble(goldByKarat['24k']);
    final total = k18 + k21 + k22 + k24;

    return _buildKpiCardWrapper(
      onTap: () {
        // Navigate to inventory
      },
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.pie_chart, color: AppColors.primaryGold, size: _s(20)),
              SizedBox(width: _s(6)),
              Text(
                isArabic ? 'توزيع العيارات' : 'Karat Mix',
                style: theme.textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontSize: _s(12),
                ),
              ),
            ],
          ),
          SizedBox(height: _s(12)),
          if (total == 0)
            Center(
              child: Text(
                isArabic ? 'لا يوجد ذهب' : 'No gold',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.hintColor,
                ),
              ),
            )
          else
            Row(
              children: [
                // Mini Donut Chart
                SizedBox(
                  width: _s(70),
                  height: _s(70),
                  child: PieChart(
                    PieChartData(
                      sectionsSpace: 1,
                      centerSpaceRadius: _s(18),
                      sections: [
                        PieChartSectionData(
                          value: k24,
                          color: AppColors.primaryGold,
                          radius: _s(15),
                          showTitle: false,
                        ),
                        PieChartSectionData(
                          value: k22,
                          color: Colors.amber.shade600,
                          radius: _s(15),
                          showTitle: false,
                        ),
                        PieChartSectionData(
                          value: k21,
                          color: Colors.orange.shade600,
                          radius: _s(15),
                          showTitle: false,
                        ),
                        PieChartSectionData(
                          value: k18,
                          color: Colors.deepOrange.shade400,
                          radius: _s(15),
                          showTitle: false,
                        ),
                      ],
                    ),
                  ),
                ),
                SizedBox(width: _s(10)),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _buildKaratLegendItem(
                        label: '24K',
                        value: k24,
                        color: AppColors.primaryGold,
                        total: total,
                      ),
                      _buildKaratLegendItem(
                        label: '22K',
                        value: k22,
                        color: Colors.amber.shade600,
                        total: total,
                      ),
                      _buildKaratLegendItem(
                        label: '21K',
                        value: k21,
                        color: Colors.orange.shade600,
                        total: total,
                      ),
                      _buildKaratLegendItem(
                        label: '18K',
                        value: k18,
                        color: Colors.deepOrange.shade400,
                        total: total,
                      ),
                    ],
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _buildKaratLegendItem({
    required String label,
    required double value,
    required Color color,
    required double total,
  }) {
    final pct = total > 0 ? (value / total * 100).toStringAsFixed(0) : '0';
    return Padding(
      padding: EdgeInsets.only(bottom: _s(2)),
      child: Row(
        children: [
          Container(
            width: _s(9),
            height: _s(9),
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          SizedBox(width: _s(6)),
          Expanded(
            child: Text(
              '$label: ${_formatWeight(value)} • $pct%',
              style: TextStyle(fontSize: _s(11)),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }

  // Liquidity Breakdown Card
  Widget _buildLiquidityBreakdownCard(Map<String, dynamic> liquidity) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final cashInHand = _asDouble(liquidity['cash_in_hand']);
    final cashInBanks = _asDouble(liquidity['cash_in_banks']);
    final receivables = _asDouble(liquidity['receivables']);
    final total = cashInHand + cashInBanks + receivables;

    return _buildKpiCardWrapper(
      onTap: () {},
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.water_drop, color: Colors.blue, size: _s(20)),
              SizedBox(width: _s(6)),
              Text(
                isArabic ? 'مركز السيولة' : 'Liquidity',
                style: theme.textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontSize: _s(12),
                ),
              ),
            ],
          ),
          SizedBox(height: _s(12)),
          _buildLiquidityRow(
            isArabic ? 'نقدية' : 'Cash',
            cashInHand,
            Colors.green,
            total,
          ),
          SizedBox(height: _s(4)),
          _buildLiquidityRow(
            isArabic ? 'بنوك' : 'Banks',
            cashInBanks,
            Colors.blue,
            total,
          ),
          SizedBox(height: _s(4)),
          _buildLiquidityRow(
            isArabic ? 'ذمم' : 'Receiv.',
            receivables,
            Colors.orange,
            total,
          ),
        ],
      ),
    );
  }

  Widget _buildLiquidityRow(
    String label,
    double value,
    Color color,
    double total,
  ) {
    final pct = total > 0 ? value / total : 0.0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: TextStyle(fontSize: _s(11))),
            Text(
              _formatCurrency(value),
              style: TextStyle(fontSize: _s(11), fontWeight: FontWeight.bold),
            ),
          ],
        ),
        SizedBox(height: _s(2)),
        ClipRRect(
          borderRadius: BorderRadius.circular(_s(2)),
          child: LinearProgressIndicator(
            value: pct,
            minHeight: _s(4),
            backgroundColor: color.withValues(alpha: 0.15),
            valueColor: AlwaysStoppedAnimation<Color>(color),
          ),
        ),
      ],
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // HERO PROFIT SECTION (always shows TODAY, range-independent)
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildHeroProfitSection(
    Map<String, dynamic> kpis,
    Map<String, dynamic> liquidity,
  ) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final todayProfit = _asDouble(kpis['today_profit']);
    final marginValue = _asDoubleOrNull(kpis['today_profit_margin_pct']);
    final vsYesterdayPct = _asDoubleOrNull(kpis['today_profit_vs_yesterday_pct']);
    final salesChangePct = _asDoubleOrNull(
        (kpis['sales_today'] as Map?)?['change_pct'],
    );

    final salesToday = _asDouble((kpis['sales_today'] as Map?)?['net_value']);
    final purchasesToday = _asDouble((kpis['purchases_today'] as Map?)?['net_value']);
    final cashAvailable = _asDouble(liquidity['cash_available']);

    final isProfit = todayProfit >= 0;
    final profitColor = isProfit ? AppColors.success : Colors.red.shade600;

    // Build smart insight text
    String insightText = '';
    if (vsYesterdayPct != null) {
      final direction = vsYesterdayPct >= 0
          ? (isArabic ? 'ارتفع' : 'Up')
          : (isArabic ? 'انخفض' : 'Down');
      insightText = isArabic
          ? 'الربح $direction ${vsYesterdayPct.abs().toStringAsFixed(1)}% مقارنة بالأمس'
          : 'Profit $direction ${vsYesterdayPct.abs().toStringAsFixed(1)}% vs yesterday';
    } else if (salesChangePct != null && salesChangePct.abs() > 0) {
      final dirSales = salesChangePct >= 0
          ? (isArabic ? 'ارتفعت' : 'up')
          : (isArabic ? 'انخفضت' : 'down');
      insightText = isArabic
          ? 'المبيعات $dirSales ${salesChangePct.abs().toStringAsFixed(1)}% مقارنة بالأمس'
          : 'Sales $dirSales ${salesChangePct.abs().toStringAsFixed(1)}% vs yesterday';
    } else if (isProfit) {
      insightText = isArabic ? 'النتيجة: ربح ✓' : 'Result: Profit ✓';
    } else {
      insightText = isArabic ? 'المصروف أعلى من المبيعات اليوم' : 'Expenses exceed sales today';
    }

    return Padding(
      padding: EdgeInsets.fromLTRB(_s(16), _s(8), _s(16), 0),
      child: Container(
        padding: EdgeInsets.all(_s(20)),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topRight,
            end: Alignment.bottomLeft,
            colors: isProfit
                ? [
                    AppColors.success.withValues(alpha: 0.10),
                    theme.cardColor,
                  ]
                : [
                    Colors.red.shade600.withValues(alpha: 0.08),
                    theme.cardColor,
                  ],
          ),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
            color: profitColor.withValues(alpha: 0.25),
            width: 1.5,
          ),
          boxShadow: [
            BoxShadow(
              color: profitColor.withValues(alpha: 0.08),
              blurRadius: 16,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Title row + vs-yesterday badge
            Row(
              children: [
                Icon(
                  isProfit ? Icons.trending_up : Icons.trending_down,
                  color: profitColor,
                  size: _s(20),
                ),
                SizedBox(width: _s(6)),
                Text(
                  isArabic ? 'صافي الربح اليوم' : "Today's Net Profit",
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: theme.textTheme.bodySmall?.color,
                  ),
                ),
                const Spacer(),
                if (vsYesterdayPct != null)
                  Container(
                    padding: EdgeInsets.symmetric(
                      horizontal: _s(8),
                      vertical: _s(3),
                    ),
                    decoration: BoxDecoration(
                      color: (vsYesterdayPct >= 0 ? Colors.green : Colors.red)
                          .withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          vsYesterdayPct >= 0
                              ? Icons.arrow_upward
                              : Icons.arrow_downward,
                          size: _s(12),
                          color: vsYesterdayPct >= 0
                              ? Colors.green.shade700
                              : Colors.red.shade600,
                        ),
                        SizedBox(width: _s(2)),
                        Text(
                          '${vsYesterdayPct.abs().toStringAsFixed(1)}%',
                          style: TextStyle(
                            fontSize: _s(11),
                            fontWeight: FontWeight.bold,
                            color: vsYesterdayPct >= 0
                                ? Colors.green.shade700
                                : Colors.red.shade600,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
            SizedBox(height: _s(10)),

            // The hero number
            Text(
              _formatCurrency(todayProfit),
              style: theme.textTheme.displaySmall?.copyWith(
                fontWeight: FontWeight.w900,
                color: profitColor,
                fontSize: _s(30),
                letterSpacing: -0.5,
              ),
            ),

            // Margin badge
            if (marginValue != null) ...[
              SizedBox(height: _s(4)),
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
                  '${marginValue.toStringAsFixed(1)}% ${isArabic ? "هامش ربح" : "margin"}',
                  style: TextStyle(
                    fontSize: _s(11),
                    fontWeight: FontWeight.bold,
                    color: profitColor,
                  ),
                ),
              ),
            ],

            SizedBox(height: _s(10)),
            // Smart insight
            if (insightText.isNotEmpty)
              Row(
                children: [
                  Icon(
                    Icons.lightbulb_outline,
                    size: _s(13),
                    color: theme.hintColor,
                  ),
                  SizedBox(width: _s(4)),
                  Text(
                    insightText,
                    style: theme.textTheme.bodySmall?.copyWith(
                      fontSize: _s(11),
                      color: theme.hintColor,
                    ),
                  ),
                ],
              ),

            SizedBox(height: _s(14)),
            // Quick chips row
            Wrap(
              spacing: _s(8),
              runSpacing: _s(6),
              children: [
                _heroChip(
                  icon: Icons.account_balance_wallet_outlined,
                  label: isArabic ? 'السيولة' : 'Cash',
                  value: _formatCurrency(cashAvailable),
                  color: AppColors.primaryGold,
                ),
                _heroChip(
                  icon: Icons.arrow_upward,
                  label: isArabic ? 'مبيعات' : 'Sales',
                  value: _formatCurrency(salesToday),
                  color: const Color(0xFF1B9E4B),
                ),
                _heroChip(
                  icon: Icons.arrow_downward,
                  label: isArabic ? 'مشتريات' : 'Purch.',
                  value: _formatCurrency(purchasesToday),
                  color: Colors.orange.shade700,
                ),
              ],
            ),
          ],
        ),
      ),
    );
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

  // Today's Profit Card (kept for potential future reuse)
  // ignore: unused_element
  Widget _buildTodayProfitCard(Map<String, dynamic> kpis) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final todayProfit = _asDouble(kpis['today_profit']);
    final profitMargin = kpis['today_profit_margin_pct'];
    final marginValue = profitMargin is num ? profitMargin.toDouble() : null;

    final isPositive = todayProfit >= 0;

    return _buildKpiCardWrapper(
      onTap: () {},
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.trending_up,
                color: isPositive ? Colors.green : Colors.red,
                size: _s(20),
              ),
              SizedBox(width: _s(6)),
              Text(
                isArabic ? 'هامش الربح اليوم' : 'Today Profit',
                style: theme.textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  fontSize: _s(12),
                ),
              ),
            ],
          ),
          SizedBox(height: _s(12)),
          Text(
            _formatCurrency(todayProfit),
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.bold,
              color: isPositive ? Colors.green : Colors.red,
              fontSize: _s(20),
            ),
          ),
          if (marginValue != null)
            Container(
              margin: EdgeInsets.only(top: _s(4)),
              padding: EdgeInsets.symmetric(horizontal: _s(6), vertical: _s(2)),
              decoration: BoxDecoration(
                color: (isPositive ? Colors.green : Colors.red).withValues(
                  alpha: 0.1,
                ),
                borderRadius: BorderRadius.circular(_s(4)),
              ),
              child: Text(
                '${marginValue.toStringAsFixed(1)}% ${isArabic ? "هامش" : "margin"}',
                style: TextStyle(
                  fontSize: _s(11),
                  fontWeight: FontWeight.bold,
                  color: isPositive ? Colors.green : Colors.red,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildKpiCardWrapper({required Widget child, VoidCallback? onTap}) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: EdgeInsets.all(_s(12)),
        decoration: BoxDecoration(
          color: isDark ? theme.cardColor : Colors.white,
          borderRadius: BorderRadius.circular(16),
          border: isDark
              ? Border.all(
                  color: AppColors.primaryGold.withValues(alpha: 0.22),
                  width: 1,
                )
              : Border.all(
                  color: AppColors.primaryGold.withValues(alpha: 0.45),
                  width: 1.2,
                ),
          boxShadow: isDark
              ? [
                  BoxShadow(
                    color: AppColors.primaryGold.withValues(alpha: 0.09),
                    blurRadius: 16,
                    offset: const Offset(0, 0),
                  ),
                ]
              : [
                  BoxShadow(
                    color: AppColors.primaryGold.withValues(alpha: 0.15),
                    blurRadius: 14,
                    offset: const Offset(0, 4),
                  ),
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.04),
                    blurRadius: 6,
                    offset: const Offset(0, 2),
                  ),
                ],
        ),
        child: child,
      ),
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // 4. VAULTS & CUSTODY (Horizontal List)
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildVaultsSection(List<dynamic> safeBoxes) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    if (safeBoxes.isEmpty) return const SizedBox.shrink();

    final anyExpanded = _expandedVaultSafeBoxId != null;
    // Give cards enough vertical room to avoid RenderFlex overflow.
    final listHeight = anyExpanded ? _s(260) : _s(168);
    final sorted = _sortedVaults(safeBoxes);

    Widget buildCard(int index, Map<String, dynamic> sb, {bool reorderMode = false}) {
      final id = sb['id'];
      final sbId = id is int ? id : int.tryParse(id?.toString() ?? '');
      final heroTag = sbId != null ? 'vault_safe_box_$sbId' : 'vault_safe_box_$index';
      final isExpanded = (sbId != null && sbId == _expandedVaultSafeBoxId);
      final isPressed = (sbId != null && sbId == _pressedVaultSafeBoxId);

      return _buildVaultCard(
        sb,
        heroTag: heroTag,
        isExpanded: isExpanded,
        isPressed: isPressed,
        reorderMode: reorderMode,
        onTap: () {
          if (sbId == null) return;
          setState(() {
            _expandedVaultSafeBoxId = isExpanded ? null : sbId;
          });
        },
        onOpenDetails: () {
          if (sbId != null) {
            setState(() => _recentVaultIds.add(sbId));
          }
          Navigator.of(context).push(
            MaterialPageRoute(
              builder: (_) => _SafeBoxHeroDetailsScreen(
                api: widget.api,
                isArabic: widget.isArabic,
                safeBox: sb,
                heroTag: heroTag,
              ),
            ),
          );
        },
        onPressChanged: (pressed) {
          if (sbId == null) return;
          setState(() {
            if (pressed) {
              _pressedVaultSafeBoxId = sbId;
            } else if (_pressedVaultSafeBoxId == sbId) {
              _pressedVaultSafeBoxId = null;
            }
          });
        },
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: EdgeInsets.symmetric(horizontal: _s(16)),
          child: Row(
            children: [
              Icon(
                Icons.inventory_2,
                color: theme.colorScheme.primary,
                size: _s(22),
              ),
              SizedBox(width: _s(8)),
              Text(
                isArabic ? 'توزيع العهد والخزائن' : 'Vaults & Custody',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
              ),
              const Spacer(),
              // Reorder toggle
              Tooltip(
                message: _isReorderingVaults
                    ? (isArabic ? 'تم الترتيب' : 'Done')
                    : (isArabic ? 'إعادة ترتيب' : 'Reorder'),
                child: IconButton(
                  icon: Icon(
                    _isReorderingVaults ? Icons.check_circle_outline : Icons.swap_horiz,
                    size: _s(20),
                    color: _isReorderingVaults
                        ? theme.colorScheme.primary
                        : theme.hintColor,
                  ),
                  onPressed: () => setState(() => _isReorderingVaults = !_isReorderingVaults),
                ),
              ),
              TextButton(
                onPressed: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => SafeBoxesScreen(
                        api: widget.api,
                        isArabic: widget.isArabic,
                        balancesView: true,
                      ),
                    ),
                  );
                },
                child: Text(isArabic ? 'عرض الكل' : 'View all'),
              ),
            ],
          ),
        ),
        SizedBox(height: _s(12)),
        SizedBox(
          height: listHeight,
          child: Listener(
            onPointerSignal: (event) {
              if (event is PointerScrollEvent) {
                final offset = (_vaultScrollController.offset +
                    event.scrollDelta.dy * 1.5)
                    .clamp(0.0,
                        _vaultScrollController.position.maxScrollExtent);
                _vaultScrollController.jumpTo(offset);
              }
            },
            child: _isReorderingVaults
                ? ReorderableListView.builder(
                    scrollDirection: Axis.horizontal,
                    scrollController: _vaultScrollController,
                    padding: EdgeInsets.symmetric(horizontal: _s(16)),
                    itemCount: sorted.length,
                    onReorder: (oldIndex, newIndex) {
                      setState(() {
                        if (newIndex > oldIndex) newIndex--;
                        final item = sorted.removeAt(oldIndex);
                        sorted.insert(newIndex, item);
                        // Rebuild _vaultOrder from reordered list
                        _vaultOrder = sorted
                            .map((sb) {
                              final id = sb['id'];
                              return id is int
                                  ? id
                                  : int.tryParse(id?.toString() ?? '');
                            })
                            .whereType<int>()
                            .toList();
                      });
                      _saveVaultOrder();
                    },
                    itemBuilder: (context, index) {
                      final sb = sorted[index];
                      final id = sb['id'];
                      final sbId = id is int ? id : int.tryParse(id?.toString() ?? '');
                      return KeyedSubtree(
                        key: ValueKey(sbId ?? index),
                        child: buildCard(index, sb, reorderMode: true),
                      );
                    },
                  )
                : AnimationLimiter(
                    child: ListView.builder(
                      scrollDirection: Axis.horizontal,
                      controller: _vaultScrollController,
                      padding: EdgeInsets.symmetric(horizontal: _s(16)),
                      itemCount: sorted.length,
                      itemBuilder: (context, index) {
                        final sb = sorted[index];
                        return AnimationConfiguration.staggeredList(
                          position: index,
                          duration: const Duration(milliseconds: 420),
                          child: SlideAnimation(
                            verticalOffset: 18.0,
                            child: FadeInAnimation(
                              child: buildCard(index, sb),
                            ),
                          ),
                        );
                      },
                    ),
                  ),
          ),
        ),
      ],
    );
  }

  double _sbWeight(Map<String, dynamic> sb, String key) {
    final wb = sb['weight_balance'];
    if (wb is Map) {
      final raw = wb[key];
      if (raw is num) return raw.toDouble();
      return double.tryParse(raw?.toString() ?? '') ?? 0.0;
    }
    return 0.0;
  }

  Widget _buildVaultCard(
    Map<String, dynamic> sb, {
    required String heroTag,
    required bool isExpanded,
    required bool isPressed,
    required VoidCallback onTap,
    required VoidCallback onOpenDetails,
    required ValueChanged<bool> onPressChanged,
    bool reorderMode = false,
  }) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final name = sb['name'] ?? '-';
    final safeType = sb['safe_type'] ?? 'cash';
    final cashBalance = _asDouble(sb['balance_cash']);
    final goldBalance = _asDouble(sb['balance_gold_21k']);
    final hasActivity = sb['has_recent_activity'] == true;

    final w18 = _sbWeight(sb, '18k');
    final w21 = _sbWeight(sb, '21k');
    final w22 = _sbWeight(sb, '22k');
    final w24 = _sbWeight(sb, '24k');
    final totalMain = _asDouble(sb['total_weight_main_karat']);
    final hasWeightBreakdown = sb['weight_balance'] is Map;
    final mainKaratFromApi = _asInt(sb['main_karat']);
    final displayMainKarat = mainKaratFromApi > 0 ? mainKaratFromApi : 21;

    double totalMainFallback() {
      final mk = displayMainKarat <= 0 ? 21.0 : displayMainKarat.toDouble();
      return (w18 * (18.0 / mk)) + w21 + (w22 * (22.0 / mk)) + (w24 * (24.0 / mk));
    }

    final totalMainEffective = (totalMain > 0)
        ? totalMain
        : (hasWeightBreakdown ? totalMainFallback() : 0.0);

    final physicalTotal = hasWeightBreakdown ? (w18 + w21 + w22 + w24) : 0.0;

    IconData icon;
    Color color;
    String subtitle;
    double primaryValue;
    String Function(double) primaryFormatter;
    String? primaryCaption;

    switch (safeType) {
      case 'gold':
        icon = Icons.auto_awesome;
        color = AppColors.primaryGold;
        // Collapsed: show main-karat equivalent (dynamic main karat).
        // Expanded: show physical total across all karats.
        primaryValue = isExpanded ? physicalTotal : totalMainEffective;
        primaryFormatter = _formatWeight;
        subtitle = isArabic ? 'ذهب' : 'Gold';
        primaryCaption = isExpanded
            ? (isArabic
                ? 'إجمالي فعلي (جميع العيارات)'
                : 'Physical total (all karats)')
            : (isArabic
                ? 'مكافئ العيار الرئيسي (${displayMainKarat}k)'
                : 'Main karat equivalent (${displayMainKarat}k)');
        break;
      case 'bank':
        icon = Icons.account_balance;
        color = Colors.blue;
        primaryValue = cashBalance;
        primaryFormatter = _formatCurrency;
        subtitle = isArabic ? 'بنك' : 'Bank';
        break;
      default:
        icon = Icons.account_balance_wallet;
        color = Colors.green;
        primaryValue = cashBalance;
        primaryFormatter = _formatCurrency;
        subtitle = isArabic ? 'نقد' : 'Cash';
    }

    final cardWidth = isExpanded ? _s(290) : _s(172);

    Widget buildDetailChip(String label, String value, {Color? chipColor}) {
      final c = chipColor ?? color;
      return Container(
        padding: EdgeInsets.symmetric(horizontal: _s(8), vertical: _s(5)),
        decoration: BoxDecoration(
          color: c.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(_s(10)),
          border: Border.all(color: c.withValues(alpha: 0.28)),
        ),
        child: Text(
          '$label: $value',
          style: theme.textTheme.bodySmall?.copyWith(
            fontSize: _s(11),
            fontWeight: FontWeight.w600,
            color: theme.brightness == Brightness.dark
                ? Colors.white
                : Colors.black87,
          ),
        ),
      );
    }

    final details = safeType == 'gold'
        ? (hasWeightBreakdown
            ? Wrap(
                spacing: _s(8),
                runSpacing: _s(8),
                children: [
                  buildDetailChip('24k', _formatWeight(w24), chipColor: AppColors.karat24),
                  buildDetailChip('22k', _formatWeight(w22), chipColor: AppColors.karat22),
                  buildDetailChip('21k', _formatWeight(w21), chipColor: AppColors.karat21),
                  buildDetailChip('18k', _formatWeight(w18), chipColor: AppColors.karat18),
                ],
              )
            : Wrap(
                spacing: _s(8),
                runSpacing: _s(8),
                children: [
                  buildDetailChip('21k', _formatWeight(goldBalance), chipColor: AppColors.karat21),
                  buildDetailChip(
                    isArabic ? 'ملاحظة' : 'Note',
                    isArabic
                        ? 'تفصيل العيارات غير متوفر بعد'
                        : 'Karat breakdown not available yet',
                    chipColor: theme.hintColor,
                  ),
                ],
              ))
        : Wrap(
            spacing: _s(8),
            runSpacing: _s(8),
            children: [
              buildDetailChip(
                isArabic ? 'الرصيد' : 'Balance',
                _formatCurrency(cashBalance),
                chipColor: color,
              ),
            ],
          );

    final borderAccent = hasActivity ? Colors.green : theme.hintColor;
    final borderColor = borderAccent.withValues(alpha: hasActivity ? 0.55 : 0.25);
    final glowColor = (hasActivity ? Colors.green : color).withValues(
      alpha: isPressed ? 0.22 : (isExpanded ? 0.14 : 0.10),
    );
    final glassBase = theme.colorScheme.surface.withValues(
      alpha: theme.brightness == Brightness.dark ? 0.25 : 0.78,
    );

    final heroIconTag = '${heroTag}_icon';
    final heroNameTag = '${heroTag}_name';

    final cardBody = Material(
      color: Colors.transparent,
      child: ClipRRect(
        borderRadius: BorderRadius.circular(14),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
          child: InkWell(
            borderRadius: BorderRadius.circular(14),
            onTapDown: (_) => onPressChanged(true),
            onTapCancel: () => onPressChanged(false),
            onTap: () {
              onPressChanged(false);
              onTap();
            },
            child: AnimatedScale(
              duration: const Duration(milliseconds: 140),
              curve: Curves.easeOut,
              scale: isPressed ? 0.985 : 1.0,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 260),
                curve: Curves.easeOutCubic,
                width: cardWidth,
                padding: EdgeInsets.all(_s(12)),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: borderColor,
                    width: isPressed ? 1.2 : 1.0,
                  ),
                  gradient: LinearGradient(
                    begin: AlignmentDirectional.topStart,
                    end: AlignmentDirectional.bottomEnd,
                    colors: [
                      glassBase.withValues(alpha: 0.88),
                      glassBase.withValues(alpha: 0.72),
                    ],
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: glowColor,
                      blurRadius: isPressed ? 18 : (isExpanded ? 16 : 12),
                      offset: const Offset(0, 8),
                    ),
                  ],
                ),
                child: Stack(
                  children: [
                    PositionedDirectional(
                      start: 0,
                      top: 0,
                      bottom: 0,
                      child: Container(
                        width: _s(4),
                        decoration: BoxDecoration(
                          color: color.withValues(
                            alpha: hasActivity ? 0.85 : 0.55,
                          ),
                          borderRadius: BorderRadiusDirectional.horizontal(
                            start: Radius.circular(_s(14)),
                          ),
                        ),
                      ),
                    ),
                    Padding(
                      padding: EdgeInsetsDirectional.only(start: _s(6)),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Hero(
                                tag: heroIconTag,
                                createRectTween: (begin, end) =>
                                    MaterialRectArcTween(begin: begin, end: end),
                                child: Material(
                                  color: Colors.transparent,
                                  child: Icon(
                                    icon,
                                    color: color,
                                    size: _s(20),
                                  ),
                                ),
                              ),
                              SizedBox(width: _s(6)),
                              if (hasActivity)
                                Container(
                                  width: _s(9),
                                  height: _s(9),
                                  decoration: const BoxDecoration(
                                    color: Colors.green,
                                    shape: BoxShape.circle,
                                  ),
                                ),
                              const Spacer(),
                              InkResponse(
                                onTap: () {
                                  onPressChanged(false);
                                  onOpenDetails();
                                },
                                radius: _s(18),
                                child: Icon(
                                  Icons.open_in_new,
                                  color: theme.hintColor,
                                  size: _s(18),
                                ),
                              ),
                              SizedBox(width: _s(6)),
                              AnimatedRotation(
                                turns: isExpanded ? 0.5 : 0.0,
                                duration: const Duration(milliseconds: 220),
                                curve: Curves.easeOutCubic,
                                child: Icon(
                                  Icons.expand_more,
                                  color: theme.hintColor,
                                  size: _s(18),
                                ),
                              ),
                            ],
                          ),
                          SizedBox(height: _s(8)),
                          Hero(
                            tag: heroNameTag,
                            createRectTween: (begin, end) =>
                                MaterialRectArcTween(begin: begin, end: end),
                            child: Material(
                              color: Colors.transparent,
                              child: Tooltip(
                                message: name.toString(),
                                child: Text(
                                  name,
                                  style: theme.textTheme.bodySmall?.copyWith(
                                    fontWeight: FontWeight.w700,
                                    fontSize: _s(12.5),
                                  ),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            ),
                          ),
                          SizedBox(height: _s(2)),
                          Text(
                            subtitle,
                            style: theme.textTheme.bodySmall?.copyWith(
                              fontSize: _s(11),
                              color: theme.hintColor,
                            ),
                          ),
                          if (!isExpanded) const Spacer(),
                          SizedBox(height: _s(10)),
                          if (primaryCaption != null) ...[
                            Text(
                              primaryCaption,
                              style: theme.textTheme.bodySmall?.copyWith(
                                fontSize: _s(10.5),
                                color: theme.hintColor,
                                fontWeight: FontWeight.w600,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            SizedBox(height: _s(6)),
                          ],
                          _AnimatedValueText(
                            value: primaryValue,
                            formatter: primaryFormatter,
                            style: theme.textTheme.bodyMedium?.copyWith(
                              fontWeight: FontWeight.bold,
                              color: color,
                              fontSize: _s(14),
                            ),
                          ),
                          AnimatedCrossFade(
                            firstChild: const SizedBox.shrink(),
                            secondChild: Padding(
                              padding: EdgeInsets.only(top: _s(12)),
                              child: details,
                            ),
                            crossFadeState: isExpanded
                                ? CrossFadeState.showSecond
                                : CrossFadeState.showFirst,
                            duration: const Duration(milliseconds: 240),
                            firstCurve: Curves.easeOut,
                            secondCurve: Curves.easeOutCubic,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );

    return Container(
      margin: EdgeInsetsDirectional.only(start: _s(12)),
      child: cardBody,
    );
  }

  // ══════════════════════════════════════════════════════════════════════════
  // 5. SENSITIVE OPERATIONS FEED
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildSensitiveOperationsSection(List<dynamic> operations) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final hasData = operations.isNotEmpty;

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
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
              ),
              const Spacer(),
              TextButton(
                onPressed: () {
                  Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AuditLogScreen()),
                  );
                },
                child: Text(isArabic ? 'السجل' : 'Log'),
              ),
            ],
          ),
        ),
        SizedBox(height: _s(8)),
        if (!hasData)
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
                Icon(
                  Icons.shield_outlined,
                  color: Colors.purple.shade300,
                  size: _s(22),
                ),
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
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const AuditLogScreen()),
                    );
                  },
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
              onTap: () {
                Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const AuditLogScreen()),
                );
              },
              borderRadius: BorderRadius.circular(8),
              child: Container(
                margin: EdgeInsets.symmetric(
                  horizontal: _s(16),
                  vertical: _s(4),
                ),
                padding: EdgeInsets.all(_s(10)),
                decoration: BoxDecoration(
                  color: Colors.purple.withValues(alpha: 0.05),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: Colors.purple.withValues(alpha: 0.1),
                  ),
                ),
                child: Row(
                  children: [
                    Icon(
                      Icons.security,
                      color: Colors.purple.shade300,
                      size: _s(18),
                    ),
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
                    Icon(
                      Icons.chevron_left,
                      size: _s(20),
                      color: theme.hintColor,
                    ),
                  ],
                ),
              ),
            );
          }),
      ],
    );
  }
}

/// Collapsible section header used inside the summary card.
class _SummarySection extends StatefulWidget {
  final String title;
  final Widget child;
  final double scale;

  const _SummarySection({
    required this.title,
    required this.child,
    required this.scale,
  });

  @override
  State<_SummarySection> createState() => _SummarySectionState();
}

class _SummarySectionState extends State<_SummarySection> {
  bool _expanded = true;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: () => setState(() => _expanded = !_expanded),
          borderRadius: BorderRadius.circular(6),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(
              children: [
                Icon(
                  _expanded
                      ? Icons.keyboard_arrow_down
                      : Icons.keyboard_arrow_left,
                  size: 16 * widget.scale,
                  color: AppColors.primaryGold,
                ),
                const SizedBox(width: 4),
                Text(
                  widget.title,
                  style: TextStyle(
                    fontSize: 12 * widget.scale,
                    fontWeight: FontWeight.w600,
                    color: theme.textTheme.bodySmall?.color,
                  ),
                ),
              ],
            ),
          ),
        ),
        if (_expanded) ...[
          const SizedBox(height: 6),
          widget.child,
        ],
      ],
    );
  }
}

class _AlertItem {
  final IconData icon;
  final Color color;
  final String text;

  _AlertItem({required this.icon, required this.color, required this.text});
}

/// Small metric chip used in the scrap purchases card.
class _ScrapChip extends StatelessWidget {
  final String label;
  final String value;
  final String unit;
  final IconData icon;
  final Color color;
  final double scale;

  const _ScrapChip({
    required this.label,
    required this.value,
    required this.unit,
    required this.icon,
    required this.color,
    required this.scale,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: EdgeInsets.symmetric(horizontal: 8 * scale, vertical: 7 * scale),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.18)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 12 * scale, color: color),
              SizedBox(width: 4 * scale),
              Expanded(
                child: Text(
                  label,
                  style: TextStyle(
                    fontSize: 9 * scale,
                    color: theme.textTheme.bodySmall?.color,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          SizedBox(height: 4 * scale),
          Text(
            value,
            style: TextStyle(
              fontSize: 13 * scale,
              fontWeight: FontWeight.bold,
              color: color,
            ),
          ),
          Text(
            unit,
            style: TextStyle(
              fontSize: 9 * scale,
              color: theme.textTheme.bodySmall?.color,
            ),
          ),
        ],
      ),
    );
  }
}

class _SafeBoxHeroDetailsScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;
  final Map<String, dynamic> safeBox;
  final String heroTag;

  const _SafeBoxHeroDetailsScreen({
    required this.api,
    required this.isArabic,
    required this.safeBox,
    required this.heroTag,
  });

  @override
  State<_SafeBoxHeroDetailsScreen> createState() =>
      _SafeBoxHeroDetailsScreenState();
}

class _SafeBoxHeroDetailsScreenState extends State<_SafeBoxHeroDetailsScreen> {
  late Map<String, dynamic> _safeBox;
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _safeBox = Map<String, dynamic>.from(widget.safeBox);
    // Fetch the latest balances immediately on open.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _refresh();
    });
  }

  double _uiScale(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    if (width >= 1200) return 1.20;
    if (width >= 900) return 1.12;
    if (width >= 600) return 1.04;
    return 1.0;
  }

  double _s(BuildContext context, double value) => value * _uiScale(context);

  double _asDouble(dynamic v) {
    if (v is num) return v.toDouble();
    return double.tryParse(v?.toString() ?? '') ?? 0.0;
  }

  double _sbWeight(Map<String, dynamic> sb, String key) {
    final wb = sb['weight_balance'];
    if (wb is Map) {
      final raw = wb[key];
      if (raw is num) return raw.toDouble();
      return double.tryParse(raw?.toString() ?? '') ?? 0.0;
    }
    return 0.0;
  }

  int? _safeBoxIdFromMap(Map<String, dynamic> sb) {
    final id = sb['id'];
    if (id is int) return id;
    return int.tryParse(id?.toString() ?? '');
  }

  Map<String, dynamic> _mergeFromSafeBoxModel(SafeBoxModel m) {
    final wb = m.weightBalance;
    return <String, dynamic>{
      'id': m.id,
      'name': m.name,
      'safe_type': m.safeType,
      'weight_balance': wb,
      'total_weight_main_karat': m.totalWeightMainKarat,
      'balance_cash': m.cashBalance,
      // Keep the dashboard convention.
      'balance_gold_21k': wb?['21k'] ?? 0.0,
      // Best-effort: keep existing signal if present.
      'has_recent_activity': _safeBox['has_recent_activity'] == true,
      // Use safe's karat when available.
      'main_karat': m.karat,
    };
  }

  Future<void> _refresh() async {
    final id = _safeBoxIdFromMap(_safeBox);
    if (id == null) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final model = await widget.api.getSafeBox(id, includeBalance: true);
      if (!mounted) return;
      setState(() {
        _safeBox = {
          ..._safeBox,
          ..._mergeFromSafeBoxModel(model),
        };
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
      });
    } finally {
      if (!mounted) return;
      setState(() {
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final name = _safeBox['name'] ?? '-';
    final safeType = _safeBox['safe_type'] ?? 'cash';
    final cashBalance = _asDouble(_safeBox['balance_cash']);
    final hasActivity = _safeBox['has_recent_activity'] == true;

    final w18 = _sbWeight(_safeBox, '18k');
    final w21 = _sbWeight(_safeBox, '21k');
    final w22 = _sbWeight(_safeBox, '22k');
    final w24 = _sbWeight(_safeBox, '24k');

    IconData icon;
    Color color;
    String subtitle;

    switch (safeType) {
      case 'gold':
        icon = Icons.auto_awesome;
        color = AppColors.primaryGold;
        subtitle = widget.isArabic ? 'ذهب' : 'Gold';
        break;
      case 'bank':
        icon = Icons.account_balance;
        color = Colors.blue;
        subtitle = widget.isArabic ? 'بنك' : 'Bank';
        break;
      default:
        icon = Icons.account_balance_wallet;
        color = Colors.green;
        subtitle = widget.isArabic ? 'نقد' : 'Cash';
    }

    Widget buildDetailChip(String label, String value, {Color? chipColor}) {
      final c = chipColor ?? color;
      return Container(
        padding: EdgeInsets.symmetric(
          horizontal: _s(context, 10),
          vertical: _s(context, 6),
        ),
        decoration: BoxDecoration(
          color: c.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(_s(context, 12)),
          border: Border.all(color: c.withValues(alpha: 0.28)),
        ),
        child: Text(
          '$label: $value',
          style: theme.textTheme.bodySmall?.copyWith(
            fontWeight: FontWeight.w600,
            fontSize: _s(context, 12),
          ),
        ),
      );
    }

    final heroIconTag = '${widget.heroTag}_icon';
    final heroNameTag = '${widget.heroTag}_name';

    final headerCard = Material(
      color: Colors.transparent,
      child: Container(
        padding: EdgeInsets.all(_s(context, 14)),
        decoration: BoxDecoration(
          color: theme.cardColor,
          borderRadius: BorderRadius.circular(_s(context, 16)),
          border: Border.all(
            color: (hasActivity ? Colors.green : theme.hintColor)
                .withValues(alpha: 0.25),
          ),
          boxShadow: [
            BoxShadow(
              color: color.withValues(alpha: 0.10),
              blurRadius: 16,
              offset: const Offset(0, 10),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Hero(
                  tag: heroIconTag,
                  createRectTween: (begin, end) =>
                      MaterialRectArcTween(begin: begin, end: end),
                  child: Material(
                    color: Colors.transparent,
                    child: Icon(icon, color: color, size: _s(context, 26)),
                  ),
                ),
                SizedBox(width: _s(context, 10)),
                Expanded(
                  child: Hero(
                    tag: heroNameTag,
                    createRectTween: (begin, end) =>
                        MaterialRectArcTween(begin: begin, end: end),
                    child: Material(
                      color: Colors.transparent,
                      child: Text(
                        name,
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ),
                ),
                if (hasActivity)
                  Container(
                    width: _s(context, 9),
                    height: _s(context, 9),
                    decoration: const BoxDecoration(
                      color: Colors.green,
                      shape: BoxShape.circle,
                    ),
                  ),
              ],
            ),
            SizedBox(height: _s(context, 6)),
            Text(
              subtitle,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.hintColor,
              ),
            ),
          ],
        ),
      ),
    );

    final detailsContent = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_error != null)
          Padding(
            padding: EdgeInsets.only(top: _s(context, 12)),
            child: Text(
              _error!,
              style: theme.textTheme.bodySmall?.copyWith(color: Colors.red),
            ),
          ),
        SizedBox(height: _s(context, 16)),
        Card(
          elevation: 0,
          color: theme.cardColor,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(_s(context, 16)),
            side: BorderSide(color: theme.dividerColor.withValues(alpha: 0.5)),
          ),
          child: Padding(
            padding: EdgeInsets.all(_s(context, 14)),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      widget.isArabic ? 'أرصدة مباشرة' : 'Live balances',
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.bold),
                    ),
                    const Spacer(),
                    if (_loading)
                      SizedBox(
                        width: _s(context, 18),
                        height: _s(context, 18),
                        child: const CircularProgressIndicator(strokeWidth: 2),
                      ),
                  ],
                ),
                SizedBox(height: _s(context, 10)),
                if (safeType == 'gold')
                  Wrap(
                    spacing: _s(context, 10),
                    runSpacing: _s(context, 10),
                    children: [
                      buildDetailChip('24k', _weightFmt(w24), chipColor: AppColors.karat24),
                      buildDetailChip('22k', _weightFmt(w22), chipColor: AppColors.karat22),
                      buildDetailChip('21k', _weightFmt(w21), chipColor: AppColors.karat21),
                      buildDetailChip('18k', _weightFmt(w18), chipColor: AppColors.karat18),
                    ],
                  )
                else
                  Wrap(
                    spacing: _s(context, 10),
                    runSpacing: _s(context, 10),
                    children: [
                      buildDetailChip(
                        widget.isArabic ? 'الرصيد' : 'Balance',
                        _currencyFmt(cashBalance),
                        chipColor: color,
                      ),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ],
    );

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.isArabic ? 'تفاصيل الخزنة' : 'Safe Box Details'),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => SafeBoxesScreen(
                    api: widget.api,
                    isArabic: widget.isArabic,
                    balancesView: true,
                  ),
                ),
              );
            },
            child: Text(widget.isArabic ? 'عرض الكل' : 'View all'),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: EdgeInsets.all(_s(context, 16)),
          children: [
            headerCard,
            TweenAnimationBuilder<double>(
              tween: Tween<double>(begin: 0, end: 1),
              duration: const Duration(milliseconds: 260),
              curve: Curves.easeOutCubic,
              builder: (context, v, child) {
                return Opacity(
                  opacity: v,
                  child: Transform.translate(
                    offset: Offset(0, (1 - v) * 10),
                    child: child,
                  ),
                );
              },
              child: detailsContent,
            ),
          ],
        ),
      ),
    );
  }

  String _weightFmt(double v) {
    final f = NumberFormat('#,##0.000');
    return '${f.format(v)} g';
  }

  String _currencyFmt(double v) {
    final f = NumberFormat.currency(
      locale: widget.isArabic ? 'ar' : 'en',
      symbol: '',
      decimalDigits: 2,
    );
    final s = f.format(v).trim();
    return widget.isArabic ? '$s ر.س' : '$s SAR';
  }
}

class _AnimatedValueText extends StatefulWidget {
  final double value;
  final String Function(double) formatter;
  final TextStyle? style;

  const _AnimatedValueText({
    required this.value,
    required this.formatter,
    this.style,
  });

  @override
  State<_AnimatedValueText> createState() => _AnimatedValueTextState();
}

class _AnimatedValueTextState extends State<_AnimatedValueText> {
  late double _from;
  late double _to;

  @override
  void initState() {
    super.initState();
    _from = 0.0;
    _to = widget.value;
  }

  @override
  void didUpdateWidget(covariant _AnimatedValueText oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.value != widget.value) {
      _from = _to;
      _to = widget.value;
    }
  }

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween<double>(begin: _from, end: _to),
      duration: const Duration(milliseconds: 650),
      curve: Curves.easeOutCubic,
      builder: (context, v, _) {
        return Text(widget.formatter(v), style: widget.style);
      },
      onEnd: () {
        _from = _to;
      },
    );
  }
}
