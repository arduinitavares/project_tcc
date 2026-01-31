"""
Persona Checker Module

Provides deterministic validation and enforcement of user personas in stories.
"""
import re
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel

# --- Configuration ---

# Synonyms map: canonical -> [alternatives]
# We map alternatives TO canonical
PERSONA_SYNONYMS: Dict[str, str] = {
    "control engineer": "automation engineer",
    "controls engineer": "automation engineer",
    "scada engineer": "automation engineer",
    "qa engineer": "engineering qa reviewer",
    "qa reviewer": "engineering qa reviewer",
    "ml engineer": "ml engineer",  # Normalize
    "machine learning engineer": "ml engineer",
    "data scientist": "ml engineer",  # Project specific mapping
    "it admin": "it administrator",
    "admin": "it administrator",
    "administrator": "it administrator",
}

# Regex to find "As a [persona]," pattern
# Captures: "As a ", "As an ", then the persona up to comma or " I want"
# Cases:
# "As a developer," -> "developer"
# "As an admin I want" -> "admin"
PERSONA_PATTERN = re.compile(r"As an? ([\w\s]+?)(?:,| I want)", re.IGNORECASE)


class PersonaCheckResult(BaseModel):
    is_valid: bool
    extracted_persona: Optional[str] = None
    violation_message: Optional[str] = None
    corrected_description: Optional[str] = None


def normalize_persona(persona: str) -> str:
    """Normalize persona string for comparison."""
    if not persona:
        return ""
    normalized = persona.lower().strip()

    # Handle plural 's' at end (simplistic, but common in stories)
    # e.g. "As a users" -> "user"
    if normalized.endswith("s") and not normalized.endswith("ss"):
         normalized = normalized[:-1]

    # Resolve synonyms
    return PERSONA_SYNONYMS.get(normalized, normalized)


def extract_persona_from_story(description: str) -> Optional[str]:
    """Extracts the persona from a story description string."""
    if not description:
        return None
    match = PERSONA_PATTERN.search(description)
    if match:
        return match.group(1).strip().lower()
    return None


def are_personas_equivalent(persona1: str, persona2: str) -> bool:
    """Check if two personas are effectively the same."""
    return normalize_persona(persona1) == normalize_persona(persona2)


def validate_persona(
    story_description: str,
    required_persona: str,
    allow_synonyms: bool = True
) -> PersonaCheckResult:
    """
    Validates if the story uses the required persona.
    """
    extracted = extract_persona_from_story(story_description)

    if not extracted:
        return PersonaCheckResult(
            is_valid=False,
            extracted_persona=None,
            violation_message="Could not extract persona from story description (expected 'As a ...')"
        )

    normalized_required = normalize_persona(required_persona)
    normalized_extracted = normalize_persona(extracted)

    is_match = normalized_extracted == normalized_required

    if is_match:
        return PersonaCheckResult(is_valid=True, extracted_persona=extracted)

    # If not a match, it's a violation
    return PersonaCheckResult(
        is_valid=False,
        extracted_persona=extracted,
        violation_message=f"Persona mismatch: expected '{required_persona}', found '{extracted}'"
    )


def _get_article(word: str) -> str:
    """Return 'a' or 'an' appropriate for the word."""
    if not word:
        return "a"
    return "an" if word[0].lower() in "aeiou" else "a"


def auto_correct_persona(story_data: dict, required_persona: str) -> dict:
    """
    Deterministically replaces the persona in the story description.
    Returns a NEW dict with updated description.
    """
    new_story = story_data.copy()
    description = new_story.get("description", "")

    # If we can't find a persona pattern, check if we can prepend it
    extracted = extract_persona_from_story(description)
    if not extracted:
        # Check if it starts with "I want"
        if description.lower().startswith("i want"):
            article = _get_article(required_persona)
            new_desc = f"As {article} {required_persona}, {description}"
            new_story["description"] = new_desc
            return new_story
        # If completely unstructured, we can't safely auto-correct
        return new_story

    # Re-match to get the span
    match = PERSONA_PATTERN.search(description)
    if match:
        # We need to replace match.start() -> match.span(1)[1]
        # match.span(1) is the span of the captured persona
        # match.start() is the start of "As ..."

        p_start, p_end = match.span(1)

        # Construct new prefix: "As {article} {required_persona}"
        article = _get_article(required_persona)
        new_prefix = f"As {article} {required_persona}"

        # Replace the substring from match.start() to p_end with new_prefix
        # description[:match.start()] is what comes before (usually empty)
        # description[p_end:] is what comes after the persona (" I want..." or ", I want...")

        prefix_replaced = description[:match.start()] + new_prefix + description[p_end:]
        new_story["description"] = prefix_replaced

    return new_story
