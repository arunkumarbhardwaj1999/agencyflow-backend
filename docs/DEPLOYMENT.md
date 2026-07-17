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

### Public URL on PythonAnywhere (required for Vercel)

Console `uvicorn --port 8001` is **only local to that console**. Vercel cannot reach it.
That is why the live site shows **Failed to fetch** — `https://aastha282002.pythonanywhere.com` currently returns **404**.

You must create an **ASGI website** with the `pa` tool:

1. Account → **API token** → Create  
   https://www.pythonanywhere.com/account/#api_token

2. In a **new** Bash console:

```bash
pip install --upgrade pythonanywhere

# Find your real venv path (one of these usually works):
ls ~/.virtualenvs/
which uvicorn

# Set CORS + frontend for Vercel (edit .env)
cd ~/agencyflow-backend
nano .env
```

Put these lines in `.env` (adjust if needed):

```bash
REDIS_URL=
CORS_ORIGINS=https://agencyflow-frontend-lac.vercel.app,http://localhost:3000
FRONTEND_URL=https://agencyflow-frontend-lac.vercel.app
BACKEND_PUBLIC_URL=https://aastha282002.pythonanywhere.com
```

3. Create the public ASGI site (replace venv path if different):

```bash
# If venv is ~/.virtualenvs/agencyenv :
pa website create --domain aastha282002.pythonanywhere.com --command '/home/Aastha282002/.virtualenvs/agencyenv/bin/uvicorn --app-dir /home/Aastha282002/agencyflow-backend --uds ${DOMAIN_SOCKET} app.main:app'
```

If `agencyenv` is not under `.virtualenvs`, first run `which uvicorn` and use that path instead of `/home/Aastha282002/.virtualenvs/agencyenv/bin/uvicorn`.

4. Test in browser:

```text
https://aastha282002.pythonanywhere.com/health
```

Must show `{"status":"ok",...}`. Then reload the Vercel register page.

5. After code updates:

```bash
cd ~/agencyflow-backend && git pull origin main
pa website reload --domain aastha282002.pythonanywhere.com
```
