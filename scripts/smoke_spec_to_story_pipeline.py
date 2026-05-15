"""Smoke harness: Spec Authority + Story Pipeline (agent-backed).

Run from repo root:
  python scripts/smoke_spec_to_story_pipeline.py
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import json
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, SQLModel, create_engine, select

from utils.cli_output import emit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from google.adk.sessions import InMemorySessionService  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import agile_sqlmodel  # noqa: E402
from agile_sqlmodel import (  # noqa: E402
    CompiledSpecAuthority,
    Product,
    SpecRegistry,
)
from models.core import Epic, Feature, ProductPersona, Theme  # noqa: E402
from tools import spec_tools  # noqa: E402
from tools.spec_tools import (  # noqa: E402
    compile_spec_authority_for_version,
    update_spec_and_compile_authority,
)

# Boundary contract: from models.core import ProductPersona
from utils.smoke_schema import parse_smoke_run_record  # noqa: E402
from utils.spec_schemas import (  # noqa: E402
    SpecAuthorityCompilationFailure,
    SpecAuthorityCompilerOutput,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from google.adk.sessions import Session as AdkSession
    from google.adk.sessions.base_session_service import GetSessionConfig


_STORY_PIPELINE_MODULES = {
    "single_story": "orchestrator_agent.agent_tools.story_pipeline.single_story",
    "tools": "orchestrator_agent.agent_tools.story_pipeline.tools",
    "alignment_checker": (
        "orchestrator_agent.agent_tools.story_pipeline.steps.alignment_checker"
    ),
    "generation_context": (
        "orchestrator_agent.agent_tools.story_pipeline.util.story_generation_context"
    ),
}
RAW_SPEC_FORWARDING_FIELD = "pass_raw_spec_text"


def _load_story_pipeline_module(module_key: str) -> Any:  # noqa: ANN401
    module_name = _STORY_PIPELINE_MODULES[module_key]
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        msg = (
            "The legacy story_pipeline smoke harness requires module "
            f"{module_name!r}, which is not present in this checkout."
        )
        raise RuntimeError(msg) from exc


single_story_module = _load_story_pipeline_module("single_story")
story_tools = _load_story_pipeline_module("tools")
_alignment_checker = _load_story_pipeline_module("alignment_checker")
check_alignment_violation = _alignment_checker.check_alignment_violation
derive_forbidden_capabilities_from_authority = (
    _alignment_checker.derive_forbidden_capabilities_from_authority
)
ProcessStoryInput = story_tools.ProcessStoryInput
process_single_story = story_tools.process_single_story
build_generation_context = _load_story_pipeline_module(
    "generation_context"
).build_generation_context


@dataclass
class DeterministicValidationResult:
    """Test helper for deterministic validation result."""

    passed: bool
    missing_fields: list[str]
    checked_fields: list[str]


def _make_engine() -> Any:  # noqa: ANN401
    temp_dir = Path(tempfile.mkdtemp(prefix="agileforge_smoke_"))
    db_path = temp_dir / "smoke.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _patch_engines(engine: Any) -> None:  # noqa: ANN401
    def smoke_engine() -> Any:  # noqa: ANN401
        return engine

    # Patch main module engine
    agile_sqlmodel.__dict__["engine"] = engine

    # Patch production engine to ensure get_engine() returns our test engine
    # even if get_engine() is imported directly by other modules.
    if hasattr(agile_sqlmodel, "_production_engine"):
        agile_sqlmodel.__dict__["_production_engine"] = engine

    # Patch get_engine globally
    agile_sqlmodel.__dict__["get_engine"] = smoke_engine

    spec_tools.__dict__["engine"] = engine
    if hasattr(spec_tools, "get_engine"):
        spec_tools.__dict__["get_engine"] = smoke_engine

    story_tools.__dict__["engine"] = engine

    # Patch single_story_module get_engine as it imports it from agile_sqlmodel
    if hasattr(single_story_module, "get_engine"):
        single_story_module.__dict__["get_engine"] = smoke_engine


def _require_id(value: int | None, name: str) -> int:
    if value is None:
        msg = f"{name} was not generated."
        raise RuntimeError(msg)
    return value


def _seed_product_graph(
    engine: Any,  # noqa: ANN401
    *,
    name: str,
    persona: str,
) -> dict[str, Any]:
    with Session(engine) as session:
        product = Product(name=name, vision="Tiny spec smoke harness")
        session.add(product)
        session.commit()
        session.refresh(product)

        product_id = _require_id(product.product_id, "product_id")

        persona_row = ProductPersona(
            product_id=product_id,
            persona_name=persona,
            is_default=True,
            category="primary_user",
        )
        session.add(persona_row)
        session.commit()

        theme = Theme(title="Core", product_id=product_id)
        session.add(theme)
        session.commit()
        session.refresh(theme)
        theme_id = _require_id(theme.theme_id, "theme_id")

        epic = Epic(title="User Data", theme_id=theme_id)
        session.add(epic)
        session.commit()
        session.refresh(epic)
        epic_id = _require_id(epic.epic_id, "epic_id")

        feature = Feature(title="Capture user_id in payload", epic_id=epic_id)
        session.add(feature)
        session.commit()
        session.refresh(feature)
        feature_id = _require_id(feature.feature_id, "feature_id")

        return {
            "product_id": product_id,
            "product_name": product.name,
            "product_vision": product.vision,
            "feature_id": feature_id,
            "feature_title": feature.title,
            "theme": theme.title,
            "epic": epic.title,
            "theme_id": theme_id,
            "epic_id": epic_id,
        }


def _compile_and_accept(
    *,
    product_id: int,
    spec_text: str,
) -> dict[str, Any]:
    update_result = update_spec_and_compile_authority(
        {
            "product_id": product_id,
            "spec_content": spec_text,
        },
        tool_context=None,
    )
    if not update_result.get("success"):
        msg = f"Spec update failed: {update_result}"
        raise RuntimeError(msg)
    return update_result


def _compile_without_acceptance(
    *,
    product_id: int,
    spec_text: str,
) -> dict[str, Any]:
    register = spec_tools.register_spec_version(
        {"product_id": product_id, "content": spec_text},
        tool_context=None,
    )
    if not register.get("success"):
        msg = f"Spec register failed: {register}"
        raise RuntimeError(msg)

    spec_version_id = register["spec_version_id"]
    approve = spec_tools.approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "smoke"},
        tool_context=None,
    )
    if not approve.get("success"):
        msg = f"Spec approval failed: {approve}"
        raise RuntimeError(msg)

    compiled = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )
    if not compiled.get("success"):
        msg = f"Spec compile failed: {compiled}"
        raise RuntimeError(msg)

    return {
        "spec_version_id": spec_version_id,
        "compiled_result": compiled,
    }


def _summarize_compiled_artifact(authority: CompiledSpecAuthority) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "compiler_version": authority.compiler_version,
        "prompt_hash": authority.prompt_hash,
        "compiled_at": authority.compiled_at.isoformat(),
    }
    if authority.compiled_artifact_json:
        parsed = SpecAuthorityCompilerOutput.model_validate_json(
            authority.compiled_artifact_json
        )
        if not isinstance(parsed.root, SpecAuthorityCompilationFailure):
            success = parsed.root
            summary.update(
                {
                    "scope_themes_count": len(success.scope_themes),
                    "invariants_count": len(success.invariants),
                    "gaps": success.gaps,
                    "assumptions": success.assumptions,
                }
            )
    return summary


def _deterministic_required_field_check(
    *,
    authority: CompiledSpecAuthority,
    story_text: str,
    story_metadata: dict[str, Any],
) -> DeterministicValidationResult:
    required_fields: list[str] = []
    if authority.compiled_artifact_json:
        parsed = SpecAuthorityCompilerOutput.model_validate_json(
            authority.compiled_artifact_json
        )
        if not isinstance(parsed.root, SpecAuthorityCompilationFailure):
            for inv in parsed.root.invariants:
                if inv.type == "REQUIRED_FIELD":
                    field_name = getattr(inv.parameters, "field_name", None)
                    if field_name:
                        required_fields.append(str(field_name))

    missing: list[str] = []
    for field in required_fields:
        if field == "spec_version_id":
            if story_metadata.get("spec_version_id") is None:
                missing.append(field)
        elif field not in story_text:
            missing.append(field)
    return DeterministicValidationResult(
        passed=len(missing) == 0,
        missing_fields=missing,
        checked_fields=required_fields,
    )


def _create_validation_story_text(*, include_user_id: bool) -> str:
    if include_user_id:
        return "- Payload includes user_id"
    return "- Payload includes account_id"


def _build_evidence_record(
    *,
    spec_version_id: int,
    validation: DeterministicValidationResult,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = [
        {
            "rule": "REQUIRED_FIELD",
            "expected": field,
            "actual": None,
            "message": f"Missing required field: {field}",
        }
        for field in validation.missing_fields
    ]
    return {
        "spec_version_id": spec_version_id,
        "passed": validation.passed,
        "invariants_checked": validation.checked_fields,
        "failures": failures,
    }


def _build_trace_base() -> dict[str, Any]:
    return {
        "RUN_ID": None,
        "SCENARIO_ID": None,
        "VARIANT": None,
        "TIMING_MS": None,
        "METRICS": None,
        "SPEC_UPDATE_RESULT": None,
        "SPEC_ACCEPTED": None,
        "COMPILED_ARTIFACT_SUMMARY": None,
        "AUTHORITY_CONTEXT_SUMMARY": None,
        "FORBIDDEN_CAPABILITIES": None,
        "FEATURE_TEXT": None,
        "USER_ID_IN_FEATURE": None,
        "OAUTH1_IN_FEATURE": None,
        "ALIGNMENT_REJECTED": None,
        "ALIGNMENT_ISSUES": None,
        "PINNED_SPEC_VERSION_ID": None,
        "DRAFT_SPEC_VERSION_ID": None,
        "REFINER_SPEC_VERSION_ID": None,
        "SPEC_VERSION_ID_MATCH": None,
        "DRAFT_AGENT_OUTPUT": None,
        "REFINER_OUTPUT": None,
        "VALIDATION_RESULT": None,
        "EVIDENCE_RECORD": None,
        "ACCEPTANCE_GATE_BLOCKED": False,
    }


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


class _TeeIO:
    def __init__(self, *streams: Any) -> None:  # noqa: ANN401
        self._streams = streams

    def write(self, data: str) -> int:
        total = 0
        for stream in self._streams:
            total += stream.write(data)
        return total

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


@contextlib.contextmanager
def _tee_output(log_path: Path | None) -> Any:  # noqa: ANN401
    if not log_path:
        yield
        return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        stdout = _TeeIO(sys.stdout, log_file)
        stderr = _TeeIO(sys.stderr, log_file)
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = stdout
        sys.stderr = stderr
        try:
            yield
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def _count_acceptance_criteria(story_payload: Any) -> int | None:  # noqa: ANN401
    if not isinstance(story_payload, dict):
        return None
    criteria = story_payload.get("acceptance_criteria")
    if not isinstance(criteria, str):
        return None
    lines = [line.strip() for line in criteria.split("\n")]
    bullets = [line for line in lines if line.startswith("-")]
    return len(bullets)


def _handle_unaccepted_spec(
    *,
    trace: dict[str, Any],
    spec_version_id: int,
    spec_accepted: bool,
    run_story_pipeline: Callable[[], Any],
) -> bool:
    del run_story_pipeline
    if spec_accepted:
        return False

    trace["SPEC_ACCEPTED"] = False
    trace["PINNED_SPEC_VERSION_ID"] = spec_version_id
    trace["ACCEPTANCE_GATE_BLOCKED"] = True
    trace["AUTHORITY_CONTEXT_SUMMARY"] = None
    trace["DRAFT_AGENT_OUTPUT"] = None
    trace["REFINER_OUTPUT"] = None
    trace["VALIDATION_RESULT"] = None
    trace["EVIDENCE_RECORD"] = None
    emit(
        "[Acceptance Gate] BLOCKED: authority not accepted for "
        f"spec_version_id={spec_version_id}"
    )
    return True


def _empty_metrics() -> dict[str, Any]:
    return {
        "acceptance_blocked": False,
        "alignment_rejected": False,
        "contract_passed": None,
        "required_fields_missing_count": None,
        "spec_version_id_match": None,
        "draft_present": False,
        "refiner_output_present": False,
        "refiner_ran": False,
        "final_story_present": False,
        "ac_count": None,
        "alignment_issues_count": 0,
        "stage": "pipeline_not_run",
    }


def _finalize_stage(metrics: dict[str, Any], pipeline_called: bool) -> str:
    if pipeline_called:
        if metrics.get("alignment_rejected"):
            return "alignment_rejected"
        if metrics.get("acceptance_blocked"):
            return "acceptance_blocked"
        return "pipeline_ran"
    if metrics.get("acceptance_blocked"):
        return "acceptance_blocked"
    if metrics.get("alignment_rejected"):
        return "alignment_rejected"
    return "pipeline_not_run"


def _refiner_ran(*, enable_refiner: bool, refiner_output: Any) -> bool:  # noqa: ANN401
    if not enable_refiner:
        return False
    if not isinstance(refiner_output, dict):
        return False
    return refiner_output.get("refinement_notes") != "Story refiner disabled."


def _validate_trace(trace: dict[str, Any]) -> None:
    try:
        parse_smoke_run_record(trace)
    except ValidationError as exc:
        run_id = trace.get("RUN_ID")
        scenario_id = trace.get("SCENARIO_ID")
        variant = trace.get("VARIANT")
        msg = (
            "Smoke record validation failed "
            f"RUN_ID={run_id} SCENARIO_ID={scenario_id} VARIANT={variant}"
        )
        raise RuntimeError(
            msg
        ) from exc


async def _run_scenario(  # noqa: C901, PLR0912, PLR0913, PLR0915
    *,
    engine: Any,  # noqa: ANN401
    scenario_id: int,
    enable_refiner: bool,
    enable_spec_validator: bool,
    pass_raw_spec_text: bool,
    debug_state: bool,
    spec_text: str,
    out_jsonl: Path | None,
) -> None:
    trace = _build_trace_base()
    pipeline_result: Any = None
    total_start = time.perf_counter()
    compile_ms: float | None = None
    pipeline_ms: float | None = None
    validation_ms: float | None = None
    pipeline_called = False
    metrics = _empty_metrics()

    trace["RUN_ID"] = str(uuid.uuid4())
    trace["SCENARIO_ID"] = scenario_id
    trace["VARIANT"] = {
        "enable_refiner": enable_refiner,
        "enable_spec_validator": enable_spec_validator,
        RAW_SPEC_FORWARDING_FIELD: pass_raw_spec_text,
    }

    try:
        seed = _seed_product_graph(
            engine,
            name=f"Smoke Scenario {scenario_id} {trace['RUN_ID']}",
            persona="automation engineer",
        )

        if scenario_id == 2:  # noqa: PLR2004
            feature_title = "OAuth1 login flow for user_id payload"
        else:
            feature_title = "Capture user_id in payload"

        trace["FEATURE_TEXT"] = feature_title
        trace["USER_ID_IN_FEATURE"] = "user_id" in feature_title.lower()
        trace["OAUTH1_IN_FEATURE"] = "oauth1" in feature_title.lower()

        if scenario_id == 3:  # noqa: PLR2004
            compile_start = time.perf_counter()
            compile_result = _compile_without_acceptance(
                product_id=seed["product_id"],
                spec_text=spec_text,
            )
            compile_ms = (time.perf_counter() - compile_start) * 1000
            trace["SPEC_UPDATE_RESULT"] = {
                "spec_version_id": compile_result["spec_version_id"],
                "compiled": compile_result["compiled_result"],
            }
            trace["SPEC_ACCEPTED"] = False
            trace["PINNED_SPEC_VERSION_ID"] = compile_result["spec_version_id"]
            with Session(engine) as session:
                compiled_authority = session.exec(
                    select(CompiledSpecAuthority).where(
                        CompiledSpecAuthority.spec_version_id
                        == compile_result["spec_version_id"]
                    )
                ).first()
                if compiled_authority:
                    trace["COMPILED_ARTIFACT_SUMMARY"] = _summarize_compiled_artifact(
                        compiled_authority
                    )
                    forbidden_items = derive_forbidden_capabilities_from_authority(
                        compiled_authority
                    )
                    forbidden_terms = [item.term for item in forbidden_items]
                    trace["FORBIDDEN_CAPABILITIES"] = forbidden_terms
                    alignment = check_alignment_violation(
                        feature_title,
                        forbidden_items,
                        context_label="feature",
                    )
                    trace["ALIGNMENT_REJECTED"] = not alignment.is_aligned
                    trace["ALIGNMENT_ISSUES"] = alignment.alignment_issues

            blocked = _handle_unaccepted_spec(
                trace=trace,
                spec_version_id=compile_result["spec_version_id"],
                spec_accepted=False,
                run_story_pipeline=lambda: process_single_story(
                    ProcessStoryInput(
                        product_id=seed["product_id"],
                        product_name=seed["product_name"],
                        product_vision=seed["product_vision"],
                        feature_id=seed["feature_id"],
                        feature_title=feature_title,
                        theme_id=seed["theme_id"],
                        epic_id=seed["epic_id"],
                        theme=seed["theme"],
                        epic=seed["epic"],
                        time_frame=None,
                        theme_justification=None,
                        sibling_features=None,
                        user_persona="automation engineer",
                        include_story_points=True,
                        spec_version_id=compile_result["spec_version_id"],
                        enable_story_refiner=enable_refiner,
                        enable_spec_validator=enable_spec_validator,
                        pass_raw_spec_text=pass_raw_spec_text,
                    )
                ),
            )
            if blocked:
                total_ms = (time.perf_counter() - total_start) * 1000
                trace["TIMING_MS"] = {
                    "total_ms": total_ms,
                    "compile_ms": compile_ms,
                    "pipeline_ms": None,
                    "validation_ms": None,
                }
                metrics["acceptance_blocked"] = True
                metrics["alignment_rejected"] = bool(trace.get("ALIGNMENT_REJECTED"))
                metrics["spec_version_id_match"] = trace.get("SPEC_VERSION_ID_MATCH")
                metrics["alignment_issues_count"] = (
                    len(trace.get("ALIGNMENT_ISSUES", []))
                    if isinstance(trace.get("ALIGNMENT_ISSUES"), list)
                    else 0
                )
                metrics["stage"] = "acceptance_blocked"
                metrics["final_story_present"] = metrics["draft_present"]
                trace["METRICS"] = metrics
                _validate_trace(trace)
                emit(json.dumps(trace, indent=2, default=str))
                if out_jsonl:
                    _append_jsonl(out_jsonl, trace)
                return

        compile_start = time.perf_counter()
        update_result = _compile_and_accept(
            product_id=seed["product_id"],
            spec_text=spec_text,
        )
        compile_ms = (time.perf_counter() - compile_start) * 1000
        trace["SPEC_UPDATE_RESULT"] = update_result
        trace["SPEC_ACCEPTED"] = update_result.get("accepted")
        spec_version_id = update_result["spec_version_id"]
        trace["PINNED_SPEC_VERSION_ID"] = spec_version_id

        with Session(engine) as session:
            spec_version = session.get(SpecRegistry, spec_version_id)
            compiled_authority = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == spec_version_id
                )
            ).first()
            if compiled_authority:
                trace["COMPILED_ARTIFACT_SUMMARY"] = _summarize_compiled_artifact(
                    compiled_authority
                )
                trace["AUTHORITY_CONTEXT_SUMMARY"] = build_generation_context(
                    compiled_authority=compiled_authority,
                    spec_version_id=spec_version_id,
                    spec_hash=getattr(spec_version, "spec_hash", None),
                )
                forbidden_items = derive_forbidden_capabilities_from_authority(
                    compiled_authority
                )
                forbidden_terms = [item.term for item in forbidden_items]
                trace["FORBIDDEN_CAPABILITIES"] = forbidden_terms
                alignment = check_alignment_violation(
                    feature_title,
                    forbidden_items,
                    context_label="feature",
                )
                trace["ALIGNMENT_REJECTED"] = not alignment.is_aligned
                trace["ALIGNMENT_ISSUES"] = alignment.alignment_issues

        if trace.get("ALIGNMENT_REJECTED") is True:
            total_ms = (time.perf_counter() - total_start) * 1000
            trace["TIMING_MS"] = {
                "total_ms": total_ms,
                "compile_ms": compile_ms,
                "pipeline_ms": None,
                "validation_ms": None,
            }
            metrics["alignment_rejected"] = True
            metrics["alignment_issues_count"] = (
                len(trace.get("ALIGNMENT_ISSUES", []))
                if isinstance(trace.get("ALIGNMENT_ISSUES"), list)
                else 0
            )
            metrics["stage"] = "alignment_rejected"
            metrics["final_story_present"] = metrics["draft_present"]
            trace["METRICS"] = metrics
            _validate_trace(trace)
            emit(json.dumps(trace, indent=2, default=str))
            if out_jsonl:
                _append_jsonl(out_jsonl, trace)
            return

        debug_state_holder: dict[str, Any] = {}

        class DebugSessionService(InMemorySessionService):
            async def create_session(
                self,
                *,
                app_name: str,
                user_id: str,
                state: dict[str, Any] | None = None,
                session_id: str | None = None,
            ) -> AdkSession:
                session = await super().create_session(
                    app_name=app_name,
                    user_id=user_id,
                    state=state,
                    session_id=session_id,
                )
                if session and getattr(session, "state", None) is not None:
                    debug_state_holder["state"] = session.state
                return session

            async def get_session(
                self,
                *,
                app_name: str,
                user_id: str,
                session_id: str,
                config: GetSessionConfig | None = None,
            ) -> AdkSession | None:
                session = await super().get_session(
                    app_name=app_name,
                    user_id=user_id,
                    session_id=session_id,
                    config=config,
                )
                if session and getattr(session, "state", None) is not None:
                    debug_state_holder["state"] = session.state
                return session

        original_session_service = single_story_module.InMemorySessionService
        single_story_module.InMemorySessionService = DebugSessionService
        try:
            pipeline_start = time.perf_counter()
            pipeline_called = True
            pipeline_result = await process_single_story(
                ProcessStoryInput(
                    product_id=seed["product_id"],
                    product_name=seed["product_name"],
                    product_vision=seed["product_vision"],
                    feature_id=seed["feature_id"],
                    feature_title=feature_title,
                    theme_id=seed["theme_id"],
                    epic_id=seed["epic_id"],
                    theme=seed["theme"],
                    epic=seed["epic"],
                    time_frame=None,
                    theme_justification=None,
                    sibling_features=None,
                    user_persona="automation engineer",
                    include_story_points=True,
                    spec_version_id=spec_version_id,
                    enable_story_refiner=enable_refiner,
                    enable_spec_validator=enable_spec_validator,
                    pass_raw_spec_text=pass_raw_spec_text,
                )
            )
            pipeline_ms = (time.perf_counter() - pipeline_start) * 1000
        finally:
            single_story_module.InMemorySessionService = original_session_service

        if isinstance(pipeline_result, dict):
            trace["ALIGNMENT_REJECTED"] = pipeline_result.get("rejected")
            trace["ALIGNMENT_ISSUES"] = pipeline_result.get("alignment_issues")

        state = debug_state_holder.get("state", {})
        trace["DRAFT_AGENT_OUTPUT"] = state.get("story_draft")
        trace["REFINER_OUTPUT"] = state.get("refinement_result")

        draft_metadata = {}
        if isinstance(trace["DRAFT_AGENT_OUTPUT"], dict):
            draft_metadata = trace["DRAFT_AGENT_OUTPUT"].get("metadata", {})
        trace["DRAFT_SPEC_VERSION_ID"] = draft_metadata.get("spec_version_id")

        refined_metadata = {}
        if isinstance(trace["REFINER_OUTPUT"], dict):
            refined_story = trace["REFINER_OUTPUT"].get("refined_story", {})
            if isinstance(refined_story, dict):
                refined_metadata = refined_story.get("metadata", {})
        trace["REFINER_SPEC_VERSION_ID"] = refined_metadata.get("spec_version_id")

        if trace["PINNED_SPEC_VERSION_ID"] is not None:
            if trace["REFINER_SPEC_VERSION_ID"] is not None:
                trace["SPEC_VERSION_ID_MATCH"] = (
                    trace["PINNED_SPEC_VERSION_ID"] == trace["REFINER_SPEC_VERSION_ID"]
                )
            elif trace["DRAFT_SPEC_VERSION_ID"] is not None:
                trace["SPEC_VERSION_ID_MATCH"] = (
                    trace["PINNED_SPEC_VERSION_ID"] == trace["DRAFT_SPEC_VERSION_ID"]
                )

        if debug_state:
            trace["SPEC_VALIDATOR_STATE_KEYS"] = sorted(state.keys())
            trace["RAW_SPEC_TEXT_PRESENT"] = "raw_spec_text" in state

        validation_story_text = _create_validation_story_text(
            include_user_id=(scenario_id == 1)
        )

        with Session(engine) as session:
            authority = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == spec_version_id
                )
            ).first()
            if not authority:
                msg = "Compiled authority not found"
                raise RuntimeError(msg)  # noqa: TRY301

        validation_start = time.perf_counter()
        validation = _deterministic_required_field_check(
            authority=authority,
            story_text=validation_story_text,
            story_metadata=refined_metadata or draft_metadata,
        )
        validation_ms = (time.perf_counter() - validation_start) * 1000
        trace["VALIDATION_RESULT"] = asdict(validation)
        trace["EVIDENCE_RECORD"] = _build_evidence_record(
            spec_version_id=spec_version_id,
            validation=validation,
        )

    except Exception as exc:
        trace["ERROR"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        total_ms = (time.perf_counter() - total_start) * 1000
        trace["TIMING_MS"] = {
            "total_ms": total_ms,
            "compile_ms": compile_ms,
            "pipeline_ms": pipeline_ms,
            "validation_ms": validation_ms,
        }
        metrics["stage"] = "crashed"
        metrics["acceptance_blocked"] = bool(trace.get("ACCEPTANCE_GATE_BLOCKED"))
        metrics["alignment_rejected"] = bool(trace.get("ALIGNMENT_REJECTED"))
        metrics["alignment_issues_count"] = (
            len(trace.get("ALIGNMENT_ISSUES", []))
            if isinstance(trace.get("ALIGNMENT_ISSUES"), list)
            else 0
        )
        trace["METRICS"] = metrics
        _validate_trace(trace)
        emit(json.dumps(trace, indent=2, default=str))
        raise

    total_ms = (time.perf_counter() - total_start) * 1000

    # Ensure pipeline_ms is None if alignment rejected (schema requirement)
    if trace.get("ALIGNMENT_REJECTED"):
        pipeline_ms = None

    trace["TIMING_MS"] = {
        "total_ms": total_ms,
        "compile_ms": compile_ms,
        "pipeline_ms": pipeline_ms,
        "validation_ms": validation_ms,
    }
    validation_result = trace.get("VALIDATION_RESULT")
    missing_fields: int | None = None
    if isinstance(validation_result, dict):
        missing = validation_result.get("missing_fields")
        if isinstance(missing, list):
            missing_fields = len(missing)
        elif validation_result.get("passed") is True:
            missing_fields = 0

    alignment_issues = trace.get("ALIGNMENT_ISSUES")
    alignment_issue_count = None
    if isinstance(alignment_issues, list):
        alignment_issue_count = len(alignment_issues)

    final_story_payload: dict[str, Any] | None = None
    if isinstance(trace.get("REFINER_OUTPUT"), dict):
        refined_story = trace["REFINER_OUTPUT"].get("refined_story")
        if isinstance(refined_story, dict):
            final_story_payload = refined_story
    if final_story_payload is None and isinstance(
        trace.get("DRAFT_AGENT_OUTPUT"), dict
    ):
        final_story_payload = trace["DRAFT_AGENT_OUTPUT"]

    final_story_present = final_story_payload is not None  # noqa: F841
    ac_count = _count_acceptance_criteria(final_story_payload)

    metrics["acceptance_blocked"] = bool(trace.get("ACCEPTANCE_GATE_BLOCKED"))
    metrics["alignment_rejected"] = bool(trace.get("ALIGNMENT_REJECTED"))
    metrics["draft_present"] = trace.get("DRAFT_AGENT_OUTPUT") is not None
    metrics["refiner_output_present"] = trace.get("REFINER_OUTPUT") is not None
    metrics["refiner_ran"] = _refiner_ran(
        enable_refiner=enable_refiner,
        refiner_output=trace.get("REFINER_OUTPUT"),
    )
    metrics["final_story_present"] = (
        metrics["refiner_ran"] or metrics["draft_present"]
        if enable_refiner
        else metrics["draft_present"]
    )
    metrics["ac_count"] = ac_count
    metrics["spec_version_id_match"] = trace.get("SPEC_VERSION_ID_MATCH")
    metrics["required_fields_missing_count"] = (
        missing_fields if missing_fields is not None else 0
    )
    metrics["alignment_issues_count"] = alignment_issue_count or 0

    if pipeline_called:
        # Get is_valid from pipeline result - can be True, False, or None (unknown/skipped)  # noqa: E501
        if isinstance(pipeline_result, dict) and "is_valid" in pipeline_result:
            pipeline_is_valid = pipeline_result.get("is_valid")
            # Preserve None explicitly - don't apply fallback logic when validation was skipped  # noqa: E501
            if pipeline_is_valid is None:
                # Validation was skipped (e.g., enable_spec_validator=False)
                # Keep contract_passed=None to indicate "unknown" status
                metrics["contract_passed"] = None
            else:
                metrics["contract_passed"] = pipeline_is_valid
        else:
            # Pipeline didn't return is_valid - apply fallback logic
            metrics["contract_passed"] = None
            if metrics["final_story_present"] and validation_result is not None:
                metrics["contract_passed"] = bool(validation_result.get("passed"))
            elif metrics["final_story_present"]:
                metrics["contract_passed"] = True
            else:
                metrics["contract_passed"] = False
    else:
        metrics["contract_passed"] = None

    metrics["stage"] = _finalize_stage(metrics, pipeline_called)

    trace["METRICS"] = metrics

    _validate_trace(trace)
    emit(json.dumps(trace, indent=2, default=str))
    if out_jsonl:
        _append_jsonl(out_jsonl, trace)


async def _run_all(args: argparse.Namespace) -> None:
    out_jsonl = Path(args.out_jsonl).resolve() if args.out_jsonl else None  # noqa: ASYNC240
    if args.fresh_jsonl and out_jsonl:
        out_jsonl.write_text("", encoding="utf-8")

    if args.spec_path:
        spec_text = Path(args.spec_path).read_text(encoding="utf-8").strip()  # noqa: ASYNC240
    else:
        spec_text = """
