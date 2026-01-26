# orchestrator_agent/agent_tools/story_pipeline/tools.py
"""
Tools for orchestrator to invoke the story validation pipeline.

These tools handle:
1. Setting up state for a single story
2. Running the pipeline
3. Extracting the validated story
4. Batch processing multiple features
5. Deterministic alignment enforcement (vision constraint checking)
"""

import asyncio
import json
from typing import Annotated, Any, Callable, Dict, List, Optional, Set

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from agile_sqlmodel import UserStory, engine, ProductPersona, Product
from orchestrator_agent.agent_tools.story_pipeline.pipeline import (
    story_validation_loop,
)
from orchestrator_agent.agent_tools.story_pipeline.alignment_checker import (
    extract_forbidden_capabilities,
    validate_feature_alignment,
    check_alignment_violation,
    detect_requirement_drift,
    create_rejection_response,
)
from orchestrator_agent.agent_tools.story_pipeline.story_contract_enforcer import (
    enforce_story_contracts,
    format_contract_violations,
)
from orchestrator_agent.agent_tools.story_pipeline.persona_checker import (
    validate_persona,
    auto_correct_persona,
    extract_persona_from_story,
    normalize_persona,
)

# --- Schema for single story processing ---


class ProcessStoryInput(BaseModel):
    """Input schema for process_single_story tool."""

    product_id: Annotated[int, Field(description="The product ID.")]
    product_name: Annotated[str, Field(description="The product name.")]
    product_vision: Annotated[
        Optional[str], Field(default=None, description="The product vision statement.")
    ]
    feature_id: Annotated[
        int, Field(description="The feature ID to create a story for.")
    ]
    feature_title: Annotated[str, Field(description="The feature title.")]
    theme: Annotated[str, Field(description="The theme this feature belongs to.")]
    epic: Annotated[str, Field(description="The epic this feature belongs to.")]
    # NEW: Roadmap context fields for strategic awareness
    time_frame: Annotated[
        Optional[str],
        Field(
            default=None,
            description="The roadmap time frame: 'Now', 'Next', or 'Later'.",
        ),
    ]
    theme_justification: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Strategic justification for why this theme exists.",
        ),
    ]
    sibling_features: Annotated[
        Optional[List[str]],
        Field(
            default=None,
            description="Other features in the same theme (for context).",
        ),
    ]
    user_persona: Annotated[
        str,
        Field(
            default="user",
            description="The target user persona for the story.",
        ),
    ]
    include_story_points: Annotated[
        bool,
        Field(
            default=True,
            description="Whether to include story point estimates.",
        ),
    ]
    technical_spec: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Technical specification document for domain context.",
        ),
    ]


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
) -> Dict[str, Any]:
    """
    Process a single feature through the story validation pipeline.

    This tool:
    1. Validates feature alignment with product vision (FAIL-FAST on violations)
    2. Sets up initial state with feature context + forbidden capabilities
    3. Runs the LoopAgent pipeline (Draft → Validate → Refine)
    4. Applies deterministic post-validation (catches LLM misses + drift)
    5. Returns the validated story or rejection

    The pipeline will loop up to 3 times until a valid story is produced.
    """

    # --- Helper for logging ---
    def log(msg: str):
        if output_callback:
            output_callback(msg)
        else:
            print(msg)

    # --- ANSI colors for terminal output ---
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    log(
        f"\n{CYAN}[Pipeline]{RESET} Processing feature: {BOLD}'{story_input.feature_title}'{RESET}"
    )
    log(f"{DIM}   Theme: {story_input.theme} | Epic: {story_input.epic}{RESET}")

    # --- STEP 0: Fail-Fast Persona Whitelist Check ---
    with Session(engine) as session:
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

    # --- STEP 1: Extract forbidden capabilities from vision ---
    forbidden_capabilities = extract_forbidden_capabilities(story_input.product_vision)
    if forbidden_capabilities:
        log(
            f"{YELLOW}[Constraints]{RESET} Forbidden capabilities detected: {forbidden_capabilities}"
        )

    # --- STEP 2: FAIL-FAST - Check feature alignment BEFORE running pipeline ---
    # This catches obvious violations early (e.g., "web dashboard" for mobile-only app)
    feature_alignment = validate_feature_alignment(
        story_input.feature_title, story_input.product_vision
    )

    if not feature_alignment.is_aligned:
        log(f"{RED}[Alignment REJECTED]{RESET} Feature violates product vision:")
        for issue in feature_alignment.alignment_issues:
            log(f"   {RED}✗{RESET} {issue}")

        # Return rejection response - do NOT run the pipeline
        return create_rejection_response(
            feature_title=story_input.feature_title,
            alignment_issues=feature_alignment.alignment_issues,
            product_vision=story_input.product_vision,
        )

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
        # Technical specification for domain context (optional)
        "technical_spec": story_input.technical_spec or "",
    }

    # --- Create session and runner ---
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name="story_pipeline",
        user_id="pipeline_user",
        state=initial_state,
    )

    runner = Runner(
        agent=story_validation_loop,
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

                    # Attempt auto-correction
                    refined_story = auto_correct_persona(
                        refined_story, story_input.user_persona
                    )
                    log(
                        f"{GREEN}✅ Auto-corrected persona to: {story_input.user_persona}{RESET}"
                    )

                    # Re-validate
                    recheck = validate_persona(
                        refined_story.get("description", ""), story_input.user_persona
                    )
                    if not recheck.is_valid:
                        # Fail hard if we can't correct it
                        # Instead of raising, we treat it as an alignment failure to keep the flow
                        fail_msg = (
                            f"PERSONA ENFORCEMENT FAILED: Required '{story_input.user_persona}', "
                            f"Found '{recheck.extracted_persona}'"
                        )
                        alignment_issues.append(fail_msg)
                        log(f"{RED}[Fatal Persona Error]{RESET} {fail_msg}")
                    else:
                        log(f"{GREEN}✅ Persona validation passed after correction{RESET}")
                else:
                    log(
                        f"{GREEN}✅ Persona validation passed: {story_input.user_persona}{RESET}"
                    )

                # 3d. DETERMINISTIC VETO: If alignment issues found, override LLM's is_valid
                if alignment_issues:
                    log(
                        f"{RED}[Deterministic Veto]{RESET} Overriding LLM validation due to alignment violations"
                    )
                    is_valid = False  # Force invalid regardless of LLM score

                # Final summary
                # Note: validation_result no longer exists (INVEST Validator removed)
                # Score defaults to None to indicate "not applicable"
                final_score: Optional[int] = None
                if isinstance(state.get("validation_result"), dict):
                    final_score = state.get("validation_result", {}).get(
                        "validation_score", None
                    )
                elif isinstance(state.get("validation_result"), str):
                    try:
                        val = json.loads(state.get("validation_result", "{}"))
                        final_score = val.get("validation_score", None)
                    except (json.JSONDecodeError, TypeError):
                        pass

                # If deterministic veto applied, cap the score
                if alignment_issues and final_score is not None:
                    final_score = min(
                        final_score, 40
                    )  # Cap at 40 for alignment violations

                status_icon = "✅" if is_valid else "⚠️"
                status_color = GREEN if is_valid else YELLOW
                if alignment_issues:
                    status_icon = "❌"
                    status_color = RED

                # Use locally tracked iterations (current_iteration) instead of state
                iterations = max(current_iteration, 1)  # At least 1 iteration
                
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
                
                contract_result = enforce_story_contracts(
                    story=refined_story,
                    include_story_points=story_input.include_story_points,
                    expected_persona=story_input.user_persona,
                    feature_time_frame=story_input.time_frame,
                    allowed_scope=None,  # TODO: Add scope filtering support
                    validation_result=state.get("validation_result"),
                    spec_validation_result=state.get("spec_validation_result"),
                    refinement_result=refinement_result_dict,
                    expected_feature_id=story_input.feature_id,  # Data integrity check
                )
                
                if not contract_result.is_valid:
                    # Contract violations found - override LLM validation
                    is_valid = False
                    if final_score is not None:
                        final_score = min(final_score, 30)  # Cap at 30 for contract failures
                    status_icon = "❌"
                    status_color = RED
                    
                    log(f"{RED}[Contract Enforcer] FAILED - {len(contract_result.violations)} violations{RESET}")
                    log(format_contract_violations(contract_result.violations))
                    
                    # Add contract violations to alignment issues for reporting
                    for violation in contract_result.violations:
                        alignment_issues.append(f"[{violation.rule}] {violation.message}")
                else:
                    log(f"{GREEN}[Contract Enforcer] PASSED - All contracts satisfied{RESET}")
                    # Use sanitized story (may have stripped forbidden fields)
                    refined_story = contract_result.sanitized_story or refined_story
                
                # Format score display (N/A if no INVEST validation)
                score_display = f"{final_score}/100" if final_score is not None else "N/A"
                
                log(
                    f"\n{status_color}   {status_icon} FINAL: '{refined_story.get('title', 'Unknown')}' | Score: {score_display} | Iterations: {iterations}{RESET}"
                )

                if alignment_issues:
                    log(f"{RED}   Alignment issues: {len(alignment_issues)}{RESET}")

                return {
                    "success": True,
                    "is_valid": is_valid, if final_score is not None else 0,  # Default to 0 for backward compatibility
                    "rejected": len(alignment_issues) > 0,  # Mark as rejected if alignment issues
                    "story": refined_story,
                    "validation_score": final_score,
                    "iterations": iterations,
                    "refinement_notes": refinement_notes,
                    "alignment_issues": alignment_issues,  # Always include (may be empty)
                    "message": f"Generated story '{refined_story.get('title', 'Unknown')}' "
                    f"(valid={is_valid}, iterations={iterations})"
                    + (f" - REJECTED: {len(alignment_issues)} alignment violations" if alignment_issues else ""),
                }

        # Fallback: try to get story_draft
        story_draft = state.get("story_draft")
        if story_draft:
            if isinstance(story_draft, str):
                try:
                    story_draft = json.loads(story_draft)
                except json.JSONDecodeError:
                    pass

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


# --- Schema for batch processing ---


class ProcessBatchInput(BaseModel):
    """Input schema for process_story_batch tool."""

    product_id: Annotated[int, Field(description="The product ID.")]
    product_name: Annotated[str, Field(description="The product name.")]
    product_vision: Annotated[
        Optional[str], Field(default=None, description="The product vision statement.")
    ]
    features: Annotated[
        List[Dict[str, Any]],
        Field(
            description=(
                "List of feature dicts with: feature_id, feature_title, theme, epic, "
                "and optional roadmap context: time_frame, theme_justification, sibling_features"
            )
        ),
    ]
    user_persona: Annotated[
        str,
        Field(
            default="user",
            description="The target user persona for all stories.",
        ),
    ]
    include_story_points: Annotated[
        bool,
        Field(
            default=True,
            description="Whether to include story point estimates.",
        ),
    ]
    technical_spec: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Technical specification document for domain context. If not provided, will be fetched from DB.",
        ),
    ]

    max_concurrency: Annotated[
        int,
        Field(
            default=1,
            ge=1,
            le=10,
            description=(
                "Maximum number of features to process in parallel. "
                "Default is 1 for deterministic, in-order logs. Increase for speed."
            ),
        ),
    ]


