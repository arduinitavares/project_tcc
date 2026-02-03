from __future__ import annotations

import json
from typing import Any, Dict

from utils.schemes import StoryRefinerInput


def test_story_refiner_input_schema_round_trip() -> None:
    payload: Dict[str, Any] = {
        "story_draft": {
            "title": "Capture user_id",
            "description": "As a automation engineer, I want ... so that ...",
            "acceptance_criteria": "- Example",
            "story_points": 3,
            "metadata": {"spec_version_id": 1},
        },
        "spec_validation_result": {
            "is_compliant": False,
            "suggestions": ["Add AC for user_id"],
            "domain_compliance": {"critical_gaps": []},
        },
        "authority_context": {
            "scope_themes": ["payload validation"],
            "invariants": ["REQUIRED_FIELD:user_id"],
        },
        "spec_version_id": 1,
        "current_feature": {
            "feature_id": 1,
            "feature_title": "Capture user_id",
            "theme": "Core",
            "epic": "User Data",
            "time_frame": None,
            "theme_justification": None,
            "sibling_features": [],
        },
        "story_preferences": {"include_story_points": True},
        "raw_spec_text": None,
        "extra_state_key": "allowed",
    }

    model = StoryRefinerInput.model_validate(payload)
    dumped = model.model_dump_json()
    loaded = StoryRefinerInput.model_validate_json(dumped)

    assert loaded.spec_version_id == 1
    assert loaded.current_feature["feature_title"] == "Capture user_id"
    assert loaded.story_preferences["include_story_points"] is True

    # Extra keys should be preserved in model dump
    dumped_obj = json.loads(dumped)
    assert dumped_obj.get("extra_state_key") == "allowed"
