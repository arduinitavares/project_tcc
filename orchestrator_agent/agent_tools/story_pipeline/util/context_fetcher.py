"""
Context fetcher for story pipeline.

This module provides fetch_feature_context() which derives all pipeline context
from a single feature_id by traversing the DB hierarchy:
    feature -> epic -> theme -> product

This simplifies the input contract: callers only need to provide feature_id,
and all other metadata (theme, epic, time_frame, product_vision, etc.) is
fetched automatically from the database.
"""

import re
from typing import Any, Dict, List, Optional

from sqlalchemy import Engine
from sqlmodel import Session, select

from agile_sqlmodel import Epic, Feature, Product, Theme, get_engine


def _derive_time_frame_from_title(title: str) -> Optional[str]:
    """Derive time_frame from theme title if not stored in DB.
    
    Extracts 'Now', 'Next', or 'Later' from titles like:
      - "Now (Months 1-3) - Core Infrastructure"
      - "Next Phase - Data Pipeline"
      - "Later (Q4) - Advanced Features"
    
    Returns:
        Capitalized time_frame string or None if not found.
    """
    if not title:
        return None
    match = re.search(r"\b(now|next|later)\b", title, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).lower()
    return value.capitalize()


def _get_sibling_features(
    session: Session, theme_id: int, exclude_feature_title: str
) -> List[str]:
    """Get all feature titles in the same theme, excluding the target feature.
    
    Siblings = features in different epics under the same theme, plus
    other features in the same epic.
    """
    # Get all epics in this theme
    epics = session.exec(select(Epic).where(Epic.theme_id == theme_id)).all()
    epic_ids = [e.epic_id for e in epics]
    
    if not epic_ids:
        return []
    
    # Get all features in those epics
    features = session.exec(
        select(Feature.title).where(Feature.epic_id.in_(epic_ids))
    ).all()
    
    # Exclude self
    return [f for f in features if f != exclude_feature_title]


def fetch_feature_context(
    feature_id: int,
    engine: Optional[Engine] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch complete pipeline context from a single feature_id.
    
    Traverses the DB hierarchy:
        Feature -> Epic -> Theme -> Product
    
    and returns a dict with all fields needed for story generation.
    
    NOTE: `domain` is NOT included here as it comes from CompiledSpecAuthority,
    not from the product hierarchy. Domain is loaded during authority setup.
    
    Args:
        feature_id: The feature database ID.
        engine: Optional SQLAlchemy engine (uses default if not provided).
    
    Returns:
        Dict with complete context, or None if feature not found.
        
        Returned keys:
          - product_id, product_name, product_vision
          - theme_id, theme_name, time_frame, theme_justification
          - epic_id, epic_name
          - feature_id, feature_title
          - sibling_features (list of other feature titles in same theme)
    """
    db_engine = engine or get_engine()
    
    with Session(db_engine) as session:
        # 1. Fetch the feature
        feature = session.get(Feature, feature_id)
        if not feature:
            return None
        
        # 2. Fetch the epic
        epic = session.get(Epic, feature.epic_id)
        if not epic:
            return None
        
        # 3. Fetch the theme
        theme = session.get(Theme, epic.theme_id)
        if not theme:
            return None
        
        # 4. Fetch the product
        product = session.get(Product, theme.product_id)
        if not product:
            return None
        
        # 5. Derive time_frame (from DB or title fallback)
        time_frame = theme.time_frame
        if time_frame and hasattr(time_frame, 'value'):
            # Handle SQLModel enum
            time_frame = time_frame.value
        if not time_frame:
            time_frame = _derive_time_frame_from_title(theme.title)
        
        # 6. Get sibling features
        sibling_features = _get_sibling_features(
            session, theme.theme_id, feature.title
        )
        
        return {
            # Product-level
            "product_id": product.product_id,
            "product_name": product.name,
            "product_vision": product.vision,
            # Theme-level
            "theme_id": theme.theme_id,
            "theme_name": theme.title,
            "time_frame": time_frame,
            "theme_justification": theme.description,
            # Epic-level
            "epic_id": epic.epic_id,
            "epic_name": epic.title,
            # Feature-level
            "feature_id": feature.feature_id,
            "feature_title": feature.title,
            # Related features
            "sibling_features": sibling_features,
        }
