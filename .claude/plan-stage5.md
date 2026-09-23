# Stage 5 — Premium Pricing + Allocation

- [ ] Add premium_rate to Benefit model (benefits table)
- [ ] Add premium to MemberBenefit model (election premium, computed)
- [ ] Register changes in app/models/__init__.py
- [ ] Extend RBAC (view_premiums, manage_premiums)
- [ ] Premium calculation service (premiums.py): per-member, per-policy totals
- [ ] API (premiums.py): policy premium detail, per-member, set election amount
- [ ] Wire router into main.py
- [ ] Create templates (partials/premium_detail.html, update member coverage elect form)
- [ ] Link member detail → premium coverage, policy → premium summary
- [ ] Extend smoke test (rate, elect units, compute premium, broker 403)
- [ ] Run smoke test & fix issues
- [ ] Commit

## Context

Stage 4 (benefits + member elections) lets a member elect a benefit, but the
"election_amount" / "coverage_amount" columns are unused for money — there is no
premium calculation anywhere. Stage 5 is the deferred work: **price elections**.

Per the plan in Stage 4's "Deliberately out of scope":

> Pricing / premium allocation per member or per product. Deferred.

The confirmed model (per-unit rate on the benefit):

- `Benefit.premium_rate` — catalog-level rate per unit, set by the underwriter
  when they add or edit a benefit.
- `MemberBenefit.election_amount` — units (or a base) the member elected.
- Per-member premium = `election_amount × benefit.premium_rate`.
- `Policy.premium` — sum of all member premiums for that policy (currently a
  never-populated placeholder). This stage populates it.

## Scope for this stage
- Add a `premium_rate` column to `Benefit` (nullable per-unit rate).
- Add a `premium` column to `MemberBenefit` storing the computed per-member
  premium (stored alongside the amount so we don't lose the historical value
  when the catalog rate changes).
- Compute and expose:
  - per-member premium,
  - per-policy premium total,
  - the election premium.
- Underwriter manages premiums (`manage_premiums`); brokers view them
  (`view_premiums`).

## Deliberately out of scope
- Invoicing / payment processing. Deferred.
- Late-payment or lapse automation tied to premium. Deferred.
- Coverage-tier / benefit-variant variants. Not modeled.

## Model design
`benefit.premium_rate` — `Numeric(12, 4)` nullable. Per-unit rate in catalog
currency. Added to the `benefits` table (portable core types; DB-level index on
Postgres).

`member_benefit.premium` — `Numeric(12, 2)` nullable. Computed per-member premium
stored on the election so historical premium isn't lost when the catalog
`premium_rate` changes later.

## RBAC (auth.py `_ROLE_PERMISSIONS`)
- underwriter: add `view_premiums`, `manage_premiums`.
- broker: add `view_premiums` (no `manage_premiums`).

## API (under `/api/premiums`)
All JSON + HTMX-partial, matching existing `products`/`policies`/`members` style.
- `GET /api/premiums/policy?policy_id=...` → JSON {policy_id, total, breakdown: [...]},
  requires `view_premiums`.
- `GET /api/premiums/member?member_id=...` → JSON {member_id, premium},
  requires `view_premiums`.
- `GET /api/premiums/detail` → HTMX partial (per-member election + premium table),
  optional `?policy_id=` or `?member_id=`, requires `view_premiums`.
- `POST /api/premiums/elect-amount` (form) → set `election_amount` on a
  MemberBenefit and recompute that member's premium, requires `manage_premiums`;
  enforces the benefit belongs to the member's product; raises 400 otherwise;
  logs `premium_recompute`.

## Services (app/services/premiums.py)
- `per_member_premium(db, member_benefit_id)` → float: `election_amount × premium_rate`
  (0 if either is None).
- `policy_premium(db, policy_id)` → dict {total, breakdown: [{member_id, amount}]}.
- `set_election_amount(db, *, member_benefit_id, amount)` → MemberBenefit; sets
  `election_amount`, recomputes `premium`; raises ValueError on unknown or
  cross-product election.

## UI
- `templates/partials/premium_detail.html` — per-member election + premium table
  with an amount edit form.
- `templates/partials/member_coverage.html` — add an `election_amount` field so a
  member can set units at election time.
- `templates/auth/dashboard.html` — set the "Coverage" sidebar link to
  `hx-get="/api/premiums/detail"`.

## Tests
Extend `test_smoke.py`: underwriter creates a product → adds a benefit with
`premium_rate=0.10` → creates a policy → enrolls a member → elects a benefit with
`election_amount=100` → verifies per-member premium = `100 × 0.10 = 10.00` and
policy total = `10.00`. Then register a broker and assert a broker's
`manage_premiums` attempt returns 403. Keep DB reset idempotency.

## Notes / assumptions
- `election_amount` on `MemberBenefit` is a nullable base unit (default 1 is the
  responsibility of the caller; the service treats it as given).
- Premium rate is a catalog attribute set by the underwriter; no discount or
  member-specific override in this stage.
