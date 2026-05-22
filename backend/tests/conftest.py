# هذا الملف يُعرّف pytest على تهيئة الاختبارات
# الملفات e2e_* هي سكريبتات تُشغَّل مباشرة وليست اختبارات pytest
collect_ignore = [
    "e2e_direct_test.py",
    "e2e_invoice_test.py",
]
