import 'package:flutter/material.dart';

enum _AccountAction { statement, addChild, edit, delete }

// 1. AccountNode Class
class AccountNode {
  final Map<String, dynamic> account;
  List<AccountNode> children;

  AccountNode({required this.account, List<AccountNode>? children})
    : children = children ?? [];
}

// 2. buildAccountTree Function
List<AccountNode> buildAccountTree(List<dynamic> accounts) {
  final nodes = <int, AccountNode>{};
  final roots = <AccountNode>[];
  final allNodeIds = accounts.map<int>((acc) => acc['id'] as int).toSet();

  // Sort accounts by account_number to ensure correct child order
  accounts.sort(
    (a, b) => (a['account_number'] as String).compareTo(
      b['account_number'] as String,
    ),
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
  final Function(Map<String, dynamic>) onEdit;
  final Function(int) onDelete;
  final Function(Map<String, dynamic>) onAddChild;
  final Function(Map<String, dynamic>) onAccountTap; // Add this

  const AccountTreeView({
    super.key,
    required this.roots,
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
  final Function(Map<String, dynamic>) onEdit;
  final Function(int) onDelete;
  final Function(Map<String, dynamic>) onAddChild;
  final Function(Map<String, dynamic>) onAccountTap; // Add this

  const AccountTile({
    super.key,
    required this.node,
    required this.onEdit,
    required this.onDelete,
    required this.onAddChild,
    required this.onAccountTap, // Add this
  });

  @override
  Widget build(BuildContext context) {
    final account = node.account;
    final bool isLeaf = node.children.isEmpty;

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

    if (isLeaf) {
      // Still use ExpansionTile for a consistent look and to handle initially childless nodes
      // that might get children later, but the expand icon will be hidden automatically.
      return ExpansionTile(
        key: PageStorageKey(account['id']), // Preserve expansion state
        title: tileTitle,
        children: [], // No children to expand
      );
    }

    return ExpansionTile(
      key: PageStorageKey(account['id']), // Preserve expansion state
      title: tileTitle,
      children: node.children
          .map(
            (child) => AccountTile(
              node: child,
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
