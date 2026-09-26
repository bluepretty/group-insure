# Stage 14 — Claims Management (rework of Stage 7)

> Status: **planned**, awaiting approval.
>
> The committed Stage 7 claims feature is being **repurposed**, not replaced by a
> new table. One source of truth: the existing `Claim` table becomes the real,
> business-shaped claim model.

## 0. What to read first (already done)

- `.claude/plan-stage14.md` — this file.
- `src/backend/app/models/claim.py` — current (Stage 7) Claim: `open→under_review→paid|denied→closed`, `claim_amount`/`paid_amount`/`reason`.
- `src/backend/app/services/claims.py` — Stage 7 service (`create_claim`/`mark_under_review`/`adjudicate`/`close_claim`).
- `src/backend/app/api/claims.py` — Stage 7 router + JSON + HTMX partials.
- `src/backend/app/api/auth.py` (`_ROLE_PERMISSIONS`) — **already** defines `view_claims` (underwriter + broker) and `manage_claims` (underwriter only). No RBAC change needed.
- `src/backend/app/services/reports.py` — `build_report` maps `Claim.status` using the old vocabulary; must be updated.
- `src/backend/app/templates/partials/claim_list.html`, `claim_detail.html` — old fields + lifecycle; full rewrite.
- `src/backend/app/templates/auth/dashboard.html:16` — the **Claims** sidebar link already exists (`hx-get="/api/claims/list"`). No new nav link is needed.
- `src/backend/app/api/test_smoke.py` — the Stage 7 smoke block (lines ~427-544) gets rewritten to Stage 14.

## 1. Scope

Per the kickoff (`group-insure` / Peter, 2026-09-25):

1. Model & DB on the existing `Claim` table, scoped to a `Policy` + a `Member` of that policy. New attributes: `claim_number` (unique, service-generated), `incident_date`, `amount_claimed`, `amount_approved`, `status` (`submitted`, `approved`, `rejected`, `paid`), `description`, timestamps. Validate `incident_date` ∈ policy active term `[start_date, end_date]` and the member is active.
2. RBAC: `view_claims` (broker + underwriter) + `manage_claims` (underwriter only).
3. Service layer `services/claims.py`: `list_claims`, `get_claim`, `submit_claim`, `update_claim_status`.
4. API `api/claims.py`: submit, list (filtered by policy/party for brokers), detail, status (underwriter-gated). JSON + HTMX partials.
5. UI: Claims sidebar link (exists already), HTMX list/detail partials + submit/adjudicate forms.
6. Smoke test: register underwriter/broker → create policy → enroll member → submit claim → underwriter approves/rejects → broker 403 on approval attempt.

## 2. Key decisions

### 2.1 Reuse and repurpose the existing `Claim` table (confirmed)
Peter chose "reuse Claim table, repurpose it" over (a) a second coexisting table or (b) cramming old+new fields onto the same rows. The Stage 7 status machine and claim-amount/paid-amount/reason columns are **superseded** by the Stage 14 vocabulary and columns. `claim.benefit_id` is retained (a claim can target a specific elected benefit); `claim.member_id` is now **required** (a claim is always scoped to a member).

### 2.2 `claim_number` — auto-generated in the service layer
Modeled after `services/invoices.py::_NEXT_INVOICE` (`"CLM-1", "CLM-2", …`), module-level counter with a `CLM-` prefix. Uniqueness is **checked in the service layer** (no DB-level constraint yet — matches member/policy-number convention and avoids a migration on an existing DB). The submit endpoint does **not** take `claim_number` from the caller; the service stamps it.

### 2.3 Lifecycle: `submitted → approved → paid` and `submitted → rejected`
```
submitted ──approve──▶ approved ──pay──▶ paid
     └──reject────────────────────────────▶ rejected   (rejected is terminal)
```
`approved` and `rejected` are both terminal "decision" states. Approval sets `amount_approved` (≤ `amount_claimed`); a payout action promotes `approved → paid` (carrying `amount_approved` forward). `rejected` is terminal. This is a decision-and-payout model, not a review queue — hence no `under_review`.

### 2.4 Business validation (new vs. Stage 7)
`submit_claim` raises `ValueError` unless:
- the policy exists and is within its active term (`start_date ≤ incident_date ≤ end_date`);
- the member exists, belongs to that policy, and is `active`.
These are the scope's validation requirements and are the main functional growth over Stage 7.

