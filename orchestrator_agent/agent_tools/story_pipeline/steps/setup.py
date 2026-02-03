import json
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session
from google.adk.tools import ToolContext

from agile_sqlmodel import get_engine
from tools.spec_tools import ensure_accepted_spec_authority

from orchestrator_agent.agent_tools.story_pipeline.util.models import ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline.util.constants import (
    KEY_CURRENT_FEATURE, KEY_PRODUCT_CONTEXT, KEY_SPEC_VERSION_ID,
    KEY_AUTHORITY_CONTEXT, KEY_RAW_SPEC_TEXT, KEY_FORBIDDEN_CAPABILITIES,
    KEY_USER_PERSONA, KEY_STORY_PREFERENCES, KEY_REFINEMENT_FEEDBACK,
    KEY_ITERATION_COUNT, KEY_ORIGINAL_FEATURE_TITLE
)
from orchestrator_agent.agent_tools.story_pipeline.util.common import load_compiled_authority
from orchestrator_agent.agent_tools.story_pipeline.steps.alignment_checker import (
    validate_feature_alignment,
    create_rejection_response,
    extract_invariants_from_authority,
    derive_forbidden_capabilities_from_authority,
)
from orchestrator_agent.agent_tools.story_pipeline.util.story_generation_context import build_generation_context


def normalize_story_input_defaults(story_input: ProcessStoryInput) -> ProcessStoryInput:
    """Apply defaults for optional parameters."""
    return story_input.model_copy(
        update={
            "include_story_points": story_input.include_story_points if story_input.include_story_points is not None else True,
            "recompile": story_input.recompile if story_input.recompile is not None else False,
            "enable_story_refiner": story_input.enable_story_refiner if story_input.enable_story_refiner is not None else True,
            "enable_spec_validator": story_input.enable_spec_validator if story_input.enable_spec_validator is not None else True,
            "pass_raw_spec_text": story_input.pass_raw_spec_text if story_input.pass_raw_spec_text is not None else True,
        }
    )

def resolve_spec_version_id(
    story_input: ProcessStoryInput,
    tool_context: Optional[ToolContext] = None,
) -> Tuple[ProcessStoryInput, Optional[str]]:
    """Resolves the spec version ID, compiling if necessary. Returns updated input and error string.
    
    Fallback Logic:
    - If spec_content/content_ref are not in story_input, checks tool_context.state for:
      - 'pending_spec_content' (set by load_specification_from_file)
      - 'pending_spec_path' (set by load_specification_from_file)
    - This fallback handles cases where LLM forgets to pass spec content explicitly.
    """

    if story_input.spec_version_id is not None and story_input.spec_version_id <= 0:
        return story_input, f"Invalid spec_version_id: {story_input.spec_version_id}. Must be a positive integer or None."

    effective_spec_version_id = story_input.spec_version_id
    if not effective_spec_version_id:
        spec_content = story_input.spec_content
        content_ref = story_input.content_ref
        
        # FALLBACK: If not in input, check tool_context.state (set by load_specification_from_file)
        if not spec_content and not content_ref and tool_context and tool_context.state:
            state = tool_context.state
            if "pending_spec_content" in state:
                spec_content = state["pending_spec_content"]
            if "pending_spec_path" in state:
                content_ref = state["pending_spec_path"]

        try:
            effective_spec_version_id = ensure_accepted_spec_authority(
                story_input.product_id,
                spec_content=spec_content,
                content_ref=content_ref,
                recompile=story_input.recompile,
                tool_context=tool_context,
            )
        except RuntimeError as e:
            return story_input, str(e)

        story_input = story_input.model_copy(
            update={"spec_version_id": effective_spec_version_id}
        )

    return story_input, None

def setup_authority_and_alignment(story_input: ProcessStoryInput) -> Tuple[
    Optional[Dict[str, Any]],
    Optional[str],
    Optional[List[str]],
    Optional[List[str]],
    Optional[Dict[str, Any]]
]:
    """Loads authority, extracts invariants, and checks feature alignment."""
    with Session(get_engine()) as session:
        try:
            spec_version, compiled_authority, technical_spec = load_compiled_authority(
                session=session,
                product_id=story_input.product_id,
                spec_version_id=story_input.spec_version_id,
            )
        except ValueError as exc:
            return None, None, None, None, {"success": False, "error": str(exc)}

    invariants = extract_invariants_from_authority(compiled_authority)
    forbidden_items = derive_forbidden_capabilities_from_authority(
        compiled_authority,
        invariants=invariants,
    )
    forbidden_capabilities = [item.term for item in forbidden_items]

    # Check feature alignment
    feature_alignment = validate_feature_alignment(
        story_input.feature_title,
        compiled_authority=compiled_authority,
    )

    if not feature_alignment.is_aligned:
        response = create_rejection_response(
            feature_title=story_input.feature_title,
            alignment_issues=feature_alignment.alignment_issues,
            invariants=invariants,
        )
        return None, None, None, None, response

    authority_context = build_generation_context(
        compiled_authority=compiled_authority,
        spec_version_id=story_input.spec_version_id,
        spec_hash=getattr(spec_version, "spec_hash", None),
    )


    return authority_context, technical_spec, forbidden_capabilities, invariants, None


def build_initial_state(
    story_input: ProcessStoryInput,
    authority_context: Dict[str, Any],
    technical_spec: Optional[str],
    forbidden_capabilities: List[str]
) -> Dict[str, Any]:
    """Constructs the initial session state for the runner."""
    state = {
        KEY_CURRENT_FEATURE: {
            "feature_id": story_input.feature_id,
            "feature_title": story_input.feature_title,
            "theme": story_input.theme,
            "epic": story_input.epic,
            "time_frame": story_input.time_frame,
            "theme_justification": story_input.theme_justification,
            "sibling_features": story_input.sibling_features or [],
        },
        KEY_PRODUCT_CONTEXT: {
            "product_id": story_input.product_id,
            "product_name": story_input.product_name,
            "vision": story_input.product_vision or "",
            "forbidden_capabilities": forbidden_capabilities,
            "time_frame": story_input.time_frame,
        },
        KEY_SPEC_VERSION_ID: story_input.spec_version_id,
        KEY_AUTHORITY_CONTEXT: authority_context,
        KEY_ORIGINAL_FEATURE_TITLE: story_input.feature_title,
        KEY_FORBIDDEN_CAPABILITIES: forbidden_capabilities,
        KEY_USER_PERSONA: story_input.user_persona,
        KEY_STORY_PREFERENCES: {
            "include_story_points": story_input.include_story_points,
        },
        KEY_REFINEMENT_FEEDBACK: "",
        KEY_ITERATION_COUNT: 0,
    }

    if story_input.pass_raw_spec_text and technical_spec:
        state[KEY_RAW_SPEC_TEXT] = technical_spec

    return state
