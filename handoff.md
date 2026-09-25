# Handoff — Stage 9 (Policy Lapse) complete

> **UPDATE 2026-09-25 ~11:25pm: Stage 9 is now COMMITTED.** Committed
> `5c1fb45` — 10 files, +299 / −13. Billing → policy lifecycle: an unpaid invoice
> past `due_date` lapses an active policy, full payment reinstates it
> (`lapsed → active`), and reissuing while lapsed re-activates. New
> `GET /api/policies/{id}/lapse-check` (`manage_policies` gate); UI shows a Lapse
> button / lapsed badge / Reinstate button. Smoke test green (1 passed).
> See `.claude/plan-stage9.md`. The content below this banner is the original
> kickoff note; kept as history. The next phase is to define the following stage.
>
> **Done this session (Peter, late ~11pm):** wired the `policy_list.html`
> Reinstate + Lapse buttons, made `policy_list`/`policy_create` pass the
> `outstanding`/`invoices` dicts the partial needs, fixed the smoke test's
> broken `pytest` invocation and a `policy_create` UndefinedError, ran it green
> (1 passed), and committed the whole Stage 9 change. `.claude/plan-stage9.md`
> had listed the `policy_list.html` Reinstate button as in-progress — it's done
> now; mark it done there.

Written 2026-09-23 ~11pm. Peter is asleep; come back tomorrow.

## What just happened
Stage 5 ("Premium Pricing + Allocation") is **fully implemented, tested, and committed**
(commit `200f017`). This was the last item on the Stage 5 plan — `plan-stage5.md`.
The only thing that landed this session was wiring the **policy → premium summary**
link (the final unchecked plan item) plus the smoke-test assertion for it.

## Where to pick up
Start with `claude/plan-stage9.md` — that file is the next phase's authoritative
spec. If it isn't there yet, ask Peter what Stage 9 is before doing anything.

## Run tests (do this first tomorrow)
```
cd src/backend
PYTHONPATH=. ~/.venv/bin/python -m pytest api/test_smoke.py -v
```
Run **from `src/backend`** (templates/static are resolved relative to there). The
`httpx`/lifespan deprecation warnings are noise — 1 passed is green.

## Stage 5 files (committed)
- `src/backend/app/api/premiums.py` — `/policy`, `/member`, `/detail`, `/elect-amount`,
  `/rate`, and `/policy-html` (the new policy summary partial).
- `src/backend/app/services/premiums.py` — `per_member_premium`, `policy_premium`
  (populates `Policy.premium` + breakdown), `set_election_amount` (cross-product guard).
- `src/backend/app/templates/partials/premium_detail.html` — per-member election + premium table.
- `src/backend/app/templates/partials/premium_picker.html` — choose a member picker.
- `src/backend/app/templates/partials/policy_premium.html` — rendered policy premium summary.
- `src/backend/app/templates/partials/policy_list.html` — now has a "Premiums" button
  → `hx-get="/api/premiums/policy-html?policy_id=..."` → swaps `#content`.
- `src/backend/app/api/test_smoke.py` — Stage 5 coverage (rate 0.10, units 100 → premium
  10.00, per-member + policy totals, policy-html partial, broker 200-view / 403-manage).

## Confirmed domain model (don't re-litigate)
- `Benefit.premium_rate` (Numeric 12,4, nullable) — catalog per-unit rate, underwriter-set.
- `MemberBenefit.election_amount` (Numeric 12,2, nullable) — units the member elected.
- Per-member premium = `election_amount × premium_rate`; `MemberBenefit.premium`
  (Numeric 12,2) stores it so historical premium survives catalog rate changes.
- `Policy.premium` = sum of member premiums for that policy.
- One benefit elected per member — unique index on `MemberBenefit.member_id`; uniqueness
  also enforced in `set_election_amount` / election service.
- Security: professional accounts only (underwriter/broker); JWT secret in `.env`
  (gitignored at repo root line 24); `.env` never committed.

## Known quirks
- Newer FastAPI: `app.routes` entries are `_IncludedRouter` wrappers (no `.path`); verify
  via the smoke test, not route introspection.
- `list_policies` filters by `party_id` when given; bare scripts against shared Postgres
  have collided on leftover rows (e.g. "POL-001 already exists") — the smoke test uses a
  fresh in-memory DB so it's authoritative.
- `set_benefit_rate` / `set_election_amount` raise `ValueError` → endpoints return 400.

