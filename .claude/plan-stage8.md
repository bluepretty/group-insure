# Stage 8 — Reports / Aggregate Dashboard

- [x] Add reports service (services/reports.py): one `build_report(db) -> dict` aggregating across policies, members, benefits, claims, invoices
- [x] Extend RBAC — gate on `view_dashboard` (both roles); see §RBAC
- [x] API (api/reports.py): JSON `GET /api/reports` + HTMX-partial `GET /api/reports/list`
- [x] Register router in main.py
- [x] Populate the 4 overview stat cards in `auth/overview_partial.html` from the same service
- [x] Wire the dead **Reports** dashboard nav link to `hx-get="/api/reports/list"`
- [x] Extend smoke test (well-formed report dict, non-negative counts/totals, reflects fixture data)
- [x] Run smoke test & fix issues (1 passed)
- [x] Commit

## Context

Every navigation link on the dashboard is wired except one:

```
app/templates/auth/dashboard.html:17
  <a class="nav-link" href="#" hx-get="#" hx-target="#content">Reports</a>
```

The dashboard home (`overview_partial.html`) shows four stat cards —
Policyholders, Active Policies, Enrolled Members, Open Claims — each with a
hard-coded `—` and no data wired in. So the dashboard is *live* for every
section except its own headline cards and the cross-cutting Reports view.

Everything the report needs already exists and is already queryable:

- `Policy.status` ∈ `("draft","active","lapsed","closed")`; `Policy.premium`
  (persisted at issue/election time, Stage 6).
- `Member.status` ∈ `("active","inactive","terminated")`.
- `MemberBenefit.premium` (in-force elected premium, Stage 5).
- `Claim.status` ∈ `("open","under_review","paid","denied","closed")`.
- `Invoice.total_amount` / `paid_amount` / `status` (Stage 6).

There is no reporting concern expressed anywhere else that is more concrete than
"make the platform's own totals visible." So this stage closes that gap with a
single aggregate snapshot the Reports page and the dashboard cards both render.

## Scope for this stage
- Build **one** aggregation function over the existing tables and return a flat
  dict of counts + money totals (no new tables, no new columns).
- Serve it as JSON (`GET /api/reports`) and as an HTMX-partial
  (`GET /api/reports/list`) to match the other list endpoints.
- Wire the dead Reports nav link to the partial.
- Populate the four existing overview stat cards from the same service so the
  dashboard home stops showing "—".
- Keep it a **static aggregate snapshot**: no date-range filtering, no export,
  no drill-down detail rows yet.

## Deliberately out of scope (later stages)
- Charts / graphs (SVG/Canvas bar or line charts). Start with cards + table.
- Date-range / time-series aggregation.
- Export (CSV/PDF) of the report.
- Per-product, per-policyholder, or per-member breakdown pages.
- A dedicated `/reports` page distinct from the HTMX partial; the partial is
  swapped into `#content` like every other section.
- Row-level report access scoping to a single policy; this dashboard shows the
  whole platform (professional admin tooling).

## Service design — `services/reports.py`
A single function, no class:

```python
def build_report(db) -> dict:
    ...
```

Aggregate over all rows once and bucket by status in Python (the tables are
small in this product; keep it readable and testable rather than pushing
`group_by` into SQL). Define bucket membership explicitly:

- `policyholders` = len(Party)
- `policies` = len(Policy); `active_policies` (`"active"`), `lapsed_policies`
  (`"lapsed"`); `open_policies` = live = `active` + `lapsed` — **`draft` and
  `closed` are excluded** (draft is an un-formalized concept and `closed` is
  gone; only live policies count).
- `members` = len(Member); `active_members` (= status "active").
- `enrolled_premium` = Σ MemberBenefit.premium (in-force coverage).
- `policy_premium` = Σ Policy.premium.
- `claims`: `claims_total`, `claims_open` (status ∈ `("open","under_review")` —
  anything not yet finalized counts as in-progress), `claims_paid` (== "paid"),
  `claims_denied` (== "denied"), `claims_closed`.
- `claims_paid_total` = Σ Claim.paid_amount where status == "paid".
- `invoiced_total` = Σ Invoice.total_amount; `paid_total` = Σ Invoice.paid_amount;
  `outstanding_total` = invoiced_total − paid_total.

Money values round to 2 decimals. Use a `_positive_number(value)` helper
(`float(value) if value else 0.0`) so a nullable column never raises on an empty
DB. The dict returned by `build_report` is the single contract the JSON endpoint,
the partial, and the cards all consume.

## RBAC (auth.py `_ROLE_PERMISSIONS`)
- Gate on the **existing `view_dashboard`** permission — no new permission. This
  is a cross-domain dashboard roll-up, and v1 keeps a single permission gate
  rather than adding one per section. Both underwriter and broker already hold
  `view_dashboard`, so both can see the report.

Rationale: Peter confirmed v1 should reuse the existing dashboard/view permission
rather than introduce a dedicated `view_reports`. Both roles already have
`view_dashboard`, which is sufficient.

## API (under `/api/reports`)
- `GET /api/reports` → JSON `build_report(db)`, gated on `view_dashboard`. Returns
  the flat dict from §Service design.
- `GET /api/reports/list` → HTMX-partial (`partials/report_list.html`),
  gated on `view_dashboard`.
- Empty data (no policies/claims/invoices) must return zeros, not 400/500 — the
  service is called on a fresh platform too.

## UI
- `partials/report_list.html` — the same cards as the dashboard
  (`overview_partial.html`), plus a small "Premiums & Billing" and "Claims"
  subgroup so the page reads as a report rather than four lonely cards. Reuse
  the existing Bootstrap card markup; iterate over the report dict, formatting
  money with `${{ "%.2f"|format(x) }}`.
- `overview_partial.html` — replace the four hard-coded `—` values with the real
  numbers from `build_report(db)` threaded through the dashboard route
  (`pages.py` `dashboard`), so the home page and the Reports page share one
  source of truth.
- `dashboard.html` — change the **Reports** link from `hx-get="#"` to
  `hx-get="/api/reports/list"`.

## Audit
None required this stage — reporting is read-only aggregation over data with its
own audit trail.

## Tests
Extend `test_smoke.py` (after the Stage 7 block). By this point the fixture has
an active policy with a 10.00 premium, one invoice issued and paid, and at
least one claim. Assert, on `GET /api/reports` as underwriter:
- status 200; response is a dict with all keys from §Service design.
- every count is an int ≥ 0; every total is a number ≥ 0.
- `active_policies >= 1`, `policies >= 1`, `members >= 1`.
- `invoiced_total >= 10.00` and `paid_total >= 10.00` (the Stage 6 invoice).
- `enrolled_premium >= 10.00` (the Stage 5 election).
- a broker's read of the report returns 200 (via `view_dashboard`).
Also assert `overview_partial.html` now renders a number (not "—") by hitting
the dashboard page once — optional, low priority.

## Assumptions / open questions (for Peter)
- Resolved: `open_policies` excludes `draft` and `closed` (live = active + lapsed).
- Resolved: `claims_open` groups `open` + `under_review`.
- Resolved: gate on existing `view_dashboard` (no new `view_reports` permission).
- Resolved: platform-wide point-in-time snapshot for v1 (no per-policy/date
  filtering; charts/graphs and CSV/PDF export are later-stage).
