-- Verify custom audit review materialization for ASN-A3C06707 / scan d468a36b...

SELECT id, sku, expected_qty, actual_qty, variance_qty, variance_value_inr, rca_code, product_name
FROM public.digital_audit_lines
WHERE scan_id = 'd468a36b-5cf1-44b7-8b11-12b7ad0d7dab'
ORDER BY created_at;

SELECT id, bin_key, storage_path
FROM public.audit_evidence
WHERE scan_id = 'd468a36b-5cf1-44b7-8b11-12b7ad0d7dab';

SELECT id, finding_type, severity, status, expected_value, actual_value, variance_units, rca_code
FROM public.findings
WHERE assignment_id = 'a3c06707-a0a8-427c-9ebc-39a165c0bf6b'
ORDER BY created_at DESC;

SELECT section_key, record_index, field_key, value
FROM public.audit_responses
WHERE scan_id = 'd468a36b-5cf1-44b7-8b11-12b7ad0d7dab'
ORDER BY section_key, record_index, field_key;
