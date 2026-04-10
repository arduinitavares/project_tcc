# tools/story_query_tools.py
"""
Tools for querying features and story-related data.

Extracted from legacy product_user_story_tool/tools.py to preserve
query_features_for_stories functionality after legacy agent removal.
"""

import re
from typing import Annotated, Any, cast

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from models.core import Epic, Feature, Product, Theme, UserStory
from models.db import get_engine

# --- Schemas for querying features ---


class FeatureForStory(BaseModel):
    """
    Schema for a single feature ready for story generation.

    CRITICAL: theme and epic are REQUIRED fields. They must NEVER be None or "Unknown".
    This enforces the contract that all features must have proper roadmap metadata.

    IMMUTABILITY: This model is frozen to prevent accidental mutation during pipeline processing.
    All fields are set at construction time and cannot be changed.
    """

    model_config = {"frozen": True}  # Immutable after construction

    feature_id: Annotated[int, Field(description="Feature ID")]
    feature_title: Annotated[str, Field(description="Feature title")]
    # --- Stable ID-based references (preferred for validation) ---
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
    # --- Title-based references (human-readable, validated against IDs) ---
    theme: Annotated[
        str,
        Field(
            description="Theme name (REQUIRED - must never be None or 'Unknown')",
            min_length=1,  # Enforce non-empty after stripping
        ),
    ]
    epic: Annotated[
        str,
        Field(
            description="Epic name (REQUIRED - must never be None or 'Unknown')",
            min_length=1,  # Enforce non-empty after stripping
        ),
    ]
    existing_stories_count: Annotated[
        int | None,
        Field(description="Number of existing stories. Defaults to 0 if not provided."),
    ] = None
    time_frame: Annotated[
        str | None,
        Field(description="Roadmap time frame. Defaults to None if not provided."),
    ] = None
    theme_justification: Annotated[
        str | None,
        Field(
            description="Strategic theme justification. Defaults to None if not provided."
        ),
    ] = None
    sibling_features: Annotated[
        list[str],
        Field(default_factory=list, description="Other features in same theme"),
    ]

    @field_validator("theme", "epic")
    @classmethod
    def validate_non_empty_after_strip(cls, v: str) -> str:
        """Strip whitespace and validate min_length."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty or whitespace-only")
        return v.strip()


class QueryFeaturesOutput(BaseModel):
    """Output schema for query_features_for_stories with validated structure."""

    success: Annotated[bool, Field(description="Whether query succeeded")]
    product_id: Annotated[int, Field(description="Product ID")]
    product_name: Annotated[str, Field(description="Product name")]
    features_flat: Annotated[
        list[FeatureForStory],
        Field(description="Flat list of features with REQUIRED theme/epic metadata"),
    ]
    structure: Annotated[
        list[dict[str, Any]],
        Field(description="Hierarchical theme/epic/feature structure"),
    ]
    total_features: Annotated[int, Field(description="Total feature count")]
    message: Annotated[str, Field(description="Human-readable message")]


class QueryFeaturesInput(BaseModel):
    """Input schema for querying features."""

    product_id: Annotated[int, Field(description="The product ID to query.")]


def query_features_for_stories(
    query_input: QueryFeaturesInput,
) -> dict[str, Any]:
    """
    Query all features for a product, organized by theme/epic.
    Used by the orchestrator to provide context to the user story agent.

    Returns:
        Dict representation of QueryFeaturesOutput with validated features_flat list
        where EVERY feature has required theme and epic fields (enforced by Pydantic schema).
        Returns JSON-serializable dict for ADK compatibility.

    Raises:
        ValidationError: If any feature is missing theme or epic metadata.
    """
    print(
        f"\n[Tool: query_features_for_stories] Querying product {query_input.product_id}..."
    )

    try:
        with Session(get_engine()) as session:
            product = session.get(Product, query_input.product_id)
            if not product:
                return {
                    "success": False,
                    "error": f"Product {query_input.product_id} not found",
                }

            # 1. Fetch all Themes
            themes = session.exec(
                select(Theme).where(Theme.product_id == query_input.product_id)
            ).all()
            theme_ids = [t.theme_id for t in themes if t.theme_id is not None]

            # 2. Fetch all Epics for these themes
            epics: list[Epic] = []
            if theme_ids:
                epics = list(
                    session.exec(
                        select(Epic).where(cast("Any", Epic.theme_id).in_(theme_ids))
                    ).all()
                )

            epic_ids = [e.epic_id for e in epics if e.epic_id is not None]
            epics_by_theme: dict[int, list[Epic]] = {tid: [] for tid in theme_ids}
            epic_to_theme: dict[int, int] = {}
            for epic in epics:
                theme_id = epic.theme_id
                epic_id = epic.epic_id
                if theme_id is None or epic_id is None:
                    continue
                epics_by_theme[theme_id].append(epic)
                epic_to_theme[epic_id] = theme_id

            # 3. Fetch all Features for these epics
            features: list[Feature] = []
            if epic_ids:
                features = list(
                    session.exec(
                        select(Feature).where(
                            cast("Any", Feature.epic_id).in_(epic_ids)
                        )
                    ).all()
                )

            feature_ids = [f.feature_id for f in features if f.feature_id is not None]
            features_by_epic: dict[int, list[Feature]] = {eid: [] for eid in epic_ids}
            features_by_theme: dict[int, list[str]] = {tid: [] for tid in theme_ids}

            for feature in features:
                epic_id = feature.epic_id
                feature_id = feature.feature_id
                if epic_id is None or feature_id is None:
                    continue
                features_by_epic[epic_id].append(feature)
                # Map feature to theme via epic
                theme_id = epic_to_theme.get(epic_id)
                if theme_id is not None:
                    features_by_theme[theme_id].append(feature.title)

            # 4. Fetch Story Counts grouped by feature
            story_counts: dict[int, int] = {}
            if feature_ids:
                story_counts_query = (
                    select(UserStory.feature_id, func.count(UserStory.story_id))
                    .where(cast("Any", UserStory.feature_id).in_(feature_ids))
                    .group_by(UserStory.feature_id)
                )
                results = session.exec(story_counts_query).all()
                story_counts = {
                    feature_id: count
                    for feature_id, count in results
                    if feature_id is not None
                }

            # 5. Assemble structure
            features_list: list[FeatureForStory] = []
            structure: list[dict[str, Any]] = []

            def _derive_time_frame_from_title(title: str) -> str | None:
                if not title:
                    return None
                match = re.search(r"\b(now|next|later)\b", title, re.IGNORECASE)
                if not match:
                    return None
                value = match.group(1).lower()
                return value.capitalize()

            for theme in themes:
                theme_id = theme.theme_id
                if theme_id is None:
                    continue
                time_frame_value = theme.time_frame.value if theme.time_frame else None
                if time_frame_value is None:
                    time_frame_value = _derive_time_frame_from_title(theme.title)
                theme_data: dict[str, Any] = {
                    "theme_id": theme_id,
                    "theme_title": theme.title,
                    "time_frame": time_frame_value,
                    "justification": theme.description,
                    "epics": [],
                }

                # Get all feature titles in this theme for sibling comparison
                theme_all_features = features_by_theme.get(theme_id, [])

                for epic in epics_by_theme.get(theme_id, []):
                    epic_id = epic.epic_id
                    if epic_id is None:
                        continue
                    epic_data: dict[str, Any] = {
                        "epic_id": epic_id,
                        "epic_title": epic.title,
                        "features": [],
                    }

                    for feature in features_by_epic.get(epic_id, []):
                        feature_id = feature.feature_id
                        if feature_id is None:
                            continue
                        count = story_counts.get(feature_id, 0)

                        # Sibling features = all features in this theme except current
                        sibling_features = [
                            f for f in theme_all_features if f != feature.title
                        ]

                        # Create validated FeatureForStory object
                        # This will FAIL with ValidationError if theme or epic are missing/empty
                        # INCLUDES stable IDs to eliminate duplicate name ambiguity
                        feature_obj = FeatureForStory(
                            feature_id=feature_id,
                            feature_title=feature.title,
                            theme_id=theme_id,  # Stable ID reference
                            epic_id=epic_id,  # Stable ID reference
                            theme=theme.title,  # REQUIRED - Pydantic validates non-empty
                            epic=epic.title,  # REQUIRED - Pydantic validates non-empty
                            existing_stories_count=count,
                            time_frame=time_frame_value,
                            theme_justification=theme.description,
                            sibling_features=sibling_features,
                        )

                        # Add validated feature to flat list
                        features_list.append(feature_obj)

                        # Add raw dict to hierarchical structure
                        feature_info: dict[str, Any] = {
                            "feature_id": feature.feature_id,
                            "feature_title": feature.title,
                            "existing_stories_count": count,
                            "time_frame": time_frame_value,
                            "theme_justification": theme.description,
                            "sibling_features": sibling_features,
                        }
                        epic_data["features"].append(feature_info)

                    theme_data["epics"].append(epic_data)

                structure.append(theme_data)

            # Create validated Pydantic output (enforces schema)
            validated_output = QueryFeaturesOutput(
                success=True,
                product_id=query_input.product_id,
                product_name=product.name,
                features_flat=features_list,  # List[FeatureForStory] - validated!
                structure=structure,
                total_features=len(features_list),
                message=f"Found {len(features_list)} features for '{product.name}'",
            )

            # Return JSON-serializable dict for ADK
            return validated_output.model_dump()

    except SQLAlchemyError as e:
        print(f"   [DB Error] {e}")
        # Return error response (still needs to match schema for success=False case)
        # We'll need to handle this - for now, re-raise to make error visible
        raise
