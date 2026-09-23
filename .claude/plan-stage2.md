# Stage 2 — Products & Policy Administration

## Context

Stage 1 established the platform scaffold: FastAPI + HTMX server-rendered UI,
user/auth with RBAC, Party/Organization models, and audit logging. The auth
module already declares the `manage_policies` and `manage_claims` permissions
for the underwriter role, but no policies exist yet. Stage 2 introduces the
core insurance domain: the product catalog and group policies, plus the policy
lifecycle. This is the stage the underwriter (insurer side) works in most.

Goals:
- Add a **product catalog**: an insurer-side catalog of insurance products
  (plan types) that policies are built from.
- Add **group policies**: a policy belongs to a policyholder Party and references
  a product; carries policy number, dates, status, and premium.
- Enforce a simple **policy lifecycle** (`draft` → `active` → `lapsed`/`closed`)
  with status changes audited.
- Wire the new CRUD into the HTMX UI (list + create forms), mirroring the
  party flow, and keep the existing RBAC discipline (underwriters create/edit
  policies; brokers can only view).
- Keep the DB models portable (SQLite → Postgres later) — no engine-specific
  types.

## Why this scope

Policy administration is the spine of a group-insurance platform: products and
policies are what claims (Stage 3) and reporting (Stage 4) hang off. Getting the
product/policy data model and lifecycle right early avoids rework. Claims are a
separate concept with their own lifecycle and are deferred to Stage 3.

## Model design

Three new tables. Keep columns minimal — full features come later.

**Product** (`product_catalog`): id, name, product_type (e.g. "group-term-life",
"group-disability", "group-health"), description, is_active bool, created_at.
Products are global (insurer-managed catalog), not scoped to an org.

**Policy** (`policies`):
- id, policy_number (unique per product), product_id FK → product_catalog,
  party_id FK → parties (the policyholder), organization_id FK → organizations
  (tenant scope, nullable).
- status: Mapped[str] in ("draft", "active", "lapsed", "closed"), default "draft".
- start_date, end_date (Date, nullable).
- premium (Numeric(12,2), nullable) — annual written premium placeholder.
- underwriter_id FK → users (nullable), active bool default True.
- created_at (reuse audit-style UTC default).

Policy number uniqueness: enforce at the (product_id, policy_number) level. On
SQLite this is a partial unique index — too fiddly now — so for now enforce the
uniqueness in the service layer (check before insert) and note that a DB-level
unique index should be added when switching to Postgres.

## RBAC / access

Extend `_ROLE_PERMISSIONS` in `api/auth.py`:
- `underwriter`: add `manage_products` and `manage_policies`.
- `broker`: add `view_policies`. (Brokers can see policies for parties they
  manage — but scoping by broker is Stage 5; for now brokers can list, and we
  guard only creation/edit with the right permission.)

Endpoints use `require_role` exactly as parties do. No public reads.

## Endpoints (all under `/api/policies` and `/api/products`, HTMX-style)

Products (insurer-only, `manage_products`):
- `GET /api/products/list` → renders product_list partial (sidebar-nav driven).
- `POST /api/products/create` (form) → create, return partial.

Policies (underwriter create/edit; broker read):
- `GET /api/policies/list` → policy_list partial (with an optional `?party_id=`
  filter, but default to all underwriter can see).
- `POST /api/policies/create` (form) → validate product exists, policy_number not
  a duplicate, status stays "draft"; return partial.
- `POST /api/policies/{id}/status` (form) → change status (draft→active, etc.);
  audit the change.

## Services

- `app/services/products.py`: `list_products`, `add_product`.
- `app/services/policies.py`: `list_policies`, `get_policy`, `add_policy`
  (checks policy_number uniqueness in-service, audits `policy_create`),
  `change_policy_status` (audits `policy_status_change`, validates the transition
  is legal per a small ALLOWED map, e.g. draft→active, active→lapsed,
  active→closed).

## Audit

Use existing `record_log`. New actions: `product_create`, `policy_create`,
`policy_status_change`. The audit view doesn't need changes (it already renders
any action/entity).

## UI / templates

- `templates/partials/product_list.html`, `policy_list.html`.
- `templates/auth/dashboard.html`: add Product catalog and Policies links to the
  sidebar (hx-get into #content), following the existing pattern. Keep the
  placeholder links for Enrollment/Claims/Reports as-is (stages 3–4).
- Small inline create forms in each partial (copy the party form shape).
- A policy card shows: policy number, product, status badge, dates.

## Tests

Extend `app/api/test_smoke.py` with: register underwriter, create a product
(underwriter), create a policy referencing it, verify status change flow, and
that a broker user is rejected (403) from create. Keep the existing DB reset
(drop_all/create_all) idempotency.

## Notes / decisions

- Numeric premium stored as `Numeric(12,2)` via SQLAlchemy core type — portable
  across SQLite and Postgres.
- Policy-number uniqueness enforced in the service layer for now; document the
  Postgres partial-unique-index upgrade for the migration stage.
- Product catalog is global (not per-org) — underwriters manage it centrally.
- Full broker scoping, member enrollment, and reporting are intentionally out of
  scope and carried to later stages.

## Verification

1. `uv run --extra dev pytest src/backend/app/api/test_smoke.py` — all pass.
2. Boot: `cd src/backend && uv run uvicorn app.main:app --reload`, login as an
   underwriter (or register one via API), navigate to Product catalog and
   Policies, create a product + policy, flip status, and confirm each change
   appears in the Audit log.

## Commit

When approved, stage 1 already committed. Commit Stage 2 with message "Stage 2:
product catalog and group policies with lifecycle" then `Co-Authored-By`.
