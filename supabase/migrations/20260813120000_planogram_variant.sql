-- Planogram: add variant column; tighten required fields for new rows
-- Apply on Lovable Supabase after backend deploy

ALTER TABLE public.planogram_items
  ADD COLUMN IF NOT EXISTS variant TEXT;

COMMENT ON COLUMN public.planogram_items.variant IS
  'Optional pack size / flavor (e.g. 200ml, 25 bags). Used in match_key when present.';

-- Backfill legacy rows before NOT NULL (safe no-op if already set)
UPDATE public.planogram_items
SET location = COALESCE(NULLIF(trim(location), ''), NULLIF(trim(aisle), ''), 'Unspecified')
WHERE location IS NULL OR trim(location) = '';

UPDATE public.planogram_items
SET sub_category = COALESCE(NULLIF(trim(sub_category), ''), NULLIF(trim(category), ''), 'General')
WHERE sub_category IS NULL OR trim(sub_category) = '';

-- Enforce mandatory fields for inserts/updates going forward
ALTER TABLE public.planogram_items
  ALTER COLUMN location SET NOT NULL,
  ALTER COLUMN sub_category SET NOT NULL;
