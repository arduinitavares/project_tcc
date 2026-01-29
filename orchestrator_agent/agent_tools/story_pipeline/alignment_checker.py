# orchestrator_agent/agent_tools/story_pipeline/alignment_checker.py
"""
Deterministic alignment checker for spec authority forbidden capabilities.

This module enforces scope boundaries derived from compiled spec authority.
It extracts forbidden capabilities from FORBIDDEN_CAPABILITY invariants and
checks stories/features for violations. This ensures deterministic alignment
without relying on LLM validation.

Key functions:
- derive_forbidden_capabilities_from_authority: Extract forbidden terms from authority
- derive_forbidden_capabilities_from_invariants: Legacy fallback (FORBIDDEN only)
- check_alignment_violation: Checks a story/feature against forbidden capabilities
- detect_requirement_drift: Compares original request vs final story
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from pydantic import ValidationError

from utils.schemes import (
    SpecAuthorityCompilerOutput,
    SpecAuthorityCompilationFailure,
    Invariant,
    InvariantType,
)

from agile_sqlmodel import CompiledSpecAuthority


@dataclass
class AlignmentResult:
    """Result of an alignment check."""
    is_aligned: bool
    alignment_issues: List[str]
    forbidden_found: List[str]  # Which forbidden terms were detected
    findings: List["AlignmentFinding"]


@dataclass
class AlignmentFinding:
    """Structured alignment finding for evidence capture."""
    code: str
    invariant: Optional[str]
    capability: Optional[str]
    message: str
    severity: str  # "warning" | "failure"
    created_at: datetime


@dataclass
class ForbiddenCapability:
    """Structured forbidden capability with optional invariant ID."""

    term: str
    invariant_id: Optional[str] = None


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


def _extract_forbidden_capabilities_from_vision(vision: Optional[str]) -> List[str]:
    """
    INTERNAL: legacy helper for vision-based constraints (not for external use).
    """
    if not vision:
        return []

    vision_lower = vision.lower()
    forbidden: List[str] = []

    for trigger_phrases, forbidden_terms in VISION_CONSTRAINT_PATTERNS.items():
        for phrase in trigger_phrases:
            if phrase in vision_lower:
                for term in forbidden_terms:
                    if term not in forbidden:
                        forbidden.append(term)
                break

    return forbidden


def _normalize_forbidden_capabilities(
    forbidden_capabilities: Sequence[Union[str, ForbiddenCapability]],
) -> List[ForbiddenCapability]:
    normalized: List[ForbiddenCapability] = []
    for item in forbidden_capabilities:
        if isinstance(item, ForbiddenCapability):
            term = item.term.strip().lower()
            if term:
                normalized.append(
                    ForbiddenCapability(term=term, invariant_id=item.invariant_id)
                )
        else:
            term = str(item).strip().lower()
            if term:
                normalized.append(ForbiddenCapability(term=term))
    return normalized


def check_alignment_violation(
    text: str,
    forbidden_capabilities: Sequence[Union[str, ForbiddenCapability]],
    context_label: str = "content",
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
        ['Feature violates spec authority: contains forbidden capability "web" ...]
    """
    if not text or not forbidden_capabilities:
        return AlignmentResult(
            is_aligned=True,
            alignment_issues=[],
            forbidden_found=[],
            findings=[],
        )
    
    text_lower = text.lower()
    found_terms: List[str] = []
    issues: List[str] = []
    
    findings: List[AlignmentFinding] = []

    normalized = _normalize_forbidden_capabilities(forbidden_capabilities)
    for item in normalized:
        term = item.term
        # Use word boundary matching to avoid false positives
        # e.g., "web" shouldn't match "cobweb"
        pattern = rf'\b{re.escape(term)}\b'
        if re.search(pattern, text_lower):
            found_terms.append(term)
            invariant_suffix = (
                f" (FORBIDDEN_CAPABILITY {item.invariant_id})"
                if item.invariant_id
                else " (FORBIDDEN_CAPABILITY)"
            )
            issues.append(
                f'{context_label.capitalize()} violates spec authority: '
                f'contains forbidden capability "{term}"{invariant_suffix}'
            )
            findings.append(
                AlignmentFinding(
                    code="FORBIDDEN_CAPABILITY",
                    invariant=item.invariant_id,
                    capability=term,
                    message=(
                        f'{context_label.capitalize()} violates spec authority: '
                        f'contains forbidden capability "{term}"{invariant_suffix}'
                    ),
                    severity="failure",
                    created_at=datetime.now(timezone.utc),
                )
            )
    
    return AlignmentResult(
        is_aligned=len(found_terms) == 0,
        alignment_issues=issues,
        forbidden_found=found_terms,
        findings=findings,
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


def derive_forbidden_capabilities_from_invariants(
    invariants: List[str],
) -> List[ForbiddenCapability]:
    """
    Legacy fallback: derive forbidden capabilities from invariant strings.

    Only invariants formatted as FORBIDDEN_CAPABILITY:<term> are accepted.
    REQUIRED_FIELD, MAX_VALUE, and other invariant types are ignored.
    """
    if not invariants:
        return []

    forbidden: List[ForbiddenCapability] = []
    for invariant in invariants:
        if not invariant:
            continue
        raw = invariant.strip()
        if raw.upper().startswith("FORBIDDEN_CAPABILITY:"):
            term = raw.split(":", 1)[1].strip()
            if term:
                forbidden.append(ForbiddenCapability(term=term.lower()))
    return forbidden


def derive_forbidden_capabilities_from_authority(
    compiled_authority: Optional[CompiledSpecAuthority],
    invariants: Optional[List[str]] = None,
) -> List[ForbiddenCapability]:
    """
    Preferred derivation from compiled_artifact_json (FORBIDDEN_CAPABILITY only).

    Falls back to parsing legacy invariant strings when artifact is missing or
    unparseable.
    """
    if compiled_authority and compiled_authority.compiled_artifact_json:
        try:
            parsed = SpecAuthorityCompilerOutput.model_validate_json(
                compiled_authority.compiled_artifact_json
            )
        except (ValidationError, ValueError):
            parsed = None
        if parsed and not isinstance(parsed.root, SpecAuthorityCompilationFailure):
            forbidden: List[ForbiddenCapability] = []
            for inv in parsed.root.invariants:
                if inv.type == InvariantType.FORBIDDEN_CAPABILITY:
                    capability = getattr(inv.parameters, "capability", None)
                    if capability:
                        forbidden.append(
                            ForbiddenCapability(
                                term=str(capability).strip().lower(),
                                invariant_id=inv.id,
                            )
                        )
            if forbidden:
                return forbidden

    if invariants is None:
        return []
    return derive_forbidden_capabilities_from_invariants(invariants)


def _render_invariant_summary(invariant: Invariant) -> str:
    if invariant.type == InvariantType.FORBIDDEN_CAPABILITY:
        capability = getattr(invariant.parameters, "capability", "")
        return f"FORBIDDEN_CAPABILITY:{capability}"
    if invariant.type == InvariantType.REQUIRED_FIELD:
        field_name = getattr(invariant.parameters, "field_name", "")
        return f"REQUIRED_FIELD:{field_name}"
    if invariant.type == InvariantType.MAX_VALUE:
        field_name = getattr(invariant.parameters, "field_name", "")
        max_value = getattr(invariant.parameters, "max_value", "")
        return f"MAX_VALUE:{field_name}<= {max_value}"
    return f"INVARIANT:{invariant.type}"


def extract_invariants_from_authority(
    compiled_authority: Optional[CompiledSpecAuthority],
) -> List[str]:
    """Prefer structured invariants from compiled_artifact_json when available."""
    if not compiled_authority:
        return []
    if compiled_authority.compiled_artifact_json:
        try:
            parsed = SpecAuthorityCompilerOutput.model_validate_json(
                compiled_authority.compiled_artifact_json
            )
        except (ValidationError, ValueError):
            parsed = None
        if parsed and not isinstance(parsed.root, SpecAuthorityCompilationFailure):
            return [_render_invariant_summary(inv) for inv in parsed.root.invariants]
    return (
        json.loads(compiled_authority.invariants)
        if compiled_authority.invariants
        else []
    )


def _resolve_invariants(
    compiled_authority: Optional[CompiledSpecAuthority],
    _invariants: Optional[List[str]],
) -> List[str]:
    """Resolve invariants from compiled authority or explicit list."""
    if _invariants is not None:
        return _invariants
    if compiled_authority is None:
        raise ValueError(
            "alignment_checker requires compiled_authority or _invariants"
        )
    return extract_invariants_from_authority(compiled_authority)


def validate_feature_alignment(
    feature_title: str,
    compiled_authority: Optional[CompiledSpecAuthority] = None,
    _invariants: Optional[List[str]] = None,
) -> AlignmentResult:
    """
    Validate that a feature request aligns with pinned compiled authority.
    
    Call this at the start of the pipeline to fail-fast on vision violations.
    
    Args:
        feature_title: The requested feature title
        compiled_authority: Compiled spec authority (preferred)
        _invariants: INTERNAL-ONLY invariants extracted from compiled authority
        
    Returns:
        AlignmentResult indicating if the feature can be processed
        
    Example:
        >>> result = validate_feature_alignment(
        ...     "Web-based analytics dashboard",
        ...     _invariants=["FORBIDDEN_CAPABILITY:web"]
        ... )
        >>> result.is_aligned
        False
    """
    invariants_list = _resolve_invariants(compiled_authority, _invariants)
    if not invariants_list or invariants_list == ["No invariants extracted"]:
        return AlignmentResult(
            is_aligned=True,
            alignment_issues=[],
            forbidden_found=[],
            findings=[
                AlignmentFinding(
                    code="NO_INVARIANTS",
                    invariant=None,
                    capability=None,
                    message="No invariants provided for alignment check",
                    severity="warning",
                    created_at=datetime.now(timezone.utc),
                )
            ],
        )
    forbidden = derive_forbidden_capabilities_from_authority(
        compiled_authority,
        invariants=invariants_list,
    )
    if not forbidden:
        return AlignmentResult(
            is_aligned=True,
            alignment_issues=[],
            forbidden_found=[],
            findings=[],
        )
    return check_alignment_violation(feature_title, forbidden, "feature request")


def create_rejection_response(
    feature_title: str,
    alignment_issues: List[str],
    invariants: Optional[List[str]]
) -> Dict[str, Any]:
    """
    Create a structured rejection response for an out-of-scope feature.
    
    Used when a feature fails alignment validation. Returns a response
    that explains why the feature cannot be implemented.
    
    Args:
        feature_title: The rejected feature title
        alignment_issues: List of alignment violation messages
        invariants: Spec invariants for context
        
    Returns:
        Dict with rejection details, matching expected output schema
    """
    return {
        "success": False,
        "is_valid": False,
        "rejected": True,
        "rejection_reason": "Feature violates spec authority forbidden capabilities",
        "alignment_issues": alignment_issues,
        "story": {
            "title": f"[REJECTED] {feature_title}",
            "description": (
                "This feature request cannot be implemented because it violates "
                "spec authority forbidden capabilities. See alignment_issues for details."
            ),
            "acceptance_criteria": None,
            "story_points": None,
        },
        "validation_score": 0,
        "iterations": 0,
        "message": (
            f"Feature '{feature_title}' rejected: violates spec authority. "
            f"Issues: {'; '.join(alignment_issues)}"
        ),
        "invariants_excerpt": (
            "; ".join(invariants)[:200] + "..."
            if invariants and len("; ".join(invariants)) > 200
            else "; ".join(invariants) if invariants else None
        )
    }
