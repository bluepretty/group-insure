-- ============================================================================
-- Seed data for the group insurance schema (database_schema_ddl.sql)
-- Engine: SQLite / PostgreSQL compatible (uses ISO datetimes, TRUE/FALSE, SERIAL-style ids)
-- Insert ORDER matters: parents before children.
--
-- Coverage of what this seed produces:
--   2   organizations          (employers)
--   2   product_catalog        (insurance products)
--   3   users                  (1 admin + 2 underwriters, used as underwriters / audit actors)
--   5   benefits               (5 benefit definitions, spread over the 2 products)
--  15   parties                (5 brokers + 2 employer parties + 8 insured individuals)
--  10   policies               (5 under Acme, 5 under Global Logistics)
--  20   members                (2 members per policy)
--  ~30   member_benefits      (one member per benefit election)
--   4   claims                 (one per lifecycle status)
--  10   invoices               (one per policy, mix of paid / unpaid)
--  10   payments               (one per invoice)
--   4   life_events            (enrollment / renewal / termination)
--   2   audit_log              (create / underwrite)
--
-- Party reuse note: there are only 8 "insured" parties but 20 members, so the
-- same party is referenced by members on multiple policies. This is realistic
-- (an employee re-insured under a renewed policy year) and every FK still
-- resolves to a real row.
-- ============================================================================


-- ----------------------------- organizations --------------------------------
INSERT INTO organizations (id, name, type, email, active, created_at) VALUES
    (1, 'Acme Manufacturing Inc',        'employer', 'hr@acme.example.com',        TRUE,  '2023-01-10 09:00:00'),
    (2, 'Global Logistics Ltd',          'employer', 'people@globallog.example.com', TRUE,  '2023-03-15 09:00:00');

-- ----------------------------- products -------------------------------------
INSERT INTO product_catalog (id, name, product_type, description, is_active, created_at) VALUES
    (1, 'Group Term Life Insurance', 'life',   'Basic group term life cover with accidental death add-on',   TRUE, '2023-01-10 09:00:00'),
    (2, 'Group Critical Illness Cover', 'health', 'Hospital income plus critical illness lump-sum cover',       TRUE, '2023-01-10 09:00:00');

-- -------------------------------- users -------------------------------------
-- password columns hold placeholder hashes; any non-empty string works here.
INSERT INTO users (id, username, password, roles, email, active, created_at) VALUES
    (1, 'admin',      '$2a$10$placeholderhashforadmin00000000000000000000abc', 'admin',      'admin@platform.example',  TRUE, '2022-11-01 08:30:00'),
    (2, 'jsmith',     '$2a$10$placeholderhashforunderwriter000000000000000abc',  'underwriter','jsmith@example.com',      TRUE, '2023-02-04 09:15:00'),
    (3, 'alee',       '$2a$10$placeholderhashforunderwriter000000000000000abc',  'underwriter','alee@example.com',        TRUE, '2023-05-19 10:45:00');

-- ----------------------------- benefits -------------------------------------
INSERT INTO benefits (id, product_id, code, name, description, benefit_type, coverage_amount, premium_rate, is_active, created_at) VALUES
    (1, 1, 'DTL-BASIC',  'Basic Death Benefit',    'Standard death benefit',              'life',   100000.00, 0.0120, TRUE, '2023-01-10 09:00:00'),
    (2, 1, 'AD-BASIC',   'Accidental Death',       'Optional accidental death benefit',   'life',    50000.00, 0.0040, TRUE, '2023-01-10 09:00:00'),
    (3, 2, 'CI-STD',     'Critical Illness Cover',  'Lump-sum critical illness cover',     'health',  50000.00, 0.0300, TRUE, '2023-01-10 09:00:00'),
    (4, 2, 'HOSP-DAILY', 'Hospital Income',         'Daily hospital income benefit',      'health',     150.00, 0.0008, TRUE, '2023-01-10 09:00:00'),
    (5, 2, 'SPOUSE-STD', 'Spouse Cover',            'Spouse dependency cover',           'life',   25000.00, 0.0180, TRUE, '2023-01-10 09:00:00');

