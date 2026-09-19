-- Sync pricing entitlements v2 schema drift on production.
-- Symptom: get_org_usage_summary / can_org_add_master_setup fail with
--   column sp.master_setup_limit does not exist
-- Cause: function bodies were deployed without subscription_plans columns.

ALTER TABLE public.subscription_plans
  ADD COLUMN IF NOT EXISTS master_setup_limit INTEGER,
  ADD COLUMN IF NOT EXISTS price_per_audit_inr INTEGER,
  ADD COLUMN IF NOT EXISTS entitlements JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.subscription_plans.master_setup_limit IS
  'Max active master shelf setups / planograms per org';
COMMENT ON COLUMN public.subscription_plans.price_per_audit_inr IS
  'PAYG price per completed AI audit (INR)';
COMMENT ON COLUMN public.subscription_plans.entitlements IS
  'Boolean feature flags enforced server-side';

-- Backfill plan catalogue limits when columns were added late.
UPDATE public.subscription_plans SET master_setup_limit = 1, updated_at = now()
WHERE code = 'free' AND master_setup_limit IS NULL;

UPDATE public.subscription_plans SET master_setup_limit = 5, updated_at = now()
WHERE code = 'starter' AND master_setup_limit IS NULL;

UPDATE public.subscription_plans SET master_setup_limit = 25, updated_at = now()
WHERE code = 'growth' AND master_setup_limit IS NULL;

UPDATE public.subscription_plans SET master_setup_limit = 100, updated_at = now()
WHERE code = 'professional' AND master_setup_limit IS NULL;

UPDATE public.subscription_plans SET master_setup_limit = NULL, updated_at = now()
WHERE code = 'enterprise' AND master_setup_limit IS DISTINCT FROM NULL;

UPDATE public.subscription_plans SET master_setup_limit = 3, updated_at = now()
WHERE code = 'payg' AND master_setup_limit IS NULL;

-- Helpers referenced by get_org_usage_summary (no-op if already present).
CREATE OR REPLACE FUNCTION public.count_org_master_setups(_org_id UUID)
RETURNS INTEGER
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT COUNT(*)::INTEGER
  FROM public.planogram_versions pv
  WHERE pv.org_id = _org_id
    AND COALESCE(pv.status, 'draft') <> 'archived';
$$;

