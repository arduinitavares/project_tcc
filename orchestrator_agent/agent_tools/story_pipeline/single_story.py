"""
Tools for orchestrator to invoke the story validation pipeline.

These tools handle:
1. Setting up state for a single story
2. Running the pipeline
3. Extracting the validated story
4. Batch processing multiple features
5. Deterministic alignment enforcement (spec authority forbidden capability checking)
"""

from typing import Any, Callable, Dict, Optional
from sqlmodel import Session
from google.adk.tools import ToolContext
from google.adk.sessions import InMemorySessionService

from agile_sqlmodel import get_engine

from orchestrator_agent.agent_tools.story_pipeline.models import ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline.pipeline_logging import PipelineLogger
from orchestrator_agent.agent_tools.story_pipeline.pipeline_setup import (
    normalize_story_input_defaults,
    resolve_spec_version_id,
    validate_persona_against_registry,
    setup_authority_and_alignment,
    build_initial_state
)
from orchestrator_agent.agent_tools.story_pipeline.pipeline_execution import (
    create_pipeline_runner,
    execute_pipeline
)
from orchestrator_agent.agent_tools.story_pipeline.pipeline_postprocessing import (
    process_pipeline_result
)

# Export ProcessStoryInput for backward compatibility with tools.py
__all__ = ["ProcessStoryInput", "process_single_story", "validate_persona_against_registry"]


async def process_single_story(
    story_input: ProcessStoryInput,
    output_callback: Optional[Callable[[str], None]] = None,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Process a single feature through the story validation pipeline.

    This tool:
    1. Validates feature alignment with spec authority forbidden capabilities
    2. Sets up initial state with feature context + forbidden capabilities
    3. Runs the LoopAgent pipeline (Draft → Validate → Refine)
    4. Applies deterministic post-validation (catches LLM misses + drift)
    5. Returns the validated story or rejection
    """

    # --- SETUP & LOGGING ---
    logger = PipelineLogger(output_callback, tool_context)
    story_input = normalize_story_input_defaults(story_input)
    logger.log_header(story_input.feature_title, story_input.theme, story_input.epic)

    # --- SPEC VERSION RESOLUTION ---
    story_input, error_msg = resolve_spec_version_id(story_input, tool_context)
    if error_msg:
        # Check if it was a rejection (spec authority failed) or validation error
        if "Invalid spec_version_id" in error_msg:
            logger.log(f"\033[91m[Spec REJECTED]\033[0m {error_msg}")
        else:
            logger.log(f"\033[91m[Spec Authority FAILED]\033[0m {error_msg}")
        return {"success": False, "error": error_msg, "story": None}

    # --- FAIL-FAST: PERSONA CHECK ---
    with Session(get_engine()) as session:
        is_valid_persona, persona_error = validate_persona_against_registry(
            story_input.product_id, story_input.user_persona, session
        )
        if not is_valid_persona:
            logger.log(f"\033[91m[Persona REJECTED]\033[0m {persona_error}")
            return {"success": False, "error": persona_error, "story": None}

    # --- AUTHORITY & ALIGNMENT ---
    authority_context, technical_spec, forbidden_capabilities, invariants, error_response = \
        setup_authority_and_alignment(story_input)

    if error_response:
        # If it's a rejection response (list of issues), log them
        if "alignment_issues" in error_response:
            logger.log(f"\033[91m[Alignment REJECTED]\033[0m Feature violates spec authority forbidden capabilities:")
            for issue in error_response.get("alignment_issues", []):
                logger.log(f"   \033[91m✗\033[0m {issue}")
        elif error_response.get("error"):
            logger.log(f"\033[91m[Error]\033[0m {error_response['error']}")
        return error_response

    if forbidden_capabilities:
        logger.log(f"\033[93m[Constraints]\033[0m Forbidden capabilities (spec authority): {forbidden_capabilities}")

    # --- BUILD INITIAL STATE ---
    initial_state = build_initial_state(
        story_input, authority_context, technical_spec, forbidden_capabilities
    )

    # --- EXECUTION ---
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="story_pipeline",
        user_id="pipeline_user",
        state=initial_state,
    )

    runner, agent_to_run = create_pipeline_runner(story_input, session_service)

    # Debug Dump
    try:
        debug_info = {
            "prompt_text": f"Generate a user story for feature: {story_input.feature_title}",
            "initial_state": initial_state,
            "story_input": story_input.model_dump(),
            "instructions": logger.extract_agent_instructions(agent_to_run)
        }
        logger.dump_debug_info(debug_info)
    except Exception as e:
        logger.log(f"\033[91m[Debug Error]\033[0m Failed to dump debug info: {e}")

    try:
        final_state = await execute_pipeline(
            runner, session.id, story_input.feature_title, story_input, logger, session_service
        )
    except Exception as e:
         return {"success": False, "error": f"Pipeline error: {str(e)}"}

    # --- POST-PROCESSING ---
    return process_pipeline_result(
        final_state, story_input, forbidden_capabilities, logger
    )