-- ----------------------------- parties --------------------------------------
-- parties 1-5  : brokers
-- parties 6-7  : employer parties (linked to an organization)
-- parties 8-15 : insured individuals
INSERT INTO parties (id, name, party_type, email, active, organization_id, broker_id, created_at) VALUES
    (1,  'Summit Insurance Brokers',    'broker',   'agent@summit.example',     TRUE, NULL, NULL, '2023-01-05 09:00:00'),
    (2,  'Beacon Risk Partners',        'broker',   'brokerage@beacon.example', TRUE, NULL, NULL, '2023-01-06 09:00:00'),
    (3,  'Northgate Advisory',          'broker',   'contact@northgate.example', TRUE, NULL, NULL, '2023-01-07 09:00:00'),
    (4,  'Pinnacle Brokerage',          'broker',   'hello@pinnacle.example',   TRUE, NULL, NULL, '2023-01-08 09:00:00'),
    (5,  'Harbor Wealth & Risk',        'broker',   'team@harbor.example',      TRUE, NULL, NULL, '2023-01-09 09:00:00'),
    (6,  'Acme Manufacturing Inc',      'employer', 'hr@acme.example.com',      TRUE, 1, 1, '2023-01-10 09:00:00'),
    (7,  'Global Logistics Ltd',        'employer', 'people@globallog.example.com', TRUE, 2, 2, '2023-03-15 09:00:00'),
    (8,  'John Smith',                  'insured',  'john.smith@example.com',   TRUE, 1, NULL, '2023-01-10 09:00:00'),
    (9,  'Maria Garcia',                'insured',  'maria.garcia@example.com', TRUE, 1, NULL, '2023-01-10 09:00:00'),
    (10, 'David Chen',                  'insured',  'david.chen@example.com',   TRUE, 1, NULL, '2023-01-10 09:00:00'),
    (11, 'Priya Patel',                 'insured',  'priya.patel@example.com',  TRUE, 1, NULL, '2023-01-10 09:00:00'),
    (12, 'James O''Brien',              'insured',  'james.obrien@example.com', TRUE, 2, NULL, '2023-03-15 09:00:00'),
    (13, 'Sarah Johnson',               'insured',  'sarah.johnson@example.com', TRUE, 2, NULL, '2023-03-15 09:00:00'),
    (14, 'Liam Nguyen',                 'insured',  'liam.nguyen@example.com',  TRUE, 2, NULL, '2023-03-15 09:00:00'),
    (15, 'Emily Rodriguez',             'insured',  'emily.rodriguez@example.com', TRUE, 2, NULL, '2023-03-15 09:00:00');

-- ----------------------------- policies -------------------------------------
-- party_id  = the employer policyholder party (6 = Acme, 7 = Global)
INSERT INTO policies (id, policy_number, product_id, party_id, organization_id, status, status_changed_at, start_date, end_date, premium, underwriter_id, active, created_at) VALUES
    (1,  'POL-2024-0001', 1, 6, 1, 'active',     '2024-01-01 00:00:00', '2024-01-01', '2024-12-31', 12000.00, 2, TRUE,  '2023-12-01 09:00:00'),
    (2,  'POL-2024-0002', 1, 6, 1, 'active',     '2024-01-01 00:00:00', '2024-01-01', '2024-12-31', 15000.00, 2, TRUE,  '2023-12-01 09:00:00'),
    (3,  'POL-2024-0003', 2, 6, 1, 'active',     '2024-06-01 00:00:00', '2024-06-01', '2025-05-31',  8000.00, 3, TRUE,  '2024-05-15 09:00:00'),
    (4,  'POL-2024-0004', 1, 7, 2, 'active',     '2024-01-01 00:00:00', '2024-01-01', '2024-12-31', 20000.00, 3, TRUE,  '2023-12-10 09:00:00'),
    (5,  'POL-2024-0005', 2, 7, 2, 'active',     '2024-01-01 00:00:00', '2024-01-01', '2024-12-31',  9500.00, 2, TRUE,  '2023-12-10 09:00:00'),
    (6,  'POL-2024-0006', 2, 7, 2, 'pending',    '2024-07-01 00:00:00', NULL,           NULL,          5000.00, 3, TRUE,  '2024-06-20 09:00:00'),
    (7,  'POL-2023-0007', 1, 6, 1, 'expired',    '2024-12-31 00:00:00', '2023-01-01', '2023-12-31', 11000.00, 2, FALSE, '2022-12-01 09:00:00'),
    (8,  'POL-2024-0008', 1, 7, 2, 'active',     '2024-01-01 00:00:00', '2024-01-01', '2024-12-31', 18000.00, 3, TRUE,  '2023-12-10 09:00:00'),
    (9,  'POL-2024-0009', 2, 6, 1, 'pending',    '2024-11-01 00:00:00', NULL,           NULL,          7000.00, 3, TRUE,  '2024-10-25 09:00:00'),
    (10, 'POL-2024-0010', 1, 7, 2, 'active',     '2024-01-01 00:00:00', '2024-01-01', '2024-12-31', 22000.00, 2, TRUE,  '2023-12-10 09:00:00');

