-- Extended planogram audit package: assortment, MSL, promotions, scoring rules, SOS geometry.

ALTER TABLE public.planogram_versions
  ADD COLUMN IF NOT EXISTS audit_package jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS store_timezone text,
  ADD COLUMN IF NOT EXISTS fixture_id text,
  ADD COLUMN IF NOT EXISTS valid_from timestamptz,
  ADD COLUMN IF NOT EXISTS valid_to timestamptz;

COMMENT ON COLUMN public.planogram_versions.audit_package IS
  'JSON package: assortment_skus, msl_skus, promotions, price_requirements, scoring_rules, sos_geometry, listed_skus';

ALTER TABLE public.planogram_items
  ADD COLUMN IF NOT EXISTS expected_orientation text,
  ADD COLUMN IF NOT EXISTS approved_substitutes jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS authorized_shelf_price numeric(12, 2),
  ADD COLUMN IF NOT EXISTS price_basis text,
  ADD COLUMN IF NOT EXISTS price_valid_from timestamptz,
  ADD COLUMN IF NOT EXISTS price_valid_to timestamptz,
  ADD COLUMN IF NOT EXISTS product_width_cm numeric(8, 2),
  ADD COLUMN IF NOT EXISTS product_height_cm numeric(8, 2),
  ADD COLUMN IF NOT EXISTS slot_width_cm numeric(8, 2),
  ADD COLUMN IF NOT EXISTS is_mandatory_assortment boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS is_msl boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS is_optional boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS public.planogram_promotions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES public.planogram_versions(id) ON DELETE CASCADE,
  org_id uuid NOT NULL,
  promotion_id text NOT NULL,
  participating_skus jsonb NOT NULL DEFAULT '[]'::jsonb,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz NOT NULL,
  required_location text,
  expected_offer_text text,
  expected_promo_price numeric(12, 2),
  required_facings integer,
  visual_checks jsonb NOT NULL DEFAULT '[]'::jsonb,
  reference_signage_url text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (version_id, promotion_id)
);

CREATE INDEX IF NOT EXISTS planogram_promotions_version_idx ON public.planogram_promotions(version_id);

ALTER TABLE public.planogram_promotions ENABLE ROW LEVEL SECURITY;

CREATE POLICY planogram_promotions_org ON public.planogram_promotions
  FOR ALL USING (
    org_id IN (SELECT org_id FROM public.organization_members WHERE user_id = auth.uid())
  );
