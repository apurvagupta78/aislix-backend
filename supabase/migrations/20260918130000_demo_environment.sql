-- Demo environment: isolated showcase org + procedural audit seed helpers.
-- Templates must exist in audit_templates (run seedSystemTemplatesForOrg first).

-- ============ Organization flag ============

ALTER TABLE public.organizations
  ADD COLUMN IF NOT EXISTS is_demo BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS organizations_is_demo_idx
  ON public.organizations (is_demo) WHERE is_demo = true;

COMMENT ON COLUMN public.organizations.is_demo IS
  'When true, all dashboard/Ask Aislix responses must be labeled as demo data.';

-- Fixed demo org id (deterministic seed target)
CREATE OR REPLACE FUNCTION public.aislix_demo_org_id()
RETURNS UUID
LANGUAGE sql IMMUTABLE AS $$
  SELECT 'd0000000-0000-4000-8000-000000000001'::uuid;
$$;

-- ============ Activity probe ============

CREATE OR REPLACE FUNCTION public.org_has_real_audit_activity(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.scan_assignments
    WHERE org_id = p_org_id
      AND status IN ('completed', 'in_progress')
    LIMIT 1
  );
$$;

GRANT EXECUTE ON FUNCTION public.org_has_real_audit_activity(UUID) TO authenticated;

-- ============ Variance helper (matches digital-audit.ts) ============

CREATE OR REPLACE FUNCTION public.demo_compute_variance(
  p_expected INT,
  p_actual INT,
  p_mrp NUMERIC
)
RETURNS TABLE(variance_qty INT, variance_pct NUMERIC, variance_value_inr NUMERIC)
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
  v_qty INT;
  v_pct NUMERIC;
  v_val NUMERIC;
BEGIN
  v_qty := p_actual - p_expected;
  IF p_expected > 0 THEN
    v_pct := round((v_qty::numeric / p_expected) * 100, 2);
  ELSIF p_actual = 0 THEN
    v_pct := 0;
  ELSE
    v_pct := 100;
  END IF;
  IF p_mrp IS NOT NULL THEN
    v_val := round(v_qty * p_mrp, 2);
  ELSE
    v_val := NULL;
  END IF;
  RETURN QUERY SELECT v_qty, v_pct, v_val;
END;
$$;

-- ============ Single completed audit seed ============

CREATE OR REPLACE FUNCTION public.seed_demo_completed_audit(
  p_org_id UUID,
  p_store_id UUID,
  p_template_id UUID,
  p_assignee_id UUID,
  p_assigner_id UUID,
  p_created_at TIMESTAMPTZ,
  p_completed_at TIMESTAMPTZ,
  p_scenario INT,
  p_operating_model TEXT,
  p_template_name TEXT
)
RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_assignment UUID;
  v_scan UUID;
  v_line RECORD;
  v_sku TEXT;
  v_product TEXT;
  v_brand TEXT;
  v_expected INT;
  v_actual INT;
  v_mrp NUMERIC;
  v_var RECORD;
  v_approval TEXT;
  v_status TEXT;
  v_rca TEXT;
  v_category TEXT;
  v_bin TEXT;
  v_i INT;
