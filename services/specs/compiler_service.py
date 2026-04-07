"""Public helpers for working with compiled spec artifacts."""

from __future__ import annotations

import json
import hashlib
import asyncio
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, List, Callable

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select

from models.core import Product
from models.db import get_engine
from models.enums import SpecAuthorityStatus
from models.specs import (
    CompiledSpecAuthority,
    SpecAuthorityAcceptance,
    SpecRegistry,
)

from orchestrator_agent.agent_tools.spec_authority_compiler_agent.agent import (
    root_agent as spec_authority_compiler_agent,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.compiler_contract import (
    compute_prompt_hash,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.instructions_source import (
    SPEC_AUTHORITY_COMPILER_INSTRUCTIONS,
    SPEC_AUTHORITY_COMPILER_VERSION,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.normalizer import (
    normalize_compiler_output,
)
from utils.spec_schemas import (
    Invariant,
    InvariantType,
    SpecAuthorityCompilerInput,
    SpecAuthorityCompilationFailure,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
)
from utils.adk_runner import get_agent_model_info, invoke_agent_to_text
from utils.failure_artifacts import AgentInvocationError, write_failure_artifact
from utils.runtime_config import SPEC_AUTHORITY_COMPILER_IDENTITY

logger = logging.getLogger(__name__)
_DEFAULT_GET_ENGINE = get_engine


class UpdateSpecAndCompileAuthorityInput(BaseModel):
    """Input schema for update+compile spec workflows."""

    product_id: int = Field(description="Product ID for spec update")
    spec_content: Optional[str] = Field(
        default=None,
        description="Raw specification content to persist and compile",
    )
    content_ref: Optional[str] = Field(
        default=None,
        description="Path/reference to specification content on disk",
    )
    recompile: Optional[bool] = Field(
        default=False,
        description="Force recompilation even if compiled authority already exists",
    )


class CompileSpecAuthorityForVersionInput(BaseModel):
    """Input schema for compile spec authority by version."""

    spec_version_id: int = Field(description="Approved spec version to compile")
    force_recompile: Optional[bool] = Field(
        default=False,
        description="If true, recompile even when cached authority exists",
    )


class PreviewSpecAuthorityInput(BaseModel):
    """Input schema for preview spec authority compilation."""

    content: str = Field(description="The raw specification text to compile.")


class CompileSpecAuthorityInput(BaseModel):
    """Input schema for legacy one-shot spec authority compilation."""

    spec_version_id: int = Field(description="Approved spec version to compile")


class CheckSpecAuthorityStatusInput(BaseModel):
    """Input schema for spec authority status checks."""

    product_id: int = Field(description="Product ID to check status for")


class GetCompiledAuthorityInput(BaseModel):
    """Input schema for deterministic retrieval of compiled authority by version."""

    product_id: int = Field(description="Product ID")
    spec_version_id: int = Field(description="Spec version ID to retrieve")


def load_compiled_artifact(
    authority: Any,
) -> SpecAuthorityCompilationSuccess | None:
    """Load normalized compiled artifact JSON if present and valid."""
    artifact_json = getattr(authority, "compiled_artifact_json", None)
    if not artifact_json:
        return None
    try:
        parsed = SpecAuthorityCompilerOutput.model_validate_json(
            artifact_json
        )
    except (ValidationError, ValueError):
        return None
    if isinstance(parsed.root, SpecAuthorityCompilationFailure):
        return None
    return parsed.root


def ensure_spec_authority_accepted(
    *,
    product_id: int,
    spec_version_id: int,
    policy: str,
    decided_by: str,
    rationale: str | None = None,
) -> SpecAuthorityAcceptance:
    """Ensure an accepted authority decision exists for a compiled spec version."""
    with Session(_resolve_engine()) as session:
        spec_version = session.get(SpecRegistry, spec_version_id)
        if not spec_version:
            raise ValueError(f"Spec version {spec_version_id} not found")
        if spec_version.product_id != product_id:
            raise ValueError(
                f"Spec version {spec_version_id} does not belong to product {product_id}"
            )

        authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == spec_version_id
            )
        ).first()
        if not authority:
            raise ValueError(f"spec_version_id {spec_version_id} is not compiled")

        artifact = load_compiled_artifact(authority)
        if not artifact:
            raise ValueError(
                f"spec_version_id {spec_version_id} compiled artifact invalid"
            )

        existing = session.exec(
            select(SpecAuthorityAcceptance).where(
                SpecAuthorityAcceptance.spec_version_id == spec_version_id,
                SpecAuthorityAcceptance.status == "accepted",
            )
        ).first()
        if existing:
            return existing

        acceptance = SpecAuthorityAcceptance(
            product_id=product_id,
            spec_version_id=spec_version_id,
            status="accepted",
            policy=policy,
            decided_by=decided_by,
            decided_at=datetime.now(timezone.utc),
            rationale=rationale,
            compiler_version=authority.compiler_version,
            prompt_hash=authority.prompt_hash,
            spec_hash=spec_version.spec_hash,
        )
        session.add(acceptance)
        session.commit()
        session.refresh(acceptance)
        return acceptance


def ensure_accepted_spec_authority(
    product_id: int,
    *,
    spec_content: str | None = None,
    content_ref: str | None = None,
    recompile: bool = False,
    tool_context: ToolContext | None = None,
    _update_spec_and_compile_authority: Callable[..., dict[str, Any]] | None = None,
    _logger: logging.Logger | None = None,
) -> int:
    """Ensure an accepted spec authority exists for the product."""
    gate_logger = _logger or logger
    update_and_compile = _update_spec_and_compile_authority
    if update_and_compile is None:
        update_and_compile = (
            _resolve_update_spec_and_compile_authority()
            or update_spec_and_compile_authority
        )
    spec_input_provided = spec_content is not None or content_ref is not None

    session_id: str | None = None
    if tool_context and hasattr(tool_context, "session_id"):
        session_id = getattr(tool_context, "session_id", None)

    gate_logger.info(
        "authority_gate.check",
        extra={
            "product_id": product_id,
            "session_id": session_id,
            "recompile": recompile,
            "spec_input_provided": spec_input_provided,
            "has_spec_content": spec_content is not None,
            "has_content_ref": content_ref is not None,
            "tool_context_present": tool_context is not None,
        },
    )

    from db.migrations import ensure_schema_current

    engine = _resolve_engine()
    ensure_schema_current(engine)

    compile_reason = "no_accepted_authority"
    existing_spec_version_id: int | None = None
    accepted_decision_found = False
    compiled_row_found = False
    compiled_artifact_success = False

    with Session(engine) as session:
        existing_acceptance = session.exec(
            select(SpecAuthorityAcceptance)
            .where(
                SpecAuthorityAcceptance.product_id == product_id,
                SpecAuthorityAcceptance.status == "accepted",
            )
            .order_by(SpecAuthorityAcceptance.decided_at.desc())
        ).first()

        if existing_acceptance:
            accepted_decision_found = True
            existing_spec_version_id = existing_acceptance.spec_version_id
            compiled = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id
                    == existing_acceptance.spec_version_id
                )
            ).first()
            if compiled:
                compiled_row_found = True
                if compiled.compiled_artifact_json:
                    artifact = load_compiled_artifact(compiled)
                    if artifact is not None:
                        compiled_artifact_success = True
                        gate_logger.info(
                            "authority_gate.pass",
                            extra={
                                "product_id": product_id,
                                "session_id": session_id,
                                "spec_version_id": existing_spec_version_id,
                                "path_used": "existing_authority",
                                "accepted_decision_found": True,
                                "compiled_row_found": True,
                                "compiled_artifact_success": True,
                                "spec_input_provided": spec_input_provided,
                            },
                        )
                        return existing_spec_version_id
            compile_reason = "compiled_unusable_or_missing"

    if spec_content is None and content_ref is None:
        gate_logger.error(
            "authority_gate.fail_no_source",
            extra={
                "product_id": product_id,
                "session_id": session_id,
                "path_used": "fail_no_source",
                "accepted_decision_found": accepted_decision_found,
                "compiled_row_found": compiled_row_found,
                "compiled_artifact_success": compiled_artifact_success,
                "spec_input_provided": False,
                "reason": "missing_inputs",
            },
        )
        raise RuntimeError(
            f"No accepted spec authority exists for product {product_id}, and no "
            "spec_content or content_ref was provided. Please provide the specification "
            "content or a file path to create an authority."
        )

    path_used = "explicit_args"
    if tool_context and tool_context.state:
        if (
            tool_context.state.get("pending_spec_content") == spec_content
            or tool_context.state.get("pending_spec_path") == content_ref
        ):
            path_used = "proposal_from_state"

    params: dict[str, Any] = {
        "product_id": product_id,
        "recompile": recompile,
    }
    if spec_content is not None:
        params["spec_content"] = spec_content
    if content_ref is not None:
        params["content_ref"] = content_ref
    input_source = "spec_content" if spec_content is not None else "content_ref"

    gate_logger.info(
        "authority_gate.compile_start",
        extra={
            "product_id": product_id,
            "session_id": session_id,
            "path_used": path_used,
            "input_source": input_source,
            "recompile": recompile,
            "reason": compile_reason,
            "accepted_decision_found": accepted_decision_found,
            "compiled_row_found": compiled_row_found,
            "compiled_artifact_success": compiled_artifact_success,
            "spec_input_provided": True,
        },
    )

    try:
        result = update_and_compile(params, tool_context=tool_context)
    except Exception as exc:
        gate_logger.error(
            "authority_gate.compile_result",
            extra={
                "product_id": product_id,
                "session_id": session_id,
                "path_used": path_used,
                "reason": "update_failed",
                "success": False,
                "accepted": False,
                "spec_version_id": None,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise

    if not result.get("success"):
        error_msg = result.get("error", "Unknown error")
        gate_logger.error(
            "authority_gate.fail",
            extra={
                "product_id": product_id,
                "reason": "update_failed",
                "success": result.get("success"),
                "accepted": result.get("accepted"),
                "spec_version_id": result.get("spec_version_id"),
            },
        )
        raise RuntimeError(
            f"Failed to create accepted spec authority for product {product_id}: {error_msg}"
        )

    if not result.get("accepted"):
        gate_logger.error(
            "authority_gate.fail",
            extra={
                "product_id": product_id,
                "reason": "not_accepted",
                "success": result.get("success"),
                "accepted": result.get("accepted"),
                "spec_version_id": result.get("spec_version_id"),
            },
        )
        raise RuntimeError(
            f"Spec authority for product {product_id} was compiled but not accepted. "
            "Authority acceptance is required before story generation can proceed."
        )

    spec_version_id = result.get("spec_version_id")
    if spec_version_id is None:
        gate_logger.error(
            "authority_gate.fail",
            extra={
                "product_id": product_id,
                "reason": "missing_spec_version_id",
                "success": result.get("success"),
                "accepted": result.get("accepted"),
                "spec_version_id": result.get("spec_version_id"),
            },
        )
        raise RuntimeError(
            f"Spec authority creation succeeded but no spec_version_id was returned "
            f"for product {product_id}."
        )

    gate_logger.info(
        "authority_gate.updated",
        extra={
            "product_id": product_id,
            "spec_version_id": spec_version_id,
            "accepted": result.get("accepted"),
            "success": result.get("success"),
            "compiler_version": result.get("compiler_version"),
        },
    )

    return spec_version_id


def _run_async_task(coro: Any) -> Any:
    """Run an async coroutine from sync code, even if a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pylint: disable=broad-except
            error["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error:
        raise error["error"]
    return result.get("value")


def _extract_compiler_response_text(events: List[Any]) -> str:
    """Extract the first text part from the final agent event."""
    final_event = events[-1] if events else None
    if not final_event or not getattr(final_event, "content", None):
        return ""
    for part in final_event.content.parts:
        text = getattr(part, "text", None)
        if text:
            return text
    return ""


async def _invoke_spec_authority_compiler_async(
    input_payload: SpecAuthorityCompilerInput,
) -> str:
    """Invoke the spec authority compiler agent and return raw JSON text."""
    return await invoke_agent_to_text(
        agent=spec_authority_compiler_agent,
        runner_identity=SPEC_AUTHORITY_COMPILER_IDENTITY,
        payload_json=input_payload.model_dump_json(),
        no_text_error="Compiler agent returned no text response",
    )


def _default_invoke_spec_authority_compiler(
    spec_content: str,
    content_ref: Optional[str],
    product_id: Optional[int],
    spec_version_id: Optional[int],
) -> str:
    """Invoke the compiler agent from sync code and return raw JSON text."""
    input_payload = SpecAuthorityCompilerInput(
        spec_source=spec_content,
        spec_content_ref=None,
        domain_hint=None,
        product_id=product_id,
        spec_version_id=spec_version_id,
    )
    return _run_async_task(_invoke_spec_authority_compiler_async(input_payload))


def _resolve_compiler_invoker():
    """Preserve the legacy spec_tools compiler monkeypatch seam for tests."""
    try:
        from tools import spec_tools  # pylint: disable=import-outside-toplevel
    except ImportError:
        spec_tools = None

    if spec_tools is not None:
        tool_invoke = getattr(spec_tools, "_invoke_spec_authority_compiler", None)
        if callable(tool_invoke):
            module_name = getattr(tool_invoke, "__module__", "")
            function_name = getattr(tool_invoke, "__name__", "")
            if not (
                module_name == "tools.spec_tools"
                and function_name == "_invoke_spec_authority_compiler"
            ):
                return tool_invoke

    return _default_invoke_spec_authority_compiler


def _invoke_spec_authority_compiler(
    spec_content: str,
    content_ref: Optional[str],
    product_id: Optional[int],
    spec_version_id: Optional[int],
) -> str:
    """Invoke the effective compiler seam, honoring legacy monkeypatch overrides."""
    compiler_invoke = _resolve_compiler_invoker()
    return compiler_invoke(
        spec_content=spec_content,
        content_ref=content_ref,
        product_id=product_id,
        spec_version_id=spec_version_id,
    )


def preview_spec_authority(
    params: dict[str, Any] | PreviewSpecAuthorityInput | None = None,
    *,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Compile spec authority in preview mode without persistence side effects."""
    raw_params = params
    if hasattr(raw_params, "model_dump"):
        raw_params = raw_params.model_dump()
    try:
        parsed = PreviewSpecAuthorityInput.model_validate(raw_params or {})
    except ValidationError as exc:
        return {"success": False, "error": f"Invalid input: {exc}"}

    try:
        raw_json = _invoke_spec_authority_compiler(
            spec_content=parsed.content,
            content_ref=None,
            product_id=None,
            spec_version_id=None,
        )
        normalized = normalize_compiler_output(raw_json)

        if isinstance(normalized.root, SpecAuthorityCompilationFailure):
            return {
                "success": False,
                "error": "Compilation failed",
                "details": normalized.root.model_dump(),
            }

        compiled_json = normalized.root.model_dump_json()
        if tool_context and tool_context.state is not None:
            tool_context.state["compiled_authority_cached"] = compiled_json

        return {
            "success": True,
            "compiled_authority": compiled_json,
        }
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("preview_spec_authority failed")
        return {"success": False, "error": str(exc)}


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
) -> dict[str, Any]:
    summary = f"{error}: {reason}" if reason else error
    artifact_result = write_failure_artifact(
        phase="spec_authority",
        project_id=product_id,
        failure_stage=failure_stage,
        failure_summary=summary,
        raw_output=raw_output,
        context={
            "product_id": product_id,
            "spec_version_id": spec_version_id,
            "content_ref": content_ref,
        },
        model_info={
            **get_agent_model_info(spec_authority_compiler_agent),
            "app_name": SPEC_AUTHORITY_COMPILER_IDENTITY.app_name,
            "user_id": SPEC_AUTHORITY_COMPILER_IDENTITY.user_id,
        },
        validation_errors=blocking_gaps,
        exception=exception,
        extra={
            "error": error,
            "reason": reason,
            "blocking_gaps": blocking_gaps or [],
        },
    )
    metadata = artifact_result["metadata"]
    if exception is not None:
        logger.exception(
            "Spec authority compilation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            summary,
        )
    else:
        logger.error(
            "Spec authority compilation failed [artifact_id=%s stage=%s]: %s",
            metadata["failure_artifact_id"],
            failure_stage,
            summary,
        )
    return {
        "success": False,
        "error": error,
        "reason": reason,
        "blocking_gaps": blocking_gaps or [],
        **metadata,
    }


def _render_invariant_summary(invariant: Invariant) -> str:
    """Render a structured invariant into a stable string for legacy consumers."""
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


def _resolve_engine():
    """Preserve the legacy spec_tools.engine monkeypatch seam for tests."""
    from services.specs._engine_resolution import resolve_spec_engine

    return resolve_spec_engine(
        service_get_engine=get_engine,
        default_service_get_engine=_DEFAULT_GET_ENGINE,
    )


def _compile_spec_authority_for_version(
    *,
    spec_version_id: int,
    force_recompile: bool,
    tool_context: ToolContext | None,
) -> dict[str, Any]:
    tool_compile = _resolve_compile_spec_authority_for_version()
    if tool_compile is not None:
        return tool_compile(
            {
                "spec_version_id": spec_version_id,
                "force_recompile": force_recompile,
            },
            tool_context=tool_context,
        )
    return compile_spec_authority_for_version(
        spec_version_id=spec_version_id,
        force_recompile=force_recompile,
        tool_context=tool_context,
    )


def _extract_spec_authority_llm(
    *,
    spec_content: str,
    content_ref: Optional[str],
    product_id: int,
    spec_version_id: int,
) -> SpecAuthorityCompilationSuccess:
    """Extract spec authority using the compiler and normalize to success output."""
    raw_json = _invoke_spec_authority_compiler(
        spec_content=spec_content,
        content_ref=content_ref,
        product_id=product_id,
        spec_version_id=spec_version_id,
    )

    normalized = normalize_compiler_output(raw_json)
    if isinstance(normalized.root, SpecAuthorityCompilationFailure):
        raise ValueError(
            f"Spec authority compilation failed: {normalized.root.error} - {normalized.root.reason}"
        )
    return normalized.root


def compile_spec_authority(
    params: dict[str, Any] | CompileSpecAuthorityInput | None = None,
    *,
    tool_context: ToolContext | None = None,  # pylint: disable=unused-argument
    extract_authority: (
        Callable[..., SpecAuthorityCompilationSuccess] | None
    ) = None,
) -> dict[str, Any]:
    """Compile an approved spec version into cached authority (legacy one-shot path)."""
    raw_params = params
    if hasattr(raw_params, "model_dump"):
        raw_params = raw_params.model_dump()
    parsed = CompileSpecAuthorityInput.model_validate(raw_params or {})

    extractor = extract_authority or _extract_spec_authority_llm

    with Session(_resolve_engine()) as session:
        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found",
            }

        if spec_version.status != "approved":
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} is not approved "
                    f"(status: {spec_version.status}). "
                    "Only approved specs can be compiled."
                ),
            }

        existing_authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == parsed.spec_version_id
            )
        ).first()
        if existing_authority:
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} is already compiled "
                    f"(authority_id: {existing_authority.authority_id})"
                ),
            }

        try:
            success_artifact = extractor(
                spec_content=spec_version.content,
                content_ref=spec_version.content_ref,
                product_id=spec_version.product_id,
                spec_version_id=spec_version.spec_version_id,
            )
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
            }

        prompt_hash = compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS)
        scope_themes = success_artifact.scope_themes
        invariants = [
            _render_invariant_summary(inv) for inv in success_artifact.invariants
        ]
        spec_gaps = success_artifact.gaps
        compiled_artifact_json = success_artifact.model_dump_json()

        authority = CompiledSpecAuthority(
            spec_version_id=parsed.spec_version_id,
            compiler_version=SPEC_AUTHORITY_COMPILER_VERSION,
            prompt_hash=prompt_hash,
            compiled_at=datetime.now(timezone.utc),
            scope_themes=json.dumps(scope_themes),
            invariants=json.dumps(invariants),
            eligible_feature_ids=json.dumps([]),
            rejected_features=json.dumps([]),
            spec_gaps=json.dumps(spec_gaps),
            compiled_artifact_json=compiled_artifact_json,
        )
        session.add(authority)
        session.commit()
        session.refresh(authority)

        return {
            "success": True,
            "authority_id": authority.authority_id,
            "spec_version_id": parsed.spec_version_id,
            "compiler_version": SPEC_AUTHORITY_COMPILER_VERSION,
            "prompt_hash": prompt_hash[:8],
            "scope_themes_count": len(scope_themes),
            "invariants_count": len(invariants),
            "message": (
                f"Compiled spec version {parsed.spec_version_id} "
                f"(authority ID: {authority.authority_id})"
            ),
        }


