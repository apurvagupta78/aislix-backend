-- Pricing entitlements v2 — centralized plan limits, PAYG, master setups, usage ledger.
-- Mirrors src/lib/plan-entitlements.ts in aislix-frontend.

-- ============ 1. Schema extensions ============

ALTER TABLE public.subscription_plans
  ADD COLUMN IF NOT EXISTS master_setup_limit INTEGER,
  ADD COLUMN IF NOT EXISTS price_per_audit_inr INTEGER,
  ADD COLUMN IF NOT EXISTS entitlements JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.subscription_plans.master_setup_limit IS 'Max active master shelf setups / planograms per org';
COMMENT ON COLUMN public.subscription_plans.price_per_audit_inr IS 'PAYG price per completed AI audit (INR)';
COMMENT ON COLUMN public.subscription_plans.entitlements IS 'Boolean feature flags enforced server-side';

-- ============ 2. Usage ledger (append-only, idempotent per audit) ============

CREATE TABLE IF NOT EXISTS public.usage_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE SET NULL,
  plan_code TEXT NOT NULL,
  usage_type TEXT NOT NULL DEFAULT 'ai_audit',
  usage_quantity INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'completed',
  amount_inr INTEGER,
  billing_period_start TIMESTAMPTZ,
  billing_period_end TIMESTAMPTZ,
  idempotency_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS usage_ledger_org_created_idx
  ON public.usage_ledger (org_id, created_at DESC);

ALTER TABLE public.usage_ledger ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS usage_ledger_org_read ON public.usage_ledger;
CREATE POLICY usage_ledger_org_read ON public.usage_ledger
  FOR SELECT USING (
    org_id IN (SELECT om.org_id FROM public.organization_members om WHERE om.user_id = auth.uid())
  );

GRANT SELECT ON public.usage_ledger TO authenticated;
GRANT ALL ON public.usage_ledger TO service_role;

-- ============ 3. Plan catalogue (aligned with plan-entitlements.ts) ============

INSERT INTO public.subscription_plans (
  code, name, tagline, price_monthly_inr, price_annual_inr,
  scan_quota, store_limit, seat_limit, master_setup_limit, price_per_audit_inr,
  quota_period, history_days, entitlements, is_contact_sales, sort_order, is_active
)
VALUES (
  'payg',
  'Pay as You Go',
  'No monthly commitment. Pay only when you run an audit.',
  0,
  0,
  NULL,
  3,
  3,
  3,
  29,
  'pay_per_use',
  NULL,
  '{"team_assignment":true,"excel_export":true,"public_share_links":true}'::jsonb,
  false,
  2,
  true
)
ON CONFLICT (code) DO UPDATE SET
  name = EXCLUDED.name,
  tagline = EXCLUDED.tagline,
  price_monthly_inr = EXCLUDED.price_monthly_inr,
  price_annual_inr = EXCLUDED.price_annual_inr,
  scan_quota = EXCLUDED.scan_quota,
  store_limit = EXCLUDED.store_limit,
  seat_limit = EXCLUDED.seat_limit,
  master_setup_limit = EXCLUDED.master_setup_limit,
  price_per_audit_inr = EXCLUDED.price_per_audit_inr,
  quota_period = EXCLUDED.quota_period,
  history_days = EXCLUDED.history_days,
  entitlements = EXCLUDED.entitlements,
  is_contact_sales = EXCLUDED.is_contact_sales,
  sort_order = EXCLUDED.sort_order,
  is_active = EXCLUDED.is_active,
  updated_at = now();

UPDATE public.subscription_plans SET
  tagline = 'Try Aislix before you commit.',
  scan_quota = 5,
  store_limit = 1,
  seat_limit = 1,
  master_setup_limit = 1,
  price_per_audit_inr = NULL,
  quota_period = 'rolling_24h',
  history_days = 7,
  price_monthly_inr = 0,
  price_annual_inr = 0,
  sort_order = 1,
  entitlements = '{"csv_export":true,"pdf_export":true}'::jsonb,
  updated_at = now()
