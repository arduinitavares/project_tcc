"""
End-to-end conceptual demonstration of SPEC → COMPILED AUTHORITY → DETERMINISTIC GATE.

This file is NOT about production architecture.
It exists to make the data transformations visible and understandable.

Key principle demonstrated:
- Natural language is interpreted ONCE (by humans / LLMs).
- The output of that interpretation is a typed, frozen authority.
- Validation is deterministic and domain-agnostic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


# =============================================================================
# Phase 1 — Compiled Authority (output of human / LLM interpretation)
# =============================================================================

# IMPORTANT:
# These invariants are NOT parsed from text here.
# They are the result of a prior interpretation step that is allowed to be fuzzy.
# Once written here, they are treated as ground truth.

COMPILED_INVARIANTS_SOFTWARE = [
    {
        "id": "INV-002",
        "type": "FORBIDDEN_CAPABILITY",
        "capability": "OAuth1",
        "origin": "Spec v3: 'OAuth1 is no longer supported'",
    }
]

COMPILED_INVARIANTS_CONSTRUCTION = [
    {
        "id": "INV-901",
        "type": "FORBIDDEN_CAPABILITY",
        "capability": "Asbestos",
        "origin": "Spec v7: 'Asbestos insulation must not be used'",
    },
    {
        "id": "INV-902",
        "type": "REQUIRED_FIELD",
        "field": "permit_id",
        "origin": "Spec v7: 'All construction must have a permit'",
    },
]


# =============================================================================
# Phase 2 — Deterministic Validation Artifacts
# =============================================================================

@dataclass(frozen=True)
class Finding:
    """Deterministic validation finding."""
    code: str
    message: str
    severity: str  # "FAIL" | "WARN"


@dataclass(frozen=True)
class ValidationResult:
    """Deterministic validation result."""
    passed: bool
    findings: tuple[Finding, ...]


def _serialize_result(result: ValidationResult) -> dict[str, Any]:
    """Serialize ValidationResult to JSON-safe dict."""
    return {
        "passed": result.passed,
        "findings": [asdict(finding) for finding in result.findings],
    }


# =============================================================================
# Phase 3 — Deterministic Gate (NO text parsing, NO LLM, NO human judgment)
# =============================================================================

def validate_against_invariants(
    *,
    item: dict[str, Any],
    invariants: list[dict[str, Any]],
) -> ValidationResult:
    """
    Deterministic validator over structured inputs + typed invariants.

    CRITICAL:
    - This function does NOT read natural language.
    - It does NOT know what 'OAuth1' or 'Asbestos' means.
    - It ONLY compares structured values.
    """
    findings: list[Finding] = []

    # Convention: items declare "capabilities" explicitly.
    capabilities = set(item.get("capabilities", []))

    for inv in invariants:
        inv_type = inv["type"]

        if inv_type == "FORBIDDEN_CAPABILITY":
            forbidden = inv["capability"]
            if forbidden in capabilities:
                findings.append(
                    Finding(
                        code=inv["id"],
                        message=f"Forbidden capability used: {forbidden}",
                        severity="FAIL",
                    )
                )

        elif inv_type == "REQUIRED_FIELD":
            field_name = inv["field"]
            if field_name not in item or item[field_name] in (None, ""):
                findings.append(
                    Finding(
                        code=inv["id"],
                        message=f"Missing required field: {field_name}",
                        severity="FAIL",
                    )
                )

        else:
            # This is intentional:
            # New rule types require explicit implementation.
            raise ValueError(f"Unknown invariant type: {inv_type}")

    passed = all(f.severity != "FAIL" for f in findings)
    return ValidationResult(passed=passed, findings=tuple(findings))


# =============================================================================
# Phase 4 — Examples (Same Gate, Different Domains)
# =============================================================================

def test_software_story_fails_deterministically() -> None:
    """
    Software domain example.

    INPUT:
    - Compiled invariant: OAuth1 is forbidden
    - Story explicitly declares OAuth1

    OUTPUT:
    - Deterministic failure
    """
    story = {
        "title": "Implement login",
        "capabilities": ["OAuth1"],
    }

    result = validate_against_invariants(
        item=story,
        invariants=COMPILED_INVARIANTS_SOFTWARE,
    )

    assert result.passed is False
    assert result.findings[0].code == "INV-002"


def test_construction_plan_fails_for_same_reason_shape() -> None:
    """
    Construction domain example.

    SAME invariant type.
    DIFFERENT string value.
    SAME validator.
    """
    build_plan = {
        "title": "Select insulation",
        "capabilities": ["Asbestos"],
    }

    result = validate_against_invariants(
        item=build_plan,
        invariants=COMPILED_INVARIANTS_CONSTRUCTION,
    )

    assert result.passed is False
    assert result.findings[0].code == "INV-901"


def test_required_field_is_domain_agnostic() -> None:
    """
    REQUIRED_FIELD works identically across domains.

    The gate does not know what a permit is.
    It only knows that the field is required.
    """
    build_plan = {
        "title": "Start construction",
        "capabilities": ["Excavation"],
        # missing permit_id
    }

    result = validate_against_invariants(
        item=build_plan,
        invariants=COMPILED_INVARIANTS_CONSTRUCTION,
    )

    assert result.passed is False
    assert result.findings[0].code == "INV-902"


def build_demo_artifacts() -> dict[str, Any]:
    """Build demo inputs and deterministic results for artifact export."""
    story = {
        "title": "Implement login",
        "capabilities": ["OAuth1"],
    }
    story_result = validate_against_invariants(
        item=story,
        invariants=COMPILED_INVARIANTS_SOFTWARE,
    )

    build_plan_forbidden = {
        "title": "Select insulation",
        "capabilities": ["Asbestos"],
    }
    build_plan_forbidden_result = validate_against_invariants(
        item=build_plan_forbidden,
        invariants=COMPILED_INVARIANTS_CONSTRUCTION,
    )

    build_plan_missing_field = {
        "title": "Start construction",
        "capabilities": ["Excavation"],
    }
    build_plan_missing_field_result = validate_against_invariants(
        item=build_plan_missing_field,
        invariants=COMPILED_INVARIANTS_CONSTRUCTION,
    )

    return {
        "software_example": {
            "input": story,
            "invariants": COMPILED_INVARIANTS_SOFTWARE,
            "result": _serialize_result(story_result),
        },
        "construction_forbidden_example": {
            "input": build_plan_forbidden,
            "invariants": COMPILED_INVARIANTS_CONSTRUCTION,
            "result": _serialize_result(build_plan_forbidden_result),
        },
        "construction_required_field_example": {
            "input": build_plan_missing_field,
            "invariants": COMPILED_INVARIANTS_CONSTRUCTION,
            "result": _serialize_result(build_plan_missing_field_result),
        },
    }


def save_artifacts(output_dir: Path) -> list[Path]:
    """Save demo artifacts to disk as JSON files.

    Args:
        output_dir: Folder where artifacts are written.

    Returns:
        List of paths written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = build_demo_artifacts()
    written_paths: list[Path] = []

    for key, payload in artifacts.items():
        path = output_dir / f"{key}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written_paths.append(path)

    return written_paths


def main() -> None:
    """Run the deterministic gate demo and write artifacts to disk."""
    output_dir = Path(__file__).resolve().parents[1] / "artifacts" / "generate_example"
    written = save_artifacts(output_dir)
    print(f"Wrote {len(written)} artifacts to: {output_dir}")
    for path in written:
        print(f"- {path.name}")


if __name__ == "__main__":
    main()
