import 'package:flutter/material.dart';

class SearchablePickerField extends StatelessWidget {
  final String labelText;
  final String? valueText;
  final String? hintText;
  final String? helperText;
  final String? errorText;
  final IconData? prefixIcon;
  final VoidCallback? onTap;
  final bool enabled;

  const SearchablePickerField({
    super.key,
    required this.labelText,
    this.valueText,
    this.hintText,
    this.helperText,
    this.errorText,
    this.prefixIcon,
    this.onTap,
    this.enabled = true,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final effectiveValue = (valueText ?? '').trim();
    final displayText = effectiveValue.isNotEmpty
        ? effectiveValue
        : (hintText ?? 'اضغط للاختيار');

    return InkWell(
      onTap: enabled ? onTap : null,
      borderRadius: BorderRadius.circular(8),
      child: InputDecorator(
        decoration: InputDecoration(
          labelText: labelText,
          helperText: helperText,
          errorText: errorText,
          border: const OutlineInputBorder(),
          prefixIcon: prefixIcon == null ? null : Icon(prefixIcon),
          suffixIcon: Icon(
            Icons.manage_search,
            color: enabled
                ? theme.colorScheme.primary
                : theme.disabledColor,
          ),
        ),
        child: Text(
          displayText,
          style: effectiveValue.isNotEmpty
              ? theme.textTheme.bodyLarge
              : theme.textTheme.bodyLarge
                  ?.copyWith(color: theme.hintColor),
        ),
      ),
    );
  }
}
