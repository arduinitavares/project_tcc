"""Batch story pipeline processing."""

import asyncio
import logging
from typing import Annotated, Any, Dict, List, Optional, cast, Tuple

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from agile_sqlmodel import CompiledSpecAuthority, get_engine, Product, Theme, Epic
from tools.spec_tools import ensure_accepted_spec_authority
from tools.story_query_tools import FeatureForStory
from .common import load_compiled_authority
from .single_story import ProcessStoryInput, process_single_story

# Configure logger
logger = logging.getLogger(__name__)


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
        str,
        Field(
            description="The target user persona for all stories. Defaults to 'user' if not provided.",
            default="user",
        ),
    ]
    include_story_points: Annotated[
        bool,
        Field(
            description="Whether to include story point estimates. Defaults to True if not provided.",
            default=True,
        ),
    ]
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
        bool,
        Field(
            description="Force recompile even if authority cache exists. Defaults to False if not provided.",
            default=False,
        ),
    ]
    enable_story_refiner: Annotated[
        bool,
        Field(
            description="Whether to run the story refiner loop (A/B testing). Defaults to True if not provided.",
            default=True,
        ),
    ]

    max_concurrency: Annotated[
        int,
        Field(
            ge=1,
            le=10,
            description=(
                "Maximum number of features to process in parallel. "
                "Defaults to 1 for deterministic, in-order logs. Increase for speed."
            ),
            default=1,
        ),
    ]


def _resolve_effective_spec_version_id(
    batch_input: ProcessBatchInput, tool_context: Optional[ToolContext]
) -> int:
    """Resolve the effective spec version ID, performing lookups and auto-resolution if needed."""
    effective_spec_version_id = batch_input.spec_version_id

    # Validate provided spec_version_id
    if effective_spec_version_id:
        with Session(get_engine()) as check_session:
            exists = check_session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == effective_spec_version_id
                )
            ).first()
            if not exists:
                logger.warning(
                    "Provided spec_version_id=%s not found, auto-resolving...",
                    effective_spec_version_id
                )
                effective_spec_version_id = None

    if not effective_spec_version_id:
        spec_content = batch_input.spec_content
        content_ref = batch_input.content_ref

        # Auto-resolve from Product if neither spec_content nor content_ref provided
        if not spec_content and not content_ref:
            with Session(get_engine()) as session:
                product = session.exec(
                    select(Product).where(Product.product_id == batch_input.product_id)
                ).first()
                if product:
                    if product.spec_file_path:
                        logger.info("Auto-resolved spec from product: %s", product.spec_file_path)
                        content_ref = product.spec_file_path
                    elif product.technical_spec:
                        logger.info("Auto-resolved spec content from product DB")
                        spec_content = product.technical_spec

        # Fallback to ToolContext state
        if tool_context and tool_context.state:
            spec_content = spec_content or tool_context.state.get("pending_spec_content")
            content_ref = content_ref or tool_context.state.get("pending_spec_path")

        # Authority gate input rule: prefer content_ref
        if spec_content and content_ref:
            spec_content = None

        effective_spec_version_id = ensure_accepted_spec_authority(
            batch_input.product_id,
            spec_content=spec_content,
            content_ref=content_ref,
            recompile=batch_input.recompile,
            tool_context=tool_context,
        )

    return effective_spec_version_id


def _load_technical_spec(product_id: int, spec_version_id: int) -> str:
    """Load the technical spec content for the given version."""
    with Session(get_engine()) as session:
        _, _, technical_spec = load_compiled_authority(
            session=session,
            product_id=product_id,
            spec_version_id=spec_version_id,
        )
    return technical_spec


def _build_theme_epic_lookup(product_id: int) -> Tuple[Dict[str, int], Dict[Tuple[int, str], int]]:
    """Build lookup maps for themes and epics."""
    theme_map: Dict[str, int] = {}
    epic_lookup: Dict[Tuple[int, str], int] = {}

    with Session(get_engine()) as session:
        themes = session.exec(select(Theme).where(Theme.product_id == product_id)).all()
        theme_map = {t.title: t.theme_id for t in themes}

        if themes:
            theme_ids = [t.theme_id for t in themes]
            epics = session.exec(select(Epic).where(Epic.theme_id.in_(theme_ids))).all()
            epic_lookup = {(e.theme_id, e.title): e.epic_id for e in epics}

    return theme_map, epic_lookup


