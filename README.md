# Group Insurance Admin Platform

Back-office system for insurers/underwriters and broker/admin staff to administer
group insurance policies: parties, policy lifecycle, member enrollment, billing,
and claims.

## Tech stack

- **Backend:** FastAPI + SQLAlchemy 2.0 + Pydantic v2 (Python)
- **Auth:** JWT (PyJWT) + native bcrypt, role-based access
- **Frontend:** HTMX + Jinja2 + Bootstrap (server-rendered, no SPA framework)
- **Database:** SQLite by default, PostgreSQL in production

## Stages

Development is broken into stages. Each phase has an authoritative plan in
`.claude/plan-stageN.md` (e.g. `.claude/plan-stage6.md` for the most recent):

1. **Foundations & repo** — done
2. **Products & policy administration** — done (product catalog, group policies with lifecycle, RBAC)
3. **Member enrollment** — done
4. **Product benefits + member coverage elections** — done
5. **Premium pricing + allocation** — done
6. **Billing & payment processing** — done (invoices, payments, `manage_billing`/`view_billing` permissions)
7. **Claims** — done (repurposes the Stage 7 `Claim` table as the single source of truth: `submitted → approved → paid` / `submitted → rejected` lifecycle with `manage_claims` (underwriter-only) gating adjudication; see Stage 14 below, `.claude/plan-stage7.md`)
8. **Reports** — done (cross-domain platform snapshot via `build_report`, `GET /api/reports` + `/api/reports/list`, wires the dashboard Reports nav link and populates the four overview stat cards, `view_dashboard` gate)
9. **Policy lapse** — done (billing drives policy lifecycle: unpaid invoice past `due_date` lapses an active policy, full payment reinstates it, reissue while lapsed re-activates; `GET /api/policies/{id}/lapse-check`, `manage_policies` gate)
10. **Closed lapsed policies** — done (a policy lapsed past the grace window is closed out of the system, clearing remaining members and invoices; closed policies appear only in a `closed` filter and the policy partial shows a status badge; `manage_policies` gate. See `.claude/plan-stage10.md`)
11. **Policy statement** — done (HTML preview + `GET /api/policies/{id}/statement.pdf`, `window.print()` preview with print CSS, and confirm-gated email of the PDF to the policyholder's stored, validated email; SMTP disabled by default so the send path 400s in dev. Single email-validation source of truth (`validators.validate_email`) applied on Party/Organization/User entry — a malformed address 400s.)
12. **Mid-term census** — done (life-event log + `GET /api/members/life-events`; add/remove members mid-cycle; daily proration translating a roster change into a signed adjustment invoice linked to billing; notifications via `record_log` + optional email. Billing fork (b2): a census change issues a separate signed `-ADJ` adjustment invoice, exempt from the one-outstanding-invoice-per-policy invariant. `manage_members` gate. See `.claude/plan-stage12.md`)
13. **Policy renewal** — done (`POST /api/policies/{id}/renew` under `manage_policies`: extends a settled, active policy's `start_date`/`end_date` into a new term and bills the next term via `create_invoice` with a new explicit premium, preserving the one-outstanding-invoice-per-policy invariant; logs `policy_renewed`; Renew button in the policies partial auto-fills the new term with the day after the current end date. See `.claude/plan-stage13.md`)
14. **Claims management** — done (repurposes the Stage 7 `Claim` table as the single source of truth: `claim_number` (service-generated, `CLM-` prefix), scoped to a policy + enrolled member, `incident_date` validated within the policy term, `submitted → approved → paid` / `submitted → rejected` lifecycle with `manage_claims` (underwriter-only) gating adjudication; `POST /api/claims` / `POST /api/claims/submit` (broker+underwriter file), JSON + HTMX list/detail, an adjudication partial; reports repurposed to the new statuses. See `.claude/plan-stage14.md`)

## Project layout

```
src/backend/
├── app/
│   ├── main.py            # FastAPI app factory
│   ├── api/               # API + page routes (auth, parties, audit, pages)
│   ├── models/            # SQLAlchemy models (User, Party, Organization, AuditLog)
│   ├── services/          # Business logic (parties, audit)
│   ├── core/              # config, database, security
│   ├── templates/         # Jinja2 templates + HTMX partials
│   └── view.py            # Template registry (avoids name clash with /templates)
└── static/                # static assets (CSS)
```

## Getting started

The project uses [uv](https://docs.astral.sh/uv/).

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure the database

The backend reads a `.env` file in `src/backend/`. A default `.env` pointing at a
local SQLite database is already committed, so you can start immediately:

```bash
cd src/backend
# .env already points to sqlite:///./group_insure.db
```

For production with PostgreSQL, copy the example and edit it:

```bash
cp src/backend/.env.example src/backend/.env
```

Then set:

```
GROUP_INSURE_DATABASE_URL=postgresql+psycopg2://group_insure:group_insure@localhost:5432/group_insure
GROUP_INSURE_JWT_SECRET=<your-production-secret>
```

You can run Postgres locally with Docker (see `docker-compose.yml`):

```bash
docker compose up -d postgres
```

### 3. Run the backend

```bash
cd src/backend
GROUP_INSURE_DATABASE_URL="sqlite:///./group_insure.db" uv run uvicorn app.main:app --reload
```

The app starts at <http://localhost:8000>. API docs are at `/docs`.

### 4. Register an account

Use the HTML register page, or the API:

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"broker1","password":"pass123","email":"b@e.com","roles":"broker"}'
```

## Verifying

A smoke test covers register, login, and the `/me` round-trip. It needs the dev
dependencies, so run them with the `dev` extra:

```bash
cd src/backend
uv run --extra dev pytest app/api/test_smoke.py
```

## Deploy to Render (one click)

Render has a free tier for both the web app and PostgreSQL, so you can run the whole
stack live in a few minutes. The app auto-creates its schema on first boot, so you
only need to deploy the repo and point it at the database.

> **Prerequisite:** push this repo to GitHub first (see below). The "Deploy to
> Render" button links to a GitHub repo.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/bluepretty/group-insure)

Render will spin up:

- **Web Service** — your FastAPI app, built from the `Dockerfile` in this repo.
- **PostgreSQL (Free tier)** — the production database; the app creates its tables on boot.

### First — push the repo to GitHub

```bash
# from the repo root, using a new GitHub repo named "group_insure"
git branch -M main
git remote add origin https://github.com/<your-username>/group_insure.git
git push -u origin main
```

### Second — open the Deploy to Render button

After pushing, replace `<your-org>` in the button URL above with your GitHub
username and click it. Render imports the repo and opens the deploy page with the
service and database pre-configured.

Set (or confirm) these **Environment Variables** in the Render UI:

| Variable | Value |
|---|---|
| `GROUP_INSURE_DATABASE_URL` | Render sets `GROUP_INSURE_DATABASE_URL` automatically to your new Postgres *Internal Database URL*. |
| `GROUP_INSURE_JWT_SECRET` | A long random string — generate one with `openssl rand -hex 32`. |
| `GROUP_INSURE_SMTP_ENABLED` | `false` (only flip to `true` once you add SMTP credentials). |

Click **Deploy** and wait for the service to turn green, then open the app URL and
register an account.

> **Note:** the button deploys a linked copy of this repo in your Render account.
> To keep editing your local code, push new commits to GitHub and Render rebuilds
> automatically — or connect the existing service to this repo's push.

## Database notes

- SQLite is the default (no setup required) — great for local development.
- Switching to PostgreSQL requires no code changes; only the `DATABASE_URL` env var.
- Models use portable SQLAlchemy types, so they work on both databases.

[Back to top](#group-insurance-admin-platform)
