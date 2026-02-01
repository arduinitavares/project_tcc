-- =============================================================================
-- Query: sprint_plan_cycle_time.sql
-- Purpose: Compute sprint planning cycle time from SPRINT_PLAN_SAVED events
--          This corresponds to T5 (Planejamento de Sprint) in evaluation protocol
-- Inputs: None
-- Assumptions: SPRINT_PLAN_SAVED events have duration_seconds populated
-- Output columns: product_id, product_name, sprint_id, planning_duration_sec,
--                 stories_linked, total_points
-- =============================================================================

SELECT 
    we.product_id,
    p.name AS product_name,
    we.sprint_id,
    we.duration_seconds AS planning_duration_sec,
    we.timestamp AS planned_at,
    json_extract(we.event_metadata, '$.stories_linked') AS stories_linked,
    json_extract(we.event_metadata, '$.total_points') AS total_points,
    json_extract(we.event_metadata, '$.stories_skipped') AS stories_skipped
FROM workflow_events we
JOIN products p ON we.product_id = p.product_id
WHERE we.event_type = 'SPRINT_PLAN_SAVED'
ORDER BY we.timestamp;