async def process_story_batch(batch_input: ProcessBatchInput) -> Dict[str, Any]:
    """
    Process multiple features through the story validation pipeline.

    Each feature is processed ONE AT A TIME through the full pipeline.
    Results are returned for user review. Use `save_validated_stories` to persist.

    NOTE: This function does NOT save to the database. After user confirms,
    call `save_validated_stories` with the validated_stories from this response.
    """
    # --- ANSI colors for terminal output ---
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    # --- Fetch technical spec from DB if not provided ---
    technical_spec = batch_input.technical_spec
    if technical_spec is None:
        with Session(engine) as db_session:
            product = db_session.get(Product, batch_input.product_id)
            if product and product.technical_spec:
                technical_spec = product.technical_spec
                print(f"{CYAN}[Spec]{RESET} Loaded technical specification (~{len(technical_spec) // 4} tokens)")

    print(f"\n{CYAN}{'═' * 60}{RESET}")
    print(f"{CYAN}{BOLD}  INVEST-VALIDATED STORY PIPELINE{RESET}")
    print(
        f"{CYAN}  Processing {len(batch_input.features)} features for '{batch_input.product_name}'{RESET}"
    )
    print(
        f"{CYAN}  Persona: {batch_input.user_persona[:50]}...{RESET}"
        if len(batch_input.user_persona) > 50
        else f"{CYAN}  Persona: {batch_input.user_persona}{RESET}"
    )
    if technical_spec:
        print(f"{CYAN}  Spec: ✓ Available ({len(technical_spec)} chars){RESET}")
    else:
        print(f"{YELLOW}  Spec: ✗ Not available (stories generated from feature titles only){RESET}")
    print(f"{CYAN}{'═' * 60}{RESET}")

    validated_stories: List[Dict[str, Any]] = []
    failed_stories: List[Dict[str, Any]] = []
    total_iterations: int = 0

    # Synchronization primitives
    semaphore = asyncio.Semaphore(batch_input.max_concurrency)
    console_lock = asyncio.Lock()

    async def process_story_safe(idx: int, feature: Dict[str, Any]) -> Any:
        logs: List[str] = []

        def log_capture(msg: str):
            logs.append(msg)

        # Pre-buffer the header
        log_capture(
            f"\n{YELLOW}[{idx + 1}/{len(batch_input.features)}]{RESET} {BOLD}{feature.get('feature_title', 'Unknown')}{RESET}"
        )

        result = None
        try:
            async with semaphore:
                result = await process_single_story(
                    ProcessStoryInput(
                        product_id=batch_input.product_id,
                        product_name=batch_input.product_name,
                        product_vision=batch_input.product_vision,
                        feature_id=feature["feature_id"],
                        feature_title=feature["feature_title"],
                        theme=feature.get("theme", "Unknown"),
                        epic=feature.get("epic", "Unknown"),
                        user_persona=batch_input.user_persona,
                        include_story_points=batch_input.include_story_points,
                        # Roadmap context (optional)
                        time_frame=feature.get("time_frame"),
                        theme_justification=feature.get("theme_justification"),
                        sibling_features=feature.get("sibling_features"),
                        # Technical spec for domain context
                        technical_spec=technical_spec,
                    ),
                    output_callback=log_capture,
                )
        except Exception as e:
            result = e
            log_capture(f"{RED}   [Error]{RESET} {str(e)}")

        # Atomically print logs
        async with console_lock:
            for line in logs:
                print(line)

        return result

    # Execute in parallel
    results = await asyncio.gather(
        *[
            process_story_safe(idx, feature)
            for idx, feature in enumerate(batch_input.features)
        ],
        return_exceptions=True,
    )

    for idx, feature in enumerate(batch_input.features):
        result = results[idx]

        if isinstance(result, Exception):
            failed_stories.append(
                {
                    "feature_id": feature["feature_id"],
                    "feature_title": feature["feature_title"],
                    "error": str(result),
                    "error_type": type(result).__name__,
                }
            )
            continue

        # Check for dict errors returned by process_single_story
        if isinstance(result, dict) and result.get("success") and result.get("is_valid"):
            validated_stories.append(
                {
                    "feature_id": feature["feature_id"],
                    "feature_title": feature["feature_title"],
                    "story": result["story"],
                    "validation_score": result.get("validation_score", 0),
                    "iterations": result.get("iterations", 1),
                }
            )
            total_iterations += result.get("iterations", 1)
        else:
            # Handle rejection or partial failure
            error_msg = "Validation failed"
            partial = {}
            if isinstance(result, dict):
                error_msg = result.get("error", "Validation failed")
                partial = result.get("story", {})

            failed_stories.append(
                {
                    "feature_id": feature["feature_id"],
                    "feature_title": feature["feature_title"],
                    "error": error_msg,
                    "partial_story": partial,
                }
            )

    # --- Summary ---
    print(f"\n{CYAN}{'═' * 60}{RESET}")
    print(f"{CYAN}{BOLD}  PIPELINE SUMMARY{RESET}")
    print(f"{GREEN}  ✅ Validated: {len(validated_stories)}{RESET}")
    print(f"{RED}  ❌ Failed: {len(failed_stories)}{RESET}")
    if validated_stories:
        avg_iter = total_iterations / len(validated_stories)
        print(f"{CYAN}  📊 Avg iterations: {avg_iter:.1f}{RESET}")
    print(f"{CYAN}{'═' * 60}{RESET}")

    return {
        "success": True,
        "total_features": len(batch_input.features),
        "validated_count": len(validated_stories),
        "failed_count": len(failed_stories),
        "average_iterations": (
            total_iterations / len(validated_stories) if validated_stories else 0
        ),
        "validated_stories": validated_stories,
        "failed_stories": failed_stories,
        "message": f"Processed {len(batch_input.features)} features: "
        f"{len(validated_stories)} validated, {len(failed_stories)} failed",
    }


