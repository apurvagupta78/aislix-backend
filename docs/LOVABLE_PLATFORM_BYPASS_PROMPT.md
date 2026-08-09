# Lovable Prompt — Platform bypass for apurv@aislix.com

Paste into Lovable. Run SQL migration first.

---

```
Give apurv@aislix.com unlimited platform access for testing all subscription plans.
This is INTERNAL ONLY — customers must still hit plan limits.

## STEP 1 — Run SQL migration (Supabase Cloud SQL editor)

Run the full file:
supabase/migrations/20260809220000_platform_access_grants.sql

This creates:
- platform_access_grants table with apurv@aislix.com
- org_has_platform_bypass() helper
- Patches can_org_start_scan, can_org_add_store, get_org_usage_summary
- DB triggers still run but bypass returns TRUE for apurv's org

Verify:
SELECT * FROM platform_access_grants;
-- should show apurv@aislix.com active

## STEP 2 — Update src/lib/subscription-limits.ts

Copy changes from docs/subscription-limits.ts:

1. Add PLATFORM_BYPASS_EMAILS = ["apurv@aislix.com"]
2. Add hasPlatformBypass(email) helper
3. assertCanStartScan() — if hasPlatformBypass(user.email) → skip limit check
4. assertCanAddStore() — same bypass
5. fetchUsageSummary() — if platform_bypass from RPC or email → force blocked: false
6. historyCutoffForPlan(planCode, email) — return null (full history) for bypass email

Extend UsageSummary type with optional:
- platform_bypass?: boolean
- platform_bypass_note?: string

## STEP 3 — Scan history (Free plan 7-day limit)

Where scan history is filtered:
const { data: { user } } = await supabase.auth.getUser();
const cutoff = historyCutoffForPlan(usage.plan_code, user?.email);

Bypass email sees ALL history regardless of plan.

## STEP 4 — UI (optional subtle badge)

On Billing / scan page when usage.platform_bypass === true:
- Show small dev-only badge: "Tester access — limits not enforced"
- Still display the org's CURRENT plan name and quotas (so we can test Free vs Starter UI)
- Do NOT show this badge to other users

## STEP 5 — Do NOT change for customers

- Pricing page unchanged
- Other emails still blocked by free 3/24h and monthly quotas
- Do not expose platform_access_grants table in client queries

## Acceptance

1. Log in as apurv@aislix.com on Free plan
2. Run 10+ scans in a row — all succeed (no cooldown, no block)
3. Billing page still shows "Free" plan but blocked=false
4. Can add multiple stores beyond Free limit (1 store)
5. Scan history shows scans older than 7 days
6. Log in as any other user on Free — still blocked after 3 scans / 24h

## Adding more testers later

INSERT INTO platform_access_grants (email, note) VALUES ('other@aislix.com', 'QA');
```

---

## Files in repo

| File | Purpose |
|------|---------|
| `supabase/migrations/20260809220000_platform_access_grants.sql` | DB migration — run in Lovable Supabase |
| `docs/subscription-limits.ts` | Updated TypeScript helpers to copy |
