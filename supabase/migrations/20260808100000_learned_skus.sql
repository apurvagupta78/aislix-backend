-- Learned SKU catalog: GPT-identified products persisted for FAISS reuse.
-- Apply in Lovable → Cloud → SQL editor, or Supabase dashboard SQL.

CREATE TABLE IF NOT EXISTS public.learned_skus (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sku TEXT UNIQUE NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_learned_skus_sku ON public.learned_skus (sku);

ALTER TABLE public.learned_skus ENABLE ROW LEVEL SECURITY;

-- Backend service role writes/reads; no client access required initially.
DROP POLICY IF EXISTS learned_skus_service_all ON public.learned_skus;
CREATE POLICY learned_skus_service_all ON public.learned_skus
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Storage bucket for learned FAISS files (backup alongside table rows).
INSERT INTO storage.buckets (id, name, public)
VALUES ('catalog-data', 'catalog-data', false)
ON CONFLICT (id) DO NOTHING;
