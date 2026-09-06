import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

enum _AccountAction { statement, addChild, edit, delete }

final NumberFormat _cashFormat = NumberFormat('#,##0.00', 'ar');
final NumberFormat _goldFormat = NumberFormat('#,##0.###', 'ar');

// 1. AccountNode Class
class AccountNode {
  final Map<String, dynamic> account;
  List<AccountNode> children;

  AccountNode({required this.account, List<AccountNode>? children})
    : children = children ?? [];
}

int _accountNumberOrder(String n) {
  final s = n.replaceAll(RegExp(r'[^0-9]'), '');
  return s.isEmpty ? 0 : (int.tryParse(s) ?? 0);
}

// 2. buildAccountTree Function
List<AccountNode> buildAccountTree(List<dynamic> accounts) {
  final nodes = <int, AccountNode>{};
  final roots = <AccountNode>[];
  final allNodeIds = accounts.map<int>((acc) => acc['id'] as int).toSet();

  // Numeric sort so "2" < "11" < "100" instead of lexicographic "100" < "11" < "2".
  accounts.sort(
    (a, b) => _accountNumberOrder(a['account_number'] as String)
        .compareTo(_accountNumberOrder(b['account_number'] as String)),
  );

  for (var acc in accounts) {
    nodes[acc['id']] = AccountNode(account: acc);
  }

  for (var acc in accounts) {
    final parentId = acc['parent_id'];
    final node = nodes[acc['id']]!;

    if (parentId == null || !allNodeIds.contains(parentId)) {
      // Check if parentId is valid
      roots.add(node);
    } else {
      final parentNode = nodes[parentId];
      if (parentNode != null) {
        parentNode.children.add(node);
      } else {
        // This case should ideally not be reached due to the check above,
        // but as a fallback, add it to roots.
        roots.add(node);
      }
    }
  }
  return roots;
}

// 3. AccountTreeView Widget
class AccountTreeView extends StatelessWidget {
  final List<AccountNode> roots;
  final Map<int, Map<String, dynamic>> accountsById;
  final Function(Map<String, dynamic>) onEdit;
  final Function(int) onDelete;
  final Function(Map<String, dynamic>) onAddChild;
  final Function(Map<String, dynamic>) onAccountTap; // Add this

  const AccountTreeView({
    super.key,
    required this.roots,
    required this.accountsById,
    required this.onEdit,
    required this.onDelete,
    required this.onAddChild,
    required this.onAccountTap, // Add this
  });

  @override
  Widget build(BuildContext context) {
    return ListView.builder(
      itemCount: roots.length,
      itemBuilder: (context, index) {
        return AccountTile(
          node: roots[index],
          accountsById: accountsById,
          onEdit: onEdit,
          onDelete: onDelete,
          onAddChild: onAddChild,
          onAccountTap: onAccountTap, // Pass this down
        );
      },
    );
  }
}

class AccountTile extends StatelessWidget {
  final AccountNode node;
  final Map<int, Map<String, dynamic>> accountsById;
  final Function(Map<String, dynamic>) onEdit;
  final Function(int) onDelete;
  final Function(Map<String, dynamic>) onAddChild;
  final Function(Map<String, dynamic>) onAccountTap; // Add this

  const AccountTile({
    super.key,
    required this.node,
    required this.accountsById,
    required this.onEdit,
    required this.onDelete,
    required this.onAddChild,
    required this.onAccountTap, // Add this
  });

