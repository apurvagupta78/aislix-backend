-- Custom Audit Builder & Configurable Audit Engine
-- Extends audit_templates with field definitions, rules, workflow, and response storage.

-- ============ Template builder columns ============

ALTER TABLE public.audit_templates
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'published', 'archived')),
  ADD COLUMN IF NOT EXISTS category TEXT,
  ADD COLUMN IF NOT EXISTS icon TEXT,
  ADD COLUMN IF NOT EXISTS audit_level TEXT NOT NULL DEFAULT 'one_per_audit'
    CHECK (audit_level IN (
      'one_per_audit', 'one_per_sku', 'one_per_shelf',
      'one_per_location', 'repeating_section'
    )),
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS updated_by UUID REFERENCES auth.users(id),
  ADD COLUMN IF NOT EXISTS sections JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS field_definitions JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS rules JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS workflow_settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS scoring_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS ai_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS evidence_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS calculated_fields JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Backfill status from published flag
UPDATE public.audit_templates
SET status = CASE WHEN published THEN 'published' ELSE 'draft' END
WHERE status = 'draft' AND published = true;

-- Expand template_type check (drop/recreate if exists)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'audit_templates_template_type_check'
      AND conrelid = 'public.audit_templates'::regclass
  ) THEN
    ALTER TABLE public.audit_templates DROP CONSTRAINT audit_templates_template_type_check;
  END IF;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

-- ============ Assignment + scan linkage ============

