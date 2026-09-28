-- organizations definition

CREATE TABLE organizations (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	email VARCHAR(255), 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);


-- product_catalog definition

CREATE TABLE product_catalog (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	product_type VARCHAR(100) NOT NULL, 
	description TEXT, 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);


-- users definition

CREATE TABLE users (
	id INTEGER NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	password VARCHAR(255) NOT NULL, 
	roles VARCHAR(255) NOT NULL, 
	email VARCHAR(255), 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_username ON users (username);


-- audit_log definition

CREATE TABLE audit_log (
	id INTEGER NOT NULL, 
	actor_id INTEGER, 
	action VARCHAR(50) NOT NULL, 
	entity VARCHAR(100) NOT NULL, 
	entity_id INTEGER, 
	details TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE INDEX ix_audit_log_entity_id ON audit_log (entity_id);


-- benefits definition

CREATE TABLE benefits (
	id INTEGER NOT NULL, 
	product_id INTEGER NOT NULL, 
	code VARCHAR(60) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	description TEXT, 
	benefit_type VARCHAR(40), 
	coverage_amount NUMERIC(12, 2), 
	premium_rate NUMERIC(12, 4), 
	is_active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_benefit_product_code UNIQUE (product_id, code), 
	FOREIGN KEY(product_id) REFERENCES product_catalog (id)
);

CREATE INDEX ix_benefits_product_id ON benefits (product_id);


-- parties definition

CREATE TABLE parties (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	party_type VARCHAR(50) NOT NULL, 
	email VARCHAR(255), 
	active BOOLEAN NOT NULL, 
	organization_id INTEGER, 
	broker_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id), 
	FOREIGN KEY(broker_id) REFERENCES parties (id)
);


-- policies definition

CREATE TABLE policies (
	id INTEGER NOT NULL, 
	policy_number VARCHAR(80) NOT NULL, 
	product_id INTEGER NOT NULL, 
	party_id INTEGER, 
	organization_id INTEGER, 
	status VARCHAR(20) NOT NULL, 
	status_changed_at DATETIME, 
	start_date DATE, 
	end_date DATE, 
	premium NUMERIC(12, 2), 
	underwriter_id INTEGER, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_policy_policy_number UNIQUE (id, policy_number), 
	FOREIGN KEY(product_id) REFERENCES product_catalog (id), 
	FOREIGN KEY(party_id) REFERENCES parties (id), 
	FOREIGN KEY(organization_id) REFERENCES organizations (id), 
	FOREIGN KEY(underwriter_id) REFERENCES users (id)
);

CREATE INDEX ix_policies_party_id ON policies (party_id);


-- invoices definition

CREATE TABLE invoices (
	id INTEGER NOT NULL, 
	policy_id INTEGER, 
	invoice_number VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	total_amount NUMERIC(12, 2), 
	paid_amount NUMERIC(12, 2) NOT NULL, 
	issued_date DATE, 
	due_date DATE, 
	paid_date DATETIME, 
	adjustment_reason VARCHAR(255), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_invoice_policy_number UNIQUE (policy_id, invoice_number), 
	FOREIGN KEY(policy_id) REFERENCES policies (id)
);

CREATE INDEX ix_invoices_policy_id ON invoices (policy_id);


-- members definition

CREATE TABLE members (
	id INTEGER NOT NULL,
	policy_id INTEGER NOT NULL,
	party_id INTEGER,
	organization_id INTEGER,
	member_number VARCHAR(60) NOT NULL,
	first_name VARCHAR(80) NOT NULL,
	last_name VARCHAR(80) NOT NULL,
	date_of_birth DATE,
	gender VARCHAR(20),
	relationship_code VARCHAR(50),
	position_code VARCHAR(50),
	annual_salary NUMERIC(12, 2),
	status VARCHAR(20) NOT NULL,
	effective_date DATE,
	termination_date DATE,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_member_policy_number UNIQUE (policy_id, member_number),
	FOREIGN KEY(policy_id) REFERENCES policies (id),
	FOREIGN KEY(party_id) REFERENCES parties (id),
	FOREIGN KEY(organization_id) REFERENCES organizations (id),
	FOREIGN KEY(relationship_code) REFERENCES relationships (code),
	FOREIGN KEY(position_code) REFERENCES positions (code)
);

CREATE INDEX ix_members_party_id ON members (party_id);
CREATE INDEX ix_members_policy_id ON members (policy_id);


-- payments definition

CREATE TABLE payments (
	id INTEGER NOT NULL, 
	invoice_id INTEGER, 
	amount NUMERIC(12, 2) NOT NULL, 
	method VARCHAR(20), 
	reference VARCHAR(80), 
	status VARCHAR(20) NOT NULL, 
	payment_date DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(invoice_id) REFERENCES invoices (id)
);

CREATE INDEX ix_payments_invoice_id ON payments (invoice_id);


-- claims definition

CREATE TABLE claims (
	id INTEGER NOT NULL, 
	claim_number VARCHAR(60) NOT NULL, 
	policy_id INTEGER NOT NULL, 
	member_id INTEGER NOT NULL, 
	benefit_id INTEGER, 
	status VARCHAR(20) NOT NULL, 
	incident_date DATE NOT NULL, 
	amount_claimed NUMERIC(12, 2) NOT NULL, 
	amount_approved NUMERIC(12, 2), 
	description TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(policy_id) REFERENCES policies (id), 
	FOREIGN KEY(member_id) REFERENCES members (id), 
	FOREIGN KEY(benefit_id) REFERENCES benefits (id)
);

CREATE INDEX ix_claims_policy_id ON claims (policy_id);
CREATE UNIQUE INDEX ix_claims_claim_number ON claims (claim_number);
CREATE INDEX ix_claims_member_id ON claims (member_id);


-- life_events definition

CREATE TABLE life_events (
	id INTEGER NOT NULL, 
	policy_id INTEGER, 
	member_id INTEGER, 
	event_type VARCHAR(40) NOT NULL, 
	effective_date DATE NOT NULL, 
	actor_id INTEGER, 
	details TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(policy_id) REFERENCES policies (id), 
	FOREIGN KEY(member_id) REFERENCES members (id), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE INDEX ix_life_events_policy_id ON life_events (policy_id);


-- member_benefits definition

CREATE TABLE member_benefits (
	id INTEGER NOT NULL,
	member_id INTEGER NOT NULL,
	benefit_id INTEGER NOT NULL,
	election_amount NUMERIC(12, 2),
	premium NUMERIC(12, 2),
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_member_benefit_member UNIQUE (member_id),
	FOREIGN KEY(member_id) REFERENCES members (id),
	FOREIGN KEY(benefit_id) REFERENCES benefits (id)
);


-- lookup tables definition

-- party_types: the value set a party declares itself to be (individual,
-- corporation, trust ...). party.party_type is a code into this table.

CREATE TABLE party_types (
	code VARCHAR(50) NOT NULL,
	name VARCHAR(120) NOT NULL,
	description TEXT,
	is_active BOOLEAN NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (code)
);


-- party_roles: the many-to-many role a party can play (policy_holder, broker,
-- underwriter, member, beneficiary ...). party_party_roles.role_code is a code
-- into this table.

CREATE TABLE party_roles (
	code VARCHAR(50) NOT NULL,
	name VARCHAR(120) NOT NULL,
	description TEXT,
	is_active BOOLEAN NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (code)
);


-- policy_statuses: the finite state set (draft, active, lapsed, closed). The
-- transition map lives in app.enums; this table holds the values. policies.status
-- is a code into this table.

CREATE TABLE policy_statuses (
	code VARCHAR(50) NOT NULL,
	name VARCHAR(120) NOT NULL,
	description TEXT,
	is_active BOOLEAN NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (code)
);


-- party_party_roles: join table for the party<->role many-to-many. role_code
-- references party_roles.code; party_id references parties.id.

CREATE TABLE party_party_roles (
	party_id INTEGER NOT NULL,
	role_code VARCHAR(50) NOT NULL,
	PRIMARY KEY (party_id, role_code),
	FOREIGN KEY(party_id) REFERENCES parties (id),
	FOREIGN KEY(role_code) REFERENCES party_roles (code)
);


-- positions: a role a member holds within a policyholder organization (staff,
-- director, manager ...). member.position_code is a code into this table.

CREATE TABLE positions (
	code VARCHAR(50) NOT NULL,
	name VARCHAR(120) NOT NULL,
	description TEXT,
	is_active BOOLEAN NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (code)
);


-- relationships: a kinship a member has to the policyholder (self, spouse,
-- child ...). member.relationship_code is a code into this table.

CREATE TABLE relationships (
	code VARCHAR(50) NOT NULL,
	name VARCHAR(120) NOT NULL,
	description TEXT,
	is_active BOOLEAN NOT NULL,
	sort_order INTEGER NOT NULL,
	PRIMARY KEY (code)
);
