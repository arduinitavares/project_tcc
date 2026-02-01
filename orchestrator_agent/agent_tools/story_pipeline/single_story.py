"""
Tools for orchestrator to invoke the story validation pipeline.

These tools handle:
1. Setting up state for a single story
2. Running the pipeline
3. Extracting the validated story
4. Batch processing multiple features
5. Deterministic alignment enforcement (spec authority forbidden capability checking)
"""

import copy
import json
from typing import Annotated, Any, Callable, Dict, List, Optional, Set

from google.adk.agents import BaseAgent, LlmAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.genai import types
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from agile_sqlmodel import ProductPersona, get_engine
from .alignment_checker import (
    check_alignment_violation,
    create_rejection_response,
    derive_forbidden_capabilities_from_authority,
    detect_requirement_drift,
    extract_invariants_from_authority,
    validate_feature_alignment,
)
from .persona_checker import (
    normalize_persona,
    validate_persona,
)
from .pipeline import story_validation_loop
from .story_contract_enforcer import (
    enforce_story_contracts,
    format_contract_violations,
)
from .story_draft_agent.agent import story_draft_agent
from .story_generation_context import build_generation_context
from .story_refiner_agent.agent import story_refiner_agent
from tools.spec_tools import ensure_accepted_spec_authority
from orchestrator_agent.agent_tools.utils.resilience import SelfHealingAgent

from .common import load_compiled_authority

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def _ensure_spec_version_metadata(
    story_payload: Dict[str, Any],
    spec_version_id: int,
) -> Dict[str, Any]:
    metadata = story_payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["spec_version_id"] = spec_version_id
    story_payload["metadata"] = metadata
    return story_payload


def _clone_agent(agent: BaseAgent) -> BaseAgent:
    if isinstance(agent, LlmAgent):
        return LlmAgent(
            name=agent.name,
            model=agent.model,
            instruction=agent.instruction,
            description=getattr(agent, "description", None),
            output_key=getattr(agent, "output_key", None),
            output_schema=getattr(agent, "output_schema", None),
            disallow_transfer_to_parent=getattr(agent, "disallow_transfer_to_parent", False),
            disallow_transfer_to_peers=getattr(agent, "disallow_transfer_to_peers", False),
        )
    cloned = copy.deepcopy(agent)
    if hasattr(cloned, "parent"):
        setattr(cloned, "parent", None)
    if hasattr(cloned, "_parent"):
        setattr(cloned, "_parent", None)
    return cloned


# --- Schema for single story processing ---


class ProcessStoryInput(BaseModel):
    """Input schema for process_single_story tool.

    IMMUTABILITY: This model is frozen to prevent accidental mutation during pipeline processing.
    Source metadata (theme, epic, theme_id, epic_id) must remain unchanged from construction
    through contract enforcement to ensure data integrity.
    """

    model_config = {"frozen": True}  # Immutable after construction

    product_id: Annotated[int, Field(description="The product ID.")]
    product_name: Annotated[str, Field(description="The product name.")]
    product_vision: Annotated[
        Optional[str], Field(description="The product vision statement. Defaults to None if not provided.")
    ] = None
    feature_id: Annotated[
        int, Field(description="The feature ID to create a story for.")
    ]
    feature_title: Annotated[str, Field(description="The feature title.")]
    # --- Stable ID-based references (for contract validation) ---
    theme_id: Annotated[
        int,
        Field(
            description="Theme database ID (stable reference - eliminates duplicate name ambiguity)",
        ),
    ]
    epic_id: Annotated[
        int,
        Field(
            description="Epic database ID (stable reference - eliminates duplicate name ambiguity)",
        ),
    ]
    # --- Title-based references ---
    theme: Annotated[str, Field(description="The theme this feature belongs to.")]
    epic: Annotated[str, Field(description="The epic this feature belongs to.")]
    # NEW: Roadmap context fields for strategic awareness
    time_frame: Annotated[
        Optional[str],
        Field(
            default=None,
            description="The roadmap time frame: 'Now', 'Next', or 'Later'.",
        ),
    ] = None
    theme_justification: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Strategic justification for why this theme exists.",
        ),
    ] = None
    sibling_features: Annotated[
        Optional[List[str]],
        Field(
            default=None,
            description="Other features in the same theme (for context).",
        ),
    ] = None
    user_persona: Annotated[
        Optional[str],
        Field(
            description="The target user persona for the story. Defaults to 'user' if not provided.",
        ),
    ] = None
    delivery_role: Annotated[
        Optional[str],
        Field(
            description=(
                "Delivery responsibility role for technical implementation (e.g., 'ml engineer'). "
                "Used for compliance policy; MUST NOT replace user_persona."
            ),
        ),
    ] = None
    include_story_points: Annotated[
        Optional[bool],
        Field(
            description="Whether to include story point estimates. Defaults to True if not provided.",
        ),
    ] = None
    spec_version_id: Annotated[
        Optional[int],
        Field(
            description="Compiled spec version ID to validate against. Defaults to None if not provided.",
        ),
    ] = None
    spec_content: Annotated[
        Optional[str],
        Field(
            description="Optional spec text to compile if no accepted authority exists. Defaults to None if not provided.",
        ),
    ] = None
    content_ref: Annotated[
        Optional[str],
        Field(
            description="Optional spec file path to compile if no accepted authority exists. Defaults to None if not provided.",
        ),
    ] = None
    recompile: Annotated[
        Optional[bool],
        Field(
            description="Force recompile even if authority cache exists. Defaults to False if not provided.",
        ),
    ] = None
    enable_story_refiner: Annotated[
        Optional[bool],
        Field(
            description="Whether to run the story refiner loop (A/B testing). Defaults to True if not provided.",
        ),
    ] = None
    enable_spec_validator: Annotated[
        Optional[bool],
        Field(
            description="Whether to run the spec validator agent. Defaults to True if not provided.",
        ),
    ] = None
    pass_raw_spec_text: Annotated[
        Optional[bool],
        Field(
            description="Whether to pass raw spec text into session state. Defaults to True if not provided.",
        ),
    ] = None


