"""Post-processing utilities for the story pipeline."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from orchestrator_agent.agent_tools.story_pipeline.steps.alignment_checker import (
    check_alignment_violation,
    detect_requirement_drift,
)
from orchestrator_agent.agent_tools.story_pipeline.util.constants import (
    KEY_REFINEMENT_RESULT,
    KEY_STORY_DRAFT,
    KEY_SPEC_VALIDATION_RESULT,
    KEY_ITERATION_COUNT,
)
from orchestrator_agent.agent_tools.story_pipeline.util.story_contract_enforcer import (
    enforce_story_contracts,
    format_contract_violations,
)
from orchestrator_agent.agent_tools.story_pipeline.util.models import ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline.util.logging import PipelineLogger


def _ensure_spec_version_metadata(
    story_payload: Dict[str, Any],
    spec_version_id: Optional[int],
) -> Dict[str, Any]:
    metadata = story_payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["spec_version_id"] = spec_version_id
    story_payload["metadata"] = metadata
    return story_payload


def _parse_json_payload(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    return value


def _get_iterations(state: Dict[str, Any]) -> int:
    iterations = state.get("_local_iterations")
    if isinstance(iterations, int) and iterations > 0:
        return iterations
    if isinstance(state.get(KEY_ITERATION_COUNT), int) and state.get(KEY_ITERATION_COUNT) > 0:
        return state.get(KEY_ITERATION_COUNT)
    return 1


def process_pipeline_result(
    state: Dict[str, Any],
    story_input: ProcessStoryInput,
    forbidden_capabilities: List[str],
    logger: PipelineLogger,
) -> Dict[str, Any]:
    """Extracts story from final state and applies deterministic enforcement."""
    state = state or {}
    iterations = _get_iterations(state)

    refinement_result = state.get(KEY_REFINEMENT_RESULT)
    story_draft = state.get(KEY_STORY_DRAFT)

    if not story_input.enable_story_refiner:
        if isinstance(story_draft, str):
            story_draft = _parse_json_payload(story_draft)
        if isinstance(story_draft, dict):
            _ensure_spec_version_metadata(story_draft, story_input.spec_version_id)
            state[KEY_REFINEMENT_RESULT] = {
                "refined_story": story_draft,
                "is_valid": True,
                "refinement_applied": False,
                "refinement_notes": "Story refiner disabled.",
            }
            refinement_result = state.get(KEY_REFINEMENT_RESULT)

    refinement_data = _parse_json_payload(refinement_result)
    if isinstance(refinement_data, dict) and refinement_data:
        refined_story = refinement_data.get("refined_story", {}) or {}
        if not isinstance(refined_story, dict):
            refined_story = {}
        is_valid = refinement_data.get("is_valid", False)
        refinement_notes = str(refinement_data.get("refinement_notes", ""))

        refined_story["feature_id"] = story_input.feature_id
        refined_story["feature_title"] = story_input.feature_title
        _ensure_spec_version_metadata(refined_story, story_input.spec_version_id)

        if not story_input.include_story_points and refined_story.get("story_points") is not None:
            refined_story["story_points"] = None

        alignment_issues: List[str] = []

        story_text = f"{refined_story.get('title', '')} {refined_story.get('description', '')}"
        story_alignment = check_alignment_violation(
            story_text,
            forbidden_capabilities,
            "generated story",
        )
        if not story_alignment.is_aligned:
            alignment_issues.extend(story_alignment.alignment_issues)
            for issue in story_alignment.alignment_issues:
                logger.log(f"Alignment issue: {issue}")

        drift_detected, drift_message = detect_requirement_drift(
            original_feature=story_input.feature_title,
            final_story_title=refined_story.get("title", ""),
            final_story_description=refined_story.get("description", ""),
            forbidden_capabilities=forbidden_capabilities,
        )
        if drift_detected and drift_message:
            alignment_issues.append(drift_message)
            logger.log(f"Drift detected: {drift_message}")

        if alignment_issues:
            is_valid = False

        refined_story["theme"] = story_input.theme
        refined_story["epic"] = story_input.epic
        refined_story["feature_id"] = story_input.feature_id
        refined_story["theme_id"] = story_input.theme_id
        refined_story["epic_id"] = story_input.epic_id

        spec_validation_payload = _parse_json_payload(state.get(KEY_SPEC_VALIDATION_RESULT))
        if not isinstance(spec_validation_payload, dict):
            spec_validation_payload = None

        contract_result = enforce_story_contracts(
            story=refined_story,
            include_story_points=story_input.include_story_points,
            feature_time_frame=story_input.time_frame,
            allowed_scope=None,
            validation_result=None,
            spec_validation_result=spec_validation_payload,
            refinement_result=refinement_data,
            expected_feature_id=story_input.feature_id,
            theme=story_input.theme,
            epic=story_input.epic,
            theme_id=story_input.theme_id,
            epic_id=story_input.epic_id,
            invest_validation_expected=False,
        )

        if contract_result.is_valid is False:
            is_valid = False
            logger.log(
                f"Contract enforcement failed: {len(contract_result.violations)} violations"
            )
            logger.log(format_contract_violations(contract_result.violations))
        elif contract_result.is_valid is None:
            # Contract enforcement was skipped (INVEST validator removed from architecture).
            # Preserve the refiner's is_valid assessment instead of overwriting with None.
            # The refiner's is_valid (extracted at line ~88) remains the source of truth.
            refined_story = contract_result.sanitized_story or refined_story
            logger.log("Contract enforcement skipped (INVEST validator disabled); using refiner's assessment.")
        else:
            refined_story = contract_result.sanitized_story or refined_story

        message = (
            f"Generated story '{refined_story.get('title', 'Unknown')}' "
            f"(valid={is_valid}, iterations={iterations})"
        )
        if alignment_issues:
            message += f" - REJECTED: {len(alignment_issues)} alignment violations"

        return {
            "success": True,
            "is_valid": is_valid,
            "rejected": len(alignment_issues) > 0,
            "story": refined_story,
            "iterations": iterations,
            "refinement_notes": refinement_notes,
            "alignment_issues": alignment_issues,
            "message": message,
        }

    if isinstance(story_draft, str):
        story_draft = _parse_json_payload(story_draft)

    if isinstance(story_draft, dict):
        story_draft["theme"] = story_input.theme
        story_draft["epic"] = story_input.epic
        story_draft["feature_id"] = story_input.feature_id
        _ensure_spec_version_metadata(story_draft, story_input.spec_version_id)
        return {
            "success": True,
            "is_valid": False,
            "story": story_draft,
            "validation_score": 0,
            "iterations": iterations,
            "refinement_notes": "Pipeline did not complete validation",
            "message": "Story drafted but validation incomplete",
        }

    return {
        "success": False,
        "error": "Pipeline did not produce a story",
        "state_keys": list(state.keys()) if state else [],
    }
