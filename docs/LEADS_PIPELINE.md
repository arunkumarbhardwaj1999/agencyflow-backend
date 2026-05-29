# Sales Lead Pipeline — Phase 1

**Module:** Kanban board, lead CRUD, swimlanes, follow-up dates, revenue value  
**Status:** In progress (~20% daily milestone) · Core flow working

---

## Swimlanes (status)

| Stage | Meaning |
|-------|---------|
| **new** | Fresh enquiry |
| **contacted** | First touch done |
| **proposal** | Quote / proposal sent |
| **won** | Deal closed — can convert to client |
| **lost** | Did not convert |

---

## Features

| Feature | Backend | Frontend |
|---------|---------|----------|
| List / create / update / delete leads | `GET/POST/PATCH/DELETE /api/v1/leads` | Leads page |
| Kanban drag-and-drop | `PATCH` status on drop | `@dnd-kit` |
| Revenue value | `value` field | Card + form |
| Follow-up date | `next_followup` field | Form + card label |
| Convert to client | `POST /leads/{id}/convert` | Won column button |

---

## Manual test checklist

Run with backend (`docker compose up`) and frontend (`npm run dev`). Login as **owner** or **manager**.

- [ ] Open **Leads** — 5 columns visible (New → Lost)
- [ ] **Add Lead** — name, value, optional follow-up date → appears in **New**
- [ ] Card shows **₹ value** and **follow-up** text (if set)
- [ ] **Drag** lead to Contacted → Proposal → Won (stays in column after refresh)
- [ ] On **Won**, click **Convert to client** (lead must have **email**)
- [ ] **Clients** page — new client listed
- [ ] Drag lead to **Lost** — moves correctly

---

## API quick test (optional)

```bash
# After login, use token from browser or register
curl http://localhost:8000/api/v1/leads -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Still planned (remaining ~80%)

- Edit lead from UI (dialog)
- Delete lead from card
- Filter / search leads
- Assign lead to team member on form
- Overdue follow-ups dashboard widget

---

## Files

| Area | Path |
|------|------|
| API | `app/api/v1/leads.py` |
| Model | `app/models/lead.py` |
| Kanban UI | `src/components/leads/leads-kanban.tsx` |
| Add form | `src/components/leads/lead-form-dialog.tsx` |
