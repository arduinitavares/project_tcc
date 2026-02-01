-- =============================================================================
-- Query: spec_authority_status.sql
-- Purpose: Extract spec registry and compiled authority status for each product
--          This supports T3 (Compilação de Autoridade) analysis
-- Inputs: None
-- Assumptions: spec_registry, compiled_spec_authority tables exist
--              (These tables exist in spec_authority_dev.db but not agile_simple.db)
-- Output columns: product_id, spec_version_id, status, created_at, approved_at,
--                 authority_id, compiled_at, compiler_version
-- =============================================================================

SELECT 
    sr.product_id,
    p.name AS product_name,
    sr.spec_version_id,
    sr.status AS spec_status,
    sr.created_at AS spec_created_at,
    sr.approved_at AS spec_approved_at,
    sr.approved_by,
    csa.authority_id,
    csa.compiled_at,
    csa.compiler_version,
    csa.prompt_hash
FROM spec_registry sr
JOIN products p ON sr.product_id = p.product_id
LEFT JOIN compiled_spec_authority csa ON sr.spec_version_id = csa.spec_version_id
ORDER BY sr.product_id, sr.spec_version_id;