BEGIN
  v_status := CASE WHEN p_scenario IN (0, 2) THEN 'completed' ELSE 'completed' END;
  v_approval := CASE
    WHEN p_scenario = 0 THEN 'approved'
    WHEN p_scenario = 1 THEN 'approved'
    WHEN p_scenario = 2 THEN 'flagged'
    WHEN p_scenario = 3 THEN 'approved'
    ELSE 'rejected'
  END;

  INSERT INTO public.scan_assignments (
    org_id, store_id, assignee_id, assigner_id, scope_type, scope_values,
    due_at, instructions, status, audit_mode, approval_status, creation_source,
    template_id, template_version, require_rca, completed_at, created_at, updated_at
  ) VALUES (
    p_org_id, p_store_id, p_assignee_id, p_assigner_id, 'category',
    jsonb_build_object('category', COALESCE(
      CASE p_operating_model
        WHEN 'supermarket' THEN 'Beverages'
        WHEN 'dark_store' THEN 'Instant Foods'
        WHEN 'local_store' THEN 'Groceries'
        WHEN 'warehouse' THEN 'FMCG'
        WHEN 'fmcg_distributor' THEN 'Snacks'
        ELSE 'General'
      END, 'General'
    )),
    p_created_at + interval '2 days',
    format('Demo %s audit — scenario %s', p_template_name, p_scenario + 1),
    v_status, 'digital', v_approval, 'api',
    p_template_id, 1, true, p_completed_at, p_created_at, p_completed_at
  ) RETURNING id INTO v_assignment;

  INSERT INTO public.shelf_scans (
    org_id, store_id, assignment_id, status, audit_mode, submission_status,
    submitted_at, finalized_at, finalized_by, created_by, template_id, created_at, updated_at
  ) VALUES (
    p_org_id, p_store_id, v_assignment, 'completed', 'digital',
    CASE WHEN v_approval = 'approved' THEN 'approved' WHEN v_approval = 'rejected' THEN 'rejected' ELSE 'pending_review' END,
    p_completed_at - interval '30 minutes', p_completed_at, p_assignee_id, p_assignee_id,
    p_template_id, p_created_at, p_completed_at
  ) RETURNING id INTO v_scan;

  UPDATE public.scan_assignments SET scan_id = v_scan WHERE id = v_assignment;

  -- SKU lines — Maggi recurring for dark_store Sec 54 scenarios
  FOR v_i IN 1..5 LOOP
    IF p_operating_model = 'dark_store' AND p_scenario >= 0 THEN
      v_sku := CASE v_i
        WHEN 1 THEN 'MAGGI-70G'
        WHEN 2 THEN 'LAYS-RS50'
        WHEN 3 THEN 'COCA-500ML'
        WHEN 4 THEN 'AMUL-MILK-1L'
        ELSE 'PARLE-G-800G'
      END;
      v_product := CASE v_sku
        WHEN 'MAGGI-70G' THEN 'Maggi 2-Minute Noodles 70g'
        WHEN 'LAYS-RS50' THEN 'Lay''s Classic Salted 50g'
        WHEN 'COCA-500ML' THEN 'Coca-Cola 500ml'
        WHEN 'AMUL-MILK-1L' THEN 'Amul Taaza Milk 1L'
        ELSE 'Parle-G Gold 800g'
      END;
      v_brand := split_part(v_sku, '-', 1);
    ELSE
      v_sku := format('SKU-DEMO-%s-%s', p_scenario, v_i);
      v_product := format('Demo Product %s', v_i);
      v_brand := 'DemoBrand';
    END IF;

    v_expected := 10 + v_i;
    v_actual := v_expected + CASE
      WHEN p_scenario = 0 THEN 0
      WHEN p_scenario = 1 AND v_i = 1 THEN -2
      WHEN p_scenario = 2 AND v_sku = 'MAGGI-70G' THEN -3
      WHEN p_scenario = 3 AND v_i = 2 THEN -1
      WHEN p_scenario = 4 AND v_sku = 'MAGGI-70G' THEN -2
      ELSE 0
    END;
    v_mrp := CASE v_sku
      WHEN 'MAGGI-70G' THEN 14.00
      WHEN 'LAYS-RS50' THEN 20.00
      WHEN 'COCA-500ML' THEN 40.00
      WHEN 'AMUL-MILK-1L' THEN 54.00
      ELSE 30.00
    END;
    v_category := CASE p_operating_model
      WHEN 'supermarket' THEN 'Beverages'
      WHEN 'dark_store' THEN 'Instant Foods'
      ELSE 'General'
    END;
    v_bin := format('bin-%s', v_i);
    v_rca := CASE
      WHEN v_actual < v_expected AND v_sku = 'MAGGI-70G' THEN 'stock_sold'
      WHEN v_actual < v_expected THEN 'missing'
      ELSE NULL
    END;

    SELECT * INTO v_var FROM public.demo_compute_variance(v_expected, v_actual, v_mrp);

    INSERT INTO public.digital_audit_lines (
      scan_id, assignment_id, org_id, store_id, sku, brand, product_name, category,
      location, bin_key, expected_qty, actual_qty, mrp_inr,
      variance_qty, variance_pct, variance_value_inr, rca_code, source, entered_by
    ) VALUES (
      v_scan, v_assignment, p_org_id, p_store_id, v_sku, v_brand, v_product, v_category,
      format('Zone %s', (v_i % 3) + 1), v_bin, v_expected, v_actual, v_mrp,
      v_var.variance_qty, v_var.variance_pct, v_var.variance_value_inr, v_rca, 'form', p_assignee_id
    );
  END LOOP;

  PERFORM public.sync_findings_for_scan(v_scan);

  -- Evidence placeholder (path only — upload assets separately)
  INSERT INTO public.audit_evidence (
    scan_id, org_id, bin_key, storage_path, captured_by, captured_at
  ) VALUES (
    v_scan, p_org_id, 'bin-1',
    format('%s/demo/%s/shelf-stacking.jpg', p_org_id, v_scan),
    p_assignee_id, p_completed_at
  ) ON CONFLICT (scan_id, bin_key) DO NOTHING;

  -- Corrective action on flagged/rejected scenarios
  IF p_scenario IN (2, 4) THEN
    INSERT INTO public.corrective_actions (
      org_id, store_id, scan_id, finding_id, issue_type, status, priority,
      title, suggestion, assigned_to, due_at, sla_hours
    )
    SELECT
      p_org_id, p_store_id, v_scan, f.id, f.finding_type,
      CASE WHEN p_scenario = 2 THEN 'open' ELSE 'overdue' END,
      CASE f.severity WHEN 'critical' THEN 'critical' ELSE 'high' END,
      format('Fix %s at demo store', f.title),
      'Restock and verify count',
      p_assignee_id,
      CASE WHEN p_scenario = 4 THEN p_completed_at - interval '3 days' ELSE p_completed_at + interval '2 days' END,
      48
    FROM public.findings f
    WHERE f.scan_id = v_scan AND f.status = 'open'
    LIMIT 2;
  END IF;

  RETURN v_assignment;
