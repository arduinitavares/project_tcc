from typing import Annotated, Optional, List
from pydantic import BaseModel, Field

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
