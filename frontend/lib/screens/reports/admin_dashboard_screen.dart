import 'dart:ui' show ImageFilter;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_staggered_animations/flutter_staggered_animations.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../api_service.dart';
import '../../app_events.dart';
import '../../providers/settings_provider.dart';
import '../../utils/currency_utils.dart' as cu;
import '../../theme/app_theme.dart';
import '../audit_log_screen.dart';
import '../safe_boxes_screen.dart';
import 'gold_price_history_report_screen.dart';
import 'safe_box_hero_details_screen.dart';
import 'widgets/dashboard_summary_tabs_card.dart';
import '../../widgets/alerts_dialog.dart';

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

  int? _expandedVaultSafeBoxId;
  int? _pressedVaultSafeBoxId;

  _TimeRange _timeRange = _TimeRange.today;

  // ── Gram Profit KPI ─────────────────────────────────────────────────────
  Map<String, dynamic>? _gramProfitData;
  bool _gramProfitLoading = false;

  // ── Overlay alert state ──────────────────────────────────────────────────
  /// Alerts that the user has manually dismissed (by id/text key).
  final Set<String> _dismissedAlertKeys = {};
  /// Live OverlayEntry for the floating toast stack (null = not shown).
  OverlayEntry? _toastOverlayEntry;

  // ── Alert badge (pending approvals + system alerts) ──────────────────────
  int _alertsBadgeCount = 0;

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
  bool _currencyIsNewSar = false;
  int _currencyDecimals = 2;

  late NumberFormat _currencyFormat;
  late NumberFormat _weightFormat;

  @override
  void initState() {
    super.initState();
    _currencyFormat = NumberFormat(
      '#,##0${'.'}${'0' * _currencyDecimals}',
      widget.isArabic ? 'ar' : 'en',
    );
    _weightFormat = NumberFormat('#,##0.000');
    _loadVaultOrder();
    _loadData();
    _loadGramProfit();
    AppEvents.vaultRefreshSignal.addListener(_onVaultRefresh);
  }

  void _onVaultRefresh() {
    if (mounted) _loadData();
  }

  @override
  void dispose() {
    AppEvents.vaultRefreshSignal.removeListener(_onVaultRefresh);
    _toastOverlayEntry?.remove();
    _toastOverlayEntry = null;
    _vaultScrollController.dispose();
    super.dispose();
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
  void didChangeDependencies() {
    super.didChangeDependencies();
    final settings = Provider.of<SettingsProvider>(context);
    final symbol = settings.currencySymbolText;
    final isNewSar = settings.currencyIsNewSar;
    final decimals = settings.decimalPlaces;

    if (symbol != _currencySymbol ||
        isNewSar != _currencyIsNewSar ||
        decimals != _currencyDecimals) {
      setState(() {
        _currencySymbol = symbol;
        _currencyIsNewSar = isNewSar;
        _currencyDecimals = decimals;
        _currencyFormat = NumberFormat(
          '#,##0${'.'}${'0' * decimals}',
          widget.isArabic ? 'ar' : 'en',
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

      // Fallback: for any period where backend returns zeros, compute locally.
      final sps = (result['sales_purchases_summary'] as Map<String, dynamic>?) ?? {};
      final periodsNeedingFallback = ['today', 'month', 'year'].where((p) {
        final pd = (sps[p] as Map<String, dynamic>?) ?? {};
        return (_asDoubleSafe(pd['sales']?['total_value']) == 0.0) &&
               (_asDoubleSafe(pd['purchases']?['total_value']) == 0.0) &&
               ((pd['sales']?['docs'] ?? 0) == 0);
      }).toList();

      if (periodsNeedingFallback.isNotEmpty) {
        final computed = await _computeSummaryLocally(periodsNeedingFallback);
        if (computed != null) {
          final mergedSps = Map<String, dynamic>.from(sps);
          for (final p in periodsNeedingFallback) {
            if (computed[p] != null) mergedSps[p] = computed[p];
          }
          result['sales_purchases_summary'] = mergedSps;
        }
      }

      setState(() => _response = result);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
        _refreshAlertsBadge();
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _updateToastOverlay();
        });
      }
    }
  }

  static double _asDoubleSafe(dynamic v) => v is num ? v.toDouble() : 0.0;

  /// Computes sales_purchases_summary for the given periods by querying /api/invoices directly.
  Future<Map<String, dynamic>?> _computeSummaryLocally(List<String> periods) async {
    try {
      final now = DateTime.now();
      final todayStart = DateTime(now.year, now.month, now.day);
      final tomorrowStart = todayStart.add(const Duration(days: 1));
      final monthStart = DateTime(now.year, now.month, 1);
      final yearStart = DateTime(now.year, 1, 1);

      final periodBounds = {
        'today': (start: todayStart, end: tomorrowStart),
        'month': (start: monthStart, end: tomorrowStart),
        'year':  (start: yearStart,  end: tomorrowStart),
      };

      final saleTypes = {'بيع': 1, 'sell': 1, 'sale': 1, 'مرتجع بيع': -1};
      final purchaseTypes = {
        'شراء': 1, 'شراء من عميل': 1,
        'مرتجع شراء': -1, 'مرتجع شراء (مورد)': -1,
      };
      const scrapTypes = {'شراء': 1, 'شراء من عميل': 1, 'مرتجع شراء': -1};

      Map<String, dynamic> empty() => {
        'total_value': 0.0, 'total_weight': 0.0,
        'docs': 0, 'by_user': [], 'by_karat': [],
      };

      Future<Map<String, dynamic>> fetchSummary(
        Map<String, int> types, DateTime from, DateTime to, {String? goldType}) async {
        try {
          final resp = await widget.api.getInvoices(
            perPage: 1000,
            invoiceTypes: types.keys.toList(),
            dateFrom: from,
            dateTo: to,
            goldType: goldType,
          );
          final items = (resp['invoices'] ?? resp['items'] ?? resp) as List? ?? [];
          double totalValue = 0, totalWeight = 0;
          int docCount = 0;
          final Map<String, Map<String, double>> byUser = {};
          for (final inv in items) {
            if (inv['is_posted'] != true) continue;
            if (goldType != null && inv['gold_type'] != goldType) continue;
            final type = inv['invoice_type'] as String? ?? '';
            final sign = (types[type] ?? 1).toDouble();
            final val = _asDoubleSafe(inv['total']) * sign;
            final wt = _asDoubleSafe(inv['total_weight']) * sign;
            totalValue += val;
            totalWeight += wt;
            docCount++;
            final user = (inv['posted_by'] as String? ?? 'غير معروف').trim();
            byUser[user] ??= {'value': 0, 'weight': 0, 'docs': 0};
            byUser[user]!['value'] = (byUser[user]!['value']! + val);
            byUser[user]!['weight'] = (byUser[user]!['weight']! + wt);
            byUser[user]!['docs'] = (byUser[user]!['docs']! + 1);
          }
          final byUserList = byUser.entries
              .map((e) => {'user': e.key, 'value': e.value['value'], 'weight': e.value['weight'], 'docs': e.value['docs']?.toInt()})
              .toList()
            ..sort((a, b) => (_asDoubleSafe(b['value']) - _asDoubleSafe(a['value'])).sign.toInt());
          return {
            'total_value': double.parse(totalValue.toStringAsFixed(2)),
            'total_weight': double.parse(totalWeight.toStringAsFixed(3)),
            'docs': docCount,
            'by_user': byUserList,
            'by_karat': [],
          };
        } catch (_) {
          return empty();
        }
      }

      Map<String, dynamic> buildPeriod(Map<String, dynamic> sales,
          Map<String, dynamic> purchases, Map<String, dynamic> scrap) => {
        'sales': sales,
        'purchases': purchases,
        'expenses': {'total_value': 0.0, 'by_account': []},
        'scrap_purchases': {...scrap, 'avg_rate': 0.0, 'avg_gold': 0.0, 'cumulative_weight': 0.0},
      };

      // Only fetch for the periods that need it (avoid unnecessary API calls).
      final futures = <Future<Map<String, dynamic>>>[];
      for (final p in periods) {
        final bounds = periodBounds[p]!;
        futures.add(fetchSummary(saleTypes, bounds.start, bounds.end));
        futures.add(fetchSummary(purchaseTypes, bounds.start, bounds.end));
        futures.add(fetchSummary(scrapTypes, bounds.start, bounds.end, goldType: 'scrap'));
      }
      final results = await Future.wait(futures);

      final output = <String, dynamic>{};
      for (int i = 0; i < periods.length; i++) {
        output[periods[i]] = buildPeriod(results[i * 3], results[i * 3 + 1], results[i * 3 + 2]);
      }
      return output;
    } catch (e) {
      debugPrint('⚠️ _computeSummaryLocally failed: $e');
      return null;
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

  void _refreshAlertsBadge() {
    if (!mounted) return;
    final alerts = (_response?['alerts'] as Map<String, dynamic>?) ?? {};
    final criticalBar = (alerts['critical_bar'] as List?) ?? [];
    final criticalCount = alerts['critical_unreviewed_count'];
    final unpostedCount = alerts['unposted_invoices_count'];
    final lastShift = alerts['last_shift_closing'] as Map<String, dynamic>?;
    final cashDiff = lastShift?['cash_difference'];
    final goldDiff = lastShift?['gold_pure_24k_difference'];

    int count = criticalBar.length;
    if ((criticalCount is num ? criticalCount.toInt() : 0) > 0) count++;
    if ((cashDiff is num ? cashDiff.toDouble() : 0.0).abs() > 0.01) count++;
    if ((goldDiff is num ? goldDiff.toDouble() : 0.0).abs() > 0.001) count++;
    if ((unpostedCount is num ? unpostedCount.toInt() : 0) > 0) count++;

    setState(() => _alertsBadgeCount = count);
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

  double? _asDoubleOrNull(dynamic value) =>
      value is num ? value.toDouble() : null;

  int _asInt(dynamic value) =>
      value is int ? value : (value is num ? value.toInt() : 0);

  String _formatCurrency(num value) => '${_currencyFormat.format(value)} $_currencySymbol';
  String _formatWeight(num value) => '${_weightFormat.format(value)} جم';

  Widget _currencyAwareText(
    String text, {
    TextStyle? style,
    TextAlign textAlign = TextAlign.start,
    int? maxLines,
    TextOverflow? overflow,
  }) {
    return cu.SarAwareText(
      text,
      isNewSar: _currencyIsNewSar,
      style: style,
      textAlign: textAlign,
      maxLines: maxLines,
      overflow: overflow,
    );
  }

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
    final hintColor = Theme.of(context).hintColor;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.error_outline, size: _s(52), color: AppColors.error),
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
              style: TextStyle(color: hintColor, fontSize: _s(12)),
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

          // === 3. Time-range-dependent content ===
          SliverToBoxAdapter(
            child: Column(
              children: [
                // Gram Profit KPI + Cash Profit Card (side-by-side on wide, stacked on mobile)
                Padding(
                  padding: EdgeInsets.fromLTRB(_s(16), _s(8), _s(16), 0),
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final isWide = constraints.maxWidth >= 760;
                      final gramKpi = _buildGramProfitKpi();
                      final heroProfit = _buildHeroProfitSection(
                          kpis, liquidity, salesPurchasesSummary);
                      if (isWide) {
                        return IntrinsicHeight(
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Expanded(child: gramKpi),
                              SizedBox(width: _s(12)),
                              Expanded(child: heroProfit),
                            ],
                          ),
                        );
                      }
                      return Column(
                        children: [
                          gramKpi,
                          SizedBox(height: _s(12)),
                          heroProfit,
                        ],
                      );
                    },
                  ),
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
                    allPeriodsData: salesPurchasesSummary,
                    isArabic: widget.isArabic,
                    currencyFormat: _currencyFormat,
                    currencySymbol: _currencySymbol,
                    currencyIsNewSar: _currencyIsNewSar,
                    weightFormat: _weightFormat,
                    scale: _s,
                  ),
                ),
              ],
            ),
          ),

          // === 4. Vaults & Custody (Horizontal List) ===
          SliverToBoxAdapter(child: _buildVaultsSection(safeBoxes)),

          // === 5. Sensitive Operations Feed ===
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
              Stack(
                children: [
                  IconButton(
                    icon: Icon(Icons.notifications_outlined, size: _s(22)),
                    onPressed: () async {
                      await AlertsDialog.show(
                        context: context,
                        api: widget.api,
                        isArabic: widget.isArabic,
                        onCountChanged: () {
                          _loadData();
                          _refreshAlertsBadge();
                        },
                      );
                      _loadData();
                    },
                  ),
                  if (_alertsBadgeCount > 0)
                    Positioned(
                      right: 6,
                      top: 6,
                      child: Container(
                        width: 16,
                        height: 16,
                        decoration: const BoxDecoration(
                          color: Colors.red,
                          shape: BoxShape.circle,
                        ),
                        child: Center(
                          child: Text(
                            _alertsBadgeCount > 9 ? '9+' : '$_alertsBadgeCount',
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 9,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
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

  Widget _buildKpiGrid({
    required Map<String, dynamic> goldByKarat,
    required Map<String, dynamic> liquidity,
  }) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 700;
        if (isWide) {
          return Row(
            children: [
              Expanded(child: _buildKaratDistributionCard(goldByKarat)),
              SizedBox(width: _s(12)),
              Expanded(child: _buildLiquidityBreakdownCard(liquidity)),
            ],
          );
        }

        return Column(
          children: [
            _buildKaratDistributionCard(goldByKarat),
            SizedBox(height: _s(12)),
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
    final isPositive = netPosition >= 0;
    final accentColor = isPositive ? AppColors.primaryGold : AppColors.error;
    return Container(
      padding: EdgeInsets.all(_s(16)),
      decoration: BoxDecoration(
        color: theme.cardColor,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: accentColor.withValues(alpha: isDark ? 0.30 : 0.50),
          width: 1.2,
        ),
        boxShadow: [
          BoxShadow(
            color: accentColor.withValues(alpha: isDark ? 0.10 : 0.14),
            blurRadius: 16,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final isWide = constraints.maxWidth >= 500;

          return Row(
            children: [
              Container(
                width: _s(56),
                height: _s(56),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      accentColor.withValues(alpha: 0.20),
                      accentColor.withValues(alpha: 0.08),
                    ],
                  ),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(
                  isPositive ? Icons.account_balance : Icons.account_balance_outlined,
                  color: accentColor,
                  size: _s(28),
                ),
              ),
              SizedBox(width: _s(14)),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      isArabic ? 'صافي المركز المالي' : 'Net Position',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.hintColor,
                        fontSize: _s(12),
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    SizedBox(height: _s(6)),
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: AlignmentDirectional.centerStart,
                      child: _currencyAwareText(
                        _formatCurrency(netPosition),
                        style: theme.textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                          color: accentColor,
                          fontSize: _s(22),
                        ),
                      ),
                    ),
                    SizedBox(height: _s(2)),
                    Text(
                      isArabic ? 'نقد + قيمة الذهب' : 'Cash + Gold Value',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.hintColor,
                        fontSize: _s(11),
                      ),
                    ),
                  ],
                ),
              ),
              if (isWide && _response != null) ...[
                SizedBox(width: _s(16)),
                Container(
                  width: 1,
                  height: _s(60),
                  color: theme.dividerColor.withValues(alpha: 0.3),
                ),
                SizedBox(width: _s(16)),
                _buildSnapshotMiniStat(
                  theme: theme,
                  icon: Icons.water_drop_outlined,
                  label: isArabic ? 'السيولة' : 'Liquidity',
                  value: _formatCurrency(_asDouble(
                    (_response?['liquidity'] as Map?)?['cash_available'] ?? 0,
                  )),
                  color: AppColors.invoiceSaleScrap,
                ),
                SizedBox(width: _s(20)),
                _buildSnapshotMiniStat(
                  theme: theme,
                  icon: Icons.auto_awesome,
                  label: isArabic ? 'وزن الذهب' : 'Gold Weight',
                  value: _formatWeight(_asDouble(
                    (_response?['kpis'] as Map?)?['gold_equivalent_main_karat'] ?? 0,
                  )),
                  color: AppColors.primaryGold,
                ),
              ],
            ],
          );
        },
      ),
    );
  }

  Widget _buildSnapshotMiniStat({
    required ThemeData theme,
    required IconData icon,
    required String label,
    required String value,
    required Color color,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          children: [
            Icon(icon, size: _s(13), color: color),
            SizedBox(width: _s(4)),
            Text(
              label,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.hintColor,
                fontSize: _s(11),
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
        SizedBox(height: _s(4)),
        _currencyAwareText(
          value,
          style: TextStyle(
            fontSize: _s(14),
            fontWeight: FontWeight.bold,
            color: color,
          ),
        ),
      ],
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
            color: (isPositive ? AppColors.success : AppColors.error).withValues(
              alpha: theme.brightness == Brightness.dark ? 0.40 : 0.55,
            ),
            width: 1.2,
          ),
          boxShadow: [
            BoxShadow(
              color: (isPositive ? AppColors.success : AppColors.error).withValues(
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
                Container(
                  width: _s(36),
                  height: _s(36),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: (isPositive ? AppColors.success : AppColors.error)
                        .withValues(alpha: 0.12),
                  ),
                  child: Icon(
                    Icons.show_chart,
                    color: isPositive ? AppColors.success : AppColors.error,
                    size: _s(20),
                  ),
                ),
                SizedBox(width: _s(8)),
                Text(
                  '24K',
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const Spacer(),
                if (changeValue != null)
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isPositive
                            ? Icons.arrow_upward
                            : Icons.arrow_downward,
                        size: _s(13),
                        color: isPositive
                            ? AppColors.success
                            : AppColors.error,
                      ),
                      Text(
                        '${changeValue.abs().toStringAsFixed(1)}%',
                        style: TextStyle(
                          fontSize: _s(12),
                          fontWeight: FontWeight.bold,
                          color: isPositive
                              ? AppColors.success
                              : AppColors.error,
                        ),
                      ),
                    ],
                  ),
              ],
            ),
            SizedBox(height: _s(6)),
            _currencyAwareText(
              goldPrice > 0
                  ? '${goldPrice.toStringAsFixed(0)} $_currencySymbol'
                  : '-',
              style: theme.textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.bold,
                fontSize: _s(20),
              ),
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
                        color: isPositive ? AppColors.success : AppColors.error,
                        barWidth: _s(2),
                        dotData: const FlDotData(show: false),
                        belowBarData: BarAreaData(
                          show: true,
                          color: (isPositive ? AppColors.success : AppColors.error)
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
          color: isCrit ? AppColors.error : AppColors.warning,
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
      final isManyAlerts = cCount > 5;
      items.add(_AlertItem(
        icon: isManyAlerts
            ? Icons.error_outline
            : Icons.warning_amber_rounded,
        color: AppColors.error,
        text: isArabic
            ? '$cCount تنبيهات حرجة بانتظار المراجعة'
            : '$cCount critical alerts pending',
      ));
    }
    if (cDiff.abs() > 0.01) {
      items.add(_AlertItem(
        icon: Icons.account_balance_wallet,
        color: AppColors.warning,
        text: isArabic
            ? 'فرق نقدي (${_formatCurrency(cDiff)}) في آخر إغلاق'
            : 'Cash difference (${_formatCurrency(cDiff)}) in last closing',
      ));
    }
    if (gDiff.abs() > 0.001) {
      items.add(_AlertItem(
        icon: Icons.auto_awesome,
        color: AppColors.warning,
        text: isArabic
            ? 'فرق ذهب (${_formatWeight(gDiff)}) في آخر إغلاق'
            : 'Gold difference (${_formatWeight(gDiff)}) in last closing',
      ));
    }
    if (uCount > 0) {
      items.add(_AlertItem(
        icon: Icons.pending_actions,
        color: AppColors.info,
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
                child: _currencyAwareText(
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
                color: AppColors.warning,
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
              Icon(Icons.water_drop, color: AppColors.info, size: _s(20)),
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
            AppColors.success,
            total,
          ),
          SizedBox(height: _s(4)),
          _buildLiquidityRow(
            isArabic ? 'بنوك' : 'Banks',
            cashInBanks,
            AppColors.info,
            total,
          ),
          SizedBox(height: _s(4)),
          _buildLiquidityRow(
            isArabic ? 'ذمم' : 'Receiv.',
            receivables,
            AppColors.warning,
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
            _currencyAwareText(
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
  // HERO PROFIT SECTION (follows selected time range) — compact side-by-side
  // ══════════════════════════════════════════════════════════════════════════
  Widget _buildHeroProfitSection(
    Map<String, dynamic> kpis,
    Map<String, dynamic> liquidity,
    Map<String, dynamic> salesPurchasesSummary,
  ) {
    final theme = Theme.of(context);
    final isArabic = widget.isArabic;

    final periodData =
        (salesPurchasesSummary[_summaryPeriod] as Map<String, dynamic>?) ?? {};
    final salesData = (periodData['sales'] as Map<String, dynamic>?) ?? {};
    final purchasesData =
        (periodData['purchases'] as Map<String, dynamic>?) ?? {};
    final expensesData =
        (periodData['expenses'] as Map<String, dynamic>?) ?? {};

    final periodSales = _asDouble(salesData['total_value']);
    final periodPurchases = _asDouble(purchasesData['total_value']);
    final periodExpenses = _asDouble(expensesData['total_value']);
    final periodProfit = periodSales - periodPurchases - periodExpenses;
    final periodMargin =
        periodSales > 0 ? (periodProfit / periodSales) * 100 : null;
    final cashAvailable = _asDouble(liquidity['cash_available']);

    final vsYesterdayPct =
        _timeRange == _TimeRange.today
            ? _asDoubleOrNull(kpis['today_profit_vs_yesterday_pct'])
            : null;

    final isProfit = periodProfit >= 0;
    final profitColor = isProfit ? AppColors.success : AppColors.error;

    final String periodLabel;
    switch (_timeRange) {
      case _TimeRange.today:
        periodLabel = isArabic ? 'اليوم' : 'Today';
        break;
      case _TimeRange.month:
        periodLabel = isArabic ? 'الشهر' : 'Month';
        break;
      case _TimeRange.year:
        periodLabel = isArabic ? 'السنة' : 'Year';
        break;
    }

    final isAllZero =
        periodSales == 0 && periodPurchases == 0 && periodExpenses == 0;

    if (isAllZero) {
      return Container(
        padding: EdgeInsets.symmetric(horizontal: _s(16), vertical: _s(14)),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: AlignmentDirectional.centerStart,
            end: AlignmentDirectional.centerEnd,
            colors: [
              AppColors.success.withValues(alpha: 0.08),
              AppColors.success.withValues(alpha: 0.03),
              theme.cardColor,
            ],
          ),
          borderRadius: BorderRadius.circular(_s(14)),
          border: Border.all(color: AppColors.success.withValues(alpha: 0.18)),
        ),
        child: Row(
          children: [
            Container(
              width: _s(40),
              height: _s(40),
              decoration: BoxDecoration(
                color: AppColors.success.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(Icons.trending_up_rounded,
                  color: AppColors.success, size: _s(20)),
            ),
            SizedBox(width: _s(12)),
            Expanded(
              child: Text(
                isArabic
                    ? 'لا توجد عمليات بعد'
                    : 'No transactions yet',
                style: TextStyle(
                    fontSize: _s(12), color: theme.hintColor),
              ),
            ),
            _currencyAwareText('0 $_currencySymbol',
                style: TextStyle(
                    fontSize: _s(14),
                    fontWeight: FontWeight.w800,
                    color: theme.hintColor.withValues(alpha: 0.5))),
          ],
        ),
      );
    }

    return Container(
      padding: EdgeInsets.all(_s(14)),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [profitColor.withValues(alpha: 0.06), theme.cardColor],
        ),
        borderRadius: BorderRadius.circular(_s(14)),
        border: Border.all(color: profitColor.withValues(alpha: 0.20)),
        boxShadow: [
          BoxShadow(
            color: profitColor.withValues(alpha: 0.05),
            blurRadius: 10,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          // Header
          Row(
            children: [
              Container(
                width: _s(32),
                height: _s(32),
                decoration: BoxDecoration(
                  color: profitColor.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  isProfit
                      ? Icons.trending_up_rounded
                      : Icons.trending_down_rounded,
                  color: profitColor,
                  size: _s(16),
                ),
              ),
              SizedBox(width: _s(8)),
              Expanded(
                child: Text(
                  isArabic ? 'صافي الربح' : 'Net Profit',
                  style: TextStyle(
                    fontSize: _s(13),
                    fontWeight: FontWeight.w700,
                    color: profitColor,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (vsYesterdayPct != null)
                Container(
                  padding: EdgeInsets.symmetric(
                      horizontal: _s(6), vertical: _s(2)),
                  decoration: BoxDecoration(
                    color: (vsYesterdayPct >= 0
                            ? AppColors.success
                            : AppColors.error)
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
                        size: _s(10),
                        color: vsYesterdayPct >= 0
                            ? AppColors.success
                            : AppColors.error,
                      ),
                      Text(
                        '${vsYesterdayPct.abs().toStringAsFixed(1)}%',
                        style: TextStyle(
                          fontSize: _s(9),
                          fontWeight: FontWeight.bold,
                          color: vsYesterdayPct >= 0
                              ? AppColors.success
                              : AppColors.error,
                        ),
                      ),
                    ],
                  ),
                )
              else
                Container(
                  padding: EdgeInsets.symmetric(
                      horizontal: _s(8), vertical: _s(3)),
                  decoration: BoxDecoration(
                    color: profitColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    periodLabel,
                    style: TextStyle(
                      fontSize: _s(10),
                      fontWeight: FontWeight.w600,
                      color: profitColor,
                    ),
                  ),
                ),
            ],
          ),
          SizedBox(height: _s(10)),

          // Hero number + margin badge
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Flexible(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: AlignmentDirectional.centerStart,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(
                        _formatCurrency(periodProfit)
                            .replaceAll(_currencySymbol, '')
                            .trim(),
                        style: TextStyle(
                          fontWeight: FontWeight.w900,
                          color: profitColor,
                          fontSize: _s(22),
                          letterSpacing: -0.5,
                        ),
                      ),
                      SizedBox(width: _s(4)),
                      Padding(
                        padding: EdgeInsets.only(bottom: _s(3)),
                        child: _currencyAwareText(
                          _currencySymbol,
                          style: TextStyle(
                            color: profitColor.withValues(alpha: 0.7),
                            fontWeight: FontWeight.w600,
                            fontSize: _s(11),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const Spacer(),
              if (periodMargin != null)
                Container(
                  padding: EdgeInsets.symmetric(
                      horizontal: _s(7), vertical: _s(3)),
                  decoration: BoxDecoration(
                    color: profitColor.withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '${periodMargin.toStringAsFixed(1)}%',
                    style: TextStyle(
                      fontSize: _s(10),
                      fontWeight: FontWeight.bold,
                      color: profitColor,
                    ),
                  ),
                ),
              SizedBox(width: _s(4)),
              Container(
                padding:
                    EdgeInsets.symmetric(horizontal: _s(7), vertical: _s(3)),
                decoration: BoxDecoration(
                  color: profitColor.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      isProfit ? Icons.check_circle : Icons.cancel,
                      size: _s(10),
                      color: profitColor,
                    ),
                    SizedBox(width: _s(2)),
                    Text(
                      isProfit
                          ? (isArabic ? 'ربح' : 'Profit')
                          : (isArabic ? 'خسارة' : 'Loss'),
                      style: TextStyle(
                        fontSize: _s(10),
                        fontWeight: FontWeight.bold,
                        color: profitColor,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          SizedBox(height: _s(10)),

          // 3 chips: Liquidity, Sales, Purchases
          Row(
            children: [
              Expanded(
                child: _miniStatChip(
                  icon: Icons.water_drop_outlined,
                  label: isArabic ? 'السيولة' : 'Cash',
                  value: _formatCurrency(cashAvailable)
                      .replaceAll(_currencySymbol, '')
                      .trim(),
                  color: AppColors.primaryGold,
                ),
              ),
              SizedBox(width: _s(6)),
              Expanded(
                child: _miniStatChip(
                  icon: Icons.arrow_upward,
                  label: isArabic ? 'مبيعات' : 'Sales',
                  value: _formatCurrency(periodSales)
                      .replaceAll(_currencySymbol, '')
                      .trim(),
                  color: AppColors.success,
                ),
              ),
              SizedBox(width: _s(6)),
              Expanded(
                child: _miniStatChip(
                  icon: Icons.arrow_downward,
                  label: isArabic ? 'مشتريات' : 'Purch.',
                  value: _formatCurrency(periodPurchases)
                      .replaceAll(_currencySymbol, '')
                      .trim(),
                  color: AppColors.warning,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _miniStatChip({
    required IconData icon,
    required String label,
    required String value,
    required Color color,
  }) {
    final theme = Theme.of(context);
    return Container(
      padding:
          EdgeInsets.symmetric(horizontal: _s(7), vertical: _s(5)),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.18)),
      ),
      child: Row(
        children: [
          Icon(icon, size: _s(11), color: color),
          SizedBox(width: _s(4)),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  label,
                  style: TextStyle(fontSize: _s(9), color: theme.hintColor),
                  overflow: TextOverflow.ellipsis,
                ),
                _currencyAwareText(
                  value,
                  style: TextStyle(
                    fontSize: _s(10),
                    fontWeight: FontWeight.bold,
                    color: color,
                    letterSpacing: -0.2,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
        ],
      ),
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

    final mainKarat = g['main_karat']?.toString() ?? '21';
    final isProfit = netProfitWeight >= 0;

    final isAllZero = netProfitWeight == 0 &&
        weightSold == 0 &&
        avgSell == 0 &&
        avgBuy == 0;

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

    if (isAllZero) {
      return Container(
        padding: EdgeInsets.symmetric(horizontal: _s(16), vertical: _s(14)),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: AlignmentDirectional.centerStart,
            end: AlignmentDirectional.centerEnd,
            colors: [
              AppColors.primaryGold.withValues(alpha: 0.10),
              AppColors.primaryGold.withValues(alpha: 0.04),
              theme.cardColor,
            ],
          ),
          borderRadius: BorderRadius.circular(_s(14)),
          border: Border.all(
            color: AppColors.primaryGold.withValues(alpha: 0.20),
          ),
        ),
        child: Row(
          children: [
            Container(
              width: _s(48),
              height: _s(48),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [
                    AppColors.primaryGold.withValues(alpha: 0.25),
                    AppColors.primaryGold.withValues(alpha: 0.10),
                  ],
                ),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                Icons.auto_graph,
                color: AppColors.primaryGold,
                size: _s(24),
              ),
            ),
            SizedBox(width: _s(12)),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Text(
                        isArabic ? 'ربح الجرام الذهبي' : 'Gold Gram Profit',
                        style: TextStyle(
                          fontSize: _s(13.5),
                          fontWeight: FontWeight.w800,
                          color: AppColors.primaryGold,
                        ),
                      ),
                      SizedBox(width: _s(8)),
                      Container(
                        padding: EdgeInsets.symmetric(
                          horizontal: _s(7),
                          vertical: _s(2),
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.primaryGold.withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(_s(20)),
                        ),
                        child: Text(
                          periodLabel,
                          style: TextStyle(
                            fontSize: _s(9.5),
                            fontWeight: FontWeight.w700,
                            color: AppColors.primaryGold,
                          ),
                        ),
                      ),
                    ],
                  ),
                  SizedBox(height: _s(4)),
                  Row(
                    children: [
                      Icon(
                        Icons.info_outline_rounded,
                        size: _s(13),
                        color: theme.hintColor,
                      ),
                      SizedBox(width: _s(4)),
                      Expanded(
                        child: Text(
                          isArabic
                              ? 'في انتظار أول عملية بيع لحساب الربح'
                              : 'Awaiting first sale to calculate profit',
                          style: TextStyle(
                            fontSize: _s(11.5),
                            color: theme.hintColor,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  isArabic ? 'الربح' : 'Profit',
                  style: TextStyle(
                    fontSize: _s(10),
                    color: theme.hintColor,
                  ),
                ),
                _currencyAwareText(
                  '0 $_currencySymbol',
                  style: TextStyle(
                    fontSize: _s(15),
                    fontWeight: FontWeight.w800,
                    color: theme.hintColor.withValues(alpha: 0.6),
                  ),
                ),
              ],
            ),
          ],
        ),
      );
    }

    final profitColor = isProfit ? AppColors.success : AppColors.error;

    return Container(
      padding: EdgeInsets.all(_s(14)),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [
            AppColors.primaryGold.withValues(alpha: 0.06),
            theme.cardColor,
          ],
        ),
        borderRadius: BorderRadius.circular(_s(14)),
        border: Border.all(
          color: AppColors.primaryGold.withValues(alpha: 0.20),
        ),
        boxShadow: [
          BoxShadow(
            color: AppColors.primaryGold.withValues(alpha: 0.05),
            blurRadius: 10,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          // Header
          Row(
            children: [
              Container(
                width: _s(32),
                height: _s(32),
                decoration: BoxDecoration(
                  color: AppColors.primaryGold.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  Icons.auto_graph,
                  color: AppColors.primaryGold,
                  size: _s(16),
                ),
              ),
              SizedBox(width: _s(8)),
              Expanded(
                child: Text(
                  isArabic ? 'ربح الجرام الذهبي' : 'Gold Gram Profit',
                  style: TextStyle(
                    fontSize: _s(13),
                    fontWeight: FontWeight.w700,
                    color: AppColors.primaryGold,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Container(
                padding: EdgeInsets.symmetric(
                    horizontal: _s(8), vertical: _s(3)),
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

          // Hero: Weight + karat + ≈Cash + Margin
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Flexible(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: AlignmentDirectional.centerStart,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(
                        _formatWeight(netProfitWeight)
                            .replaceAll(' جم', '')
                            .replaceAll(' g', ''),
                        style: TextStyle(
                          fontWeight: FontWeight.w900,
                          color: profitColor,
                          fontSize: _s(22),
                          letterSpacing: -0.5,
                        ),
                      ),
                      SizedBox(width: _s(4)),
                      Padding(
                        padding: EdgeInsets.only(bottom: _s(3)),
                        child: Text(
                          isArabic
                              ? 'جم ($mainKarat)'
                              : 'g (k$mainKarat)',
                          style: TextStyle(
                            color: profitColor.withValues(alpha: 0.7),
                            fontWeight: FontWeight.w600,
                            fontSize: _s(11),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const Spacer(),
              Container(
                padding: EdgeInsets.symmetric(
                    horizontal: _s(7), vertical: _s(3)),
                decoration: BoxDecoration(
                  color: profitColor.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: _currencyAwareText(
                  '≈ ${_formatCurrency(netProfit)}',
                  style: TextStyle(
                    fontSize: _s(10),
                    fontWeight: FontWeight.bold,
                    color: profitColor,
                  ),
                ),
              ),
              SizedBox(width: _s(4)),
              Container(
                padding: EdgeInsets.symmetric(
                    horizontal: _s(7), vertical: _s(3)),
                decoration: BoxDecoration(
                  color: profitColor.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '${netMarginPct.toStringAsFixed(1)}%',
                  style: TextStyle(
                    fontSize: _s(10),
                    fontWeight: FontWeight.bold,
                    color: profitColor,
                  ),
                ),
              ),
            ],
          ),
          SizedBox(height: _s(10)),

          // 4 chips
          Row(
            children: [
              Expanded(
                child: _miniStatChip(
                  icon: Icons.trending_up,
                  label: isArabic ? 'بيع/جم' : 'Sell/g',
                  value: _formatCurrency(avgSell)
                      .replaceAll(_currencySymbol, '')
                      .trim(),
                  color: AppColors.success,
                ),
              ),
              SizedBox(width: _s(6)),
              Expanded(
                child: _miniStatChip(
                  icon: Icons.trending_down,
                  label: isArabic ? 'شراء/جم' : 'Buy/g',
                  value: _formatCurrency(avgBuy)
                      .replaceAll(_currencySymbol, '')
                      .trim(),
                  color: AppColors.warning,
                ),
              ),
              SizedBox(width: _s(6)),
              Expanded(
                child: _miniStatChip(
                  icon: Icons.swap_horiz,
                  label: isArabic ? 'فارق/جم' : 'Margin/g',
                  value: _formatCurrency(marginPerGram)
                      .replaceAll(_currencySymbol, '')
                      .trim(),
                  color: marginPerGram >= 0
                      ? AppColors.success
                      : AppColors.error,
                ),
              ),
              SizedBox(width: _s(6)),
              Expanded(
                child: _miniStatChip(
                  icon: Icons.monitor_weight_outlined,
                  label: isArabic ? 'المباع' : 'Sold',
                  value: _formatWeight(weightSold)
                      .replaceAll(' جم', '')
                      .replaceAll(' g', ''),
                  color: AppColors.info,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  // _buildTodayProfitCard removed (unused).
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
                isPositive ? Icons.trending_up : Icons.trending_down,
                color: isPositive ? AppColors.success : AppColors.error,
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
          _currencyAwareText(
            _formatCurrency(todayProfit),
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.bold,
              color: isPositive ? AppColors.success : AppColors.error,
              fontSize: _s(20),
            ),
          ),
          if (marginValue != null)
            Container(
              margin: EdgeInsets.only(top: _s(4)),
              padding: EdgeInsets.symmetric(horizontal: _s(6), vertical: _s(2)),
              decoration: BoxDecoration(
                color: (isPositive ? AppColors.success : AppColors.error).withValues(
                  alpha: 0.1,
                ),
                borderRadius: BorderRadius.circular(_s(4)),
              ),
              child: Text(
                '${marginValue.toStringAsFixed(1)}% ${isArabic ? "هامش" : "margin"}',
                style: TextStyle(
                  fontSize: _s(11),
                  fontWeight: FontWeight.bold,
                  color: isPositive ? AppColors.success : AppColors.error,
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
              builder: (_) => SafeBoxHeroDetailsScreen(
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
        color = AppColors.info;
        primaryValue = cashBalance;
        primaryFormatter = _formatCurrency;
        subtitle = isArabic ? 'بنك' : 'Bank';
        break;
      default:
        icon = Icons.account_balance_wallet;
        color = AppColors.success;
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
        child: _currencyAwareText(
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

    final borderAccent = hasActivity ? AppColors.success : theme.hintColor;
    final borderColor = borderAccent.withValues(alpha: hasActivity ? 0.55 : 0.25);
    final glowColor = (hasActivity ? AppColors.success : color).withValues(
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
                                    color: AppColors.success,
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
                          Text(
                            subtitle,
                            style: theme.textTheme.bodySmall?.copyWith(
                              fontSize: _s(11),
                              color: color,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          SizedBox(height: _s(2)),
                          Hero(
                            tag: heroNameTag,
                            createRectTween: (begin, end) =>
                                MaterialRectArcTween(begin: begin, end: end),
                            child: Material(
                              color: Colors.transparent,
                              child: Text(
                                name,
                                style: theme.textTheme.bodySmall?.copyWith(
                                  fontWeight: FontWeight.w700,
                                  fontSize: _s(12.5),
                                ),
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                              ),
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
                            isNewSar: _currencyIsNewSar,
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

class _AnimatedValueText extends StatefulWidget {
  final double value;
  final String Function(double) formatter;
  final bool isNewSar;
  final TextStyle? style;

  const _AnimatedValueText({
    required this.value,
    required this.formatter,
    this.isNewSar = false,
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
        return cu.SarAwareText(
          widget.formatter(v),
          isNewSar: widget.isNewSar,
          style: widget.style,
        );
      },
      onEnd: () {
        _from = _to;
      },
    );
  }
}
