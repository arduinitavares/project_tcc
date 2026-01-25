# orchestrator_agent/agent_tools/story_pipeline/persona_checker.py
"""
Deterministic persona enforcement for story generation.

This module provides code-level validation of user story personas,
ensuring stories use the correct persona specified in requirements.
Similar to alignment_checker.py for vision constraints, this prevents
LLM drift toward generic task-based personas.

Key functions:
- extract_persona_from_story: Parse persona from story description
- validate_persona: Check if story uses required persona
- auto_correct_persona: Programmatic persona substitution
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PersonaCheckResult:
    """Result of persona validation."""

    is_valid: bool
    required_persona: str
    extracted_persona: Optional[str]
    violation_message: Optional[str]
    corrected_description: Optional[str]  # Auto-corrected if simple substitution


# --- Regex Patterns ---

# Matches: "As a [persona], I want" or "As an [persona], I want"
PERSONA_PATTERN = r"^As (?:a|an)\s+([^,]+),\s+I want"

# Common synonym groups for persona matching
PERSONA_SYNONYMS: Dict[str, List[str]] = {
    "automation engineer": [
        "automation engineer",
        "control engineer",
        "controls engineer",
        "automation control engineer",
    ],
    "qa reviewer": [
        "qa reviewer",
        "quality reviewer",
        "engineering reviewer",
        "engineering qa reviewer",
    ],
    "ml engineer": ["ml engineer", "machine learning engineer", "ai engineer"],
    "it administrator": ["it administrator", "system administrator", "sysadmin"],
}


def extract_persona_from_story(description: str) -> Optional[str]:
    """
    Extract persona from user story description.

    Parses the standard user story format: "As a [persona], I want..."

    Args:
        description: Story description text

    Returns:
        Extracted persona string, or None if format doesn't match

    Example:
        >>> extract_persona_from_story("As an automation engineer, I want to...")
        'automation engineer'
    """
    if not description:
        return None

    match = re.match(PERSONA_PATTERN, description.strip(), re.IGNORECASE)
    return match.group(1).strip() if match else None


def normalize_persona(persona: str) -> str:
    """
    Normalize persona for comparison.

    Converts to lowercase and maps synonyms to canonical form.

    Args:
        persona: Persona string to normalize

    Returns:
        Normalized persona string
    """
    persona_lower = persona.lower().strip()

    # Check if persona is in synonym groups
    for canonical, synonyms in PERSONA_SYNONYMS.items():
        if persona_lower in synonyms:
            return canonical

    return persona_lower


def are_personas_equivalent(persona1: str, persona2: str) -> bool:
    """
    Check if two personas are equivalent (exact match or synonyms).

    Args:
        persona1: First persona
        persona2: Second persona

    Returns:
        True if personas are equivalent

    Example:
        >>> are_personas_equivalent("automation engineer", "control engineer")
        True
    """
    return normalize_persona(persona1) == normalize_persona(persona2)


def validate_persona(
    story_description: str, required_persona: str, allow_synonyms: bool = True
) -> PersonaCheckResult:
    """
    Validate that story uses the required persona.

    This is a deterministic check that extracts the persona from the story
    description and compares it to the required persona.

    Args:
        story_description: The story description text
        required_persona: The persona that MUST be used
        allow_synonyms: If True, allows equivalent personas (default: True)

    Returns:
        PersonaCheckResult with validation status and optional correction

    Example:
        >>> result = validate_persona(
        ...     "As a data annotator, I want to mark P&ID symbols...",
        ...     "automation engineer"
        ... )
        >>> result.is_valid
        False
        >>> result.violation_message
        "Persona mismatch: expected 'automation engineer', found 'data annotator'"
    """
    extracted = extract_persona_from_story(story_description)

    # Check format compliance
    if not extracted:
        return PersonaCheckResult(
            is_valid=False,
            required_persona=required_persona,
            extracted_persona=None,
            violation_message=(
                "Story does not follow 'As a [persona], I want...' format"
            ),
            corrected_description=None,
        )

    # Exact match check
    if extracted.lower().strip() == required_persona.lower().strip():
        return PersonaCheckResult(
            is_valid=True,
            required_persona=required_persona,
            extracted_persona=extracted,
            violation_message=None,
            corrected_description=None,
        )

    # Synonym matching
    if allow_synonyms and are_personas_equivalent(extracted, required_persona):
        return PersonaCheckResult(
            is_valid=True,
            required_persona=required_persona,
            extracted_persona=extracted,
            violation_message=None,
            corrected_description=None,
        )

    # Violation detected - generate auto-correction
    article = "an" if required_persona[0].lower() in "aeiou" else "a"
    corrected = re.sub(
        PERSONA_PATTERN,
        f"As {article} {required_persona}, I want",
        story_description,
        count=1,
        flags=re.IGNORECASE,
    )

    return PersonaCheckResult(
        is_valid=False,
        required_persona=required_persona,
        extracted_persona=extracted,
        violation_message=(
            f"Persona mismatch: expected '{required_persona}', found '{extracted}'"
        ),
        corrected_description=corrected,
    )


def auto_correct_persona(story_dict: Dict[str, Any], required_persona: str) -> Dict[str, Any]:
    """
    Automatically correct persona in story description.

    Performs in-place correction of the story's persona if a mismatch is detected.

    Args:
        story_dict: Story object with 'description' field
        required_persona: The correct persona to use

    Returns:
        Updated story dict with corrected description

    Example:
        >>> story = {
        ...     "description": "As a software engineer, I want to configure rules..."
        ... }
        >>> corrected = auto_correct_persona(story, "automation engineer")
        >>> corrected['description']
        'As an automation engineer, I want to configure rules...'
    """
    if "description" not in story_dict:
        return story_dict

    result = validate_persona(story_dict["description"], required_persona)

    if not result.is_valid and result.corrected_description:
        story_dict["description"] = result.corrected_description

    return story_dict


# --- Persona Registry Helpers ---


def get_approved_personas(product_id: int, db_session: Any) -> List[str]:
    """
    Fetch approved personas for a product from the database.

    This function integrates with the ProductPersona table when implemented.
    For now, returns a default list.

    Args:
        product_id: Product ID
        db_session: SQLModel session

    Returns:
        List of approved persona names

    Note:
        Requires ProductPersona table implementation (Tier 3).
    """
    # TODO: Implement database query when ProductPersona table exists
    # Example query:
    # from agile_sqlmodel import ProductPersona
    # from sqlmodel import select
    #
    # personas = db_session.exec(
    #     select(ProductPersona.persona_name)
    #     .where(ProductPersona.product_id == product_id)
    # ).all()
    # return list(personas)

    # Temporary fallback - return common personas
    return [
        "automation engineer",
        "engineering QA reviewer",
        "ML engineer",
        "IT administrator",
    ]


def validate_persona_from_registry(
    product_id: int, requested_persona: str, db_session: Any
) -> tuple[bool, Optional[str]]:
    """
    Check if persona is approved for this product.

    Args:
        product_id: Product ID
        requested_persona: Persona to validate
        db_session: SQLModel session

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> is_valid, error = validate_persona_from_registry(1, "data scientist", session)
        >>> is_valid
        False
        >>> error
        "Persona 'data scientist' not approved. Use: ['automation engineer', ...]"
    """
    approved_personas = get_approved_personas(product_id, db_session)

    # Normalize for comparison
    requested_normalized = normalize_persona(requested_persona)
    approved_normalized = [normalize_persona(p) for p in approved_personas]

    if requested_normalized in approved_normalized:
        return True, None

    return (
        False,
        f"Persona '{requested_persona}' not approved. Use: {approved_personas}",
    )


# --- Batch Correction Helpers ---


def detect_generic_personas(description: str) -> bool:
    """
    Detect if story uses a generic task-based persona instead of domain-specific one.

    Common generic personas that indicate drift:
    - Data annotator (should be: automation engineer performing review)
    - Software engineer (should be: automation engineer configuring)
    - Frontend developer (should be: automation engineer using UI)
    - Data scientist (should be: ML engineer for model work, automation engineer for analysis)

    Args:
        description: Story description to check

    Returns:
        True if generic persona detected

    Example:
        >>> detect_generic_personas("As a data annotator, I want...")
        True
        >>> detect_generic_personas("As an automation engineer, I want...")
        False
    """
    GENERIC_PERSONAS = [
        "data annotator",
        "software engineer",
        "frontend developer",
        "backend developer",
        "data scientist",
        "qa engineer",  # Too generic - use "engineering QA reviewer"
        "developer",
        "user",  # Too vague unless intentional
        "customer",
    ]

    extracted = extract_persona_from_story(description)
    if not extracted:
        return False

    return extracted.lower().strip() in GENERIC_PERSONAS


def suggest_persona_replacement(generic_persona: str, context: str = "") -> Optional[str]:
    """
    Suggest correct persona based on generic persona and context.

    Args:
        generic_persona: The generic persona found
        context: Additional context (feature title, description)

    Returns:
        Suggested persona, or None if no clear suggestion

    Example:
        >>> suggest_persona_replacement("data annotator", "review P&ID symbols")
        'automation engineer'
    """
    REPLACEMENT_MAP = {
        "data annotator": "automation engineer",
        "software engineer": "automation engineer",
        "frontend developer": "automation engineer",
        "backend developer": "automation engineer",
        "qa engineer": "engineering QA reviewer",
        "developer": "automation engineer",
    }

    # Check for ML/training context
    ml_keywords = ["train", "model", "machine learning", "ai", "neural"]
    if any(kw in context.lower() for kw in ml_keywords):
        return "ML engineer"

    # Check for admin context
    admin_keywords = ["deploy", "security", "permissions", "user management"]
    if any(kw in context.lower() for kw in admin_keywords):
        return "IT administrator"

    return REPLACEMENT_MAP.get(generic_persona.lower().strip())
