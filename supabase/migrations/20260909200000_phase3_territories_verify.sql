-- Phase 3: territories hierarchy + manager verification on assignments

CREATE TABLE IF NOT EXISTS public.territories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  parent_id uuid REFERENCES public.territories(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS territories_org_id_idx ON public.territories(org_id);

ALTER TABLE public.stores
  ADD COLUMN IF NOT EXISTS territory_id uuid REFERENCES public.territories(id) ON DELETE SET NULL;

ALTER TABLE public.scan_assignments
  ADD COLUMN IF NOT EXISTS verified_at timestamptz,
  ADD COLUMN IF NOT EXISTS verified_by uuid REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.territories ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS territories_select ON public.territories;
CREATE POLICY territories_select ON public.territories
  FOR SELECT USING (public.is_org_member(org_id, auth.uid()));

DROP POLICY IF EXISTS territories_insert ON public.territories;
CREATE POLICY territories_insert ON public.territories
  FOR INSERT WITH CHECK (
    public.has_org_role(org_id, auth.uid(), ARRAY['owner','admin','manager']::public.app_role[])
  );

DROP POLICY IF EXISTS territories_update ON public.territories;
CREATE POLICY territories_update ON public.territories
  FOR UPDATE USING (
    public.has_org_role(org_id, auth.uid(), ARRAY['owner','admin','manager']::public.app_role[])
  );

DROP POLICY IF EXISTS territories_delete ON public.territories;
CREATE POLICY territories_delete ON public.territories
  FOR DELETE USING (
    public.has_org_role(org_id, auth.uid(), ARRAY['owner','admin']::public.app_role[])
  );
