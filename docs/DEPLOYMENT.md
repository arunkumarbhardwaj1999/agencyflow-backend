# Deployment Guide — Row 15 (DevOps)

## Local development

```bash
cd agencyflow-backend
cp .env.example .env
docker compose up --build
```

Services: `db`, `api`, `redis`, `worker` (Celery WhatsApp queue)

```bash
cd agencyflow-frontend
cp .env.example .env.local
npm install && npm run dev
```

## Production architecture

| Service | Platform | Purpose |
|---------|----------|---------|
| Frontend | **Vercel** | Next.js 15 app |
| API | **Railway** | FastAPI + migrations |
| Database | **Railway PostgreSQL** | Primary data store |
| Redis | **Railway Redis** | Celery broker + WebSocket pub/sub |
| Worker | **Railway** (2nd service) | Celery WhatsApp jobs |
| Files | **Cloudflare R2** | Uploads (optional) |

## Backend — Railway

1. Create Railway project, add **PostgreSQL** and **Redis** plugins.
2. Deploy `agencyflow-backend` from GitHub.
3. Set environment variables from `.env.example`.
4. `DATABASE_URL` — use Railway Postgres connection string (asyncpg format).
5. `REDIS_URL` — use Railway Redis URL.
6. `CORS_ORIGINS` — your Vercel domain.
7. `FRONTEND_URL` — `https://your-app.vercel.app`
8. `SECRET_KEY` — long random string.

### Celery worker (second Railway service)

Deploy the same repo with start command:

```bash
celery -A app.celery_app worker --loglevel=info -Q whatsapp
```

Or use `railway.worker.toml` in this repo.

## Frontend — Vercel

1. Import `agencyflow-frontend` from GitHub.
2. Framework preset: **Next.js** (`vercel.json` included).
3. Environment variables:
   - `NEXT_PUBLIC_API_URL` = `https://your-api.railway.app/api/v1`
   - `NEXT_PUBLIC_GOOGLE_CLIENT_ID` = (optional)

## Webhooks (production)

| Provider | URL |
|----------|-----|
| Razorpay | `https://api.example.com/api/v1/payments/webhook/razorpay` |
| Stripe | `https://api.example.com/api/v1/payments/webhook/stripe` |
| WhatsApp | `https://api.example.com/api/v1/whatsapp/webhook` |

WhatsApp verify token: set `WHATSAPP_WEBHOOK_VERIFY_TOKEN` in Meta Console and `.env`.

## CI

Both repos include `.github/workflows/ci.yml` — runs on push/PR to `main` and `develop`.

## Health check

`GET /health` → `{"status":"ok"}`

Railway uses this via `railway.toml`.

## PythonAnywhere (API only)

PythonAnywhere free accounts do **not** run Redis. Set this in your `.env`:

```bash
REDIS_URL=
```

(or `REDIS_URL=disabled`)

The API still works — WhatsApp queue and cross-server WebSockets fall back to in-process mode.

### Port already in use (`address already in use`)

Something is already listening on 8000. Free it, then restart:

```bash
cd ~/agencyflow-backend
source ~/agencyenv/bin/activate   # your venv name may differ
fuser -k 8000/tcp                 # kill whatever holds port 8000
# if fuser is missing:
#   ps aux | grep uvicorn
#   kill <PID>
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Or use another port for a quick test:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### Public URL on PythonAnywhere

Console `uvicorn` on port 8000 is mainly for testing. For a public site, use the **Web** tab (ASGI/WSGI) or an Always-on task (paid). Free tier cannot expose arbitrary ports to the internet the same way Railway/Vercel do.