### 2.5 Reports knock-on (the only "side" file)
`services/reports.py::build_report` currently buckets `claim.status in ("open","under_review")`, `== "paid"`/`"denied"`/`"closed"`, and sums `paid_amount`. Update it to the new vocabulary — **all report keys are unchanged**, only the bucket definitions change:
- `claims_open`: `submitted` + `approved` (awaiting finalization — the "not yet decided" set).
- `claims_paid`: `paid`.
- `claims_denied`: `rejected` (Stage 7's "denied" maps to the new "rejected").
- `claims_closed`: **finalized** = `paid` + `rejected`. The new lifecycle has no literal "closed" state, so "closed" is read as "closed out / finalized" — this is what the smoke assertion `claims_closed >= 1` (Stage 8 block) expects, and it's satisfied once a claim reaches `paid`.
- `claims_paid_total`: sum of `amount_approved` over `paid` claims (not `paid_amount`).
The keys (`claims_total`/`claims_open`/`claims_paid`/`claims_denied`/`claims_closed`/`claims_paid_total`) are unchanged, so `overview_partial.html` and `report_list.html` need no changes.

### 2.6 No RBAC or nav-link changes
`view_claims`/`manage_claims` already exist in `auth.py` exactly as the scope describes, and the **Claims** sidebar link already exists in `dashboard.html`. Stage 14 keeps both as-is; the smoke test just re-gates on the same permissions.

## 3. Implementation plan

### 3.1 Model — `src/backend/app/models/claim.py`
Rewrite `Claim` to:
- `claim_number: String(60)` — generated, unique.
- `policy_id` (non-null FK, required scope).
- `member_id` (non-null FK, required — a claim is always scoped to a member).
- `benefit_id: Optional[int]` (nullable FK — optional benefit target).
- `incident_date: Date` — the claim event date.
- `amount_claimed: Numeric(12,2)`.
- `amount_approved: Numeric(12,2)` — set on approval, nullable until then.
- `status: String(20)` default `"submitted"`.
- `description: Text` nullable.
- `created_at`, `updated_at` (tz-aware).
Keep `policy`/`member`/`benefit` relationships for template display. Reassign the class docstring to the new lifecycle; drop `claim_amount`/`paid_amount`/`reason` references. (No Alembic — tables come from `create_all`, so the smoke test picks up the new columns automatically.)

### 3.2 Service — `src/backend/app/services/claims.py`
Replace the Stage 7 service with:
- `_next_claim_number()`: in-memory counter → `CLM-{n}`, mirroring `invoices.py::_NEXT_INVOICE`.
- `list_claims(db, *, policy_id=None, member_id=None, party_id=None)` — filter set; `party_id` scopes to policies held by a policyholder Party (brokers list their own clients' claims).
- `get_claim(db, claim_id)` — `ValueError` on unknown.
- `submit_claim(db, *, policy_id, member_id, amount_claimed, incident_date, benefit_id=None, description=None, claim_number=None)`:
  - existence checks (policy, member-of-policy) → `ValueError`;
  - term check (`start_date ≤ incident_date ≤ end_date`) → `ValueError`;
  - member-active check → `ValueError`;
  - uniqueness check on `claim_number` → `ValueError`;
  - build row with a generated `claim_number`, `status="submitted"`, `amount_approved=None`;
  - `record_log(action="claim_submit", …)`; return row.
- `update_claim_status(db, claim_id, *, status, amount_approved=None)`:
  - state-machine guard via a `_TRANSITIONS` dict: `submitted → {approved, rejected}`, `approved → {paid}`;
  - on `approved`, require `amount_approved` (0 < amount ≤ amount_claimed) and set it;
  - on a transition into `paid`, carry `amount_approved` forward (require it set);
  - `record_log(action="claim_status_change", details=f"{from}->{status}", …)`; return row.

### 3.3 API — `src/backend/app/api/claims.py`
Keep `router = APIRouter(prefix="/api/claims", tags=["claims"])` (already registered in `main.py`). Replace handlers:
- `POST /` (JSON, Form-capable) — `submit_claim`; gated on `view_claims` so **both underwriters and brokers** can submit (`manage_claims` is only for status changes). `ValueError` → 400 JSON.

  **RBAC split (per scope):** submit = `view_claims` (broker + underwriter can file); status changes = `manage_claims` (underwriter only). This is why the broker's 403 in the smoke test is on the **approval** attempt (`/status`), not on submit.
- `GET /list` (HTMX) — list scoped with `policy_id`/`member_id`/`party_id`; `view_claims`; context sets `can_manage` for adjudicate buttons.
- `GET /` (JSON) — list (optional filters).
- `GET /detail` (HTMX) — `get_claim` + `can_manage`; renders `partials/claim_detail.html`.
- `GET /{claim_id}` (JSON) — detail.
- `POST /{claim_id}/status` (JSON + Form) — `update_claim_status`; `manage_claims`; `ValueError` → 400 JSON; returns updated claim.
- Optionally a `POST /{claim_id}/submit` (Form) for the HTMX submit form.
Response models updated to new fields (`claim_number`, `incident_date`, `amount_claimed`, `amount_approved`, `status`, `description`).

### 3.4 Templates
Rewrite (do not patch) the two partials to the new vocabulary:
- `partials/claim_list.html` — columns: claim number, policy id, member id, incident date, status, amount claimed, amount approved. Detail link → `/api/claims/detail?claim_id=`.
- `partials/claim_detail.html` — field display + adjudication form shown when `can_manage and status == 'submitted'` (approve with amount-approved input; reject). On `approved`, a "Pay" button posts to `/status` with `status=paid`. On `rejected` show a read-only terminal badge.
- `partials/claim_submit.html` — a form that posts `POST /` (Form) with policy/member/amount/incident-date/benefit/description; returns the list partial on success. (Implemented in practice inside `claim_list.html` — "Submit a claim" card — rather than as a separate partial, so drop line 147's separate partial.)
- Wire the existing **Claims** nav link (already in `dashboard.html`) to the new list partial — no change beyond verifying it renders.

### 3.5 Smoke test — `src/backend/app/api/test_smoke.py`
Replace the Stage 7 smoke block (lines ~427-544) with a Stage 14 block. **Two fixture notes are required:**

1. **The fixture's `members[0]` is terminated at line 172** (Stage 6/12), so `submit_claim`'s "member active" validation would 400 against it. Enroll a **fresh active member** (a second `POST /api/members/create` before the claims block) and file/claim against that one; assert its DB row is `active`.
2. **The Stage 8 report block asserts `claims_closed >= 1`.** With the repurposed model `claims_closed` = finalized (`paid`+`rejected`), drive the claim to `paid` (approve → pay) before the report block lands. Keep the report keys asserted exactly as-is (the keys are unchanged).

New block asserts:
- `POST /api/claims` JSON `{policy_id, member_id, amount_claimed, incident_date, description}` → 200; response carries a `CLM-…` `claim_number` (starts with `CLM-`); `status == "submitted"`; `amount_claimed` echoed.
- List (`GET /api/claims?policy_id=`) returns it; detail (`GET /api/claims/{id}`) returns it.
- Underwriter approve: `POST /api/claims/{id}/status {status:"approved", amount_approved=…}` → 200, `status == "approved"`, `amount_approved` set (and ≤ `amount_claimed`).
- Approve → pay: `POST …/status {status:"paid"}` → 200.
- Reject path: a fresh submitted claim → `rejected` → 200, terminal; a further transition 400.
- Validation: an incident date **outside** the policy term → 400; a claim against a **terminated/non-roster** member → 400; unknown policy → 400; unknown claim detail → 404.
- Broker 403 on the approval/status attempt (`/status` — `manage_claims`), and broker can view list/detail and **submit** a claim (`view_claims`) with 200.
- Audit: assert a `claim_submit` (and `claim_status_change`) audit line was recorded.
Preserve all other stages intact — they share the in-memory DB and the repurposed `Claim` table must not break the Stage 8 report-key assertions or the Stage 12/13 fixtures.

### 3.6 Reports — `src/backend/app/services/reports.py`
Update the status buckets and the paid-total as in 2.5. Keys unchanged.

### 3.7 main.py / wiring
No change — `claims.router` is already included and the partials dir is the Jinja root. Only re-point the repurposed templates at the new endpoints (done in 3.4).

## 4. What changes vs. the committed Stage 7 (so the diff stays sane)
- `models/claim.py`: full rewrite (columns + docstring).
- `services/claims.py`: full rewrite (new lifecycle, validation, claim_number).
- `api/claims.py`: replace handlers + response models (same router/prefix).
- `templates/partials/claim_list.html`, `claim_detail.html`: full rewrite (submit form lives in `claim_list.html`, not a separate partial).
- `services/reports.py`: edit the 6 status/total lines.
- `api/test_smoke.py`: rewrite the Stage 7 block.
- **No** change to `auth.py` (perms already correct), `main.py` (router already included), `dashboard.html` (nav link already present).

## 5. Verification
```
cd src/backend
PYTHONPATH=. ~/.venv/bin/python -m pytest api/test_smoke.py -v
```
Expect **1 passed**. Then a manual smoke: register underwriter + broker, create a dated policy, enroll a member, file a claim, approve → pay; and confirm a broker gets 403 approving.

## 6. Post-implementation
- Update `handoff.md` with a "Stage 14 (Claims)" section.
- Update `README.md` stage list (add Stage 14; Stage 7's old claims mention — if listed — is now superseded; check the README before editing).
- Commit: `feat: Stage 14 — claims management (repurposed Stage 7)` with attribution line.
