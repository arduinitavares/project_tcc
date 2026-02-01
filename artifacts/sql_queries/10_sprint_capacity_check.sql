-- =============================================================================
-- Query: sprint_capacity_check.sql
-- Purpose: Verify sprint capacity allocation (allocated vs declared)
--          Extracts from SPRINT_PLAN_DRAFT and SPRINT_PLAN_SAVED metadata
-- Inputs: None
-- Assumptions: event_metadata contains story_count, total_points, capacity_points
-- Output columns: product_id, sprint_id, event_type, story_count, total_points,
--                 capacity_points, within_capacity
-- =============================================================================

SELECT 
    we.product_id,
    p.name AS product_name,
    we.sprint_id,
    we.event_type,
    we.timestamp,
    json_extract(we.event_metadata, '$.story_count') AS story_count,
    json_extract(we.event_metadata, '$.total_points') AS total_points,
    json_extract(we.event_metadata, '$.capacity_points') AS capacity_points,
    json_extract(we.event_metadata, '$.stories_linked') AS stories_linked,
    json_extract(we.event_metadata, '$.stories_skipped') AS stories_skipped,
    CASE 
        WHEN json_extract(we.event_metadata, '$.capacity_points') IS NOT NULL 
             AND json_extract(we.event_metadata, '$.total_points') <= json_extract(we.event_metadata, '$.capacity_points')
        THEN 'YES'
        WHEN json_extract(we.event_metadata, '$.capacity_points') IS NULL
        THEN 'N/A (no capacity set)'
        ELSE 'NO (over capacity)'
    END AS within_capacity
FROM workflow_events we
JOIN products p ON we.product_id = p.product_id
WHERE we.event_type IN ('SPRINT_PLAN_DRAFT', 'SPRINT_PLAN_SAVED')
ORDER BY we.timestamp;
