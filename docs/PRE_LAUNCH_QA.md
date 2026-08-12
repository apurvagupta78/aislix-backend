# Pre-Launch QA — Subscription Plans & Critical Flows

Run this checklist **before making Aislix live**. Fixes are in repo migrations + Lovable prompts.

**Live Supabase project:** `vythviniybatyrdyrmhg`  
**Production frontend:** `https://aislix.com` (preview: `aislix.lovable.app`)  
**Backend API:** `https://aislix-backend-production.up.railway.app`

---

## Phase 0 — Apply remaining SQL (one time)

Run in Lovable **Cloud → SQL editor**, in order:

| # | Migration file | Purpose |
|---|----------------|---------|
| 1 | `20260811150000_onboarding_free_subscription_fix.sql` | ✅ Done (you ran this) |
| 2 | `20260811160000_subscription_hardening.sql` | **Run now** — fixes scan/store limits for new orgs |
| 3 | `20260812130000_plan_seat_limits.sql` | **Team user limits** — Free/Starter 1, Growth 3, Pro 5, Enterprise unlimited |
| 4 | `scripts/verify_subscription_limits.sql` | Verification — all checks should be OK |

---

## Phase 1 — Automated DB verification (5 min)

Run `scripts/verify_subscription_limits.sql` in SQL editor.

**Pass criteria:**
- Section A: 5 plans, all `check_result = OK`
- Section B: **0 rows** (every org has subscription)
- Section C: **0 rows** with bad status (or only expected statuses)
- Section D: 6 functions exist
- Section E: 3 triggers exist
- Section F: every org `check_result = OK`, free orgs show `stores_included = 1`
- Section H: `apurv@aislix.com` bypass grant active

---

## Phase 2 — Plan limit manual tests (15 cases)

Use **3 test accounts** if possible:
- **Owner A** — new signup, free plan (fresh org)
- **Owner B** — test org on free (Hello's org or dedicated test org)
- **Apurv** — platform bypass (limits not enforced, but UI should still show plan)

### Free plan

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 1 | Onboarding first store | New signup → Step 2 → create store | ✅ No "undefined stores" error |
| 2 | First scan | Complete 1 scan | ✅ Succeeds, usage shows 1/3 |
| 3 | Scan limit | Complete 3 scans total | ✅ 4th scan blocked with cooldown message |
| 4 | Store limit | Try adding 2nd store | ✅ Blocked + upgrade CTA (not "undefined") |
| 5 | History limit | View scan history >7 days old | ✅ Hidden + upgrade banner (data still in DB) |

### Starter (temporarily set test org plan in SQL)

```sql
UPDATE subscriptions SET plan_id = (SELECT id FROM subscription_plans WHERE code = 'starter')
WHERE org_id = 'YOUR_TEST_ORG_ID';
```

| # | Test | Expected |
|---|------|----------|
| 6 | 300 scans | Blocked at 301st scan start |
| 7 | 2nd store | Blocked with upgrade message |

### Growth / Professional

Repeat store/scan limit tests at 3 stores / 3000 scans (Growth) and 5 stores / 5000 scans (Professional).

### Enterprise

| # | Test | Expected |
|---|------|----------|
| 12 | Unlimited scans/stores | No blocks, no upgrade CTA on limits |

### Billing & lifecycle

| # | Test | Expected |
|---|------|----------|
| 13 | Period reset | After `current_period_end`, `scans_used` resets to 0 |
| 14 | Upgrade | Change plan → limits apply immediately |
| 15 | Downgrade | Existing stores/scans kept; new over-limit actions blocked |

---

## Phase 3 — Critical user flows (smoke test)

| Flow | Test | Expected |
|------|------|----------|
| Signup | New email → confirm → login | Lands on **/verify-email** → click email link → **/onboarding** → dashboard |
| Onboarding | Complete all 4 steps | Dashboard shows store, no errors |
| Onboarding skip | Skip planogram + team | Dashboard with empty-state CTAs |
| Invited member | Hello joins existing org | No onboarding wizard |
| Assigned scan | Member scans assignment | Planogram compliance returned |
| Manager dashboard | View assignments widget | Shows pending/completed |
| Scan download | Download PDF/CSV | Works (if on plan that includes it) |
| Billing page | View current plan + usage | Matches `get_org_usage_summary` |
| Mobile nav | Sidebar on phone | Usable, no overflow |

---

## Phase 4 — Bugs found & fixed in this audit

### Fixed in repo (apply to live)

| Bug | Impact | Fix |
|-----|--------|-----|
| `stores_included` undefined on onboarding | Blocked first store | Migration `20260811150000` + Lovable prompt |
| `can_org_start_scan` FALSE when no subscription | New users can't scan | Migration `20260811160000` |
| `can_org_add_store` TRUE when no subscription | Unlimited stores bypass | Migration `20260811160000` |
| Subscription `status` NULL invisible to limits | Limits silently broken | Backfill + explicit `'active'` on insert |
| Frontend null RPC fields | "undefined stores" toasts | `normalizeUsageSummary()` in `docs/subscription-limits.ts` |

### Still needs Lovable sync

Paste into Lovable chat:

```
PRE-LAUNCH HARDENING — subscription limits

1. Copy normalizeUsageSummary from docs/subscription-limits.ts into src/lib/subscription-limits.ts
2. fetchUsageSummary must call normalizeUsageSummary on RPC result
3. ALL limit checks must use fetchUsageSummary / assertCanAddStore / assertCanStartScan — never hand-roll plan limits
4. Never show toast with interpolated undefined: use StoreLimitError / ScanLimitError messages only
5. Onboarding: zero stores → always allow first store
6. Billing/usage widgets: handle null gracefully with normalizeUsageSummary defaults

Run migration 20260811160000_subscription_hardening.sql in SQL editor first.
```

---

## Phase 5 — Backend tests (Railway)

From project root:

```bash
py -m pytest tests/ -q
```

**Current backend test areas:** planogram compliance, guided recognition, shelf layout, brand dictionary, detector.

These don't cover Supabase limits (limits are DB-side). Phase 1 SQL script covers that.

---

## Go / No-Go checklist

Before launch, all must be ✅:

- [ ] SQL verification script — all OK
- [ ] Migration `20260811160000` applied
- [ ] Lovable hardening prompt applied
- [ ] Free plan: onboarding + 1 store + 3 scans tested
- [ ] Store limit error shows proper message (not "undefined")
- [ ] Scan limit error shows proper message + cooldown for free
- [ ] Invited member flow works (no false onboarding)
- [ ] Assigned scan + compliance still works on test org
- [ ] Apurv bypass works for internal testing
- [ ] No console errors on dashboard, scan, billing pages

---

## Quick SQL helpers for testing

**Reset free scan batch for test org:**
```sql
-- Only for test orgs — deletes completed scans to reset free batch
DELETE FROM shelf_scans WHERE org_id = 'YOUR_ORG_ID' AND status = 'completed';
```

**Set org to specific plan:**
```sql
UPDATE subscriptions
SET plan_id = (SELECT id FROM subscription_plans WHERE code = 'growth'),
    scans_used = 0
WHERE org_id = 'YOUR_ORG_ID';
```

**Check usage RPC:**
```sql
SELECT public.get_org_usage_summary('YOUR_ORG_ID'::uuid);
```
