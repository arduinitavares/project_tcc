-- =============================================================================
-- Query: products_summary.sql
-- Purpose: Extract summary of all products (projects) in the database
-- Inputs: None
-- Assumptions: products table exists and follows agile_sqlmodel.py schema
-- Output columns: product_id, name, created_at, updated_at, has_vision, has_spec
-- =============================================================================

SELECT 
    product_id,
    name,
    created_at,
    updated_at,
    CASE WHEN vision IS NOT NULL AND vision != '' THEN 1 ELSE 0 END AS has_vision,
    CASE WHEN technical_spec IS NOT NULL AND technical_spec != '' THEN 1 ELSE 0 END AS has_spec,
    spec_file_path,
    spec_loaded_at
FROM products
ORDER BY product_id;
