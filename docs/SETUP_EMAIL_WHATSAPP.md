# Email + WhatsApp — Real mode setup (Hindi guide)

Jab tak API keys `.env` mein **blank** hain, system **mock mode** mein chalega (console log / DB log only).
Keys daal kar backend **restart** karo → real email / WhatsApp chal jayega.

---

## Part 1 — Email (Resend) — FREE tier

### Step 1: Account
1. https://resend.com → Sign up (free)
2. **API Keys** → Create → copy key (`re_...`)

### Step 2: `.env` mein daalo
```env
RESEND_API_KEY=re_your_key_here
EMAIL_FROM=onboarding@resend.dev
EMAIL_FROM_NAME=AgencyFlow
```

> **Free limit:** ~3,000 emails/month.  
> **Free testing rule:** Bina domain verify ke sirf **apni Resend sign-up email** pe mail jayegi.  
> Kisi bhi email pe bhejne ke liye Resend → **Domains** → apna domain verify karo, phir:
> `EMAIL_FROM=noreply@yourdomain.com`

### Step 3: Restart
```bash
cd agencyflow-backend
docker compose restart api worker
```

### Step 4: Test
1. Team → **Invite member** → email daalo → Send invite  
2. Inbox / spam check karo  
3. Ya browser mein: http://localhost:8000/health → `"email": { "enabled": true }`

---

## Part 2 — WhatsApp (Meta Cloud API)

### Tumhara Meta Business (Agency-flow)
Business portfolio ban chuka hai: [Meta Business Settings](https://business.facebook.com/latest/settings/business_info)

Business account ID (`.env` mein already set):
`WHATSAPP_BUSINESS_ACCOUNT_ID=192028446869010`

### Step 1: Meta Developer App
1. https://developers.facebook.com/apps/create/ → type **Business**
2. App name: e.g. `AgencyFlow CRM`
3. **Business portfolio** select karo: **Agency-flow**
4. App dashboard → **Add product** → **WhatsApp** → **Set up**

### Step 2: Values copy karo
| `.env` variable | Kahan milega |
|-----------------|--------------|
| `WHATSAPP_TOKEN` | API Setup → Temporary access token (ya permanent System User token) |
| `WHATSAPP_PHONE_NUMBER_ID` | API Setup → Phone number ID |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | WhatsApp → Account ID (optional, logging) |

### Step 3: Test phone number (zaroori dev ke liye)
Meta Console → WhatsApp → **API Setup** → **To** field mein apna phone add karo (OTP verify).

> Jab tak app **Development** mode mein hai, sirf **registered test numbers** ko message jayega.

### Step 4: `.env` mein daalo
```env
WHATSAPP_TOKEN=EAAxxxx...
WHATSAPP_PHONE_NUMBER_ID=123456789012345
WHATSAPP_BUSINESS_ACCOUNT_ID=123456789012345
WHATSAPP_WEBHOOK_VERIFY_TOKEN=agencyflow-dev
WHATSAPP_AUTO_ON_PAYMENT=true
WHATSAPP_AUTO_ON_INVOICE_SEND=true
REDIS_URL=redis://redis:6379/0
```

### Step 5: Restart (API + worker — worker queue ke liye zaroori)
```bash
docker compose restart api worker redis
```

### Step 6: Test (app UI)
1. Dashboard → **Settings → Integrations** (sidebar)
2. Setup steps follow karo, phir **Send test** apne phone pe
3. **Finance** → client with phone → invoice → WhatsApp button
4. http://localhost:8000/health → `"whatsapp": { "enabled": true }`

### Step 7: Test (Finance)

### Templates (optional, production)
Meta Business Manager mein templates approve karwao:
- `payment_reminder`
- `invoice_ready`
- `payment_received`
- `task_update`

Agar template approve nahi hai, system **plain text** fallback try karega (24h window / test number pe kaam karta hai).

### Inbound webhook (local — optional)
Meta ko public URL chahiye. Local test ke liye **ngrok**:
```bash
ngrok http 8000
```
Webhook URL: `https://xxxx.ngrok.io/api/v1/whatsapp/webhook`  
Verify token: same as `WHATSAPP_WEBHOOK_VERIFY_TOKEN`

---

## Quick check

```bash
curl http://localhost:8000/health
```

```json
"integrations": {
  "email": { "enabled": true, "provider": "resend" },
  "whatsapp": { "enabled": true, "provider": "meta", "celery_queue": true }
}
```

Dono `enabled: true` → real mode on ✅

---

## Common problems

| Problem | Fix |
|---------|-----|
| Email nahi aayi | `RESEND_API_KEY` set? API restart? Free tier = sirf verified email |
| WhatsApp mock status | Token / Phone ID blank? Worker running? |
| WhatsApp API error 131 | Phone Meta test list mein add karo |
| Invite link galat port | `FRONTEND_URL` sahi port set karo (3000/3001/3002) |
