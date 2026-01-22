#!/usr/bin/env python3
"""
إضافة حقل karat (العيار) إلى جدول Category
"""
from app import app, db
from sqlalchemy import text

def add_category_karat_column():
    """إضافة حقل karat في جدول category"""
    with app.app_context():
        try:
            # التحقق من وجود العمود
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('category')]
            
            if 'karat' in columns:
                print('✅ عمود karat موجود بالفعل في جدول category')
                return
            
            # إضافة العمود
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE category ADD COLUMN karat VARCHAR(10)'))
                conn.commit()
            
            print('✅ تمت إضافة عمود karat إلى جدول category بنجاح')
            
        except Exception as e:
            print(f'❌ خطأ أثناء إضافة العمود: {e}')
            raise

if __name__ == '__main__':
    add_category_karat_column()
