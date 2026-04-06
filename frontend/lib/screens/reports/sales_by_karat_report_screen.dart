import 'package:flutter/material.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:provider/provider.dart';

import '../../api_service.dart';
import '../../providers/settings_provider.dart';

class SalesByKaratReportScreen extends StatefulWidget {
  final ApiService api;
  final bool isArabic;

  const SalesByKaratReportScreen({
    super.key,
    required this.api,
    this.isArabic = true,
  });

  @override
  State<SalesByKaratReportScreen> createState() =>
      _SalesByKaratReportScreenState();
}

class _SalesByKaratReportScreenState extends State<SalesByKaratReportScreen> {
  Map<String, dynamic>? _report;
  bool _isLoading = false;
  String? _error;

  DateTimeRange? _selectedRange;
  bool _includeUnposted = false;

  String _currencySymbol = 'ر.س';
  int _currencyDecimals = 2;
  int _mainKarat = 21;

  late NumberFormat _currencyFormat;
  final NumberFormat _weightFormat = NumberFormat('#,##0.000');
  final NumberFormat _pctFormat = NumberFormat('#,##0.0');

  // ألوان العيارات
  static const Map<int, Color> _karatColors = {
    18: Color(0xFF9C6E3A),
    21: Color(0xFFFFD700),
    22: Color(0xFFFFC107),
    24: Color(0xFFFF8F00),
  };

  Color _karatColor(int karat) =>
      _karatColors[karat] ?? const Color(0xFF8E7D6D);

  @override
  void initState() {
    super.initState();
    final today = DateTime.now();
    _selectedRange = DateTimeRange(
      start: DateTime(today.year, today.month, today.day)
          .subtract(const Duration(days: 29)),
      end: DateTime(today.year, today.month, today.day),
    );
    _currencyFormat = NumberFormat.currency(
      locale: widget.isArabic ? 'ar' : 'en',
      symbol: _currencySymbol,
      decimalDigits: _currencyDecimals,
    );
    _loadReport();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final settings = Provider.of<SettingsProvider>(context);
    if (settings.currencySymbol != _currencySymbol ||
        settings.decimalPlaces != _currencyDecimals ||
        settings.mainKarat != _mainKarat) {
      setState(() {
        _currencySymbol = settings.currencySymbol;
        _currencyDecimals = settings.decimalPlaces;
        _mainKarat = settings.mainKarat;
        _currencyFormat = NumberFormat.currency(
          locale: widget.isArabic ? 'ar' : 'en',
          symbol: _currencySymbol,
          decimalDigits: _currencyDecimals,
        );
      });
    }
  }

  Future<void> _loadReport() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final result = await widget.api.getSalesByKaratReport(
        startDate: _selectedRange?.start,
        endDate: _selectedRange?.end,
        includeUnposted: _includeUnposted,
      );
      if (!mounted) return;
      setState(() => _report = result);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _pickDateRange() async {
    final now = DateTime.now();
    final picked = await showDateRangePicker(
      context: context,
      firstDate: DateTime(now.year - 5),
      lastDate: DateTime(now.year + 1),
      initialDateRange: _selectedRange ??
          DateTimeRange(
            start: now.subtract(const Duration(days: 29)),
            end: now,
          ),
      locale: widget.isArabic ? const Locale('ar') : const Locale('en'),
    );
    if (picked != null) {
      setState(() => _selectedRange = picked);
      await _loadReport();
    }
  }

  double _asDouble(dynamic v) {
    if (v is num) return v.toDouble();
    return 0.0;
  }

  String _fw(num v) => '${_weightFormat.format(v)} جم';
  String _fv(num v) => _currencyFormat.format(v);

