"""
Story Contract Enforcer - Final deterministic validation stage.

This module provides hard contract enforcement AFTER the LLM refinement loop.
It ensures stories meet non-negotiable requirements before persistence.

Unlike LLM-based validation (which can drift), this is deterministic and strict.

NOTE: INVEST principles are enforced by the Draft Agent's instructions (schema validation).
This contract enforcer focuses on data integrity (feature_id, persona, story_points) and
state consistency (refinement completeness), not INVEST scoring.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass


def normalize_persona_for_comparison(persona: str) -> str:
    """
    Normalize persona for comparison (handles singular/plural, case).
    
    Matches the logic from persona_checker.py to ensure consistency.
    """
    if not persona:
        return ""
    normalized = persona.lower().strip()
    
    # Handle plural 's' at end (e.g., "reviewers" -> "reviewer")
    if normalized.endswith("s") and not normalized.endswith("ss"):
        normalized = normalized[:-1]
    
    return normalized


@dataclass
class ContractViolation:
    """Represents a single contract violation."""

    rule: str  # e.g., "STORY_POINTS_FORBIDDEN"
    message: str  # Human-readable explanation
    field: Optional[str] = None  # Field that violated (if applicable)
    expected: Optional[Any] = None  # Expected value
    actual: Optional[Any] = None  # Actual value


@dataclass
class ContractEnforcementResult:
    """Result of contract enforcement."""

    is_valid: bool
    violations: List[ContractViolation]
    sanitized_story: Optional[Dict[str, Any]] = None  # Story after fixes applied


def enforce_story_points_contract(
    story: Dict[str, Any], include_story_points: bool
) -> Optional[ContractViolation]:
    """
    Rule 1: Story points must be NULL when include_story_points=False.

    Args:
        story: The refined story dict
        include_story_points: User preference

    Returns:
        ContractViolation if rule is broken, None otherwise
    """
    story_points = story.get("story_points")

    if not include_story_points:
        # Points must be NULL/None
        if story_points is not None:
            return ContractViolation(
                rule="STORY_POINTS_FORBIDDEN",
                message=f"Story points must be NULL when include_story_points=false, but found: {story_points}",
                field="story_points",
                expected=None,
                actual=story_points,
            )
    else:
        # Points should be present (1-8 or None if not estimable)
        if story_points is not None and (story_points < 1 or story_points > 8):
            return ContractViolation(
                rule="STORY_POINTS_OUT_OF_RANGE",
                message=f"Story points must be 1-8 or NULL, but found: {story_points}",
                field="story_points",
                expected="1-8 or NULL",
                actual=story_points,
            )

    return None


def enforce_persona_contract(
    story: Dict[str, Any], expected_persona: str
) -> Optional[ContractViolation]:
    """
    Rule 2: Story must use exactly the expected persona.

    Args:
        story: The refined story dict
        expected_persona: The required persona (e.g., "automation engineer")

    Returns:
        ContractViolation if persona is wrong or missing
    """
    description = story.get("description", "").lower()

    # Extract persona from "As a <persona>, I want..." or "As an <persona>, I want..."
    if not (description.startswith("as a ") or description.startswith("as an ")):
        return ContractViolation(
            rule="PERSONA_FORMAT_INVALID",
            message="Story description must start with 'As a <persona>, I want...' or 'As an <persona>, I want...'",
            field="description",
            expected="As a <persona>, I want...",
            actual=description[:50] + "...",
        )

    # Extract the persona portion
    persona_end = description.find(", i want")
    if persona_end == -1:
        return ContractViolation(
            rule="PERSONA_FORMAT_INVALID",
            message="Story description must contain ', I want'",
            field="description",
            expected="As a <persona>, I want...",
            actual=description[:50] + "...",
        )

    # Skip "as a " or "as an "
    if description.startswith("as a "):
        extracted_persona = description[5:persona_end].strip()
    else:  # "as an "
        extracted_persona = description[6:persona_end].strip()

    # Normalize for comparison (lowercase, no extra spaces)
    expected_norm = normalize_persona_for_comparison(expected_persona)
    extracted_norm = normalize_persona_for_comparison(extracted_persona)

    if extracted_norm != expected_norm:
        return ContractViolation(
            rule="PERSONA_MISMATCH",
            message=f"Story must use persona '{expected_persona}', but found '{extracted_persona}'",
            field="description",
            expected=expected_persona,
            actual=extracted_persona,
        )

    return None


def enforce_invest_result_presence(
    validation_result: Optional[Dict[str, Any]]
) -> Optional[ContractViolation]:
    """
    Rule 3a: INVEST validation result must be present and meaningful.
    
    Stories claiming "INVEST-validated" must have actual validation scores.
    A score of 0 or missing validation_result indicates no quality signal.
    
    Args:
        validation_result: INVEST validation result from state
    
    Returns:
        ContractViolation if INVEST result is missing or invalid
    """
    if validation_result is None:
        return ContractViolation(
            rule="INVEST_RESULT_MISSING",
            message="Story marked as validated but INVEST validation result is missing",
            field="validation_result",
            expected="Present validation_result with score",
            actual=None,
        )
    
    validation_score = validation_result.get("validation_score")
    if validation_score is None:
        return ContractViolation(
            rule="INVEST_SCORE_MISSING",
            message="INVEST validation result exists but validation_score is missing",
            field="validation_result.validation_score",
            expected="Numeric score (0-100)",
            actual=None,
        )
    
    # Score of 0 indicates validation didn't run properly
    if validation_score == 0:
        return ContractViolation(
            rule="INVEST_SCORE_ZERO",
            message="INVEST validation score is 0, indicating validation did not run or failed",
            field="validation_result.validation_score",
            expected="Score > 0 (validation ran)",
            actual=0,
        )
    
    return None


def enforce_feature_id_consistency(
    story: Dict[str, Any], expected_feature_id: int
) -> Optional[ContractViolation]:
    """
    Rule 3b: Story feature_id must match the input feature being processed.
    
    Data integrity bug: If story.feature_id != input.feature_id, the story
    will be attached to the wrong feature downstream.
    
    Args:
        story: The refined story dict
        expected_feature_id: The feature ID from the input
    
    Returns:
        ContractViolation if feature IDs don't match
    """
    story_feature_id = story.get("feature_id")
    
    if story_feature_id is None:
        return ContractViolation(
            rule="FEATURE_ID_MISSING",
            message="Story is missing feature_id field",
            field="feature_id",
            expected=expected_feature_id,
            actual=None,
        )
    
    if story_feature_id != expected_feature_id:
        return ContractViolation(
            rule="FEATURE_ID_MISMATCH",
            message=f"Story feature_id ({story_feature_id}) does not match input feature_id ({expected_feature_id}). This will cause data corruption.",
            field="feature_id",
            expected=expected_feature_id,
            actual=story_feature_id,
        )
    
    return None


def enforce_scope_contract(
    feature_time_frame: Optional[str], allowed_scope: Optional[str]
) -> Optional[ContractViolation]:
    """
    Rule 4: Feature must belong to the active scope (e.g., "Now" slice only).

    Args:
        feature_time_frame: The feature's time frame ("Now", "Next", "Later")
        allowed_scope: The allowed scope (e.g., "Now")

    Returns:
        ContractViolation if scope is mismatched or missing
    """
    if allowed_scope is None:
        # No scope restriction
        return None

    if feature_time_frame is None:
        return ContractViolation(
            rule="SCOPE_METADATA_MISSING",
            message="Feature time_frame is missing (required for scope validation)",
            field="time_frame",
            expected=allowed_scope,
            actual=None,
        )

    if feature_time_frame != allowed_scope:
        return ContractViolation(
            rule="SCOPE_MISMATCH",
            message=f"Feature time_frame must be '{allowed_scope}', but found '{feature_time_frame}'",
            field="time_frame",
            expected=allowed_scope,
            actual=feature_time_frame,
        )

    return None


def enforce_validator_state_consistency(
    validation_result: Optional[Dict[str, Any]],
    spec_validation_result: Optional[Dict[str, Any]],
    refinement_result: Optional[Dict[str, Any]],
) -> List[ContractViolation]:
    """
    Rule 4: Validator state must be consistent and complete.

    Checks:
    - Validator outputs are present (not None)
    - No mixed PASS/FAIL signals
    - No leftover suggestions when validation passed
    - No spec violations masked by high INVEST scores

    Args:
        validation_result: INVEST validation result from state
        spec_validation_result: Spec validation result from state
        refinement_result: Refinement result from state

    Returns:
        List of ContractViolations (empty if consistent)
    """
    violations: List[ContractViolation] = []
    
    # MANDATORY: Refinement result must exist
    if refinement_result is None:
        violations.append(
            ContractViolation(
                rule="REFINEMENT_RESULT_MISSING",
                message="Refinement result is missing - story did not complete refinement loop",
                field="refinement_result",
                expected="Present refinement_result",
                actual=None,
            )
        )
        return violations  # Can't check consistency without refinement result

    # Check for mixed signals between INVEST and spec validation
    invest_passed = False
    spec_passed = True  # Spec validation is optional (defaults to pass if not present)

    if validation_result:
        invest_score = validation_result.get("validation_score", 0)
        invest_passed = invest_score >= 90  # Passing threshold

    if spec_validation_result:
        spec_passed = spec_validation_result.get("is_compliant", True)

    # If INVEST passed but spec failed, that's a violation
    if invest_passed and not spec_passed:
        violations.append(
            ContractViolation(
                rule="MIXED_VALIDATION_SIGNALS",
                message="INVEST validation passed (score ≥90) but spec validation failed",
                field="validation_consistency",
                expected="Both INVEST and spec must pass",
                actual=f"INVEST: PASS, Spec: FAIL",
            )
        )

    # Check for leftover suggestions when story is marked valid
    if refinement_result:
        is_valid = refinement_result.get("is_valid", False)
        if is_valid and spec_validation_result:
            suggestions = spec_validation_result.get("suggestions", [])
            if suggestions:
                violations.append(
                    ContractViolation(
                        rule="LEFTOVER_SUGGESTIONS",
                        message=f"Story marked valid but {len(suggestions)} spec suggestions remain unresolved",
                        field="spec_validation_result.suggestions",
                        expected="Empty suggestions when valid",
                        actual=f"{len(suggestions)} suggestions",
                    )
                )

            # Check domain compliance critical gaps
            domain_compliance = spec_validation_result.get("domain_compliance", {})
            critical_gaps = domain_compliance.get("critical_gaps", [])
            if critical_gaps:
                violations.append(
                    ContractViolation(
                        rule="UNRESOLVED_CRITICAL_GAPS",
                        message=f"Story marked valid but {len(critical_gaps)} critical domain gaps remain",
                        field="domain_compliance.critical_gaps",
                        expected="No critical gaps when valid",
                        actual=f"{len(critical_gaps)} gaps: {critical_gaps}",
                    )
                )

    return violations


def enforce_story_contracts(
    story: Dict[str, Any],
    include_story_points: bool,
    expected_persona: str,
    feature_time_frame: Optional[str],
    allowed_scope: Optional[str],
    validation_result: Optional[Dict[str, Any]],
    spec_validation_result: Optional[Dict[str, Any]],
    refinement_result: Optional[Dict[str, Any]],
    expected_feature_id: Optional[int] = None,
) -> ContractEnforcementResult:
    """
    Main entry point: Enforce ALL story contracts.

    This is a deterministic, non-LLM validation stage that runs AFTER refinement.
    If any contract is violated, the story is considered INVALID regardless of
    prior LLM validation scores.

    Args:
        story: The refined story dict
        include_story_points: User preference for story points
        expected_persona: Required persona (e.g., "automation engineer")
        feature_time_frame: Feature's time frame ("Now", "Next", "Later")
        allowed_scope: Allowed scope filter (e.g., "Now" only)
        validation_result: INVEST validation state
        spec_validation_result: Spec validation state
        refinement_result: Refinement state
        expected_feature_id: Expected feature ID for data integrity check

    Returns:
        ContractEnforcementResult with violations (if any)
    """
    violations: List[ContractViolation] = []

    # Rule 1: Story points contract
    story_points_violation = enforce_story_points_contract(story, include_story_points)
    if story_points_violation:
        violations.append(story_points_violation)

    # Rule 2: Persona contract
    persona_violation = enforce_persona_contract(story, expected_persona)
    if persona_violation:
        violations.append(persona_violation)

    # Rule 3: Feature ID consistency (data integrity)
    if expected_feature_id is not None:
        feature_id_violation = enforce_feature_id_consistency(story, expected_feature_id)
        if feature_id_violation:
            violations.append(feature_id_violation)

    # Rule 4: Scope contract
    scope_violation = enforce_scope_contract(feature_time_frame, allowed_scope)
    if scope_violation:
        violations.append(scope_violation)

    # Rule 5: Validator state consistency and completeness
    state_violations = enforce_validator_state_consistency(
        validation_result, spec_validation_result, refinement_result
    )
    violations.extend(state_violations)

    # Sanitize story if possible (strip forbidden fields)
    sanitized_story = story.copy()
    if not include_story_points and sanitized_story.get("story_points") is not None:
        # Strip story points if they shouldn't be there
        sanitized_story["story_points"] = None

    is_valid = len(violations) == 0

    return ContractEnforcementResult(
        is_valid=is_valid, violations=violations, sanitized_story=sanitized_story
    )


def format_contract_violations(violations: List[ContractViolation]) -> str:
    """
    Format violations for display.

    Args:
        violations: List of contract violations

    Returns:
        Formatted string for logging
    """
    if not violations:
        return "No contract violations"

    lines = ["Contract Violations Detected:"]
    for i, v in enumerate(violations, 1):
        lines.append(f"  [{i}] {v.rule}")
        lines.append(f"      {v.message}")
        if v.expected is not None or hasattr(v, "expected"):
            lines.append(f"      Expected: {v.expected}")
        if v.actual is not None or hasattr(v, "actual"):
            lines.append(f"      Actual: {v.actual}")

    return "\n".join(lines)
