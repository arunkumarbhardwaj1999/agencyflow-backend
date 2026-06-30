# AgencyFlow CRM — Backend (Phase 1)

FastAPI + PostgreSQL 16 + SQLAlchemy 2.0 + Alembic + JWT auth.

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

API: http://localhost:8000/docs

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
docker compose up db -d
alembic upgrade head
python -m scripts.seed_roles
python -m scripts.seed_plans
uvicorn app.main:app --reload
```

## API routes

| Module | Prefix |
|--------|--------|
| Auth | `/api/v1/auth` |
| Leads | `/api/v1/leads` |
| Clients | `/api/v1/clients` |
| Projects | `/api/v1/projects` |
| Tasks | `/api/v1/tasks` |
| Dashboard | `/api/v1/dashboard` |
| Invoices (GST + PDF) | `/api/v1/invoices` |
| Payments (links + webhooks) | `/api/v1/payments` |
| Client portal | `/api/v1/portal` |
| Staff | `/api/v1/users` |

## Docs

- [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md)
- [`docs/LEADS_PIPELINE.md`](docs/LEADS_PIPELINE.md)
- [`docs/BILLING_PAYMENTS.md`](docs/BILLING_PAYMENTS.md)
- [`docs/CLIENT_PORTAL.md`](docs/CLIENT_PORTAL.md)
- Verify DB: `python -m scripts.verify_schema`
