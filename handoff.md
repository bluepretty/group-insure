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


## Stage 10 (Closed Lapsed Policies) — complete, committed
- Spec: `.claude/plan-stage10.md`. The small sibling to Stage 9: closes the loop
  so an unresolved lapse terminates the policy (`lapsed -> closed`) rather than
  pinning it forever in `lapsed`. `_ALLOWED` already modelled the edge; nothing
  triggered it. This only makes it reachable and gated by a grace window.
- Service: `src/backend/app/services/policies.py` — `close_policy(db, *, policy_id,
  today=None)` raises `ValueError` unless the policy is unknown, not lapsed, or
  inside the grace window, then calls `change_policy_status(..., "closed")`
  (logs `policy_closed`); `_lapsed_for(db, policy, today=None)` is the
  day-count seam used by both `close_policy` and the service-level test.
  `GRACE_DAYS = 30` module constant. `change_policy_status` now sets
  `status_changed_at` on every transition, so the grace window is measured from
  when the policy actually went `lapsed`, not from `start_date`.
- Model: `src/backend/app/models/policy.py` — new nullable
  `status_changed_at: datetime` on `Policy`, set by `change_policy_status`.
  Nullable + no migration (existing DB); a policy only ever reaches `lapsed`
  by transitioning from `active`, so the column is populated.
- API: `src/backend/app/api/policies.py` — `POST /api/policies/{id}/close`,
  underwriter-gated (`manage_policies`), `ValueError` → 400 JSON, returns
  `{policy_id, status}`. Imported lazily to keep the smoke import path cheap.
- UI: `templates/partials/policy_list.html` — **Close** button (after
  Reinstate, `btn-outline-secondary`, warning title) shows only when
  `can_manage and policy.status == 'lapsed'`; `hx-post`s the close endpoint and
  reloads on success.
- Smoke test: `src/backend/app/api/test_smoke.py` added a Stage 10 block —
  API asserts auto-lapse then a too-recent close returns 400 and the broker
  returns 403; service-driven with injected `today` asserts inside-the-window
  refusal, close past the window, and the closed policy's terminal state.
  **1 passed.**
- No background sweep, no grace-timer service, no `void_policy` — that's a later
  lapse follow-up. `GRACE_DAYS` is a module constant (not runtime config) in v1.


## Stage 11 (Policy Statement: PDF, Inline Preview, Email) — complete, committed
- Spec: `.claude/plan-stage11.md`. Three faces of one read-only roll-up; the
  statement is a policy's reconciliation document. Single source of truth for
  email validation (`services/validators.py::validate_email`) applied on entry to
  every external record — Party, Organization, User.
- Validation: `services/validators.py` — `validate_email(value)` is the single
  source of truth: strips, lowercases, returns `None` for empty/missing, raises
  `ValueError` for anything that isn't a syntactically valid email. No record
  type drifts on what "valid" means.
- Part 0 (email on every record): `models/party.py`, `models/organization.py`,
  `models/user.py` — new nullable `email: str` on each (nullable so the smoke DB
  and existing rows are unaffected). `services/parties.py::add_party` — optional
  `email` param, validated before construction. `api/parties.py::create_party` and
  `party_create` — pass/validate `email` (`Form(None)`), `ValueError` → 400 JSON.
  `api/auth.py::register` — `RegisterModel.email` now validated; `ValueError` → 400
  JSON. A malformed address returns `400`, a valid one is stored lower-cased.
- Part 1 (builder): `services/statements.py::build_statement(db, *, policy_id) ->
  dict` — read-only, plain-Python roll-up of Policy / Party / Organization /
  Product / Invoice / Payment; returns `{policy_number, status, start_date,
  end_date, premium, product_name, organization_name, policyholder_name,
  policyholder_email, invoices[], total_invoiced, total_paid, balance_outstanding,
  as_of}`. Money rounds to 2 dp; a nullable/None column contributes 0.0 so an
  empty policy still renders a coherent statement. Raises `ValueError` for an
  unknown policy_id. `render_statement_pdf(stmt) -> bytes` — one ReportLab pass
  over the same dict, so the PDF and the HTML preview always agree on numbers.
