# Email setup (Resend)

While `RESEND_API_KEY` in `.env` is blank, the system runs in **mock mode** (emails are logged to the console / DB only).
Add a key and **restart** the backend to send real email.

Email is used for: invites, account confirmation, password reset, invoice PDF, proposals, and contracts.

---

## Free tier (Resend)

### Step 1: Account
1. https://resend.com → Sign up (free)
2. **API Keys** → Create → copy key (`re_...`)

### Step 2: Add to `.env`
```env
RESEND_API_KEY=re_your_key_here
EMAIL_FROM=onboarding@resend.dev
EMAIL_FROM_NAME=AgencyFlow
```

> **Free limit:** ~3,000 emails/month.  
> **Free testing rule:** Without a verified domain, mail only goes to your Resend sign-up email.  
> To send to any address: Resend → **Domains** → verify your domain, then set:
> `EMAIL_FROM=noreply@yourdomain.com`

### Step 3: Restart
```bash
cd agencyflow-backend
docker compose restart api
# If you use a worker service:
# docker compose restart api worker
```

### Step 4: Test
1. Team → **Invite member** → enter email → Send invite  
2. Check inbox / spam  
3. Or open http://localhost:8000/health → `"email": { "enabled": true }`  
4. In the app: **Settings → Integrations** shows Email Live vs Mock  

---

## Quick check

```bash
curl http://localhost:8000/health
```

Look for email enabled / provider = resend when the key is set.

---

## Common problems

| Problem | Fix |
|---------|-----|
| Email not received | Is `RESEND_API_KEY` set? API restarted? Free tier = verified email only |
| Invite link wrong port | Set `FRONTEND_URL` to the correct port (3000/3001/3002) |

---

## Related

- File uploads + email overview: [`FILES_EMAIL.md`](FILES_EMAIL.md)
- Product UI: Settings → Integrations (email status only; WhatsApp/AI are off in the frontend)
