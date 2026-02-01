"""Batch story pipeline processing."""

import asyncio
from typing import Annotated, Any, Dict, List, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from agile_sqlmodel import CompiledSpecAuthority, get_engine
from tools.spec_tools import ensure_accepted_spec_authority

from ..product_user_story_tool.tools import FeatureForStory
from .common import load_compiled_authority
from .single_story import ProcessStoryInput, process_single_story

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


class ProcessBatchInput(BaseModel):
    """Input schema for process_story_batch tool."""

    product_id: Annotated[int, Field(description="The product ID.")]
    product_name: Annotated[str, Field(description="The product name.")]
    product_vision: Annotated[
        Optional[str], Field(description="The product vision statement. Defaults to None if not provided.")
    ] = None
    features: Annotated[
        List[FeatureForStory],
        Field(
            description=(
                "List of validated FeatureForStory objects with guaranteed theme/epic fields. "
                "Obtain this from query_features_for_stories tool (do NOT construct manually). "
                "Each feature must have: feature_id, feature_title, theme (min 1 char), epic (min 1 char), "
                "and optional roadmap context: time_frame, theme_justification, sibling_features."
            )
        ),
    ]
    user_persona: Annotated[
        Optional[str],
        Field(
            description="The target user persona for all stories. Defaults to 'user' if not provided.",
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
            description=(
                "Compiled spec version ID to validate against. "
                "OMIT this field unless you have a known valid ID from a previous tool response. "
                "The system will auto-resolve the correct spec version if omitted. "
                "Do NOT make up or guess spec_version_id values."
            ),
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

    max_concurrency: Annotated[
        Optional[int],
        Field(
            ge=1,
            le=10,
            description=(
                "Maximum number of features to process in parallel. "
                "Defaults to 1 for deterministic, in-order logs. Increase for speed."
            ),
        ),
    ] = None


async def process_story_batch(
    batch_input: ProcessBatchInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Process multiple features through the story validation pipeline.

    Each feature is processed ONE AT A TIME through the full pipeline.
    Results are returned for user review. Use `save_validated_stories` to persist.

    NOTE: This function does NOT save to the database. After user confirms,
    call `save_validated_stories` with the validated_stories from this response.
    """
    # --- Apply defaults for optional parameters (moved from schema to runtime) ---
    effective_persona = batch_input.user_persona if batch_input.user_persona is not None else "user"
    effective_include_points = batch_input.include_story_points if batch_input.include_story_points is not None else True
    effective_recompile = batch_input.recompile if batch_input.recompile is not None else False
    effective_enable_refiner = batch_input.enable_story_refiner if batch_input.enable_story_refiner is not None else True
    effective_max_concurrency = batch_input.max_concurrency if batch_input.max_concurrency is not None else 1

    # --- Resolve spec_version_id with validation ---
    effective_spec_version_id = batch_input.spec_version_id

    # Validate that provided spec_version_id actually exists
    if effective_spec_version_id:
        with Session(get_engine()) as check_session:
            exists = check_session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == effective_spec_version_id
                )
            ).first()
            if not exists:
                print(f"{YELLOW}[WARN] Provided spec_version_id={effective_spec_version_id} not found, auto-resolving...{RESET}")
                effective_spec_version_id = None  # Fall back to auto-resolution

    if not effective_spec_version_id:
        spec_content = batch_input.spec_content
        content_ref = batch_input.content_ref
        if tool_context and tool_context.state:
            spec_content = spec_content or tool_context.state.get("pending_spec_content")
            content_ref = content_ref or tool_context.state.get("pending_spec_path")

        # Authority gate requires exactly one of spec_content or content_ref.
        # If both are set, prefer content_ref (file path) as the canonical source.
        if spec_content and content_ref:
            spec_content = None

        effective_spec_version_id = ensure_accepted_spec_authority(
            batch_input.product_id,
            spec_content=spec_content,
            content_ref=content_ref,
            recompile=effective_recompile,
            tool_context=tool_context,
        )

    # --- Fetch technical spec by spec_version_id (no fallbacks) ---
    with Session(get_engine()) as db_session:
        try:
            _, _, technical_spec = load_compiled_authority(
                session=db_session,
                product_id=batch_input.product_id,
                spec_version_id=effective_spec_version_id,
            )
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
            }
        print(
            f"{CYAN}[Spec]{RESET} Loaded technical specification "
            f"(~{len(technical_spec) // 4} tokens)"
        )

    print(f"\n{CYAN}{'═' * 60}{RESET}")
    print(f"{CYAN}{BOLD}  INVEST-VALIDATED STORY PIPELINE{RESET}")
    print(
        f"{CYAN}  Processing {len(batch_input.features)} features for '{batch_input.product_name}'{RESET}"
    )
    print(
        f"{CYAN}  Persona: {effective_persona[:50]}...{RESET}"
        if len(effective_persona) > 50
        else f"{CYAN}  Persona: {effective_persona}{RESET}"
    )
    print(f"{CYAN}  Spec: ✓ Available ({len(technical_spec)} chars){RESET}")
    print(f"{CYAN}{'═' * 60}{RESET}")

    validated_stories: List[Dict[str, Any]] = []
    failed_stories: List[Dict[str, Any]] = []
    total_iterations: int = 0

    # Synchronization primitives
    semaphore = asyncio.Semaphore(effective_max_concurrency)
    console_lock = asyncio.Lock()

    async def process_story_safe(idx: int, feature: FeatureForStory) -> Any:
        logs: List[str] = []

        def log_capture(msg: str):
            logs.append(msg)

        # Pre-buffer the header
        log_capture(
            f"\n{YELLOW}[{idx + 1}/{len(batch_input.features)}]{RESET} {BOLD}{feature.feature_title}{RESET}"
        )

        result = None
        try:
            async with semaphore:
                result = await process_single_story(
                    ProcessStoryInput(
                        product_id=batch_input.product_id,
                        product_name=batch_input.product_name,
                        product_vision=batch_input.product_vision,
                        feature_id=feature.feature_id,
                        feature_title=feature.feature_title,
                        # Stable ID references (preferred for validation)
                        theme_id=feature.theme_id,  # Immutable from source
                        epic_id=feature.epic_id,    # Immutable from source
                        # Title references (guaranteed non-empty by FeatureForStory)
                        theme=feature.theme,
                        epic=feature.epic,
                        user_persona=effective_persona,
                        include_story_points=effective_include_points,
                        # Roadmap context (optional)
                        time_frame=feature.time_frame,
                        theme_justification=feature.theme_justification,
                        sibling_features=feature.sibling_features,
                        # Spec version required for validation
                        spec_version_id=effective_spec_version_id,
                        enable_story_refiner=effective_enable_refiner,
                    ),
                    output_callback=log_capture,
                    tool_context=tool_context,
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
                    "feature_id": feature.feature_id,
                    "feature_title": feature.feature_title,
                    "error": str(result),
                    "error_type": type(result).__name__,
                }
            )
            continue

        # Check for dict errors returned by process_single_story
        # Correction: Explicitly check for 'rejected' flag. "is_valid" might be True (LLM)
        # but rejected by post-validation constraints (alignment, drift, etc.)
        if (
            isinstance(result, dict)
            and result.get("success")
            and result.get("is_valid")
            and not result.get("rejected")
        ):
            validated_stories.append(
                {
                    "feature_id": feature.feature_id,
                    "feature_title": feature.feature_title,
                    "story": result["story"],
                    "iterations": result.get("iterations", 1),
                }
            )
            total_iterations += result.get("iterations", 1)
        else:
            # Handle rejection or partial failure
            error_msg = "Validation failed"
            partial = {}
            if isinstance(result, dict):
                if result.get("rejected"):
                    issues = result.get("alignment_issues", [])
                    error_msg = (
                        f"Alignment/Constraint Rejection: {issues[0]}"
                        if issues
                        else "Rejected by constraints"
                    )
                else:
                    error_msg = result.get("error", "Validation failed")
                partial = result.get("story", {})

            failed_stories.append(
                {
                    "feature_id": feature.feature_id,
                    "feature_title": feature.feature_title,
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

    # --- Store validated stories in session state for save_validated_stories fallback ---
    if tool_context and validated_stories:
        # Prepare stories in the format expected by save_validated_stories
        stories_for_save = [
            {
                "feature_id": vs.get("feature_id"),
                "title": vs.get("story", {}).get("title"),
                "description": vs.get("story", {}).get("description"),
                "acceptance_criteria": vs.get("story", {}).get("acceptance_criteria"),
                "story_points": vs.get("story", {}).get("story_points"),
            }
            for vs in validated_stories
        ]
        tool_context.state["pending_validated_stories"] = stories_for_save
        tool_context.state["pending_product_id"] = batch_input.product_id
        tool_context.state["pending_spec_version_id"] = effective_spec_version_id
        print(f"{CYAN}[STATE] Stored {len(stories_for_save)} stories in session state for save_validated_stories{RESET}")

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