  @override
  Widget build(BuildContext context) {
    final isArabic = widget.isArabic;
    return Directionality(
      textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
      child: Scaffold(
        appBar: AppBar(
          title: Text(isArabic ? 'المبيعات حسب العيار' : 'Sales by Karat'),
          actions: [
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: isArabic ? 'تحديث' : 'Refresh',
              onPressed: _isLoading ? null : _loadReport,
            ),
          ],
        ),
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
          Icon(Icons.error_outline, size: 48, color: Colors.red.shade400),
          const SizedBox(height: 12),
          Text(
            isArabic ? 'تعذّر تحميل التقرير' : 'Failed to load report',
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Text(
              _error ?? '',
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.grey),
            ),
          ),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _loadReport,
            icon: const Icon(Icons.refresh),
            label: Text(isArabic ? 'إعادة المحاولة' : 'Try Again'),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    final isArabic = widget.isArabic;
    return RefreshIndicator(
      onRefresh: _loadReport,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        children: [
          _buildFiltersCard(isArabic),
          const SizedBox(height: 16),
          _buildSummaryCards(isArabic),
          const SizedBox(height: 16),
          _buildWeightBarChart(isArabic),
          const SizedBox(height: 16),
          _buildKaratCards(isArabic),
        ],
      ),
    );
  }

  // ── فلاتر ──────────────────────────────────────────────
  Widget _buildFiltersCard(bool isArabic) {
    final rangeText = _selectedRange == null
        ? (isArabic ? 'كل الفترات' : 'All time')
        : '${DateFormat('yyyy-MM-dd').format(_selectedRange!.start)} – ${DateFormat('yyyy-MM-dd').format(_selectedRange!.end)}';

    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment:
              isArabic ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            Text(
              isArabic ? 'خيارات التقرير' : 'Report Options',
              style: const TextStyle(
                  fontWeight: FontWeight.bold, fontSize: 16),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 10,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                OutlinedButton.icon(
                  onPressed: _pickDateRange,
                  icon: const Icon(Icons.date_range, size: 18),
                  label: Text(rangeText),
                ),
                if (_selectedRange != null)
                  TextButton.icon(
                    onPressed: () {
                      setState(() => _selectedRange = null);
                      _loadReport();
                    },
                    icon: const Icon(Icons.clear, size: 16),
                    label: Text(isArabic ? 'إزالة الفترة' : 'Clear'),
                  ),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Switch(
                      value: _includeUnposted,
                      onChanged: (v) {
                        setState(() => _includeUnposted = v);
                        _loadReport();
                      },
                    ),
                    const SizedBox(width: 6),
                    Text(
                      isArabic ? 'تضمين غير المرحّلة' : 'Include unposted',
                      style: const TextStyle(fontSize: 13),
                    ),
                  ],
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  // ── ملخص ──────────────────────────────────────────────
  Widget _buildSummaryCards(bool isArabic) {
    if (_report == null) return const SizedBox.shrink();
    final s = _report!['summary'] as Map<String, dynamic>? ?? {};
    final mainK = s['main_karat'] ?? _mainKarat;

    final items = [
      _SummaryItem(
        icon: Icons.scale,
        color: const Color(0xFFFFD700),
        label: isArabic ? 'صافي الوزن' : 'Net Weight',
        value: _fw(_asDouble(s['net_weight'])),
        sub: 'عيار $mainK',
      ),
      _SummaryItem(
        icon: Icons.monetization_on,
        color: const Color(0xFF2E7D32),
        label: isArabic ? 'صافي المبيعات' : 'Net Sales',
        value: _fv(_asDouble(s['net_value'])),
      ),
      _SummaryItem(
        icon: Icons.speed,
        color: const Color(0xFF1565C0),
        label: isArabic ? 'متوسط سعر/جم' : 'Avg Price/g',
        value: _fv(_asDouble(s['avg_price_per_gram'])),
      ),
      _SummaryItem(
        icon: Icons.receipt_long,
        color: const Color(0xFF6A1B9A),
        label: isArabic ? 'عدد الفواتير' : 'Invoices',
        value: '${s['total_documents'] ?? 0}',
      ),
    ];

    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisSpacing: 12,
      mainAxisSpacing: 12,
      childAspectRatio: 2.1,
      children: items.map(_buildSummaryTile).toList(),
    );
  }

  Widget _buildSummaryTile(_SummaryItem item) {
    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Row(
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: item.color.withOpacity(0.12),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(item.icon, color: item.color, size: 22),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    item.label,
                    style: TextStyle(
                      fontSize: 11,
                      color: Colors.grey.shade600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    item.value,
                    style: const TextStyle(
                        fontWeight: FontWeight.bold, fontSize: 14),
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (item.sub != null)
                    Text(
                      item.sub!,
                      style:
                          TextStyle(fontSize: 10, color: Colors.grey.shade500),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── شريط الوزن ────────────────────────────────────────
  Widget _buildWeightBarChart(bool isArabic) {
    if (_report == null) return const SizedBox.shrink();
    final karats = (_report!['karats'] as List<dynamic>?) ?? [];
    if (karats.isEmpty) return const SizedBox.shrink();

    final totalNetWeight = karats.fold<double>(
        0.0, (s, k) => s + _asDouble((k as Map)['net_weight']));
    if (totalNetWeight <= 0) return const SizedBox.shrink();

    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment:
              isArabic ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            Text(
              isArabic ? 'توزيع الوزن حسب العيار' : 'Weight by Karat',
              style: const TextStyle(
                  fontWeight: FontWeight.bold, fontSize: 15),
            ),
            const SizedBox(height: 16),
            ...karats.map((k) {
              final km = k as Map<String, dynamic>;
              final karat = km['karat'] as int? ?? 21;
              final nw = _asDouble(km['net_weight']);
              final pct = totalNetWeight > 0
                  ? (nw / totalNetWeight * 100).clamp(0.0, 100.0)
                  : 0.0;
              final color = _karatColor(karat);

              return Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Column(
                  crossAxisAlignment: isArabic
                      ? CrossAxisAlignment.end
                      : CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          width: 10,
                          height: 10,
                          decoration: BoxDecoration(
                            color: color,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'عيار $karat',
                            style: const TextStyle(
                                fontWeight: FontWeight.w600, fontSize: 13),
                          ),
                        ),
                        Text(
                          _fw(nw),
                          style: const TextStyle(fontSize: 12),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          '${_pctFormat.format(pct)}%',
                          style: TextStyle(
                              fontSize: 12,
                              color: color,
                              fontWeight: FontWeight.bold),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    ClipRRect(
                      borderRadius: BorderRadius.circular(6),
                      child: LinearProgressIndicator(
                        value: pct / 100,
                        minHeight: 10,
                        backgroundColor: Colors.grey.shade200,
                        valueColor: AlwaysStoppedAnimation<Color>(color),
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
        ),
      ),
    );
  }

  // ── بطاقات العيارات ────────────────────────────────────
  Widget _buildKaratCards(bool isArabic) {
    if (_report == null) return const SizedBox.shrink();
    final karats = (_report!['karats'] as List<dynamic>?) ?? [];
    if (karats.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Text(
            isArabic ? 'لا توجد بيانات في هذه الفترة' : 'No data for this period',
            style: const TextStyle(color: Colors.grey, fontSize: 16),
          ),
        ),
      );
    }

    return Column(
      children: karats.map((k) {
        final km = k as Map<String, dynamic>;
        return _buildKaratCard(km, isArabic);
      }).toList(),
    );
  }

  Widget _buildKaratCard(Map<String, dynamic> km, bool isArabic) {
    final karat = km['karat'] as int? ?? 21;
    final color = _karatColor(karat);
    final nw = _asDouble(km['net_weight']);
    final sw = _asDouble(km['sales_weight']);
    final rw = _asDouble(km['returns_weight']);
    final nv = _asDouble(km['net_value']);
    final sv = _asDouble(km['sales_value']);
    final rv = _asDouble(km['returns_value']);
    final avg = _asDouble(km['avg_price_per_gram']);
    final pct = _asDouble(km['weight_share_pct']);
    final docs = km['documents'] as int? ?? 0;

    return Card(
      elevation: 2,
      margin: const EdgeInsets.only(bottom: 12),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ExpansionTile(
        leading: Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            color: color.withOpacity(0.15),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Center(
            child: Text(
              '$karat',
              style: TextStyle(
                color: color,
                fontWeight: FontWeight.bold,
                fontSize: 16,
              ),
            ),
          ),
        ),
        title: Text(
          'عيار $karat',
          style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
        ),
        subtitle: Row(
          children: [
            Icon(Icons.scale, size: 12, color: Colors.grey.shade500),
            const SizedBox(width: 4),
            Text(
              _fw(nw),
              style: TextStyle(fontSize: 12, color: Colors.grey.shade600),
            ),
            const SizedBox(width: 12),
            Icon(Icons.percent, size: 12, color: color),
            const SizedBox(width: 2),
            Text(
              '${_pctFormat.format(pct)}%',
              style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        trailing: Text(
          _fv(nv),
          style: TextStyle(
            fontWeight: FontWeight.bold,
            fontSize: 15,
            color: color,
          ),
        ),
        childrenPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        children: [
          const Divider(height: 1),
          const SizedBox(height: 12),
          _buildDetailGrid([
            _DetailItem(
                label: isArabic ? 'وزن المبيعات' : 'Sales Weight',
                value: _fw(sw),
                icon: Icons.arrow_upward,
                color: Colors.green),
            _DetailItem(
                label: isArabic ? 'وزن المرتجعات' : 'Returns Weight',
                value: _fw(rw),
                icon: Icons.arrow_downward,
                color: Colors.red),
            _DetailItem(
                label: isArabic ? 'إجمالي المبيعات' : 'Sales Value',
                value: _fv(sv),
                icon: Icons.sell,
                color: Colors.green),
            _DetailItem(
                label: isArabic ? 'إجمالي المرتجعات' : 'Returns Value',
                value: _fv(rv),
                icon: Icons.undo,
                color: Colors.orange),
            _DetailItem(
                label: isArabic ? 'متوسط سعر/جم' : 'Avg Price/g',
                value: _fv(avg),
                icon: Icons.speed,
                color: Colors.blue),
            _DetailItem(
                label: isArabic ? 'عدد الفواتير' : 'Invoices',
                value: '$docs',
                icon: Icons.receipt_long,
                color: Colors.purple),
          ]),
          const SizedBox(height: 8),
        ],
      ),
    );
  }

  Widget _buildDetailGrid(List<_DetailItem> items) {
    return GridView.count(
      crossAxisCount: 2,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      crossAxisSpacing: 10,
      mainAxisSpacing: 10,
      childAspectRatio: 2.8,
      children: items.map((item) {
        return Container(
          decoration: BoxDecoration(
            color: item.color.withOpacity(0.07),
            borderRadius: BorderRadius.circular(10),
          ),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          child: Row(
            children: [
              Icon(item.icon, size: 16, color: item.color),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      item.label,
                      style: TextStyle(
                          fontSize: 10, color: Colors.grey.shade600),
                    ),
                    Text(
                      item.value,
                      style: const TextStyle(
                          fontWeight: FontWeight.bold, fontSize: 12),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }
}

class _SummaryItem {
  final IconData icon;
  final Color color;
  final String label;
  final String value;
  final String? sub;
  const _SummaryItem(
      {required this.icon,
      required this.color,
      required this.label,
      required this.value,
      this.sub});
}

class _DetailItem {
  final String label;
  final String value;
  final IconData icon;
  final Color color;
  const _DetailItem(
      {required this.label,
      required this.value,
      required this.icon,
      required this.color});
}
