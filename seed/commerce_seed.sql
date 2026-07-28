-- seed/commerce_seed.sql
-- Runs against postgres-commerce AFTER the commerce-api creates its schema
-- (via create_schema() in the lifespan).
--
-- INVARIANT: item IDs here MUST match erp_seed.sql exactly.
-- These IDs represent the SAME physical items across the DB boundary.
-- A mismatch is a TOCTOU vulnerability — the claim-race and N+4 tests
-- depend on both sides agreeing on item identity.

SET client_encoding = 'UTF8';

-- ── Categories ─────────────────────────────────────────────────────────────
-- Mirrors ERP category table; IDs must stay in sync with erp_seed.sql
INSERT INTO category (id, name, description, karat, created_at) VALUES
  (1, 'خواتم', 'خواتم ذهبية',  '21', NOW()),
  (2, 'أساور', 'أساور ذهبية',  '21', NOW()),
  (3, 'قلائد', 'قلائد ذهبية',  '18', NOW())
ON CONFLICT (id) DO NOTHING;

-- ── Items ──────────────────────────────────────────────────────────────────
-- weight in grams; price in SAR; stock = currently available units
INSERT INTO item
  (id, item_code, name, barcode, category_id, karat,
   weight, has_stones, stones_weight, stones_value, count,
   wage, description, price, stock)
VALUES
  (101, 'I-000101', 'خاتم ذهب سادة 21',    '6290000000101', 1, '21',
    5.20, false, NULL,  NULL,  1,  120.0, NULL,  855.0, 3),
  (102, 'I-000102', 'خاتم ذهب مجوهر 21',   '6290000000102', 1, '21',
    6.80, true,  0.50, 250.0,  1,  180.0, NULL, 1240.0, 2),
  (201, 'I-000201', 'سوار ذهب 21',          '6290000000201', 2, '21',
   12.50, false, NULL,  NULL,  1,  250.0, NULL, 2050.0, 5),
  (301, 'I-000301', 'قلادة ذهب 18',         '6290000000301', 3, '18',
    8.30, false, NULL,  NULL,  1,  200.0, NULL, 1640.0, 4),
  (302, 'I-000302', 'قلادة ذهب مجوهرة 18', '6290000000302', 3, '18',
   10.10, true,  1.20, 600.0,  1,  300.0, NULL, 2480.0, 2)
ON CONFLICT (id) DO NOTHING;

-- ── Gold price (SAR per gram, 21-karat basis) ──────────────────────────────
-- gold_price.date stores UTC (naive). Both catalog.py and reservations.py
-- normalise it with .replace(tzinfo=timezone.utc). Never store local time here.
INSERT INTO gold_price (id, price, date) VALUES
  (1, 195.50, NOW())
ON CONFLICT (id) DO UPDATE SET price = EXCLUDED.price, date = EXCLUDED.date;