END;
$$;

-- ============ Full environment seed ============

CREATE OR REPLACE FUNCTION public.seed_aislix_demo_environment(
  p_owner_user_id UUID,
  p_force BOOLEAN DEFAULT false
)
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_org UUID := public.aislix_demo_org_id();
  v_store RECORD;
  v_tpl RECORD;
  v_scenario INT;
  v_created_at TIMESTAMPTZ;
  v_completed_at TIMESTAMPTZ;
  v_store_id UUID;
  v_audits INT := 0;
  v_templates INT := 0;
  v_days INT;
BEGIN
  IF p_owner_user_id IS NULL THEN
    RAISE EXCEPTION 'owner user id required';
  END IF;

  -- Upsert demo org
  INSERT INTO public.organizations (id, name, slug, owner_id, is_demo, country, industry, customer_type)
  VALUES (v_org, 'Aislix Demo Showcase', 'aislix-demo', p_owner_user_id, true, 'India', 'retail', 'demo')
  ON CONFLICT (id) DO UPDATE SET is_demo = true, name = EXCLUDED.name;

  INSERT INTO public.organization_members (org_id, user_id, role, status)
  VALUES (v_org, p_owner_user_id, 'owner', 'active')
  ON CONFLICT (org_id, user_id) DO UPDATE SET role = 'owner', status = 'active';

  PERFORM public.seed_hierarchy_profiles(v_org);

  -- Demo stores per operating model
  INSERT INTO public.stores (id, org_id, name, city, country, status, store_type)
  VALUES
    ('d0000001-0000-4000-8000-000000000001', v_org, 'More Mart — Bandra', 'Mumbai', 'India', 'active', 'supermarket'),
    ('d0000001-0000-4000-8000-000000000002', v_org, 'Big Bazaar — Koramangala', 'Bangalore', 'India', 'active', 'supermarket'),
    ('d0000001-0000-4000-8000-000000000003', v_org, 'Reliance Fresh — Connaught Place', 'Delhi', 'India', 'active', 'supermarket'),
    ('d0000002-0000-4000-8000-000000000001', v_org, 'Blinkit Dark Store — Sec 54 Gurgaon', 'Gurgaon', 'India', 'active', 'dark_store'),
    ('d0000002-0000-4000-8000-000000000002', v_org, 'Zepto Dark Store — HSR Layout', 'Bangalore', 'India', 'active', 'dark_store'),
    ('d0000003-0000-4000-8000-000000000001', v_org, 'Sharma Kirana — Pune Camp', 'Pune', 'India', 'active', 'local_store'),
    ('d0000003-0000-4000-8000-000000000002', v_org, 'Gupta General Store — Jaipur', 'Jaipur', 'India', 'active', 'local_store'),
    ('d0000004-0000-4000-8000-000000000001', v_org, 'Delhivery WH — Bhiwandi', 'Mumbai', 'India', 'active', 'warehouse'),
    ('d0000004-0000-4000-8000-000000000002', v_org, 'Flipkart FC — Hyderabad', 'Hyderabad', 'India', 'active', 'warehouse'),
    ('d0000005-0000-4000-8000-000000000001', v_org, 'HUL Distributor — Andheri East', 'Mumbai', 'India', 'active', 'outlet'),
    ('d0000005-0000-4000-8000-000000000002', v_org, 'PepsiCo Outlet — Saket', 'Delhi', 'India', 'active', 'outlet')
  ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, status = 'active';

  IF p_force THEN
    DELETE FROM public.corrective_actions WHERE org_id = v_org;
    DELETE FROM public.findings WHERE org_id = v_org;
    DELETE FROM public.digital_audit_lines WHERE org_id = v_org;
    DELETE FROM public.audit_evidence WHERE org_id = v_org;
    DELETE FROM public.shelf_scans WHERE org_id = v_org;
    DELETE FROM public.scan_assignments WHERE org_id = v_org;
  ELSIF EXISTS (SELECT 1 FROM public.scan_assignments WHERE org_id = v_org LIMIT 1) THEN
    RETURN jsonb_build_object(
      'org_id', v_org,
      'skipped', true,
      'message', 'Demo audits already exist. Pass p_force=true to reseed.'
    );
  END IF;

  FOR v_tpl IN
    SELECT id, operating_model, name
    FROM public.audit_templates
    WHERE org_id = v_org AND is_system_template = true AND status = 'published'
    ORDER BY operating_model, name
  LOOP
    v_templates := v_templates + 1;

    SELECT id INTO v_store_id FROM public.stores
    WHERE org_id = v_org AND status = 'active'
      AND (
        (v_tpl.operating_model = 'supermarket' AND store_type = 'supermarket')
        OR (v_tpl.operating_model = 'dark_store' AND store_type = 'dark_store')
        OR (v_tpl.operating_model = 'local_store' AND store_type = 'local_store')
        OR (v_tpl.operating_model = 'warehouse' AND store_type = 'warehouse')
        OR (v_tpl.operating_model = 'fmcg_distributor' AND store_type = 'outlet')
      )
    ORDER BY created_at
    LIMIT 1;

    IF v_store_id IS NULL THEN
      SELECT id INTO v_store_id FROM public.stores WHERE org_id = v_org LIMIT 1;
    END IF;

    FOR v_scenario IN 0..4 LOOP
      v_days := 12 + (v_scenario * 14) + (v_templates % 7);
      v_created_at := now() - (v_days || ' days')::interval;
      v_completed_at := v_created_at + interval '4 hours';

      PERFORM public.seed_demo_completed_audit(
        v_org, v_store_id, v_tpl.id, p_owner_user_id, p_owner_user_id,
        v_created_at, v_completed_at, v_scenario,
        v_tpl.operating_model, v_tpl.name
      );
      v_audits := v_audits + 1;
    END LOOP;
  END LOOP;

  RETURN jsonb_build_object(
    'org_id', v_org,
    'templates_seeded', v_templates,
    'audits_created', v_audits,
    'stores', (SELECT count(*) FROM public.stores WHERE org_id = v_org)
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.seed_aislix_demo_environment(UUID, BOOLEAN) TO authenticated;
GRANT EXECUTE ON FUNCTION public.aislix_demo_org_id() TO authenticated;

-- ============ Read-only demo org access for authenticated users ============

CREATE OR REPLACE FUNCTION public.is_demo_org_readable(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT p_org_id = public.aislix_demo_org_id()
    AND EXISTS (SELECT 1 FROM public.organizations WHERE id = p_org_id AND is_demo = true);
$$;

DO $$
DECLARE
  tbl TEXT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'scan_assignments', 'shelf_scans', 'digital_audit_lines', 'findings',
    'corrective_actions', 'audit_evidence', 'audit_templates', 'stores'
  ] LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS demo_showcase_read ON public.%I;
       CREATE POLICY demo_showcase_read ON public.%I
         FOR SELECT TO authenticated
         USING (public.is_demo_org_readable(org_id));',
      tbl, tbl
    );
  END LOOP;
END $$;
