"""
Specification persistence and retrieval tools.
Handles both file-based and pasted text specifications.

Design:
- save_project_specification: Saves spec to DB, creates backup file if needed
- read_project_specification: Retrieves spec for active project

Specification Authority v1 (NEW):
- register_spec_version: Create versioned spec with hash
- approve_spec_version: Explicit approval gate
- compile_spec_authority: Extract and cache spec authority (LLM-based)
- check_spec_authority_status: Status check (CURRENT/STALE/NOT_COMPILED/PENDING_REVIEW)
- get_compiled_authority_by_version: Deterministic retrieval

Usage:
1. User provides spec via file path -> Load from file, save path reference
2. User pastes spec text -> Save text, create backup file in specs/
3. Agents read spec on-demand using read_project_specification
"""

from typing import Any, Dict, Optional, List, Union, Literal, Callable
import logging

from google.adk.tools import ToolContext
from pydantic import BaseModel
from sqlmodel import Session

from models.core import Feature, UserStory
from models.db import engine, get_engine
from models.specs import CompiledSpecAuthority, SpecAuthorityAcceptance

from utils.spec_schemas import (
    ValidationEvidence,
    ValidationFailure,
    AlignmentFinding,
    SpecAuthorityCompilationSuccess,
    Invariant,
)
from services.specs.lifecycle_service import (
    ApproveSpecVersionInput as _service_ApproveSpecVersionInput,
    LinkSpecToProductInput as _service_LinkSpecToProductInput,
    ReadProjectSpecificationInput as _service_ReadProjectSpecificationInput,
    RegisterSpecVersionInput as _service_RegisterSpecVersionInput,
    SaveProjectSpecificationInput as _service_SaveProjectSpecificationInput,
    approve_spec_version as _service_approve_spec_version,
    link_spec_to_product as _service_link_spec_to_product,
    read_project_specification as _service_read_project_specification,
    register_spec_version as _service_register_spec_version,
    save_project_specification as _service_save_project_specification,
)
from services.specs.compiler_service import (
    _compiler_failure_result as _service_compiler_failure_result,
    _extract_compiler_response_text as _service_extract_compiler_response_text,
    _extract_spec_authority_llm as _service_extract_spec_authority_llm,
    _invoke_spec_authority_compiler as _service_invoke_spec_authority_compiler,
    _invoke_spec_authority_compiler_async as _service_invoke_spec_authority_compiler_async,
    _run_async_task as _service_run_async_task,
    check_spec_authority_status as _service_check_spec_authority_status,
    CheckSpecAuthorityStatusInput as _service_CheckSpecAuthorityStatusInput,
    compile_spec_authority as _service_compile_spec_authority,
    CompileSpecAuthorityForVersionInput as _service_CompileSpecAuthorityForVersionInput,
    CompileSpecAuthorityInput as _service_CompileSpecAuthorityInput,
    ensure_accepted_spec_authority as _service_ensure_accepted_spec_authority,
    ensure_spec_authority_accepted as _service_ensure_spec_authority_accepted,
    GetCompiledAuthorityInput as _service_GetCompiledAuthorityInput,
    get_compiled_authority_by_version as _service_get_compiled_authority_by_version,
    load_compiled_artifact as _service_load_compiled_artifact,
    PreviewSpecAuthorityInput as _service_PreviewSpecAuthorityInput,
    compile_spec_authority_for_version as _service_compile_spec_authority_for_version,
    UpdateSpecAndCompileAuthorityInput as _service_UpdateSpecAndCompileAuthorityInput,
    preview_spec_authority as _service_preview_spec_authority,
    update_spec_and_compile_authority as _service_update_spec_and_compile_authority,
)
from services.specs.story_validation_service import (
    ValidateStoryInput as _service_ValidateStoryInput,
    compute_story_input_hash as _service_compute_story_input_hash,
    invoke_spec_validator_async as _service_invoke_spec_validator_async,
    parse_llm_validator_response as _service_parse_llm_validator_response,
    persist_validation_evidence as _service_persist_validation_evidence,
    render_invariant_summary as _service_render_invariant_summary,
    resolve_default_validation_mode as _service_resolve_default_validation_mode,
    run_deterministic_alignment_checks as _service_run_deterministic_alignment_checks,
    run_structural_story_checks as _service_run_structural_story_checks,
    run_llm_spec_validation as _service_run_llm_spec_validation,
    validate_story_with_spec_authority as _service_validate_story_with_spec_authority,
)

