-- ═══════════════════════════════════════════════════════════════════════════════
-- 🏦 نظام الشجرة المحاسبية المزدوجة (مالي + وزني)
-- ═══════════════════════════════════════════════════════════════════════════════
-- النظام: نقدي ← كل المبالغ تُسجل بالريال
--         وزني ← كل المبالغ تُحول إلى وزن (مبلغ ÷ سعر مباشر)
--         المخزون الوزني = وزن فعلي فقط
-- ═══════════════════════════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════════════════════════
-- 🟡 القسم الأول: الشجرة المالية (النقدية)
-- ═══════════════════════════════════════════════════════════════════════════════

-- ───────────────────────────────────────────────────────────────────────────────
-- 1 – الأصول
-- ───────────────────────────────────────────────────────────────────────────────

-- 1.1 الأصول المتداولة (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('11', 'الأصول المتداولة', 'Asset', 1, NULL, 0, 'cash');

-- 1.1.1 الصندوق
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('111', 'الصندوق', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '11'), 0, 'cash');

-- 1.1.2 البنك
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('112', 'البنك', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '11'), 0, 'cash');

-- 1.1.3 العملاء (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('113', 'العملاء', 'Asset', 1, 
    (SELECT id FROM account WHERE account_number = '11'), 0, 'cash');

-- 1.1.4 ذمم مكاتب التكسير (الديوان – نقدي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('114', 'ذمم مكاتب التكسير (نقدي)', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '11'), 0, 'cash');

-- 1.1.5 مخزون ذهب (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('115', 'مخزون ذهب', 'Asset', 1, 
    (SELECT id FROM account WHERE account_number = '11'), 0, 'cash');

-- 1.1.5.1 مخزون ذهب 24
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1151', 'مخزون ذهب عيار 24', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '115'), 0, 'cash');

-- 1.1.5.2 مخزون ذهب 22
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1152', 'مخزون ذهب عيار 22', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '115'), 0, 'cash');

-- 1.1.5.3 مخزون ذهب 21
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1153', 'مخزون ذهب عيار 21', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '115'), 0, 'cash');

-- 1.1.5.4 مخزون ذهب 18
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1154', 'مخزون ذهب عيار 18', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '115'), 0, 'cash');

-- 1.2 أصول أخرى (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('12', 'أصول أخرى', 'Asset', 1, NULL, 0, 'cash');

-- 1.2.1 دفعات مقدمة
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('121', 'دفعات مقدمة', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '12'), 0, 'cash');

-- 1.2.2 عهد
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('122', 'عهد', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '12'), 0, 'cash');

-- ───────────────────────────────────────────────────────────────────────────────
-- 2 – الالتزامات
-- ───────────────────────────────────────────────────────────────────────────────

-- 2.1 التزامات قصيرة الأجل (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('21', 'التزامات قصيرة الأجل', 'Liability', 1, NULL, 0, 'cash');

-- 2.1.1 الموردون
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('211', 'الموردون', 'Liability', 0, 
    (SELECT id FROM account WHERE account_number = '21'), 0, 'cash');

-- 2.1.2 مكاتب التكسير (الديوان – ذمم نقدية)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('212', 'مكاتب التكسير (ذمم نقدية)', 'Liability', 0, 
    (SELECT id FROM account WHERE account_number = '21'), 0, 'cash');

-- 2.1.3 رواتب مستحقة
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('213', 'رواتب مستحقة', 'Liability', 0, 
    (SELECT id FROM account WHERE account_number = '21'), 0, 'cash');

-- 2.1.4 مصاريف مستحقة
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('214', 'مصاريف مستحقة', 'Liability', 0, 
    (SELECT id FROM account WHERE account_number = '21'), 0, 'cash');

-- ───────────────────────────────────────────────────────────────────────────────
-- 3 – حقوق الملكية
-- ───────────────────────────────────────────────────────────────────────────────

-- 3.1 رأس المال
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('31', 'رأس المال', 'Equity', 0, NULL, 0, 'cash');

-- 3.2 أرباح وخسائر
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('32', 'أرباح وخسائر', 'Equity', 0, NULL, 0, 'cash');

-- 3.3 احتياطيات
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('33', 'احتياطيات', 'Equity', 0, NULL, 0, 'cash');

-- ───────────────────────────────────────────────────────────────────────────────
-- 4 – الإيرادات
-- ───────────────────────────────────────────────────────────────────────────────

-- 4 الإيرادات (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('40', 'الإيرادات', 'Revenue', 1, NULL, 0, 'cash');

-- 4.1 إيرادات بيع ذهب
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('401', 'إيرادات بيع ذهب', 'Revenue', 0, 
    (SELECT id FROM account WHERE account_number = '40'), 0, 'cash');

-- 4.2 إيرادات مصنعية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('402', 'إيرادات مصنعية', 'Revenue', 0, 
    (SELECT id FROM account WHERE account_number = '40'), 0, 'cash');

-- 4.3 إيرادات فرق تسكير الذهب
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('403', 'إيرادات فرق تسكير', 'Revenue', 0, 
    (SELECT id FROM account WHERE account_number = '40'), 0, 'cash');

-- 4.4 إيرادات تقييم وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('404', 'إيرادات تقييم وزني', 'Revenue', 0, 
    (SELECT id FROM account WHERE account_number = '40'), 0, 'cash');

-- ───────────────────────────────────────────────────────────────────────────────
-- 5 – المصروفات
-- ───────────────────────────────────────────────────────────────────────────────

-- 5 المصروفات (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('50', 'المصروفات', 'Expense', 1, NULL, 0, 'cash');

-- 5.1 تكلفة المبيعات
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('501', 'تكلفة المبيعات', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '50'), 0, 'cash');

-- 5.2 مصروفات تشغيل
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('502', 'مصروفات تشغيل', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '50'), 0, 'cash');

-- 5.3 رواتب
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('503', 'رواتب', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '50'), 0, 'cash');

-- 5.4 إيجارات
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('504', 'إيجارات', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '50'), 0, 'cash');