def validate_persona_against_registry(
    product_id: int, requested_persona: str, db_session: Session
) -> tuple[bool, Optional[str]]:
    """
    Check if persona is approved for this product.

    Returns:
        (is_valid, error_message)
    """
    # Query approved personas
    approved = db_session.exec(
        select(ProductPersona.persona_name).where(
            ProductPersona.product_id == product_id
        )
    ).all()

    if not approved:
        # No personas defined - allow any (fallback)
        return True, None

    # Normalize for comparison
    requested_norm = normalize_persona(requested_persona)
    approved_norm = [normalize_persona(p) for p in approved]

    if requested_norm in approved_norm:
        return True, None

    return False, (
        f"Persona '{requested_persona}' not in approved list for this product. "
        f"Approved personas: {list(approved)}"
    )


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

    The pipeline will loop up to 3 times until a valid story is produced.
    """
    # --- Apply defaults for optional parameters (moved from schema to runtime) ---
    # Create new instance with defaults applied using model_copy (works with frozen models)
    story_input = story_input.model_copy(
        update={
            "user_persona": story_input.user_persona or "user",
            "include_story_points": story_input.include_story_points if story_input.include_story_points is not None else True,
            "recompile": story_input.recompile if story_input.recompile is not None else False,
            "enable_story_refiner": story_input.enable_story_refiner if story_input.enable_story_refiner is not None else True,
            "enable_spec_validator": story_input.enable_spec_validator if story_input.enable_spec_validator is not None else True,
            "pass_raw_spec_text": story_input.pass_raw_spec_text if story_input.pass_raw_spec_text is not None else True,
        }
    )

    # --- Helper for logging ---
    def log(msg: str):
        if output_callback:
            output_callback(msg)
        else:
            print(msg)

    log(
        f"\n{CYAN}[Pipeline]{RESET} Processing feature: {BOLD}'{story_input.feature_title}'{RESET}"
    )
    log(f"{DIM}   Theme: {story_input.theme} | Epic: {story_input.epic}{RESET}")

    # --- Fail-fast check for invalid spec_version_id ---
    # spec_version_id=0 is explicitly invalid (not the same as None/missing)
    if story_input.spec_version_id is not None and story_input.spec_version_id <= 0:
        log(f"{RED}[Spec REJECTED]{RESET} Invalid spec_version_id: {story_input.spec_version_id}")
        return {
            "success": False,
            "error": f"Invalid spec_version_id: {story_input.spec_version_id}. Must be a positive integer or None.",
            "story": None,
        }

    effective_spec_version_id = story_input.spec_version_id
    if not effective_spec_version_id:
        spec_content = story_input.spec_content
        content_ref = story_input.content_ref
        if tool_context and tool_context.state:
            spec_content = spec_content or tool_context.state.get("pending_spec_content")
            content_ref = content_ref or tool_context.state.get("pending_spec_path")

        # Authority gate requires exactly one of spec_content or content_ref.
        # If both are set, prefer content_ref (file path) as the canonical source.
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
            log(f"{RED}[Spec Authority FAILED]{RESET} {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "story": None,
            }
        story_input = story_input.model_copy(
            update={"spec_version_id": effective_spec_version_id}
        )

    # --- STEP 0: Fail-Fast Persona Whitelist Check ---
    with Session(get_engine()) as session:
        is_valid_persona, persona_error = validate_persona_against_registry(
            story_input.product_id, story_input.user_persona, session
        )
        if not is_valid_persona:
            log(f"{RED}[Persona REJECTED]{RESET} {persona_error}")
            return {
                "success": False,
                "error": persona_error,
                "story": None,
            }

    # --- STEP 1: Load compiled spec authority by spec_version_id (no fallbacks) ---
    with Session(get_engine()) as session:
        try:
            spec_version, compiled_authority, technical_spec = load_compiled_authority(
                session=session,
                product_id=story_input.product_id,
                spec_version_id=story_input.spec_version_id,
            )
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
            }

    invariants = extract_invariants_from_authority(compiled_authority)
    forbidden_items = derive_forbidden_capabilities_from_authority(
        compiled_authority,
        invariants=invariants,
    )
    forbidden_capabilities = [item.term for item in forbidden_items]
    if forbidden_capabilities:
        log(
            f"{YELLOW}[Constraints]{RESET} Forbidden capabilities (spec authority): "
            f"{forbidden_capabilities}"
        )

    # --- STEP 2: FAIL-FAST - Check feature alignment BEFORE running pipeline ---
    feature_alignment = validate_feature_alignment(
        story_input.feature_title,
        compiled_authority=compiled_authority,
    )

    if not feature_alignment.is_aligned:
        log(
            f"{RED}[Alignment REJECTED]{RESET} "
            f"Feature violates spec authority forbidden capabilities:"
        )
        for issue in feature_alignment.alignment_issues:
            log(f"   {RED}✗{RESET} {issue}")

        # Return rejection response - do NOT run the pipeline
        return create_rejection_response(
            feature_title=story_input.feature_title,
            alignment_issues=feature_alignment.alignment_issues,
            invariants=invariants,
        )

    authority_context = build_generation_context(
        compiled_authority=compiled_authority,
        spec_version_id=story_input.spec_version_id,
        spec_hash=getattr(spec_version, "spec_hash", None),
    )

    domain = (authority_context.get("domain") or "").lower()
    technical_domains = {"training", "provenance", "ingestion", "audit", "revision"}
    if domain in technical_domains and not story_input.delivery_role:
        error_message = (
            f"Unsatisfiable constraints: domain '{domain}' requires delivery_role, "
            "but none was provided."
        )
        log(f"{RED}[Persona REJECTED]{RESET} {error_message}")
        return {
            "success": False,
            "error": error_message,
            "story": None,
        }

    # --- Set up initial state (includes forbidden_capabilities for validator) ---
    initial_state: Dict[str, Any] = {
        "current_feature": json.dumps(
            {
                "feature_id": story_input.feature_id,
                "feature_title": story_input.feature_title,
                "theme": story_input.theme,
                "epic": story_input.epic,
                # Roadmap context for better story alignment
                "time_frame": story_input.time_frame,
                "theme_justification": story_input.theme_justification,
                "sibling_features": story_input.sibling_features or [],
                "delivery_role": story_input.delivery_role,
            }
        ),
        "product_context": json.dumps(
            {
                "product_id": story_input.product_id,
                "product_name": story_input.product_name,
                "vision": story_input.product_vision or "",
                # Pass forbidden capabilities for LLM validator (best-effort)
                "forbidden_capabilities": forbidden_capabilities,
                # Roadmap context for time-frame validation
                "time_frame": story_input.time_frame,
            }
        ),
        "spec_version_id": story_input.spec_version_id,
        "authority_context": json.dumps(authority_context),
        # Store original feature for drift detection
        "original_feature_title": story_input.feature_title,
        "forbidden_capabilities": json.dumps(forbidden_capabilities),
        "user_persona": story_input.user_persona,
        "story_preferences": json.dumps(
            {
                "include_story_points": story_input.include_story_points,
            }
        ),
        "refinement_feedback": "",  # Empty for first iteration
        "iteration_count": 0,
    }
    if story_input.pass_raw_spec_text:
        # Raw spec text for phrasing only (NON-authoritative)
        initial_state["raw_spec_text"] = technical_spec

    # --- Create session and runner ---
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="story_pipeline",
        user_id="pipeline_user",
        state=initial_state,
    )

    if story_input.enable_story_refiner:
        if story_input.enable_spec_validator:
            agent_to_run = story_validation_loop
        else:
            agent_to_run = SequentialAgent(
                name="StorySequentialNoSpecValidator",
                sub_agents=[
                    SelfHealingAgent(agent=_clone_agent(story_draft_agent), max_retries=3),
                    SelfHealingAgent(agent=_clone_agent(story_refiner_agent), max_retries=3),
                ],
                description="Drafts and refines a story (no spec validator).",
            )
    else:
        agent_to_run = story_draft_agent
    runner = Runner(
        agent=agent_to_run,
        app_name="story_pipeline",
        session_service=session_service,
    )

    # --- Track state changes for verbose output ---
    last_story_draft: Optional[Any] = None
    last_spec_validation_result: Optional[Any] = None
    last_refinement_result: Optional[Any] = None
    last_exit_loop_diagnostic: Optional[Any] = None
    current_iteration: int = 0  # Track locally by counting new drafts
    seen_drafts: Set[int] = set()  # Track unique drafts to count iterations

    # --- Run the pipeline ---
    try:
        # Build the Content object for ADK runner
        prompt_text = f"Generate a user story for feature: {story_input.feature_title}"
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt_text)],
        )

        # The pipeline runs until is_valid=True or max_iterations
        async for _ in runner.run_async(
            user_id="pipeline_user",
            session_id=session.id,
            new_message=new_message,
        ):
            # Check for state updates during streaming
            try:
                current_session = await session_service.get_session(
                    app_name="story_pipeline",
                    user_id="pipeline_user",
                    session_id=session.id,
                )
                if current_session and current_session.state:
                    state = current_session.state

                    # Check for new story draft - use this to track iterations
                    story_draft = state.get("story_draft")
                    if story_draft and story_draft != last_story_draft:
                        # Create a hash to track unique drafts
                        draft_hash = hash(str(story_draft))
                        if draft_hash not in seen_drafts:
                            seen_drafts.add(draft_hash)
                            current_iteration += 1
                            log(
                                f"\n{MAGENTA}   ╭─ Iteration {current_iteration} ─────────────────────────────────╮{RESET}"
                            )

                        last_story_draft = story_draft
                        draft_data: Dict[str, Any] = (
                            story_draft if isinstance(story_draft, dict) else {}
                        )
                        if isinstance(story_draft, str):
                            try:
                                draft_data = json.loads(story_draft)
                            except (json.JSONDecodeError, TypeError):
                                pass

                        # POST-PROCESSING: Strip story_points if include_story_points=False
                        # This ensures LLM output respects user preferences even if LLM didn't follow instructions
                        if not story_input.include_story_points and draft_data.get("story_points") is not None:
                            draft_data["story_points"] = None
                            # Update state to persist the change
                            state["story_draft"] = draft_data

                        if draft_data:
                            _ensure_spec_version_metadata(
                                draft_data,
                                story_input.spec_version_id,
                            )
                            state["story_draft"] = draft_data

                        if draft_data:
                            title = draft_data.get("title", "")
                            desc = draft_data.get("description", "")[:100]
                            log(f"{CYAN}   │ 📝 DRAFT:{RESET}")
                            log(f"{CYAN}   │{RESET}    Title: {title}")
                            log(f"{CYAN}   │{RESET}    Story: {desc}...")
                            # Only display points if include_story_points is enabled
                            if story_input.include_story_points:
                                points = draft_data.get("story_points", "?")
                                log(f"{CYAN}   │{RESET}    Points: {points}")

                    # Check for spec validation result
                    spec_validation_result = state.get("spec_validation_result")
                    if (
                        spec_validation_result
                        and spec_validation_result != last_spec_validation_result
                    ):
                        last_spec_validation_result = spec_validation_result
                        spec_data: Dict[str, Any] = (
                            spec_validation_result
                            if isinstance(spec_validation_result, dict)
                            else {}
                        )
                        if isinstance(spec_validation_result, str):
                            try:
                                spec_data = json.loads(spec_validation_result)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        if spec_data:
                            is_compliant = bool(spec_data.get("is_compliant", True))
                            spec_issues = spec_data.get("issues", [])
                            spec_suggestions = spec_data.get("suggestions", [])
                            domain_compliance = spec_data.get("domain_compliance", {})

                            status_icon = "✅" if is_compliant else "❌"
                            status_color = GREEN if is_compliant else RED
                            log(
                                f"{YELLOW}   │ 🧾 SPEC: {status_color}{status_icon} {'OK' if is_compliant else 'VIOLATION'}{RESET}"
                            )

                            # Show domain compliance details (NEW)
                            if domain_compliance:
                                domain_name = domain_compliance.get("matched_domain", "general")
                                bound_count = domain_compliance.get("bound_requirement_count", 0)
                                satisfied = domain_compliance.get("satisfied_count", 0)
                                critical_gaps = domain_compliance.get("critical_gaps", [])

                                log(f"{YELLOW}   │{RESET}    Domain: {domain_name} ({satisfied}/{bound_count} requirements)")

                                if critical_gaps:
                                    log(f"{RED}   │{RESET}    Critical Gaps ({len(critical_gaps)}):")
                                    for gap in critical_gaps[:3]:  # Show first 3
                                        log(f"{RED}   │{RESET}      ⚠ {gap}")

                            if (not is_compliant) and spec_issues:
                                log(f"{RED}   │{RESET}    Spec issues:")
                                for issue in spec_issues[:3]:  # Show first 3 issues
                                    log(f"{RED}   │{RESET}      • {issue}")

                            if spec_suggestions:
                                log(f"{YELLOW}   │{RESET}    Spec fixes needed:")
                                for sug in spec_suggestions[:3]:  # Show first 3 suggestions
                                    log(f"{YELLOW}   │{RESET}      → {sug}")

                    # Check for exit_loop diagnostics (avoids noisy stdout prints)
                    exit_loop_diag = state.get("exit_loop_diagnostic")
                    if exit_loop_diag and exit_loop_diag != last_exit_loop_diagnostic:
                        last_exit_loop_diagnostic = exit_loop_diag
                        diag_data: Dict[str, Any] = (
                            exit_loop_diag if isinstance(exit_loop_diag, dict) else {}
                        )
                        if isinstance(exit_loop_diag, str):
                            try:
                                diag_data = json.loads(exit_loop_diag)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        if diag_data:
                            loop_exit = bool(diag_data.get("loop_exit", False))
                            blocked_by = diag_data.get("blocked_by")
                            reason = diag_data.get("reason", "")
                            if loop_exit:
                                log(f"{GREEN}   │ 🧰 LOOP EXIT: ready{RESET}")
                            else:
                                log(
                                    f"{YELLOW}   │ 🧰 LOOP EXIT: blocked ({blocked_by}){RESET}"
                                )
                            if reason:
                                log(f"{YELLOW}   │{RESET}      → {reason}")

                    # Check for refinement result
                    refinement_result = state.get("refinement_result")
                    if (
                        refinement_result
                        and refinement_result != last_refinement_result
                    ):
                        last_refinement_result = refinement_result
                        ref_data: Dict[str, Any] = (
                            refinement_result
                            if isinstance(refinement_result, dict)
                            else {}
                        )
                        if isinstance(refinement_result, str):
                            try:
                                ref_data = json.loads(refinement_result)
                            except (json.JSONDecodeError, TypeError):
                                pass
                        if ref_data:
                            is_valid = ref_data.get("is_valid", False)
                            refined = ref_data.get("refined_story", {})
                            notes = ref_data.get("refinement_notes", "")
                            refinement_applied = ref_data.get("refinement_applied", False)

                            status_color = GREEN if is_valid else YELLOW
                            refinement_icon = "🔧" if refinement_applied else "✓"
                            log(f"{status_color}   │ ✨ REFINED: {refinement_icon} {'Changes applied' if refinement_applied else 'No changes'}{RESET}")
                            if refined:
                                title = refined.get('title', '')
                                log(
                                    f"{status_color}   │{RESET}    Title: {title}"
                                )
                                # Show acceptance criteria count
                                # Note: acceptance_criteria is a string (bullets), not a list
                                ac_raw = refined.get('acceptance_criteria', '')
                                if ac_raw:
                                    # Parse bullet-point string into list
                                    ac_list = [line.strip() for line in ac_raw.strip().split('\n') if line.strip().startswith('-')]
                                    log(f"{status_color}   │{RESET}    AC Count: {len(ac_list)} criteria")
                                    # Show first 2 AC to verify spec compliance fixes
                                    for ac in ac_list[:2]:
                                        ac_preview = ac[:60] + "..." if len(ac) > 60 else ac
                                        log(f"{status_color}   │{RESET}      • {ac_preview}")
                            if notes:
                                log(
                                    f"{status_color}   │{RESET}    Notes: {notes[:100]}{'...' if len(notes) > 100 else ''}"
                                )
                            log(
                                f"{MAGENTA}   ╰────────────────────────────────────────────────╯{RESET}"
                            )
            except Exception:
                pass  # Ignore errors during state inspection

        # Extract the final session state
        final_session = await session_service.get_session(
            app_name="story_pipeline",
            user_id="pipeline_user",
            session_id=session.id,
        )

        state = final_session.state if final_session else {}

        # Get the refined story from state
        refinement_result = state.get("refinement_result")
        if refinement_result:
            # Parse if it's a string
            refinement_data: Dict[str, Any]
            if isinstance(refinement_result, str):
                try:
                    refinement_data = json.loads(refinement_result)
                except json.JSONDecodeError:
                    refinement_data = {}
            elif isinstance(refinement_result, dict):
                refinement_data = refinement_result
            else:
                refinement_data = {}

            if refinement_data:
                refined_story: Dict[str, Any] = refinement_data.get("refined_story", {})
                is_valid: bool = bool(refinement_data.get("is_valid", False))
                refinement_notes: str = str(refinement_data.get("refinement_notes", ""))

                # POST-PROCESSING: Add feature_id from input state (prevent LLM override)
                # LLM should not regenerate this - it causes data corruption
                refined_story["feature_id"] = story_input.feature_id
                refined_story["feature_title"] = story_input.feature_title
                _ensure_spec_version_metadata(refined_story, story_input.spec_version_id)

                # POST-PROCESSING: Strip story_points if include_story_points=False
                # This is a safety net in case LLM didn't follow instructions
                if not story_input.include_story_points and refined_story.get("story_points") is not None:
                    refined_story["story_points"] = None

                # --- STEP 3: POST-PIPELINE DETERMINISTIC ALIGNMENT ENFORCEMENT ---
                # This catches cases where LLM validator missed alignment issues
                # and where refiner silently transformed the requirement

                alignment_issues: List[str] = []

                # 3a. Check final story for forbidden capabilities
                story_text = f"{refined_story.get('title', '')} {refined_story.get('description', '')}"
                story_alignment = check_alignment_violation(
                    story_text,
                    forbidden_capabilities,
                    "generated story"
                )
                if not story_alignment.is_aligned:
                    alignment_issues.extend(story_alignment.alignment_issues)
                    log(
                        f"{RED}[Post-Validation]{RESET} Story contains forbidden capabilities:"
                    )
                    for issue in story_alignment.alignment_issues:
                        log(f"   {RED}✗{RESET} {issue}")

                # 3b. Check for requirement drift (feature was silently transformed)
                drift_detected, drift_message = detect_requirement_drift(
                    original_feature=story_input.feature_title,
                    final_story_title=refined_story.get("title", ""),
                    final_story_description=refined_story.get("description", ""),
                    forbidden_capabilities=forbidden_capabilities,
                )
                if drift_detected and drift_message:
                    alignment_issues.append(drift_message)
                    log(f"{RED}[Drift Detection]{RESET} {drift_message}")

                # 3c. DETERMINISTIC PERSONA ENFORCEMENT (Layer 3)
                log(f"{CYAN}[Persona Guard] Validating persona...{RESET}")

                persona_check = validate_persona(
                    story_description=refined_story.get("description", ""),
                    required_persona=story_input.user_persona,
                    allow_synonyms=True,
                )

                if not persona_check.is_valid:
                    log(
                        f"{YELLOW}⚠️  Persona violation: {persona_check.violation_message}{RESET}"
                    )
                    fail_msg = (
                        f"PERSONA ENFORCEMENT FAILED: Required '{story_input.user_persona}', "
                        f"Found '{persona_check.extracted_persona}'"
                    )
                    alignment_issues.append(fail_msg)
                    log(f"{RED}[Fatal Persona Error]{RESET} {fail_msg}")
                else:
                    log(
                        f"{GREEN}✅ Persona validation passed: {story_input.user_persona}{RESET}"
                    )

                # 3d. DETERMINISTIC VETO: If alignment issues found, override LLM's is_valid
                if alignment_issues:
                    log(
                        f"{RED}[Deterministic Veto]{RESET} Overriding LLM validation due to alignment violations"
                    )
                    is_valid = False  # Force invalid regardless of LLM validation

                # Determine status icon and color
                status_icon = "✅" if is_valid else "⚠️"
                status_color = GREEN if is_valid else YELLOW
                if alignment_issues:
                    status_icon = "❌"
                    status_color = RED

                # Use locally tracked iterations (current_iteration) instead of state
                iterations = max(current_iteration, 1)  # At least 1 iteration

                # --- ATTACH METADATA BEFORE CONTRACT ENFORCEMENT ---
                # Theme/epic must be on the story BEFORE contract validation
                # This ensures the contract enforcer can validate the metadata was propagated
                # Include stable IDs if available (eliminates duplicate name ambiguity)
                refined_story["theme"] = story_input.theme
                refined_story["epic"] = story_input.epic
                refined_story["feature_id"] = story_input.feature_id
                refined_story["theme_id"] = story_input.theme_id  # Stable reference
                refined_story["epic_id"] = story_input.epic_id    # Stable reference

                # --- STEP 4: CONTRACT ENFORCEMENT (Final deterministic boundary) ---
                log(f"{CYAN}\n[Contract Enforcer] Running final validation...{RESET}")

                # Ensure refinement_result is a dict for contract enforcer
                refinement_result_dict: Optional[Dict[str, Any]] = None
                if isinstance(refinement_result, dict):
                    refinement_result_dict = refinement_result
                elif isinstance(refinement_result, str):
                    try:
                        refinement_result_dict = json.loads(refinement_result)
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Normalize validation result payloads (can be JSON strings)
                validation_result_payload = state.get("validation_result")
                if isinstance(validation_result_payload, str):
                    try:
                        validation_result_payload = json.loads(validation_result_payload)
                    except (json.JSONDecodeError, TypeError):
                        validation_result_payload = None

                spec_validation_payload = state.get("spec_validation_result")
                if isinstance(spec_validation_payload, str):
                    try:
                        spec_validation_payload = json.loads(spec_validation_payload)
                    except (json.JSONDecodeError, TypeError):
                        spec_validation_payload = None

                contract_result = enforce_story_contracts(
                    story=refined_story,
                    include_story_points=story_input.include_story_points,
                    expected_persona=story_input.user_persona,
                    feature_time_frame=story_input.time_frame,
                    allowed_scope=None,  # TODO: Add scope filtering support
                    validation_result=validation_result_payload,
                    spec_validation_result=spec_validation_payload,
                    refinement_result=refinement_result_dict,
                    expected_feature_id=story_input.feature_id,  # Data integrity check
                    theme=story_input.theme,  # Theme title from feature
                    epic=story_input.epic,    # Epic title from feature
                    theme_id=story_input.theme_id,  # Stable ID reference
                    epic_id=story_input.epic_id,    # Stable ID reference
                    # INVEST validator only runs when BOTH refiner AND spec_validator are enabled
                    invest_validation_expected=(story_input.enable_story_refiner and story_input.enable_spec_validator),
                )

                # Handle three-state contract result: True (pass), False (fail), None (unknown/skipped)
                if contract_result.is_valid is False:
                    # Contract violations found - override LLM validation
                    is_valid = False
                    status_icon = "❌"
                    status_color = RED

                    log(f"{RED}[Contract Enforcer] FAILED - {len(contract_result.violations)} violations{RESET}")
                    log(format_contract_violations(contract_result.violations))
                    # NOTE: Contract violations are NOT alignment issues (alignment = spec authority forbidden capabilities)
                    # Contract violations only affect is_valid, not 'rejected' status
                elif contract_result.is_valid is None:
                    # Validation was skipped (e.g., spec_validator disabled)
                    # Keep is_valid as None to propagate "unknown" state
                    is_valid = None
                    status_icon = "❔"
                    status_color = YELLOW
                    log(f"{YELLOW}[Contract Enforcer] SKIPPED - INVEST validation not run (validator disabled){RESET}")
                    # Use sanitized story
                    refined_story = contract_result.sanitized_story or refined_story
                else:
                    log(f"{GREEN}[Contract Enforcer] PASSED - All contracts satisfied{RESET}")
                    # Use sanitized story (may have stripped forbidden fields)
                    refined_story = contract_result.sanitized_story or refined_story

                log(
                    f"\n{status_color}   {status_icon} FINAL: '{refined_story.get('title', 'Unknown')}' | Iterations: {iterations}{RESET}"
                )

                if alignment_issues:
                    log(f"{RED}   Alignment issues: {len(alignment_issues)}{RESET}")

                # Metadata already attached before contract enforcement
                # Just return the refined_story (which has theme/epic/feature_id)
                return {
                    "success": True,
                    "is_valid": is_valid,
                    "rejected": len(alignment_issues) > 0,  # Mark as rejected if alignment issues
                    "story": refined_story,
                    "iterations": iterations,
                    "refinement_notes": refinement_notes,
                    "alignment_issues": alignment_issues,  # Always include (may be empty)
                    "message": f"Generated story '{refined_story.get('title', 'Unknown')}' "
                    f"(valid={is_valid}, iterations={iterations})"
                    + (f" - REJECTED: {len(alignment_issues)} alignment violations" if alignment_issues else ""),
                }

        # If refiner disabled, synthesize refinement_result from draft
        if not story_input.enable_story_refiner:
            story_draft = state.get("story_draft")
            if isinstance(story_draft, str):
                try:
                    story_draft = json.loads(story_draft)
                except json.JSONDecodeError:
                    story_draft = None

            if isinstance(story_draft, dict):
                _ensure_spec_version_metadata(story_draft, story_input.spec_version_id)
                state["refinement_result"] = {
                    "refined_story": story_draft,
                    "is_valid": True,
                    "refinement_applied": False,
                    "refinement_notes": "Story refiner disabled.",
                }
                refinement_result = state.get("refinement_result")

                # Re-run the standard refined-story path
                if refinement_result:
                    if isinstance(refinement_result, dict):
                        refinement_data = refinement_result
                    else:
                        refinement_data = {}
                    refined_story = refinement_data.get("refined_story", {})
                    is_valid = bool(refinement_data.get("is_valid", False))
                    refinement_notes = str(refinement_data.get("refinement_notes", ""))

                    # POST-PROCESSING: Add feature_id from input state (prevent LLM override)
                    refined_story["feature_id"] = story_input.feature_id
                    refined_story["feature_title"] = story_input.feature_title
                    _ensure_spec_version_metadata(refined_story, story_input.spec_version_id)

                    # POST-PROCESSING: Strip story_points if include_story_points=False
                    if (
                        not story_input.include_story_points
                        and refined_story.get("story_points") is not None
                    ):
                        refined_story["story_points"] = None

                    # --- STEP 3: POST-PIPELINE DETERMINISTIC ALIGNMENT ENFORCEMENT ---
                    alignment_issues: List[str] = []

                    story_text = (
                        f"{refined_story.get('title', '')} {refined_story.get('description', '')}"
                    )
                    story_alignment = check_alignment_violation(
                        story_text,
                        forbidden_capabilities,
                        "generated story",
                    )
                    if not story_alignment.is_aligned:
                        alignment_issues.extend(story_alignment.alignment_issues)
                        log(
                            f"{RED}[Post-Validation]{RESET} Story contains forbidden capabilities:"
                        )
                        for issue in story_alignment.alignment_issues:
                            log(f"   {RED}✗{RESET} {issue}")

                    drift_detected, drift_message = detect_requirement_drift(
                        original_feature=story_input.feature_title,
                        final_story_title=refined_story.get("title", ""),
                        final_story_description=refined_story.get("description", ""),
                        forbidden_capabilities=forbidden_capabilities,
                    )
                    if drift_detected and drift_message:
                        alignment_issues.append(drift_message)
                        log(f"{RED}[Drift Detection]{RESET} {drift_message}")

                    log(f"{CYAN}[Persona Guard] Validating persona...{RESET}")

                    persona_check = validate_persona(
                        story_description=refined_story.get("description", ""),
                        required_persona=story_input.user_persona,
                        allow_synonyms=True,
                    )

                    if not persona_check.is_valid:
                        log(
                            f"{YELLOW}⚠️  Persona violation: {persona_check.violation_message}{RESET}"
                        )
                        fail_msg = (
                            f"PERSONA ENFORCEMENT FAILED: Required '{story_input.user_persona}', "
                            f"Found '{persona_check.extracted_persona}'"
                        )
                        alignment_issues.append(fail_msg)
                        log(f"{RED}[Fatal Persona Error]{RESET} {fail_msg}")
                    else:
                        log(
                            f"{GREEN}✅ Persona validation passed: {story_input.user_persona}{RESET}"
                        )

                    if alignment_issues:
                        log(
                            f"{RED}[Deterministic Veto]{RESET} Overriding LLM validation due to alignment violations"
                        )
                        is_valid = False

                    status_icon = "✅" if is_valid else "⚠️"
                    status_color = GREEN if is_valid else YELLOW
                    if alignment_issues:
                        status_icon = "❌"
                        status_color = RED

                    iterations = max(current_iteration, 1)

                    refined_story["theme"] = story_input.theme
                    refined_story["epic"] = story_input.epic
                    refined_story["feature_id"] = story_input.feature_id
                    refined_story["theme_id"] = story_input.theme_id
                    refined_story["epic_id"] = story_input.epic_id

                    log(f"{CYAN}\n[Contract Enforcer] Running final validation...{RESET}")

                    refinement_result_dict = state.get("refinement_result")

                    validation_result_payload = state.get("validation_result")
                    if isinstance(validation_result_payload, str):
                        try:
                            validation_result_payload = json.loads(validation_result_payload)
                        except (json.JSONDecodeError, TypeError):
                            validation_result_payload = None

                    spec_validation_payload = state.get("spec_validation_result")
                    if isinstance(spec_validation_payload, str):
                        try:
                            spec_validation_payload = json.loads(spec_validation_payload)
                        except (json.JSONDecodeError, TypeError):
                            spec_validation_payload = None

                    contract_result = enforce_story_contracts(
                        story=refined_story,
                        include_story_points=story_input.include_story_points,
                        expected_persona=story_input.user_persona,
                        feature_time_frame=story_input.time_frame,
                        allowed_scope=None,
                        validation_result=validation_result_payload,
                        spec_validation_result=spec_validation_payload,
                        refinement_result=refinement_result_dict,
                        expected_feature_id=story_input.feature_id,
                        theme=story_input.theme,
                        epic=story_input.epic,
                        theme_id=story_input.theme_id,
                        epic_id=story_input.epic_id,
                        # INVEST validator only runs when BOTH refiner AND spec_validator are enabled
                        invest_validation_expected=(story_input.enable_story_refiner and story_input.enable_spec_validator),
                    )

                    # Handle three-state contract result: True (pass), False (fail), None (unknown/skipped)
                    if contract_result.is_valid is False:
                        is_valid = False
                        status_icon = "❌"
                        status_color = RED

                        log(
                            f"{RED}[Contract Enforcer] FAILED - {len(contract_result.violations)} violations{RESET}"
                        )
                        log(format_contract_violations(contract_result.violations))
                        # NOTE: Contract violations are NOT alignment issues (alignment = spec authority forbidden capabilities)
                        # Contract violations only affect is_valid, not 'rejected' status
                    elif contract_result.is_valid is None:
                        # Validation was skipped (e.g., spec_validator disabled)
                        is_valid = None
                        status_icon = "❔"
                        status_color = YELLOW
                        log(f"{YELLOW}[Contract Enforcer] SKIPPED - INVEST validation not run (validator disabled){RESET}")
                        refined_story = (
                            contract_result.sanitized_story or refined_story
                        )
                    else:
                        log(
                            f"{GREEN}[Contract Enforcer] PASSED - All contracts satisfied{RESET}"
                        )
                        refined_story = (
                            contract_result.sanitized_story or refined_story
                        )

                    log(
                        f"\n{status_color}   {status_icon} FINAL: '{refined_story.get('title', 'Unknown')}' | Iterations: {iterations}{RESET}"
                    )

                    if alignment_issues:
                        log(
                            f"{RED}   Alignment issues: {len(alignment_issues)}{RESET}"
                        )

                    return {
                        "success": True,
                        "is_valid": is_valid,
                        "rejected": len(alignment_issues) > 0,
                        "story": refined_story,
                        "iterations": iterations,
                        "refinement_notes": refinement_notes,
                        "alignment_issues": alignment_issues,
                        "message": f"Generated story '{refined_story.get('title', 'Unknown')}' "
                        f"(valid={is_valid}, iterations={iterations})"
                        + (
                            f" - REJECTED: {len(alignment_issues)} alignment violations"
                            if alignment_issues
                            else ""
                        ),
                    }

        # Fallback: try to get story_draft
        story_draft = state.get("story_draft")
        if story_draft:
            if isinstance(story_draft, str):
                try:
                    story_draft = json.loads(story_draft)
                except json.JSONDecodeError:
                    pass

            # Attach metadata to fallback story
            if isinstance(story_draft, dict):
                story_draft["theme"] = story_input.theme
                story_draft["epic"] = story_input.epic
                story_draft["feature_id"] = story_input.feature_id
                _ensure_spec_version_metadata(story_draft, story_input.spec_version_id)

            return {
                "success": True,
                "is_valid": False,
                "story": story_draft if isinstance(story_draft, dict) else {},
                "validation_score": 0,
                "iterations": max(current_iteration, 1),
                "refinement_notes": "Pipeline did not complete validation",
                "message": "Story drafted but validation incomplete",
            }

        return {
            "success": False,
            "error": "Pipeline did not produce a story",
            "state_keys": list(state.keys()) if state else [],
        }

    except Exception as e:
        log(f"   [Pipeline Error] {e}")
        return {
            "success": False,
            "error": f"Pipeline error: {str(e)}",
        }
