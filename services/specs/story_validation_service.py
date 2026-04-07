"""Public helpers for spec-backed story validation support."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from models.core import Feature
from models.core import UserStory
from models.db import get_engine
from models.specs import CompiledSpecAuthority, SpecRegistry
from services.specs.compiler_service import load_compiled_artifact
from orchestrator_agent.agent_tools.spec_validator_agent.agent import (
    root_agent as spec_validator_agent,
)
from utils.spec_schemas import (
    AlignmentFinding,
    Invariant,
    InvariantType,
    ValidationEvidence,
    ValidationFailure,
)
from utils.adk_runner import invoke_agent_to_text
from utils.runtime_config import SPEC_VALIDATOR_IDENTITY, get_default_validation_mode


logger = logging.getLogger(__name__)
_DEFAULT_GET_ENGINE = get_engine

DEFAULT_VALIDATION_MODE_ENV = "SPEC_VALIDATION_DEFAULT_MODE"
_VALIDATION_MODES = {"deterministic", "llm", "hybrid"}


class ValidateStoryInput(BaseModel):
    """Input schema for validate_story_with_spec_authority service."""

    story_id: int = Field(description="Story ID to validate")
    spec_version_id: int = Field(
        description="Spec version ID to validate against (REQUIRED)"
    )
    mode: Literal["deterministic", "llm", "hybrid"] = Field(
        default="deterministic",
        description=(
            "Validation mode: deterministic (rule-based), llm (spec_validator_agent), "
            "or hybrid (both)."
        ),
    )


def compute_story_input_hash(story: Any) -> str:
    """Compute deterministic SHA-256 hash of story content."""
    content = json.dumps(
        {
            "title": getattr(story, "title", "") or "",
            "description": getattr(story, "story_description", "") or "",
            "acceptance_criteria": getattr(story, "acceptance_criteria", "") or "",
        },
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode()).hexdigest()


def resolve_default_validation_mode() -> str:
    """Resolve default validation mode from environment with safe fallback."""
    raw_value = get_default_validation_mode("deterministic").strip().lower()
    if raw_value in _VALIDATION_MODES:
        return raw_value
    logger.warning(
        "Invalid %s=%r; falling back to 'deterministic'",
        DEFAULT_VALIDATION_MODE_ENV,
        raw_value,
    )
    return "deterministic"


def persist_validation_evidence(
    session: Session,
    story: UserStory,
    evidence: ValidationEvidence,
    passed: bool,
) -> None:
    """Persist validation evidence and update accepted spec version on pass."""
    story.validation_evidence = evidence.model_dump_json()
    if passed:
        story.accepted_spec_version_id = evidence.spec_version_id
    session.add(story)
    session.commit()


def _resolve_tool_helper(name: str) -> Any | None:
    """Resolve the current tool-level helper for compatibility seams."""
    try:
        from tools import spec_tools  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None
    return getattr(spec_tools, name, None)


def _run_async_task(coro: Any) -> Any:
    """Run an async coroutine from sync code, even if a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, Exception] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # pylint: disable=broad-except
            error["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error:
        raise error["error"]
    return result.get("value")


def _resolve_engine():
    """Preserve the legacy spec_tools.engine monkeypatch seam for tests."""
    from services.specs._engine_resolution import resolve_spec_engine

    return resolve_spec_engine(
        service_get_engine=get_engine,
        default_service_get_engine=_DEFAULT_GET_ENGINE,
    )


def _render_invariant_summary(invariant: Invariant) -> str:
    """Render a structured invariant into a stable string for consumers."""
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


def render_invariant_summary(invariant: Invariant) -> str:
    """Public helper for invariant rendering used by legacy adapters."""
    return _render_invariant_summary(invariant)


def _split_story_segments(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?;:])\s+|\n+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _build_capability_pattern(capability: str) -> re.Pattern[str] | None:
    tokens = [
        re.escape(token)
        for token in re.split(r"[\s_]+", capability.strip().lower())
        if token
    ]
    if not tokens:
        return None
    return re.compile(r"\b" + r"[\s_-]+".join(tokens) + r"\b", flags=re.IGNORECASE)


