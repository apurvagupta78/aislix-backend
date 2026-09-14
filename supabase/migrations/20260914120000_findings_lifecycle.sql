-- Findings lifecycle: Finding → RCA → Corrective Action → SLA → Verification → Closure
-- Additive only. Reuses digital_audit_lines, planogram_comparison_lines, corrective_actions,
-- audit_schedules, notifications, shelf_scans.parent_scan_id.

-- ============ Supporting tables used by frontend but not yet in repo ============

CREATE TABLE IF NOT EXISTS public.audit_exceptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  source_type TEXT NOT NULL,
  source_id UUID NOT NULL,
  scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE SET NULL,
  store_id UUID REFERENCES public.stores(id) ON DELETE SET NULL,
  assignment_id UUID REFERENCES public.scan_assignments(id) ON DELETE SET NULL,
  severity TEXT NOT NULL DEFAULT 'attention',
  lifecycle TEXT NOT NULL DEFAULT 'open',
  owner_id UUID REFERENCES auth.users(id),
  due_at TIMESTAMPTZ,
  title TEXT NOT NULL,
  description TEXT,
  impact_label TEXT,
  shelf_label TEXT,
  sku_label TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, source_type, source_id)
);

ALTER TABLE public.audit_exceptions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_exceptions_select ON public.audit_exceptions;
CREATE POLICY audit_exceptions_select ON public.audit_exceptions
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
DROP POLICY IF EXISTS audit_exceptions_write ON public.audit_exceptions;
CREATE POLICY audit_exceptions_write ON public.audit_exceptions
  FOR ALL TO authenticated
  USING (public.is_org_member(org_id))
  WITH CHECK (public.is_org_member(org_id));

CREATE TABLE IF NOT EXISTS public.audit_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  template_type TEXT NOT NULL DEFAULT 'shelf_audit',
  audit_mode TEXT NOT NULL DEFAULT 'digital',
  scope_type TEXT NOT NULL DEFAULT 'planogram',
  scope_values JSONB NOT NULL DEFAULT '{}'::jsonb,
  instructions TEXT,
  evidence_required BOOLEAN NOT NULL DEFAULT true,
  version INT NOT NULL DEFAULT 1,
  published BOOLEAN NOT NULL DEFAULT false,
  created_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.audit_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_templates_select ON public.audit_templates;
CREATE POLICY audit_templates_select ON public.audit_templates
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
DROP POLICY IF EXISTS audit_templates_manage ON public.audit_templates;
CREATE POLICY audit_templates_manage ON public.audit_templates
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

CREATE TABLE IF NOT EXISTS public.audit_template_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id UUID NOT NULL REFERENCES public.audit_templates(id) ON DELETE CASCADE,
  org_id UUID NOT NULL,
  version INT NOT NULL,
  snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  change_summary TEXT,
  created_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (template_id, version)
);

ALTER TABLE public.audit_template_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_template_versions_select ON public.audit_template_versions;
CREATE POLICY audit_template_versions_select ON public.audit_template_versions
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
DROP POLICY IF EXISTS audit_template_versions_manage ON public.audit_template_versions;
CREATE POLICY audit_template_versions_manage ON public.audit_template_versions
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

-- ============ Findings ============

CREATE TABLE IF NOT EXISTS public.findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE SET NULL,
  assignment_id UUID REFERENCES public.scan_assignments(id) ON DELETE SET NULL,
  store_id UUID REFERENCES public.stores(id) ON DELETE SET NULL,
  digital_audit_line_id UUID REFERENCES public.digital_audit_lines(id) ON DELETE SET NULL,
  comparison_line_id UUID REFERENCES public.planogram_comparison_lines(id) ON DELETE SET NULL,
  source_type TEXT NOT NULL DEFAULT 'digital_variance'
    CHECK (source_type IN (
      'digital_variance', 'planogram_line', 'manual', 'ai_suggested'
    )),
  source_id UUID,
  audit_origin TEXT NOT NULL DEFAULT 'digital'
    CHECK (audit_origin IN ('digital', 'ai', 'ai_assisted')),
  finding_type TEXT NOT NULL
    CHECK (finding_type IN (
      'inventory_shortage', 'inventory_excess', 'out_of_stock', 'wrong_placement',
      'planogram_violation', 'pricing_issue', 'damaged_product', 'expired_product',
      'missing_product', 'receiving_issue', 'display_issue', 'shelf_execution_issue', 'other'
    )),
  severity TEXT NOT NULL DEFAULT 'medium'
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  confirmation_state TEXT NOT NULL DEFAULT 'human_confirmed'
    CHECK (confirmation_state IN ('ai_suggested', 'human_confirmed')),
  title TEXT NOT NULL,
  description TEXT,
  sku TEXT,
  product_name TEXT,
  category TEXT,
  shelf_label TEXT,
  expected_value NUMERIC,
  actual_value NUMERIC,
  variance_units NUMERIC,
  variance_percentage NUMERIC,
  variance_value_inr NUMERIC,
  rca_code TEXT
    CHECK (rca_code IS NULL OR rca_code IN (
      'stock_sold', 'damaged', 'expired', 'missing', 'misplaced',
      'receiving_pending', 'counting_error', 'system_inventory_incorrect', 'other'
    )),
  rca_notes TEXT,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN (
      'open', 'assigned', 'in_progress', 'pending_verification',
      'resolved', 'rejected', 'closed'
    )),
  assigned_to UUID REFERENCES auth.users(id),
  created_by UUID REFERENCES auth.users(id),
  due_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  verified_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS findings_org_status_idx ON public.findings (org_id, status, severity);
