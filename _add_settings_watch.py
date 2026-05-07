"""
Add context.watch<SettingsProvider>() to the first Widget build() in each
screen that uses currencySymbolText/_currencySymbol but lacks a reactive
SettingsProvider subscription.
"""
import re
import glob
import os

# Screens that already have Provider.of<SettingsProvider>(context) or
# context.watch — skip them
SKIP = {
    'initial_setup_screen.dart',  # sets the symbol, no display
    'settings_screen_enhanced.dart',  # already handled
}

WATCH_LINE = '    context.watch<SettingsProvider>();\n'

# Pattern: the first `Widget build(BuildContext context) {`
BUILD_RE = re.compile(
    r'(\s*@override\s*\n\s*Widget build\(BuildContext context\)\s*\{)',
)

files = sorted(glob.glob('frontend/lib/screens/**/*.dart', recursive=True) +
               glob.glob('frontend/lib/screens/*.dart'))
files = [f for f in files if '_archived' not in f and '.backup.' not in f]

changed = 0
for fpath in files:
    basename = os.path.basename(fpath)
    if basename in SKIP:
        continue

    with open(fpath, encoding='utf-8') as f:
        content = f.read()

    # Only process files that use currencySymbolText or _currencySymbol
    if 'currencySymbolText' not in content and '_currencySymbol' not in content:
        continue

    # Skip if already has context.watch<SettingsProvider>
    if 'context.watch<SettingsProvider>()' in content:
        continue

    # Skip if already has Provider.of<SettingsProvider>(context) without listen:false
    # (meaning it already listens)
    pof_matches = re.findall(
        r'Provider\.of<SettingsProvider>\(context(?:,\s*listen:\s*(true|false))?\)',
        content,
    )
    has_listen_true = any(m in ('', 'true') for m in pof_matches)
    if has_listen_true:
        print(f'  SKIP (already listens via Provider.of): {fpath}')
        continue

    # Find the FIRST Widget build(BuildContext context) {
    match = BUILD_RE.search(content)
    if not match:
        print(f'  SKIP (no build() found): {fpath}')
        continue

    # Insert watch line RIGHT after the opening { of that build method
    insert_pos = match.end()
    # Peek ahead: skip blank lines / existing declarations to insert at position 0
    new_content = content[:insert_pos] + '\n' + WATCH_LINE + content[insert_pos:]

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    changed += 1
    print(f'  ✓ {fpath}')

print(f'\nDone. {changed} files updated.')
