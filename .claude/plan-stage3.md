# Stage 3 — Member Enrollment

## Context
Stage 2 added the product catalog and group policies with a lifecycle. But a
"group" policy is only as useful as its enrollees. This stage introduces
**members** (enrollees) — the individual people covered under a policy — plus the
CRUD + enrollment flow. This is the "Enrollment" placeholder in the dashboard
sidebar.

Members are scoped to a policy. A broker can only see members of policyholders'
policies they can already view; underwriters manage enrollment.

## Scope for this stage
- Member model + minimal attributes (identity, coverage, lifecycle).
- Enroll / terminate flows with audit logging.
- List members filtered by policyholder party (so broker scoping works via the
  existing `view_policies` party filter).
- Wire an "Enrollment" nav link + an HTMX partial.
- RBAC: `view_members` (brokers + underwriters), `manage_members` (underwriters).
- Smoke test: enroll, list, terminate, broker 403.

## Deliberately out of scope
- Product coverage elections per member (which benefits a member actually
  holds). That ties members to product benefit tiers — Stage 4.
- Member eligibility / effective-date automation. Kept manual for now.
- Roster import (CSV). Deferred.
- Benefits split / premium allocation per member. Deferred.

## Model design
Single new table `members`, scoped to a policy:

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| policy_id | FK policies | not null |
| party_id | FK parties | denormalized so list can filter by policyholder |
| organization_id | FK organizations | tenant scope, nullable |
| member_number | str(60) | unique per policy (enforced in service) |
| first_name, last_name | str(80) | required |
| date_of_birth | Date | nullable |
| gender | str(20) | nullable, optional |
| relationship | str(40) | e.g. self / spouse / dependent |
| status | str(20) | "active" | "inactive" | "terminated", default "active" |
| effective_date | Date | nullable |
| termination_date | Date | nullable |
| created_at | UTC datetime | |

Policy-number uniqueness is enforced in the service layer (a DB-level unique
index is added when switching to Postgres). Same pattern already used for
policy numbers in `services/policies.py`.

## RBAC (auth.py `_ROLE_PERMISSIONS`)
- underwriter: add `view_members`, `manage_members`.
- broker: add `view_members` (no `manage_members`).

## API (all under `/api/members`, HTMX + JSON like policies)
- `GET /api/members` → JSON list (response_model), requires `view_members`.
- `GET /api/members?party_id=...` → JSON list, filtered by policyholder.
- `GET /api/members/list` → HTMX partial (policy list view), optional `party_id`.
- `POST /api/members` → JSON create (for API clients).
- `POST /api/members/enroll` (form) → enroll, returns partial, requires `manage_members`.
  - Enforce member_number uniqueness per policy; log `member_enroll`.
- `POST /api/members/{id}/terminate` (form) → terminate with a date, log `member_terminate`, returns JSON.

## Services (app/services/members.py)
- `list_members(db, *, party_id=None)`
- `get_member(db, member_id)`
- `enroll_member(db, *, policy_id, party_id, organization_id=None, member_number, first_name, last_name, date_of_birth=None, relationship=None, effective_date=None)` — raises ValueError on unknown policy or duplicate number; logs `member_enroll`.
- `terminate_member(db, member_id, termination_date=None)` — logs `member_terminate`.

## UI
- `templates/partials/member_list.html` — form to enroll + table of members with terminate buttons.
- `templates/auth/dashboard.html` — set the "Enrollment" sidebar link to `hx-get="/api/members/list"`.
- Keep the "Enrolled Members" card as-is for now (count shown later, or left as a placeholder).

## Tests
Extend `test_smoke.py`: register underwriter → create product → party → policy →
enroll a member → list → terminate. Then register a broker and assert a broker's
member-enroll attempt returns 403. Keep DB reset idempotency.

## Verification
1. `uv run pytest src/backend/app/api/test_smoke.py` — all pass.
2. Boot `cd src/backend && uv run uvicorn app.main:app --reload`, log in as
   underwriter, open Enrollment, enroll a member on an active policy, then log in
   as broker and confirm you can view (but not enroll).

## Notes / decisions
- Members are intentionally thin; richer attributes (SSN masking, address,
  contact) come later.
- Termination is the only lifecycle op here (Stage 2 policy lifecycle is separate).
  Adding member "inactive" (lapse) or reinstatement can be a later refinement.
- Member scoping by broker currently relies on the policyholder party id; full
  broker→party routing (Stage 4).

## Commit
When approved, commit Stage 3 with message "Stage 3: member enrollment CRUD, RBAC, HTMX" then `Co-Authored-By`.
