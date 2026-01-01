#!/usr/bin/env python3
"""
Script to add NormalizeNumberFormatter to all numeric TextFields/TextFormFields
that don't already have inputFormatters.
"""

import re
import sys
from pathlib import Path

def process_file(file_path):
    """Add NormalizeNumberFormatter to numeric fields without inputFormatters"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    modified = False
    
    # Pattern to find TextField/TextFormField with keyboardType containing "number"
    # but WITHOUT inputFormatters
    lines = content.split('\n')
    result_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        result_lines.append(line)
        
        # Check if this line has keyboardType with number
        if 'keyboardType' in line and 'number' in line.lower():
            # Check next 5 lines for inputFormatters
            has_formatters = False
            closing_paren_found = False
            j = i + 1
            check_range = min(i + 15, len(lines))
            
            for k in range(j, check_range):
                if 'inputFormatters' in lines[k]:
                    has_formatters = True
                    break
                # Check if we've reached the end of this TextField
                if '),)' in lines[k] or '),' in lines[k]:
                    closing_paren_found = True
                    break
            
            # If no formatters found, add them
            if not has_formatters and closing_paren_found:
                # Find the indentation
                indent = len(line) - len(line.lstrip())
                indent_str = ' ' * indent
                
                # Insert inputFormatters after keyboardType line
                formatter_line = f"{indent_str}inputFormatters: [NormalizeNumberFormatter()],"
                result_lines.append(formatter_line)
                modified = True
                print(f"  ✅ Added formatter at line {i+1}")
        
        i += 1
    
    if modified:
        new_content = '\n'.join(result_lines)
        
        # Ensure utils.dart is imported
        if 'NormalizeNumberFormatter' in new_content and "import '../utils.dart'" not in new_content:
            # Find the last import
            import_pattern = re.compile(r"^import .*?;$", re.MULTILINE)
            imports = list(import_pattern.finditer(new_content))
            if imports:
                last_import = imports[-1]
                insert_pos = last_import.end()
                new_content = new_content[:insert_pos] + "\nimport '../utils.dart';" + new_content[insert_pos:]
                print(f"  📦 Added utils.dart import")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return True
    
    return False

def main():
    frontend_dir = Path('/Users/salehalabbadi/yasargold/frontend')
    
    # Target files from the grep output
    target_files = [
        'lib/screens/gold_price_manual_screen_enhanced.dart',
        'lib/screens/gold_reservation_screen.dart',
        'lib/screens/items_screen_enhanced.dart',
        'lib/screens/journal_entry_form.dart',
        'lib/screens/employees_screen.dart',
        'lib/screens/add_office_screen.dart',
        'lib/screens/add_voucher_screen.dart',
        'lib/screens/attendance_screen.dart',
        'lib/screens/barcode_print_screen.dart',
    ]
    
    print("\n🔧 Adding NormalizeNumberFormatter to numeric fields...\n")
    
    modified_count = 0
    for file_rel_path in target_files:
        file_path = frontend_dir / file_rel_path
        if file_path.exists():
            print(f"📝 Processing: {file_rel_path}")
            if process_file(file_path):
                modified_count += 1
            else:
                print(f"  ℹ️  No changes needed")
        else:
            print(f"  ⚠️  File not found: {file_rel_path}")
    
    print(f"\n✅ Summary:")
    print(f"   Files processed: {len(target_files)}")
    print(f"   Files modified: {modified_count}")
    print(f"\n📋 Next: Run 'flutter analyze' to check for issues")

if __name__ == '__main__':
    main()