-- 5.5 كهرباء
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('505', 'كهرباء', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '50'), 0, 'cash');

-- 5.6 دعاية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('506', 'دعاية', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '50'), 0, 'cash');

-- 5.7 مصروفات وزن (اختياري)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('507', 'مصروفات وزن', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '50'), 0, 'cash');


-- ═══════════════════════════════════════════════════════════════════════════════
-- 🟣 القسم الثاني: الشجرة الوزنية (دفتر المذكرات الوزني)
-- ═══════════════════════════════════════════════════════════════════════════════

-- ───────────────────────────────────────────────────────────────────────────────
-- 1W – وزن الأصول
-- ───────────────────────────────────────────────────────────────────────────────

-- 1W.1 أصول وزنية (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W1', 'أصول وزنية', 'Asset', 1, NULL, 1, 'gold');

-- 1W.1.1 صندوق وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W11', 'صندوق وزني', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '1W1'), 1, 'gold');

-- 1W.1.2 بنك وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W12', 'بنك وزني', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '1W1'), 1, 'gold');

-- 1W.1.3 عملاء وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W13', 'عملاء وزني', 'Asset', 1, 
    (SELECT id FROM account WHERE account_number = '1W1'), 1, 'gold');

-- 1W.1.4 الديوان وزني (ذمم وزنية)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W14', 'الديوان وزني', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '1W1'), 1, 'gold');

