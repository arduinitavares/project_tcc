import json
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select
from google.adk.tools import ToolContext

from agile_sqlmodel import ProductPersona, get_engine
from tools.spec_tools import ensure_accepted_spec_authority

from orchestrator_agent.agent_tools.story_pipeline.models import ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline.pipeline_constants import (
    KEY_CURRENT_FEATURE, KEY_PRODUCT_CONTEXT, KEY_SPEC_VERSION_ID,
    KEY_AUTHORITY_CONTEXT, KEY_RAW_SPEC_TEXT, KEY_FORBIDDEN_CAPABILITIES,
    KEY_USER_PERSONA, KEY_STORY_PREFERENCES, KEY_REFINEMENT_FEEDBACK,
    KEY_ITERATION_COUNT
)
from orchestrator_agent.agent_tools.story_pipeline.common import load_compiled_authority
from orchestrator_agent.agent_tools.story_pipeline.persona_checker import normalize_persona
from orchestrator_agent.agent_tools.story_pipeline.alignment_checker import (
    validate_feature_alignment,
    create_rejection_response,
    extract_invariants_from_authority,
    derive_forbidden_capabilities_from_authority,
)
from orchestrator_agent.agent_tools.story_pipeline.story_generation_context import build_generation_context


def normalize_story_input_defaults(story_input: ProcessStoryInput) -> ProcessStoryInput:
    """Apply defaults for optional parameters."""
    return story_input.model_copy(
        update={
            "user_persona": story_input.user_persona or "user",
            "include_story_points": story_input.include_story_points if story_input.include_story_points is not None else True,
            "recompile": story_input.recompile if story_input.recompile is not None else False,
            "enable_story_refiner": story_input.enable_story_refiner if story_input.enable_story_refiner is not None else True,
            "enable_spec_validator": story_input.enable_spec_validator if story_input.enable_spec_validator is not None else True,
            "pass_raw_spec_text": story_input.pass_raw_spec_text if story_input.pass_raw_spec_text is not None else True,
        }
    )

def resolve_spec_version_id(
    story_input: ProcessStoryInput,
    tool_context: Optional[ToolContext]
) -> Tuple[ProcessStoryInput, Optional[str]]:
    """Resolves the spec version ID, compiling if necessary. Returns updated input and error string."""

    if story_input.spec_version_id is not None and story_input.spec_version_id <= 0:
        return story_input, f"Invalid spec_version_id: {story_input.spec_version_id}. Must be a positive integer or None."

    effective_spec_version_id = story_input.spec_version_id
    if not effective_spec_version_id:
        spec_content = story_input.spec_content
        content_ref = story_input.content_ref
        if tool_context and tool_context.state:
            spec_content = spec_content or tool_context.state.get("pending_spec_content")
            content_ref = content_ref or tool_context.state.get("pending_spec_path")

        if spec_content and content_ref:
            spec_content = None

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

def validate_persona_against_registry(
    product_id: int, requested_persona: str, db_session: Session
) -> tuple[bool, Optional[str]]:
    """Check if persona is approved for this product."""
    approved = db_session.exec(
        select(ProductPersona.persona_name).where(
            ProductPersona.product_id == product_id
        )
    ).all()

    if not approved:
        return True, None

    requested_norm = normalize_persona(requested_persona)
    approved_norm = [normalize_persona(p) for p in approved]

    if requested_norm in approved_norm:
        return True, None

    return False, (
        f"Persona '{requested_persona}' not in approved list for this product. "
        f"Approved personas: {list(approved)}"
    )

def setup_authority_and_alignment(story_input: ProcessStoryInput):
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

    # Check domain constraint
    domain = (authority_context.get("domain") or "").lower()
    technical_domains = {"training", "provenance", "ingestion", "audit", "revision"}
    if domain in technical_domains and not story_input.delivery_role:
        error_message = (
            f"Unsatisfiable constraints: domain '{domain}' requires delivery_role, "
            "but none was provided."
        )
        return None, None, None, None, {"success": False, "error": error_message, "story": None}

    return authority_context, technical_spec, forbidden_capabilities, invariants, None


def build_initial_state(
    story_input: ProcessStoryInput,
    authority_context: Dict[str, Any],
    technical_spec: Optional[str],
    forbidden_capabilities: List[str]
) -> Dict[str, Any]:
    """Constructs the initial session state for the runner."""
    state = {
        KEY_CURRENT_FEATURE: json.dumps(
            {
                "feature_id": story_input.feature_id,
                "feature_title": story_input.feature_title,
                "theme": story_input.theme,
                "epic": story_input.epic,
                "time_frame": story_input.time_frame,
                "theme_justification": story_input.theme_justification,
                "sibling_features": story_input.sibling_features or [],
                "delivery_role": story_input.delivery_role,
            }
        ),
        KEY_PRODUCT_CONTEXT: json.dumps(
            {
                "product_id": story_input.product_id,
                "product_name": story_input.product_name,
                "vision": story_input.product_vision or "",
                "forbidden_capabilities": forbidden_capabilities,
                "time_frame": story_input.time_frame,
            }
        ),
        KEY_SPEC_VERSION_ID: story_input.spec_version_id,
        KEY_AUTHORITY_CONTEXT: json.dumps(authority_context),
        "original_feature_title": story_input.feature_title,
        KEY_FORBIDDEN_CAPABILITIES: json.dumps(forbidden_capabilities),
        KEY_USER_PERSONA: story_input.user_persona,
        KEY_STORY_PREFERENCES: json.dumps(
            {
                "include_story_points": story_input.include_story_points,
            }
        ),
        KEY_REFINEMENT_FEEDBACK: "",
        KEY_ITERATION_COUNT: 0,
    }

    if story_input.pass_raw_spec_text and technical_spec:
        state[KEY_RAW_SPEC_TEXT] = technical_spec

    return state
