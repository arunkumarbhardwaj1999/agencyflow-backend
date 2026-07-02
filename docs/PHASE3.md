# Phase 3 — 100% complete

## Row 13 — Real-Time WebSockets ✅

- Workspace-wide `RealtimeProvider` with auto-reconnect (exponential backoff)
- Live toast stack on all app pages (lead, invoice, project, task, client events)
- Header bell dropdown with unread count + connection status dot
- Auto-invalidates React Query caches when events arrive
- Sound notifications (Web Audio API chime)
- Desktop notifications (browser Notification API when tab is hidden)
- Per-user preferences persisted in `localStorage`
- Sound / desktop toggles in bell dropdown

## Row 10 — WhatsApp Notifications ✅

- Meta Cloud API integration with **mock mode** (logs to `whatsapp_logs`)
- **Meta-approved template messages** with text fallback when template not approved
- Templates: `payment_reminder`, `invoice_ready`, `payment_received`, `task_update`, `custom`
- **Celery + Redis async queue** (`worker` service in docker-compose); falls back to in-process async without Redis
- `GET /whatsapp/templates` — list available templates for UI
- `POST /whatsapp/invoices/{id}/notify?template=` — invoice notifications from Finance
- `POST /whatsapp/send` — manual message to client
- `GET /whatsapp/logs` — message history with template key + status
- **Auto-triggers:**
  - Payment webhooks (Razorpay/Stripe/simulate) → `payment_received` WhatsApp
  - Invoice email send → `invoice_ready` WhatsApp (if client has phone)
  - Task marked **done** → `task_update` WhatsApp to client

### Config

```
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_BUSINESS_ACCOUNT_ID=
WHATSAPP_AUTO_ON_PAYMENT=true
WHATSAPP_AUTO_ON_INVOICE_SEND=true
WHATSAPP_TEMPLATE_LANGUAGE=en
REDIS_URL=redis://localhost:6379/0
```

## Row 11 — AI Features (Claude) ✅

- Anthropic Claude API with **mock mode** (template drafts without API key)
- **SSE streaming** via `POST /ai/stream` (live token-by-token when API key set)
- **Rate limits** — `20/minute` per user (configurable via `AI_RATE_LIMIT`)
- Endpoints:
  - `POST /ai/draft-email` — follow-up email from lead context
  - `POST /ai/summarize-project` — standup summary from project + tasks
  - `POST /ai/suggest-followups` — prioritized pipeline actions
  - `POST /ai/draft-invoice-email` — invoice cover email
  - `POST /ai/polish-task` — improve task description
  - `POST /ai/draft-client-welcome` — onboarding welcome email
  - `POST /ai/stream` — streaming for all actions above

**Frontend:** AI on Leads, Projects (summary + task polish), Clients (welcome), Finance (invoice email). Modal supports **streaming**, **inline edit**, and **copy**.

### Config

```
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-20250514
AI_RATE_LIMIT=20/minute
```

## Manual test (mock mode)

1. **Leads** → AI on card → streaming email draft → edit → Copy
2. **AI follow-ups** → prioritized actions
3. **Projects** → AI summary + **AI polish** on a task
4. **Clients** → **Welcome email** AI button
5. **Finance** → template dropdown → WA on invoice → **WhatsApp activity** log
6. **Finance** → AI button on invoice row → draft invoice email
7. Mark invoice paid (simulate) → auto WhatsApp `payment_received` in logs
8. Mark task done on project → auto `task_update` WhatsApp (client needs phone)

## Docker (full stack with worker)

```bash
docker compose up --build
```

Services: `db`, `api`, `redis`, `worker` (Celery WhatsApp queue)