-- ----------------------------- members --------------------------------------
INSERT INTO members (id, policy_id, party_id, organization_id, member_number, first_name, last_name, date_of_birth, gender, relationship, status, effective_date, termination_date, created_at) VALUES
    (1,  1, 8,  1, 'MEM-0001', 'John',   'Smith',   '1978-04-12', 'male',   'Self',    'active',   '2024-01-01', NULL, '2023-12-01 09:00:00'),
    (2,  1, 9,  1, 'MEM-0002', 'Maria',  'Garcia',  '1980-07-23', 'female', 'Spouse',  'active',   '2024-01-01', NULL, '2023-12-01 09:00:00'),
    (3,  2, 10, 1, 'MEM-0003', 'David',  'Chen',    '1975-11-30', 'male',   'Self',    'active',   '2024-01-01', NULL, '2023-12-01 09:00:00'),
    (4,  2, 11, 1, 'MEM-0004', 'Priya',  'Patel',   '1982-02-14', 'female', 'Spouse',  'active',   '2024-01-01', NULL, '2023-12-01 09:00:00'),
    (5,  3, 8,  1, 'MEM-0005', 'John',   'Smith',   '1978-04-12', 'male',   'Self',    'active',   '2024-06-01', NULL, '2024-05-15 09:00:00'),
    (6,  3, 9,  1, 'MEM-0006', 'Maria',  'Garcia',  '1980-07-23', 'female', 'Spouse',  'active',   '2024-06-01', NULL, '2024-05-15 09:00:00'),
    (7,  7, 10, 1, 'MEM-0007', 'David',  'Chen',    '1975-11-30', 'male',   'Self',    'terminated','2023-01-01','2023-12-31','2022-12-01 09:00:00'),
    (8,  7, 11, 1, 'MEM-0008', 'Priya',  'Patel',   '1982-02-14', 'female', 'Spouse',  'terminated','2023-01-01','2023-12-31','2022-12-01 09:00:00'),
    (9,  9, 11, 1, 'MEM-0009', 'Priya',  'Patel',   '1982-02-14', 'female', 'Self',    'pending',  '2024-11-01', NULL, '2024-10-25 09:00:00'),
    (10, 9, 8,  1, 'MEM-0010', 'John',   'Smith',   '1978-04-12', 'male',   'Self',    'pending',  '2024-11-01', NULL, '2024-10-25 09:00:00'),
    (11, 4, 12, 2, 'MEM-0011', 'James',  'O''Brien','1976-09-05', 'male',   'Self',    'active',   '2024-01-01', NULL, '2023-12-10 09:00:00'),
    (12, 4, 13, 2, 'MEM-0012', 'Sarah',  'Johnson', '1981-06-18', 'female', 'Spouse',  'active',   '2024-01-01', NULL, '2023-12-10 09:00:00'),
    (13, 5, 14, 2, 'MEM-0013', 'Liam',   'Nguyen',  '1984-03-22', 'male',   'Self',    'active',   '2024-01-01', NULL, '2023-12-10 09:00:00'),
    (14, 5, 15, 2, 'MEM-0014', 'Emily',  'Rodriguez','1983-11-09','female', 'Spouse',  'active',   '2024-01-01', NULL, '2023-12-10 09:00:00'),
    (15, 6, 12, 2, 'MEM-0015', 'James',  'O''Brien','1976-09-05', 'male',   'Self',    'active',   '2024-07-01', NULL, '2024-06-20 09:00:00'),
    (16, 6, 13, 2, 'MEM-0016', 'Sarah',  'Johnson', '1981-06-18', 'female', 'Spouse',  'active',   '2024-07-01', NULL, '2024-06-20 09:00:00'),
    (17, 8, 14, 2, 'MEM-0017', 'Liam',   'Nguyen',  '1984-03-22', 'male',   'Self',    'active',   '2024-01-01', NULL, '2023-12-10 09:00:00'),
    (18, 8, 15, 2, 'MEM-0018', 'Emily',  'Rodriguez','1983-11-09','female', 'Spouse',  'active',   '2024-01-01', NULL, '2023-12-10 09:00:00'),
    (19, 10,12, 2, 'MEM-0019', 'James',  'O''Brien','1976-09-05', 'male',   'Self',    'active',   '2024-01-01', NULL, '2023-12-10 09:00:00'),
    (20, 10,14, 2, 'MEM-0020', 'Liam',   'Nguyen',  '1984-03-22', 'male',   'Self',    'active',   '2024-01-01', NULL, '2023-12-10 09:00:00');

