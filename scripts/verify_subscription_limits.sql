-- Pre-launch subscription/plan verification script.
-- Run in Lovable Cloud SQL editor. Each section should return expected results.
-- Fix any FAIL rows before going live.

-- ══════════════════════════════════════════════════════════════
-- A. PLAN CATALOGUE — expect 5 active plans with correct limits
-- ══════════════════════════════════════════════════════════════

SELECT
  code,
  scan_quota,
  store_limit,
  seat_limit,
  is_active,
  CASE
    WHEN code = 'free'         AND scan_quota = 5    AND store_limit = 1 AND seat_limit = 1 THEN 'OK'
    WHEN code = 'starter'      AND scan_quota = 300  AND store_limit = 1 AND seat_limit = 1 THEN 'OK'
    WHEN code = 'growth'       AND scan_quota = 3000 AND store_limit = 3 AND seat_limit = 3 THEN 'OK'
    WHEN code = 'professional' AND scan_quota = 5000 AND store_limit = 5 AND seat_limit = 5 THEN 'OK'
    WHEN code = 'enterprise'   AND scan_quota IS NULL AND store_limit IS NULL AND seat_limit IS NULL THEN 'OK'
    ELSE 'FAIL — wrong limits'
  END AS check_result
FROM public.subscription_plans
WHERE is_active = TRUE
ORDER BY sort_order;

-- ══════════════════════════════════════════════════════════════
-- B. ORGS WITHOUT SUBSCRIPTION — expect 0 rows
-- ══════════════════════════════════════════════════════════════

SELECT o.id, o.name, 'FAIL — no subscription' AS check_result
FROM public.organizations o
WHERE NOT EXISTS (SELECT 1 FROM public.subscriptions s WHERE s.org_id = o.id);

-- ══════════════════════════════════════════════════════════════
-- C0. VALID subscription_status ENUM VALUES (informational — run once)
-- ══════════════════════════════════════════════════════════════

SELECT e.enumlabel AS valid_status
FROM pg_enum e
JOIN pg_type t ON t.oid = e.enumtypid
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'public' AND t.typname = 'subscription_status'
ORDER BY e.enumsortorder;

-- ══════════════════════════════════════════════════════════════
-- C. SUBSCRIPTIONS WITH NULL OR NON-ACTIVE STATUS — expect 0 rows
-- (Compare as text — avoids invalid enum literal errors)
-- ══════════════════════════════════════════════════════════════

SELECT s.org_id, s.status::text AS status, sp.code AS plan_code, 'FAIL — bad status' AS check_result
FROM public.subscriptions s
JOIN public.subscription_plans sp ON sp.id = s.plan_id
WHERE s.status IS NULL
   OR s.status::text NOT IN ('active', 'trialing');

-- ══════════════════════════════════════════════════════════════
-- D. RPC FUNCTIONS EXIST — expect 8 rows all OK
-- ══════════════════════════════════════════════════════════════

SELECT proname AS function_name, 'OK' AS check_result
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND proname IN (
    'get_org_usage_summary',
    'can_org_start_scan',
    'can_org_add_store',
    'can_org_add_member',
    'count_org_seats',
    'ensure_org_free_subscription',
    'free_plan_scan_status',
    'reset_subscription_period_if_due'
  )
ORDER BY proname;

-- ══════════════════════════════════════════════════════════════
-- E. TRIGGERS EXIST — expect 4 rows
-- ══════════════════════════════════════════════════════════════

SELECT tgname AS trigger_name, relname AS table_name
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal
  AND tgname IN (
    'stores_enforce_limit',
    'shelf_scans_enforce_limit',
    'shelf_scans_usage_on_complete',
    'organization_members_enforce_seat_limit'
  );

-- ══════════════════════════════════════════════════════════════
-- F. USAGE SUMMARY PER ORG — stores_included must never be null for free/starter/growth/pro
-- ══════════════════════════════════════════════════════════════

SELECT
  o.name AS org_name,
  sp.code AS plan_code,
  u->>'stores_included' AS stores_included,
  u->>'seats_included' AS seats_included,
  u->>'seats_used' AS seats_used,
  u->>'scans_included' AS scans_included,
  u->>'plan_code' AS rpc_plan_code,
  CASE
    WHEN u->>'plan_code' IS NULL THEN 'FAIL — null plan_code'
    WHEN sp.code IN ('free','starter','growth','professional')
         AND (u->>'stores_included') IS NULL THEN 'FAIL — null stores_included'
    WHEN sp.code = 'free' AND (u->>'stores_included')::int <> 1 THEN 'FAIL — free should be 1 store'
    WHEN sp.code = 'free' AND (u->>'seats_included')::int <> 1 THEN 'FAIL — free should be 1 user'
    WHEN sp.code = 'starter' AND (u->>'seats_included')::int <> 1 THEN 'FAIL — starter should be 1 user'
    WHEN sp.code = 'growth' AND (u->>'seats_included')::int <> 3 THEN 'FAIL — growth should be 3 users'
    WHEN sp.code = 'professional' AND (u->>'seats_included')::int <> 5 THEN 'FAIL — professional should be 5 users'
    ELSE 'OK'
  END AS check_result
FROM public.organizations o
JOIN public.subscriptions s ON s.org_id = o.id
JOIN public.subscription_plans sp ON sp.id = s.plan_id
CROSS JOIN LATERAL (
  SELECT public.get_org_usage_summary(o.id) AS u
) rpc
WHERE s.status IN ('active', 'trialing')
ORDER BY o.name;

-- ══════════════════════════════════════════════════════════════
-- G. STORE LIMIT ENFORCEMENT SPOT CHECK (read-only simulation)
-- Replace YOUR_ORG_ID with a test org on free plan with 1 store already
-- ══════════════════════════════════════════════════════════════

-- SELECT public.can_org_add_store('YOUR_ORG_ID'::uuid);  -- expect FALSE if at limit
-- SELECT public.can_org_start_scan('YOUR_ORG_ID'::uuid);  -- expect TRUE if under scan limit

-- ══════════════════════════════════════════════════════════════
-- H. PLATFORM BYPASS — apurv@aislix.com grant exists
-- ══════════════════════════════════════════════════════════════

SELECT email, is_active, bypass_scan_limits, bypass_store_limits,
  CASE WHEN is_active THEN 'OK' ELSE 'FAIL' END AS check_result
FROM public.platform_access_grants
WHERE lower(email) = 'apurv@aislix.com';
