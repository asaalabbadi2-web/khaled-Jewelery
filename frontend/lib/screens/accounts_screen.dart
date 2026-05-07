import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../providers/settings_provider.dart';

import '../api_service.dart';
import 'account_ledger_screen.dart';
import 'account_statement_screen.dart';
import '../utils/currency_utils.dart' as cu;

enum _AccountsViewMode { cards, compact }

class AccountsScreen extends StatefulWidget {
  final bool initialOnlyDetailAccounts;

  const AccountsScreen({super.key, this.initialOnlyDetailAccounts = false});

  @override
  State<AccountsScreen> createState() => _AccountsScreenState();
}

class _AccountsScreenState extends State<AccountsScreen> {
  final TextEditingController _searchController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final GlobalKey _topChromeKey = GlobalKey();

  List<Map<String, dynamic>> _allAccounts = const [];
  List<Map<String, dynamic>> _filteredAccounts = const [];
  bool _isLoading = true;
  String? _error;

  late bool _onlyDetailAccounts;
  bool _onlyWithBalance = false;
  bool _onlyWeightAccounts = false;
  String _sortBy = 'number';
  bool _sortAscending = true;
  _AccountsViewMode _viewMode = _AccountsViewMode.cards;

  double _topChromeHeight = 0;
  double _topChromeCollapseOffset = 0;

  final NumberFormat _cashFormat = NumberFormat('#,##0.00', 'ar');
  final NumberFormat _goldFormat = NumberFormat('#,##0.###', 'ar');

  @override
  void initState() {
    super.initState();
    _onlyDetailAccounts = widget.initialOnlyDetailAccounts;
    _searchController.addListener(_filterAccounts);
    _scrollController.addListener(_onContentScroll);
    _fetchAccounts();
  }

  @override
  void dispose() {
    _searchController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _fetchAccounts() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final allAccounts = await ApiService().getAccounts();
      if (!mounted) {
        return;
      }
      _allAccounts = allAccounts
          .whereType<Map>()
          .map(
            (entry) =>
                entry.map((key, value) => MapEntry(key.toString(), value)),
          )
          .toList(growable: false);
      _filterAccounts();
      setState(() {
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) {
        return;
      }
      setState(() {
        _isLoading = false;
        _error = e.toString();
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('تعذر تحميل الحسابات: $e')));
    }
  }

  void _onContentScroll() {
    final nextOffset = _scrollController.hasClients
        ? _scrollController.offset.clamp(0.0, _topChromeHeight)
        : 0.0;
    if ((nextOffset - _topChromeCollapseOffset).abs() < 0.5) {
      return;
    }
    setState(() {
      _topChromeCollapseOffset = nextOffset;
    });
  }