def _is_policy_only_capability_context(segment: str) -> bool:
    policy_context_patterns = (
        re.compile(r"\bplagiarism policy\b", flags=re.IGNORECASE),
        re.compile(r"\bacademic integrity\b", flags=re.IGNORECASE),
        re.compile(r"\bcitation\b", flags=re.IGNORECASE),
        re.compile(r"\bappropriate(?:ly)? cited?\b", flags=re.IGNORECASE),
        re.compile(r"\bwithout appropriate citation\b", flags=re.IGNORECASE),
        re.compile(r"\brubric\b", flags=re.IGNORECASE),
        re.compile(r"\bgrading\b", flags=re.IGNORECASE),
        re.compile(r"\bsubmission instructions?\b", flags=re.IGNORECASE),
        re.compile(r"\bsubmission requirements?\b", flags=re.IGNORECASE),
    )
    integrity_enforcement_patterns = (
        re.compile(r"\bdetect(?:ion)?\b", flags=re.IGNORECASE),
        re.compile(r"\bchecker\b", flags=re.IGNORECASE),
        re.compile(r"\bscan(?:ning)?\b", flags=re.IGNORECASE),
        re.compile(r"\bflag\b", flags=re.IGNORECASE),
        re.compile(r"\bprevent\b", flags=re.IGNORECASE),
        re.compile(r"\bblock\b", flags=re.IGNORECASE),
        re.compile(r"\benforce\b", flags=re.IGNORECASE),
        re.compile(r"\bmonitor(?:ing)?\b", flags=re.IGNORECASE),
        re.compile(r"\bverify\b", flags=re.IGNORECASE),
        re.compile(r"\bscore\b", flags=re.IGNORECASE),
        re.compile(r"\bcompare\b", flags=re.IGNORECASE),
    )
    if not segment:
        return False
    if not any(pattern.search(segment) for pattern in policy_context_patterns):
        return False
    return not any(pattern.search(segment) for pattern in integrity_enforcement_patterns)


def _story_mentions_forbidden_capability(
    *,
    story_segments: list[str],
    combined_text: str,
    capability: str,
) -> bool:
    pattern = _build_capability_pattern(capability)
    if pattern is None:
        return False

    if not pattern.search(combined_text):
        return False

    for segment in story_segments:
        if not pattern.search(segment):
            continue
        if _is_policy_only_capability_context(segment):
            continue
        return True

    return False


def run_structural_story_checks(
    story: UserStory,
) -> tuple[list[str], list[ValidationFailure], list[str]]:
    """Run deterministic structural story checks used by all validation modes."""
    rules_checked: list[str] = []
    failures: list[ValidationFailure] = []
    warnings: list[str] = []

    rules_checked.append("RULE_TITLE_REQUIRED")
    if not story.title or not story.title.strip():
        failures.append(
            ValidationFailure(
                rule="RULE_TITLE_REQUIRED",
                expected="Non-empty title",
                actual="Empty or missing",
                message="Story must have a title",
            )
        )

    rules_checked.append("RULE_ACCEPTANCE_CRITERIA_REQUIRED")
    if not story.acceptance_criteria or not story.acceptance_criteria.strip():
        failures.append(
            ValidationFailure(
                rule="RULE_ACCEPTANCE_CRITERIA_REQUIRED",
                expected="Non-empty acceptance criteria",
                actual="Empty or missing",
                message="Story must have acceptance criteria",
            )
        )

    rules_checked.append("RULE_PERSONA_FORMAT")
    title_lower = (story.title or "").lower()
    desc_lower = (story.story_description or "").lower()
    acceptance_lower = (story.acceptance_criteria or "").lower()
    if not (
        "as a " in title_lower
        or "as a " in desc_lower
        or "as an " in title_lower
        or "as an " in desc_lower
    ):
        warnings.append("Story does not follow 'As a [persona], I want...' format")

    rules_checked.append("RULE_CONTRADICTORY_CONNECTIVITY_REQUIREMENTS")
    combined_text = " ".join(
        part for part in [title_lower, desc_lower, acceptance_lower] if part
    )
    if "offline" in combined_text and "cloud sync" in combined_text:
        failures.append(
            ValidationFailure(
                rule="RULE_CONTRADICTORY_CONNECTIVITY_REQUIREMENTS",
                expected="Connectivity requirements are internally consistent",
                actual="Story requires both offline operation and cloud sync dependency",
                message=(
                    "Story contains contradictory connectivity requirements "
                    "(offline operation vs cloud sync dependency)"
                ),
            )
        )

    rules_checked.append("RULE_IMPOSSIBLE_LATENCY_REQUIREMENT")
    if re.search(
        r"\b(?:under|below|less than|<=?|at most)\s*0\s*ms\b",
        acceptance_lower,
    ) or "0ms (impossible)" in acceptance_lower:
        failures.append(
            ValidationFailure(
                rule="RULE_IMPOSSIBLE_LATENCY_REQUIREMENT",
                expected="Latency constraints are physically plausible",
                actual="Latency constraint requires <= 0ms",
                message="Story defines an impossible latency requirement (<= 0ms)",
            )
        )

    rules_checked.append("RULE_ACCEPTANCE_CRITERIA_SCOPE_MISMATCH")
    normalized_acceptance = " ".join(acceptance_lower.split())
    if (
        "out of scope feature request." in desc_lower
        and normalized_acceptance.startswith("given item, when add, then in cart")
    ):
        failures.append(
            ValidationFailure(
                rule="RULE_ACCEPTANCE_CRITERIA_SCOPE_MISMATCH",
                expected="Acceptance criteria align with story scope",
                actual="Story scope and acceptance criteria describe different domains",
                message="Acceptance criteria appear to be copied from an unrelated scope",
            )
        )

    return rules_checked, failures, warnings


