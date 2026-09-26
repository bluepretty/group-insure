# Stage 13 — Policy Renewal: extending a policy term

## Why

A policy has a fixed term: `Policy.start_date` → `Policy.end_date`. Stages 9, 10, 11
added the *downward* lifecycle — a non-paying policy lapses, lapses can be reinstated,
and a long-lapsed policy is closed. Stages 3, 6, 12 added creation, billing, and
mid-term census changes. But a healthy policy that **completes its term** had nowhere
to go: the only move after `end_date` is `close`, which kills it. There was no way to
continue coverage into a new year.

This stage adds **renewal**: extend a settled, active policy past its `end_date` into a
new term and bill the next term. It is the missing inverse of `close` (Stage 9) and
completes the story that "a policy has a life cycle."

## Context / conventions (grounded in the codebase)

- **Policy model** (`models/policy.py`): `policy_number`, `product_id`, `party_id`,
  `organization_id`, `status` in `draft | active | lapsed | closed`,
  `status_changed_at`, `start_date`/`end_date` (nullable on purpose), `premium`
  (`Numeric(12, 2)`). `start_date`/`end_date` already exist — no schema change.
- **Lifecycle** (`services/policies.py`): `VALID_STATUSES = ("draft","active","lapsed","closed")`
  and `_ALLOWED` transitions (`draft→active`, `active→lapsed`, `lapsed→{active,closed}`,
  `closed→{}`). `change_policy_status` validates the transition, stamps `status_changed_at`,
  and logs `policy_status_change`. `close_policy` (Stage 9) is the `lapsed→closed` path;
  renewal is a sibling, not a new status.
- **Premium refresh** (`services/premiums.py`): `refresh_policy_premium(db, *, policy_id)`
  recomputes and persists `policy.premium` from the roster, logging `policy_premium_refresh`.
  `create_invoice` calls it internally.
- **Invoices** (`services/invoices.py`): `create_invoice(db, *, policy_id, issued_date?,
  due_date?)` → refreshes the premium, snapshots `total_amount`, and **refuses to issue if
  an outstanding (unpaid) invoice already exists** (the one-outstanding-invoice-per-policy
  invariant). If the policy is `lapsed`, issuing a new invoice reinstates it.
  **The billing fork is (b2)** — census proration issues a *separate* signed `-ADJ`
  adjustment invoice, exempt from that invariant. Renewal stays clean of the proration
  path; the adjustment invoice is untouched here.
- **RBAC** (`api/auth.py`): `manage_policies` drives the policy lifecycle. Renewal is an
  underwriter action.
- **Templates**: `templates/partials/policy_list.html` renders per-policy action buttons
  (Reinstate / Close / Lapse / Preview / Download / Email) via `can_manage`/`can_view_statement`.
  Renewal plugs into the same buttons.
- **Testing**: single additive `test_smoke.py`; extend with a Stage-13 block. `setup_test_db`
  resets the DB, so assertions must be self-contained.

## Design decisions for review

1. **When can a policy be renewed?** Only an **active** policy whose current term is
   **fully settled** (no outstanding/unpaid invoice). Rationale:
   - `create_invoice` already refuses to issue while an outstanding invoice exists, so
     renewal must bill a settled term or it 400s regardless.
   - Renewing an active-but-unsettled policy would leave two overlapping terms both
     outstanding — contradicting the one-outstanding-invoice invariant.
   - A **lapsed** policy has two paths already: pay off → reinstatement, or lapse past the
     grace window → close. Renewing *before* settlement would conflate those. So renewal is
     `active` + settled; a lapsed party renews after reinstating.
   This keeps renewal a narrow, well-defined action rather than a catch-all.
2. **How is the term extended?** Renewal extends the *period*: the new term starts the day
   after the current `end_date` (`new_start == end_date + 1 day`, enforced) and runs to a
   new `new_end` (must be later than `new_start`, and must not overlap the current term).
   The policy's `start_date`/`end_date` are rewritten to the new term.
3. **What premium is billed for the new term?** Either an explicit `premium` is passed, or
   the premium is refreshed from the current roster (`refresh_policy_premium`). Either way
   it is persisted on the policy before issuing the invoice, so the policy and any statement
   reflect the renewed term. `create_invoice` bills `policy.premium`.
4. **Due date for the new invoice?** `new_end + 30 days` by default (a full-year term billed
   at its end, 30-day payment window). Injectable/overridable at the service level.

## Part 0 — `renew` service

`services/policies.py::renew(db, *, policy_id, new_start: date, new_end: date, premium?) -> dict`:

- Validates: new term is `active`, has `start_date`/`end_date`, `new_start == end_date + 1 day`,
  `new_end > new_start`, and no outstanding invoice (else `ValueError`).
- Rewrites `start_date`/`end_date` to the new term; applies `premium` or refreshes it and
  persists `policy.premium`.
- Calls `create_invoice(db, policy_id, issued_date=new_start, due_date=new_end + 30d)`.
- Logs `policy_renewed` with the new term and invoice number.
- Returns `{policy_id, new_start, new_end, premium, invoice_number, invoice_total}`.

## Part 1 — API

`api/policies.py::policy_renew` — `POST /{policy_id}/renew` under `manage_policies`; Form
fields `new_start`, `new_end` (ISO date strings, `YYYY-MM-DD`), optional `premium`.
Returns `200` JSON with the renewal summary; `400` JSON on `ValueError` (bad term,
unsettled policy, unknown id). Mirrors `policy_close`.

## Part 2 — UI

`templates/partials/policy_list.html` — add a **Renew** button, shown for active, fully-settled
policies (`can_manage and policy.status == 'active'` and no outstanding invoice), posting
`{policy_id}/renew` with new term inputs; the form is revealed inline next to the existing
Reinstate/Close/Lapse controls so the new term is entered on the policy row.

## Testing

Additive `test_smoke.py` Stage-13 block:

- Renew an active, fully-settled policy: `200`, period extended to the new term, policy
  `status == 'active'`, a new invoice exists with the billed premium, and an audit line
  `policy_renewed` is written.
- Renewing before the term is settled → `400` (one-outstanding-invoice invariant preserved).
- Renewing with a bad term (`new_start != end_date + 1 day`, or `new_end <= new_start`) → `400`.
- A broker (no `manage_policies`) → `403`.

## Files touched

- `src/backend/app/services/policies.py` — `renew`
- `src/backend/app/api/policies.py` — `POST /{policy_id}/renew`
- `src/backend/app/templates/partials/policy_list.html` — Renew button
- `src/backend/app/api/test_smoke.py` — Stage-13 assertions
- `handoff.md` — Stage 13 section
- `.claude/plan-stage13.md` — this plan

## Scope notes

- No new status; renewal is a sibling of `close_policy`, not a new lifecycle node.
- Renewal does not touch the census proration path — the billing fork stays (b2); the `-ADJ`
  adjustment invoice is unchanged.
- Reinstatement (pay-off → `active`) is unchanged; a lapsed party renews only after reinstating.