-- 1W.2 مخزون وزني (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W2', 'مخزون وزني', 'Asset', 1, NULL, 1, 'gold');

-- 1W.2.1 مخزون ذهب فعلي 24
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W21', 'مخزون ذهب فعلي 24', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '1W2'), 1, 'gold');

-- 1W.2.2 مخزون ذهب فعلي 22
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W22', 'مخزون ذهب فعلي 22', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '1W2'), 1, 'gold');

-- 1W.2.3 مخزون ذهب فعلي 21
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W23', 'مخزون ذهب فعلي 21', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '1W2'), 1, 'gold');

-- 1W.2.4 مخزون ذهب فعلي 18
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('1W24', 'مخزون ذهب فعلي 18', 'Asset', 0, 
    (SELECT id FROM account WHERE account_number = '1W2'), 1, 'gold');

-- ───────────────────────────────────────────────────────────────────────────────
-- 2W – التزامات وزنية
-- ───────────────────────────────────────────────────────────────────────────────

-- 2W.1 التزامات وزنية (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('2W1', 'التزامات وزنية', 'Liability', 1, NULL, 1, 'gold');

-- 2W.1.1 موردون وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('2W11', 'موردون وزني', 'Liability', 0, 
    (SELECT id FROM account WHERE account_number = '2W1'), 1, 'gold');

-- 2W.1.2 رواتب مستحقة وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('2W12', 'رواتب مستحقة وزني', 'Liability', 0, 
    (SELECT id FROM account WHERE account_number = '2W1'), 1, 'gold');

-- 2W.1.3 مصاريف مستحقة وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('2W13', 'مصاريف مستحقة وزني', 'Liability', 0, 
    (SELECT id FROM account WHERE account_number = '2W1'), 1, 'gold');

-- ───────────────────────────────────────────────────────────────────────────────
-- 3W – حقوق ملكية وزنية
-- ───────────────────────────────────────────────────────────────────────────────

-- 3W حقوق ملكية وزنية (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('3W', 'حقوق ملكية وزنية', 'Equity', 1, NULL, 1, 'gold');

-- 3W.1 رأس مال وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('3W1', 'رأس مال وزني', 'Equity', 0, 
    (SELECT id FROM account WHERE account_number = '3W'), 1, 'gold');

-- 3W.2 أرباح / خسائر وزنية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('3W2', 'أرباح وخسائر وزنية', 'Equity', 0, 
    (SELECT id FROM account WHERE account_number = '3W'), 1, 'gold');

-- ───────────────────────────────────────────────────────────────────────────────
-- 4W – الإيرادات الوزنية
-- ───────────────────────────────────────────────────────────────────────────────

-- 4W الإيرادات الوزنية (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('4W', 'إيرادات وزنية', 'Revenue', 1, NULL, 1, 'gold');

-- 4W.1 إيرادات بيع وزنية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('4W1', 'إيرادات بيع وزنية', 'Revenue', 0, 
    (SELECT id FROM account WHERE account_number = '4W'), 1, 'gold');

-- 4W.2 إيرادات مصنعية وزنية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('4W2', 'إيرادات مصنعية وزنية', 'Revenue', 0, 
    (SELECT id FROM account WHERE account_number = '4W'), 1, 'gold');

-- 4W.3 إيرادات فرق تقييم وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('4W3', 'إيرادات فرق تقييم وزني', 'Revenue', 0, 
    (SELECT id FROM account WHERE account_number = '4W'), 1, 'gold');

-- 4W.4 إيرادات تسكير وزني
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('4W4', 'إيرادات تسكير وزني', 'Revenue', 0, 
    (SELECT id FROM account WHERE account_number = '4W'), 1, 'gold');

-- ───────────────────────────────────────────────────────────────────────────────
-- 5W – المصروفات الوزنية
-- ───────────────────────────────────────────────────────────────────────────────

-- 5W المصروفات الوزنية (رئيسي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('5W', 'مصروفات وزنية', 'Expense', 1, NULL, 1, 'gold');

-- 5W.1 تكلفة مبيعات وزنية (وزن فعلي)
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('5W1', 'تكلفة مبيعات وزنية', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '5W'), 1, 'gold');

-- 5W.2 مصروفات تشغيل وزنية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('5W2', 'مصروفات تشغيل وزنية', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '5W'), 1, 'gold');

-- 5W.3 رواتب وزنية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('5W3', 'رواتب وزنية', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '5W'), 1, 'gold');

-- 5W.4 إيجارات وزنية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('5W4', 'إيجارات وزنية', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '5W'), 1, 'gold');

-- 5W.5 كهرباء وزنية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('5W5', 'كهرباء وزنية', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '5W'), 1, 'gold');

-- 5W.6 دعاية وزنية
INSERT INTO account (account_number, name, type, is_parent, parent_id, tracks_weight, transaction_type)
VALUES ('5W6', 'دعاية وزنية', 'Expense', 0, 
    (SELECT id FROM account WHERE account_number = '5W'), 1, 'gold');


-- ═══════════════════════════════════════════════════════════════════════════════
-- ✅ الشجرة المزدوجة جاهزة الآن!
-- ═══════════════════════════════════════════════════════════════════════════════
-- استخدم هذا الملف لإنشاء الحسابات في قاعدة البيانات
-- 
-- كيفية التطبيق:
-- 1. احذف الحسابات القديمة (إن وجدت) أو نفذ هذا على قاعدة بيانات جديدة
-- 2. نفذ هذا الملف: sqlite3 app.db < dual_chart_of_accounts.sql
-- 3. تأكد من أن Routes تستخدم الحسابات الجديدة في القيود
-- ═══════════════════════════════════════════════════════════════════════════════