# --- Schema for saving already-validated stories ---


class SaveStoriesInput(BaseModel):
    """Input schema for save_validated_stories tool."""

    product_id: Annotated[int, Field(description="The product ID.")]
    stories: Annotated[
        List[Dict[str, Any]],
        Field(
            description=(
                "List of already-validated story dicts. Each must have: "
                "feature_id, title, description, acceptance_criteria, story_points"
            )
        ),
    ]


async def save_validated_stories(save_input: SaveStoriesInput) -> Dict[str, Any]:
    """
    Save already-validated stories to the database WITHOUT re-running the pipeline.

    Use this tool when:
    - Stories have already been generated and shown to the user
    - User confirms they want to save them
    - NO need to regenerate - just persist what was already created

    This saves API calls and ensures the exact stories shown are saved.
    """
    # --- ANSI colors for terminal output ---
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    RESET = "\033[0m"

    print(
        f"\n{CYAN}Saving {len(save_input.stories)} validated stories to database...{RESET}"
    )

    saved_ids: List[int] = []
    failed_saves: List[Dict[str, Any]] = []

    try:
        with Session(engine) as session:
            for story_data in save_input.stories:
                try:
                    description = story_data.get("description", "")
                    user_story = UserStory(
                        title=story_data.get("title", "Untitled"),
                        story_description=description,
                        # Auto-extract persona for denormalized field
                        persona=extract_persona_from_story(description),
                        acceptance_criteria=story_data.get("acceptance_criteria"),
                        story_points=story_data.get("story_points"),
                        feature_id=story_data.get("feature_id"),
                        product_id=save_input.product_id,
                    )
                    session.add(user_story)
                    session.commit()
                    session.refresh(user_story)
                    saved_ids.append(user_story.story_id)
                    print(
                        f"   {GREEN}✓{RESET} Saved story ID: {user_story.story_id} - {story_data.get('title', '')[:40]}"
                    )
                except SQLAlchemyError as e:
                    failed_saves.append(
                        {
                            "title": story_data.get("title", "Unknown"),
                            "error": str(e),
                        }
                    )
                    print(
                        f"   {RED}✗{RESET} Failed: {story_data.get('title', '')[:40]} - {e}"
                    )
    except SQLAlchemyError as e:
        print(f"   {RED}[DB Error]{RESET} {e}")
        return {
            "success": False,
            "error": f"Database error: {str(e)}",
            "saved_story_ids": saved_ids,
        }

    return {
        "success": True,
        "saved_count": len(saved_ids),
        "failed_count": len(failed_saves),
        "saved_story_ids": saved_ids,
        "failed_saves": failed_saves,
        "message": f"Saved {len(saved_ids)} stories to database"
        + (f" ({len(failed_saves)} failed)" if failed_saves else ""),
    }