def compile_spec_authority_for_version(
    params: dict[str, Any] | CompileSpecAuthorityForVersionInput | None = None,
    *,
    spec_version_id: int | None = None,
    force_recompile: Optional[bool] = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Compile an approved spec version into cached authority (idempotent)."""
    raw_params = params
    if hasattr(raw_params, "model_dump"):
        raw_params = raw_params.model_dump()
    merged_params: dict[str, Any] = dict(raw_params or {})
    if spec_version_id is not None:
        merged_params["spec_version_id"] = spec_version_id
    if force_recompile is not None:
        merged_params["force_recompile"] = force_recompile
    parsed = CompileSpecAuthorityForVersionInput.model_validate(merged_params)
    force_recompile = bool(parsed.force_recompile)

    with Session(_resolve_engine()) as session:
        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found",
            }

        product = session.get(Product, spec_version.product_id)

        if spec_version.status != "approved":
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} is not approved "
                    f"(status: {spec_version.status}). "
                    "Only approved specs can be compiled."
                ),
            }

        existing_authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == parsed.spec_version_id
            )
        ).first()

        if (
            existing_authority
            and not force_recompile
            and existing_authority.compiled_artifact_json
        ):
            artifact = load_compiled_artifact(existing_authority)
            if artifact:
                scope_themes = artifact.scope_themes
                invariants = [
                    _render_invariant_summary(inv) for inv in artifact.invariants
                ]
            else:
                scope_themes = json.loads(existing_authority.scope_themes)
                invariants = json.loads(existing_authority.invariants)

            if product:
                product.compiled_authority_json = (
                    existing_authority.compiled_artifact_json
                )
                session.add(product)
                session.commit()

            if tool_context and tool_context.state is not None:
                tool_context.state["compiled_authority_cached"] = (
                    existing_authority.compiled_artifact_json
                )

            return {
                "success": True,
                "cached": True,
                "authority_id": existing_authority.authority_id,
                "spec_version_id": parsed.spec_version_id,
                "compiler_version": existing_authority.compiler_version,
                "prompt_hash": existing_authority.prompt_hash,
                "scope_themes_count": len(scope_themes),
                "invariants_count": len(invariants),
                "content_ref": spec_version.content_ref,
                "content_source": "content",
                "message": (
                    f"Spec version {parsed.spec_version_id} is already compiled "
                    f"(authority ID: {existing_authority.authority_id})."
                ),
            }

        spec_content = spec_version.content or ""
        content_source = "content"

        if not spec_content.strip() and spec_version.content_ref:
            content_path = Path(spec_version.content_ref)
            if not content_path.exists():
                return {
                    "success": False,
                    "error": (
                        "Spec content is empty and content_ref was not found: "
                        f"{spec_version.content_ref}"
                    ),
                }
            try:
                spec_content = content_path.read_text(encoding="utf-8")
                content_source = "content_ref"
            except (OSError, UnicodeDecodeError) as exc:
                return {
                    "success": False,
                    "error": f"Failed to read content_ref: {exc}",
                }

        if not spec_content.strip():
            return {
                "success": False,
                "error": "Spec content is empty; cannot compile authority.",
            }

        try:
            raw_json = _invoke_spec_authority_compiler(
                spec_content=spec_content,
                content_ref=spec_version.content_ref,
                product_id=spec_version.product_id,
                spec_version_id=spec_version.spec_version_id,
            )
        except AgentInvocationError as exc:
            return _compiler_failure_result(
                product_id=spec_version.product_id,
                spec_version_id=spec_version.spec_version_id,
                content_ref=spec_version.content_ref,
                failure_stage="invocation_exception",
                error="SPEC_COMPILER_INVOCATION_FAILED",
                reason=str(exc),
                raw_output=exc.partial_output,
                exception=exc,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return _compiler_failure_result(
                product_id=spec_version.product_id,
                spec_version_id=spec_version.spec_version_id,
                content_ref=spec_version.content_ref,
                failure_stage="invocation_exception",
                error="SPEC_COMPILER_INVOCATION_FAILED",
                reason=str(exc),
                exception=exc,
            )

        normalized = normalize_compiler_output(raw_json)
        if isinstance(normalized.root, SpecAuthorityCompilationFailure):
            failure_stage = (
                "invalid_json"
                if normalized.root.reason == "INVALID_JSON"
                else "output_validation"
            )
            return _compiler_failure_result(
                product_id=spec_version.product_id,
                spec_version_id=spec_version.spec_version_id,
                content_ref=spec_version.content_ref,
                failure_stage=failure_stage,
                error=normalized.root.error,
                reason=normalized.root.reason,
                raw_output=raw_json,
                blocking_gaps=normalized.root.blocking_gaps,
            )

        success = normalized.root
        compiled_artifact_json = success.model_dump_json()
        prompt_hash = compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS)
        compiler_version = SPEC_AUTHORITY_COMPILER_VERSION

        scope_themes = success.scope_themes
        invariants = [_render_invariant_summary(inv) for inv in success.invariants]
        spec_gaps = success.gaps

        if existing_authority and force_recompile:
            existing_authority.compiler_version = compiler_version
            existing_authority.prompt_hash = prompt_hash
            existing_authority.compiled_at = datetime.now(timezone.utc)
            existing_authority.compiled_artifact_json = compiled_artifact_json
            existing_authority.scope_themes = json.dumps(scope_themes)
            existing_authority.invariants = json.dumps(invariants)
            existing_authority.eligible_feature_ids = json.dumps([])
            existing_authority.rejected_features = json.dumps([])
            existing_authority.spec_gaps = json.dumps(spec_gaps)
            session.add(existing_authority)
            session.commit()
            session.refresh(existing_authority)

            if product:
                product.compiled_authority_json = compiled_artifact_json
                session.add(product)
                session.commit()

            authority_id = existing_authority.authority_id
            cached = False
            recompiled = True
        else:
            authority = CompiledSpecAuthority(
                spec_version_id=parsed.spec_version_id,
                compiler_version=compiler_version,
                prompt_hash=prompt_hash,
                compiled_at=datetime.now(timezone.utc),
                compiled_artifact_json=compiled_artifact_json,
                scope_themes=json.dumps(scope_themes),
                invariants=json.dumps(invariants),
                eligible_feature_ids=json.dumps([]),
                rejected_features=json.dumps([]),
                spec_gaps=json.dumps(spec_gaps),
            )
            session.add(authority)
            session.commit()
            session.refresh(authority)

            if product:
                product.compiled_authority_json = compiled_artifact_json
                session.add(product)
                session.commit()

            authority_id = authority.authority_id
            cached = False
            recompiled = False

        if tool_context and tool_context.state is not None:
            tool_context.state["compiled_authority_cached"] = compiled_artifact_json

        return {
            "success": True,
            "cached": cached,
            "recompiled": recompiled,
            "authority_id": authority_id,
            "spec_version_id": parsed.spec_version_id,
            "compiler_version": compiler_version,
            "prompt_hash": prompt_hash,
            "scope_themes_count": len(scope_themes),
            "invariants_count": len(invariants),
            "content_ref": spec_version.content_ref,
            "content_source": content_source,
            "message": (
                f"Compiled spec version {parsed.spec_version_id} "
                f"(authority ID: {authority_id})"
            ),
        }


def _ensure_spec_authority_accepted(
    *,
    product_id: int,
    spec_version_id: int,
    policy: str,
    decided_by: str,
    rationale: str | None = None,
):
    tool_ensure = _resolve_ensure_spec_authority_accepted()
    if tool_ensure is not None:
        return tool_ensure(
            product_id=product_id,
            spec_version_id=spec_version_id,
            policy=policy,
            decided_by=decided_by,
            rationale=rationale,
        )
    return ensure_spec_authority_accepted(
        product_id=product_id,
        spec_version_id=spec_version_id,
        policy=policy,
        decided_by=decided_by,
        rationale=rationale,
    )


def _resolve_compile_spec_authority_for_version():
    """Preserve legacy tool-level monkeypatch seam for compile delegation."""
    try:
        from tools import spec_tools  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None

    tool_compile = getattr(spec_tools, "compile_spec_authority_for_version", None)
    if not callable(tool_compile):
        return None

    module_name = getattr(tool_compile, "__module__", "")
    function_name = getattr(tool_compile, "__name__", "")
    if (
        module_name == "tools.spec_tools"
        and function_name == "compile_spec_authority_for_version"
    ):
        return None

    return tool_compile


def _resolve_ensure_spec_authority_accepted():
    """Preserve legacy tool-level monkeypatch seam for acceptance delegation."""
    try:
        from tools import spec_tools  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None

    tool_ensure = getattr(spec_tools, "ensure_spec_authority_accepted", None)
    if not callable(tool_ensure):
        return None

    module_name = getattr(tool_ensure, "__module__", "")
    function_name = getattr(tool_ensure, "__name__", "")
    if (
        module_name == "tools.spec_tools"
        and function_name == "ensure_spec_authority_accepted"
    ):
        return None

    return tool_ensure


def _resolve_update_spec_and_compile_authority():
    """Preserve legacy tool-level monkeypatch seam for update+compile delegation."""
    try:
        from tools import spec_tools  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None

    tool_update = getattr(spec_tools, "update_spec_and_compile_authority", None)
    if not callable(tool_update):
        return None

    module_name = getattr(tool_update, "__module__", "")
    function_name = getattr(tool_update, "__name__", "")
    if (
        module_name == "tools.spec_tools"
        and function_name == "update_spec_and_compile_authority"
    ):
        return None

    return tool_update


def update_spec_and_compile_authority(
    params: dict[str, Any],
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Persist spec content, compile authority, and auto-accept the result."""
    raw_params = params
    if hasattr(raw_params, "model_dump"):
        raw_params = raw_params.model_dump()
    parsed = UpdateSpecAndCompileAuthorityInput.model_validate(raw_params or {})
    force_recompile = bool(parsed.recompile)

    has_content = parsed.spec_content is not None
    has_ref = parsed.content_ref is not None
    if has_content == has_ref:
        raise ValueError("Provide exactly one of spec_content or content_ref")

    if parsed.content_ref:
        content_path = Path(parsed.content_ref)
        if not content_path.exists():
            return {
                "success": False,
                "error": f"Specification file not found: {parsed.content_ref}",
            }
        try:
            spec_content = content_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {
                "success": False,
                "error": f"Failed to read specification file: {exc}",
            }
    else:
        spec_content = parsed.spec_content or ""

    spec_hash = hashlib.sha256(spec_content.encode("utf-8")).hexdigest()

    with Session(_resolve_engine()) as session:
        product = session.get(Product, parsed.product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product ID {parsed.product_id} not found",
            }

        latest_spec = session.exec(
            select(SpecRegistry)
            .where(SpecRegistry.product_id == parsed.product_id)
            .order_by(SpecRegistry.spec_version_id.desc())
        ).first()

        if latest_spec and latest_spec.spec_hash == spec_hash:
            spec_version_id = latest_spec.spec_version_id
        else:
            new_spec = SpecRegistry(
                product_id=parsed.product_id,
                spec_hash=spec_hash,
                content=spec_content,
                content_ref=parsed.content_ref,
                status="approved",
                approved_at=datetime.now(timezone.utc),
                approved_by="implicit",
                approval_notes="Implicit approval",
            )
            session.add(new_spec)
            session.commit()
            session.refresh(new_spec)
            spec_version_id = new_spec.spec_version_id

    compile_result = _compile_spec_authority_for_version(
        spec_version_id=spec_version_id,
        force_recompile=force_recompile,
        tool_context=tool_context,
    )

    if not compile_result.get("success"):
        return compile_result

    with Session(_resolve_engine()) as session:
        authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == spec_version_id
            )
        ).first()

        if not authority:
            return {
                "success": False,
                "error": (
                    f"Compiled authority missing for spec version {spec_version_id}"
                ),
            }

    try:
        acceptance = _ensure_spec_authority_accepted(
            product_id=parsed.product_id,
            spec_version_id=spec_version_id,
            policy="auto",
            decided_by="system",
            rationale="Auto-accepted on compile success",
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "accepted": False,
        }

    artifact = load_compiled_artifact(authority)
    if artifact:
        scope_themes_count = len(artifact.scope_themes)
        invariants_count = len(artifact.invariants)
        eligible_feature_ids_count = len(json.loads(authority.eligible_feature_ids))
    else:
        scope_themes_count = len(json.loads(authority.scope_themes or "[]"))
        invariants_count = len(json.loads(authority.invariants or "[]"))
        eligible_feature_ids_count = len(
            json.loads(authority.eligible_feature_ids or "[]")
        )

    return {
        "success": True,
        "product_id": parsed.product_id,
        "spec_version_id": spec_version_id,
        "authority_id": authority.authority_id,
        "spec_hash": spec_hash,
        "compiled_at": authority.compiled_at.isoformat(),
        "compiler_version": authority.compiler_version,
        "num_scope_themes": scope_themes_count,
        "num_invariants": invariants_count,
        "num_eligible_feature_ids": eligible_feature_ids_count,
        "cache_hit": bool(compile_result.get("cached")) and not force_recompile,
        "accepted": acceptance.status == "accepted",
        "acceptance_policy": acceptance.policy,
        "acceptance_decided_at": acceptance.decided_at.isoformat(),
        "acceptance_decided_by": acceptance.decided_by,
        "message": (
            f"Spec v{spec_version_id} ready. Use this spec_version_id for "
            "story validation and generation."
        ),
    }


