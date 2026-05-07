"""
Swap amount-then-symbol → symbol-then-amount in all active Flutter Dart files.
Skips price-per-unit suffixes like /جم, /g, /جرام, /غ.
"""

import re
import os
import glob

# Patterns for the currency symbol interpolation expressions
SYMBOL_EXPRS = [
    r'\$\{_settingsProvider\.currencySymbolText\}',
    r'\$\{context\.read<SettingsProvider>\(\)\.currencySymbolText\}',
    r'\$\{settingsProvider\.currencySymbolText\}',
    r'\$\{settings\.currencySymbolText\}',
    r"\$\{cu\.isNewSarSymbol\(_currencySymbol\) \? 'ر\.س' : _currencySymbol\}",
    r'\$\{_currencySymbol\}',
    r'\$\{currencySymbol\}',
    r'\$\{currency\}',
]

# Amount expression: any ${...toStringAsFixed(N)...} or ${amount_var}
AMOUNT_RE = r'(\$\{[^{}]+\})'

# per-unit suffix that should NOT be moved (leave price/gram as-is)
PER_UNIT = r'(?!\s*/(?:جم|g\b|جرام|غ\b))'

total_changes = 0
changed_files = []

files = glob.glob('frontend/lib/**/*.dart', recursive=True)
files = [f for f in files
         if '_archived' not in f
         and '.backup.' not in f]

for sym_pattern_str in SYMBOL_EXPRS:
    # Match: ${AMOUNT} ${SYMBOL}  (not followed by /جم etc.)
    pattern = re.compile(
        AMOUNT_RE +
        r' (' + sym_pattern_str + r')' +
        PER_UNIT
    )

    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue

        new_content, n = pattern.subn(lambda m: f'{m.group(2)} {m.group(1)}', content)

        if n > 0 and new_content != content:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            total_changes += n
            if fpath not in changed_files:
                changed_files.append(fpath)
            print(f'  {n:3d} swaps  {fpath}')

print(f'\nDone. {total_changes} total swaps across {len(changed_files)} files.')
print('\nChanged files:')
for f in changed_files:
    print(f'  {f}')
