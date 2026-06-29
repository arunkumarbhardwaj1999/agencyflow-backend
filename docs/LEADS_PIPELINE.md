# Sales Lead Pipeline — Phase 1

**Status:** Done

## Swimlanes

| Stage | Meaning |
|-------|---------|
| **new** | Fresh enquiry |
| **contacted** | First touch done |
| **proposal** | Quote / proposal sent |
| **won** | Deal closed — can convert to client |
| **lost** | Did not convert |

## API

| Feature | Endpoint |
|---------|----------|
| List / create / update / delete | `GET/POST/PATCH/DELETE /api/v1/leads` |
| Convert to client | `POST /api/v1/leads/{id}/convert` |
| Assign team member | `assigned_user_id` on lead + `GET /api/v1/users/members` |

## Manual test

1. Open **Leads** — 5 columns (New → Lost)
2. **Add Lead** → appears in **New**
3. **Drag** between columns (persists after refresh)
4. On **Won**, **Convert to client** (lead needs email)
5. Check **Clients** page for new client
