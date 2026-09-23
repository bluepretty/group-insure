# Stage 4 — Product Benefits + Member Coverage Elections

- [x] Create Benefit model (benefits table)
- [x] Create MemberBenefit model (member_benefits table)
- [x] Register both in app/models/__init__.py
- [x] Extend RBAC (view_benefits, manage_benefits)
- [x] Create service (benefits.py): list per product, add benefit, list a member's elections
- [x] Create API (benefits.py): per-product benefit list partial, add-benefit form, member-coverage list
- [x] Wire router into main.py
- [x] Create templates (partials/benefit_list.html, partials/member_coverage.html)
- [x] Link product detail → benefits, member detail → coverage
- [x] Extend smoke test (add benefit, enroll member with benefit, list coverage, broker 403)
- [x] Run smoke test & fix issues
- [x] Commit

## Context

Stage 2 (catalog) + Stage 3 (enrollees) introduced the two objects a group policy
is built from, but nothing connects them yet:

- A **product** is a catalog item with a type, but today it has no benefits.
- A **member** is enrolled under a policy, but today they have no coverage.

Stage 3 explicitly deferred "product coverage elections per member (which
benefits a member actually holds)" to this stage. Stage 4 fills that gap:
products offer a set of **benefits**, and members **elect** specific benefits.
Later stages can then price premiums from those elections.

This is a data-model + service/API layer change; the UI is a light HTMX layer
over the same patterns already in products/policies/members. It is deliberately
scoped so pricing/allocation stays for a later stage.

## Scope for this stage
- **Benefit**: a benefit definition owned by a product (e.g. "Term — Base" /
  "Spouse rider"). A product can have several benefits.
- **MemberBenefit (coverage election)**: the fact that a specific member holds a
  specific benefit from the product their policy is built from. Enforced to only
  reference benefits that belong to the member's product.
- Per-member election amount is optional (nullable) — enough to record that the
  member elected the benefit and, optionally, how much. Actual premium
  allocation is Stage 5.
- Broker views benefits/coverage under `view_benefits`; underwriters manage
  them via `manage_benefits`.

## Deliberately out of scope
- Pricing / premium allocation per member or per product. Deferred.
- Eligibility rules (who may elect which benefits by relationship/age). Deferred.
- Coverage tiers / benefit variants. Not modeled.

## Model design
Two new tables. Both use portable core types (portable to Postgres); uniqueness
enforced in the service layer, DB-level indexes added when switching engines.

### benefit
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| product_id | FK product_catalog | not null (a benefit belongs to a product) |
| code | String(60) | e.g. "TERM-BASE" (unique per product, enforced in service) |
| name | String(200) | human-readable |
| description | Text | nullable |
| benefit_type | String(40) | e.g. term / disability / dependent |
| coverage_amount | Numeric(12,2) | nullable |
| is_active | bool | default True |
| created_at | UTC datetime | |

### member_benefit
| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| member_id | FK members | not null |
| benefit_id | FK benefit | not null (must belong to member's product) |
| election_amount | Numeric(12,2) | nullable |
| created_at | UTC datetime | |

Uniqueness: at most one election per (member, benefit). Enforced in the service
layer (a DB unique index can be added on Postgres).

## RBAC (auth.py `_ROLE_PERMISSIONS`)
- underwriter: add `view_benefits`, `manage_benefits`.
- broker: add `view_benefits` (no `manage_benefits`).

## API (under `/api/benefits`)
All JSON + HTMX-partial, matching existing `products`/`policies`/`members` style.
- `GET /api/benefits?product_id=...` → JSON list, requires `view_benefits`.
- `GET /api/benefits/list` → HTMX partial (per-product benefit list, optional
  `?product_id=`), requires `view_benefits`.
- `POST /api/benefits` (form) → add a benefit to a product, requires
  `manage_benefits`; raises 400 on unknown product or duplicate code; logs
  `benefit_add`.
- `GET /api/benefits/coverage` (JSON, `?member_id=...`) → a member's elected
  benefits, requires `view_benefits`.
- `POST /api/members/{member_id}/benefits` (form) → enroll a member in a
  benefit (create MemberBenefit), requires `manage_members`; enforces that the
  benefit belongs to the member's product and that the (member, benefit) pair
  is not already elected; raises 400 otherwise; logs `benefit_elect`.

## Services (app/services/benefits.py)
- `list_benefits(db, *, product_id=None)`
- `add_benefit(db, *, product_id, code, name, description=None, benefit_type=None, coverage_amount=None)` — raises ValueError on unknown product / duplicate code; logs `benefit_add`.
- `list_member_benefits(db, *, member_id=None)` — returns a member's elections.
- `elect_benefit(db, *, member_id, benefit_id, election_amount=None)` — raises ValueError on unknown member/benefit; raises if `benefit.product_id != member.policy.product_id`; raises if the (member, benefit) pair is already elected; logs `benefit_elect`.

## UI
- `templates/partials/benefit_list.html` — add-benefit form (product select +
  code/name/type fields) + table of a product's benefits.
- `templates/partials/member_coverage.html` — table of one member's elected
  benefits with an "Add benefit" form.
- `templates/auth/dashboard.html` — set the "Coverage" sidebar link to
  `hx-get="/api/benefits/list"`.

## Tests
Extend `test_smoke.py`: underwriter creates a product → adds a benefit → creates
a policy → enrolls a member → elects the member into the benefit → lists
member coverage. Then register a broker and assert a broker's benefit-add
attempt returns 403. Keep DB reset idempotency.
