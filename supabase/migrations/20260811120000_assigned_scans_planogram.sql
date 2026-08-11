-- Assigned Scans + Planogram Compliance (apply on live Lovable Supabase project)
-- Extends existing organization_members.role (enum app_role), shelf_scans, detected_products

-- Optional: extend app_role enum for manager/junior (PG 15+ IF NOT EXISTS)
ALTER TYPE public.app_role ADD VALUE IF NOT EXISTS 'admin';
ALTER TYPE public.app_role ADD VALUE IF NOT EXISTS 'manager';
ALTER TYPE public.app_role ADD VALUE IF NOT EXISTS 'member';

-- ============ Helpers ============

CREATE OR REPLACE FUNCTION public.is_org_member(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organization_members om
    WHERE om.org_id = p_org_id
      AND om.user_id = auth.uid()
      AND om.status = 'active'
  );
$$;

CREATE OR REPLACE FUNCTION public.is_org_manager(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organization_members om
    WHERE om.org_id = p_org_id
      AND om.user_id = auth.uid()
      AND om.status = 'active'
      AND lower(om.role::text) IN ('owner', 'admin', 'manager')
  );
$$;

GRANT EXECUTE ON FUNCTION public.is_org_member(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_org_manager(UUID) TO authenticated;

-- ============ Planogram / Store Master ============

CREATE TABLE IF NOT EXISTS public.planogram_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  store_id UUID NOT NULL REFERENCES public.stores(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT 'Store planogram',
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'active', 'archived')),
  source_type TEXT NOT NULL DEFAULT 'manual'
    CHECK (source_type IN ('csv', 'manual', 'mixed')),
  uploaded_by UUID REFERENCES auth.users(id),
  source_filename TEXT,
  row_count INT NOT NULL DEFAULT 0,
  activated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS planogram_versions_org_store_idx
  ON public.planogram_versions (org_id, store_id, status);

CREATE TABLE IF NOT EXISTS public.planogram_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id UUID NOT NULL REFERENCES public.planogram_versions(id) ON DELETE CASCADE,
  org_id UUID NOT NULL,
  store_id UUID NOT NULL REFERENCES public.stores(id) ON DELETE CASCADE,
  location TEXT,
  aisle TEXT,
  category TEXT NOT NULL,
  sub_category TEXT,
  brand TEXT NOT NULL,
  product_name TEXT NOT NULL,
  sku TEXT,
  expected_qty INT NOT NULL DEFAULT 1 CHECK (expected_qty >= 0),
  shelf_position TEXT,
  match_key TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS planogram_items_version_idx ON public.planogram_items (version_id);
CREATE INDEX IF NOT EXISTS planogram_items_match_key_idx ON public.planogram_items (version_id, match_key);

-- ============ Scan assignments ============

CREATE TABLE IF NOT EXISTS public.scan_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  store_id UUID NOT NULL REFERENCES public.stores(id) ON DELETE CASCADE,
  planogram_version_id UUID REFERENCES public.planogram_versions(id) ON DELETE SET NULL,
  assignee_id UUID NOT NULL REFERENCES auth.users(id),
  assigner_id UUID NOT NULL REFERENCES auth.users(id),
  scope_type TEXT NOT NULL CHECK (scope_type IN ('category', 'sub_category', 'location')),
  scope_values JSONB NOT NULL DEFAULT '{}'::jsonb,
  due_at TIMESTAMPTZ,
  instructions TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'in_progress', 'completed', 'overdue', 'cancelled')),
  scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS scan_assignments_assignee_idx
  ON public.scan_assignments (assignee_id, status);
CREATE INDEX IF NOT EXISTS scan_assignments_org_idx
  ON public.scan_assignments (org_id, status);

ALTER TABLE public.shelf_scans
  ADD COLUMN IF NOT EXISTS assignment_id UUID REFERENCES public.scan_assignments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS shelf_scans_assignment_idx ON public.shelf_scans (assignment_id);

-- ============ Comparison results ============

CREATE TABLE IF NOT EXISTS public.planogram_comparisons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id UUID REFERENCES public.scan_assignments(id) ON DELETE SET NULL,
  scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE CASCADE,
  org_id UUID NOT NULL,
  store_id UUID NOT NULL,
  compliance_percent NUMERIC(5,2),
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.planogram_comparison_lines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  comparison_id UUID NOT NULL REFERENCES public.planogram_comparisons(id) ON DELETE CASCADE,
  planogram_item_id UUID REFERENCES public.planogram_items(id) ON DELETE SET NULL,
  issue_type TEXT NOT NULL
    CHECK (issue_type IN (
      'correct', 'missing', 'qty_mismatch', 'wrong_product',
      'wrong_category', 'wrong_location', 'unexpected'
    )),
  expected_brand TEXT,
  expected_product TEXT,
  expected_qty INT,
  actual_brand TEXT,
  actual_product TEXT,
  actual_qty INT,
  severity TEXT NOT NULL DEFAULT 'info'
    CHECK (severity IN ('info', 'warning', 'critical')),
  detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS planogram_comparison_lines_cmp_idx
  ON public.planogram_comparison_lines (comparison_id);

