-- =============================================================================
-- Query: workflow_events_timing.sql
-- Purpose: Extract workflow event timing for cycle time analysis (T5)
-- Inputs: None
-- Assumptions: workflow_events table exists with event_type enum values
-- Output columns: event_id, event_type, timestamp, duration_seconds, 
--                 product_id, sprint_id, metadata (JSON)
-- =============================================================================

SELECT 
    event_id,
    event_type,
    timestamp,
    duration_seconds,
    turn_count,
    product_id,
    sprint_id,
    session_id,
    event_metadata
FROM workflow_events
ORDER BY timestamp;

-- Aggregated version for summary
-- SELECT 
--     event_type,
--     COUNT(*) AS event_count,
--     AVG(duration_seconds) AS avg_duration_sec,
--     SUM(duration_seconds) AS total_duration_sec,
--     MIN(timestamp) AS first_event,
--     MAX(timestamp) AS last_event
-- FROM workflow_events
-- GROUP BY event_type
-- ORDER BY event_type;
