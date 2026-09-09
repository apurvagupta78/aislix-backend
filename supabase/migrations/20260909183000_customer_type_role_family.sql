-- Phase 2: customer segmentation + role families + brand/competitor config

ALTER TABLE public.organizations
  ADD COLUMN IF NOT EXISTS customer_type text,
  ADD COLUMN IF NOT EXISTS brand_config jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS role_family text;

COMMENT ON COLUMN public.organizations.customer_type IS
  'fmcg | supermarket | darkstore | warehouse | distributor | local | audit_agency';
COMMENT ON COLUMN public.organizations.brand_config IS
  'JSON: { primary_brand, competitor_brands[] } for share-of-shelf intel';
COMMENT ON COLUMN public.profiles.role_family IS
  'field | store_ops | merchandising | operations | commercial | executive';

UPDATE public.organizations
SET customer_type = industry
WHERE customer_type IS NULL AND industry IS NOT NULL AND industry <> '';
