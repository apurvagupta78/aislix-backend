-- Unified audit creation: assignment-level evidence policy and RCA controls.
-- Additive and backward compatible with existing assignment execution.

ALTER TABLE public.scan_assignments
  ADD COLUMN IF NOT EXISTS evidence_policy JSONB NOT NULL DEFAULT jsonb_build_object(
    'level', 'standard',
    'requiredProof', jsonb_build_array('context_photo', 'variance_photo'),
    'captureSource', 'either',
    'minimumPhotos', 1,
    'qualityChecks', jsonb_build_array('blur', 'dark', 'duplicate_hash'),
    'reviewMode', 'manager'
  ),
  ADD COLUMN IF NOT EXISTS require_rca BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS reviewer_id UUID REFERENCES auth.users(id),
  ADD COLUMN IF NOT EXISTS creation_source TEXT NOT NULL DEFAULT 'legacy'
    CHECK (creation_source IN ('legacy', 'unified_new_audit', 'schedule', 'api')),
  ADD COLUMN IF NOT EXISTS input_source TEXT
    CHECK (input_source IS NULL OR input_source IN (
      'manual_rows', 'csv_upload', 'existing_planogram', 'camera', 'photo_upload', 'template'
    ));

COMMENT ON COLUMN public.scan_assignments.evidence_policy IS
  'Immutable assignment evidence requirements selected by manager. Template minimums cannot be weakened.';
COMMENT ON COLUMN public.scan_assignments.require_rca IS
  'When true, every non-zero variance requires RCA before successful submission.';

ALTER TABLE public.scan_assignments
  DROP CONSTRAINT IF EXISTS scan_assignments_independent_reviewer_check;
ALTER TABLE public.scan_assignments
  ADD CONSTRAINT scan_assignments_independent_reviewer_check
  CHECK (reviewer_id IS NULL OR reviewer_id <> assignee_id);

-- Freeze assignment controls once execution starts. Only status/review fields may
-- change through existing workflow services.
CREATE OR REPLACE FUNCTION public.protect_assignment_control_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.status <> 'pending' AND (
    NEW.evidence_policy IS DISTINCT FROM OLD.evidence_policy OR
    NEW.require_rca IS DISTINCT FROM OLD.require_rca OR
    NEW.template_snapshot IS DISTINCT FROM OLD.template_snapshot OR
    NEW.scope_values IS DISTINCT FROM OLD.scope_values
  ) THEN
    RAISE EXCEPTION 'Audit scope, template, evidence policy and RCA policy are immutable after execution starts';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS protect_assignment_control_snapshot_trigger
  ON public.scan_assignments;
CREATE TRIGGER protect_assignment_control_snapshot_trigger
BEFORE UPDATE ON public.scan_assignments
FOR EACH ROW EXECUTE FUNCTION public.protect_assignment_control_snapshot();

-- Server validation helper used before audit approval/submission.
CREATE OR REPLACE FUNCTION public.validate_assignment_rca(p_assignment_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_org UUID;
  v_require BOOLEAN;
  v_missing INT := 0;
BEGIN
  SELECT org_id, require_rca
  INTO v_org, v_require
  FROM public.scan_assignments
  WHERE id = p_assignment_id;

  IF v_org IS NULL OR NOT public.is_org_member(v_org) THEN
    RAISE EXCEPTION 'Assignment not found or access denied';
  END IF;

  IF NOT v_require THEN
    RETURN jsonb_build_object('ok', true, 'missingRcaCount', 0);
  END IF;

  SELECT COUNT(*)::INT
  INTO v_missing
  FROM public.digital_audit_lines l
  JOIN public.shelf_scans s ON s.id = l.scan_id
  WHERE s.assignment_id = p_assignment_id
    AND COALESCE(l.variance_qty, 0) <> 0
    AND NULLIF(trim(COALESCE(l.rca_code, '')), '') IS NULL;

  RETURN jsonb_build_object(
    'ok', v_missing = 0,
    'missingRcaCount', v_missing,
    'message', CASE
      WHEN v_missing = 0 THEN 'RCA requirements satisfied'
      ELSE 'Every non-zero variance requires an RCA'
    END
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.validate_assignment_rca(UUID) TO authenticated;
