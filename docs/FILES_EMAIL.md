# File Storage + Email — Phase 2 (rows 12 & 14)

**Status:** Done

## File Storage (Row 12)

Uploads use **Cloudflare R2** (S3-compatible, zero egress) when configured, and
fall back to **local disk** (`./uploads`) so everything works in development
without any cloud account.

- **Company logo** — owners upload a logo; it's stored and surfaced as
  `company.logo` (used for portal/invoice branding).
- **Project documents** — staff upload contracts, briefs, and assets against a
  project. Files are namespaced per company: `<company>/<kind>/<uuid>-<name>`.
- **Access control** — every document is scoped to the uploader's company;
  downloads stream through an authenticated endpoint.
- **Local dev serving** — when R2 is not configured, logo URLs point at
  `GET /api/v1/files/public/{key}` (this route is disabled once R2 is on).

### API

| Action | Endpoint |
|--------|----------|
| Upload workspace logo | `POST /api/v1/files/logo` (multipart `file`) |
| Upload document | `POST /api/v1/files/documents` (multipart `file`, optional `project_id`) |
| List documents | `GET /api/v1/files/documents?project_id=` |
| Download document | `GET /api/v1/files/documents/{id}/download` |
| Delete document | `DELETE /api/v1/files/documents/{id}` |
| Serve local file (dev) | `GET /api/v1/files/public/{key}` |

### Config (.env)

```
# Leave blank for local disk storage.
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=
R2_PUBLIC_URL=            # optional public/CDN base URL for the bucket
LOCAL_STORAGE_DIR=uploads
BACKEND_PUBLIC_URL=http://localhost:8000
MAX_UPLOAD_MB=10
```

To go live: create an R2 bucket + API token, fill the four `R2_*` values, and
(optionally) set `R2_PUBLIC_URL` to a public bucket/CDN domain.

## Email (Row 14)

Transactional email via **Resend**. With no API key it runs in **mock mode** —
emails are logged to the console so flows can be tested without a mailbox.

For step-by-step Resend setup, see [`SETUP_EMAIL.md`](SETUP_EMAIL.md).

- **Welcome / confirmation** — workspace registration  
- **Password reset** — reset link emailed (mock mode may also return token in API)  
- **Invoice email** — tax-invoice PDF to the client, optional pay link  
- **Invites / proposals / contracts** — other transactional mail  

### API

| Action | Endpoint |
|--------|----------|
| Email invoice PDF to client | `POST /api/v1/invoices/{id}/send` |

### Config (.env)

```
RESEND_API_KEY=            # blank = mock mode (log to console)
EMAIL_FROM=noreply@agencyflow.in
EMAIL_FROM_NAME=AgencyFlow
```

## Manual test (mock mode, no keys needed)

1. **Projects** → documents → upload / download / delete.  
2. **Invoices** → **Email** on any invoice → toast confirms (check API logs for mock send).  
3. **Register** / **Forgot password** → check API console for the mock email log.  
4. **Settings → Integrations** → Email shows Mock or Live.