REVOKE ALL ON FUNCTION public.count_org_master_setups(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.count_org_master_setups(UUID) TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.can_org_add_master_setup(_org_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  setup_limit INT;
  setup_count INT;
BEGIN
  IF public.org_has_platform_bypass(_org_id) THEN
    RETURN TRUE;
  END IF;

  SELECT sp.master_setup_limit INTO setup_limit
  FROM public.subscriptions s
  JOIN public.subscription_plans sp ON sp.id = s.plan_id
  WHERE s.org_id = _org_id AND s.status IN ('active', 'trialing');

  IF NOT FOUND OR setup_limit IS NULL THEN
    RETURN TRUE;
  END IF;

  setup_count := public.count_org_master_setups(_org_id);
  RETURN setup_count < setup_limit;
END;
$$;

REVOKE ALL ON FUNCTION public.can_org_add_master_setup(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.can_org_add_master_setup(UUID) TO authenticated, service_role;

-- Re-assert get_org_usage_summary matches live columns (from pricing_entitlements_v2).
CREATE OR REPLACE FUNCTION public.get_org_usage_summary(p_org_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  plan_code TEXT;
  plan_name TEXT;
  scan_quota INT;
  store_limit INT;
  seat_limit INT;
  master_limit INT;
  price_per_audit INT;
  scans_used INT;
  stores_used INT;
  seats_used INT;
  masters_used INT;
  period_end TIMESTAMPTZ;
  period_start TIMESTAMPTZ;
  free_status RECORD;
  is_bypass BOOLEAN := public.org_has_platform_bypass(p_org_id);
  seat_label TEXT;
  free_scans_included INT := 5;
  payg_audits INT := 0;
BEGIN
  PERFORM public.ensure_org_free_subscription(p_org_id);
  PERFORM public.reset_subscription_period_if_due(p_org_id);

  SELECT sp.code, sp.name, sp.scan_quota, sp.store_limit, sp.seat_limit,
         sp.master_setup_limit, sp.price_per_audit_inr,
         s.scans_used, s.current_period_start, s.current_period_end
  INTO plan_code, plan_name, scan_quota, store_limit, seat_limit, master_limit,
       price_per_audit, scans_used, period_start, period_end
  FROM public.subscriptions s
  JOIN public.subscription_plans sp ON sp.id = s.plan_id
  WHERE s.org_id = p_org_id AND s.status IN ('active', 'trialing');

  IF NOT FOUND THEN
    plan_code := 'free';
    plan_name := 'Free';
    scan_quota := free_scans_included;
    store_limit := 1;
    seat_limit := 1;
    master_limit := 1;
    scans_used := 0;
  END IF;

  SELECT COUNT(*) INTO stores_used FROM public.stores WHERE org_id = p_org_id AND status = 'active';
  seats_used := public.count_org_seats(p_org_id);
  masters_used := public.count_org_master_setups(p_org_id);

  IF plan_code = 'payg' THEN
    SELECT COUNT(*) INTO payg_audits
    FROM public.usage_ledger
    WHERE org_id = p_org_id
      AND usage_type = 'ai_audit'
      AND status = 'completed'
      AND (period_start IS NULL OR created_at >= period_start);
    scans_used := payg_audits;
  END IF;

  seat_label := CASE
    WHEN seat_limit IS NULL THEN 'Unlimited users'
    WHEN seat_limit = 1 THEN '1 user'
    ELSE seat_limit::text || ' users'
  END;

  IF is_bypass THEN
    RETURN jsonb_build_object(
      'plan_code', plan_code, 'plan_name', plan_name,
      'scans_used', COALESCE(scans_used, 0), 'scans_included', scan_quota,
      'scans_remaining', NULL,
      'scan_limit_label', CASE
        WHEN plan_code = 'payg' THEN 'Pay per completed audit'
        WHEN scan_quota IS NULL THEN 'Unlimited AI audits'
        WHEN plan_code = 'free' THEN '5 AI audits / 24 hours'
        ELSE scan_quota::text || ' AI audits / month'
      END,
      'blocked', FALSE, 'cooldown_until', NULL,
      'stores_used', stores_used, 'stores_included', COALESCE(store_limit, 1),
      'seats_used', seats_used, 'seats_included', seat_limit,
      'seat_limit_label', seat_label,
      'master_setups_used', masters_used,
      'master_setups_included', master_limit,
      'price_per_audit_inr', price_per_audit,
      'history_days', NULL, 'period_start', period_start, 'period_end', period_end,
      'platform_bypass', TRUE,
      'platform_bypass_note', 'Internal tester — plan limits not enforced'
    );
  END IF;

  IF plan_code = 'free' THEN
    SELECT * INTO free_status FROM public.free_plan_scan_status(p_org_id);
    RETURN jsonb_build_object(
      'plan_code', plan_code, 'plan_name', plan_name,
      'scans_used', free_status.scans_used_in_batch,
      'scans_included', free_scans_included,
      'scans_remaining', GREATEST(0, free_scans_included - free_status.scans_used_in_batch),
      'scan_limit_label', '5 AI audits / 24 hours',
      'blocked', free_status.blocked, 'cooldown_until', free_status.cooldown_until,
      'stores_used', stores_used, 'stores_included', COALESCE(store_limit, 1),
      'seats_used', seats_used, 'seats_included', COALESCE(seat_limit, 1),
      'seat_limit_label', seat_label,
      'master_setups_used', masters_used,
      'master_setups_included', COALESCE(master_limit, 1),
      'price_per_audit_inr', NULL,
      'history_days', 7, 'period_start', period_start, 'period_end', period_end,
      'platform_bypass', FALSE
    );
  END IF;

  IF plan_code = 'payg' THEN
    RETURN jsonb_build_object(
      'plan_code', plan_code, 'plan_name', plan_name,
      'scans_used', scans_used, 'scans_included', NULL, 'scans_remaining', NULL,
      'scan_limit_label', 'Pay per completed AI audit',
      'blocked', FALSE, 'cooldown_until', NULL,
      'stores_used', stores_used, 'stores_included', store_limit,
      'seats_used', seats_used, 'seats_included', seat_limit,
      'seat_limit_label', seat_label,
      'master_setups_used', masters_used,
      'master_setups_included', master_limit,
      'price_per_audit_inr', COALESCE(price_per_audit, 29),
      'history_days', NULL, 'period_start', period_start, 'period_end', period_end,
      'platform_bypass', FALSE
    );
  END IF;

  RETURN jsonb_build_object(
    'plan_code', plan_code, 'plan_name', plan_name,
    'scans_used', scans_used, 'scans_included', scan_quota,
    'scans_remaining', CASE WHEN scan_quota IS NULL THEN NULL ELSE GREATEST(0, scan_quota - scans_used) END,
    'scan_limit_label', CASE WHEN scan_quota IS NULL THEN 'Unlimited AI audits' ELSE scan_quota::text || ' AI audits / month' END,
    'blocked', CASE WHEN scan_quota IS NULL THEN FALSE ELSE scans_used >= scan_quota END,
    'cooldown_until', NULL,
    'stores_used', stores_used, 'stores_included', store_limit,
    'seats_used', seats_used, 'seats_included', seat_limit,
    'seat_limit_label', seat_label,
    'master_setups_used', masters_used,
    'master_setups_included', master_limit,
    'price_per_audit_inr', NULL,
    'history_days', NULL, 'period_start', period_start, 'period_end', period_end,
    'platform_bypass', FALSE
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_org_usage_summary(UUID) TO authenticated, service_role;