ALTER TABLE public.scan_assignments
  ADD COLUMN IF NOT EXISTS template_id UUID REFERENCES public.audit_templates(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS template_version INT,
  ADD COLUMN IF NOT EXISTS template_snapshot JSONB;

ALTER TABLE public.shelf_scans
  ADD COLUMN IF NOT EXISTS template_id UUID REFERENCES public.audit_templates(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS template_snapshot JSONB;

CREATE INDEX IF NOT EXISTS scan_assignments_template_idx
  ON public.scan_assignments (template_id) WHERE template_id IS NOT NULL;

-- ============ Custom audit responses ============

CREATE TABLE IF NOT EXISTS public.audit_responses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  assignment_id UUID REFERENCES public.scan_assignments(id) ON DELETE CASCADE,
  scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE SET NULL,
  template_id UUID NOT NULL REFERENCES public.audit_templates(id) ON DELETE RESTRICT,
  template_version INT NOT NULL DEFAULT 1,
  section_key TEXT NOT NULL DEFAULT 'default',
  record_index INT NOT NULL DEFAULT 0,
  field_key TEXT NOT NULL,
  field_type TEXT NOT NULL,
  field_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  value JSONB,
  ai_suggested JSONB,
  human_confirmed BOOLEAN NOT NULL DEFAULT false,
  created_by UUID REFERENCES auth.users(id),
  updated_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (assignment_id, section_key, record_index, field_key)
);

CREATE INDEX IF NOT EXISTS audit_responses_assignment_idx
  ON public.audit_responses (assignment_id, section_key, record_index);
CREATE INDEX IF NOT EXISTS audit_responses_scan_idx
  ON public.audit_responses (scan_id) WHERE scan_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS audit_responses_template_idx
  ON public.audit_responses (template_id, template_version);

ALTER TABLE public.audit_responses ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_responses_select ON public.audit_responses;
CREATE POLICY audit_responses_select ON public.audit_responses
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_responses_insert ON public.audit_responses;
CREATE POLICY audit_responses_insert ON public.audit_responses
  FOR INSERT TO authenticated WITH CHECK (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_responses_update ON public.audit_responses;
CREATE POLICY audit_responses_update ON public.audit_responses
  FOR UPDATE TO authenticated
  USING (public.is_org_member(org_id))
  WITH CHECK (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_responses_delete ON public.audit_responses;
CREATE POLICY audit_responses_delete ON public.audit_responses
  FOR DELETE TO authenticated USING (public.is_org_manager(org_id));

-- ============ Publish helper ============

CREATE OR REPLACE FUNCTION public.publish_audit_template(p_template_id UUID)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_org_id UUID;
  v_row public.audit_templates%ROWTYPE;
  v_next_version INT;
  v_user UUID := auth.uid();
BEGIN
  IF NOT public.is_org_manager(
    (SELECT org_id FROM public.audit_templates WHERE id = p_template_id)
  ) THEN
    RAISE EXCEPTION 'Manager access required';
  END IF;

  SELECT * INTO v_row FROM public.audit_templates WHERE id = p_template_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Template not found';
  END IF;

  v_next_version := COALESCE(v_row.version, 0) + 1;

  UPDATE public.audit_templates
  SET
    published = true,
    status = 'published',
    version = v_next_version,
    updated_at = now(),
    updated_by = v_user
  WHERE id = p_template_id
  RETURNING * INTO v_row;

  INSERT INTO public.audit_template_versions (
    template_id, org_id, version, snapshot, change_summary, created_by
  ) VALUES (
    p_template_id,
    v_row.org_id,
    v_next_version,
    to_jsonb(v_row),
    format('Published %s as v%s', v_row.name, v_next_version),
    v_user
  );

  RETURN v_next_version;
END;
$$;

GRANT EXECUTE ON FUNCTION public.publish_audit_template(UUID) TO authenticated;

-- ============ Seed FNV QC demo template (per org on first manager visit via RPC) ============

CREATE OR REPLACE FUNCTION public.seed_fnv_qc_template(p_org_id UUID)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_id UUID;
  v_user UUID := auth.uid();
  v_snapshot JSONB;
BEGIN
  IF NOT public.is_org_manager(p_org_id) THEN
    RAISE EXCEPTION 'Manager access required';
  END IF;

  SELECT id INTO v_id
  FROM public.audit_templates
  WHERE org_id = p_org_id AND name = 'FNV QC Audit'
  LIMIT 1;

  IF v_id IS NOT NULL THEN
    RETURN v_id;
  END IF;

  INSERT INTO public.audit_templates (
    org_id, name, description, template_type, audit_mode, scope_type,
    scope_values, evidence_required, published, status, category, icon,
    audit_level, sections, field_definitions, rules, workflow_settings,
    scoring_config, ai_config, evidence_config, calculated_fields, created_by
  ) VALUES (
    p_org_id,
    'FNV QC Audit',
    'Fresh & Near-expiry quality control audit for store inventory.',
    'fnv_qc_audit',
    'digital',
    'category',
    '{"category":"Fresh Produce"}'::jsonb,
    true,
    false,
    'draft',
    'Fresh Produce',
    'leaf',
    'one_per_sku',
    '[
      {"key":"store_info","title":"Store Information","order":0},
      {"key":"product","title":"Product Information","order":1,"repeatable":true},
      {"key":"quality","title":"Quality & Evidence","order":2,"repeatable":true}
    ]'::jsonb,
    '[
      {"id":"f1","key":"store","type":"store","label":"Store","section":"store_info","order":0,"required":true,"config":{}},
      {"id":"f2","key":"auditor","type":"auditor","label":"Auditor","section":"store_info","order":1,"required":true,"config":{},"system":true},
      {"id":"f3","key":"audit_date","type":"audit_date","label":"Audit Date","section":"store_info","order":2,"required":true,"config":{}},
      {"id":"f4","key":"gps","type":"gps","label":"GPS Location","section":"store_info","order":3,"required":false,"config":{"requireGps":false}},
      {"id":"f5","key":"sku_id","type":"sku_id","label":"SKU ID","section":"product","order":0,"required":true,"config":{}},
      {"id":"f6","key":"item_code","type":"item_code","label":"Item Code","section":"product","order":1,"required":false,"config":{}},
      {"id":"f7","key":"item_name","type":"item_name","label":"Item Name","section":"product","order":2,"required":true,"config":{}},
      {"id":"f8","key":"category","type":"category","label":"Category","section":"product","order":3,"required":false,"config":{}},
      {"id":"f9","key":"brand","type":"brand","label":"Brand","section":"product","order":4,"required":false,"config":{}},
      {"id":"f10","key":"batch_number","type":"batch_number","label":"Batch Number","section":"product","order":5,"required":false,"config":{}},
      {"id":"f11","key":"expected_qty","type":"expected_qty","label":"Expected Qty","section":"product","order":6,"required":true,"config":{"min":0}},
      {"id":"f12","key":"actual_qty","type":"actual_qty","label":"Actual Qty","section":"product","order":7,"required":true,"config":{"min":0}},
      {"id":"f13","key":"qty_variance","type":"qty_variance","label":"Variance","section":"product","order":8,"required":false,"config":{},"calculated":true,"formula":"actual_qty - expected_qty"},
      {"id":"f14","key":"mfg_date","type":"mfg_date","label":"Manufacturing Date","section":"product","order":9,"required":false,"config":{}},
      {"id":"f15","key":"expiry_date","type":"expiry_date","label":"Expiry Date","section":"product","order":10,"required":true,"config":{}},
      {"id":"f16","key":"expiry_days_remaining","type":"expiry_days_remaining","label":"Expiry Days Remaining","section":"product","order":11,"required":false,"config":{},"calculated":true,"formula":"expiry_date - audit_date"},
      {"id":"f17","key":"qc_status","type":"qc_status","label":"QC Status","section":"quality","order":0,"required":true,"config":{"options":["Pass","Fail"]}},
      {"id":"f18","key":"defect_type","type":"defect_type","label":"Defect Type","section":"quality","order":1,"required":false,"config":{},"visibleWhen":{"field":"qc_status","equals":"Fail"}},
      {"id":"f19","key":"severity","type":"severity","label":"Severity","section":"quality","order":2,"required":false,"config":{"options":["Low","Medium","High","Critical"]},"visibleWhen":{"field":"qc_status","equals":"Fail"}},
      {"id":"f20","key":"product_images","type":"multiple_images","label":"Product Images","section":"quality","order":3,"required":true,"config":{"minImages":3,"maxImages":8,"cameraRequired":true,"galleryAllowed":true,"gpsRequired":false,"timestampRequired":true,"aiAnalysisEnabled":true}},
      {"id":"f21","key":"rca","type":"rca","label":"Root Cause Analysis","section":"quality","order":4,"required":false,"config":{}},
      {"id":"f22","key":"remarks","type":"long_text","label":"Remarks","section":"quality","order":5,"required":false,"config":{}},
      {"id":"f23","key":"timestamp","type":"timestamp","label":"Timestamp","section":"quality","order":6,"required":false,"config":{},"system":true}
    ]'::jsonb,
    '[
      {"id":"r1","label":"Actual Qty ≠ Expected Qty → RCA required","when":{"field":"qty_variance","operator":"neq","value":0},"then":[{"action":"require_field","field":"rca"}]},
      {"id":"r2","label":"QC Status = Fail → Defect + Severity + min 2 images","when":{"field":"qc_status","operator":"eq","value":"Fail"},"then":[{"action":"require_field","field":"defect_type"},{"action":"require_field","field":"severity"},{"action":"min_images","field":"product_images","value":2}]},
      {"id":"r3","label":"Expiry < Today → Critical Finding","when":{"field":"expiry_date","operator":"before_today","value":null},"then":[{"action":"create_finding","findingType":"expired_product","severity":"critical"}]},
      {"id":"r4","label":"Expiry ≤ 30 days → Near Expiry Finding","when":{"field":"expiry_date","operator":"within_days","value":30},"then":[{"action":"create_finding","findingType":"near_expiry","severity":"high"}]}
    ]'::jsonb,
    '{"submission":"manager_approval","autoFindingOnVariance":true,"autoFindingOnFailedQc":true,"autoFindingOnExpired":true,"correctiveAction":"auto","slaEnabled":true,"slaHours":24}'::jsonb,
    '{"enabled":true,"maxScore":100,"passingScore":60,"bands":[{"min":90,"label":"Excellent"},{"min":80,"label":"Good"},{"min":60,"label":"Needs Attention"},{"min":0,"label":"Fail"}],"weights":[{"field":"qc_status","weight":30},{"field":"expiry_date","weight":30},{"field":"product_images","weight":20}]}'::jsonb,
    '{"enabled":true,"features":{"productDetection":{"enabled":true,"mode":"optional","confidenceThreshold":0.75},"expiryOcr":{"enabled":true,"mode":"optional","confidenceThreshold":0.7},"batchOcr":{"enabled":true,"mode":"optional","confidenceThreshold":0.7},"defectDetection":{"enabled":true,"mode":"optional","confidenceThreshold":0.65},"imageQualityCheck":{"enabled":true,"mode":"required","confidenceThreshold":0.5},"duplicateEvidenceDetection":{"enabled":true,"mode":"required","confidenceThreshold":0.9}}}'::jsonb,
    '{"photoRequired":true,"minPhotos":3,"maxPhotos":8,"gps":false,"timestamp":true,"barcode":false,"aiVerification":true,"expiryUnitCoverage":true,"beforeAfter":false}'::jsonb,
    '[
      {"key":"qty_variance","formula":"actual_qty - expected_qty","label":"Variance"},
      {"key":"expiry_days_remaining","formula":"expiry_date - audit_date","label":"Expiry Days Remaining"}
    ]'::jsonb,
    v_user
  )
  RETURNING id INTO v_id;

  RETURN v_id;
END;
$$;

GRANT EXECUTE ON FUNCTION public.seed_fnv_qc_template(UUID) TO authenticated;