CREATE INDEX IF NOT EXISTS findings_scan_idx ON public.findings (scan_id);
CREATE INDEX IF NOT EXISTS findings_store_idx ON public.findings (store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS findings_sku_idx ON public.findings (org_id, sku);

ALTER TABLE public.findings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS findings_select ON public.findings;
CREATE POLICY findings_select ON public.findings
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
DROP POLICY IF EXISTS findings_insert ON public.findings;
CREATE POLICY findings_insert ON public.findings
  FOR INSERT TO authenticated WITH CHECK (public.is_org_member(org_id));
DROP POLICY IF EXISTS findings_update ON public.findings;
CREATE POLICY findings_update ON public.findings
  FOR UPDATE TO authenticated USING (public.is_org_member(org_id));

-- ============ Extend corrective_actions ============

ALTER TABLE public.corrective_actions
  ALTER COLUMN comparison_id DROP NOT NULL;

ALTER TABLE public.corrective_actions
  ADD COLUMN IF NOT EXISTS finding_id UUID REFERENCES public.findings(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS store_id UUID REFERENCES public.stores(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS title TEXT,
  ADD COLUMN IF NOT EXISTS description TEXT,
  ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'medium'
    CHECK (priority IS NULL OR priority IN ('low', 'medium', 'high', 'critical')),
  ADD COLUMN IF NOT EXISTS sla_hours INT,
  ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS start_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES auth.users(id),
  ADD COLUMN IF NOT EXISTS resolution_notes TEXT,
  ADD COLUMN IF NOT EXISTS resolution_qty NUMERIC,
  ADD COLUMN IF NOT EXISTS verified_by UUID REFERENCES auth.users(id),
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS rejection_reason TEXT,
  ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS sku TEXT;

ALTER TABLE public.corrective_actions DROP CONSTRAINT IF EXISTS corrective_actions_status_check;
ALTER TABLE public.corrective_actions
  ADD CONSTRAINT corrective_actions_status_check
  CHECK (status IN (
    'open', 'assigned', 'in_progress', 'pending_verification',
    'resolved', 'rejected', 'overdue', 'closed'
  ));

CREATE INDEX IF NOT EXISTS corrective_actions_finding_idx ON public.corrective_actions (finding_id);
CREATE INDEX IF NOT EXISTS corrective_actions_org_status_idx ON public.corrective_actions (org_id, status, due_at);

-- ============ Resolution evidence (does not touch original audit_evidence) ============

CREATE TABLE IF NOT EXISTS public.resolution_evidence (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  finding_id UUID REFERENCES public.findings(id) ON DELETE CASCADE,
  action_id UUID REFERENCES public.corrective_actions(id) ON DELETE CASCADE,
  storage_path TEXT,
  notes TEXT,
  resolution_qty NUMERIC,
  captured_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.resolution_evidence ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS resolution_evidence_select ON public.resolution_evidence;
CREATE POLICY resolution_evidence_select ON public.resolution_evidence
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
DROP POLICY IF EXISTS resolution_evidence_write ON public.resolution_evidence;
CREATE POLICY resolution_evidence_write ON public.resolution_evidence
  FOR ALL TO authenticated
  USING (public.is_org_member(org_id))
  WITH CHECK (public.is_org_member(org_id));

-- ============ SLA defaults + escalation ============

CREATE TABLE IF NOT EXISTS public.org_sla_defaults (
  org_id UUID PRIMARY KEY,
  critical_hours INT NOT NULL DEFAULT 4,
  high_hours INT NOT NULL DEFAULT 12,
  medium_hours INT NOT NULL DEFAULT 24,
  low_hours INT NOT NULL DEFAULT 72,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.org_sla_defaults ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_sla_defaults_select ON public.org_sla_defaults;
CREATE POLICY org_sla_defaults_select ON public.org_sla_defaults
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
DROP POLICY IF EXISTS org_sla_defaults_manage ON public.org_sla_defaults;
CREATE POLICY org_sla_defaults_manage ON public.org_sla_defaults
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

CREATE TABLE IF NOT EXISTS public.escalation_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  first_role TEXT NOT NULL DEFAULT 'member',
  escalate_after_hours INT NOT NULL DEFAULT 4,
  second_role TEXT NOT NULL DEFAULT 'store_manager',
  second_after_hours INT NOT NULL DEFAULT 12,
  final_role TEXT NOT NULL DEFAULT 'admin',
  notify_in_app BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, severity)
);

ALTER TABLE public.escalation_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS escalation_rules_select ON public.escalation_rules;
CREATE POLICY escalation_rules_select ON public.escalation_rules
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
DROP POLICY IF EXISTS escalation_rules_manage ON public.escalation_rules;
CREATE POLICY escalation_rules_manage ON public.escalation_rules
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

-- ============ Activity timeline ============

CREATE TABLE IF NOT EXISTS public.audit_activity_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE CASCADE,
  finding_id UUID REFERENCES public.findings(id) ON DELETE SET NULL,
  action_id UUID REFERENCES public.corrective_actions(id) ON DELETE SET NULL,
  actor_id UUID REFERENCES auth.users(id),
  event_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_activity_scan_idx
  ON public.audit_activity_events (scan_id, created_at);

ALTER TABLE public.audit_activity_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_activity_select ON public.audit_activity_events;
CREATE POLICY audit_activity_select ON public.audit_activity_events
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
DROP POLICY IF EXISTS audit_activity_insert ON public.audit_activity_events;
CREATE POLICY audit_activity_insert ON public.audit_activity_events
  FOR INSERT TO authenticated WITH CHECK (public.is_org_member(org_id));

-- ============ Re-audit + lock columns ============

ALTER TABLE public.shelf_scans
  ADD COLUMN IF NOT EXISTS reaudit_reason TEXT,
  ADD COLUMN IF NOT EXISTS template_version INT,
  ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ;

ALTER TABLE public.audit_schedules
  ADD COLUMN IF NOT EXISTS name TEXT,
  ADD COLUMN IF NOT EXISTS store_ids UUID[] NOT NULL DEFAULT '{}'::uuid[],
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'paused', 'completed')),
  ADD COLUMN IF NOT EXISTS template_id UUID REFERENCES public.audit_templates(id) ON DELETE SET NULL;

-- ============ Helpers ============

CREATE OR REPLACE FUNCTION public.sla_hours_for_severity(p_org_id UUID, p_severity TEXT)
RETURNS INT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  rec public.org_sla_defaults%ROWTYPE;
BEGIN
  SELECT * INTO rec FROM public.org_sla_defaults WHERE org_id = p_org_id;
  IF NOT FOUND THEN
    RETURN CASE p_severity
      WHEN 'critical' THEN 4
      WHEN 'high' THEN 12
      WHEN 'medium' THEN 24
      ELSE 72
    END;
  END IF;
  RETURN CASE p_severity
    WHEN 'critical' THEN rec.critical_hours
    WHEN 'high' THEN rec.high_hours
    WHEN 'medium' THEN rec.medium_hours
    ELSE rec.low_hours
  END;
END;
$$;

CREATE OR REPLACE FUNCTION public.log_audit_activity(
  p_org_id UUID,
  p_scan_id UUID,
  p_event_type TEXT,
  p_summary TEXT,
  p_finding_id UUID DEFAULT NULL,
  p_action_id UUID DEFAULT NULL,
  p_payload JSONB DEFAULT '{}'::jsonb
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  new_id UUID;
BEGIN
  INSERT INTO public.audit_activity_events (
    org_id, scan_id, finding_id, action_id, actor_id, event_type, summary, payload
  ) VALUES (
    p_org_id, p_scan_id, p_finding_id, p_action_id, auth.uid(), p_event_type, p_summary, p_payload
  ) RETURNING id INTO new_id;
  RETURN new_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.notify_org_role(
  p_org_id UUID,
  p_roles TEXT[],
  p_type TEXT,
  p_title TEXT,
  p_body TEXT,
  p_payload JSONB
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.notifications (user_id, org_id, type, title, body, payload)
  SELECT m.user_id, p_org_id, p_type, p_title, p_body, p_payload
  FROM public.organization_members m
  WHERE m.org_id = p_org_id
    AND m.status = 'active'
    AND m.user_id IS NOT NULL
    AND lower(m.role::text) = ANY (p_roles);
END;
$$;

-- ============ Auto-create findings from digital variance / planogram lines ============

CREATE OR REPLACE FUNCTION public.sync_findings_for_scan(p_scan_id UUID)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  scan_row public.shelf_scans%ROWTYPE;
  origin TEXT;
  inserted INT := 0;
  line RECORD;
  cmp RECORD;
  f_type TEXT;
  f_sev TEXT;
  f_title TEXT;
BEGIN
  SELECT * INTO scan_row FROM public.shelf_scans WHERE id = p_scan_id;
  IF NOT FOUND THEN RETURN 0; END IF;

  origin := CASE COALESCE(scan_row.audit_mode, 'ai')
    WHEN 'ai_assisted' THEN 'ai_assisted'
    WHEN 'digital' THEN 'digital'
    ELSE 'ai'
  END;

  FOR line IN
    SELECT *
    FROM public.digital_audit_lines
    WHERE scan_id = p_scan_id
      AND actual_qty IS NOT NULL
      AND variance_qty IS NOT NULL
      AND variance_qty <> 0
  LOOP
    IF line.actual_qty = 0 AND line.expected_qty > 0 THEN
      f_type := 'out_of_stock';
      f_title := 'Out of stock';
    ELSIF line.variance_qty < 0 THEN
      f_type := 'inventory_shortage';
      f_title := 'Inventory shortage';
    ELSE
      f_type := 'inventory_excess';
      f_title := 'Inventory excess';
    END IF;

    f_sev := CASE
      WHEN line.actual_qty = 0 AND line.expected_qty > 0 THEN 'critical'
      WHEN abs(COALESCE(line.variance_value_inr, 0)) >= 10000 THEN 'critical'
      WHEN abs(COALESCE(line.variance_qty, 0)) >= 10 THEN 'high'
      WHEN abs(COALESCE(line.variance_qty, 0)) >= 3 THEN 'medium'
      ELSE 'low'
    END;

    INSERT INTO public.findings (
      org_id, scan_id, assignment_id, store_id, digital_audit_line_id,
      source_type, source_id, audit_origin, finding_type, severity,
      confirmation_state, title, description, sku, product_name, category, shelf_label,
      expected_value, actual_value, variance_units, variance_percentage, variance_value_inr,
      rca_code, rca_notes, created_by, due_at
    )
    VALUES (
      line.org_id, line.scan_id, line.assignment_id, line.store_id, line.id,
      'digital_variance', line.id, origin, f_type, f_sev,
      CASE WHEN origin = 'ai' THEN 'ai_suggested' ELSE 'human_confirmed' END,
      f_title,
      COALESCE(line.product_name, line.sku, 'SKU variance'),
      line.sku, line.product_name, line.category, line.location,
      line.expected_qty, line.actual_qty, line.variance_qty, line.variance_pct, line.variance_value_inr,
      line.rca_code, line.rca_notes, auth.uid(),
      now() + make_interval(hours => public.sla_hours_for_severity(line.org_id, f_sev))
    )
    ON CONFLICT (org_id, source_type, source_id) DO UPDATE SET
      rca_code = EXCLUDED.rca_code,
      rca_notes = EXCLUDED.rca_notes,
      expected_value = EXCLUDED.expected_value,
      actual_value = EXCLUDED.actual_value,
      variance_units = EXCLUDED.variance_units,
      variance_percentage = EXCLUDED.variance_percentage,
      variance_value_inr = EXCLUDED.variance_value_inr,
      updated_at = now();

    GET DIAGNOSTICS inserted = ROW_COUNT;
  END LOOP;

  FOR cmp IN
    SELECT l.*, c.org_id AS cmp_org, c.scan_id AS cmp_scan, c.store_id AS cmp_store, c.assignment_id AS cmp_assignment
    FROM public.planogram_comparison_lines l
    JOIN public.planogram_comparisons c ON c.id = l.comparison_id
    WHERE c.scan_id = p_scan_id
      AND l.issue_type IS DISTINCT FROM 'correct'
      AND l.issue_type IS DISTINCT FROM 'ok'
  LOOP
    f_type := CASE cmp.issue_type
      WHEN 'missing' THEN 'missing_product'
      WHEN 'wrong_product' THEN 'wrong_placement'
      WHEN 'wrong_location' THEN 'wrong_placement'
      WHEN 'wrong_category' THEN 'planogram_violation'
      WHEN 'qty_mismatch' THEN
        CASE WHEN COALESCE(cmp.actual_qty, 0) = 0 THEN 'out_of_stock' ELSE 'planogram_violation' END
      ELSE 'shelf_execution_issue'
    END;
    f_sev := CASE COALESCE(cmp.severity, 'warning')
      WHEN 'critical' THEN 'critical'
      WHEN 'warning' THEN 'high'
      ELSE 'medium'
    END;
    f_title := CASE f_type
      WHEN 'missing_product' THEN 'Missing product'
      WHEN 'wrong_placement' THEN 'Wrong placement'
      WHEN 'out_of_stock' THEN 'Out of stock'
      WHEN 'planogram_violation' THEN 'Planogram violation'
      ELSE 'Shelf execution issue'
    END;

    INSERT INTO public.findings (
      org_id, scan_id, assignment_id, store_id, comparison_line_id,
      source_type, source_id, audit_origin, finding_type, severity,
      confirmation_state, title, description, sku, product_name, shelf_label,
      expected_value, actual_value, variance_units
    )
    VALUES (
      cmp.cmp_org, cmp.cmp_scan, cmp.cmp_assignment, cmp.cmp_store, cmp.id,
      'planogram_line', cmp.id, origin, f_type, f_sev,
      CASE WHEN origin = 'ai' THEN 'ai_suggested' ELSE 'human_confirmed' END,
      f_title,
      COALESCE(cmp.detail, cmp.expected_product, cmp.actual_product, 'Planogram issue'),
      NULL, COALESCE(cmp.expected_product, cmp.actual_product), NULL,
      cmp.expected_qty, cmp.actual_qty,
      COALESCE(cmp.actual_qty, 0) - COALESCE(cmp.expected_qty, 0)
    )
    ON CONFLICT (org_id, source_type, source_id) DO NOTHING;
  END LOOP;

  PERFORM public.log_audit_activity(
    scan_row.org_id, p_scan_id, 'findings_synced', 'Findings synced from audit results'
  );

  RETURN inserted;
END;
$$;

GRANT EXECUTE ON FUNCTION public.sync_findings_for_scan(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.sla_hours_for_severity(UUID, TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION public.log_audit_activity(UUID, UUID, TEXT, TEXT, UUID, UUID, JSONB) TO authenticated;

-- Lock submitted digital audits (managers may still use source = manager_edit)
CREATE OR REPLACE FUNCTION public.prevent_locked_digital_edits()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  scan_status TEXT;
BEGIN
  SELECT submission_status INTO scan_status
  FROM public.shelf_scans WHERE id = NEW.scan_id;

  IF scan_status IN ('submitted', 'pending_review', 'approved')
     AND NEW.source IS DISTINCT FROM 'manager_edit'
     AND (
       NEW.actual_qty IS DISTINCT FROM OLD.actual_qty
       OR NEW.rca_code IS DISTINCT FROM OLD.rca_code
       OR NEW.rca_notes IS DISTINCT FROM OLD.rca_notes
     ) THEN
    RAISE EXCEPTION 'This audit is locked. Request a re-audit or create a correction instead of changing the original record.';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS digital_audit_lines_lock ON public.digital_audit_lines;
CREATE TRIGGER digital_audit_lines_lock
  BEFORE UPDATE ON public.digital_audit_lines
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_locked_digital_edits();

-- Mark overdue corrective actions
CREATE OR REPLACE FUNCTION public.mark_overdue_corrective_actions()
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  n INT;
BEGIN
  UPDATE public.corrective_actions
  SET status = 'overdue', updated_at = now()
  WHERE due_at IS NOT NULL
    AND due_at < now()
    AND status IN ('open', 'assigned', 'in_progress', 'rejected');
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

GRANT EXECUTE ON FUNCTION public.mark_overdue_corrective_actions() TO authenticated;
