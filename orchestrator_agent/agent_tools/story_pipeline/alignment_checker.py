# orchestrator_agent/agent_tools/story_pipeline/alignment_checker.py
"""
Deterministic alignment checker for product vision constraints.

This module provides code-level enforcement of product vision boundaries.
It extracts forbidden capabilities from vision keywords and checks stories
for violations. This ensures alignment even when LLM validation is unreliable.

Key functions:
- extract_forbidden_capabilities: Derives forbidden terms from vision statement
- check_alignment_violation: Checks a story/feature against vision constraints
- detect_requirement_drift: Compares original request vs final story
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class AlignmentResult:
    """Result of an alignment check."""
    is_aligned: bool
    alignment_issues: List[str]
    forbidden_found: List[str]  # Which forbidden terms were detected


# --- Vision Keyword Patterns ---
# Maps vision phrases to forbidden capability keywords
# Key: tuple of trigger phrases, Value: list of forbidden terms
VISION_CONSTRAINT_PATTERNS: Dict[Tuple[str, ...], List[str]] = {
    # Platform constraints
    ("mobile-only", "mobile app", "mobile-first"): [
        "web", "desktop", "browser", "website", "web-based", "web app",
        "windows", "macos", "linux", "pc", "laptop"
    ],
    # Connectivity constraints  
    ("offline-first", "without internet", "works offline", "offline mode", "no internet"): [
        "real-time", "realtime", "live sync", "cloud sync", "server sync",
        "instant sync", "automatic sync", "synchronization", "online-only",
        "always connected", "streaming"
    ],
    # UX philosophy constraints
    ("distraction-free", "minimal", "simple", "focused", "private"): [
        "notifications", "notification", "alerts", "alert", "push",
        "reminders", "reminder", "badge", "sound", "vibrate", "pop-up"
    ],
    # User segment constraints
    ("casual", "home use", "consumer", "personal", "hobby", "beginner"): [
        "industrial", "plc", "opc ua", "scada", "manufacturing",
        "enterprise", "professional-grade", "commercial", "b2b"
    ],
    # Scope constraints
    ("simple", "lightweight", "basic", "minimal"): [
        "ai", "machine learning", "ml", "neural", "deep learning",
        "analytics dashboard", "reporting engine", "data warehouse"
    ],
}


def extract_forbidden_capabilities(vision: Optional[str]) -> List[str]:
    """
    Extract forbidden capability keywords from a product vision statement.
    
    Analyzes vision text for constraint-indicating phrases and returns
    a list of capability keywords that would violate those constraints.
    
    Args:
        vision: Product vision statement text
        
    Returns:
        List of forbidden capability keywords (lowercase)
        
    Example:
        >>> extract_forbidden_capabilities("Mobile-only app for quick notes")
        ['web', 'desktop', 'browser', 'website', 'web-based', ...]
    """
    if not vision:
        return []
    
    vision_lower = vision.lower()
    forbidden: List[str] = []
    
    for trigger_phrases, forbidden_terms in VISION_CONSTRAINT_PATTERNS.items():
        for phrase in trigger_phrases:
            if phrase in vision_lower:
                # Add terms that aren't already in the list
                for term in forbidden_terms:
                    if term not in forbidden:
                        forbidden.append(term)
                break  # One match per pattern group is enough
    
    return forbidden


def check_alignment_violation(
    text: str,
    forbidden_capabilities: List[str],
    context_label: str = "content"
) -> AlignmentResult:
    """
    Check if text contains any forbidden capabilities.
    
    This is a deterministic check that scans text for forbidden terms.
    Used for both feature requests and story drafts.
    
    Args:
        text: Text to check (feature title, story description, etc.)
        forbidden_capabilities: List of forbidden terms to check for
        context_label: Label for error messages (e.g., "feature", "story")
        
    Returns:
        AlignmentResult with is_aligned=False if violations found
        
    Example:
        >>> result = check_alignment_violation(
        ...     "Web-based analytics dashboard",
        ...     ["web", "dashboard"],
        ...     "feature"
        ... )
        >>> result.is_aligned
        False
        >>> result.alignment_issues
        ['Feature violates vision constraint: contains forbidden term "web"', ...]
    """
    if not text or not forbidden_capabilities:
        return AlignmentResult(is_aligned=True, alignment_issues=[], forbidden_found=[])
    
    text_lower = text.lower()
    found_terms: List[str] = []
    issues: List[str] = []
    
    for term in forbidden_capabilities:
        # Use word boundary matching to avoid false positives
        # e.g., "web" shouldn't match "cobweb"
        pattern = rf'\b{re.escape(term)}\b'
        if re.search(pattern, text_lower):
            found_terms.append(term)
            issues.append(
                f'{context_label.capitalize()} violates vision constraint: '
                f'contains forbidden capability "{term}"'
            )
    
    return AlignmentResult(
        is_aligned=len(found_terms) == 0,
        alignment_issues=issues,
        forbidden_found=found_terms
    )


def detect_requirement_drift(
    original_feature: str,
    final_story_title: str,
    final_story_description: str,
    forbidden_capabilities: List[str]
) -> Tuple[bool, Optional[str]]:
    """
    Detect if a story was silently transformed to remove forbidden capabilities.
    
    This catches cases where:
    - Original feature: "Web-based analytics dashboard" (has "web")
    - Final story: "Mobile analytics screen" (no "web")
    - The forbidden term disappeared due to transformation, not rejection
    
    Args:
        original_feature: Original feature title/description
        final_story_title: Title of the generated story
        final_story_description: Description of the generated story
        forbidden_capabilities: List of forbidden capability terms
        
    Returns:
        Tuple of (drift_detected: bool, drift_message: Optional[str])
        
    Example:
        >>> drift, msg = detect_requirement_drift(
        ...     "Real-time cloud sync feature",
        ...     "Manual data refresh",
        ...     "As a user, I want to manually refresh...",
        ...     ["real-time", "cloud sync"]
        ... )
        >>> drift
        True
        >>> msg
        'Requirement drift: original feature contained "real-time" which was removed...'
    """
    if not forbidden_capabilities:
        return False, None
    
    # Check what forbidden terms were in the original feature
    original_result = check_alignment_violation(
        original_feature, 
        forbidden_capabilities, 
        "original feature"
    )
    
    # If original feature had no forbidden terms, no drift possible
    if original_result.is_aligned:
        return False, None
    
    # Check if forbidden terms are still in the final story
    final_text = f"{final_story_title} {final_story_description}"
    final_result = check_alignment_violation(
        final_text,
        original_result.forbidden_found,  # Only check terms that were in original
        "final story"
    )
    
    # Drift = original had forbidden terms, but final doesn't (they were removed)
    if final_result.is_aligned and not original_result.is_aligned:
        removed_terms = original_result.forbidden_found
        return True, (
            f'Requirement drift detected: original feature contained '
            f'forbidden capabilities {removed_terms} which were silently removed. '
            f'The pipeline should reject out-of-scope features, not transform them.'
        )
    
    return False, None


def validate_feature_alignment(
    feature_title: str,
    product_vision: Optional[str]
) -> AlignmentResult:
    """
    Validate that a feature request aligns with product vision BEFORE processing.
    
    Call this at the start of the pipeline to fail-fast on vision violations.
    
    Args:
        feature_title: The requested feature title
        product_vision: Product vision statement
        
    Returns:
        AlignmentResult indicating if the feature can be processed
        
    Example:
        >>> result = validate_feature_alignment(
        ...     "Web-based analytics dashboard",
        ...     "Tennis Tracker is a mobile-only app..."
        ... )
        >>> result.is_aligned
        False
    """
    forbidden = extract_forbidden_capabilities(product_vision)
    return check_alignment_violation(feature_title, forbidden, "feature request")


def create_rejection_response(
    feature_title: str,
    alignment_issues: List[str],
    product_vision: Optional[str]
) -> Dict[str, Any]:
    """
    Create a structured rejection response for an out-of-scope feature.
    
    Used when a feature fails alignment validation. Returns a response
    that explains why the feature cannot be implemented.
    
    Args:
        feature_title: The rejected feature title
        alignment_issues: List of alignment violation messages
        product_vision: Product vision statement for context
        
    Returns:
        Dict with rejection details, matching expected output schema
    """
    return {
        "success": False,
        "is_valid": False,
        "rejected": True,
        "rejection_reason": "Feature violates product vision constraints",
        "alignment_issues": alignment_issues,
        "story": {
            "title": f"[REJECTED] {feature_title}",
            "description": (
                "This feature request cannot be implemented because it violates "
                "the product vision constraints. See alignment_issues for details."
            ),
            "acceptance_criteria": None,
            "story_points": None,
        },
        "validation_score": 0,
        "iterations": 0,
        "message": (
            f"Feature '{feature_title}' rejected: violates product vision. "
            f"Issues: {'; '.join(alignment_issues)}"
        ),
        "product_vision_excerpt": (
            product_vision[:200] + "..." if product_vision and len(product_vision) > 200 
            else product_vision
        ),
    }
