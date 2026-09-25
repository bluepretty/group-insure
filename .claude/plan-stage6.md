# Stage 6 — Billing & Payment Processing

- [ ] Add Invoice + Payment models
- [ ] Register models in app/models/__init__.py (package imports register on Base.metadata)
- [ ] Extend RBAC (view_billing, manage_billing)
- [ ] Invoice service (services/invoices.py): create from policy total, list, get, mark issued
- [ ] Payment service (services/payments.py): record payment, reconcile invoice status
- [ ] API (api/billing.py): invoice list/get/create, issue, record payment, list payments
- [ ] Register router in main.py
- [ ] Create templates (partials/invoice_list.html, invoice_detail.html, payment_form.html)
- [ ] Wire Invoice view into the Policy detail / premium summary view
- [ ] Extend smoke test (issue invoice, record payment -> invoice paid, broker 403)
- [ ] Run smoke test & fix issues
- [ ] Commit

## Context

Stage 5 prices elections and populates `Policy.premium` as the sum of member
premiums (`services/premiums.py:policy_premium`), but the policy's `premium`
column is only mutated in-memory in that function and is never committed
(`services/policies.py` stores whatever is passed in, default `None`; the create
API never passes it). So the platform can *price* a policy but cannot *bill* a
policyholder for it.

Stage 5's "Deliberately out of scope" lists exactly this:

> Invoicing / payment processing. Deferred.
> Late-payment or lapse automation tied to premium. Deferred.

This stage closes the invoicing/payment gap and leaves the lapse automation to a
later stage. It is the "billing" row from the project's roadmap (README) and is
the smallest coherent next slice that sits directly on the Stage 5 premium totals.

Claims is deliberately **out of scope** for this stage: it is a distinct domain
(the README roadmap lists it separately), and it would need its own permissions,
models, and policy lifecycle (open → adjust → closed). Keep Stage 6 focused on
money movement.

## Scope for this stage
- Model invoices as a per-policy billing artifact whose `total_amount` is taken
  from the policy's computed premium (a policy's `premium` should be persisted by
  the policy service rather than computed in-memory only — see §Model design).
- Model payments as a per-invoice money-in record with a status.
- Reconcile invoice status from its payments (unpaid → issued when created,
  fully paid → paid, partial → partially_paid).
- Underwriters issue invoices and record payments; brokers view invoices.

## Deliberately out of scope
- Late-payment / lapse automation (deferred — see below).
- Claims (own stage).
- Refunds / partial refunds / adjustments of a paid invoice.
- Currency, tax, or multiple invoices per policy-period for now (one outstanding
  invoice per policy is the assumption; note it).

## Model design
Follow the existing conventions: portable core types, nullable money columns,
FKs to existing tables, `created_at` tz timestamps.

`invoice` — `models/invoice.py`:
- `id` int PK
- `policy_id` FK policies.id, nullable (policy is the billable unit)
- `invoice_number` String(20)
- `status` String(20) default "issued" (issued/paid/partially_paid/written_off)
- `total_amount` Numeric(12,2) — policy premium at issue time (snapshot)
- `paid_amount` Numeric(12,2) default 0 — running paid total
- `issued_date` Date nullable
- `due_date` Date nullable
- `paid_date` DateTime nullable
- `created_at` tz DateTime now() default

`payment` — `models/payment.py`:
- `id` int PK
- `invoice_id` FK invoices.id, nullable
- `amount` Numeric(12,2)
- `method` String(20) nullable (e.g. bank_transfer, check, cash, card)
- `reference` String(80) nullable (external ref / cheque number)
- `status` String(20) default "posted" (posted/void)
- `payment_date` DateTime now() default
- `created_at` tz DateTime now() default

### Persisting `Policy.premium`
Today `policy_premium` mutates `policy.premium` in place but never commits
(`services/premiums.py`), so it is transient. For Stage 6 to bill reliably,
`Policy.premium` should be a stored value. The cleanest option: compute the policy
premium at policy **create** and **status change (draft→active)** and persist it
via the policy service with an audit log, so the invoice `total_amount` has a
source of truth independent of the in-memory recompute. `set_election_amount`
(already in `services/premiums.py`) already re-derives member premiums, so it
should also refresh `Policy.premium` when the election changes. Keep the existing
in-memory recompute too, but add a `refresh_policy_premium(db, policy_id)` helper
that computes the total and commits it.

## RBAC (auth.py `_ROLE_PERMISSIONS`)
- underwriter: add `view_billing`, `manage_billing` (issue invoice, record/void
  payment).
- broker: add `view_billing` only.
(Keep existing `view_premiums`/`manage_premiums`; billing is a sibling concern to
pricing and brokers who can view premiums should be able to view the resulting
invoices.)

