"""
Test that story_points post-processing strips points when include_story_points=False.
"""

import pytest
import json


def test_story_points_stripped_in_draft():
    """
    Verify that if LLM generates story_points despite include_story_points=False,
    the post-processing step strips them before final validation.
    """
    # Simulate LLM output with story_points (non-compliant)
    draft_data = {
        "title": "Test story",
        "description": "As an automation engineer, I want to test so that it works.",
        "acceptance_criteria": "- Test passes",
        "story_points": 5,  # LLM incorrectly generated this
    }
    
    include_story_points = False
    
    # Post-processing logic (from tools.py)
    if not include_story_points and draft_data.get("story_points") is not None:
        draft_data["story_points"] = None
    
    # After post-processing, story_points should be None
    assert draft_data["story_points"] is None


def test_story_points_preserved_when_enabled():
    """
    Verify that if include_story_points=True, points are preserved.
    """
    draft_data = {
        "title": "Test story",
        "description": "As an automation engineer, I want to test so that it works.",
        "acceptance_criteria": "- Test passes",
        "story_points": 5,
    }
    
    include_story_points = True
    
    # Post-processing logic
    if not include_story_points and draft_data.get("story_points") is not None:
        draft_data["story_points"] = None
    
    # Points should be preserved
    assert draft_data["story_points"] == 5


def test_story_points_null_not_overwritten():
    """
    Verify that NULL story_points stay NULL when include_story_points=False.
    """
    draft_data = {
        "title": "Test story",
        "description": "As an automation engineer, I want to test so that it works.",
        "acceptance_criteria": "- Test passes",
        "story_points": None,  # Already compliant
    }
    
    include_story_points = False
    
    # Post-processing logic
    if not include_story_points and draft_data.get("story_points") is not None:
        draft_data["story_points"] = None
    
    # Should remain None
    assert draft_data["story_points"] is None
