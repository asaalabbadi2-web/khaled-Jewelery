import 'package:flutter/material.dart';
import '../models/account_node.dart';
import '../api_service.dart';

enum AccountSortOrder { number, name, balance }

class AccountsTreeProvider extends ChangeNotifier {
  List<AccountNode> _allRoots = [];
  Map<int, Map<String, dynamic>> _accountsById = {};

  bool _loading = false;
  String? _error;

  final Set<int> _expandedIds = {};
  AccountNode? _selectedNode;

  String _search = '';
  AccountSortOrder _sortOrder = AccountSortOrder.number;
  String _typeFilter = ''; // '' = all, 'asset', 'liability', etc.
  bool _showOnlyPostable = false;
  bool _showBalances = true;

  bool _cashSectionCollapsed = false;
  bool _goldSectionCollapsed = false;

  // ─── Getters ─────────────────────────────────────────────────────────────
  bool get loading => _loading;
  String? get error => _error;
  bool get showBalances => _showBalances;
  String get search => _search;
  AccountSortOrder get sortOrder => _sortOrder;
  String get typeFilter => _typeFilter;
  bool get showOnlyPostable => _showOnlyPostable;
  bool get cashSectionCollapsed => _cashSectionCollapsed;
  bool get goldSectionCollapsed => _goldSectionCollapsed;
  AccountNode? get selectedNode => _selectedNode;
  Map<int, Map<String, dynamic>> get accountsById => _accountsById;

  List<AccountNode> get cashRoots =>
      _allRoots.where((n) => !n.isGoldSection).toList();
  List<AccountNode> get goldRoots =>
      _allRoots.where((n) => n.isGoldSection).toList();

  int get totalCount => _countAll(_allRoots);
  int get visibleCount => _countAll(filteredRoots);

  List<AccountNode> get filteredRoots {
    if (_search.isEmpty && _typeFilter.isEmpty && !_showOnlyPostable) {
      return _allRoots;
    }
    return _allRoots
        .map(_filterNode)
        .where((n) => n != null)
        .cast<AccountNode>()
        .toList();
  }

  List<AccountNode> get filteredCashRoots =>
      filteredRoots.where((n) => !n.isGoldSection).toList();
  List<AccountNode> get filteredGoldRoots =>
      filteredRoots.where((n) => n.isGoldSection).toList();

  // ─── Load ─────────────────────────────────────────────────────────────────
  Future<void> load() async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      final raw = await ApiService().getAccounts();
      _accountsById = {
        for (final a in raw) a['id'] as int: Map<String, dynamic>.from(a),
      };
      _allRoots = buildAccountTree(raw);
      _expandedIds.clear();
      _error = null;
    } catch (e) {
      _error = e.toString();
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  // ─── Expansion ────────────────────────────────────────────────────────────
  bool isExpanded(int id) => _expandedIds.contains(id);

  void toggleExpand(int id) {
    if (_expandedIds.contains(id)) {
      _expandedIds.remove(id);
    } else {
      _expandedIds.add(id);
    }
    notifyListeners();
  }

  void expandAll() {
    _collectIds(_allRoots, _expandedIds);
    notifyListeners();
  }

  void collapseAll() {
    _expandedIds.clear();
    notifyListeners();
  }

  void expandTo(AccountNode target) {
    _expandPathTo(_allRoots, target, []);
    notifyListeners();
  }

  bool _expandPathTo(
      List<AccountNode> nodes, AccountNode target, List<int> path) {
    for (final n in nodes) {
      if (n.id == target.id) {
        for (final id in path) {
          _expandedIds.add(id);
        }
        return true;
      }
      if (_expandPathTo(n.children, target, [...path, n.id])) return true;
    }
    return false;
  }

  // ─── Selection ────────────────────────────────────────────────────────────
  void select(AccountNode? node) {
    _selectedNode = node;
    notifyListeners();
  }

  // ─── Filters & sort ───────────────────────────────────────────────────────
  void setSearch(String q) {
    _search = q.trim();
    if (_search.isNotEmpty) expandAll();
    notifyListeners();
  }

  void setTypeFilter(String t) {
    _typeFilter = t;
    notifyListeners();
  }

  void setSortOrder(AccountSortOrder o) {
    _sortOrder = o;
    _applySortInPlace(_allRoots);
    notifyListeners();
  }

  void togglePostableOnly() {
    _showOnlyPostable = !_showOnlyPostable;
    notifyListeners();
  }

  void toggleBalances() {
    _showBalances = !_showBalances;
    notifyListeners();
  }

  void toggleCashSection() {
    _cashSectionCollapsed = !_cashSectionCollapsed;
    notifyListeners();
  }

  void toggleGoldSection() {
    _goldSectionCollapsed = !_goldSectionCollapsed;
    notifyListeners();
  }

  // ─── Helpers ──────────────────────────────────────────────────────────────
  AccountNode? findById(int id) => _findIn(_allRoots, id);

  AccountNode? _findIn(List<AccountNode> nodes, int id) {
    for (final n in nodes) {
      if (n.id == id) return n;
      final found = _findIn(n.children, id);
      if (found != null) return found;
    }
    return null;
  }

  int _countAll(List<AccountNode> nodes) {
    return nodes.fold(0, (s, n) => s + 1 + _countAll(n.children));
  }

  void _collectIds(List<AccountNode> nodes, Set<int> ids) {
    for (final n in nodes) {
      if (n.children.isNotEmpty) {
        ids.add(n.id);
        _collectIds(n.children, ids);
      }
    }
  }

  void _applySortInPlace(List<AccountNode> nodes) {
    nodes.sort((a, b) {
      switch (_sortOrder) {
        case AccountSortOrder.number:
          return _numOrder(a.number).compareTo(_numOrder(b.number));
        case AccountSortOrder.name:
          return a.name.compareTo(b.name);
        case AccountSortOrder.balance:
          return b.rolledUpCash.abs().compareTo(a.rolledUpCash.abs());
      }
    });
    for (final n in nodes) {
      _applySortInPlace(n.children);
    }
  }

  int _numOrder(String s) {
    final d = s.replaceAll(RegExp(r'[^0-9]'), '');
    return d.isEmpty ? 0 : (int.tryParse(d) ?? 0);
  }

  AccountNode? _filterNode(AccountNode node) {
    final matchesSelf = _matchesFilter(node);
    final filteredChildren = node.children
        .map(_filterNode)
        .where((c) => c != null)
        .cast<AccountNode>()
        .toList();

    if (!matchesSelf && filteredChildren.isEmpty) return null;

    return AccountNode(account: node.account, children: filteredChildren)
      ..rolledUpCash = node.rolledUpCash
      ..rolledUpWeightTotal = node.rolledUpWeightTotal
      ..dominantKarat = node.dominantKarat;
  }

  bool _matchesFilter(AccountNode n) {
    if (_showOnlyPostable && !n.isPostable) return false;
    if (_typeFilter.isNotEmpty && n.type != _typeFilter) return false;
    if (_search.isEmpty) return true;
    return n.name.contains(_search) || n.number.contains(_search);
  }
}