WHERE code = 'free';

UPDATE public.subscription_plans SET
  tagline = 'For local stores and small retail teams.',
  scan_quota = 300,
  store_limit = 3,
  seat_limit = 3,
  master_setup_limit = 5,
  price_monthly_inr = 999,
  price_annual_inr = 9960,
  quota_period = 'month',
  history_days = NULL,
  sort_order = 3,
  entitlements = '{"excel_export":true,"email_reports":true,"team_assignment":true}'::jsonb,
  updated_at = now()
WHERE code = 'starter';

UPDATE public.subscription_plans SET
  tagline = 'For growing retail chains, distributors and field teams.',
  scan_quota = 1500,
  store_limit = 10,
  seat_limit = 10,
  master_setup_limit = 25,
  price_monthly_inr = 2499,
  price_annual_inr = 24890,
  quota_period = 'month',
  history_days = NULL,
  sort_order = 4,
  entitlements = '{"brand_analysis":true,"share_of_shelf":true,"commercial_impact":true,"performance_trends":true}'::jsonb,
  updated_at = now()
WHERE code = 'growth';

UPDATE public.subscription_plans SET
  tagline = 'For supermarkets, dark stores, FMCG brands and larger retail teams.',
  scan_quota = 5000,
  store_limit = 25,
  seat_limit = 25,
  master_setup_limit = 100,
  price_monthly_inr = 4999,
  price_annual_inr = 49790,
  quota_period = 'month',
  history_days = NULL,
  sort_order = 5,
  entitlements = '{"api_access":true,"advanced_benchmarking":true}'::jsonb,
  updated_at = now()
WHERE code = 'professional';

UPDATE public.subscription_plans SET
  tagline = 'For national retail networks, FMCG organizations and large distributor operations.',
  scan_quota = NULL,
  store_limit = NULL,
  seat_limit = NULL,
  master_setup_limit = NULL,
  is_contact_sales = true,
  sort_order = 6,
  entitlements = '{"enterprise_integrations":true}'::jsonb,
  updated_at = now()
WHERE code = 'enterprise';

-- ============ 4. Master setup counting ============

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

CREATE OR REPLACE FUNCTION public.enforce_master_setup_limit()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF COALESCE(NEW.status, 'draft') = 'archived' THEN
    RETURN NEW;
  END IF;

  IF NOT public.can_org_add_master_setup(NEW.org_id) THEN
    RAISE EXCEPTION 'MASTER_SETUP_LIMIT_REACHED: You''ve reached your Master Setup limit. Upgrade plan to add more.'
      USING ERRCODE = 'P0001';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS planogram_versions_enforce_limit ON public.planogram_versions;
CREATE TRIGGER planogram_versions_enforce_limit
  BEFORE INSERT ON public.planogram_versions
  FOR EACH ROW
  EXECUTE FUNCTION public.enforce_master_setup_limit();

-- ============ 5. Usage ledger on completed audit (idempotent) ============

CREATE OR REPLACE FUNCTION public.record_audit_usage_on_complete()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  plan_code TEXT;
  price_per_audit INT;
  period_start TIMESTAMPTZ;
  period_end TIMESTAMPTZ;
  updated_rows INT;
