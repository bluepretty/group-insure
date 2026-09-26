# Stage 11 — Policy Statement: PDF, Inline Preview, and Email

## Why

The policy/billing lifecycle is complete (Stage 9 lapse + Stage 10 close). The
natural next step is for underwriters and brokers to **see and deliver** a policy's
reconciliation document: a statement of policy, invoices, payments, and balance.
They must be able to preview it in-app (print/zoom), download it as a PDF, and —
when a policyholder email is on file — email it (confirm-first). Email is a
first-class, validated field on every external record, so the recipient of a
statement is always a validated address.

## Context / conventions (grounded in the codebase)

- **Server-rendered Jinja2 + HTMX app** (Bootstrap 5.3.3, HTMX 2.0.4 via CDN, no SPA).
  Preview is a Bootstrap modal loaded into `#content` via the existing `hx-get`
  pattern in `policy_list.html`.
- **No policy detail page exists** — the only place to attach a preview is the
  per-policy button row in `partials/policy_list.html` (each button loads an HTML
  partial into `#content`). This stage adds the preview/download/email controls there.
- **RBAC**: `view_billing` (broker) / `manage_billing` (underwriter) already exist in
  `api/auth.py` — use them to gate statement-view vs. send. No new permission.
- **Party** is the base for both policyholder and broker (Party has `party_type`,
  `organization_id`, `broker_id`). Policyholder Party links to `organization_id`.
  **User** (register/login) and **Organization** exist too; email must be validated on
  all three where it is entered.
- **`build_report`** (`services/reports.py`) is the read-only pattern to mirror: it
  reads Policy/Member/Benefit/MemberBenefit/Claim/Invoice/Party and returns a flat
  dict with rounded money. `build_statement` reads Policy/Party/Organization/Product/
  Invoice/Payment.
- **Billing**: invoices via `/api/billing/invoices` (policy_id + optional due_date);
  one outstanding invoice per policy (`_outstanding_invoice`); payments via
  `/api/billing/invoices/{id}/payments`. `payments` table has date/method/reference/
  amount/status.
- **Config**: `GROUP_INSURE_` env prefix via `core/config.py`; SMTP disabled by default
  so dev/test never attempts a real send (returns 400).
- **Testing**: single additive `test_smoke.py`; add a Stage-11 block; `setup_test_db`
  resets the DB, so assertions must be self-contained (register a policyholder Party
  with a valid email, build a policy, issue/pay an invoice, then assert on the
  statement + PDF + send guard).

## Part 0 — Validated email on every external record

Email is optional but **must be valid when present**, on policyholder Party, broker
Party, Organization, and User. Add a single shared validator and apply it at entry.

- `src/backend/app/services/validators.py`: `validate_email(value) -> str | None`.
  Empty/None → `None`. Non-empty must be a syntactically valid email (a focused regex
  is fine), lowercased and stripped, else `ValueError`. This is the single source of
  truth — no record type drifts.
- Add a nullable `email: str | None` column to `Party`, `Organization`, `User`.
- Wire `validate_email` into entry points:
  - **Party** — `/api/parties` (JSON create) and `/api/parties/create` (Form) gain an
    optional `email`; `services/parties.py add_party` calls `validate_email` and raises
    `ValueError` → 400. Both policyholder and broker Party go through this path.
  - **User** — register gains optional `email`; validated at entry.
  - **Organization** — validate where an org is entered (add column + apply validator at
    the org create path if one exists; otherwise add the column + validator and wire the
    create path this stage).
- The statement must be emailed to the policyholder Party's **stored, validated email**
  — never free-form at send time.

## Part 1 — Statement data service

`src/backend/app/services/statements.py`, following `build_report`:

```
build_statement(db, *, policy_id) -> dict
```
Reads Policy / Party / Organization / Product / Invoice / Payment (read-only), raises
`ValueError` for an unknown `policy_id`. Returns a plain dict with: policy metadata
(number, status, dates, premium), policyholder org name, policyholder Party name +
email, per-invoice lines (invoice_number, status, total, paid, due, balance), per-invoice
payment history (date/method/reference/amount), and running totals (total invoiced, paid,
balance outstanding).

## Part 2 — ReportLab PDF renderer

`render_statement_pdf(stmt: dict) -> bytes` using `reportlab` (add to `pyproject.toml`).
Single-pass `Canvas`/`SimpleDocTemplate`: header (title, policy number, generated date),
sections for policy summary / policyholder / invoices table / payments, footer with
totals. Money formatted `${:,.2f}`.