## API (under `/api/billing`)
All JSON + HTMX-partial, matching `premiums`/`policies`/`members` style. All
billing reads/writes require a billing permission.

- `GET /api/billing/invoices` → JSON list of invoices (policy_number, status,
  totals, dates), requires `view_billing`. Supports `?policy_id=` filter.
- `GET /api/billing/invoices/{id}` → invoice detail (with its payments), requires
  `view_billing`.
- `GET /api/billing/invoices/create-form` → HTMX partial: form to issue a new
  invoice for a `?policy_id=` (prefilled `total_amount` from policy premium),
  requires `view_billing`.
- `POST /api/billing/invoices` → create an invoice for a policy (status
  `issued`, `total_amount` from policy premium), `manage_billing`; logs
  `invoice_issued`. Raises 400 if policy unknown or already has an outstanding
  (unpaid) invoice.
- `POST /api/billing/invoices/{id}/void` → mark written_off, `manage_billing`;
  logs `invoice_void`.
- `POST /api/billing/payments` → record a payment against `invoice_id`
  (`Form` fields: invoice_id, amount, method, reference, payment_date),
  `manage_billing`; recomputes invoice `paid_amount`/`status` and logs
  `payment_recorded`. Raises 400 if amount <= 0 or invoice unknown.
- `POST /api/billing/payments/{id}/void` → void a posted payment, `manage_billing`.
- `GET /api/billing/payments` → JSON list of payments, requires `view_billing`.

### Status reconciliation
After create / payment / void: `paid_amount == total_amount` → `paid`;
`0 < paid_amount < total_amount` → `partially_paid`; `paid_amount == 0` → `issued`.
Persist the invoice status inside the same commit as the payment update (atomic).

## Services
`services/invoices.py`:
- `list_invoices(db, *, policy_id=None)` → list.
- `get_invoice(db, invoice_id)` → Invoice (or raise).
- `create_invoice(db, *, policy_id, issued_date=None, due_date=None)` → Invoice:
  snapshots `Policy.premium` into `total_amount` (compute+persist policy premium
  first), sets status `issued`, commits, logs `invoice_issued`. Raises
  ValueError if policy unknown or an outstanding invoice already exists.

`services/payments.py`:
- `list_payments(db)` → list.
- `record_payment(db, *, invoice_id, amount, method=None, reference=None)` → Payment:
  validates invoice exists and amount > 0, persists, reconciles invoice status via
  `_reconcile_invoice`, commits, logs `payment_recorded`.
- `void_payment(db, payment_id)` → sets status void, reconciles, commits, logs
  `payment_void`.
- `_reconcile_invoice(db, invoice_id)` → reads payments for the invoice, sets
  `paid_amount` and `status`, commits.

Shared:
- `refresh_policy_premium(db, policy_id)` in `services/premiums.py`:
  computes Σ member premiums, sets `Policy.premium`, commits, logs
  `policy_premium_refresh` (used by invoice create, `set_election_amount`, and
  policy status changes).

## UI
- `partials/invoice_list.html` — table of invoices (policy, number, status,
  total, paid, due) with a link per row to detail.
- `partials/invoice_detail.html` — invoice header + payments table + "Record
  payment" form.
- `partials/payment_form.html` — payment form for a given invoice_id.
- Wire into the policy premium summary (`partials/policy_premium.html` from Stage
  5): add an "Invoices" button → `hx-get="/api/billing/invoices?policy_id=..."`
  swapping `#content`, mirroring the existing Premiums wiring.

## Audit
Every mutating action calls `record_log(db, action=..., actor_id=<user.id>,
entity=..., entity_id=..., details=...)` inside/after the committing service,
matching the pattern in `services/policies.py:75` and others. Add a
`view_dashboard`-gated view of recent activity if a billing log action type is
new and we want it surfaced (low priority; the audit_recent endpoint already
renders any action).

## Tests
Extend `app/api/test_smoke.py` (after the Stage 5 block): underwriter issues an
invoice for the active policy (total = the 10.00 from the Stage 5 election) →
assert invoice list returns it with status issued and `total_amount` 10.00 →
record a full payment of 10.00 → assert invoice status is now paid and
`paid_amount` is 10.00 → record a second (invalid) payment of 100 → assert 400 →
register a broker and assert billing reads work for the underwriter while a
broker's `manage_billing` attempt returns 403. Keep the DB reset idempotent.

Also add a service-level assertion that `refresh_policy_premium` persists
`Policy.premium` (the previously-transient value) — this closes the specific gap
flagged by Stage 5.

## Assumptions / open questions (for Peter)
- One outstanding invoice per policy (no multi-period invoicing yet).
- `Policy.premium` becomes a persisted field rather than a pure recompute — confirm
  that's acceptable; it is the source of truth the invoice snapshots.
- No late-payment or lapse automation in this stage (carried over from Stage 5).