BEGIN
  IF NEW.status = 'completed'
     AND (OLD.status IS DISTINCT FROM 'completed')
     AND NEW.processing_completed_at IS NOT NULL THEN

    SELECT sp.code, sp.price_per_audit_inr, s.current_period_start, s.current_period_end
    INTO plan_code, price_per_audit, period_start, period_end
    FROM public.subscriptions s
    JOIN public.subscription_plans sp ON sp.id = s.plan_id
    WHERE s.org_id = NEW.org_id
    FOR UPDATE;

    INSERT INTO public.usage_ledger (
      org_id, user_id, scan_id, plan_code, usage_type, usage_quantity, status,
      amount_inr, billing_period_start, billing_period_end, idempotency_key
    )
    VALUES (
      NEW.org_id,
      NEW.created_by,
      NEW.id,
      COALESCE(plan_code, 'free'),
      'ai_audit',
      1,
      'completed',
      CASE WHEN plan_code = 'payg' THEN COALESCE(price_per_audit, 29) ELSE NULL END,
      period_start,
      period_end,
      NEW.id::text
    )
    ON CONFLICT (org_id, idempotency_key) DO NOTHING;

    IF plan_code IS DISTINCT FROM 'free' AND plan_code IS DISTINCT FROM 'payg' THEN
      UPDATE public.subscriptions
      SET scans_used = scans_used + 1, updated_at = now()
      WHERE org_id = NEW.org_id
        AND (
          SELECT sp.scan_quota FROM public.subscription_plans sp
          JOIN public.subscriptions s ON s.plan_id = sp.id
          WHERE s.org_id = NEW.org_id
        ) IS NULL
         OR scans_used < (
          SELECT sp.scan_quota FROM public.subscription_plans sp
          JOIN public.subscriptions s ON s.plan_id = sp.id
          WHERE s.org_id = NEW.org_id
        )
      RETURNING 1 INTO updated_rows;

      IF updated_rows IS NULL AND plan_code NOT IN ('enterprise') THEN
        RAISE EXCEPTION 'SCAN_LIMIT_REACHED: Plan audit allowance exceeded.'
          USING ERRCODE = 'P0001';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS shelf_scans_usage_on_complete ON public.shelf_scans;
CREATE TRIGGER shelf_scans_usage_on_complete
  AFTER UPDATE OF status ON public.shelf_scans
  FOR EACH ROW
  EXECUTE FUNCTION public.record_audit_usage_on_complete();

-- ============ 6. can_org_start_scan — PAYG always allowed ============
-- Must keep parameter name `p_org_id` — Postgres rejects CREATE OR REPLACE when
-- the input parameter name changes (42P13).

CREATE OR REPLACE FUNCTION public.can_org_start_scan(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
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

  PERFORM public.ensure_org_free_subscription(p_org_id);
  PERFORM public.reset_subscription_period_if_due(p_org_id);

  SELECT sp.code, sp.scan_quota, s.scans_used
  INTO plan_code, scan_quota, scans_used
  FROM public.subscriptions s
  JOIN public.subscription_plans sp ON sp.id = s.plan_id
  WHERE s.org_id = p_org_id AND s.status IN ('active', 'trialing');

  IF NOT FOUND THEN
    plan_code := 'free';
  END IF;

  IF plan_code IN ('enterprise', 'payg') OR scan_quota IS NULL THEN
    RETURN TRUE;
  END IF;

  IF plan_code = 'free' THEN
    SELECT * INTO free_status FROM public.free_plan_scan_status(p_org_id);
    RETURN NOT free_status.blocked;
  END IF;

  RETURN COALESCE(scans_used, 0) < scan_quota;
END;
$$;

REVOKE ALL ON FUNCTION public.can_org_start_scan(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.can_org_start_scan(UUID) TO authenticated, service_role;

-- ============ 7. Feature entitlement check ============

CREATE OR REPLACE FUNCTION public.org_has_plan_feature(_org_id UUID, _feature TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  plan_code TEXT;
  ents JSONB;
BEGIN
  IF public.org_has_platform_bypass(_org_id) THEN
    RETURN TRUE;
  END IF;

  SELECT sp.code, sp.entitlements
  INTO plan_code, ents
  FROM public.subscriptions s
  JOIN public.subscription_plans sp ON sp.id = s.plan_id
  WHERE s.org_id = _org_id AND s.status IN ('active', 'trialing');

  IF NOT FOUND THEN
    RETURN FALSE;
  END IF;

  IF plan_code = 'enterprise' THEN
    RETURN TRUE;
  END IF;

  RETURN COALESCE((ents ->> _feature)::boolean, FALSE);
END;
$$;

REVOKE ALL ON FUNCTION public.org_has_plan_feature(UUID, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.org_has_plan_feature(UUID, TEXT) TO authenticated, service_role;

-- ============ 8. Extended usage summary RPC ============

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
