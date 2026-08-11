# Lovable: Manager / Owner dashboard & team workflow (M6)

For **owner / admin / manager** role in current org. Tables: `scan_assignments`, `shelf_scans`, `planogram_comparisons`, `organization_members`, `stores`, `profiles`, `notifications`.

Do not delete `organization_members` rows when fixing invites. Use upsert on `(org_id, user_id)` or `(org_id, invited_email)`.

---

## 1. Dashboard — Assignment scans widget

Add section **"Team assignments"** on `/dashboard` (manager+ only):

```typescript
const { data } = await supabase
  .from('scan_assignments')
  .select(`
    id, status, due_at, last_compliance_percent, scope_type, scope_values,
    assignee:assignee_id ( id, full_name, email ),
    store:store_id ( name ),
    assigner:assigner_id ( full_name )
  `)
  .eq('org_id', currentOrgId)
  .order('updated_at', { ascending: false })
  .limit(10);
```

Table/card columns:
- **Assignee** (profile name)
- **Store · scope** (aisle from planogram or scope_values)
- **Status** badge: pending | in_progress | needs_correction | completed | overdue
- **Compliance** — `last_compliance_percent` % (color: green 100, yellow 70–99, red <70, — if not scanned)
- **Due** date
- Link **View** → assignment detail or `/results?scan={scan_id}` if scan_id set

Empty state: "No assignments yet — assign from Store Master or Assigned Scans."

---

## 2. Scan history — assignment context

On `/scan-history`, extend query:

```typescript
.select(`*, assignment:assignment_id ( id, status, assignee_id, last_compliance_percent )`)
```

Add columns (manager sees assignee; member sees own only):
- **Type** — "Assigned" badge if `assignment_id` not null, else "Ad hoc"
- **Assignment status** — from join
- **Planogram compliance** — from `shelf_scans` or latest `planogram_comparisons.compliance_percent`

Filter dropdown: All | Assigned only | Ad hoc only

---

## 3. Reports — assignee + compliance

On `/reports` (manager reports list / export):

Join scans with assignments:

```typescript
.from('shelf_scans')
.select(`
  id, created_at, store_id, location, category,
  assignment_id,
  assignment:assignment_id (
    status, last_compliance_percent,
    assignee:assignee_id ( full_name, email )
  ),
  comparison:planogram_comparisons ( compliance_percent, summary )
`)
.eq('org_id', orgId)
```

Report table / PDF / CSV columns add:
- **Assignee**
- **Assignment status**
- **Planogram compliance %**

Filter by assignee, assignment status, date range.

---

## 4. Organization & stores — team on store card

On **Settings → Organization & stores** (or `/stores`):

For each store card/row, show **Team members** with access:

```typescript
// organization_members where store_ids contains store.id OR store_ids is null/empty (all stores)
.from('organization_members')
.select('user_id, role, status, invited_email, profiles(full_name, email)')
.eq('org_id', orgId)
.eq('status', 'active')
```

Display: avatar, name, **role** badge (owner/admin/manager/member), scoped stores if `store_ids` set.

---

## 5. Team & user management — invite + email

On `/team` Invite user modal:

Fields: email, role (member | manager | admin), optional store scope (multi-select store ids → `store_ids uuid[]`).

**Upsert** (fix duplicate key):

```typescript
await supabase.from('organization_members').upsert({
  org_id: currentOrgId,
  invited_email: email.toLowerCase(),
  role,
  status: 'invited',
  invited_by: auth.uid(),
  store_ids: selectedStoreIds.length ? selectedStoreIds : null,
}, { onConflict: 'org_id,invited_email' }); // or org_id,user_id when user exists
```

**Invitation email** — Edge Function `invite-team-member`:

- Trigger: after successful upsert OR dedicated RPC
- Use Resend (or Supabase auth invite) with:
  - Subject: "You're invited to {orgName} on Aislix"
  - Body: role, inviter name, link `https://aislix.lovable.app/accept-invite?org={orgId}&email={email}`
- On accept/login: match `invited_email` → set `user_id`, `status=active`

Show **Pending invites** table: email, role, invited_at, Resend button.

Test: invite new email → receives email → accepts → appears in team list.

---

## 6. Store creation — assign users + roles

On **Create store** modal/wizard, add step **"Team access"**:

- Multi-select from active `organization_members` (or invite inline)
- Per user: role at store level OR attach store id to member's `store_ids` array
- On submit:
  1. Insert `stores` row
  2. Update selected members: `store_ids = array_append(store_ids, new_store_id)` (dedupe)

Managers/owners always see all stores; members only stores in `store_ids`.

---

## 7. Store Master — Assign from planogram

On **Store Master** (`/store-master`), after planogram is **active** (status=active, items loaded):

Add primary action **"Assign scan"** (same modal as Assigned Scans page):

Pre-fill from context:
- `store_id`, `planogram_version_id` = active version
- Scope from UI selection (category / sub_category / location) defaulting to planogram's dominant category
- Expected count = filtered `planogram_items` count

Flow:
1. Upload CSV or manual rows → Activate planogram
2. **Assign scan** button enabled only when `planogram_versions.status = 'active'`
3. Opens assign modal → pick assignee, scope, due date → creates `scan_assignments` + notification

Disable assign if planogram is still draft.

---

## Roles & visibility

| Page / widget | owner | admin | manager | member |
|---------------|-------|-------|---------|--------|
| Dashboard assignments widget | ✓ | ✓ | ✓ | hide |
| Scan history assignee column | ✓ | ✓ | ✓ | own scans only |
| Reports assignee filter | ✓ | ✓ | ✓ | hide |
| Team invite | ✓ | ✓ | ✓ | hide |
| Store Master assign | ✓ | ✓ | ✓ | hide |

---

## Test checklist (org baa046ec, Apurv owner)

1. Dashboard shows Hello's "Test · A-1-Z" assignment, needs_correction, 13%
2. Scan history row shows Assigned + compliance
3. Reports export includes assignee + compliance
4. Stores page lists Hello as member
5. Invite sends email to test address
6. New store wizard assigns member to store
7. Store Master → active planogram → Assign scan → Hello notified
