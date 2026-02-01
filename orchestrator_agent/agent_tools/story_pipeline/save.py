"""Persist validated stories without rerunning the pipeline."""

from typing import Annotated, Any, Dict, List, Optional

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from agile_sqlmodel import UserStory, get_engine
from tools.spec_tools import validate_story_with_spec_authority

from .persona_checker import extract_persona_from_story

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


class SaveStoriesInput(BaseModel):
    """Input schema for save_validated_stories tool."""

    product_id: Annotated[int, Field(description="The product ID.")]
    spec_version_id: Annotated[
        int,
        Field(description="Compiled spec version ID used for validation."),
    ]
    stories: Annotated[
        Optional[List[Dict[str, Any]]],
        Field(
            default=None,
            description=(
                "List of already-validated story dicts. Each must have: "
                "feature_id, title, description, acceptance_criteria, story_points. "
                "If omitted, stories will be retrieved from session state (pending_validated_stories)."
            )
        ),
    ]


async def save_validated_stories(
    save_input: SaveStoriesInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Save already-validated stories to the database WITHOUT re-running the pipeline.

    Use this tool when:
    - Stories have already been generated and shown to the user
    - User confirms they want to save them
    - NO need to regenerate - just persist what was already created

    This saves API calls and ensures the exact stories shown are saved.

    If `stories` is not provided, the tool will attempt to retrieve them from
    session state (`pending_validated_stories`) set by `process_story_batch`.
    """
    # --- Resolve stories from input or session state fallback ---
    stories_to_save = save_input.stories
    if not stories_to_save and tool_context and tool_context.state:
        stories_to_save = tool_context.state.get("pending_validated_stories")
        if stories_to_save:
            print(f"{YELLOW}[INFO] Retrieved {len(stories_to_save)} stories from session state{RESET}")

    if not stories_to_save:
        return {
            "success": False,
            "error": (
                "No stories provided and none found in session state. "
                "Please provide the 'stories' field with the validated story data, "
                "or run process_story_batch first to populate session state."
            ),
            "saved_story_ids": [],
            "failed_saves": [],
            "failed_validations": [],
        }

    print(
        f"\n{CYAN}Saving {len(stories_to_save)} validated stories to database...{RESET}"
    )

    saved_ids: List[int] = []
    failed_saves: List[Dict[str, Any]] = []
    failed_validations: List[Dict[str, Any]] = []

    try:
        with Session(get_engine()) as session:
            for story_data in stories_to_save:
                try:
                    # Validate against test fixture data leakage
                    title = story_data.get("title", "Untitled")
                    description = story_data.get("description", "")
                    acceptance_criteria = story_data.get("acceptance_criteria", "")
                    
                    if any(
                        test_marker in str(field)
                        for test_marker in ["Story from session", "session state fallback", "AC from session"]
                        for field in [title, description, acceptance_criteria]
                    ):
                        failed_saves.append({
                            "title": title,
                            "error": "Test fixture data detected - refusing to persist placeholder story",
                        })
                        print(f"{RED}[ERROR] Skipped test fixture data: {title}{RESET}")
                        continue
                    
                    user_story = UserStory(
                        title=title,
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

                    validation = validate_story_with_spec_authority(
                        {
                            "story_id": user_story.story_id,
                            "spec_version_id": save_input.spec_version_id,
                        },
                        tool_context=None,
                    )

                    if not validation.get("success") or not validation.get("passed"):
                        failed_validations.append(
                            {
                                "story_id": user_story.story_id,
                                "title": story_data.get("title", "Unknown"),
                                "error": validation.get(
                                    "error",
                                    "Validation failed",
                                ),
                            }
                        )
                        print(
                            f"   {RED}✗{RESET} Validation failed for story ID: {user_story.story_id}"
                        )
                    else:
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
            "failed_saves": failed_saves,
            "failed_validations": failed_validations,
        }

    return {
        "success": len(failed_saves) == 0 and len(failed_validations) == 0,
        "saved_count": len(saved_ids),
        "failed_count": len(failed_saves),
        "saved_story_ids": saved_ids,
        "failed_saves": failed_saves,
        "failed_validations": failed_validations,
        "message": f"Saved {len(saved_ids)} stories to database"
        + (f" ({len(failed_saves)} failed)" if failed_saves else "")
        + (f" ({len(failed_validations)} failed validation)" if failed_validations else ""),
    }
