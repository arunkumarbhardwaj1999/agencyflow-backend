# AgencyFlow — Database schema (Phase 1)

PostgreSQL 16 · SQLAlchemy 2.0 · Alembic

**Status:** Verified ✅ (2026-05-29) — fresh database + migrations + indexes OK

---

## 11 production tables

| # | Table | What it stores |
|---|--------|----------------|
| 1 | **companies** | Each agency workspace (name, slug, email, GST, timezone, plan) |
| 2 | **users** | Login accounts linked to one company |
| 3 | **roles** | owner, manager, employee, client — permissions |
| 4 | **clients** | Paying customers of the agency |
| 5 | **leads** | Sales enquiries (before they become clients) |
| 6 | **projects** | Client work (title, status, budget, dates) |
| 7 | **tasks** | Jobs inside a project (assignee, due date, status) |
| 8 | **invoices** | Bills to clients (subtotal, tax, paid/unpaid) |
| 9 | **whatsapp_logs** | WhatsApp message history (Phase 3 API) |
| 10 | **subscription_plans** | Plan limits (max users, max clients, price) |
| 11 | **password_reset_tokens** | One-time forgot-password tokens (auth) |

---

## Indexes (faster search & filters)

| Index | Table | Purpose |
|-------|--------|---------|
| `idx_companies_slug_search` | companies | Lookup workspace by slug |
| `idx_users_multi_tenant` | users | Users per company + login |
| `idx_leads_pipeline_filter` | leads | Kanban by company + status |
| `idx_invoices_lookup` | invoices | Invoices by company + number |
| `idx_tasks_project_execution` | tasks | Tasks by project + status |

---

## Alembic migrations

| Revision | File | Description |
|----------|------|-------------|
| 001 | `001_initial_schema` | 10 core tables + 5 indexes |
| 002 | `002_password_reset_tokens` | Password reset table + indexes |
| 003 | `003_compat_noop` | Compatibility (no schema change) |

**Apply migrations:**
```bash
alembic upgrade head
```

**Docker (auto on start):**
```bash
docker compose up --build
```

---

## Verify schema (anytime)

```bash
docker compose exec api python -m scripts.verify_schema
```

Or list tables manually:
```bash
docker compose exec db psql -U postgres -d agencyflow -c "\dt"
docker compose exec db psql -U postgres -d agencyflow -c "\di"
```

---

## Fresh database test (for new developers)

```bash
docker compose down -v
docker compose up --build
docker compose exec api python -m scripts.verify_schema
```

Expected: `All checks passed.` and Alembic version `003`.
