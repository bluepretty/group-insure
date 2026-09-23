# Group Insurance Admin Platform

Back-office system for insurers/underwriters and broker/admin staff to administer
group insurance policies: products, policy lifecycle, member enrollment, billing,
and claims.

## Stages

Development is broken into stages (see the plan file for the roadmap):

1. **Foundations & repo** — current
2. People, access & core administration
3. Products & policy administration
4. Member enrollment (MVP core)
5. Pricing & billing
6. Claims management
7. Reporting & dashboards
8. Polish & hardening

## Stack

- **Backend:** Spring Boot 3 (Java)
- **Database:** PostgreSQL 16
- **Frontend:** React + TypeScript

## Getting started

### 1. Start the database

```bash
docker compose up -d postgres
```

### 2. Configure the backend

The backend defaults to the `local` profile and connects to the Docker Postgres
above. To change the datasource, edit
`backend/src/main/resources/application-local.yml`.

### 3. Run the backend

```bash
cd backend
./gradlew bootRun
```

The API is available at <http://localhost:8080>.

### 4. Run the frontend (coming next)

```bash
cd frontend
npm install
npm run dev
```

## Local services

- PostgreSQL — <http://localhost:5432> (credentials in `docker-compose.yml`)

## Tooling

- **Build:** Gradle (backend), npm (frontend)
- **CI:** GitHub Actions (`.github/workflows/ci.yml`)