## Part 3 — Preview + download endpoints

`src/backend/app/api/statements.py` (register in `main.py`):
- `GET /api/policies/{id}/statement` — renders `statement.html` via `TemplateResponse`
  (200, HTML). Gated on `view_billing`. This is what the Preview button loads into the
  Bootstrap modal.
- `GET /api/policies/{id}/statement.pdf` — ReportLab bytes, `Content-Type: application/pdf`,
  inline disposition so the browser's print/zoom works. Gated on `view_billing`.

## Part 4 — Frontend: preview modal + buttons

- `partials/policy_list.html` — extend the per-policy button row with **Preview** (hx-get
  modal), **Download** (plain link to `.pdf`), and **Email** (opens confirm modal). Mirror
  the existing `hx-target="#content"`/`hx-swap` button style; buttons show for anyone with
  `view_billing` (brokers included).
- `partials/statement.html` — printable statement layout matching Part 1/2 sections, with
  a "Print" button that calls `window.print()` (native zoom + print, no JS PDF lib).
- `static/css/style.css` — minimal `@media print` block so the preview prints cleanly.

## Part 5 — Confirm+send email (with attachment)

Outward-facing and hard-to-reverse, so confirm-gated and refused cleanly when SMTP is
unavailable.

- `core/config.py` — SMTP settings, all disabled/off by default:
  `EMAIL_SMTP_ENABLED`, `EMAIL_SMTP_HOST/PORT`, `EMAIL_SMTP_USER/PASSWORD`,
  `EMAIL_SMTP_USE_TLS`, `EMAIL_FROM`.
- `services/emails.py` — `send_statement_email(stmt, recipient, pdf_bytes, *, policy_id)`:
  builds `MIMEMultipart` message with the PDF attached as
  `attachment; filename="statement-<policy_number>.pdf"`, `Content-Type: application/pdf`.
  Uses stdlib `smtplib`. Raises `SendFailedError` when `EMAIL_SMTP_ENABLED=False` (never
  silently sends/bounces) and on connection failure.
- `POST /api/policies/{id}/statement/send` — under `manage_billing`. Body `{"confirm": true}`
  (intent + scope in one POST). Sends to the policyholder Party's stored, validated email.
  Returns `{"sent": true, "to": recipient}` on success; `400` when SMTP disabled / no
  policyholder email on file. `record_log` a `statement_sent` audit entry.

## Testing

Additive `test_smoke.py` Stage-11 block:
- Email validation: malformed email refused at Party create (400); valid one stored lowercased.
- `build_statement` over the fixture returns non-zero `total_invoiced` / `balance_outstanding`.
- Preview endpoint 200s with HTML body; `.pdf` 200s with `Content-Type: application/pdf`.
- Email: `POST /statement/send` with SMTP off returns 400 (guard exercised, nothing sent);
  policyholder without a stored email returns 400.
- `setup_test_db` idempotent.

## Files touched

- `src/backend/app/services/validators.py` (new)
- `src/backend/app/services/statements.py` (new) — build_statement + render_statement_pdf
- `src/backend/app/services/emails.py` (new) — send_statement_email
- `src/backend/app/services/parties.py` — validate email at entry
- `src/backend/app/models/party.py`, `organization.py`, `user.py` — add `email` column
- `src/backend/app/api/statements.py` (new) — preview + download + send endpoints
- `src/backend/app/api/parties.py`, `api/auth.py` — accept + validate email at entry
- `src/backend/app/core/config.py` — SMTP settings (off by default)
- `src/backend/app/templates/partials/{policy_list,statement}.html` — modal + layout
- `src/backend/static/css/style.css` — print styles
- `src/backend/app/main.py` — register statements router
- `src/backend/app/api/test_smoke.py` — Stage 11 assertions
- `pyproject.toml` — add `reportlab`
- `handoff.md`, `plan-stage11.md`, `README.md` — docs

## Scope notes

- PDF generation + preview are fully offline (ReportLab renders server-side; the browser
  only prints inline HTML/PDF). No Puppeteer/browser automation.
- No async worker or scheduled sends — confirmation is a single POST.
- Email is optional; records with no email are unaffected. Only present values are validated.
- The email validator is the single source of truth; no record type may validate email
  differently.
