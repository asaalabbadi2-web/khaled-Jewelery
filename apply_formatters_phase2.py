#!/usr/bin/env python3
"""
Continue adding NormalizeNumberFormatter to remaining files
"""

import re
from pathlib import Path

def process_file(file_path):
    """Add NormalizeNumberFormatter"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    result_lines = []
    modified = False
    i = 0
    
    while i < len(lines):
        line = lines[i]
        result_lines.append(line)
        
        if 'keyboardType' in line and 'number' in line.lower():
            has_formatters = False
            closing_found = False
            check_range = min(i + 15, len(lines))
            
            for k in range(i + 1, check_range):
                if 'inputFormatters' in lines[k]:
                    has_formatters = True
                    break
                if '),)' in lines[k] or '),' in lines[k] or ');' in lines[k]:
                    closing_found = True
                    break
            
            if not has_formatters and closing_found:
                indent = len(line) - len(line.lstrip())
                formatter_line = f"{' ' * indent}inputFormatters: [NormalizeNumberFormatter()],"
                result_lines.append(formatter_line)
                modified = True
                print(f"  ✅ Line {i+1}")
        
        i += 1
    
    if modified:
        new_content = '\n'.join(result_lines)
        
        if 'NormalizeNumberFormatter' in new_content and "import '../utils.dart'" not in new_content:
            import_pattern = re.compile(r"^import .*?;$", re.MULTILINE)
            imports = list(import_pattern.finditer(new_content))
            if imports:
                last_import = imports[-1]
                insert_pos = last_import.end()
                new_content = new_content[:insert_pos] + "\nimport '../utils.dart';" + new_content[insert_pos:]
                print(f"  📦 Added import")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return True
    
    return False

def main():
    frontend_dir = Path('/Users/salehalabbadi/yasargold/frontend')
    
    more_files = [
        'lib/screens/add_return_invoice_screen.dart',
        'lib/screens/melting_renewal_screen.dart',
        'lib/screens/purchase_invoice_screen.dart',
        'lib/screens/scrap_purchase_invoice_screen.dart',
        'lib/screens/scrap_sales_invoice_screen.dart',
        'lib/screens/settings_screen_enhanced.dart',
        'lib/screens/quick_add_items_screen.dart',
        'lib/screens/add_supplier_screen.dart',
        'lib/screens/add_customer_screen.dart',
    ]
    
    print("\n🔧 Phase 2: Adding formatters to more files...\n")
    
    modified_count = 0
    for file_rel_path in more_files:
        file_path = frontend_dir / file_rel_path
        if file_path.exists():
            print(f"📝 {file_rel_path.split('/')[-1]}")
            if process_file(file_path):
                modified_count += 1
            else:
                print(f"  ℹ️  No changes")
    
    print(f"\n✅ Phase 2 Complete: {modified_count}/{len(more_files)} files modified")

if __name__ == '__main__':
    main()
