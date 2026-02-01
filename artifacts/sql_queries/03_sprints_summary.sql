-- =============================================================================
-- Query: sprints_summary.sql
-- Purpose: Extract sprint planning data including stories linked and capacity
-- Inputs: None
-- Assumptions: sprints, sprint_stories, user_stories tables exist
-- Output columns: sprint_id, product_id, goal, status, start_date, end_date,
--                 stories_linked, total_story_points
-- =============================================================================

SELECT 
    s.sprint_id,
    s.product_id,
    p.name AS product_name,
    s.goal,
    s.status,
    s.start_date,
    s.end_date,
    s.created_at,
    COUNT(ss.story_id) AS stories_linked,
    COALESCE(SUM(us.story_points), 0) AS total_story_points
FROM sprints s
JOIN products p ON s.product_id = p.product_id
LEFT JOIN sprint_stories ss ON s.sprint_id = ss.sprint_id
LEFT JOIN user_stories us ON ss.story_id = us.story_id
GROUP BY s.sprint_id, s.product_id, p.name, s.goal, s.status, s.start_date, s.end_date, s.created_at
ORDER BY s.product_id, s.sprint_id;
