-- Platform access grants: internal testers bypass plan limits (scans, stores, history).
-- Apply in Lovable Cloud SQL editor on the LIVE Supabase project.

CREATE TABLE IF NOT EXISTS public.platform_access_grants (
  email TEXT PRIMARY KEY,
  bypass_scan_limits BOOLEAN NOT NULL DEFAULT TRUE,
  bypass_store_limits BOOLEAN NOT NULL DEFAULT TRUE,
  bypass_history_limits BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.platform_access_grants ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS platform_access_grants_service ON public.platform_access_grants;
CREATE POLICY platform_access_grants_service ON public.platform_access_grants
  FOR ALL TO service_role USING (true) WITH CHECK (true);

INSERT INTO public.platform_access_grants (email, note)
VALUES ('apurv@aislix.com', 'Platform admin — unlimited scans/stores for plan testing')
ON CONFLICT (email) DO UPDATE SET
  is_active = TRUE,
  bypass_scan_limits = TRUE,
  bypass_store_limits = TRUE,
  bypass_history_limits = TRUE,
  note = EXCLUDED.note,
  updated_at = now();

-- ============ Helpers ============

CREATE OR REPLACE FUNCTION public.user_email_has_platform_bypass(_email TEXT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.platform_access_grants g
    WHERE g.is_active
      AND g.bypass_scan_limits
      AND lower(trim(g.email)) = lower(trim(_email))
  );
$$;

CREATE OR REPLACE FUNCTION public.org_has_platform_bypass(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  jwt_email TEXT := lower(trim(coalesce(auth.jwt() ->> 'email', '')));
BEGIN
  IF jwt_email <> '' AND public.user_email_has_platform_bypass(jwt_email) THEN
    RETURN TRUE;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'organization_members'
  ) THEN
    RETURN EXISTS (
      SELECT 1
      FROM public.organization_members om
      JOIN auth.users u ON u.id = om.user_id
      JOIN public.platform_access_grants g ON lower(trim(g.email)) = lower(trim(u.email))
      WHERE om.org_id = p_org_id
        AND g.is_active
        AND g.bypass_scan_limits
    );
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'profiles' AND column_name = 'org_id'
  ) THEN
    RETURN EXISTS (
      SELECT 1
      FROM public.profiles p
      JOIN auth.users u ON u.id = p.id
      JOIN public.platform_access_grants g ON lower(trim(g.email)) = lower(trim(u.email))
      WHERE p.org_id = p_org_id
        AND g.is_active
        AND g.bypass_scan_limits
    );
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'org_members'
  ) THEN
    RETURN EXISTS (
      SELECT 1
      FROM public.org_members om
      JOIN auth.users u ON u.id = om.user_id
      JOIN public.platform_access_grants g ON lower(trim(g.email)) = lower(trim(u.email))
      WHERE om.org_id = p_org_id
        AND g.is_active
        AND g.bypass_scan_limits
    );
  END IF;

  RETURN FALSE;
END;
$$;

CREATE OR REPLACE FUNCTION public.org_has_platform_store_bypass(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  jwt_email TEXT := lower(trim(coalesce(auth.jwt() ->> 'email', '')));
BEGIN
  IF jwt_email <> '' AND EXISTS (
    SELECT 1 FROM public.platform_access_grants g
    WHERE g.is_active AND g.bypass_store_limits AND lower(trim(g.email)) = jwt_email
  ) THEN
    RETURN TRUE;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'organization_members'
  ) THEN
    RETURN EXISTS (
      SELECT 1
      FROM public.organization_members om
      JOIN auth.users u ON u.id = om.user_id
      JOIN public.platform_access_grants g ON lower(trim(g.email)) = lower(trim(u.email))
      WHERE om.org_id = p_org_id AND g.is_active AND g.bypass_store_limits
    );
  END IF;

  RETURN public.org_has_platform_bypass(p_org_id);
END;
$$;

