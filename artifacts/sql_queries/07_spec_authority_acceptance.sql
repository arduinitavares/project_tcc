-- =============================================================================
-- Query: spec_authority_acceptance.sql
-- Purpose: Extract spec authority acceptance/rejection decisions
--          Supports validation gate pass/fail analysis
-- Inputs: None
-- Assumptions: spec_authority_acceptance table exists 
--              (spec_authority_dev.db only)
-- Output columns: id, product_id, spec_version_id, status, policy, decided_by,
--                 decided_at, compiler_version
-- =============================================================================

SELECT 
    saa.id,
    saa.product_id,
    p.name AS product_name,
    saa.spec_version_id,
    saa.status,
    saa.policy,
    saa.decided_by,
    saa.decided_at,
    saa.compiler_version,
    saa.rationale
FROM spec_authority_acceptance saa
JOIN products p ON saa.product_id = p.product_id
ORDER BY saa.decided_at;