logger = logging.getLogger(__name__)

# --- Input Schemas ---


SaveProjectSpecificationInput = _service_SaveProjectSpecificationInput
LinkSpecToProductInput = _service_LinkSpecToProductInput
ReadProjectSpecificationInput = _service_ReadProjectSpecificationInput
PreviewSpecAuthorityInput = _service_PreviewSpecAuthorityInput


def save_project_specification(
    params: Dict[str, Any],
    tool_context: Optional[ToolContext] = None,  # pylint: disable=unused-argument
) -> Dict[str, Any]:
    """Compatibility adapter over the public lifecycle service boundary."""
    return _service_save_project_specification(
        params,
        tool_context=tool_context,
    )


def link_spec_to_product(
    params: Dict[str, Any],
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Compatibility adapter over the public lifecycle service boundary."""
    return _service_link_spec_to_product(
        params,
        tool_context=tool_context,
    )


def read_project_specification(
    params: Optional[Dict[str, Any]] = None,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Compatibility adapter over the public lifecycle service boundary."""
    return _service_read_project_specification(
        params,
        tool_context=tool_context,
    )


def preview_spec_authority(
    params: PreviewSpecAuthorityInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Compatibility adapter over the public compiler service boundary."""
    return _service_preview_spec_authority(
        params,
        tool_context=tool_context,
    )


def _run_async_task(coro: Any) -> Any:
    """Compatibility shim over the compiler-service async runner."""
    return _service_run_async_task(coro)


def _extract_compiler_response_text(events: List[Any]) -> str:
    """Compatibility shim over the compiler-service response parser."""
    return _service_extract_compiler_response_text(events)


async def _invoke_spec_authority_compiler_async(
    input_payload: Any,
) -> str:
    """Compatibility shim over the compiler-service async invoker."""
    return await _service_invoke_spec_authority_compiler_async(input_payload)


def _invoke_spec_authority_compiler(
    spec_content: str,
    content_ref: Optional[str],
    product_id: Optional[int],
    spec_version_id: Optional[int],
) -> str:
    """Compatibility shim over the compiler-service runtime invoker."""
    return _service_invoke_spec_authority_compiler(
        spec_content=spec_content,
        content_ref=content_ref,
        product_id=product_id,
        spec_version_id=spec_version_id,
    )


def _compiler_failure_result(
    *,
    product_id: Optional[int],
    spec_version_id: Optional[int],
    content_ref: Optional[str],
    failure_stage: str,
    error: str,
    reason: str,
    raw_output: Optional[str] = None,
    blocking_gaps: Optional[List[str]] = None,
    exception: Optional[BaseException] = None,
) -> Dict[str, Any]:
    """Compatibility shim over the compiler-service failure result helper."""
    return _service_compiler_failure_result(
        product_id=product_id,
        spec_version_id=spec_version_id,
        content_ref=content_ref,
        failure_stage=failure_stage,
        error=error,
        reason=reason,
        raw_output=raw_output,
        blocking_gaps=blocking_gaps,
        exception=exception,
    )


def _render_invariant_summary(invariant: Invariant) -> str:
    """Compatibility shim over the public story-validation helper."""
    return _service_render_invariant_summary(invariant)


def _load_compiled_artifact(
    authority: CompiledSpecAuthority,
) -> Optional[SpecAuthorityCompilationSuccess]:
    """Compatibility shim over the public compiler service helper."""
    return _service_load_compiled_artifact(authority)


def ensure_spec_authority_accepted(
    *,
    product_id: int,
    spec_version_id: int,
    policy: Literal["auto", "human"],
    decided_by: str,
    rationale: Optional[str] = None,
) -> SpecAuthorityAcceptance:
    """Compatibility adapter over the public compiler service boundary."""
    return _service_ensure_spec_authority_accepted(
        product_id=product_id,
        spec_version_id=spec_version_id,
        policy=policy,
        decided_by=decided_by,
        rationale=rationale,
    )


# =============================================================================
# SPECIFICATION AUTHORITY V1 — VERSIONING, APPROVAL, AND COMPILATION
# =============================================================================

# Compiler version constant (bump when extraction logic changes)
SPEC_COMPILER_VERSION = "1.0.0"


RegisterSpecVersionInput = _service_RegisterSpecVersionInput
ApproveSpecVersionInput = _service_ApproveSpecVersionInput


CompileSpecAuthorityInput = _service_CompileSpecAuthorityInput


CompileSpecAuthorityForVersionInput = _service_CompileSpecAuthorityForVersionInput


UpdateSpecAndCompileAuthorityInput = _service_UpdateSpecAndCompileAuthorityInput


CheckSpecAuthorityStatusInput = _service_CheckSpecAuthorityStatusInput


GetCompiledAuthorityInput = _service_GetCompiledAuthorityInput


def register_spec_version(
    params: RegisterSpecVersionInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """Compatibility adapter over the public lifecycle service boundary."""
    return _service_register_spec_version(
        params,
        tool_context=tool_context,
    )


def approve_spec_version(
    params: ApproveSpecVersionInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """Compatibility adapter over the public lifecycle service boundary."""
    return _service_approve_spec_version(
        params,
        tool_context=tool_context,
    )


def compile_spec_authority(
    params: CompileSpecAuthorityInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """Compatibility adapter over the public compiler service boundary."""
    return _service_compile_spec_authority(
        params,
        tool_context=tool_context,
        extract_authority=_extract_spec_authority_llm,
    )


def compile_spec_authority_for_version(
    params: CompileSpecAuthorityForVersionInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Compatibility adapter over the public compiler service boundary."""
    return _service_compile_spec_authority_for_version(
        params,
        tool_context=tool_context,
    )


def update_spec_and_compile_authority(
    params: UpdateSpecAndCompileAuthorityInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """Compatibility adapter over the public compiler service boundary."""
    return _service_update_spec_and_compile_authority(
        params,
        tool_context=tool_context,
    )


def ensure_accepted_spec_authority(
    product_id: int,
    *,
    spec_content: Optional[str] = None,
    content_ref: Optional[str] = None,
    recompile: bool = False,
    tool_context: Optional[ToolContext] = None,
) -> int:
    """
    Ensure an accepted spec authority exists for the product.

    This is the orchestrator-level gate that ensures story generation has a valid,
    accepted spec authority to validate against.

    Behavior:
    1. If an accepted spec authority already exists for the product, return its spec_version_id.
    2. Otherwise, call update_spec_and_compile_authority() to create and auto-accept one.
    3. Require success==True and accepted==True; otherwise raise RuntimeError.

    Args:
        product_id: The product ID to check/create authority for.
        spec_content: Raw specification content (text or markdown).
        content_ref: Path or reference to specification content.
        recompile: Force recompile even if authority cache exists.
        tool_context: Optional ADK ToolContext to pass through to tool execution.

    Returns:
        The spec_version_id of the accepted authority.

    Raises:
        RuntimeError: If no accepted authority exists and no spec content is provided,
                      or if update_spec_and_compile_authority fails or returns not accepted.
    """
    return _service_ensure_accepted_spec_authority(
        product_id=product_id,
        spec_content=spec_content,
        content_ref=content_ref,
        recompile=recompile,
        tool_context=tool_context,
        _update_spec_and_compile_authority=update_spec_and_compile_authority,
        _logger=logger,
    )


def check_spec_authority_status(
    params: CheckSpecAuthorityStatusInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """Compatibility adapter over the public compiler service boundary."""
    return _service_check_spec_authority_status(
        params,
        tool_context=tool_context,
    )


def get_compiled_authority_by_version(
    params: GetCompiledAuthorityInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """Compatibility adapter over the public compiler service boundary."""
    return _service_get_compiled_authority_by_version(
        params,
        tool_context=tool_context,
    )


# =============================================================================
# STORY VALIDATION PINNING V2 — SPEC VERSION REQUIRED + EVIDENCE PERSISTENCE
# =============================================================================

# Validator version constant (bump when validation logic changes)
VALIDATOR_VERSION = "1.0.0"


def _resolve_default_validation_mode() -> str:
    """Compatibility shim over the public story-validation helper."""
    return _service_resolve_default_validation_mode()


ValidateStoryInput = _service_ValidateStoryInput


def _compute_story_input_hash(story: UserStory) -> str:
    """Compatibility shim over the public story-validation helper."""
    return _service_compute_story_input_hash(story)


def _persist_validation_evidence(
    session: Session,
    story: UserStory,
    evidence: ValidationEvidence,
    passed: bool,
) -> None:
    """Compatibility shim over the public story-validation helper."""
    _service_persist_validation_evidence(session, story, evidence, passed)


def _run_structural_story_checks(
    story: UserStory,
) -> tuple[List[str], List[ValidationFailure], List[str]]:
    """Compatibility shim over the public story-validation helper."""
    return _service_run_structural_story_checks(story)


def _run_deterministic_alignment_checks(
    story: UserStory,
    authority: CompiledSpecAuthority,
    *,
    load_compiled_artifact_fn: Callable[[CompiledSpecAuthority], Any | None] | None = None,
) -> tuple[List[AlignmentFinding], List[AlignmentFinding], List[str]]:
    """Compatibility shim over the public story-validation helper."""
    return _service_run_deterministic_alignment_checks(
        story,
        authority,
        load_compiled_artifact_fn=load_compiled_artifact_fn or _load_compiled_artifact,
    )


async def _invoke_spec_validator_async(payload_text: str) -> str:
    """Compatibility shim over the public story-validation helper."""
    return await _service_invoke_spec_validator_async(payload_text)


def _parse_llm_validator_response(raw_text: str) -> Dict[str, Any]:
    """Compatibility shim over the public story-validation helper."""
    return _service_parse_llm_validator_response(raw_text)


def _run_llm_spec_validation(
    story: UserStory,
    authority: CompiledSpecAuthority,
    artifact: Optional[SpecAuthorityCompilationSuccess],
    feature: Optional[Feature] = None,
) -> Dict[str, Any]:
    """Compatibility shim over the public story-validation helper."""
    return _service_run_llm_spec_validation(
        story,
        authority,
        artifact,
        feature=feature,
        invoke_spec_validator_async_fn=_invoke_spec_validator_async,
        parse_llm_validator_response_fn=_parse_llm_validator_response,
    )


def validate_story_with_spec_authority(
    params: ValidateStoryInput,
    tool_context: Optional[ToolContext] = None  # pylint: disable=unused-argument
) -> Dict[str, Any]:
    """Compatibility adapter over the public story validation service boundary."""
    return _service_validate_story_with_spec_authority(
        params,
        tool_context=tool_context,
        resolve_default_validation_mode=_resolve_default_validation_mode,
        compute_story_input_hash_fn=_compute_story_input_hash,
        persist_validation_evidence=_persist_validation_evidence,
        run_structural_story_checks=_run_structural_story_checks,
        run_deterministic_alignment_checks=_run_deterministic_alignment_checks,
        run_llm_spec_validation=_run_llm_spec_validation,
        load_compiled_artifact_fn=_load_compiled_artifact,
        render_invariant_summary_fn=_render_invariant_summary,
        validator_version=VALIDATOR_VERSION,
    )


# --- Actual LLM Extraction (v1.1+) ---


def _extract_spec_authority_llm(
    spec_content: str,
    content_ref: Optional[str],
    product_id: int,
    spec_version_id: int,
) -> SpecAuthorityCompilationSuccess:
    """Compatibility shim over the compiler-service extraction helper."""
    return _service_extract_spec_authority_llm(
        spec_content=spec_content,
        content_ref=content_ref,
        product_id=product_id,
        spec_version_id=spec_version_id,
    )
