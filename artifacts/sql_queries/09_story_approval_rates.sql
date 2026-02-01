-- =============================================================================
-- Query: story_approval_rates.sql
-- Purpose: Compute story approval rates (first pass vs refined) per product
--          Supports "Quality of artifacts" evaluation dimension
-- Inputs: None
-- Assumptions: Stories with validation_evidence.passed=true are approved
--              Stories updated after creation may have been refined
-- Output columns: product_id, product_name, total_stories, with_validation,
--                 passed_first_pass, refined_count, approval_rate_pct
-- =============================================================================

-- Note: This query approximates "first pass" vs "refined" based on:
-- - If validation_evidence.passed = true and created_at ≈ updated_at → first pass
-- - If updated_at significantly after created_at → may have been refined
-- This is an approximation; true refinement tracking would require audit logs

SELECT 
    p.product_id,
    p.name AS product_name,
    COUNT(us.story_id) AS total_stories,
    SUM(CASE WHEN us.validation_evidence IS NOT NULL THEN 1 ELSE 0 END) AS with_validation,
    SUM(CASE 
        WHEN json_extract(us.validation_evidence, '$.passed') = 1 THEN 1 
        ELSE 0 
    END) AS validation_passed,
    -- Approximation: if updated within 1 minute of creation, likely first pass
    SUM(CASE 
        WHEN json_extract(us.validation_evidence, '$.passed') = 1 
             AND (julianday(us.updated_at) - julianday(us.created_at)) * 24 * 60 < 1 
        THEN 1 
        ELSE 0 
    END) AS likely_first_pass_approved,
    ROUND(
        100.0 * SUM(CASE WHEN json_extract(us.validation_evidence, '$.passed') = 1 THEN 1 ELSE 0 END) /
        NULLIF(SUM(CASE WHEN us.validation_evidence IS NOT NULL THEN 1 ELSE 0 END), 0),
        1
    ) AS approval_rate_pct
FROM products p
LEFT JOIN user_stories us ON p.product_id = us.product_id
GROUP BY p.product_id, p.name
ORDER BY p.product_id;
