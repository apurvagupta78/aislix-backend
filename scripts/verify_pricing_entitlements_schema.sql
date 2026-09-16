-- Verify pricing entitlements schema is in sync (run after 20260916190000 migration).

-- 1. Column must exist
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'subscription_plans'
  AND column_name IN ('master_setup_limit', 'price_per_audit_inr', 'entitlements')
ORDER BY column_name;

-- 2. get_org_usage_summary must execute without master_setup_limit errors
SELECT public.get_org_usage_summary(
  (SELECT org_id FROM public.scan_assignments WHERE id = 'a3c06707-a0a8-427c-9ebc-39a165c0bf6b')
) AS usage_summary;

-- 3. can_org_start_scan gate (used by shelf_scans trigger + frontend submit preflight)
SELECT public.can_org_start_scan(
  (SELECT org_id FROM public.scan_assignments WHERE id = 'a3c06707-a0a8-427c-9ebc-39a165c0bf6b')
) AS can_start_scan;
