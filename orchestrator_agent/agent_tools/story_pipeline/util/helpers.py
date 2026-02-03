import json
from typing import Any, Dict, Optional, cast

from orchestrator_agent.agent_tools.story_pipeline.util.models import ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline.util.constants import (
    KEY_STORY_DRAFT, KEY_SPEC_VALIDATION_RESULT, KEY_CURRENT_FEATURE,
    KEY_PRODUCT_CONTEXT, KEY_SPEC_VERSION_ID, KEY_AUTHORITY_CONTEXT,
    KEY_USER_PERSONA, KEY_STORY_PREFERENCES, KEY_REFINEMENT_FEEDBACK,
    KEY_RAW_SPEC_TEXT
)


def maybe_parse_json(value: Any) -> Any:
    """Best-effort parse JSON strings for readability."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def build_story_draft_input_payload(
    state: Dict[str, Any], story_input: ProcessStoryInput
) -> Dict[str, Any]:
    """Builds the input payload for the story draft agent."""
    current_feature: Dict[str, Any] = cast(
        Dict[str, Any], maybe_parse_json(state.get(KEY_CURRENT_FEATURE))
    ) or {
        "feature_id": story_input.feature_id,
        "feature_title": story_input.feature_title,
        "theme": story_input.theme,
        "epic": story_input.epic,
        "time_frame": story_input.time_frame,
        "theme_justification": story_input.theme_justification,
        "sibling_features": story_input.sibling_features or [],
    }
    product_context: Dict[str, Any] = cast(
        Dict[str, Any], maybe_parse_json(state.get(KEY_PRODUCT_CONTEXT))
    ) or {
        "product_id": story_input.product_id,
        "product_name": story_input.product_name,
        "vision": story_input.product_vision or "",
        "time_frame": story_input.time_frame,
    }
    authority_context: Dict[str, Any] = cast(
        Dict[str, Any], maybe_parse_json(state.get(KEY_AUTHORITY_CONTEXT))
    ) or {}
    story_preferences: Dict[str, Any] = cast(
        Dict[str, Any], maybe_parse_json(state.get(KEY_STORY_PREFERENCES))
    ) or {
        "include_story_points": story_input.include_story_points,
    }
    return {
        "current_feature": current_feature,
        "product_context": product_context,
        "spec_version_id": state.get(KEY_SPEC_VERSION_ID) or story_input.spec_version_id,
        "authority_context": authority_context,
        "user_persona": state.get(KEY_USER_PERSONA) or story_input.user_persona,
        "story_preferences": story_preferences,
        "refinement_feedback": state.get(KEY_REFINEMENT_FEEDBACK, ""),
        "raw_spec_text": state.get(KEY_RAW_SPEC_TEXT),
    }


def extract_agent_inputs(author: str, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract per-agent input payloads from pipeline state."""
    if author == "StoryDraftAgent":
        return {
            "current_feature": maybe_parse_json(state.get(KEY_CURRENT_FEATURE)),
            "product_context": maybe_parse_json(state.get(KEY_PRODUCT_CONTEXT)),
            "spec_version_id": state.get(KEY_SPEC_VERSION_ID),
            "authority_context": maybe_parse_json(state.get(KEY_AUTHORITY_CONTEXT)),
            "user_persona": state.get(KEY_USER_PERSONA),
            "story_preferences": maybe_parse_json(state.get(KEY_STORY_PREFERENCES)),
            "refinement_feedback": state.get(KEY_REFINEMENT_FEEDBACK),
            "raw_spec_text": state.get(KEY_RAW_SPEC_TEXT),
        }
    if author == "SpecValidatorAgent":
        return {
            "story_draft": state.get(KEY_STORY_DRAFT),
            "technical_spec": state.get("technical_spec"),
            "authority_context": state.get("authority_context"),
            "forbidden_capabilities": state.get("forbidden_capabilities"),
        }
    if author == "StoryRefinerAgent":
        return {
            "story_draft": state.get(KEY_STORY_DRAFT),
            "spec_validation_result": state.get(KEY_SPEC_VALIDATION_RESULT),
            "story_input": state.get("story_input"),
        }
    return None