-- -------------------------- member_benefits ---------------------------------
-- NOTE: the schema constrains member_benefits to exactly one row per member
-- (UNIQUE (member_id)). So each member is tied to their single best-fit benefit
-- for this product year.
INSERT INTO member_benefits (member_id, benefit_id, election_amount, premium, created_at) VALUES
    (1,  1, 100000.00, 600.00, '2023-12-01 09:00:00'),
    (2,  1, 100000.00, 300.00, '2023-12-01 09:00:00'),
    (3,  1, 100000.00, 750.00, '2023-12-01 09:00:00'),
    (4,  1, 100000.00, 375.00, '2023-12-01 09:00:00'),
    (5,  3,  50000.00, 120.00, '2024-05-15 09:00:00'),
    (6,  3,  50000.00, 120.00, '2024-05-15 09:00:00'),
    (7,  1, 100000.00, 440.00, '2022-12-01 09:00:00'),
    (8,  1, 100000.00, 220.00, '2022-12-01 09:00:00'),
    (9,  3,  50000.00, 175.00, '2024-10-25 09:00:00'),
    (10, 3,  50000.00, 175.00, '2024-10-25 09:00:00'),
    (11, 1, 100000.00, 720.00, '2023-12-10 09:00:00'),
    (12, 1, 100000.00, 360.00, '2023-12-10 09:00:00'),
    (13, 3,  50000.00, 190.00, '2023-12-10 09:00:00'),
    (14, 3,  50000.00, 190.00, '2023-12-10 09:00:00'),
    (15, 3,  50000.00,  95.00, '2024-06-20 09:00:00'),
    (16, 3,  50000.00,  95.00, '2024-06-20 09:00:00'),
    (17, 1, 100000.00, 600.00, '2023-12-10 09:00:00'),
    (18, 1, 100000.00, 300.00, '2023-12-10 09:00:00'),
    (19, 1, 100000.00, 660.00, '2023-12-10 09:00:00'),
    (20, 1, 100000.00, 660.00, '2023-12-10 09:00:00');

-- ----------------------------- claims ---------------------------------------
INSERT INTO claims (claim_number, policy_id, member_id, benefit_id, status, incident_date, amount_claimed, amount_approved, description, created_at, updated_at) VALUES
    ('CLAIM-2024-0001', 1, 1, 1, 'filed',     '2024-03-10', 5000.00,  NULL,          'Hospitalization for accidental injury', '2024-03-11 10:00:00', '2024-03-11 10:00:00'),
    ('CLAIM-2024-0002', 4, 11, 3, 'approved',  '2024-05-22', 40000.00, 40000.00,     'Critical illness diagnosis (covered)',  '2024-05-23 10:00:00', '2024-06-02 10:00:00'),
    ('CLAIM-2024-0003', 8, 17, 1, 'paid',      '2024-08-15', 3000.00,  3000.00,      'Accidental death benefit payout',        '2024-08-16 10:00:00', '2024-09-01 10:00:00'),
    ('CLAIM-2024-0004', 2, 3,  1, 'declined',  '2024-02-01', 8000.00,  0.00,         'Claim reviewed and declined',            '2024-02-02 10:00:00', '2024-02-20 10:00:00');

