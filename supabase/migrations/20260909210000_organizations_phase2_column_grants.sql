-- Fix: Phase 2 added customer_type + brand_config but column-level SELECT on
-- organizations (20260812032422) did not include them → "permission denied".

GRANT SELECT (customer_type, brand_config) ON public.organizations TO authenticated;

-- Allow admins to save brand/competitor config (UPDATE policy already exists).
GRANT UPDATE (customer_type, brand_config) ON public.organizations TO authenticated;
