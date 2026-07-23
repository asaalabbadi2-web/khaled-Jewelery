-- seed/erp_seed.sql
-- Runs against postgres-erp AFTER the ERP service starts and calls db.create_all().
--
-- INVARIANT: item IDs here MUST match commerce_seed.sql exactly.
-- The ERP is the Single Writer for item stock; Commerce reads item identity
-- by ID.  A mismatch hides integration bugs that only appear under the claim-race
-- and Gate B availability check — exactly the paths we need to test locally.
--
-- Admin user is created separately by `make seed-admin` (Python via werkzeug hash)
-- because bcrypt hashes cannot be generated in pure SQL portably.

SET client_encoding = 'UTF8';

-- ── Settings (ERP requires exactly one row to boot correctly) ─────────────
INSERT INTO settings (id, main_karat, currency_symbol, tax_rate, tax_enabled,
                      company_name, decimal_places, date_format)
VALUES (1, 21, 'ر.س', 0.15, true, 'مجوهرات خالد', 2, 'DD/MM/YYYY')
ON CONFLICT (id) DO NOTHING;

-- ── Chart of accounts (minimum for double-entry bookkeeping at POS) ────────
-- IDs mirror conftest.py so that unit tests continue to pass against this seed.
INSERT INTO account
  (id, account_number, name, type, transaction_type, balance_cash)
VALUES
  (15,   '15',   'صندوق النقدية',                'Asset',   'cash', 50000.0),
  (400,  '400',  'مبيعات ذهب جديد',             'Revenue', 'gold',     0.0),
  (521,  '521',  'تكلفة مبيعات الذهب',           'Expense', 'gold',     0.0),
  (1200, '1200', 'مخزون ذهب عيار 24',            'Asset',   'gold',     0.0),
  (1220, '1220', 'مخزون ذهب عيار 21',            'Asset',   'gold',     0.0),
  (1300, '1300', 'مخزون ذهب معروض للبيع (موحد)','Asset',   'gold',     0.0),
  (1310, '1310', 'مخزون ذهب كسر (موحد)',         'Asset',   'gold',     0.0),
  (1610, '1610', 'خزينة مدى',                    'Asset',   'cash',     0.0)
ON CONFLICT (id) DO NOTHING;

-- ── Categories (must match commerce_seed.sql IDs) ─────────────────────────
INSERT INTO category (id, name, description, karat, created_at) VALUES
  (1, 'خواتم', 'خواتم ذهبية',  '21', NOW()),
  (2, 'أساور', 'أساور ذهبية',  '21', NOW()),
  (3, 'قلائد', 'قلائد ذهبية',  '18', NOW())
ON CONFLICT (id) DO NOTHING;

-- ── Items (must match commerce_seed.sql IDs exactly) ─────────────────────
INSERT INTO item
  (id, item_code, name, barcode, category_id, karat,
   weight, has_stones, stock, price, wage)
VALUES
  (101, 'I-000101', 'خاتم ذهب سادة 21',    '6290000000101', 1, '21',  5.20, false, 3,  855.0, 120.0),
  (102, 'I-000102', 'خاتم ذهب مجوهر 21',   '6290000000102', 1, '21',  6.80, true,  2, 1240.0, 180.0),
  (201, 'I-000201', 'سوار ذهب 21',          '6290000000201', 2, '21', 12.50, false, 5, 2050.0, 250.0),
  (301, 'I-000301', 'قلادة ذهب 18',         '6290000000301', 3, '18',  8.30, false, 4, 1640.0, 200.0),
  (302, 'I-000302', 'قلادة ذهب مجوهرة 18', '6290000000302', 3, '18', 10.10, true,  2, 2480.0, 300.0)
ON CONFLICT (id) DO NOTHING;

-- ── Current gold price ─────────────────────────────────────────────────────
-- Note: ERP GoldPrice model has no explicit __tablename__ → Flask-SQLAlchemy
-- lowercases the class name → table is 'goldprice' (not 'gold_price').
INSERT INTO goldprice (id, price) VALUES (1, 195.50)
ON CONFLICT (id) DO NOTHING;