- Part 2 (renderer): ReportLab 5.0.1 in-memory only, no file to disk, no third
  party assets. Added `reportlab>=4.0.0` to `pyproject.toml`.
- Part 3 (preview/download): `api/statements.py` — `GET /{id}/statement` renders
  the HTML partial (`partials/statement.html`, gated on `view_billing`) that loads
  inline into `#content`; `GET /{id}/statement.pdf` streams `application/pdf` with
  an inline disposition (`render_statement_pdf`). Both route the builder through a
  `_statement()` helper that maps an unknown policy_id to `400` (not 500), so
  `GET /{id}/statement.pdf` returns 400 for a missing id. Registered in
  `main.py`; `products` import order corrected (`alphabetical`) to match.
- Part 4 (frontend): `templates/partials/policy_list.html` — per policy a Preview
  button (`hx-get=/api/policies/{id}/statement`, `hx-target="#content"`) and a
  **Download** link to `{id}/statement.pdf`; both gated by new `can_view_statement`
  (`view_billing`) passed from `api/policies.py::policy_list`. `templates/partials/
  statement.html` — the rendered statement has a **Print** button
  (`window.print()`) and, when `can_send`, an **Email statement** button carrying
  `{policy-number, policyholder-email}`; policy/invoice summaries plus paid/billed
  columns. `static/css/style.css` — new `@media print` block: prints a
  page-sized PDF (0.75in margins), hides `.no-print`/sidebar/buttons so only the
  `.statement` node renders.
- Part 5 (email delivery): `services/emails.py` — `send_statement(db, *, policy_id,
  to_email=None, actor_id=None) -> dict` builds one `MIMEMultipart` with the PDF
  as an attachment, sends via `smtplib` using `core.config` SMTP settings, and
  records `record_log(action="statement_sent", ...)`. `api/statements.py` —
  `POST /{id}/statement/send`, confirm-gated (`SendStatementModel` defaults
  `confirm: true`) + `manage_billing`; returns 400 JSON on `ValueError` (unknown
  id) or `RuntimeError` (SMTP disabled / no recipient). `core/config.py` — SMTP
  settings (`smtp_enabled` etc.) default to disabled, so the send path 400s in dev
  rather than attempting a real send.
- The statement is always emailed to the policyholder's stored, validated email
  (`stmt['policyholder_email']`) — never a free-form address at send time.
- Smoke test: `api/test_smoke.py` added a Stage 11 block — malformed email on a
  party → 400; a valid address stored lower-cased; `build_statement` returns
  non-zero `total_invoiced`/`total_paid`; preview renders (`200`, policy number in
  body) and the broker can view (`view_billing`) but the send is `403` (needs
  `manage_billing`); `.pdf` returns `application/pdf` with `%PDF` magic; confirm-
  send with SMTP disabled → `400` (no `sent`); unknown policy → `400`. **1 passed.**

## Stage 12 (Mid-Term Census: Life Events, Add/Remove, Proration) — complete, committed
- Spec: `.claude/plan-stage12.md`. A group policy is a living roster: members join
  and leave mid-cycle, and the policy premium is a live sum of member premiums. Before
  this stage there was **no way to model mid-term changes** — `enroll_member` was a
  one-time initial enrollment, nothing tracked *why/when* coverage changed, and the
  once-per-period invoice never accounted for a mid-year add/remove.
- **Billing fork (resolved as b2):** the original invoice stands; a census change issues
  a **separate signed adjustment invoice** for the delta, exempt from the one-outstanding-
  invoice-per-policy invariant. `adjustment > 0` (add) → a normal invoice (more owed);
  `adjustment < 0` (removal) → a negative credit invoice. An outstanding invoice is not
  reissued — the delta is a second line.
