-- Global learned SKU catalog shared across all organizations and stores.
-- Lovable dual-writes: learned_skus (org audit) + global_learned_skus (inference).

CREATE TABLE IF NOT EXISTS public.global_learned_skus (
  sku TEXT PRIMARY KEY,
  brand TEXT NOT NULL DEFAULT '',
  product_name TEXT NOT NULL DEFAULT '',
  variant TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'General',
  embedding JSONB NOT NULL,
  source_scan_id TEXT,
  hit_count INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_global_learned_skus_brand ON public.global_learned_skus (brand);

ALTER TABLE public.global_learned_skus ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS global_learned_skus_auth_read ON public.global_learned_skus;
CREATE POLICY global_learned_skus_auth_read ON public.global_learned_skus
  FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS global_learned_skus_auth_insert ON public.global_learned_skus;
CREATE POLICY global_learned_skus_auth_insert ON public.global_learned_skus
  FOR INSERT TO authenticated WITH CHECK (true);

DROP POLICY IF EXISTS global_learned_skus_auth_update ON public.global_learned_skus;
CREATE POLICY global_learned_skus_auth_update ON public.global_learned_skus
  FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

-- One-time backfill from org-scoped learned_skus (if org_id column exists).
INSERT INTO public.global_learned_skus (
  sku, brand, product_name, variant, category, embedding, source_scan_id, hit_count, created_at, updated_at
)
SELECT DISTINCT ON (sku)
  sku, brand, product_name, variant, category, embedding, source_scan_id, hit_count, created_at, updated_at
FROM public.learned_skus
ORDER BY sku, updated_at DESC
ON CONFLICT (sku) DO UPDATE SET
  brand = EXCLUDED.brand,
  product_name = EXCLUDED.product_name,
  variant = EXCLUDED.variant,
  category = EXCLUDED.category,
  embedding = EXCLUDED.embedding,
  source_scan_id = EXCLUDED.source_scan_id,
  hit_count = GREATEST(global_learned_skus.hit_count, EXCLUDED.hit_count),
  updated_at = EXCLUDED.updated_at;
