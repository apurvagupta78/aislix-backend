-- Align free plan with marketing: 5 scans / 24 hours (homepage + landing demo already say 5).
-- Run in Lovable Cloud SQL editor.

UPDATE public.subscription_plans
SET
  scan_quota = 5,
  features = '["5 scans / 24 hours","1 store","Scan history (last 7 days)","AI product detection","PDF audit report"]'::jsonb,
  updated_at = now()
WHERE code = 'free';

-- Rolling 24h batch: after 5 completed scans, lock until 24h from the 5th scan in the batch.
CREATE OR REPLACE FUNCTION public.free_plan_scan_status(_org_id UUID)
RETURNS TABLE (
  scans_used_in_batch INT,
  scans_allowed INT,
  blocked BOOLEAN,
  cooldown_until TIMESTAMPTZ
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  batch_start TIMESTAMPTZ := TIMESTAMPTZ '-infinity';
  batch_count INT := 0;
  batch_limit INT := 5;
  last_scan_at TIMESTAMPTZ;
  unlock_at TIMESTAMPTZ;
  rec RECORD;
BEGIN
  scans_allowed := batch_limit;

  FOR rec IN
    SELECT processing_completed_at AS completed_at
    FROM public.shelf_scans
    WHERE org_id = _org_id
      AND status = 'completed'
      AND processing_completed_at IS NOT NULL
    ORDER BY processing_completed_at ASC
  LOOP
    IF rec.completed_at < batch_start THEN
      CONTINUE;
    END IF;

    batch_count := batch_count + 1;

    IF batch_count = batch_limit THEN
      last_scan_at := rec.completed_at;
      unlock_at := last_scan_at + INTERVAL '24 hours';
      IF now() < unlock_at THEN
        scans_used_in_batch := batch_limit;
        blocked := TRUE;
        cooldown_until := unlock_at;
        RETURN NEXT;
        RETURN;
      END IF;
      batch_start := unlock_at;
      batch_count := 0;
      last_scan_at := NULL;
    END IF;
  END LOOP;

  scans_used_in_batch := batch_count;
  blocked := batch_count >= batch_limit;
  cooldown_until := NULL;
  RETURN NEXT;
END;
$$;

-- Patch usage RPC free-plan branch (based on 20260812130000_plan_seat_limits.sql).
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
  scans_used INT;
  stores_used INT;
  seats_used INT;
  period_end TIMESTAMPTZ;
  free_status RECORD;
  is_bypass BOOLEAN := public.org_has_platform_bypass(p_org_id);
  seat_label TEXT;
  free_scans_included INT := 5;
BEGIN
  PERFORM public.ensure_org_free_subscription(p_org_id);
  PERFORM public.reset_subscription_period_if_due(p_org_id);

  SELECT sp.code, sp.name, sp.scan_quota, sp.store_limit, sp.seat_limit, s.scans_used, s.current_period_end
  INTO plan_code, plan_name, scan_quota, store_limit, seat_limit, scans_used, period_end
  FROM public.subscriptions s
  JOIN public.subscription_plans sp ON sp.id = s.plan_id
  WHERE s.org_id = p_org_id
    AND s.status IN ('active', 'trialing');

  IF NOT FOUND THEN
    plan_code := 'free';
    plan_name := 'Free';
    scan_quota := free_scans_included;
    store_limit := 1;
    seat_limit := 1;
    scans_used := 0;
    period_end := NULL;
  END IF;

  SELECT COUNT(*) INTO stores_used
  FROM public.stores WHERE org_id = p_org_id AND status = 'active';

  seats_used := public.count_org_seats(p_org_id);

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
      'scan_limit_label', COALESCE(
        CASE WHEN scan_quota IS NULL THEN 'Unlimited scans' ELSE scan_quota::text || ' scans / month' END,
        '5 scans / 24 hours'
      ),
      'blocked', FALSE, 'cooldown_until', NULL,
      'stores_used', stores_used, 'stores_included', COALESCE(store_limit, 1),
      'seats_used', seats_used, 'seats_included', seat_limit,
      'seat_limit_label', seat_label,
      'history_days', NULL, 'period_end', period_end,
      'platform_bypass', TRUE,
      'platform_bypass_note', 'Internal tester — plan limits not enforced'
    );
  END IF;

  IF plan_code = 'free' THEN
    SELECT * INTO free_status FROM public.free_plan_scan_status(p_org_id);
    RETURN jsonb_build_object(
      'plan_code', plan_code, 'plan_name', plan_name,
      'scans_used', free_status.scans_used_in_batch, 'scans_included', free_scans_included,
      'scans_remaining', GREATEST(0, free_scans_included - free_status.scans_used_in_batch),
      'scan_limit_label', '5 scans / 24 hours',
      'blocked', free_status.blocked, 'cooldown_until', free_status.cooldown_until,
      'stores_used', stores_used, 'stores_included', COALESCE(store_limit, 1),
      'seats_used', seats_used, 'seats_included', COALESCE(seat_limit, 1),
      'seat_limit_label', seat_label,
      'history_days', 7, 'period_end', period_end, 'platform_bypass', FALSE
    );
  END IF;

  RETURN jsonb_build_object(
    'plan_code', plan_code, 'plan_name', plan_name,
    'scans_used', scans_used, 'scans_included', scan_quota,
    'scans_remaining', CASE WHEN scan_quota IS NULL THEN NULL ELSE GREATEST(0, scan_quota - scans_used) END,
    'scan_limit_label', CASE WHEN scan_quota IS NULL THEN 'Unlimited scans' ELSE scan_quota::text || ' scans / month' END,
    'blocked', CASE WHEN scan_quota IS NULL THEN FALSE ELSE scans_used >= scan_quota END,
    'cooldown_until', NULL, 'stores_used', stores_used, 'stores_included', store_limit,
    'seats_used', seats_used, 'seats_included', seat_limit,
    'seat_limit_label', seat_label,
    'history_days', NULL, 'period_end', period_end, 'platform_bypass', FALSE
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.get_org_usage_summary(UUID) TO authenticated, service_role;
