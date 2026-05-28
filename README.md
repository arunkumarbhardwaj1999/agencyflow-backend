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
# Start PostgreSQL (docker compose up db -d)
alembic upgrade head
python -m scripts.seed_roles
uvicorn app.main:app --reload
```

## Phase 1 API routes

| Module | Prefix |
|--------|--------|
| Auth | `/api/v1/auth` |
| Leads | `/api/v1/leads` |
| Clients | `/api/v1/clients` |
| Projects | `/api/v1/projects` |
| Tasks | `/api/v1/tasks` |
| Dashboard | `/api/v1/dashboard` |
| Invoices | `/api/v1/invoices` |
| Client portal | `/api/v1/portal` |
| Staff | `/api/v1/users` |
