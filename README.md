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
GROUP_INSURE_DATABASE_URL=postgresql://group_insure:group_insure@localhost:5432/group_insure
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

## Deploy with Koyeb (free, no card required)

Koyeb is a free-tier host that doesn't require a credit card and deploys directly
from your GitHub repo. It runs the FastAPI app; [Neon](#deploy-with-neon---no-card-required)
provides the (also free, no-card) database. The app auto-creates its schema on
first boot, so no manual SQL is needed.

### Prerequisite — push the repo to GitHub

```bash
# from the repo root, using a new GitHub repo named "group_insure"
git branch -M main
git remote add origin https://github.com/<your-username>/group-insure.git
git push -u origin main
```

### 1. Create the app
- Sign in at <https://www.koyeb.com> with **GitHub**.
- Click **New Application**, then **FastAPI app** (or **New App → FastAPI**).
- Connect the `group-insure` repo and select the `main` branch.

### 2. Build settings
- **Build method:** Buildpack
- **Run command:** `uv run uvicorn app.main:app --host 0.0.0.0`
- **CPU:** Nano (the free default)
- **Port:** `8000`

> **Working directory:** this repo's app code lives in `src/backend`, and the app's
> imports (`from app.main import app`) resolve only from there. If Koyeb asks for a
> base/working directory, set it to `src/backend`. If it doesn't offer that option,
> deploy via Docker instead (your repo already contains a `Dockerfile`).

### 3. Environment variables
Set these in the Koyeb app settings:

| Variable | Value |
|---|---|
| `GROUP_INSURE_DATABASE_URL` | Your Neon connection string — see [below](#deploy-with-neon---no-card-required), step 2. |
| `GROUP_INSURE_JWT_SECRET` | A long random string — generate one with `openssl rand -hex 32`. |
| `GROUP_INSURE_SMTP_ENABLED` | `false` (only flip to `true` once you add SMTP credentials). |

### 4. Deploy
Click **Deploy**. Koyeb auto-deploys from your repo, and each `git push` redeploys
automatically — so after the first deploy, just push for updates (no dashboard needed).

Once green, open the app URL and register an account to log in.

## Deploy with Neon — no card required

[Neon](https://neon.com) offers a free, permanent PostgreSQL tier that doesn't
require a credit card. It's the database (the app itself still needs a host like
[Koyeb](#deploy-with-koyeb--free--no-card-required)); the app works unchanged —
you just point `GROUP_INSURE_DATABASE_URL` at Neon.

### 1. Create a Neon project
- Sign up at <https://neon.com>
- **New Project**, name it `group-insure`, pick a region (e.g. `US (East)`).
- Wait for it to provision.

### 2. Get the connection string
- Open your project → **Connection Info** → copy the **serverless connection string**.
- It looks like:

  ```
  postgresql://user:pass@ep-xxx-east-2.neon.tech/neondb?sslmode=require
  ```

- Your app uses the `psycopg[binary]` driver (psycopg v3), so the plain
  `postgresql://` scheme works as-is — no driver suffix needed:

  ```
  postgresql://user:pass@ep-xxx-east-2.neon.tech/neondb?sslmode=require
  ```

> **Pooled vs. direct:** use the **direct** connection string (no `-pooler` in
> the host) for this app. Your app runs `create_all()` at startup to build the
> schema, and PgBouncer (the `-pooler` route) runs in transaction mode, which can
> interfere with table creation. Take the direct string from Neon's **Connection
> Info** dialog (toggle "Connection pooling" off).

### 3. Configure your host (Koyeb)
On the deploy page, set:

| Variable | Value |
|---|---|
| `GROUP_INSURE_DATABASE_URL` | The `postgresql+psycopg2://` string from step 2. |
| `GROUP_INSURE_JWT_SECRET` | A long random string — generate one with `openssl rand -hex 32`. |
| `GROUP_INSURE_SMTP_ENABLED` | `false` |

The app auto-creates its schema on first boot, so no manual SQL is needed.

> **Free tier limits:** ~1 GB storage + 100 CU-hours/month, no card required.
> Enough for testing; a typical deployment stays well under these limits.

## Quick start — velixir (free, no card) + Neon

The simplest no-card stack. **velixir** (velixir.net) runs your FastAPI app;
[Neon](#deploy-with-neon---no-card-required) provides the database. Both are free
and neither requires a credit card. velixir runs in the EU and sleeps when idle
(first request after idle takes a few seconds to warm up).

### Prerequisite — push the repo to GitHub

```bash
git branch -M main
git remote add origin https://github.com/<your-username>/group-insure.git
git push -u origin main
```

### 1. Set up Neon (the database)
- Sign in at <https://neon.com> → **New Project** → `group-insure`.
- Open the project → **Connection Info** → copy the connection string.
- Change the scheme to `postgresql+psycopg2://` for your app:

  ```
  postgresql+psycopg2://user:pass@ep-xxx-east-2.neon.tech/neondb?sslmode=require
  ```

### 2. Deploy the app on velixir
- Sign in at <https://velixir.net> with **GitHub** (free tier, no card).
- Push your source to velixir via its CLI (or GitHub Actions).
- velixir auto-detects the Python runtime and builds it — **no Dockerfile needed**.
- Set these environment variables in the velixir app settings:

| Variable | Value |
|---|---|
| `GROUP_INSURE_DATABASE_URL` | Your `postgresql+psycopg2://` Neon string from step 1. |
| `GROUP_INSURE_JWT_SECRET` | A long random string — `openssl rand -hex 32`. |
| `GROUP_INSURE_SMTP_ENABLED` | `false` |

> **Working directory:** your app code lives in `src/backend`, and `from app.main
> import app` resolves only from there. If velixir can't find the app, set the base
> directory to `src/backend` in the app settings.

### 3. Verify
The app auto-creates its schema on first boot, then open the velixir URL and
register an account. Each `git push` redeploys automatically.

## Database notes

- SQLite is the default (no setup required) — great for local development.
- Switching to PostgreSQL requires no code changes; only the `DATABASE_URL` env var.
- Models use portable SQLAlchemy types, so they work on both databases.

[Back to top](#group-insurance-admin-platform)