# Spec

## Requirements
- The payload must include user_id.
- The system must not use OAuth1 authentication.
""".strip()

    engine = _make_engine()
    _patch_engines(engine)

    scenario_map = {
        "1": [1],
        "2": [2],
        "3": [3],
        "all": [1, 2, 3],
    }

    variants = {
        "V000": {
            "enable_refiner": False,
            "enable_spec_validator": False,
            RAW_SPEC_FORWARDING_FIELD: False,
        },
        "V001": {
            "enable_refiner": False,
            "enable_spec_validator": False,
            RAW_SPEC_FORWARDING_FIELD: True,
        },
        "V010": {
            "enable_refiner": False,
            "enable_spec_validator": True,
            RAW_SPEC_FORWARDING_FIELD: False,
        },
        "V011": {
            "enable_refiner": False,
            "enable_spec_validator": True,
            RAW_SPEC_FORWARDING_FIELD: True,
        },
        "V100": {
            "enable_refiner": True,
            "enable_spec_validator": False,
            RAW_SPEC_FORWARDING_FIELD: False,
        },
        "V101": {
            "enable_refiner": True,
            "enable_spec_validator": False,
            RAW_SPEC_FORWARDING_FIELD: True,
        },
        "V110": {
            "enable_refiner": True,
            "enable_spec_validator": True,
            RAW_SPEC_FORWARDING_FIELD: False,
        },
        "V111": {
            "enable_refiner": True,
            "enable_spec_validator": True,
            RAW_SPEC_FORWARDING_FIELD: True,
        },
    }

    variant_keys = list(variants.keys()) if args.variant == "all" else [args.variant]

    for _ in range(args.repeat):
        for scenario_id in scenario_map[args.scenario]:
            for variant_key in variant_keys:
                variant = variants[variant_key]
                enable_refiner = variant["enable_refiner"] and not args.no_refiner
                enable_spec_validator = (
                    variant["enable_spec_validator"] and not args.no_spec_validator
                )
                pass_raw_spec_text = (
                    variant[RAW_SPEC_FORWARDING_FIELD] and not args.no_raw_spec_text
                )
                await _run_scenario(
                    engine=engine,
                    scenario_id=scenario_id,
                    enable_refiner=enable_refiner,
                    enable_spec_validator=enable_spec_validator,
                    pass_raw_spec_text=pass_raw_spec_text,
                    debug_state=args.debug_state,
                    spec_text=spec_text,
                    out_jsonl=out_jsonl,
                )


def main() -> None:
    """Return main."""
    parser = argparse.ArgumentParser(
        description="Smoke Spec Authority -> Story Pipeline"
    )
    parser.add_argument(
        "--no-refiner",
        action="store_true",
        help="Disable story refiner agent",
    )
    parser.add_argument(
        "--no-spec-validator",
        action="store_true",
        help="Disable spec validator agent",
    )
    parser.add_argument(
        "--no-raw-spec-text",
        action="store_true",
        help="Do not pass raw spec text into session state",
    )
    parser.add_argument(
        "--variant",
        choices=[
            "V000",
            "V001",
            "V010",
            "V011",
            "V100",
            "V101",
            "V110",
            "V111",
            "all",
        ],
        default="all",
        help="Run a specific A/B variant or all variants",
    )
    parser.add_argument(
        "--out-jsonl",
        help="Append results to a JSONL file",
    )
    parser.add_argument(
        "--fresh-jsonl",
        action="store_true",
        help="Truncate the JSONL output file before running",
    )
    parser.add_argument(
        "--out-log",
        default=str(Path("artifacts") / "smoke_runs.log"),
        help="Append terminal output to a log file",
    )
    parser.add_argument(
        "--scenario",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Run a single scenario or all",
    )
    parser.add_argument(
        "--debug-state",
        action="store_true",
        help="Print state keys passed through pipeline",
    )
    parser.add_argument(
        "--spec-path",
        help="Path to a markdown spec to use",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat each scenario/variant run N times",
    )

    args = parser.parse_args()
    log_path = Path(args.out_log).resolve() if args.out_log else None
    with _tee_output(log_path):
        asyncio.run(_run_all(args))


if __name__ == "__main__":
    main()
