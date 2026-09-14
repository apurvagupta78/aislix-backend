-- Digital Audit v1: expected vs actual variance, evidence, approval workflow
-- Apply on live Supabase (Lovable). AI audit flow unchanged.

-- ============ Store geofence ============

ALTER TABLE public.stores
  ADD COLUMN IF NOT EXISTS geofence_radius_m INT NOT NULL DEFAULT 200;

COMMENT ON COLUMN public.stores.geofence_radius_m IS
  'Default 200m — auditor GPS compared to store latitude/longitude on digital audit submit.';

-- ============ Planogram item extensions ============

ALTER TABLE public.planogram_items
  ADD COLUMN IF NOT EXISTS system_qty INT,
  ADD COLUMN IF NOT EXISTS item_code TEXT,
  ADD COLUMN IF NOT EXISTS barcode TEXT;

-- ============ Assignment + scan mode ============

ALTER TABLE public.scan_assignments
  ADD COLUMN IF NOT EXISTS audit_mode TEXT NOT NULL DEFAULT 'ai'
    CHECK (audit_mode IN ('ai', 'digital'));

ALTER TABLE public.scan_assignments
  ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (approval_status IN (
      'pending', 'incomplete', 'submitted', 'pending_review',
      'approved', 'rejected', 'flagged'
    ));

CREATE INDEX IF NOT EXISTS scan_assignments_audit_mode_idx
  ON public.scan_assignments (org_id, audit_mode, approval_status);

ALTER TABLE public.shelf_scans
  ADD COLUMN IF NOT EXISTS audit_mode TEXT NOT NULL DEFAULT 'ai'
    CHECK (audit_mode IN ('ai', 'digital', 'ai_assisted'));

ALTER TABLE public.shelf_scans
  ADD COLUMN IF NOT EXISTS submission_status TEXT
    CHECK (submission_status IS NULL OR submission_status IN (
      'incomplete', 'submitted', 'pending_review', 'approved', 'rejected', 'flagged'
    ));

ALTER TABLE public.shelf_scans
  ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS submitted_lat DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS submitted_lng DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS geofence_status TEXT
    CHECK (geofence_status IS NULL OR geofence_status IN ('ok', 'warning', 'outside', 'unavailable')),
  ADD COLUMN IF NOT EXISTS device_info JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS finalized_by UUID REFERENCES auth.users(id),
  ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS shelf_scans_digital_idx
  ON public.shelf_scans (org_id, audit_mode, submission_status);

-- ============ Digital audit lines (expected + actual snapshot) ============

CREATE TABLE IF NOT EXISTS public.digital_audit_lines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id UUID NOT NULL REFERENCES public.shelf_scans(id) ON DELETE CASCADE,
  assignment_id UUID REFERENCES public.scan_assignments(id) ON DELETE SET NULL,
  org_id UUID NOT NULL,
  store_id UUID NOT NULL REFERENCES public.stores(id) ON DELETE CASCADE,
  planogram_item_id UUID REFERENCES public.planogram_items(id) ON DELETE SET NULL,
  match_key TEXT,
  sku TEXT,
  item_code TEXT,
  barcode TEXT,
  brand TEXT,
  product_name TEXT NOT NULL,
  category TEXT,
  sub_category TEXT,
  location TEXT NOT NULL DEFAULT '',
  bin_key TEXT NOT NULL DEFAULT '',
  expected_qty INT NOT NULL DEFAULT 0 CHECK (expected_qty >= 0),
  system_qty INT,
  actual_qty INT,
  mrp_inr NUMERIC(12, 2),
  variance_qty INT,
  variance_pct NUMERIC(8, 2),
  variance_value_inr NUMERIC(14, 2),
  rca_code TEXT
    CHECK (rca_code IS NULL OR rca_code IN (
      'stock_sold', 'damaged', 'expired', 'missing', 'misplaced',
      'receiving_pending', 'counting_error', 'system_inventory_incorrect', 'other'
    )),
  rca_notes TEXT,
  entered_by UUID REFERENCES auth.users(id),
  source TEXT NOT NULL DEFAULT 'form'
    CHECK (source IN ('form', 'csv', 'manager_edit')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS digital_audit_lines_scan_idx
  ON public.digital_audit_lines (scan_id);
CREATE INDEX IF NOT EXISTS digital_audit_lines_bin_idx
  ON public.digital_audit_lines (scan_id, bin_key);

-- ============ Bin / shelf evidence photos ============

CREATE TABLE IF NOT EXISTS public.audit_evidence (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id UUID NOT NULL REFERENCES public.shelf_scans(id) ON DELETE CASCADE,
  org_id UUID NOT NULL,
  bin_key TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  lat DOUBLE PRECISION,
  lng DOUBLE PRECISION,
  accuracy_m DOUBLE PRECISION,
  captured_by UUID NOT NULL REFERENCES auth.users(id),
  device_info JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS audit_evidence_scan_bin_idx
  ON public.audit_evidence (scan_id, bin_key);

-- ============ Manager approval log ============

CREATE TABLE IF NOT EXISTS public.audit_approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_id UUID NOT NULL REFERENCES public.shelf_scans(id) ON DELETE CASCADE,
  assignment_id UUID REFERENCES public.scan_assignments(id) ON DELETE SET NULL,
  org_id UUID NOT NULL,
  reviewer_id UUID NOT NULL REFERENCES auth.users(id),
  action TEXT NOT NULL
    CHECK (action IN ('approved', 'rejected', 'flagged', 'reopened')),
  reject_mode TEXT
    CHECK (reject_mode IS NULL OR reject_mode IN ('reopen_same', 'new_assignment')),
  comment TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_approvals_scan_idx ON public.audit_approvals (scan_id);

-- ============ RLS ============

ALTER TABLE public.digital_audit_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_approvals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS digital_audit_lines_select ON public.digital_audit_lines;
CREATE POLICY digital_audit_lines_select ON public.digital_audit_lines
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS digital_audit_lines_insert ON public.digital_audit_lines;
CREATE POLICY digital_audit_lines_insert ON public.digital_audit_lines
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_member(org_id));

DROP POLICY IF EXISTS digital_audit_lines_update ON public.digital_audit_lines;
CREATE POLICY digital_audit_lines_update ON public.digital_audit_lines
  FOR UPDATE TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_evidence_select ON public.audit_evidence;
CREATE POLICY audit_evidence_select ON public.audit_evidence
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_evidence_insert ON public.audit_evidence;
CREATE POLICY audit_evidence_insert ON public.audit_evidence
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_evidence_update ON public.audit_evidence;
CREATE POLICY audit_evidence_update ON public.audit_evidence
  FOR UPDATE TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_approvals_select ON public.audit_approvals;
CREATE POLICY audit_approvals_select ON public.audit_approvals
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_approvals_insert ON public.audit_approvals;
CREATE POLICY audit_approvals_insert ON public.audit_approvals
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_manager(org_id));
