class AccountNode {
  final Map<String, dynamic> account;
  List<AccountNode> children;

  // Rolled-up balances (computed after tree build)
  double rolledUpCash = 0;
  double rolledUpWeightTotal = 0;
  int dominantKarat = 0;

  AccountNode({required this.account, List<AccountNode>? children})
      : children = children ?? [];

  int get id => account['id'] as int;
  String get number => account['account_number'] as String? ?? '';
  String get name => account['name'] as String? ?? '';
  String get type => account['type'] as String? ?? '';
  bool get tracksWeight => account['tracks_weight'] == true;
  bool get isGoldSection => number.startsWith('7');
  bool get isPostable => children.isEmpty;
  bool get isParent => children.isNotEmpty;
  int? get memoAccountId => account['memo_account_id'] as int?;
  int? get parentId => account['parent_id'] as int?;

  double get ownCash =>
      (account['balances']?['cash'] as num?)?.toDouble() ?? 0.0;

  double get ownWeightTotal =>
      (account['balances']?['weight']?['total'] as num?)?.toDouble() ?? 0.0;

  Map<String, double> get ownWeightByKarat {
    final w = account['balances']?['weight'] as Map<String, dynamic>?;
    if (w == null) return {};
    return {
      for (final e in w.entries)
        if (e.key != 'total') e.key: (e.value as num?)?.toDouble() ?? 0.0,
    };
  }
}

int _numericOrder(String n) {
  final s = n.replaceAll(RegExp(r'[^0-9]'), '');
  return s.isEmpty ? 0 : (int.tryParse(s) ?? 0);
}

List<AccountNode> buildAccountTree(List<dynamic> accounts) {
  final nodes = <int, AccountNode>{};
  final roots = <AccountNode>[];
  final allIds = accounts.map<int>((a) => a['id'] as int).toSet();

  accounts.sort((a, b) =>
      _numericOrder(a['account_number'] as String)
          .compareTo(_numericOrder(b['account_number'] as String)));

  for (final acc in accounts) {
    nodes[acc['id'] as int] = AccountNode(account: acc);
  }

  for (final acc in accounts) {
    final node = nodes[acc['id'] as int]!;
    final parentId = acc['parent_id'] as int?;
    if (parentId == null || !allIds.contains(parentId)) {
      roots.add(node);
    } else {
      nodes[parentId]?.children.add(node);
    }
  }

  for (final root in roots) {
    _rollUp(root);
  }

  return roots;
}

void _rollUp(AccountNode node) {
  for (final child in node.children) {
    _rollUp(child);
  }
  if (node.isPostable) {
    node.rolledUpCash = node.ownCash;
    node.rolledUpWeightTotal = node.ownWeightTotal;
    final byKarat = node.ownWeightByKarat;
    node.dominantKarat = byKarat.isEmpty
        ? 0
        : byKarat.entries
            .reduce((a, b) => a.value >= b.value ? a : b)
            .key
            .replaceAll('k', '')
            .let((s) => int.tryParse(s) ?? 0);
  } else {
    node.rolledUpCash =
        node.children.fold(0.0, (s, c) => s + c.rolledUpCash);
    node.rolledUpWeightTotal =
        node.children.fold(0.0, (s, c) => s + c.rolledUpWeightTotal);
    final allByKarat = <String, double>{};
    for (final c in node.children) {
      c.ownWeightByKarat.forEach((k, v) {
        allByKarat[k] = (allByKarat[k] ?? 0) + v;
      });
    }
    node.dominantKarat = allByKarat.isEmpty
        ? 0
        : allByKarat.entries
            .reduce((a, b) => a.value >= b.value ? a : b)
            .key
            .replaceAll('k', '')
            .let((s) => int.tryParse(s) ?? 0);
  }
}

extension _Let<T> on T {
  R let<R>(R Function(T) fn) => fn(this);
}