-- ============ Corrective actions ============

CREATE TABLE IF NOT EXISTS public.corrective_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  comparison_id UUID NOT NULL REFERENCES public.planogram_comparisons(id) ON DELETE CASCADE,
  comparison_line_id UUID REFERENCES public.planogram_comparison_lines(id) ON DELETE SET NULL,
  org_id UUID NOT NULL,
  issue_type TEXT NOT NULL,
  suggestion TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'in_progress', 'resolved')),
  assigned_to UUID REFERENCES auth.users(id),
  resolved_by UUID REFERENCES auth.users(id),
  resolved_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ Notifications ============

CREATE TABLE IF NOT EXISTS public.notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  org_id UUID NOT NULL,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS notifications_user_idx
  ON public.notifications (user_id, read_at NULLS FIRST, created_at DESC);

-- ============ RLS ============

ALTER TABLE public.planogram_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.planogram_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scan_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.planogram_comparisons ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.planogram_comparison_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.corrective_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

-- planogram_versions
DROP POLICY IF EXISTS planogram_versions_select ON public.planogram_versions;
CREATE POLICY planogram_versions_select ON public.planogram_versions
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS planogram_versions_manage ON public.planogram_versions;
CREATE POLICY planogram_versions_manage ON public.planogram_versions
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

-- planogram_items
DROP POLICY IF EXISTS planogram_items_select ON public.planogram_items;
CREATE POLICY planogram_items_select ON public.planogram_items
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS planogram_items_manage ON public.planogram_items;
CREATE POLICY planogram_items_manage ON public.planogram_items
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

-- scan_assignments
DROP POLICY IF EXISTS scan_assignments_manager ON public.scan_assignments;
CREATE POLICY scan_assignments_manager ON public.scan_assignments
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

DROP POLICY IF EXISTS scan_assignments_assignee ON public.scan_assignments;
CREATE POLICY scan_assignments_assignee ON public.scan_assignments
  FOR SELECT TO authenticated
  USING (assignee_id = auth.uid());

DROP POLICY IF EXISTS scan_assignments_assignee_update ON public.scan_assignments;
CREATE POLICY scan_assignments_assignee_update ON public.scan_assignments
  FOR UPDATE TO authenticated
  USING (assignee_id = auth.uid())
  WITH CHECK (assignee_id = auth.uid());

-- planogram_comparisons
DROP POLICY IF EXISTS planogram_comparisons_select ON public.planogram_comparisons;
CREATE POLICY planogram_comparisons_select ON public.planogram_comparisons
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS planogram_comparisons_insert ON public.planogram_comparisons;
CREATE POLICY planogram_comparisons_insert ON public.planogram_comparisons
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_member(org_id));

-- planogram_comparison_lines (via comparison org membership)
DROP POLICY IF EXISTS planogram_comparison_lines_select ON public.planogram_comparison_lines;
CREATE POLICY planogram_comparison_lines_select ON public.planogram_comparison_lines
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.planogram_comparisons c
    WHERE c.id = comparison_id AND public.is_org_member(c.org_id)
  ));

DROP POLICY IF EXISTS planogram_comparison_lines_insert ON public.planogram_comparison_lines;
CREATE POLICY planogram_comparison_lines_insert ON public.planogram_comparison_lines
  FOR INSERT TO authenticated
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.planogram_comparisons c
    WHERE c.id = comparison_id AND public.is_org_member(c.org_id)
  ));

-- corrective_actions
DROP POLICY IF EXISTS corrective_actions_select ON public.corrective_actions;
CREATE POLICY corrective_actions_select ON public.corrective_actions
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS corrective_actions_update ON public.corrective_actions;
CREATE POLICY corrective_actions_update ON public.corrective_actions
  FOR UPDATE TO authenticated
  USING (public.is_org_member(org_id))
  WITH CHECK (public.is_org_member(org_id));

DROP POLICY IF EXISTS corrective_actions_insert ON public.corrective_actions;
CREATE POLICY corrective_actions_insert ON public.corrective_actions
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_member(org_id));

-- notifications
DROP POLICY IF EXISTS notifications_own ON public.notifications;
CREATE POLICY notifications_own ON public.notifications
  FOR ALL TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- Service role full access for Edge Functions / backend
DROP POLICY IF EXISTS planogram_versions_service ON public.planogram_versions;
CREATE POLICY planogram_versions_service ON public.planogram_versions
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS scan_assignments_service ON public.scan_assignments;
CREATE POLICY scan_assignments_service ON public.scan_assignments
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS notifications_service ON public.notifications;
CREATE POLICY notifications_service ON public.notifications
  FOR ALL TO service_role USING (true) WITH CHECK (true);