REVOKE ALL ON FUNCTION public.user_email_has_platform_bypass(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.user_email_has_platform_bypass(TEXT) TO authenticated, service_role;

REVOKE ALL ON FUNCTION public.org_has_platform_bypass(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.org_has_platform_bypass(UUID) TO authenticated, service_role;

REVOKE ALL ON FUNCTION public.org_has_platform_store_bypass(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.org_has_platform_store_bypass(UUID) TO authenticated, service_role;

-- ============ Patch limit functions ============

CREATE OR REPLACE FUNCTION public.can_org_start_scan(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  plan_code TEXT;
  scan_quota INT;
  scans_used INT;
  free_status RECORD;
BEGIN
  IF public.org_has_platform_bypass(p_org_id) THEN
    RETURN TRUE;
  END IF;

  PERFORM public.reset_subscription_period_if_due(p_org_id);

  SELECT sp.code, sp.scan_quota, s.scans_used
  INTO plan_code, scan_quota, scans_used
  FROM public.subscriptions s
  JOIN public.subscription_plans sp ON sp.id = s.plan_id
  WHERE s.org_id = p_org_id
    AND s.status IN ('active', 'trialing');

  IF NOT FOUND THEN
    RETURN FALSE;
  END IF;

  IF plan_code = 'enterprise' OR scan_quota IS NULL THEN
    RETURN TRUE;
  END IF;

  IF plan_code = 'free' THEN
    SELECT * INTO free_status FROM public.free_plan_scan_status(p_org_id);
    RETURN NOT free_status.blocked;
  END IF;

  RETURN scans_used < scan_quota;
END;
$$;

CREATE OR REPLACE FUNCTION public.can_org_add_store(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  store_limit INT;
  store_count INT;
BEGIN
  IF public.org_has_platform_store_bypass(p_org_id) THEN
    RETURN TRUE;
  END IF;

  SELECT sp.store_limit
  INTO store_limit
  FROM public.subscriptions s
  JOIN public.subscription_plans sp ON sp.id = s.plan_id
  WHERE s.org_id = p_org_id
    AND s.status IN ('active', 'trialing');

  IF NOT FOUND OR store_limit IS NULL THEN
    RETURN TRUE;
  END IF;

  SELECT COUNT(*)
  INTO store_count
  FROM public.stores
  WHERE org_id = p_org_id
    AND status = 'active';

  RETURN store_count < store_limit;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_org_usage_summary(p_org_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  plan_code TEXT;
  plan_name TEXT;
  scan_quota INT;
  store_limit INT;
  scans_used INT;
  stores_used INT;
  period_end TIMESTAMPTZ;
  free_status RECORD;
  result JSONB;
  is_bypass BOOLEAN := public.org_has_platform_bypass(p_org_id);
BEGIN
  PERFORM public.reset_subscription_period_if_due(p_org_id);

  SELECT sp.code, sp.name, sp.scan_quota, sp.store_limit, s.scans_used, s.current_period_end
  INTO plan_code, plan_name, scan_quota, store_limit, scans_used, period_end
  FROM public.subscriptions s
  JOIN public.subscription_plans sp ON sp.id = s.plan_id
  WHERE s.org_id = p_org_id;

  SELECT COUNT(*) INTO stores_used
  FROM public.stores
  WHERE org_id = p_org_id AND status = 'active';

  IF is_bypass THEN
    result := jsonb_build_object(
      'plan_code', plan_code,
      'plan_name', plan_name,
      'scans_used', COALESCE(scans_used, 0),
      'scans_included', scan_quota,
      'scans_remaining', NULL,
      'scan_limit_label', COALESCE(
        CASE WHEN scan_quota IS NULL THEN 'Unlimited scans' ELSE scan_quota::text || ' scans / month' END,
        '3 scans / 24 hours'
      ),
      'blocked', FALSE,
      'cooldown_until', NULL,
      'stores_used', stores_used,
      'stores_included', store_limit,
      'history_days', NULL,
      'period_end', period_end,
      'platform_bypass', TRUE,
      'platform_bypass_note', 'Internal tester — plan limits not enforced'
    );
    RETURN result;
  END IF;

  IF plan_code = 'free' THEN
    SELECT * INTO free_status FROM public.free_plan_scan_status(p_org_id);
    result := jsonb_build_object(
      'plan_code', plan_code,
      'plan_name', plan_name,
      'scans_used', free_status.scans_used_in_batch,
      'scans_included', 3,
      'scans_remaining', GREATEST(0, 3 - free_status.scans_used_in_batch),
      'scan_limit_label', '3 scans / 24 hours',
      'blocked', free_status.blocked,
      'cooldown_until', free_status.cooldown_until,
      'stores_used', stores_used,
      'stores_included', store_limit,
      'history_days', 7,
      'period_end', period_end,
      'platform_bypass', FALSE
    );
    RETURN result;
  END IF;

  result := jsonb_build_object(
    'plan_code', plan_code,
    'plan_name', plan_name,
    'scans_used', scans_used,
    'scans_included', scan_quota,
    'scans_remaining', CASE WHEN scan_quota IS NULL THEN NULL ELSE GREATEST(0, scan_quota - scans_used) END,
    'scan_limit_label', CASE WHEN scan_quota IS NULL THEN 'Unlimited scans' ELSE scan_quota::text || ' scans / month' END,
    'blocked', CASE WHEN scan_quota IS NULL THEN FALSE ELSE scans_used >= scan_quota END,
    'cooldown_until', NULL,
    'stores_used', stores_used,
    'stores_included', store_limit,
    'history_days', NULL,
    'period_end', period_end,
    'platform_bypass', FALSE
  );
  RETURN result;
END;
$$;
