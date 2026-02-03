"""
Tools for orchestrator to invoke the story validation pipeline.

These tools handle:
1. Setting up state for a single story
2. Running the pipeline
3. Extracting the validated story
4. Batch processing multiple features
5. Deterministic alignment enforcement (spec authority forbidden capability checking)
"""

import json

from typing import Any, Dict, Optional, cast
from pydantic import ValidationError
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext

from orchestrator_agent.agent_tools.story_pipeline.util.models import ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline.util.logging import PipelineLogger
from orchestrator_agent.agent_tools.story_pipeline.util.constants import (
    KEY_AUTHORITY_CONTEXT,
    KEY_FORBIDDEN_CAPABILITIES,
    KEY_RAW_SPEC_TEXT,
    KEY_SPEC_VALIDATION_RESULT,
    KEY_STORY_DRAFT,
    KEY_CURRENT_FEATURE,
    KEY_PRODUCT_CONTEXT,
    KEY_SPEC_VERSION_ID,
    KEY_USER_PERSONA,
    KEY_STORY_PREFERENCES,
    KEY_REFINEMENT_FEEDBACK,
)
from orchestrator_agent.agent_tools.story_pipeline.steps.setup import (
    normalize_story_input_defaults,
    resolve_spec_version_id,
    setup_authority_and_alignment,
    build_initial_state
)
from orchestrator_agent.agent_tools.story_pipeline.steps.execution import (
    create_pipeline_runner,
    execute_pipeline
)
from orchestrator_agent.agent_tools.story_pipeline.steps.postprocessing import (
    process_pipeline_result
)
from orchestrator_agent.agent_tools.story_pipeline.util.helpers import (
    maybe_parse_json,
    build_story_draft_input_payload
)

# Export ProcessStoryInput for backward compatibility with tools.py
__all__ = ["process_single_story"]





async def process_single_story(
    story_input: ProcessStoryInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Process a single feature through the story validation pipeline.
    
    HYBRID APPROACH:
    - Primary data comes from 'story_input' (explicit arguments).
    - If spec_content/content_ref are missing in input, falls back to tool_context.state
      for 'pending_spec_content' and 'pending_spec_path' (set by load_specification_from_file).
    - This fallback improves robustness when LLM forgets to pass spec content explicitly.
    
    This tool:
    1. Validates feature alignment with spec authority forbidden capabilities
    2. Sets up initial state with feature context + forbidden capabilities
    3. Runs the LoopAgent pipeline (Draft → Validate → Refine)
    4. Applies deterministic post-validation (catches LLM misses + drift)
    5. Returns the validated story or rejection
    """

    # --- SETUP & LOGGING ---
    # Use internal logger (printed to stdout unless output_callback injected elsewhere)
    logger = PipelineLogger()

    # Ensure input is a model (handle dict input from tools)
    if isinstance(story_input, dict):
        try:
            story_input = ProcessStoryInput.model_validate(story_input)
        except ValidationError as e:
            return {"success": False, "error": f"Input validation failed: {str(e)}"}

    story_input = cast(ProcessStoryInput, story_input)

    story_input = normalize_story_input_defaults(story_input)
    logger.log_header(story_input.feature_title, story_input.theme, story_input.epic)

    # --- SPEC VERSION RESOLUTION ---
    # Primary: uses story_input's content. Fallback: tool_context.state for pending spec.
    story_input, error_msg = resolve_spec_version_id(story_input, tool_context)
    if error_msg:
        # Check if it was a rejection (spec authority failed) or validation error
        if "Invalid spec_version_id" in error_msg:
            logger.log(f"[Spec REJECTED] {error_msg}")
        else:
            logger.log(f"[Spec Authority FAILED] {error_msg}")
        return {"success": False, "error": error_msg, "story": None}

    # --- AUTHORITY & ALIGNMENT ---
    authority_context, technical_spec, forbidden_capabilities, _, error_response = \
        setup_authority_and_alignment(story_input)

    if error_response:
        # If it's a rejection response (list of issues), log them
        if "alignment_issues" in error_response:
            logger.log("[Alignment REJECTED] Feature violates spec authority forbidden capabilities:")
            for issue in error_response.get("alignment_issues", []):
                logger.log(f"   - {issue}")
        elif error_response.get("error"):
            logger.log(f"[Error] {error_response['error']}")
        return error_response

    if forbidden_capabilities:
        logger.log(f"[Constraints] Forbidden capabilities (spec authority): {forbidden_capabilities}")

    # --- BUILD INITIAL STATE ---
    initial_state = build_initial_state(
        story_input, authority_context or {}, technical_spec, forbidden_capabilities or []
    )

    # --- EXECUTION ---
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="story_pipeline",
        user_id="pipeline_user",
        state=initial_state,
    )

    runner, _ = create_pipeline_runner(story_input, session_service)

    try:
        final_state = await execute_pipeline(
            runner, session.id, story_input, logger, session_service
        )
    except Exception as e:
         return {"success": False, "error": f"Pipeline error: {str(e)}"}

    # Debug Dump (include per-agent inputs after pipeline runs)
    try:
        story_draft_payload = build_story_draft_input_payload(initial_state, story_input)
        prompt_text = json.dumps(story_draft_payload, ensure_ascii=False)
        debug_info: Dict[str, Any] = {
            "agent_inputs": {
                "PipelinePrompt": {
                    "text": prompt_text,
                },
                "StoryDraftAgent": {
                    "current_feature": maybe_parse_json(initial_state.get(KEY_CURRENT_FEATURE)),
                    "product_context": maybe_parse_json(initial_state.get(KEY_PRODUCT_CONTEXT)),
                    "spec_version_id": initial_state.get(KEY_SPEC_VERSION_ID),
                    "authority_context": maybe_parse_json(initial_state.get(KEY_AUTHORITY_CONTEXT)),
                    "user_persona": initial_state.get(KEY_USER_PERSONA),
                    "story_preferences": maybe_parse_json(initial_state.get(KEY_STORY_PREFERENCES)),
                    "refinement_feedback": initial_state.get(KEY_REFINEMENT_FEEDBACK),
                    "raw_spec_text": initial_state.get(KEY_RAW_SPEC_TEXT),
                },
                "SpecValidatorAgent": {
                    "story_draft": final_state.get(KEY_STORY_DRAFT),
                    "technical_spec": initial_state.get(KEY_RAW_SPEC_TEXT),
                    "authority_context": initial_state.get(KEY_AUTHORITY_CONTEXT),
                    "forbidden_capabilities": initial_state.get(KEY_FORBIDDEN_CAPABILITIES),
                },
                "StoryRefinerAgent": {
                    "story_draft": final_state.get(KEY_STORY_DRAFT),
                    "spec_validation_result": final_state.get(KEY_SPEC_VALIDATION_RESULT),
                    "story_input": story_input.model_dump(),
                },
            }
        }
        logger.dump_debug_info(debug_info)
    except Exception as e:
        logger.log(f"[Debug Error] Failed to dump debug info: {e}")

    # --- POST-PROCESSING ---
    return process_pipeline_result(
        final_state, story_input, forbidden_capabilities or [], logger
    )
