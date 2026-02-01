-- =============================================================================
-- Query: stories_per_product.sql
-- Purpose: Count user stories per product with spec authority pinning metrics
-- Inputs: None
-- Assumptions: user_stories table exists; accepted_spec_version_id may not exist
--              in all databases (older schema)
-- Output columns: product_id, product_name, total_stories, with_spec_version,
--                 with_validation_evidence, pinning_coverage_pct
-- =============================================================================

SELECT 
    p.product_id,
    p.name AS product_name,
    COUNT(us.story_id) AS total_stories,
    SUM(CASE WHEN us.accepted_spec_version_id IS NOT NULL THEN 1 ELSE 0 END) AS with_spec_version,
    SUM(CASE WHEN us.validation_evidence IS NOT NULL THEN 1 ELSE 0 END) AS with_validation_evidence,
    ROUND(
        100.0 * SUM(CASE WHEN us.accepted_spec_version_id IS NOT NULL THEN 1 ELSE 0 END) / 
        NULLIF(COUNT(us.story_id), 0),
        1
    ) AS pinning_coverage_pct
FROM products p
LEFT JOIN user_stories us ON p.product_id = us.product_id
GROUP BY p.product_id, p.name
ORDER BY p.product_id;