## Stage 6
- **Complete (2026-09-25). Committed.** Billing & payment processing: invoice + payment models, `view_billing`/`manage_billing` RBAC, invoice/payment services, `/api/billing` router, invoice partials, premium-summary → Invoices link. Smoke test covers Stage 6 (issue invoice → 10.00, full payment → paid, broker view vs 403 manage). See `claude/plan-stage6.md`.
- Previously in progress (2026-09-25): Peter delegated scope; was being implemented.

## Stage 7 (Claims) — complete, committed
- Spec: `claude/plan-stage7.md`. Lifecycle: `open → under_review → paid|denied → closed`
  (`closed` is terminal). Enforcement lives in the service layer; the API stays thin.
- Models: `src/backend/app/models/claim.py` (`Claim`, nullable `policy/member/benefit` FKs,
  `claim_amount`/`paid_amount` Numeric 12,2, `reason`, tz timestamps). Registered in
  `models/__init__.py`.
- RBAC: `view_claims` added to BOTH underwriter and broker; `manage_claims` stays underwriter-only.
- Service: `src/backend/app/services/claims.py` — `list_claims`, `get_claim`, `create_claim`,
  `mark_under_review`, `adjudicate`, `close_claim`. Raises `ValueError` → 400. FK lookups use
  the actual `Member`/`Benefit` models (not string table names).
- API: `src/backend/app/api/claims.py`, registered in `main.py`. JSON list = `GET /api/claims`,
  detail = `GET /api/claims/{id}`, actions = POST `/review` `/adjudicate` `/close`.
  HTMX partials = `GET /api/claims/list` and `GET /api/claims/detail`. `detail` sets
  `can_manage = _has_permission(user, "manage_claims")`.
- Templates: `templates/partials/claim_list.html`, `claim_detail.html` (gated action buttons).
  Wired the previously-dead **Claims** dashboard nav → `hx-get="/api/claims/list"`.
- Smoke test: added a Stage 7 block (file → open, list, fetch, review → under_review,
  adjudicate 300 → paid, close → closed, closed is terminal [400], unknown → 404,
  unknown policy → 400; broker can view [200] but not create/adjudicate [403]). **1 passed.**
- Quirks (same as before): new FastAPI `app.routes` are `_IncludedRouter` wrappers — verify via
  the smoke test, not introspection; `ValueError` → 400; smoke test uses a fresh in-memory DB.

## Stage 8 (Reports) — complete, committed
- Spec: `claude/plan-stage8.md`. Decisions locked in: open_policies = active + lapsed
  (draft excluded); claims_open = open + under_review; gate on existing
  `view_dashboard` (no new `view_reports` perm); platform-wide snapshot for v1.
- Service: `src/backend/app/services/reports.py` — one `build_report(db) -> dict`, a
  single read pass over Policy / Member / MemberBenefit / Benefit / Claim /
  Invoice / Party tables. Returns a flat dict with counts + money totals
  (`open_policies`, `enrolled_premium`, `claims_open`, `invoiced_total`, `paid_total`,
  `outstanding_total`, …). `_positive_number()` keeps nullable columns from raising on
  an empty DB.
- API: `src/backend/app/api/reports.py` — JSON `GET /api/reports` + HTMX-partial
  `GET /api/reports/list`, both gated on `view_dashboard`. Registered in `main.py`.
- UI: `templates/partials/report_list.html` (reports grouped into Enrollment / Coverage /
  Claims / Billing sections). `templates/auth/overview_partial.html` — the four overview
  stat cards now pull from `report` instead of hard-coded `—`. `dashboard.html` — the dead
  **Reports** nav link (`hx-get="#"`) → `hx-get="/api/reports/list"`.
- Smoke test: added a Stage 8 block asserting a well-formed report dict (all keys present,
  counts are ints ≥ 0, totals ≥ 0), reflecting fixture data (`active_policies/policies/members
  ≥ 1`, `enrolled_premium/policy_premium ≥ 10.00`, `claims_total ≥ 1`, `invoiced/paid ≥ 10.00`),
  the partial renders, the broker can read (view_dashboard) but an unauth read is refused, and
  the dashboard page renders without any `—` in the card bodies. **1 passed.**
- Note: the smoke fixture terminates its only member (Stage 4), so `active_members == 0` is
  correct — the report asserts on total members, not active ones. Claim is fully adjudicated
  and closed by the time Stage 8 runs, so `claims_open == 0` and `claims_paid == 0` too; the
  test asserts on `claims_total` / `claims_closed` / `claims_paid_total`.

