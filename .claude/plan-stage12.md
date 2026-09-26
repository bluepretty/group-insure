# Stage 12 — Mid-Term Census: Life Events, Additions/Removals, and Proration

## Why

A group policy is a living thing. Members get added or removed mid-year — a new hire,
a dependent born, someone leaving the employer. The policy premium is a live sum of its
members' premiums, so every census change alters what the policyholder owes. So far this
project has **no way to model those mid-term changes**: `enroll_member` is a one-time
initial enrollment, no one tracks *why* or *when* a member's coverage changed, and the
billing snapshot (an invoice issued once per policy period) never accounts for a member
joining or leaving partway through.

This stage adds:

1. A **life-event log** that records *why* and *when* coverage changed (the audit trail).
2. **Add** and **remove** member/dependent operations that work mid-policy-cycle
   (not just initial enrollment).
3. A **proration engine** that translates a membership change into a premium
   *adjustment* and links it to billing — issuing a corrected invoice (or an
   adjustment credit) for the remaining policy period.
4. **Notifications** (audit log + optional email) fired on each census change.

## Context / conventions (grounded in the codebase)

- **Server-rendered Jinja2 + HTMX app** (Bootstrap 5.3.3, HTMX 2.0.4, no SPA). New UI
  plugs into the existing `partials/member_list.html` partial, loaded into `#content`,
  mirroring the `hx-get` / `hx-target="#content"` pattern already used by the preview
  and statement buttons.
- **Member** (`models/member.py`) is scoped to a policy (`policy_id`, `party_id`,
  `organization_id`), has `member_number` unique per policy, and `status` in
  `active | inactive | terminated` with `effective_date` / `termination_date`. It
  elects exactly one `MemberBenefit` (`member_benefits`), whose `election_amount ×
  benefit.premium_rate` gives the member's annual premium.
- **Premiums** (`services/premiums.py`): `policy_premium` sums member premiums and
  `refresh_policy_premium` *computes and persists* the policy's `premium`. `Invoice`
  (`models/invoice.py`) snapshots `total_amount` from the policy premium at issue; only
  one **outstanding** invoice per policy (`invoices._outstanding_invoice`). Payment
  status is reconciled in `invoices.py` / `payments.py`.
- **RBAC** (`api/auth.py`): `manage_members`, `view_billing`, `manage_billing`,
  `view_premiums`/`manage_premiums`. Census changes are underwriter work → `manage_members`;
  the proration/billing effect is visible to `view_billing`. No new permission.
- **Audit** (`services/audit.py::record_log`) is the single logging path — `action`,
  `actor_id`, `entity`, `entity_id`, `details`. Never raises. Use a new `action` string.
- **SMTP** already works (Stage 11, `services/emails.py`, enabled in `.env` for
  `e.centrewise@gmail.com`). Reuse the same `send_*` shape; gate on config, never send
  in the test path.
- **Testing**: single additive `test_smoke.py`; extend with a Stage-12 block. `setup_test_db`
  resets the DB, so assertions must be self-contained.

## Design decisions for review (the big forks)

Before I write the parts, three decisions drive everything. These are the ones I'd want
your sign-off on:

