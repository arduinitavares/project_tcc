-- =============================================================================
-- Query: validation_evidence_details.sql
-- Purpose: Extract validation evidence from user stories for quality metrics
--          Shows stories approved on first pass vs refined
-- Inputs: None
-- Assumptions: user_stories.validation_evidence contains JSON with passed,
--              rules_checked, invariants_checked fields
-- Output columns: story_id, title, product_id, accepted_spec_version_id,
--                 validation_passed, rules_checked_count
-- =============================================================================

SELECT 
    us.story_id,
    us.title,
    us.product_id,
    p.name AS product_name,
    us.accepted_spec_version_id,
    json_extract(us.validation_evidence, '$.passed') AS validation_passed,
    json_extract(us.validation_evidence, '$.validated_at') AS validated_at,
    json_array_length(json_extract(us.validation_evidence, '$.rules_checked')) AS rules_checked_count,
    json_array_length(json_extract(us.validation_evidence, '$.invariants_checked')) AS invariants_checked_count,
    us.created_at,
    us.updated_at
FROM user_stories us
JOIN products p ON us.product_id = p.product_id
WHERE us.validation_evidence IS NOT NULL
ORDER BY us.product_id, us.story_id;