-- ----------------------------- invoices -------------------------------------
INSERT INTO invoices (policy_id, invoice_number, status, total_amount, paid_amount, issued_date, due_date, paid_date, created_at) VALUES
    (1,  'INV-2024-0001', 'paid',   12000.00, 12000.00, '2024-01-15', '2024-02-15', '2024-02-10 00:00:00', '2024-01-15 09:00:00'),
    (2,  'INV-2024-0002', 'paid',   15000.00, 15000.00, '2024-01-15', '2024-02-15', '2024-02-11 00:00:00', '2024-01-15 09:00:00'),
    (3,  'INV-2024-0003', 'unpaid',  8000.00,   0.00, '2024-06-10', '2024-07-10', NULL,                           '2024-06-10 09:00:00'),
    (4,  'INV-2024-0004', 'paid',   20000.00, 20000.00, '2024-01-15', '2024-02-15', '2024-02-12 00:00:00', '2024-01-15 09:00:00'),
    (5,  'INV-2024-0005', 'paid',    9500.00,  9500.00, '2024-01-15', '2024-02-15', '2024-02-13 00:00:00', '2024-01-15 09:00:00'),
    (6,  'INV-2024-0006', 'unpaid',  5000.00,   0.00, '2024-07-05', '2024-08-05', NULL,                           '2024-07-05 09:00:00'),
    (7,  'INV-2023-0007', 'paid',   11000.00, 11000.00, '2023-01-15', '2023-02-15', '2023-02-14 00:00:00', '2023-01-15 09:00:00'),
    (8,  'INV-2024-0008', 'paid',   18000.00, 18000.00, '2024-01-15', '2024-02-15', '2024-02-15 00:00:00', '2024-01-15 09:00:00'),
    (9,  'INV-2024-0009', 'unpaid',  7000.00,   0.00, '2024-11-05', '2024-12-05', NULL,                           '2024-11-05 09:00:00'),
    (10, 'INV-2024-0010', 'paid',   22000.00, 22000.00, '2024-01-15', '2024-02-15', '2024-02-16 00:00:00', '2024-01-15 09:00:00');

-- ----------------------------- payments -------------------------------------
INSERT INTO payments (invoice_id, amount, method, reference, status, payment_date, created_at) VALUES
    (1, 12000.00, 'bank_transfer', 'PAY-2024-0001', 'completed', '2024-02-10 00:00:00', '2024-02-10 00:00:00'),
    (2, 15000.00, 'bank_transfer', 'PAY-2024-0002', 'completed', '2024-02-11 00:00:00', '2024-02-11 00:00:00'),
    (4, 20000.00, 'card',          'PAY-2024-0003', 'completed', '2024-02-12 00:00:00', '2024-02-12 00:00:00'),
    (5,  9500.00, 'card',          'PAY-2024-0004', 'completed', '2024-02-13 00:00:00', '2024-02-13 00:00:00'),
    (8, 18000.00, 'bank_transfer', 'PAY-2024-0005', 'completed', '2024-02-15 00:00:00', '2024-02-15 00:00:00'),
    (10,22000.00, 'bank_transfer', 'PAY-2024-0006', 'completed', '2024-02-16 00:00:00', '2024-02-16 00:00:00'),
    (7, 11000.00, 'card',          'PAY-2023-0007', 'completed', '2023-02-14 00:00:00', '2023-02-14 00:00:00');

-- --------------------------- life_events ------------------------------------
INSERT INTO life_events (policy_id, member_id, event_type, effective_date, actor_id, details, created_at) VALUES
    (1, 1, 'enrollment', '2024-01-01', 2, 'Initial member enrollment', '2023-12-01 09:00:00'),
    (4, 11, 'enrollment', '2024-01-01', 3, 'Initial member enrollment', '2023-12-10 09:00:00'),
    (1, 1, 'renewal',    '2025-01-01', 2, 'Policy renewed for 2025 cycle', '2024-01-01 09:00:00'),
    (7, 7, 'termination','2023-12-31', 2, 'Member terminated with expiring policy', '2023-12-31 09:00:00');

-- ----------------------------- audit_log ------------------------------------
INSERT INTO audit_log (actor_id, action, entity, entity_id, details, created_at) VALUES
    (1, 'create',   'policy', 1, 'Created policy POL-2024-0001', '2023-12-01 09:00:00'),
    (2, 'underwrite','policy', 1, 'Underwrote and approved POL-2024-0001', '2023-12-01 09:30:00');
