-- ============================================================================
-- TEST DATA ONLY - NOT REAL COMPANY RATES, SERVICES, OR POLICIES.
-- Every value below is an invented placeholder for local development.
-- Replace wholesale before any real use.
-- ============================================================================
INSERT OR IGNORE INTO countries (id, name, active) VALUES
    (1, 'Colombia', 1),
    (2, 'Mexico', 1),
    (3, 'Honduras', 1),
    (4, 'Dominican Republic', 1),
    (5, 'Cuba', 1),
    (6, 'Venezuela', 1);

INSERT OR IGNORE INTO services (id, destination_country, service_type, active, transit_time_text) VALUES
    (1, 'Colombia', 'standard_parcel', 1, 'TEST DATA: approx. 7-10 business days'),
    (2, 'Mexico',   'standard_parcel', 1, 'TEST DATA: approx. 5-8 business days'),
    (3, 'Honduras', 'standard_parcel', 1, 'TEST DATA: approx. 8-12 business days');

INSERT OR IGNORE INTO rates (id, service_id, min_weight, max_weight, price, currency, effective_from, effective_to) VALUES
    (1, 1,  0.0, 25.0,  49.00, 'CAD', '2026-01-01', NULL),
    (2, 1, 25.0, 50.0,  89.00, 'CAD', '2026-01-01', NULL),
    (3, 2,  0.0, 25.0,  45.00, 'CAD', '2026-01-01', NULL),
    (4, 2, 25.0, 50.0,  79.00, 'CAD', '2026-01-01', NULL),
    (5, 3,  0.0, 25.0,  55.00, 'CAD', '2026-01-01', NULL),
    (6, 3, 25.0, 50.0,  95.00, 'CAD', '2026-01-01', NULL);

INSERT OR IGNORE INTO restrictions (id, destination_country, category, rule_text, active) VALUES
    (1, 'Mexico',   'electronics', 'TEST DATA: one personal-use mobile phone permitted per shipment.', 1),
    (2, 'Mexico',   'supplements', 'TEST DATA: sealed vitamins permitted up to 3 containers.', 1),
    (3, 'Colombia', 'electronics', 'TEST DATA: electronics may require a customs declaration.', 1);

INSERT OR IGNORE INTO business_info (key, value) VALUES
    ('hours_saturday', 'TEST DATA: Saturday 09:00-13:00'),
    ('hours_weekday',  'TEST DATA: Monday-Friday 09:00-18:00'),
    ('support_email',  'TEST DATA: support@example.invalid');
