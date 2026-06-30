# GST Billing + Payments — Phase 2

**Status:** Done (rows 7 & 8)

## GST Billing Engine

- **Line-item invoices** — each invoice has one or more items (description, qty, rate). Subtotal = sum of item amounts.
- **Auto GST split** based on place of supply:
  - **Intra-state** (supplier state == place of supply) → **CGST + SGST** (rate split in half).
  - **Inter-state** (different states) → **IGST** (full rate).
- **State code** comes from the first 2 digits of a GSTIN, or an explicit `place_of_supply` on the invoice.
- **Invoice number** auto-generated: `INV-<year>-<seq>`.
- **PDF export** — `GET /api/v1/invoices/{id}/pdf` returns a styled tax invoice (ReportLab).

## Payments

- **Razorpay** (domestic) and **Stripe** (international) supported via SDKs.
- **Mock mode** (default, `PAYMENTS_MOCK=true`): no real keys needed — a local pay link is returned and the invoice can be marked paid via the simulate endpoint.
- **Webhooks** verify the provider signature and set the invoice to **paid**.

## API

| Action | Endpoint |
|--------|----------|
| Create invoice (line items + GST) | `POST /api/v1/invoices` |
| Download PDF | `GET /api/v1/invoices/{id}/pdf` |
| Create payment link | `POST /api/v1/payments/invoices/{id}/link` |
| Razorpay webhook | `POST /api/v1/payments/webhook/razorpay` |
| Stripe webhook | `POST /api/v1/payments/webhook/stripe` |
| Simulate payment (dev/mock only) | `POST /api/v1/payments/invoices/{id}/simulate` |

## Config (.env)

```
FRONTEND_URL=http://localhost:3000
CURRENCY=INR
PAYMENTS_MOCK=true          # set false in production
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```

## Manual test (mock mode)

1. **Clients** → add a client (optionally with a GSTIN so place of supply is detected).
2. **Invoices** → **Create invoice**, add line items, pick GST rate → live total shows CGST+SGST or IGST.
3. **PDF** → opens the generated tax invoice.
4. **Pay link** → opens the (mock) payment link and stores the order id.
5. **Mark paid** (or call the simulate endpoint) → status becomes **Paid**.

## Notes

- Tax split: same-state client = CGST 9% + SGST 9%; other-state client = IGST 18% (for an 18% rate).
- To go live: set the provider keys, `PAYMENTS_MOCK=false`, and register the webhook URLs in the Razorpay/Stripe dashboards.