def check_spec_authority_status(
    params: dict[str, Any] | CheckSpecAuthorityStatusInput | None = None,
    *,
    tool_context: ToolContext | None = None,  # pylint: disable=unused-argument
) -> dict[str, Any]:
    """Check whether compiled authority is current for a product."""
    raw_params = params
    if hasattr(raw_params, "model_dump"):
        raw_params = raw_params.model_dump()
    parsed = CheckSpecAuthorityStatusInput.model_validate(raw_params or {})

    with Session(_resolve_engine()) as session:
        spec_versions = session.exec(
            select(SpecRegistry)
            .where(SpecRegistry.product_id == parsed.product_id)
            .order_by(SpecRegistry.spec_version_id.desc())
        ).all()

        if not spec_versions:
            return {
                "success": True,
                "status": SpecAuthorityStatus.NOT_COMPILED.value,
                "status_details": "No spec versions exist for this product",
                "message": "Status: NOT_COMPILED (no specs)",
            }

        latest_spec = spec_versions[0]
        if latest_spec.status != "approved":
            return {
                "success": True,
                "status": SpecAuthorityStatus.PENDING_REVIEW.value,
                "status_details": (
                    f"Latest spec version {latest_spec.spec_version_id} "
                    f"is {latest_spec.status}"
                ),
                "latest_spec_version_id": latest_spec.spec_version_id,
                "message": "Status: PENDING_REVIEW (latest spec not approved)",
            }

        latest_approved = latest_spec
        latest_authority = session.exec(
            select(CompiledSpecAuthority)
            .join(SpecRegistry)
            .where(SpecRegistry.product_id == parsed.product_id)
            .order_by(CompiledSpecAuthority.spec_version_id.desc())
        ).first()

        if not latest_authority:
            return {
                "success": True,
                "status": SpecAuthorityStatus.NOT_COMPILED.value,
                "status_details": (
                    f"Latest approved spec version {latest_approved.spec_version_id} "
                    "is not compiled"
                ),
                "latest_approved_spec_version_id": latest_approved.spec_version_id,
                "message": "Status: NOT_COMPILED (approved but not compiled)",
            }

        if latest_authority.spec_version_id < latest_approved.spec_version_id:
            return {
                "success": True,
                "status": SpecAuthorityStatus.STALE.value,
                "status_details": "Compiled authority is stale (newer approved spec exists)",
                "compiled_spec_version_id": latest_authority.spec_version_id,
                "latest_approved_spec_version_id": latest_approved.spec_version_id,
                "message": "Status: STALE (compiled for older spec)",
            }

        return {
            "success": True,
            "status": SpecAuthorityStatus.CURRENT.value,
            "status_details": (
                "Compiled authority exists for latest approved spec "
                f"version {latest_approved.spec_version_id}"
            ),
            "latest_approved_spec_version_id": latest_approved.spec_version_id,
            "authority_id": latest_authority.authority_id,
            "compiled_at": latest_authority.compiled_at.isoformat(),
            "message": f"Status: CURRENT (authority ID: {latest_authority.authority_id})",
        }


