"""
Revert: swap symbol-then-amount → amount-then-symbol in all active Flutter Dart files.
The correct Arabic convention is: ${amount} ${symbol}  (amount FIRST, then symbol).
"""

import re
import glob

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

AMOUNT_RE = r'(\$\{[^{}]+\})'
PER_UNIT = r'(?!\s*/(?:جم|g\b|جرام|غ\b))'

total_changes = 0
changed_files = []

files = glob.glob('frontend/lib/**/*.dart', recursive=True)
files = [f for f in files if '_archived' not in f and '.backup.' not in f]

for sym_pattern_str in SYMBOL_EXPRS:
    # Match: ${SYMBOL} ${AMOUNT}  (not followed by /جم etc.)
    pattern = re.compile(
        r'(' + sym_pattern_str + r') ' +
        AMOUNT_RE +
        PER_UNIT
    )

    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue

        # Revert: symbol amount → amount symbol
        new_content, n = pattern.subn(lambda m: f'{m.group(2)} {m.group(1)}', content)

        if n > 0 and new_content != content:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            total_changes += n
            if fpath not in changed_files:
                changed_files.append(fpath)
            print(f'  {n:3d} reverts  {fpath}')

print(f'\nDone. {total_changes} total reverts across {len(changed_files)} files.')
