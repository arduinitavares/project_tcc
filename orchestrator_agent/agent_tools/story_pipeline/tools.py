# orchestrator_agent/agent_tools/story_pipeline/tools.py
"""
Tools for orchestrator to invoke the story validation pipeline.

These tools handle:
1. Setting up state for a single story
2. Running the pipeline
3. Extracting the validated story
4. Batch processing multiple features
"""

import json
from typing import Annotated, Any, Dict, List, Optional

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from agile_sqlmodel import UserStory, engine
from orchestrator_agent.agent_tools.story_pipeline.pipeline import (
    story_validation_loop,
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


async def process_single_story(story_input: ProcessStoryInput) -> Dict[str, Any]:
    """
    Process a single feature through the story validation pipeline.

    This tool:
    1. Sets up initial state with feature context
    2. Runs the LoopAgent pipeline (Draft → Validate → Refine)
    3. Returns the validated story or error

    The pipeline will loop up to 3 times until a valid story is produced.
    """

    # --- ANSI colors for terminal output ---
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    print(
        f"\n{CYAN}[Pipeline]{RESET} Processing feature: {BOLD}'{story_input.feature_title}'{RESET}"
    )
    print(f"{DIM}   Theme: {story_input.theme} | Epic: {story_input.epic}{RESET}")

    # --- Set up initial state ---
    initial_state: Dict[str, Any] = {
        "current_feature": json.dumps(
            {
                "feature_id": story_input.feature_id,
                "feature_title": story_input.feature_title,
                "theme": story_input.theme,
                "epic": story_input.epic,
            }
        ),
        "product_context": json.dumps(
            {
                "product_id": story_input.product_id,
                "product_name": story_input.product_name,
                "vision": story_input.product_vision or "",
            }
        ),
        "user_persona": story_input.user_persona,
        "story_preferences": json.dumps(
            {
                "include_story_points": story_input.include_story_points,
            }
        ),
        "refinement_feedback": "",  # Empty for first iteration
        "iteration_count": 0,
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
    last_story_draft = None
    last_validation_result = None
    last_refinement_result = None
    current_iteration = 0  # Track locally by counting new drafts
    seen_drafts = set()  # Track unique drafts to count iterations

    # --- Run the pipeline ---
    try:
        # Build the Content object for ADK runner
        prompt_text = f"Generate a user story for feature: {story_input.feature_title}"
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt_text)],
        )

        # The pipeline runs until is_valid=True or max_iterations
        async for event in runner.run_async(
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
                            print(
                                f"\n{MAGENTA}   ╭─ Iteration {current_iteration} ─────────────────────────────────╮{RESET}"
                            )

                        last_story_draft = story_draft
                        draft_data = (
                            story_draft if isinstance(story_draft, dict) else {}
                        )
                        if isinstance(story_draft, str):
                            try:
                                draft_data = json.loads(story_draft)
                            except:
                                pass
                        if draft_data:
                            title = draft_data.get("title", "")
                            desc = draft_data.get("description", "")[:100]
                            points = draft_data.get("story_points", "?")
                            print(f"{CYAN}   │ 📝 DRAFT:{RESET}")
                            print(f"{CYAN}   │{RESET}    Title: {title}")
                            print(f"{CYAN}   │{RESET}    Story: {desc}...")
                            print(f"{CYAN}   │{RESET}    Points: {points}")

                    # Check for validation result
                    validation_result = state.get("validation_result")
                    if (
                        validation_result
                        and validation_result != last_validation_result
                    ):
                        last_validation_result = validation_result
                        val_data = (
                            validation_result
                            if isinstance(validation_result, dict)
                            else {}
                        )
                        if isinstance(validation_result, str):
                            try:
                                val_data = json.loads(validation_result)
                            except:
                                pass
                        if val_data:
                            is_valid = val_data.get("is_valid", False)
                            score = val_data.get("validation_score", 0)
                            invest = val_data.get("invest_scores", {})
                            issues = val_data.get("issues", [])
                            suggestions = val_data.get("suggestions", [])

                            status_icon = "✅" if is_valid else "❌"
                            status_color = GREEN if is_valid else RED
                            print(
                                f"{YELLOW}   │ 🔍 VALIDATION: {status_color}{status_icon} {'PASS' if is_valid else 'FAIL'}{RESET} (Score: {score}/100)"
                            )

                            # Show INVEST scores
                            if invest:
                                invest_str = " | ".join(
                                    [f"{k[0].upper()}:{v}" for k, v in invest.items()]
                                )
                                print(f"{YELLOW}   │{RESET}    INVEST: {invest_str}")

                            # Show issues if failed
                            if not is_valid and issues:
                                print(f"{RED}   │{RESET}    Issues:")
                                for issue in issues[:3]:  # Show first 3 issues
                                    print(f"{RED}   │{RESET}      • {issue}")

                            # Show suggestions
                            if suggestions:
                                print(f"{YELLOW}   │{RESET}    Feedback:")
                                for sug in suggestions[:2]:  # Show first 2 suggestions
                                    print(f"{YELLOW}   │{RESET}      → {sug}")

                    # Check for refinement result
                    refinement_result = state.get("refinement_result")
                    if (
                        refinement_result
                        and refinement_result != last_refinement_result
                    ):
                        last_refinement_result = refinement_result
                        ref_data = (
                            refinement_result
                            if isinstance(refinement_result, dict)
                            else {}
                        )
                        if isinstance(refinement_result, str):
                            try:
                                ref_data = json.loads(refinement_result)
                            except:
                                pass
                        if ref_data:
                            is_valid = ref_data.get("is_valid", False)
                            refined = ref_data.get("refined_story", {})
                            notes = ref_data.get("refinement_notes", "")

                            status_color = GREEN if is_valid else YELLOW
                            print(f"{status_color}   │ ✨ REFINED:{RESET}")
                            if refined:
                                print(
                                    f"{status_color}   │{RESET}    Title: {refined.get('title', '')}"
                                )
                            if notes:
                                print(
                                    f"{status_color}   │{RESET}    Notes: {notes[:80]}..."
                                )
                            print(
                                f"{MAGENTA}   ╰────────────────────────────────────────────────╯{RESET}"
                            )
            except:
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
            if isinstance(refinement_result, str):
                try:
                    refinement_result = json.loads(refinement_result)
                except json.JSONDecodeError:
                    pass

            if isinstance(refinement_result, dict):
                refined_story = refinement_result.get("refined_story", {})
                is_valid = refinement_result.get("is_valid", False)
                refinement_notes = refinement_result.get("refinement_notes", "")

                # Final summary
                final_score = 0
                if isinstance(state.get("validation_result"), dict):
                    final_score = state.get("validation_result", {}).get(
                        "validation_score", 0
                    )
                elif isinstance(state.get("validation_result"), str):
                    try:
                        val = json.loads(state.get("validation_result", "{}"))
                        final_score = val.get("validation_score", 0)
                    except:
                        pass

                status_icon = "✅" if is_valid else "⚠️"
                status_color = GREEN if is_valid else YELLOW
                # Use locally tracked iterations (current_iteration) instead of state
                iterations = max(current_iteration, 1)  # At least 1 iteration
                print(
                    f"\n{status_color}   {status_icon} FINAL: '{refined_story.get('title', 'Unknown')}' | Score: {final_score}/100 | Iterations: {iterations}{RESET}"
                )

                return {
                    "success": True,
                    "is_valid": is_valid,
                    "story": refined_story,
                    "validation_score": final_score,
                    "iterations": iterations,
                    "refinement_notes": refinement_notes,
                    "message": f"Generated story '{refined_story.get('title', 'Unknown')}' "
                    f"(valid={is_valid}, iterations={iterations})",
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
        print(f"   [Pipeline Error] {e}")
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
                "List of feature dicts with: feature_id, feature_title, theme, epic"
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
    print(f"{CYAN}{'═' * 60}{RESET}")

    validated_stories: List[Dict[str, Any]] = []
    failed_stories: List[Dict[str, Any]] = []
    total_iterations = 0

    for idx, feature in enumerate(batch_input.features):
        print(
            f"\n{YELLOW}[{idx + 1}/{len(batch_input.features)}]{RESET} {BOLD}{feature.get('feature_title', 'Unknown')}{RESET}"
        )

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
            )
        )

        if result.get("success") and result.get("is_valid"):
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
            failed_stories.append(
                {
                    "feature_id": feature["feature_id"],
                    "feature_title": feature["feature_title"],
                    "error": result.get("error", "Validation failed"),
                    "partial_story": result.get("story"),
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

    saved_ids = []
    failed_saves = []

    try:
        with Session(engine) as session:
            for story_data in save_input.stories:
                try:
                    user_story = UserStory(
                        title=story_data.get("title", "Untitled"),
                        story_description=story_data.get("description", ""),
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
