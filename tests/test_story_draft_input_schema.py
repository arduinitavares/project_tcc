"""Tests for StoryDraftAgent input schema."""

import json

from orchestrator_agent.agent_tools.story_pipeline.story_draft_agent.agent import (
    story_draft_agent,
)
from utils.schemes import StoryDraftInput


def test_story_draft_input_json_round_trip() -> None:
    """StoryDraftInput should validate JSON payloads and round-trip safely."""
    payload = {
        "current_feature": {
            "feature_id": 1,
            "feature_title": "Feature",
            "theme": "Theme",
            "epic": "Epic",
            "time_frame": "Now",
            "theme_justification": "Why",
            "sibling_features": ["A", "B"],
        },
        "product_context": {
            "product_id": 10,
            "product_name": "Product",
            "vision": "Vision",
            "time_frame": "Now",
        },
        "spec_version_id": 99,
        "authority_context": {
            "scope_themes": ["Theme"],
            "invariants": ["INV-1"],
            "gaps": [],
            "assumptions": [],
            "compiler_version": "1.0.0",
            "prompt_hash": "hash",
        },
        "user_persona": "gestor operacional",
        "story_preferences": {"include_story_points": True},
        "refinement_feedback": "",
        "raw_spec_text": "spec text",
    }

    json_payload = json.dumps(payload)
    parsed = StoryDraftInput.model_validate_json(json_payload)
    assert parsed.spec_version_id == 99
    assert parsed.user_persona == "gestor operacional"
    assert parsed.current_feature["feature_title"] == "Feature"
    assert parsed.story_preferences["include_story_points"] is True

    round_trip = StoryDraftInput.model_validate_json(parsed.model_dump_json())
    assert round_trip == parsed


def test_story_draft_agent_has_input_schema() -> None:
    """StoryDraftAgent should declare input_schema for structured input."""
    assert story_draft_agent.input_schema is StoryDraftInput