  @override
  Widget build(BuildContext context) {
    final account = node.account;
    final bool isLeaf = node.children.isEmpty;

    // Linked memo/weight account (Account.memo_account_id), shown as an
    // annotation (summary line + quick-jump icon) rather than relocated in
    // the tree -- the tree stays a faithful rendering of the real
    // parent_id structure. Only surfaced for leaf entities: category-level
    // nodes (e.g. root "2 - الخصوم" <-> root "72 - الخصوم وزني") also carry
    // memo_account_id but always show a zero balance of their own, so
    // there is nothing useful to annotate there.
    final memoId = account['memo_account_id'];
    final memoAccount = (isLeaf && memoId != null)
        ? accountsById[memoId]
        : null;
    // Tapping the ⚖️ below opens AccountStatementScreen for memoAccount's id.
    // The backend's get_account_statement may auto-return a merged cash+gold
    // statement (is_merged: true) for it instead of a weight-only view --
    // see the NOTE in routes.py's get_account_statement. Intentional.

    PopupMenuItem<_AccountAction> buildItem(
      _AccountAction action,
      String label,
      IconData icon, {
      Color? color,
    }) {
      return PopupMenuItem<_AccountAction>(
        value: action,
        child: Row(
          children: [
            Icon(icon, size: 18, color: color),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                label,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      );
    }

    final tileTitleRow = Row(
      children: [
        Expanded(
          child: Text(
            '${account['account_number']} - ${account['name']}',
            overflow: TextOverflow.ellipsis,
          ),
        ),
        if (memoAccount != null)
          Tooltip(
            message:
                'عرض كشف الحساب الوزني المرتبط: ${memoAccount['account_number']} - ${memoAccount['name']}',
            child: IconButton(
              icon: Icon(
                Icons.scale_outlined,
                size: 18,
                color: Theme.of(context).colorScheme.secondary,
              ),
              onPressed: () => onAccountTap(memoAccount),
            ),
          ),
        PopupMenuButton<_AccountAction>(
          tooltip: 'خيارات',
          onSelected: (action) {
            switch (action) {
              case _AccountAction.statement:
                onAccountTap(account);
                break;
              case _AccountAction.addChild:
                onAddChild(account);
                break;
              case _AccountAction.edit:
                onEdit(account);
                break;
              case _AccountAction.delete:
                onDelete(account['id']);
                break;
            }
          },
          itemBuilder: (context) => [
            buildItem(
              _AccountAction.statement,
              'عرض كشف الحساب',
              Icons.description_outlined,
              color: Theme.of(context).colorScheme.secondary,
            ),
            buildItem(
              _AccountAction.addChild,
              'إضافة حساب فرعي',
              Icons.add_circle_outline,
              color: Colors.green,
            ),
            buildItem(
              _AccountAction.edit,
              'تعديل الحساب',
              Icons.edit_outlined,
            ),
            buildItem(
              _AccountAction.delete,
              'حذف الحساب',
              Icons.delete_outline,
              color: Colors.redAccent,
            ),
          ],
          child: const Padding(
            padding: EdgeInsets.symmetric(horizontal: 4),
            child: Icon(Icons.more_vert, size: 20),
          ),
        ),
      ],
    );

    final tileTitle = GestureDetector(
      behavior: HitTestBehavior.opaque,
      onLongPress: () => onEdit(account),
      child: tileTitleRow,
    );

    Widget? tileSubtitle;
    if (memoAccount != null) {
      final cashValue =
          (account['balances']?['cash'] as num?)?.toDouble() ?? 0.0;
      final weightValue =
          (memoAccount['balances']?['weight']?['total'] as num?)
              ?.toDouble() ??
          0.0;
      tileSubtitle = Padding(
        padding: const EdgeInsets.only(top: 2),
        child: Text(
          'نقدي: ${_cashFormat.format(cashValue)}  |  وزني: ${_goldFormat.format(weightValue)} جم',
          style: TextStyle(
            fontSize: 12,
            color: Theme.of(context).colorScheme.outline,
          ),
        ),
      );
    }

    if (isLeaf) {
      // Still use ExpansionTile for a consistent look and to handle initially childless nodes
      // that might get children later, but the expand icon will be hidden automatically.
      return ExpansionTile(
        key: PageStorageKey(account['id']), // Preserve expansion state
        title: tileTitle,
        subtitle: tileSubtitle,
        children: const [], // No children to expand
      );
    }

    return ExpansionTile(
      key: PageStorageKey(account['id']), // Preserve expansion state
      title: tileTitle,
      children: node.children
          .map(
            (child) => AccountTile(
              node: child,
              accountsById: accountsById,
              onEdit: onEdit,
              onDelete: onDelete,
              onAddChild: onAddChild,
              onAccountTap: onAccountTap, // Pass this down
            ),
          )
          .toList(),
    );
  }
}
