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
7. **Claims** — done (raise/adjudicate/close claims via a small state machine, `view_claims`/`manage_claims`, `claude/plan-stage7.md`)
8. **Reports** — done (cross-domain platform snapshot via `build_report`, `GET /api/reports` + `/api/reports/list`, wires the dashboard Reports nav link and populates the four overview stat cards, `view_dashboard` gate)
9. **Policy lapse** — done (billing drives policy lifecycle: unpaid invoice past `due_date` lapses an active policy, full payment reinstates it, reissue while lapsed re-activates; `GET /api/policies/{id}/lapse-check`, `manage_policies` gate)

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

## Database notes

- SQLite is the default (no setup required) — great for local development.
- Switching to PostgreSQL requires no code changes; only the `DATABASE_URL` env var.
- Models use portable SQLAlchemy types, so they work on both databases.
