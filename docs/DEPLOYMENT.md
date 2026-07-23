# Deployment Guide

## Local development

```bash
cd agencyflow-backend
cp .env.example .env
docker compose up --build
```

Typical services: `db`, `api`, and optionally `redis` (+ `worker` if you use Celery).

```bash
cd agencyflow-frontend
cp .env.example .env.local
# Point API to local backend:
# NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
npm install && npm run dev
```

Frontend: http://localhost:3000  
API docs: http://localhost:8000/docs  
Health: http://localhost:8000/health  

---

## Production architecture (current)

| Service | Platform | Purpose |
|---------|----------|---------|
| Frontend | **Vercel** | Next.js app |
| API | **Railway** | FastAPI |
| Database | **Railway / Neon Postgres** | Primary data |
| Redis | **Optional** | Realtime pub/sub + Celery broker |
| Worker | **Optional** | Celery background jobs |
| Files | **Cloudflare R2** (optional) | Uploads; local disk in mock/dev |

> WhatsApp and AI are **disabled in the frontend UI** for now. You do not need Meta/WhatsApp worker setup for day-to-day demos.

---

## Backend — Railway

1. Create a Railway project and add **PostgreSQL** (or use Neon).  
2. Deploy `agencyflow-backend` from GitHub.  
3. Set env vars from `.env.example` (at least `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, `FRONTEND_URL`).  
4. Use async Postgres URL format for SQLAlchemy (`postgresql+asyncpg://...`).  
5. `REDIS_URL` can be empty — API still runs; realtime/queues fall back to in-process mode.  
6. For real email: set `RESEND_API_KEY` (see [`SETUP_EMAIL.md`](SETUP_EMAIL.md)).

### Optional Celery worker

Only needed if you want a separate background worker later:

```bash
celery -A app.celery_app worker --loglevel=info
```

---

## Frontend — Vercel

1. Import `agencyflow-frontend` from GitHub.  
2. Framework: **Next.js**.  
3. Env vars:
   - `NEXT_PUBLIC_API_URL` = `https://your-api.railway.app/api/v1`
   - `NEXT_PUBLIC_SITE_URL` = your Vercel URL  
   - `NEXT_PUBLIC_GOOGLE_CLIENT_ID` = (optional)

Local development should use `.env.local` with `http://localhost:8000/api/v1` — do not put Railway URL in `.env.local`.

---

## Payment webhooks (when live payments are on)

| Provider | URL |
|----------|-----|
| Razorpay | `https://your-api/api/v1/payments/webhook/razorpay` |
| Stripe | `https://your-api/api/v1/payments/webhook/stripe` |

---

## Health check

`GET /health` → should include `status: ok`.

Railway / uptime monitors can use this path.

---

## CI

Repos may include `.github/workflows/ci.yml` — runs on push/PR to `main` / `develop`.

---

## Related docs

- [`SETUP_EMAIL.md`](SETUP_EMAIL.md) — Resend email  
- [`FILES_EMAIL.md`](FILES_EMAIL.md) — file storage + email overview  
- [`BILLING_PAYMENTS.md`](BILLING_PAYMENTS.md) — GST & payments  
- Root product guide: `FEATURES.md`
