# Database schema (Phase 1)

PostgreSQL 16 · Alembic

## Tables

| Table | Purpose |
|-------|---------|
| companies | Agency workspace |
| users | Login accounts |
| roles | owner, manager, employee, client |
| clients | Paying customers |
| leads | Sales enquiries |
| projects | Client work |
| tasks | Project tasks |
| invoices | Billing |
| whatsapp_logs | Legacy WhatsApp log table (UI currently disabled) |
| subscription_plans | Plan limits |
| password_reset_tokens | Forgot-password tokens |

## Migrations

| Rev | File |
|-----|------|
| 001 | Initial schema (10 tables + indexes) |
| 002 | password_reset_tokens |
| 003 | Compatibility no-op |

```bash
alembic upgrade head
```

## Verify

```bash
python -m scripts.verify_schema
```
