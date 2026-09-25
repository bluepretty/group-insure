# Stage 7 — Claims

- [ ] Add Claim model (claims table)
- [ ] Register Claim in app/models/__init__.py
- [ ] Extend RBAC (view_claims; reuse manage_claims for underwriter)
- [ ] Claims service (services/claims.py): list, get, create, mark under review, adjudicate, close
- [ ] API (api/claims.py): claim list + partial, claim detail, create (form), adjudicate, close
- [ ] Register router in main.py
- [ ] Wire "Claims" dashboard nav link (was a dead placeholder) to the list partial
- [ ] Extend smoke test (raise claim, adjudicate, broker view-only / cannot create)
- [ ] Run smoke test & fix issues
- [ ] Commit

## Context

Every stage since 1 has touched claims only nominally: Stage 1 granted underwriters
the `manage_claims` permission but nothing consumes it, and the dashboard has a
`Claims` sidebar link that points at `hx-get="#"` (a dead placeholder). plan-stage6
explicitly deferred claims, calling them "its own stage" that needs "its own
permissions, models, and policy lifecycle (open → adjust → closed)".

This stage implements that smallest coherent slice: a claim is a record raised
against a policy for a covered benefit, tracked through a small lifecycle, and
adjudicated by an underwriter. A broker can view claims for policyholders'
policies they can already see.

## Scope for this stage
- Model a **claim** tied to a policy and, optionally, to a member + the specific
  benefit being claimed against.
- Lifecycle: `open` → `under_review` → (`paid` | `denied`) → `closed`
  (closed is terminal).
- Underwriter creates claims and adjudicates them (setting a payout `paid_amount`);
  brokers view claims.
- Full audit trail via `record_log` for every mutating action.

## Deliberately out of scope (next stages)
- Broker-side claim creation (brokers raising claims for members). This stage is
  underwriter-raised only; a later stage may let brokers file.
- Payments of adjudicated claims against the billing/invoice system (Stage 6
  invoices are separate; a future stage can reconcile a paid claim to a payment).
- Document attachment / supporting-file upload.
- Denial reasons taxonomy (keep a free-text `reason`).
- Reporting / aggregate dashboards (the "Reports" nav placeholder also stays).

## Model design
`claim` — `models/claim.py`, following existing conventions (portable core types,
FKs, nullable money columns, `created_at`/`updated_at` tz timestamps):

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| policy_id | FK policies | not null (a claim is always against a policy) |
| member_id | FK members | nullable (most claims are member-specific, but a claim can be policy-level) |
| benefit_id | FK benefits | nullable (which covered benefit triggered the claim) |
| status | String(20) | "open" | "under_review" | "paid" | "denied" | "closed"; default "open" |
| claim_amount | Numeric(12,2) | requested/admitted amount, nullable |
| paid_amount | Numeric(12,2) | adjudicated payout, default 0 |
| reason | Text | nullable free text |
| created_at | tz DateTime | |
| updated_at | tz DateTime | refreshed on every mutation |

## RBAC (auth.py `_ROLE_PERMISSIONS`)
- Reuse the existing `manage_claims` for underwriters (create + adjudicate +
  close) — it is already declared and currently unused.
- Add `view_claims` to **both** roles.
- Underwriter: `manage_claims` (already present) + `view_claims`.
- Broker: `view_claims` only (no `manage_claims`).

Brokers see only claims on policies within their `view_policies` scope; the
list endpoint's `party_id` filter (already used elsewhere) enforces this.

## Service (app/services/claims.py)
- `list_claims(db, *, policy_id=None, member_id=None)` → list[Claim].
- `get_claim(db, claim_id)` → Claim | None (raises ValueError if missing).
- `create_claim(db, *, policy_id, member_id=None, benefit_id=None, claim_amount=None, reason=None)` → Claim:
  raises ValueError on unknown policy; sets status "open"; logs `claim_create`.
- `mark_under_review(db, claim_id)` → Claim: `open` → `under_review`; raises
  ValueError if transition invalid; logs `claim_under_review`.
- `adjudicate(db, *, claim_id, paid_amount)` → Claim: requires status
  `under_review`; sets `paid_amount`; status → `paid` if paid_amount > 0 else
  `denied`; logs `claim_adjudicate` with the payout.
- `close_claim(db, claim_id)` → Claim: `paid`/`denied` → `closed` (terminal);
  raises ValueError otherwise; logs `claim_close`.
- A single `_allow_transition(db, claim, to_status)` guard enforces the state
  machine:
  - open → under_review
  - under_review → paid | denied
  - paid → closed
  - denied → closed
  - closed → (terminal)

## API (under `/api/claims`, JSON + HTMX-partial like premiums/billing)
All reads require `view_claims`; all writes require `manage_claims`.
- `GET /api/claims?policy_id=...&member_id=...` → JSON list, `view_claims`.
- `GET /api/claims/list` → HTMX partial (optional `?policy_id=`), `view_claims`.
- `POST /api/claims` (form: policy_id, member_id, benefit_id, claim_amount, reason) → create, `manage_claims`; raises 400 on unknown policy.
- `GET /api/claims/{claim_id}` → detail partial, `view_claims`; 404 if missing.
- `POST /api/claims/{claim_id}/review` (form) → mark under review, `manage_claims`.
- `POST /api/claims/{claim_id}/adjudicate` (form: paid_amount) → adjudicate, `manage_claims`.
- `POST /api/claims/{claim_id}/close` (form) → close, `manage_claims`.
- Invalid transition / already-closed → 400 (raise ValueError → JSONResponse 400), matching the premiums/billing error pattern.

## UI
- `partials/claim_list.html` — table of claims (policy, member, benefit, status, claimed, paid) with a per-row detail link.
- `partials/claim_detail.html` — claim header + status + adjudication form (set paid_amount + adjudicate) + close form, gated on `can_manage`.
- Wire the existing `Claims` dashboard nav link to
  `hx-get="/api/claims/list"?hx-target="#content"` instead of `hx-get="#"`.

## Audit
Every mutating service action calls `record_log(db, action=..., actor_id=<user.id>,
entity="Claim", entity_id=claim.id, details=...)`, matching the pattern in
`services/policies.py` / `services/premiums.py`.

## Tests
Extend `test_smoke.py` (append after the Stage 6 block, before the final
`print`): underwriter creates a product → party → active policy → enrolls a
member with a benefit → files a claim (claim_amount 500) → list returns it as
"open" → mark under review → adjudicate with paid_amount 300 → status is "paid"
→ close → status is "closed"; then register a broker and assert a broker's
create/adjudicate attempt returns 403 while their claim list (via a visible
policy) returns 200. Keep DB reset idempotent.

## Assumptions / open questions (for Peter)
- Lifecycle is `open → under_review → paid|denied → closed`. Confirm this matches
  how you want claims tracked, or want it flattened (e.g. `open → closed` with a
  `denied`/`paid` status on close).
- Claims are underwriter-raised only this stage; broker-filed claims are out of
  scope.
- `paid_amount` is a free numeric; reconciling adjudicated claims back to
  billing/payments is deferred.