def get_compiled_authority_by_version(
    params: dict[str, Any] | GetCompiledAuthorityInput | None = None,
    *,
    tool_context: ToolContext | None = None,  # pylint: disable=unused-argument
) -> dict[str, Any]:
    """Retrieve compiled authority for a specific spec version."""
    raw_params = params
    if hasattr(raw_params, "model_dump"):
        raw_params = raw_params.model_dump()
    parsed = GetCompiledAuthorityInput.model_validate(raw_params or {})

    with Session(_resolve_engine()) as session:
        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found",
            }

        if spec_version.product_id != parsed.product_id:
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} does not belong to "
                    f"product {parsed.product_id} (mismatch)"
                ),
            }

        authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == parsed.spec_version_id
            )
        ).first()

        if not authority:
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} is not compiled. "
                    "Use compile_spec_authority to compile it."
                ),
            }

        artifact = load_compiled_artifact(authority)
        if artifact:
            scope_themes = artifact.scope_themes
            invariants = [_render_invariant_summary(inv) for inv in artifact.invariants]
            spec_gaps = artifact.gaps
        else:
            scope_themes = json.loads(authority.scope_themes)
            invariants = json.loads(authority.invariants)
            spec_gaps = json.loads(authority.spec_gaps) if authority.spec_gaps else []

        eligible_feature_ids = json.loads(authority.eligible_feature_ids)
        rejected_features = (
            json.loads(authority.rejected_features)
            if authority.rejected_features
            else []
        )

        return {
            "success": True,
            "spec_version_id": parsed.spec_version_id,
            "authority_id": authority.authority_id,
            "compiler_version": authority.compiler_version,
            "compiled_at": authority.compiled_at.isoformat(),
            "scope_themes": scope_themes,
            "invariants": invariants,
            "eligible_feature_ids": eligible_feature_ids,
            "rejected_features": rejected_features,
            "spec_gaps": spec_gaps,
            "compiled_artifact_json": authority.compiled_artifact_json,
            "message": (
                f"Retrieved compiled authority for spec version "
                f"{parsed.spec_version_id}"
            ),
        }


__all__ = [
    "UpdateSpecAndCompileAuthorityInput",
    "CompileSpecAuthorityForVersionInput",
    "PreviewSpecAuthorityInput",
    "CheckSpecAuthorityStatusInput",
    "GetCompiledAuthorityInput",
    "load_compiled_artifact",
    "preview_spec_authority",
    "check_spec_authority_status",
    "get_compiled_authority_by_version",
    "ensure_accepted_spec_authority",
    "compile_spec_authority_for_version",
    "update_spec_and_compile_authority",
]