def run_deterministic_alignment_checks(
    story: UserStory,
    authority: CompiledSpecAuthority,
    *,
    load_compiled_artifact_fn: Callable[[CompiledSpecAuthority], Any | None] = load_compiled_artifact,
) -> tuple[list[AlignmentFinding], list[AlignmentFinding], list[str]]:
    """Run deterministic alignment checks against compiled authority."""
    alignment_failures: list[AlignmentFinding] = []
    alignment_warnings: list[AlignmentFinding] = []
    warnings: list[str] = []

    artifact = load_compiled_artifact_fn(authority) if callable(load_compiled_artifact_fn) else None
    if not artifact or not getattr(artifact, "invariants", None):
        return alignment_failures, alignment_warnings, warnings

    title_text = (story.title or "").lower()
    description_text = (story.story_description or "").lower()
    acceptance_text = (story.acceptance_criteria or "").lower()
    combined_text = " ".join(
        part for part in [title_text, description_text, acceptance_text] if part
    )
    normalized_acceptance = acceptance_text.replace("_", " ")
    story_segments = [
        segment
        for part in [story.title or "", story.story_description or "", story.acceptance_criteria or ""]
        for segment in _split_story_segments(part)
    ]

    for invariant in artifact.invariants:
        if invariant.type == InvariantType.FORBIDDEN_CAPABILITY:
            capability = str(getattr(invariant.parameters, "capability", "") or "").strip()
            if not capability:
                continue
            if _story_mentions_forbidden_capability(
                story_segments=story_segments,
                combined_text=combined_text,
                capability=capability,
            ):
                alignment_failures.append(
                    AlignmentFinding(
                        code="FORBIDDEN_CAPABILITY",
                        invariant=invariant.id,
                        capability=capability,
                        message=(
                            f"Story references forbidden capability '{capability}' "
                            f"(invariant {invariant.id})."
                        ),
                        severity="failure",
                        created_at=datetime.now(timezone.utc),
                    )
                )
            continue

        if invariant.type == InvariantType.REQUIRED_FIELD:
            field_name = str(getattr(invariant.parameters, "field_name", "") or "").strip()
            if not field_name:
                continue
            field_lower = field_name.lower()
            field_variants = {
                field_lower,
                field_lower.replace("_", " "),
            }
            has_field_mention = any(
                variant and (variant in acceptance_text or variant in normalized_acceptance)
                for variant in field_variants
            )
            if not has_field_mention:
                alignment_warnings.append(
                    AlignmentFinding(
                        code="REQUIRED_FIELD_MISSING",
                        invariant=invariant.id,
                        capability=None,
                        message=(
                            f"Acceptance criteria may be missing required field "
                            f"'{field_name}' (invariant {invariant.id})."
                        ),
                        severity="warning",
                        created_at=datetime.now(timezone.utc),
                    )
                )
            continue

        if invariant.type == InvariantType.MAX_VALUE:
            continue

    return alignment_failures, alignment_warnings, warnings