def _classify_story_result(
    feature: FeatureForStory, result: Any
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], int]:
    """
    Classify the result of processing a single story.
    Returns: (validated_entry, failed_entry, iterations)
    """
    iterations = 0
    if isinstance(result, Exception):
        return None, {
            "feature_id": feature.feature_id,
            "feature_title": feature.feature_title,
            "error": str(result),
            "error_type": type(result).__name__,
        }, iterations

    story_result = cast(Dict[str, Any], result) if isinstance(result, dict) else {}
    iterations = story_result.get("iterations", 1)

    # Check for success AND validity AND not rejected
    if (
        isinstance(result, dict)
        and story_result.get("success")
        and story_result.get("is_valid")
        and not story_result.get("rejected")
    ):
        return {
            "feature_id": feature.feature_id,
            "feature_title": feature.feature_title,
            "story": story_result["story"],
            "iterations": iterations,
        }, None, iterations

    # Handle rejection or partial failure
    error_msg = "Validation failed"
    partial = {}

    if isinstance(result, dict):
        if story_result.get("rejected"):
            issues = story_result.get("alignment_issues", [])
            error_msg = (
                f"Alignment/Constraint Rejection: {issues[0]}"
                if issues
                else "Rejected by constraints"
            )
        else:
            error_msg = story_result.get("error", "Validation failed")
        partial = story_result.get("story", {})

    return None, {
        "feature_id": feature.feature_id,
        "feature_title": feature.feature_title,
        "error": error_msg,
        "partial_story": partial,
    }, iterations


async def process_story_batch(
    batch_input: ProcessBatchInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Process multiple features through the story validation pipeline.

    Each feature is processed ONE AT A TIME through the full pipeline.
    Results are returned for user review. Use `save_validated_stories` to persist.
    """
    try:
        effective_spec_version_id = _resolve_effective_spec_version_id(batch_input, tool_context)
    except Exception as e:
         return {
            "success": False,
            "error": str(e),
        }

    try:
        technical_spec = _load_technical_spec(batch_input.product_id, effective_spec_version_id)
        logger.info(
            "Loaded technical specification (~%d tokens)", len(technical_spec) // 4
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    logger.info("Starting INVEST-Validated Story Pipeline for product '%s'", batch_input.product_name)
    logger.info("Processing %d features", len(batch_input.features))

    theme_map, epic_lookup = _build_theme_epic_lookup(batch_input.product_id)

    validated_stories: List[Dict[str, Any]] = []
    failed_stories: List[Dict[str, Any]] = []
    total_iterations: int = 0

    semaphore = asyncio.Semaphore(batch_input.max_concurrency)

    async def process_story_safe(idx: int, feature: FeatureForStory) -> Any:
        def log_capture(msg: str):
             # Just debug log the internal pipeline logs, don't bubble them to console
             # unless configured. The prompt says "keep it reasonably quiet".
             # We rely on the returned structure for detailed info.
             logger.debug("[%s] %s", feature.feature_title, msg)

        # Resolve IDs if missing (Robustness Fix)
        # Even though FeatureForStory types theme_id/epic_id as int (required),
        # we check for None to handle potential runtime bypass or legacy data.
        resolved_theme_id = feature.theme_id
        if resolved_theme_id is None and feature.theme in theme_map:
            resolved_theme_id = theme_map[feature.theme]
            
        resolved_epic_id = feature.epic_id
        if resolved_epic_id is None and resolved_theme_id is not None:
            if (resolved_theme_id, feature.epic) in epic_lookup:
                resolved_epic_id = epic_lookup[(resolved_theme_id, feature.epic)]

        try:
            async with semaphore:
                logger.info("[%d/%d] Processing feature: %s", idx + 1, len(batch_input.features), feature.feature_title)
                return await process_single_story(
                    ProcessStoryInput(
                        product_id=batch_input.product_id,
                        product_name=batch_input.product_name,
                        product_vision=batch_input.product_vision,
                        feature_id=feature.feature_id,
                        feature_title=feature.feature_title,
                        theme_id=resolved_theme_id,
                        epic_id=resolved_epic_id,
                        theme=feature.theme,
                        epic=feature.epic,
                        user_persona=batch_input.user_persona,
                        include_story_points=batch_input.include_story_points,
                        time_frame=feature.time_frame,
                        theme_justification=feature.theme_justification,
                        sibling_features=feature.sibling_features,
                        spec_version_id=effective_spec_version_id,
                        enable_story_refiner=batch_input.enable_story_refiner,
                    ),
                    output_callback=log_capture,
                    tool_context=tool_context,
                )
        except Exception as e:
            return e

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
        validated, failed, iterations = _classify_story_result(feature, result)
        
        if validated:
            validated_stories.append(validated)
            total_iterations += iterations
        else:
            if failed:
                failed_stories.append(failed)

    # Summary Log
    logger.info(
        "Pipeline Summary: Validated: %d, Failed: %d",
        len(validated_stories),
        len(failed_stories)
    )

    # Store in session state
    if tool_context and validated_stories:
        stories_for_save: List[Dict[str, Any]] = []
        for vs in validated_stories:
            story_obj = cast(Dict[str, Any], vs.get("story", {}))
            stories_for_save.append({
                "feature_id": vs.get("feature_id"),
                "title": story_obj.get("title"),
                "description": story_obj.get("description"),
                "acceptance_criteria": story_obj.get("acceptance_criteria"),
                "story_points": story_obj.get("story_points"),
            })
        tool_context.state["pending_validated_stories"] = stories_for_save
        tool_context.state["pending_product_id"] = batch_input.product_id
        tool_context.state["pending_spec_version_id"] = effective_spec_version_id
        logger.info("Stored %d stories in session state", len(stories_for_save))

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
