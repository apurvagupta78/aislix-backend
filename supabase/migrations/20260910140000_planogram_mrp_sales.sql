-- Planogram MRP and daily sales for financial impact calculations.

ALTER TABLE planogram_items
  ADD COLUMN IF NOT EXISTS mrp_inr numeric(12, 2),
  ADD COLUMN IF NOT EXISTS avg_daily_sales numeric(10, 2);

COMMENT ON COLUMN planogram_items.mrp_inr IS 'Maximum retail price (INR) for lost-sales estimates';
COMMENT ON COLUMN planogram_items.avg_daily_sales IS 'Average daily unit sales for velocity-based financial impact';
