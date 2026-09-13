-- Commercial catalogue v3 — new-customer prices and allowances.
-- Does not migrate existing workspaces onto new contracted entitlements.

ALTER TABLE public.subscription_plans
  ADD COLUMN IF NOT EXISTS daily_scan_limit INTEGER,
  ADD COLUMN IF NOT EXISTS catalogue_version TEXT;

COMMENT ON COLUMN public.subscription_plans.daily_scan_limit IS 'Commercial daily scan cap. NULL = no daily commercial quota.';
COMMENT ON COLUMN public.subscription_plans.catalogue_version IS 'Published pricing catalogue version for new purchases.';

UPDATE public.subscription_plans SET
  tagline = 'Try Aislix on your own shelves. No credit card required.',
  scan_quota = 30,
  daily_scan_limit = 5,
  store_limit = 1,
  seat_limit = 1,
  master_setup_limit = 1,
  price_monthly_inr = 0,
  price_annual_inr = 0,
  price_per_audit_inr = NULL,
  quota_period = 'month',
  history_days = 30,
  sort_order = 1,
  catalogue_version = '2026.09.13-v3',
  updated_at = now()
WHERE code = 'free';

UPDATE public.subscription_plans SET
  tagline = 'No subscription. Pay only for the shelf scans you need.',
  scan_quota = NULL,
  daily_scan_limit = NULL,
  store_limit = NULL,
  seat_limit = NULL,
  master_setup_limit = NULL,
  price_monthly_inr = 0,
  price_annual_inr = 0,
  price_per_audit_inr = 9,
  quota_period = 'pay_per_use',
  history_days = 90,
  sort_order = 2,
  catalogue_version = '2026.09.13-v3',
  updated_at = now()
WHERE code = 'payg';

UPDATE public.subscription_plans SET
  tagline = 'For local stores and small retail teams building a regular audit habit.',
  scan_quota = 150,
  daily_scan_limit = NULL,
  store_limit = NULL,
  seat_limit = NULL,
  master_setup_limit = NULL,
  price_monthly_inr = 499,
  price_annual_inr = 5389,
  price_per_audit_inr = NULL,
  quota_period = 'month',
  history_days = 365,
  sort_order = 3,
  catalogue_version = '2026.09.13-v3',
  updated_at = now()
WHERE code = 'starter';

UPDATE public.subscription_plans SET
  tagline = 'For growing retail chains, distributors, and field teams.',
  scan_quota = 500,
  daily_scan_limit = NULL,
  store_limit = NULL,
  seat_limit = NULL,
  master_setup_limit = NULL,
  price_monthly_inr = 1499,
  price_annual_inr = 16189,
  price_per_audit_inr = NULL,
  quota_period = 'month',
  history_days = 730,
  sort_order = 4,
  catalogue_version = '2026.09.13-v3',
  updated_at = now()
WHERE code = 'growth';

UPDATE public.subscription_plans SET
  tagline = 'For supermarkets, dark stores, FMCG brands, and larger retail operations.',
  scan_quota = 2000,
  daily_scan_limit = NULL,
  store_limit = NULL,
  seat_limit = NULL,
  master_setup_limit = NULL,
  price_monthly_inr = 4999,
  price_annual_inr = 53989,
  price_per_audit_inr = NULL,
  quota_period = 'month',
  history_days = 1095,
  sort_order = 5,
  catalogue_version = '2026.09.13-v3',
  updated_at = now()
WHERE code = 'professional';

UPDATE public.subscription_plans SET
  tagline = 'Starting package for large-scale deployments. Custom work is quoted separately.',
  scan_quota = 8000,
  daily_scan_limit = NULL,
  store_limit = NULL,
  seat_limit = NULL,
  master_setup_limit = NULL,
  price_monthly_inr = 19999,
  is_contact_sales = true,
  quota_period = 'month',
  history_days = 1095,
  sort_order = 6,
  catalogue_version = '2026.09.13-v3',
  updated_at = now()
WHERE code = 'enterprise';
