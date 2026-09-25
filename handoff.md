# Handoff — Stage 5 (Premium Pricing) complete, next = Stage 6

Written 2026-09-23 ~11pm. Peter is asleep; come back tomorrow.

## What just happened
Stage 5 ("Premium Pricing + Allocation") is **fully implemented, tested, and committed**
(commit `200f017`). This was the last item on the Stage 5 plan — `plan-stage5.md`.
The only thing that landed this session was wiring the **policy → premium summary**
link (the final unchecked plan item) plus the smoke-test assertion for it.

## Where to pick up
Start with `claude/plan-stage6.md` — that file is the next phase's authoritative
spec. If it isn't there yet, ask Peter what Stage 6 is before doing anything.

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