1. **How does proration hit billing?** The policy period runs Jan 1 → Dec 31 (per the
   Policy model's `start_date`/`end_date`). Two options:
   - **(a) Corrected invoice** — void/cancel the existing outstanding invoice and issue a
     single corrected invoice for the *new* total premium over the whole period. Cleanest
     ledger (one invoice per period), but rewrites the invoice number the policyholder
     already paid.
   - **(b) Separate adjustment invoice** — leave the original invoice and issue a second
     invoice for the signed delta (positive = more owed, negative = credit).
   *The existing code enforces a **one-outstanding-invoice-per-policy invariant**:
   `invoices.create_invoice` **raises if an outstanding invoice already exists**, and
   `_outstanding_invoice` returns the first unpaid one.* So (b) isn't free — an existing
   outstanding invoice must be handled before issuing the delta invoice. Pick one:
   - **(b1)** Void the existing outstanding invoice, then issue the corrected one (a).
   - **(b2)** Allow a *second* invoice by relaxing the invariant (adjustment invoices are
     exempt from `_outstanding_invoice`/`create_invoice`'s raise).
   *My recommendation: **(a)** — it fits the one-outstanding-invoice invariant cleanly and
   avoids two unpaid lines the policyholder must reconcile.* Flag for review.

2. **What counts as a "life event"?** The log should capture the *trigger*:
   `enrollment`, `new_dependent`, `termination`, `departure`. Keep it to these four to
   start; the log is extensible (a `type` string, free `details`).

3. **Proration basis.** Simplest defensible method: **daily proration** over the policy
   period — `adjustment = new_member_annual_premium × (days_remaining / period_days)`
   for an add, and the negative of the departed member's prorated premium for a removal.
   Signed: an add that *increases* premium is a positive adjustment invoice; a removal
   producing a credit is negative.

## Part 0 — Life-event log model + `record_event`

- New `models/life_event.py`: `LifeEvent` table —
  `id, policy_id, member_id (nullable), event_type (str, e.g. "new_member")`,
  `effective_date (date)`, `actor_id (nullable, FK users)`, `details (text, nullable)`.
  `created_at` timestamp. `event_type` constrained to a small set at the service layer.
- `services/life_events.py`: `record_event(db, *, policy_id, member_id=None, event_type,
  effective_date, actor_id=None, details=None) -> LifeEvent` — inserts + records an
  audit line (`action="life_event"`). Also `list_events(db, *, policy_id=None)`.
- This is pure tracking — no billing effect yet. It's the durable "why/when" trail.

## Part 1 — Add member mid-cycle

- Extend `services/members.py::enroll_member` (or a new `census_add_member`) to accept
  an explicit `effective_date` and to record a `new_member` / `new_dependent` life event.
  Initial enrollment (no explicit date → uses policy `start_date`) keeps its existing
  behaviour; mid-term additions get the actual `effective_date`.
- Wire `POST /api/members/{policy_id}/add` (JSON + a form `/create-census`) under
  `manage_members`; returns the new member + a proration preview (see Part 3) so the UI
  can show "this will change the premium by X".
- Audit-log the enrollment.

## Part 2 — Remove member mid-cycle

- Add `services/members.py::census_remove_member(member_id, *, effective_date)` that
  flips `status` → `terminated`/`inactive`, sets `termination_date`, and records a
  `member_departed` / `dependent_departed` life event.
- Enforce: a `terminated` member cannot be re-added without a new `member_number`; a
  member with outstanding elections can still be removed (coverage ceases), and the
  proration will credit the departed member.
- Wire `POST /api/members/{member_id}/remove` under `manage_members` mirroring the
  existing `/terminate` endpoint; returns the member + proration preview.

## Part 3 — Proration engine (the core)

- `services/proration.py`:
  - `compute_proration(db, *, policy_id, member_effect: dict) -> dict` — reads the
    policy's `start_date`/`end_date`, the change's `effective_date`, the added/removed
    member's premium (via `services/premiums::per_member_premium`), and returns a signed
    prorated adjustment for the remaining period:
    `adjustment = annual_premium × remaining_days / period_days`, signed + for an add,
    − for a removal. Includes a human `reason` string and the date math.
  - `prorate_policy(db, *, policy_id, member_effect) -> dict` — calls
    `refresh_policy_premium` (recompute + persist the new policy premium), records a
    `policy_premium_adjusted` audit line, and returns the new total + adjustment.
- Daily proration over the policy period is the default (see Design decision 3). Keep it
  a single function so the basis is swappable.

## Part 4 — Link proration to billing

- `services/invoices.py`: a new `issue_adjustment_invoice(db, *, policy_id, adjustment,
  effective_date, reason)` that, per Design decision 1, **issues an adjustment invoice
  for the delta** (the chosen approach). `adjustment > 0` → a normal invoice (more owed);
  `adjustment < 0` → a negative invoice (credit). Snapshots the adjustment on the
  invoice (`total_amount` = signed adjustment, `details`/a new `adjustment_reason` column
  carry the reason). Reuse the reconciliation in `invoices.py` — payments against it
  update `paid_amount`/`status` normally.
  - **Flag for review**: does the schema need an `adjustment_reason` column on
    `Invoice`? Yes — the model currently only has `total_amount`/`paid_amount`. Add a
    nullable `adjustment_reason` (String) so the ledger explains the delta.
- The add/remove endpoints from Parts 1–2 call `prorate_policy` + `issue_adjustment_invoice`
  in one transaction, then return the adjustment summary to the UI.
- `view_billing` sees the adjustment in policy/invoice summaries; no new endpoint needed.

## Part 5 — Notifications

- Every census change fires: (1) an audit line (via `record_log`, actions
  `member_enrolled` / `member_terminated`) — the primary, always-on record; and
  (2) an **optional email** to the policyholder (reusing `send_statement`'s SMTP shape,
  but with a plain body, no PDF) — gated on `EMAIL_SMTP_ENABLED` and only when a
  policyholder email exists. Never in the test path.
- `services/emails.py`: `notify_census_change(db, *, policy_id, event_type,
  effective_date, adjustment, actor_id)` — builds a short message ("A member was added/
  removed on <date>; the policy premium is now <new>, adjusted by <delta>") and sends it
  to the policyholder's stored email if SMTP is on. Raises `EmailError` when SMTP off /
  no recipient (like `send_statement`).

## Testing

Additive `test_smoke.py` Stage-12 block, self-contained over the fixture:
- **Life event**: adding a member records a `LifeEvent` row with the right
  `event_type`/`effective_date`; removing one sets `termination_date` + `terminated`.
- **Proration**: over a fixture policy with a known Jan 1 → Dec 31 period, adding a
  member halfway through yields a positive adjustment whose value is within rounding of
  `annual_premium × remaining_days / period_days`; removing credits a negative amount.
- **Billing link**: the adjustment creates a new `Invoice` with the signed `total_amount`;
  a positive adjustment invoice is `issued`/`outstanding`.
- **RBAC**: census add/remove is `403` without `manage_members`.
- **Email**: with SMTP off, census change logs audit + does not send (no 500); the
  policyholder without an email doesn't break.

## Files touched

- `src/backend/app/models/life_event.py` (new) — `LifeEvent`
- `src/backend/app/services/life_events.py` (new) — record_event + list_events
- `src/backend/app/services/proration.py` (new) — compute_proration + prorate_policy
- `src/backend/app/services/members.py` — census_add_member / census_remove_member
- `src/backend/app/services/invoices.py` — issue_adjustment_invoice + `adjustment_reason` col
- `src/backend/app/models/invoice.py` — add `adjustment_reason` column
- `src/backend/app/services/emails.py` — notify_census_change
- `src/backend/app/api/members.py` — add/remove census endpoints under `manage_members`
- `src/backend/app/api/life_events.py` (new) — list events + audit listing partial (optional)
- `src/backend/app/templates/partials/member_list.html` — census add/remove buttons + preview
- `src/backend/static/css/style.css` — minimal styles for census preview
- `src/backend/app/api/test_smoke.py` — Stage-12 assertions
- `src/backend/app/core/config.py` — none required beyond existing SMTP (already present)
- `handoff.md`, `plan-stage12.md` — docs

## Scope notes

- Proration uses **daily proration over the policy period** (single function, basis
  swappable). No per-benefit proration in this stage — premium is a policy-level sum.
- No worker/scheduled reconciliation — the adjustment is computed synchronously at the
  moment of the census change.
- No new RBAC permission; census is underwriter (`manage_members`), the billing effect
  is visible to `view_billing`.
- Initial enrollment (policy start) keeps its existing path; mid-term is what gets the
  event log + proration.
