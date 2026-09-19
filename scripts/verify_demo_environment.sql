-- Phase 0 validation — run after seed_aislix_demo_environment

SELECT 'demo_org' AS check_name,
  EXISTS (SELECT 1 FROM organizations WHERE id = public.aislix_demo_org_id() AND is_demo = true) AS ok;

SELECT 'stores_by_model' AS check_name, store_type, count(*) AS n
FROM stores WHERE org_id = public.aislix_demo_org_id()
GROUP BY store_type ORDER BY 1;

SELECT 'templates' AS check_name, operating_model, count(*) AS n
FROM audit_templates
WHERE org_id = public.aislix_demo_org_id() AND is_system_template = true
GROUP BY operating_model ORDER BY 1;

SELECT 'audits_per_template' AS check_name, t.name, count(a.id) AS audits
FROM audit_templates t
LEFT JOIN scan_assignments a ON a.template_id = t.id AND a.org_id = t.org_id
WHERE t.org_id = public.aislix_demo_org_id() AND t.is_system_template = true
GROUP BY t.name
HAVING count(a.id) < 4
ORDER BY audits;

SELECT 'total_completed_audits' AS check_name, count(*) AS n
FROM scan_assignments
WHERE org_id = public.aislix_demo_org_id() AND status = 'completed';

SELECT 'findings' AS check_name, severity, count(*) AS n
FROM findings WHERE org_id = public.aislix_demo_org_id()
GROUP BY severity ORDER BY 1;

SELECT 'maggi_lines_sec54' AS check_name, count(*) AS adjustment_events
FROM digital_audit_lines l
JOIN shelf_scans s ON s.id = l.scan_id
JOIN stores st ON st.id = l.store_id
WHERE l.org_id = public.aislix_demo_org_id()
  AND l.sku = 'MAGGI-70G'
  AND st.name ILIKE '%Sec 54%'
  AND l.variance_qty IS NOT NULL AND l.variance_qty <> 0;

SELECT 'variance_consistency' AS check_name, count(*) AS mismatches
FROM digital_audit_lines
WHERE org_id = public.aislix_demo_org_id()
  AND actual_qty IS NOT NULL
  AND variance_qty IS DISTINCT FROM (actual_qty - expected_qty);