async def invoke_spec_validator_async(payload_text: str) -> str:
    """Invoke spec_validator_agent and return response text."""
    return await invoke_agent_to_text(
        agent=spec_validator_agent,
        runner_identity=SPEC_VALIDATOR_IDENTITY,
        payload_json=payload_text,
        no_text_error="Spec validator agent returned no text response",
    )


def parse_llm_validator_response(raw_text: str) -> dict[str, Any]:
    """Parse agent text into SpecValidationResult shape."""
    from orchestrator_agent.agent_tools.spec_validator_agent.schemes import (
        SpecValidationResult,
    )

    candidate = raw_text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)

    try:
        parsed = SpecValidationResult.model_validate_json(candidate)
        critical_gaps: list[str] = []
        if parsed.domain_compliance and parsed.domain_compliance.critical_gaps:
            critical_gaps = list(parsed.domain_compliance.critical_gaps)
        return {
            "passed": parsed.is_compliant,
            "issues": list(parsed.issues),
            "suggestions": list(parsed.suggestions),
            "verdict": parsed.verdict,
            "critical_gaps": critical_gaps,
        }
    except ValidationError as exc:
        compliant_match = re.search(
            r'"is_compliant"\s*:\s*(true|false)',
            candidate,
            flags=re.IGNORECASE,
        )
        if not compliant_match:
            raise ValueError("Unable to parse LLM validator response") from exc

        def _extract_string_list(field_name: str) -> list[str]:
            pattern = rf'"{re.escape(field_name)}"\s*:\s*\[(.*?)(?:\]|$)'
            list_match = re.search(pattern, candidate, flags=re.DOTALL)
            if not list_match:
                return []
            raw_items = re.findall(r'"((?:\\.|[^"\\])*)"', list_match.group(1))
            values: list[str] = []
            for raw_item in raw_items:
                try:
                    values.append(json.loads(f'"{raw_item}"'))
                except json.JSONDecodeError:
                    values.append(raw_item)
            return values

        def _extract_string(field_name: str) -> str | None:
            pattern = rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"'
            value_match = re.search(pattern, candidate, flags=re.DOTALL)
            if not value_match:
                return None
            try:
                return json.loads(f'"{value_match.group(1)}"')
            except json.JSONDecodeError:
                return value_match.group(1)

        is_compliant = compliant_match.group(1).lower() == "true"
        issues = _extract_string_list("issues")
        critical_gaps = _extract_string_list("critical_gaps")
        suggestions = _extract_string_list("suggestions")
        verdict = _extract_string("verdict") or "Recovered from truncated JSON response"

        if is_compliant:
            issues = []
            critical_gaps = []
            suggestions = []
        elif not issues and critical_gaps:
            # Preserve non-compliant semantics when only critical gaps were recoverable.
            issues = list(critical_gaps)

        if not is_compliant and not issues:
            raise ValueError("Unable to recover non-compliant LLM validator response") from exc

        logger.warning("Recovered partial LLM response (truncated JSON)")
        return {
            "passed": is_compliant,
            "issues": issues,
            "suggestions": suggestions,
            "verdict": verdict,
            "critical_gaps": critical_gaps,
        }