- Proration basis — **daily proration over the policy period**:
  `adjustment = annual_premium × (days_remaining / period_days)`, both counts inclusive of
  the effective date; signed + for an add, − for a removal. Single `prorate_policy` in
  `services/proration.py` so the basis stays swappable.
- Part 0 (model + log): `models/life_event.py` — `LifeEvent` table (`id, policy_id,
  member_id nullable, event_type, effective_date, actor_id nullable, details, created_at`);
  `event_type` constrained to `new_member/new_dependent/member_departed/dependent_departed`
  at the service layer. `services/life_events.py` — `record_event(db, *, policy_id,
  member_id, event_type, effective_date, actor_id, details)` inserts the row and mirrors an
  audit line (`action="life_event"`); `list_events(db, *, policy_id, event_type)`.
- Part 1 (add): `services/census.py::census_add` — enrolls mid-cycle (via `enroll_member` +
  optional `elect_benefit`), records a `new_member`/`new_dependent` life event, recomputes
  and persists the policy premium, prorates the delta, and issues an adjustment invoice.
  `api/members.py::member_add` (`POST /api/members/{policy_id}/add`, `manage_members`) —
  Form endpoint; returns the member-list partial + a summary (event, effective date,
  proration counts, signed adjustment, adjustment invoice number).
- Part 2 (remove): `census_remove` — terminates the member, sets `termination_date`,
  records a `member_departed`/`dependent_departed` event, credits the prorated departure,
  and issues a negative adjustment invoice. `api/members.py::member_remove` (`POST
  /api/members/{member_id}/remove`, `manage_members`) mirrors the existing `/terminate`
  endpoint.
- Part 4 (billing link): `services/invoices.py::issue_adjustment_invoice` snapshots the
  signed adjustment (`total_amount` = signed delta, `adjustment_reason` carries the reason);
  a new nullable `adjustment_reason` column on `Invoice` (`models/invoice.py`). The add/remove
  endpoints call `prorate_policy` + `issue_adjustment_invoice` in one transaction.
- Part 5 (notifications): every census change fires a `record_log` audit line (`member_enrolled`
  / `member_terminated`) and an **optional** email to the policyholder's stored, validated
  email (`services/emails.py::notify_census_change`) gated on `smtp_enabled`; best-effort,
  never raises, never in the test path.
- Frontend: `templates/partials/member_list.html` — census add form (policy / first / last /
  member-number / relationship / effective-date / benefit / election-amount) posts to
  `/api/members/{policy_id}/add`; per-member **Remove** button to `/remove`; a live-change
  summary alert shows event, effective date, premium increase/decrease, proration day counts,
  and the adjustment invoice number. `templates/partials/life_events.html` (new) — the durable
  "why/when" log table rendered by `api/life_events.py::life_events`
  (`GET /api/members/life-events?policy_id=`, `view_members`).
- Smoke test: `api/test_smoke.py` added a Stage 12 block — over a dated Jan 1 → Dec 31
  fixture policy, an add on Jul 1 records a `new_member` life event and issues a positive
  adjustment invoice whose value is within rounding of `annual × remaining/period`; a removal
  credits a negative adjustment; the departed member is `terminated` with `termination_date`;
  the adjustment invoice exists with the signed `total_amount`; census add/remove is `403`
  without `manage_members`; SMTP off logs audit + does not send. **1 passed.**
- Security: professional accounts only (underwriter); census add/remove gated on
  `manage_members`; the adjustment/billing effect is visible to `view_billing`. JWT secret in
  `.env` (gitignored at repo root line 24).
- Security: professional accounts only (underwriter/broker); JWT secret in `.env`
  (gitignored at repo root line 24); `.env` never committed. `reportlab` is a
  hard runtime dependency now (was previously working in the venv without the
  pyproject entry).
