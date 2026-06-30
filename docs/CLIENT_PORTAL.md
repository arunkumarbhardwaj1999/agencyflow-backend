# Client Portal — Phase 2 (row 9)

**Status:** Done

A read-only, white-labeled area for the agency's clients. A client logs in with
their own account (role = `client`) and sees **only their own** projects and
invoices — no agency-internal data.

## What the client sees

- **Branding** — the agency's company name in the header (white-labeled).
- **Metrics** — active projects, completed projects, total paid, outstanding.
- **Projects** — title, status, progress bar (tasks done / total).
- **Invoices** — amount, GST type, status, **PDF download**, and a **Pay now**
  button when a payment link exists.

## API

| Action | Endpoint |
|--------|----------|
| Profile + branding | `GET /api/v1/portal/me` |
| Dashboard metrics | `GET /api/v1/portal/summary` |
| My projects | `GET /api/v1/portal/projects` |
| My invoices | `GET /api/v1/portal/invoices` |
| Download invoice PDF | `GET /api/v1/portal/invoices/{id}/pdf` |

All endpoints require a logged-in **client** whose email matches a client
record in the company. Every query is scoped to that client only.

## Manual test

1. As **owner/manager**: add a **client** whose email you can log in with, and
   create a **project** + **invoice** for that client.
2. Create a `client` user with the same email (or log in as that client).
3. Open **Portal** — branding, metric cards, project progress, invoices show up.
4. **PDF** → downloads the client's invoice. **Pay now** (if a link was
   generated) → opens the checkout.

## Notes

- "Read-only": the portal never exposes other clients' data or agency internals.
- Uploaded documents / campaign asset storage (Cloudflare R2) is tracked
  separately as row 12 (File Storage).