def run_llm_spec_validation(
    story: UserStory,
    authority: CompiledSpecAuthority,
    artifact: ValidationEvidence | Any | None,
    feature: Feature | None = None,
    *,
    invoke_spec_validator_async_fn: Callable[[str], Any] | None = None,
    parse_llm_validator_response_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run LLM-based spec validation and normalize result."""
    invoke_async = invoke_spec_validator_async_fn or invoke_spec_validator_async
    parse_response = parse_llm_validator_response_fn or parse_llm_validator_response

    authority_json = authority.compiled_artifact_json or ""
    if artifact:
        authority_json = artifact.model_dump_json()

    payload = {
        "story_title": story.title or "",
        "story_description": story.story_description or "",
        "acceptance_criteria": story.acceptance_criteria or "",
        "compiled_authority_json": authority_json,
        "spec_version_id": authority.spec_version_id,
        "feature_title": feature.title if feature else None,
        "feature_description": feature.description if feature else None,
    }
    raw_text = _run_async_task(invoke_async(json.dumps(payload)))
    return parse_response(raw_text)


def validate_story_with_spec_authority(
    params: dict[str, Any] | ValidateStoryInput,
    *,
    tool_context: ToolContext | None = None,  # pylint: disable=unused-argument
    resolve_default_validation_mode: Callable[[], str] | None = None,
    compute_story_input_hash_fn: Callable[[UserStory], str] | None = None,
    persist_validation_evidence: (
        Callable[[Session, UserStory, ValidationEvidence, bool], None] | None
    ) = None,
    run_structural_story_checks: (
        Callable[[UserStory], tuple[list[str], list[ValidationFailure], list[str]]] | None
    ) = None,
    run_deterministic_alignment_checks: (
        Callable[
            [UserStory, CompiledSpecAuthority],
            tuple[list[AlignmentFinding], list[AlignmentFinding], list[str]],
        ]
        | None
    ) = None,
    run_llm_spec_validation: (
        Callable[
            [UserStory, CompiledSpecAuthority, Any, Feature | None],
            dict[str, Any],
        ]
        | None
    ) = None,
    load_compiled_artifact_fn: Callable[[CompiledSpecAuthority], Any | None] | None = None,
    render_invariant_summary_fn: Callable[[Invariant], str] | None = None,
    validator_version: str = "1.0.0",
) -> dict[str, Any]:
    """Validate a story against an explicit spec version."""
    raw_params = dict(params or {})
    default_mode = resolve_default_validation_mode or globals()[
        "resolve_default_validation_mode"
    ]
    if "mode" not in raw_params:
        raw_params["mode"] = default_mode() if callable(default_mode) else "deterministic"
    parsed = ValidateStoryInput.model_validate(raw_params)

    compute_input_hash = compute_story_input_hash_fn or compute_story_input_hash
    persist_evidence = persist_validation_evidence or globals()[
        "persist_validation_evidence"
    ]
    llm_validation = run_llm_spec_validation or globals()["run_llm_spec_validation"]
    load_artifact = load_compiled_artifact_fn or load_compiled_artifact
    render_invariant = render_invariant_summary_fn or render_invariant_summary
    structural_checks = run_structural_story_checks or globals()[
        "run_structural_story_checks"
    ]
    deterministic_checks = (
        run_deterministic_alignment_checks
        or globals()["run_deterministic_alignment_checks"]
    )

    with Session(_resolve_engine()) as session:
        story = session.get(UserStory, parsed.story_id)
        if not story:
            return {
                "success": False,
                "error": f"Story {parsed.story_id} not found",
            }

        input_hash = compute_input_hash(story)

        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            evidence = ValidationEvidence(
                spec_version_id=parsed.spec_version_id,
                validated_at=datetime.now(timezone.utc),
                passed=False,
                rules_checked=["SPEC_VERSION_EXISTS"],
                invariants_checked=[],
                evaluated_invariant_ids=[],
                finding_invariant_ids=[],
                failures=[
                    ValidationFailure(
                        rule="SPEC_VERSION_EXISTS",
                        expected="Spec version exists",
                        actual="Not found",
                        message=f"Spec version {parsed.spec_version_id} not found",
                    )
                ],
                warnings=[],
                alignment_warnings=[],
                alignment_failures=[],
                validator_version=validator_version,
                input_hash=input_hash,
            )
            if callable(persist_evidence):
                persist_evidence(session, story, evidence, passed=False)
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found",
                "passed": False,
                "input_hash": input_hash,
            }

        if spec_version.product_id != story.product_id:
            evidence = ValidationEvidence(
                spec_version_id=parsed.spec_version_id,
                validated_at=datetime.now(timezone.utc),
                passed=False,
                rules_checked=["SPEC_PRODUCT_MATCH"],
                invariants_checked=[],
                evaluated_invariant_ids=[],
                finding_invariant_ids=[],
                failures=[
                    ValidationFailure(
                        rule="SPEC_PRODUCT_MATCH",
                        expected=f"Product {story.product_id}",
                        actual=f"Product {spec_version.product_id}",
                        message=(
                            "Spec version belongs to a different product "
                            f"(expected {story.product_id}, got {spec_version.product_id})"
                        ),
                    )
                ],
                warnings=[],
                alignment_warnings=[],
                alignment_failures=[],
                validator_version=validator_version,
                input_hash=input_hash,
            )
            if callable(persist_evidence):
                persist_evidence(session, story, evidence, passed=False)
            return {
                "success": False,
                "error": (
                    f"Product mismatch: story belongs to product {story.product_id}, "
                    f"but spec version {parsed.spec_version_id} belongs to product "
                    f"{spec_version.product_id}"
                ),
                "passed": False,
                "input_hash": input_hash,
            }

        authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == parsed.spec_version_id
            )
        ).first()

        if not authority:
            evidence = ValidationEvidence(
                spec_version_id=parsed.spec_version_id,
                validated_at=datetime.now(timezone.utc),
                passed=False,
                rules_checked=["SPEC_VERSION_COMPILED"],
                invariants_checked=[],
                evaluated_invariant_ids=[],
                finding_invariant_ids=[],
                failures=[
                    ValidationFailure(
                        rule="SPEC_VERSION_COMPILED",
                        expected="Compiled authority exists",
                        actual="Not compiled",
                        message=(
                            f"spec_version_id {parsed.spec_version_id} is not compiled"
                        ),
                    )
                ],
                warnings=[],
                alignment_warnings=[],
                alignment_failures=[],
                validator_version=validator_version,
                input_hash=input_hash,
            )
            if callable(persist_evidence):
                persist_evidence(session, story, evidence, passed=False)
            return {
                "success": False,
                "error": f"spec_version_id {parsed.spec_version_id} is not compiled",
                "passed": False,
                "input_hash": input_hash,
            }

        artifact = load_artifact(authority) if callable(load_artifact) else None
        invariants_checked: list[str] = []
        if artifact and getattr(artifact, "invariants", None):
            invariants_checked = [
                render_invariant(inv)
                for inv in artifact.invariants
                if inv.type in ("FORBIDDEN_CAPABILITY", "REQUIRED_FIELD")
            ]

        rules_checked, failures, warnings = structural_checks(story)

        alignment_failures: list[AlignmentFinding] = []
        alignment_warnings: list[AlignmentFinding] = []
        if not invariants_checked:
            no_invariants_message = (
                "Compiled authority has no invariants; alignment checks are informational only."
            )
            warnings.append(no_invariants_message)
            alignment_warnings.append(
                AlignmentFinding(
                    code="NO_INVARIANTS",
                    invariant=None,
                    capability=None,
                    message=no_invariants_message,
                    severity="warning",
                    created_at=datetime.now(timezone.utc),
                )
            )

        if parsed.mode in ("deterministic", "hybrid"):
            (
                deterministic_failures,
                deterministic_warnings,
                deterministic_messages,
            ) = deterministic_checks(
                story,
                authority,
                load_compiled_artifact_fn=load_artifact,
            )
            alignment_failures.extend(deterministic_failures)
            alignment_warnings.extend(deterministic_warnings)
            warnings.extend(deterministic_messages)

        if parsed.mode in ("llm", "hybrid"):
            rules_checked.append("RULE_LLM_SPEC_VALIDATION")
            try:
                feature = None
                if story.feature_id is not None:
                    feature = session.get(Feature, story.feature_id)

                llm_result = llm_validation(
                    story,
                    authority,
                    artifact,
                    feature=feature,
                )
                llm_issues = list(llm_result.get("issues", []))
                llm_critical_gaps = list(llm_result.get("critical_gaps", []))

                if (
                    not llm_result.get("passed", False)
                    and not llm_critical_gaps
                    and not llm_issues
                ):
                    verdict = llm_result.get("verdict")
                    if verdict:
                        llm_issues = [verdict]

                for issue in llm_issues:
                    warnings.append(f"LLM advisory: {issue}")
                    alignment_warnings.append(
                        AlignmentFinding(
                            code="LLM_SPEC_VALIDATION_ISSUE",
                            invariant=None,
                            capability=None,
                            message=issue,
                            severity="warning",
                            created_at=datetime.now(timezone.utc),
                        )
                    )

                for gap in llm_critical_gaps:
                    failures.append(
                        ValidationFailure(
                            rule="RULE_LLM_SPEC_VALIDATION",
                            expected="Spec-compliant story",
                            actual=gap,
                            message=gap,
                        )
                    )
                    alignment_failures.append(
                        AlignmentFinding(
                            code="LLM_SPEC_VALIDATION",
                            invariant=None,
                            capability=None,
                            message=gap,
                            severity="failure",
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                for suggestion in llm_result.get("suggestions", []):
                    warnings.append(f"LLM suggestion: {suggestion}")
                    alignment_warnings.append(
                        AlignmentFinding(
                            code="LLM_SPEC_VALIDATION_SUGGESTION",
                            invariant=None,
                            capability=None,
                            message=suggestion,
                            severity="warning",
                            created_at=datetime.now(timezone.utc),
                        )
                    )
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(
                    ValidationFailure(
                        rule="RULE_LLM_SPEC_VALIDATION",
                        expected="LLM validator completes successfully",
                        actual=str(exc),
                        message="LLM validation execution failed",
                    )
                )
                alignment_failures.append(
                    AlignmentFinding(
                        code="LLM_SPEC_VALIDATION_ERROR",
                        invariant=None,
                        capability=None,
                        message=f"LLM validation execution failed: {exc}",
                        severity="failure",
                        created_at=datetime.now(timezone.utc),
                    )
                )

        passed = len(failures) == 0 and len(alignment_failures) == 0

        evaluated_invariant_ids: list[str] = []
        if artifact and getattr(artifact, "invariants", None):
            for inv in artifact.invariants:
                if inv.type in ("FORBIDDEN_CAPABILITY", "REQUIRED_FIELD"):
                    evaluated_invariant_ids.append(inv.id)

        finding_invariant_ids: list[str] = []
        for finding in alignment_failures + alignment_warnings:
            if finding.invariant and finding.invariant not in finding_invariant_ids:
                finding_invariant_ids.append(finding.invariant)

        evidence = ValidationEvidence(
            spec_version_id=parsed.spec_version_id,
            validated_at=datetime.now(timezone.utc),
            passed=passed,
            rules_checked=rules_checked,
            invariants_checked=invariants_checked,
            evaluated_invariant_ids=evaluated_invariant_ids,
            finding_invariant_ids=finding_invariant_ids,
            failures=failures,
            warnings=warnings,
            alignment_warnings=alignment_warnings,
            alignment_failures=alignment_failures,
            validator_version=validator_version,
            input_hash=input_hash,
        )
        if callable(persist_evidence):
            persist_evidence(session, story, evidence, passed=passed)

        return {
            "success": True,
            "passed": passed,
            "story_id": parsed.story_id,
            "spec_version_id": parsed.spec_version_id,
            "mode": parsed.mode,
            "failures": [failure.model_dump() for failure in failures],
            "alignment_failures": [
                finding.model_dump(mode="json") for finding in alignment_failures
            ],
            "alignment_warnings": [
                finding.model_dump(mode="json") for finding in alignment_warnings
            ],
            "warnings": warnings,
            "input_hash": input_hash,
            "message": (
                "Validation passed"
                if passed
                else f"Validation failed with {len(failures)} issue(s)"
            ),
        }


__all__ = [
    "ValidateStoryInput",
    "compute_story_input_hash",
    "resolve_default_validation_mode",
    "persist_validation_evidence",
    "render_invariant_summary",
    "run_structural_story_checks",
    "run_deterministic_alignment_checks",
    "validate_story_with_spec_authority",
]