  void _measureTopChrome() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      final context = _topChromeKey.currentContext;
      if (context == null) {
        return;
      }
      final renderObject = context.findRenderObject();
      if (renderObject is! RenderBox) {
        return;
      }
      final measuredHeight = renderObject.size.height;
      if (measuredHeight <= 0 ||
          (measuredHeight - _topChromeHeight).abs() < 0.5) {
        return;
      }
      setState(() {
        _topChromeHeight = measuredHeight;
        if (_topChromeCollapseOffset > measuredHeight) {
          _topChromeCollapseOffset = measuredHeight;
        }
      });
    });
  }

  int? _asInt(dynamic value) {
    if (value is int) {
      return value;
    }
    if (value is num) {
      return value.toInt();
    }
    return int.tryParse('${value ?? ''}');
  }

  double _asDouble(dynamic value) {
    if (value is double) {
      return value;
    }
    if (value is num) {
      return value.toDouble();
    }
    return double.tryParse('${value ?? ''}') ?? 0.0;
  }

  Map<String, dynamic>? _balancesOf(Map<String, dynamic> account) {
    final balances = account['balances'];
    if (balances is Map) {
      return balances.map((key, value) => MapEntry(key.toString(), value));
    }
    return null;
  }

  bool _hasChildren(Map<String, dynamic> account) {
    final subAccounts = account['sub_accounts'] as List?;
    return subAccounts != null && subAccounts.isNotEmpty;
  }

  bool _tracksWeight(Map<String, dynamic> account) =>
      account['tracks_weight'] == true;

  double _cashBalanceOf(Map<String, dynamic> account) {
    return _asDouble(_balancesOf(account)?['cash']);
  }

  double _goldBalanceOf(Map<String, dynamic> account) {
    final weight = _balancesOf(account)?['weight'];
    if (weight is Map) {
      return _asDouble(weight['total']);
    }
    return 0.0;
  }

  bool _hasAnyBalance(Map<String, dynamic> account) {
    return _cashBalanceOf(account).abs() > 0.01 ||
        _goldBalanceOf(account).abs() > 0.001;
  }

  String _accountTypeLabel(Map<String, dynamic> account) {
    final type = (account['type'] ?? '').toString().trim();
    return type.isEmpty ? 'غير مصنف' : type;
  }

  String _parentLabel(Map<String, dynamic> account) {
    final parent = account['parent_account'];
    if (parent is! Map) {
      return 'بدون حساب رئيسي';
    }
    final name = (parent['name'] ?? '').toString().trim();
    final number = (parent['account_number'] ?? '').toString().trim();
    if (name.isNotEmpty && number.isNotEmpty) {
      return '$name • $number';
    }
    if (name.isNotEmpty) {
      return name;
    }
    return number.isEmpty ? 'بدون حساب رئيسي' : number;
  }

  String _accountNumber(Map<String, dynamic> account) {
    return (account['account_number'] ?? '').toString().trim();
  }

  void _filterAccounts() {
    final query = _searchController.text.trim().toLowerCase();
    final filtered = _allAccounts
        .where((account) {
          final name = (account['name'] ?? '').toString().toLowerCase();
          final accountNumber = _accountNumber(account).toLowerCase();
          final type = _accountTypeLabel(account).toLowerCase();
          final parent = _parentLabel(account).toLowerCase();

          final matchesQuery =
              query.isEmpty ||
              name.contains(query) ||
              accountNumber.contains(query) ||
              type.contains(query) ||
              parent.contains(query);

          if (!matchesQuery) {
            return false;
          }
          if (_onlyDetailAccounts && _hasChildren(account)) {
            return false;
          }
          if (_onlyWithBalance && !_hasAnyBalance(account)) {
            return false;
          }
          if (_onlyWeightAccounts && !_tracksWeight(account)) {
            return false;
          }
          return true;
        })
        .toList(growable: false);

    filtered.sort((a, b) {
      int comparison;
      switch (_sortBy) {
        case 'name':
          comparison = (a['name'] ?? '').toString().compareTo(
            (b['name'] ?? '').toString(),
          );
          break;
        case 'cash':
          comparison = _cashBalanceOf(a).compareTo(_cashBalanceOf(b));
          break;
        case 'gold':
          comparison = _goldBalanceOf(a).compareTo(_goldBalanceOf(b));
          break;
        case 'type':
          comparison = _accountTypeLabel(a).compareTo(_accountTypeLabel(b));
          break;
        case 'children':
          comparison = (_hasChildren(a) ? 1 : 0).compareTo(
            _hasChildren(b) ? 1 : 0,
          );
          break;
        default:
          comparison = _accountNumber(a).compareTo(_accountNumber(b));
          break;
      }

      if (comparison == 0) {
        comparison = (a['name'] ?? '').toString().compareTo(
          (b['name'] ?? '').toString(),
        );
      }
      return _sortAscending ? comparison : -comparison;
    });

    setState(() {
      _filteredAccounts = filtered;
    });
  }

  int get _activeFiltersCount {
    int count = 0;
    if (_searchController.text.trim().isNotEmpty) count++;
    if (_onlyDetailAccounts) count++;
    if (_onlyWithBalance) count++;
    if (_onlyWeightAccounts) count++;
    if (_sortBy != 'number' || !_sortAscending) count++;
    return count;
  }

  Future<void> _copyAccountNumber(Map<String, dynamic> account) async {
    final accountNumber = _accountNumber(account);
    if (accountNumber.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: accountNumber));
    if (!mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text('تم نسخ رقم الحساب $accountNumber')));
  }

  void _openStatement(Map<String, dynamic> account) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => AccountStatementScreen(
          accountId: _asInt(account['id']) ?? 0,
          accountName: (account['name'] ?? 'N/A').toString(),
        ),
      ),
    );
  }

  void _openLedger(Map<String, dynamic> account) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => AccountLedgerScreen(
          accountId: _asInt(account['id']) ?? 0,
          accountName: (account['name'] ?? 'N/A').toString(),
        ),
      ),
    );
  }

  Widget _buildSummaryCard({
    required String title,
    required String value,
    required String subtitle,
    required IconData icon,
    required Color color,
  }) {
    final theme = Theme.of(context);
    return ConstrainedBox(
      constraints: const BoxConstraints(minWidth: 180, maxWidth: 250),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: theme.colorScheme.surface,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: color.withValues(alpha: 0.16)),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.05),
              blurRadius: 12,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(icon, color: color, size: 20),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: theme.textTheme.bodySmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    value,
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                      color: color,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurface.withValues(
                        alpha: 0.62,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatisticsSection() {
    final totalAccounts = _filteredAccounts.length;
    final detailAccounts = _filteredAccounts
        .where((account) => !_hasChildren(account))
        .length;
    final weightAccounts = _filteredAccounts.where(_tracksWeight).length;
    final withBalance = _filteredAccounts.where(_hasAnyBalance).length;

    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        _buildSummaryCard(
          title: 'الحسابات المطابقة',
          value: '$totalAccounts',
          subtitle: 'بعد الفلاتر الحالية',
          icon: Icons.account_balance_outlined,
          color: Theme.of(context).colorScheme.primary,
        ),
        _buildSummaryCard(
          title: 'حسابات فرعية',
          value: '$detailAccounts',
          subtitle: 'جاهزة للكشوف والحركة',
          icon: Icons.account_tree_outlined,
          color: Colors.teal,
        ),
        _buildSummaryCard(
          title: 'حسابات برصيد',
          value: '$withBalance',
          subtitle: 'نقدي أو وزني',
          icon: Icons.account_balance_wallet_outlined,
          color: Colors.green,
        ),
        _buildSummaryCard(
          title: 'حسابات وزنية',
          value: '$weightAccounts',
          subtitle: 'تتعقب الذهب أو الوزن',
          icon: Icons.scale_outlined,
          color: const Color(0xFFD4A017),
        ),
      ],
    );
  }

  Widget _buildCollapsibleTopChrome() {
    final content = KeyedSubtree(
      key: _topChromeKey,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
        child: _buildStatisticsSection(),
      ),
    );

    _measureTopChrome();

    if (_topChromeHeight <= 0) {
      return content;
    }

    final collapse = _topChromeCollapseOffset.clamp(0.0, _topChromeHeight);
    final visibleHeight = (_topChromeHeight - collapse).clamp(
      0.0,
      _topChromeHeight,
    );
    if (visibleHeight <= 0) {
      return const SizedBox.shrink();
    }

    return ClipRect(
      child: SizedBox(
        height: visibleHeight,
        child: OverflowBox(
          alignment: Alignment.topCenter,
          minHeight: _topChromeHeight,
          maxHeight: _topChromeHeight,
          child: Transform.translate(
            offset: Offset(0, -collapse),
            child: content,
          ),
        ),
      ),
    );
  }

  Widget _buildManagementToolbar() {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: theme.colorScheme.outline.withValues(alpha: 0.14),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    FilterChip(
                      label: const Text('فرعية فقط'),
                      selected: _onlyDetailAccounts,
                      onSelected: (value) {
                        setState(() {
                          _onlyDetailAccounts = value;
                        });
                        _filterAccounts();
                      },
                    ),
                    FilterChip(
                      label: const Text('برصيد فقط'),
                      selected: _onlyWithBalance,
                      onSelected: (value) {
                        setState(() {
                          _onlyWithBalance = value;
                        });
                        _filterAccounts();
                      },
                    ),
                    FilterChip(
                      label: const Text('وزنية فقط'),
                      selected: _onlyWeightAccounts,
                      onSelected: (value) {
                        setState(() {
                          _onlyWeightAccounts = value;
                        });
                        _filterAccounts();
                      },
                    ),
                  ],
                ),
              ),
              if (_activeFiltersCount > 0)
                TextButton.icon(
                  onPressed: () {
                    _searchController.clear();
                    setState(() {
                      _onlyDetailAccounts = false;
                      _onlyWithBalance = false;
                      _onlyWeightAccounts = false;
                      _sortBy = 'number';
                      _sortAscending = true;
                    });
                    _filterAccounts();
                  },
                  icon: const Icon(Icons.close, size: 16),
                  label: const Text('مسح الفلاتر'),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              SizedBox(
                width: 420,
                child: TextField(
                  controller: _searchController,
                  decoration: InputDecoration(
                    hintText:
                        'ابحث بالاسم أو رقم الحساب أو النوع أو الحساب الرئيسي',
                    prefixIcon: const Icon(Icons.search, size: 18),
                    suffixIcon: _searchController.text.trim().isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.close, size: 18),
                            onPressed: () {
                              _searchController.clear();
                              _filterAccounts();
                            },
                          ),
                  ),
                ),
              ),
              SizedBox(
                width: 170,
                child: DropdownButtonFormField<String>(
                  value: _sortBy,
                  decoration: const InputDecoration(
                    labelText: 'الترتيب',
                    isDense: true,
                  ),
                  items: const [
                    DropdownMenuItem(
                      value: 'number',
                      child: Text('رقم الحساب'),
                    ),
                    DropdownMenuItem(value: 'name', child: Text('الاسم')),
                    DropdownMenuItem(value: 'type', child: Text('التصنيف')),
                    DropdownMenuItem(
                      value: 'cash',
                      child: Text('الرصيد النقدي'),
                    ),
                    DropdownMenuItem(
                      value: 'gold',
                      child: Text('الرصيد الذهبي'),
                    ),
                    DropdownMenuItem(
                      value: 'children',
                      child: Text('عدد الأبناء'),
                    ),
                  ],
                  onChanged: (value) {
                    if (value == null) return;
                    setState(() {
                      _sortBy = value;
                    });
                    _filterAccounts();
                  },
                ),
              ),
              OutlinedButton.icon(
                onPressed: () {
                  setState(() {
                    _sortAscending = !_sortAscending;
                  });
                  _filterAccounts();
                },
                icon: Icon(
                  _sortAscending ? Icons.arrow_upward : Icons.arrow_downward,
                  size: 18,
                ),
                label: Text(_sortAscending ? 'تصاعدي' : 'تنازلي'),
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
                decoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainerHighest.withValues(
                    alpha: 0.55,
                  ),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  'النتائج: ${_filteredAccounts.length}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildBalanceTile({
    required IconData icon,
    required String label,
    required String value,
    required Color color,
  }) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: theme.textTheme.bodySmall),
                Text(
                  value,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                    color: color,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAccountCard(Map<String, dynamic> account) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final cashBalance = _cashBalanceOf(account);
    final goldBalance = _goldBalanceOf(account);
    final hasChildren = _hasChildren(account);
    final accountNumber = _accountNumber(account);

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => _openStatement(account),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 44,
                    height: 44,
                    decoration: BoxDecoration(
                      color: colorScheme.primary.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Icon(
                      _tracksWeight(account)
                          ? Icons.scale_outlined
                          : Icons.account_balance_wallet_outlined,
                      color: colorScheme.primary,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          (account['name'] ?? 'N/A').toString(),
                          style: theme.textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          accountNumber.isEmpty
                              ? _accountTypeLabel(account)
                              : '$accountNumber • ${_accountTypeLabel(account)}',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: colorScheme.onSurface.withValues(
                              alpha: 0.65,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  PopupMenuButton<String>(
                    tooltip: 'الإجراءات',
                    onSelected: (value) {
                      if (value == 'statement') {
                        _openStatement(account);
                      } else if (value == 'ledger') {
                        _openLedger(account);
                      } else if (value == 'copy') {
                        _copyAccountNumber(account);
                      }
                    },
                    itemBuilder: (context) => const [
                      PopupMenuItem(
                        value: 'statement',
                        child: Text('كشف الحساب'),
                      ),
                      PopupMenuItem(
                        value: 'ledger',
                        child: Text('دفتر الأستاذ'),
                      ),
                      PopupMenuItem(
                        value: 'copy',
                        child: Text('نسخ رقم الحساب'),
                      ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  if (_tracksWeight(account))
                    Chip(
                      avatar: const Icon(Icons.scale_outlined, size: 16),
                      label: const Text('وزني'),
                    ),
                  Chip(
                    avatar: Icon(
                      hasChildren
                          ? Icons.account_tree_outlined
                          : Icons.subdirectory_arrow_left_outlined,
                      size: 16,
                    ),
                    label: Text(hasChildren ? 'رئيسي' : 'فرعي'),
                  ),
                  if (hasChildren)
                    Chip(
                      avatar: const Icon(Icons.layers_outlined, size: 16),
                      label: Text(
                        'أبناء: ${((account['sub_accounts'] as List?) ?? const []).length}',
                      ),
                    ),
                  Chip(
                    avatar: const Icon(Icons.link_outlined, size: 16),
                    label: Text(_parentLabel(account)),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: _buildBalanceTile(
                      icon: Icons.payments_outlined,
                      label: 'الرصيد النقدي',
                      value:
                          '${_cashFormat.format(cashBalance)} ${context.read<SettingsProvider>().currencySymbolText}',
                      color: Colors.green,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: _buildBalanceTile(
                      icon: Icons.auto_awesome_outlined,
                      label: 'الرصيد الذهبي',
                      value: '${_goldFormat.format(goldBalance)} جم',
                      color: const Color(0xFFD4A017),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: () => _openStatement(account),
                      icon: const Icon(Icons.assessment_outlined, size: 18),
                      label: const Text('كشف الحساب'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => _openLedger(account),
                      icon: const Icon(Icons.menu_book_outlined, size: 18),
                      label: const Text('دفتر الأستاذ'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCompactRow(Map<String, dynamic> account) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final cashBalance = _cashBalanceOf(account);
    final goldBalance = _goldBalanceOf(account);

    return Material(
      color: colorScheme.surface,
      child: InkWell(
        onTap: () => _openStatement(account),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            border: Border(
              bottom: BorderSide(
                color: colorScheme.outline.withValues(alpha: 0.1),
              ),
            ),
          ),
          child: Row(
            children: [
              Expanded(
                flex: 4,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      (account['name'] ?? 'N/A').toString(),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodyLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '${_accountNumber(account)} • ${_accountTypeLabel(account)}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: colorScheme.onSurface.withValues(alpha: 0.6),
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                flex: 2,
                child: cu.SarAwareText(
                  '${_cashFormat.format(cashBalance)} ${context.read<SettingsProvider>().currencySymbolText}',
              isNewSar: context.read<SettingsProvider>().currencyIsNewSar,
                  textAlign: TextAlign.end,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: Colors.green.shade700,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 2,
                child: Text(
                  '${_goldFormat.format(goldBalance)} جم',
                  textAlign: TextAlign.end,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: const Color(0xFFD4A017),
                  ),
                ),
              ),
              const SizedBox(width: 12),
              PopupMenuButton<String>(
                onSelected: (value) {
                  if (value == 'statement') {
                    _openStatement(account);
                  } else if (value == 'ledger') {
                    _openLedger(account);
                  } else if (value == 'copy') {
                    _copyAccountNumber(account);
                  }
                },
                itemBuilder: (context) => const [
                  PopupMenuItem(value: 'statement', child: Text('كشف الحساب')),
                  PopupMenuItem(value: 'ledger', child: Text('دفتر الأستاذ')),
                  PopupMenuItem(value: 'copy', child: Text('نسخ رقم الحساب')),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(
            Icons.account_balance_wallet_outlined,
            size: 64,
            color: theme.colorScheme.primary.withValues(alpha: 0.35),
          ),
          const SizedBox(height: 16),
          Text(
            _activeFiltersCount > 0
                ? 'لا توجد حسابات مطابقة'
                : 'لا توجد حسابات للعرض',
            style: theme.textTheme.titleMedium?.copyWith(
              color: theme.colorScheme.onSurface.withValues(alpha: 0.7),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'جرّب تعديل البحث أو إزالة بعض الفلاتر الحالية',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurface.withValues(alpha: 0.55),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null && _filteredAccounts.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                'تعذر تحميل الحسابات',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Text(_error!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: _fetchAccounts,
                icon: const Icon(Icons.refresh),
                label: const Text('إعادة المحاولة'),
              ),
            ],
          ),
        ),
      );
    }

    if (_filteredAccounts.isEmpty) {
      return _buildEmptyState();
    }

    if (_viewMode == _AccountsViewMode.compact) {
      return RefreshIndicator(
        onRefresh: _fetchAccounts,
        child: ListView(
          controller: _scrollController,
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
          children: [
            Container(
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surface,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(
                  color: Theme.of(
                    context,
                  ).colorScheme.outline.withValues(alpha: 0.12),
                ),
              ),
              child: Column(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 14,
                      vertical: 12,
                    ),
                    decoration: BoxDecoration(
                      color: Theme.of(context)
                          .colorScheme
                          .surfaceContainerHighest
                          .withValues(alpha: 0.45),
                      borderRadius: const BorderRadius.vertical(
                        top: Radius.circular(16),
                      ),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          flex: 4,
                          child: Text(
                            'الحساب',
                            style: Theme.of(context).textTheme.bodySmall
                                ?.copyWith(fontWeight: FontWeight.w800),
                          ),
                        ),
                        Expanded(
                          flex: 2,
                          child: Text(
                            'نقد',
                            textAlign: TextAlign.end,
                            style: Theme.of(context).textTheme.bodySmall
                                ?.copyWith(fontWeight: FontWeight.w800),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          flex: 2,
                          child: Text(
                            'ذهب',
                            textAlign: TextAlign.end,
                            style: Theme.of(context).textTheme.bodySmall
                                ?.copyWith(fontWeight: FontWeight.w800),
                          ),
                        ),
                        const SizedBox(width: 44),
                      ],
                    ),
                  ),
                  ..._filteredAccounts.map(_buildCompactRow),
                ],
              ),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _fetchAccounts,
      child: ListView.builder(
        controller: _scrollController,
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
        itemCount: _filteredAccounts.length,
        itemBuilder: (context, index) =>
            _buildAccountCard(_filteredAccounts[index]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    context.watch<SettingsProvider>();

    return Scaffold(
      appBar: AppBar(
        title: const Text('كشوفات الحسابات'),
        actions: [
          IconButton(
            tooltip: _viewMode == _AccountsViewMode.cards
                ? 'عرض مضغوط'
                : 'عرض البطاقات',
            icon: Icon(
              _viewMode == _AccountsViewMode.cards
                  ? Icons.table_rows_outlined
                  : Icons.view_agenda_outlined,
            ),
            onPressed: () {
              setState(() {
                _viewMode = _viewMode == _AccountsViewMode.cards
                    ? _AccountsViewMode.compact
                    : _AccountsViewMode.cards;
              });
            },
          ),
          IconButton(
            tooltip: 'تحديث',
            icon: const Icon(Icons.refresh),
            onPressed: _fetchAccounts,
          ),
        ],
      ),
      body: Column(
        children: [
          _buildCollapsibleTopChrome(),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: _buildManagementToolbar(),
          ),
          Expanded(child: _buildBody()),
        ],
      ),
    );
  }
}
