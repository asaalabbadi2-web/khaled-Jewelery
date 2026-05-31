#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
إضافة قيد فريد جزئي على office_reservation.purchase_invoice_id
يمنع ربط نفس الفاتورة بأكثر من حجز واحد (يحمي من التسوية المزدوجة).
NULLs مسموح بها (حجوزات لم تُسوَّى بعد).
"""

from app import app, db

print("=" * 60)
print("إضافة قيد UNIQUE على office_reservation.purchase_invoice_id")
print("=" * 60)

INDEX_NAME = 'uq_office_reservation_purchase_invoice_id'

with app.app_context():
    try:
        with db.engine.connect() as conn:
            # التحقق من وجود الفهرس مسبقاً
            exists = conn.execute(db.text(
                "SELECT 1 FROM pg_indexes WHERE indexname = :name"
            ), {'name': INDEX_NAME}).fetchone()

            if exists:
                print(f"\n✅ الفهرس '{INDEX_NAME}' موجود بالفعل")
            else:
                print(f"\n⏳ إنشاء الفهرس الفريد...")
                conn.execute(db.text(f"""
                    CREATE UNIQUE INDEX {INDEX_NAME}
                    ON office_reservation (purchase_invoice_id)
                    WHERE purchase_invoice_id IS NOT NULL
                """))
                conn.commit()
                print(f"✅ تم إنشاء الفهرس بنجاح")

        print("\n" + "=" * 60)
        print("✅ الآن كل فاتورة لا يمكن ربطها بأكثر من حجز واحد")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ خطأ: {e}")
