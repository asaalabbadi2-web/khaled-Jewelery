import 'package:flutter/material.dart';
import '../api_service.dart';
import '../models/inventory_models.dart';
import '../services/inventory_service.dart';
import '../theme/app_theme.dart';
import '../widgets/bucket_balance_card.dart';
import 'inventory_count_screen.dart';

class InventoryBalanceScreen extends StatefulWidget {
  const InventoryBalanceScreen({super.key});

  @override
  State<InventoryBalanceScreen> createState() => _InventoryBalanceScreenState();
}

class _InventoryBalanceScreenState extends State<InventoryBalanceScreen> {
  final _svc = InventoryService(ApiService());

  InventoryBalanceSummary? _summary;
  List<InventoryBucket> _buckets = [];
  bool _loading = true;
  String? _error;

  // Filters
  int? _filterBranchId;
  double? _filterKarat;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final results = await Future.wait([
        _svc.getBalanceSummary(),
        _svc.getBalance(branchId: _filterBranchId, karat: _filterKarat),
      ]);
      setState(() {
        _summary = results[0] as InventoryBalanceSummary;
        _buckets = results[1] as List<InventoryBucket>;
        _loading = false;
      });
    } on InventoryApiException catch (e) {
      setState(() { _error = e.message; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        backgroundColor: Theme.of(context).scaffoldBackgroundColor,
        appBar: AppBar(
          title: const Text('الجرد الفعلي'),
          backgroundColor: AppColors.primaryGold,
          foregroundColor: Colors.white,
          actions: [
            IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: _load,
              tooltip: 'تحديث',
            ),
          ],
        ),
        body: _loading
            ? const Center(child: CircularProgressIndicator(color: AppColors.primaryGold))
            : _error != null
                ? _ErrorView(message: _error!, onRetry: _load)
                : RefreshIndicator(
                    onRefresh: _load,
                    color: AppColors.primaryGold,
                    child: CustomScrollView(
                      slivers: [
                        SliverToBoxAdapter(child: _SummaryHeader(summary: _summary!)),
                        SliverToBoxAdapter(child: _KaratFilterBar(
                          karats: _summary!.byKarat.map((k) => k.karat).toList(),
                          selected: _filterKarat,
                          onSelected: (k) {
                            setState(() => _filterKarat = k);
                            _load();
                          },
                        )),
                        SliverToBoxAdapter(child: _BranchFilterBar(
                          branches: _summary!.byBranch,
                          selected: _filterBranchId,
                          onSelected: (id) {
                            setState(() => _filterBranchId = id);
                            _load();
                          },
                        )),
                        if (_buckets.isEmpty)
                          const SliverFillRemaining(
                            child: Center(child: Text('لا توجد أرصدة مسجّلة')),
                          )
                        else
                          SliverPadding(
                            padding: const EdgeInsets.fromLTRB(16, 8, 16, 100),
                            sliver: SliverList(
                              delegate: SliverChildBuilderDelegate(
                                (_, i) => Padding(
                                  padding: const EdgeInsets.only(bottom: 10),
                                  child: BucketBalanceCard.fromBucket(_buckets[i]),
                                ),
                                childCount: _buckets.length,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
        floatingActionButton: FloatingActionButton.extended(
          onPressed: _openCountSession,
          backgroundColor: AppColors.primaryGold,
          foregroundColor: Colors.white,
          icon: const Icon(Icons.fact_check_outlined),
          label: const Text('بدء جرد'),
        ),
      ),
    );
  }

  void _openCountSession() {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const InventoryCountScreen()),
    ).then((_) => _load());
  }
}

// ── Summary Header ────────────────────────────────────────────────────────────

class _SummaryHeader extends StatelessWidget {
  const _SummaryHeader({required this.summary});
  final InventoryBalanceSummary summary;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [AppColors.darkGold, AppColors.primaryGold],
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
        ),
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: AppColors.primaryGold.withOpacity(0.3),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'إجمالي الذهب',
            style: TextStyle(color: Colors.white70, fontSize: 13),
          ),
          const SizedBox(height: 4),
          Text(
            '${formatWeight(summary.grandTotalWeight)} جم',
            style: const TextStyle(
              color: Colors.white,
              fontSize: 28,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 12),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            reverse: true,
            child: Row(
              children: summary.byKarat.map((k) => _KaratChip(k)).toList(),
            ),
          ),
        ],
      ),
    );
  }
}

class _KaratChip extends StatelessWidget {
  const _KaratChip(this.k);
  final KaratTotal k;

  @override
  Widget build(BuildContext context) {
    final color = AppColors.karatColorFor(k.karat);
    return Container(
      margin: const EdgeInsets.only(left: 8),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.15),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.6)),
      ),
      child: Text(
        'عيار ${k.karat.toStringAsFixed(0)}  ${formatWeight(k.totalWeight)} جم',
        style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}

// ── Filter Bars ───────────────────────────────────────────────────────────────

class _KaratFilterBar extends StatelessWidget {
  const _KaratFilterBar({
    required this.karats,
    required this.selected,
    required this.onSelected,
  });
  final List<double> karats;
  final double? selected;
  final ValueChanged<double?> onSelected;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 40,
      child: ListView(
        scrollDirection: Axis.horizontal,
        reverse: true,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        children: [
          _FilterChip(
            label: 'كل العيارات',
            selected: selected == null,
            onTap: () => onSelected(null),
          ),
          ...karats.map((k) => _FilterChip(
                label: 'عيار ${k.toStringAsFixed(0)}',
                selected: selected == k,
                color: AppColors.karatColorFor(k),
                onTap: () => onSelected(selected == k ? null : k),
              )),
        ],
      ),
    );
  }
}

class _BranchFilterBar extends StatelessWidget {
  const _BranchFilterBar({
    required this.branches,
    required this.selected,
    required this.onSelected,
  });
  final List<BranchTotal> branches;
  final int? selected;
  final ValueChanged<int?> onSelected;

  @override
  Widget build(BuildContext context) {
    if (branches.length <= 1) return const SizedBox.shrink();
    return SizedBox(
      height: 40,
      child: ListView(
        scrollDirection: Axis.horizontal,
        reverse: true,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        children: [
          _FilterChip(
            label: 'كل الفروع',
            selected: selected == null,
            onTap: () => onSelected(null),
          ),
          ...branches.map((b) => _FilterChip(
                label: b.branchName,
                selected: selected == b.branchId,
                onTap: () => onSelected(
                    selected == b.branchId ? null : b.branchId),
              )),
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({
    required this.label,
    required this.selected,
    required this.onTap,
    this.color,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final c = color ?? AppColors.primaryGold;
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        margin: const EdgeInsets.only(left: 8),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? c : Colors.transparent,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: selected ? c : Colors.grey.shade300),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: selected ? Colors.white : Colors.grey[700],
            fontSize: 12,
            fontWeight: selected ? FontWeight.bold : FontWeight.normal,
          ),
        ),
      ),
    );
  }
}

// ── Error View ────────────────────────────────────────────────────────────────

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 48, color: AppColors.warning),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('إعادة المحاولة'),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.primaryGold,
                foregroundColor: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
