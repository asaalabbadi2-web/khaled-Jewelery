import 'package:flutter/material.dart';

class PartyPickerDialog extends StatefulWidget {
  final String title;
  final List<Map<String, dynamic>> items;
  final int? selectedId;
  final String emptyText;

  const PartyPickerDialog({
    super.key,
    required this.title,
    required this.items,
    this.selectedId,
    this.emptyText = 'لا توجد بيانات',
  });

  @override
  State<PartyPickerDialog> createState() => _PartyPickerDialogState();
}

class _PartyPickerDialogState extends State<PartyPickerDialog> {
  final TextEditingController _searchController = TextEditingController();
  String _query = '';

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  int? _toInt(dynamic v) {
    if (v == null) return null;
    if (v is int) return v;
    if (v is num) return v.toInt();
    return int.tryParse(v.toString());
  }

  String _asString(dynamic v) => (v ?? '').toString().trim();

  String _phoneOf(Map<String, dynamic> item) {
    return _asString(
      item['phone'] ??
          item['phone_number'] ??
          item['customer_phone'] ??
          item['supplier_phone'],
    );
  }

  String _mobileOf(Map<String, dynamic> item) {
    return _asString(item['mobile'] ?? item['mobile_number']);
  }

  List<Map<String, dynamic>> _filtered() {
    final q = _query.trim().toLowerCase();
    Iterable<Map<String, dynamic>> items = widget.items;

    if (q.isNotEmpty) {
      items = items.where((m) {
        final name = _asString(m['name']).toLowerCase();
        final phone = _phoneOf(m).toLowerCase();
        final mobile = _mobileOf(m).toLowerCase();
        final idNo = _asString(m['identity_number']).toLowerCase();
        final code = _asString(m['code']).toLowerCase();
        return name.contains(q) ||
            phone.contains(q) ||
            mobile.contains(q) ||
            idNo.contains(q) ||
            code.contains(q);
      });
    }

    final list = items.toList();
    list.sort((a, b) {
      final an = _asString(a['name']);
      final bn = _asString(b['name']);
      return an.compareTo(bn);
    });
    return list;
  }

  String _subtitle(Map<String, dynamic> item) {
    final phone = _phoneOf(item);
    final mobile = _mobileOf(item);
    final parts = <String>[];
    if (phone.isNotEmpty) parts.add(phone);
    if (mobile.isNotEmpty && mobile != phone) parts.add(mobile);
    return parts.join(' • ');
  }

  @override
  Widget build(BuildContext context) {
    final filtered = _filtered();
    final theme = Theme.of(context);

    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 520,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _searchController,
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: 'ابحث بالاسم / الجوال / الهاتف',
                suffixIcon: _query.trim().isEmpty
                    ? null
                    : IconButton(
                        onPressed: () {
                          setState(() {
                            _query = '';
                            _searchController.clear();
                          });
                        },
                        icon: const Icon(Icons.close),
                        tooltip: 'مسح',
                      ),
                border: const OutlineInputBorder(),
              ),
              onChanged: (v) => setState(() => _query = v),
            ),
            const SizedBox(height: 10),
            if (filtered.isEmpty)
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  widget.emptyText,
                  style: TextStyle(color: Colors.grey.shade600),
                ),
              )
            else
              Flexible(
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: filtered.length,
                  separatorBuilder: (context, index) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final item = filtered[index];
                    final id = _toInt(item['id']);
                    final name = _asString(item['name']);
                    final selected = (id != null && id == widget.selectedId);
                    final subtitle = _subtitle(item);

                    return ListTile(
                      leading: CircleAvatar(
                        backgroundColor: selected
                            ? theme.colorScheme.primary.withValues(alpha: 0.15)
                            : Colors.grey.shade200,
                        child: Icon(
                          Icons.person_outline,
                          color: selected
                              ? theme.colorScheme.primary
                              : Colors.grey.shade700,
                        ),
                      ),
                      title: Text(name.isEmpty ? 'بدون اسم' : name),
                      subtitle: subtitle.isEmpty ? null : Text(subtitle),
                      trailing: selected
                          ? Icon(
                              Icons.check_circle,
                              color: theme.colorScheme.primary,
                            )
                          : null,
                      onTap: () => Navigator.pop(context, item),
                    );
                  },
                ),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('إلغاء'),
        ),
      ],
    );
  }
}
