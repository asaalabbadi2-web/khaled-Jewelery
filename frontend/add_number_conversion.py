#!/usr/bin/env python3
"""
Script to automatically add number conversion to all TextField and TextFormField widgets
in the Flutter project.
"""

import re
import os
from pathlib import Path

# النمط للعثور على TextFormField و TextField مع keyboardType رقمي
NUMERIC_FIELD_PATTERN = re.compile(
    r'(TextFormField|TextField)\s*\(\s*.*?keyboardType\s*:\s*.*?number.*?\)',
    re.DOTALL | re.MULTILINE
)

def has_input_formatters(field_text):
    """Check if the field already has inputFormatters"""
    return 'inputFormatters' in field_text

def has_number_formatter(field_text):
    """Check if the field already has ArabicNumberTextInputFormatter"""
    return 'ArabicNumberTextInputFormatter' in field_text or 'UniversalNumberTextInputFormatter' in field_text

def add_import_if_missing(content):
    """Add the import statement if not present"""
    import_line = "import '../utils/arabic_number_formatter.dart';"
    
    if import_line in content or 'arabic_number_formatter.dart' in content:
        return content
    
    # Find the last import statement
    import_pattern = re.compile(r'^import\s+.*?;', re.MULTILINE)
    imports = list(import_pattern.finditer(content))
    
    if imports:
        last_import = imports[-1]
        insert_pos = last_import.end()
        return content[:insert_pos] + '\n' + import_line + content[insert_pos:]
    
    return import_line + '\n' + content

def process_file(file_path):
    """Process a single Dart file"""
    print(f"Processing: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if file needs processing
    if not ('TextField' in content or 'TextFormField' in content):
        print(f"  ⏭️  Skipped (no text fields)")
        return False
    
    if 'ArabicNumberTextInputFormatter' in content:
        print(f"  ✅ Already has formatter")
        return False
    
    # Count numeric fields
    numeric_fields = 0
    lines = content.split('\n')
    modified = False
    
    for i, line in enumerate(lines):
        # Look for keyboardType with number
        if 'keyboardType' in line and 'number' in line.lower():
            # Check if next lines have inputFormatters
            check_range = min(i + 10, len(lines))
            has_formatters = any('inputFormatters' in lines[j] for j in range(i, check_range))
            
            if not has_formatters:
                numeric_fields += 1
    
    if numeric_fields > 0:
        print(f"  📝 Found {numeric_fields} numeric fields that need formatting")
        modified = True
    
    if modified:
        # Add import
        content = add_import_if_missing(content)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"  ✅ Added import statement")
        return True
    
    print(f"  ℹ️  No changes needed")
    return False

def main():
    """Main function"""
    frontend_dir = Path('/Users/salehalabbadi/yasargold/frontend')
    screens_dir = frontend_dir / 'lib' / 'screens'
    widgets_dir = frontend_dir / 'lib' / 'widgets'
    
    dart_files = []
    
    # Collect all Dart files
    for dir_path in [screens_dir, widgets_dir]:
        if dir_path.exists():
            dart_files.extend(dir_path.rglob('*.dart'))
    
    print(f"\n🔍 Found {len(dart_files)} Dart files\n")
    
    modified_count = 0
    
    for dart_file in sorted(dart_files):
        if process_file(dart_file):
            modified_count += 1
    
    print(f"\n✅ Summary:")
    print(f"   Total files: {len(dart_files)}")
    print(f"   Modified: {modified_count}")
    print(f"   Unchanged: {len(dart_files) - modified_count}")
    
    print(f"\n📋 Next steps:")
    print(f"   1. Review the changes")
    print(f"   2. Manually add inputFormatters to numeric fields")
    print(f"   3. Run: flutter analyze")
    print(f"   4. Run: flutter test")

if __name__ == '__main__':
    main()
