from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from agile_sqlmodel import (
    StoryCompletionLog,
    SprintStory,
    UserStory,
    ensure_business_db_ready,
    get_engine,
)

from orchestrator_agent.agent_tools.product_vision_tool.tools import (
    SaveVisionInput,
    save_vision_tool,
)
from orchestrator_agent.agent_tools.backlog_primer.tools import (
    SaveBacklogInput,
    save_backlog_tool,
)
from orchestrator_agent.agent_tools.roadmap_builder.tools import (
    SaveRoadmapToolInput,
    save_roadmap_tool,
)
from orchestrator_agent.agent_tools.user_story_writer_tool.tools import (
    SaveStoriesInput,
    save_stories_tool,
)
from orchestrator_agent.fsm.states import OrchestratorState
from repositories.product import ProductRepository
from services.vision_runtime import run_vision_agent_from_state
from services.backlog_runtime import run_backlog_agent_from_state
from services.roadmap_runtime import run_roadmap_agent_from_state
from services.story_runtime import run_story_agent_from_state
from services.workflow import WorkflowService
from tools.orchestrator_tools import select_project
from tools.spec_tools import link_spec_to_product
from utils.failure_artifacts import read_failure_artifact
from utils.logging_config import configure_logging
from utils.runtime_config import get_api_host, get_api_port, get_api_reload

configure_logging()
logger = logging.getLogger(__name__)

product_repo = ProductRepository()
workflow_service = WorkflowService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    ensure_business_db_ready()
    migrated = workflow_service.migrate_legacy_setup_state()
    if migrated:
        logger.info("Migrated %s legacy sessions from ROUTING_MODE to SETUP_REQUIRED", migrated)
    yield


app = FastAPI(title="AgenticFlow API", lifespan=lifespan)

app.mount("/dashboard", StaticFiles(directory="frontend", html=True), name="frontend")


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    spec_file_path: str = Field(min_length=1)


class RetrySetupRequest(BaseModel):
    spec_file_path: str = Field(min_length=1)


class VisionGenerateRequest(BaseModel):
    user_input: Optional[str] = None


class BacklogGenerateRequest(BaseModel):
    user_input: Optional[str] = None


class RoadmapGenerateRequest(BaseModel):
    user_input: Optional[str] = None


class StoryGenerateRequest(BaseModel):
    user_input: Optional[str] = None


WORKFLOW_STEPS: List[Dict[str, Any]] = [
    {
        "id": "setup",
        "label": "Project Setup",
        "states": [OrchestratorState.SETUP_REQUIRED.value],
    },
    {
        "id": "vision",
        "label": "Vision",
        "states": [
            OrchestratorState.VISION_INTERVIEW.value,
            OrchestratorState.VISION_REVIEW.value,
            OrchestratorState.VISION_PERSISTENCE.value,
        ],
    },
    {
        "id": "backlog",
        "label": "Backlog",
        "states": [
            OrchestratorState.BACKLOG_INTERVIEW.value,
            OrchestratorState.BACKLOG_REVIEW.value,
            OrchestratorState.BACKLOG_PERSISTENCE.value,
        ],
    },
    {
        "id": "roadmap",
        "label": "Roadmap",
        "states": [
            OrchestratorState.ROADMAP_INTERVIEW.value,
            OrchestratorState.ROADMAP_REVIEW.value,
            OrchestratorState.ROADMAP_PERSISTENCE.value,
        ],
    },
    {
        "id": "story",
        "label": "Stories",
        "states": [
            OrchestratorState.STORY_INTERVIEW.value,
            OrchestratorState.STORY_REVIEW.value,
            OrchestratorState.STORY_PERSISTENCE.value,
        ],
    },
    {
        "id": "sprint",
        "label": "Sprint",
        "states": [
            OrchestratorState.SPRINT_SETUP.value,
            OrchestratorState.SPRINT_DRAFT.value,
            OrchestratorState.SPRINT_PERSISTENCE.value,
            OrchestratorState.SPRINT_VIEW.value,
            OrchestratorState.SPRINT_LIST.value,
            OrchestratorState.SPRINT_UPDATE_STORY.value,
            OrchestratorState.SPRINT_MODIFY.value,
            OrchestratorState.SPRINT_COMPLETE.value,
        ],
    },
]
VALID_FSM_STATES = {state.value for state in OrchestratorState}
FAILURE_META_FIELDS = (
    "failure_artifact_id",
    "failure_stage",
    "failure_summary",
    "raw_output_preview",
    "has_full_artifact",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_fsm_state(value: Optional[str]) -> str:
    """Normalize state to canonical key, fallback to SETUP_REQUIRED."""
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in VALID_FSM_STATES:
            return normalized
    return OrchestratorState.SETUP_REQUIRED.value


def _failure_meta(
    source: Optional[Dict[str, Any]],
    *,
    fallback_summary: Optional[str] = None,
) -> Dict[str, Any]:
    payload = source or {}
    return {
        "failure_artifact_id": payload.get("failure_artifact_id"),
        "failure_stage": payload.get("failure_stage"),
        "failure_summary": payload.get("failure_summary") or fallback_summary,
        "raw_output_preview": payload.get("raw_output_preview"),
        "has_full_artifact": bool(payload.get("has_full_artifact", False)),
    }


def _set_setup_failure_meta(
    state: Dict[str, Any],
    source: Optional[Dict[str, Any]],
    *,
    error_message: Optional[str],
) -> Dict[str, Any]:
    metadata = _failure_meta(source, fallback_summary=error_message)
    state["setup_failure_artifact_id"] = metadata["failure_artifact_id"]
    state["setup_failure_stage"] = metadata["failure_stage"]
    state["setup_failure_summary"] = metadata["failure_summary"]
    state["setup_raw_output_preview"] = metadata["raw_output_preview"]
    state["setup_has_full_artifact"] = metadata["has_full_artifact"]
    return metadata


def _clear_setup_failure_meta(state: Dict[str, Any]) -> None:
    state["setup_failure_artifact_id"] = None
    state["setup_failure_stage"] = None
    state["setup_failure_summary"] = None
    state["setup_raw_output_preview"] = None
    state["setup_has_full_artifact"] = False


def _setup_blocker(product: Any) -> Optional[str]:
    if not product:
        return "Project not found."

    spec_file_path = (getattr(product, "spec_file_path", None) or "").strip()
    if not spec_file_path:
        return "Specification file path is required."

    if not Path(spec_file_path).exists():
        return "Specification file path does not exist on disk."

    compiled_authority = getattr(product, "compiled_authority_json", None)
    if not compiled_authority:
        return "Specification authority is missing. Run setup retry."

    return None


async def _ensure_session(session_id: str) -> Dict[str, Any]:
    state = workflow_service.get_session_status(session_id) or {}
    if not state.get("fsm_state"):
        await workflow_service.initialize_session(session_id=session_id)
        state = workflow_service.get_session_status(session_id) or {}
    return state


async def _hydrate_context(session_id: str, project_id: int) -> SimpleNamespace:
    state = await _ensure_session(session_id)
    context = SimpleNamespace(state=dict(state), session_id=session_id)
    select_project(project_id, context)
    return context


def _save_session_state(session_id: str, state: Dict[str, Any]) -> None:
    workflow_service.update_session_status(session_id, state)


def _vision_state_from_complete(is_complete: bool) -> str:
    return (
        OrchestratorState.VISION_REVIEW.value
        if is_complete
        else OrchestratorState.VISION_INTERVIEW.value
    )


def _ensure_vision_attempts(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    attempts = state.get("vision_attempts")
    if not isinstance(attempts, list):
        attempts = []
    return attempts


def _record_vision_attempt(
    state: Dict[str, Any],
    *,
    trigger: str,
    input_context: Dict[str, Any],
    output_artifact: Dict[str, Any],
    is_complete: bool,
    failure_meta: Optional[Dict[str, Any]] = None,
) -> int:
    attempts = _ensure_vision_attempts(state)
    normalized_failure = _failure_meta(failure_meta)
    attempts.append(
        {
            "created_at": _now_iso(),
            "trigger": trigger,
            "input_context": input_context,
            "output_artifact": output_artifact,
            "is_complete": is_complete,
            **normalized_failure,
        }
    )
    state["vision_attempts"] = attempts
    state["vision_last_input_context"] = input_context
    state["product_vision_assessment"] = output_artifact
    if isinstance(output_artifact.get("updated_components"), dict):
        state["vision_components"] = output_artifact["updated_components"]
    return len(attempts)


def _set_vision_fsm_state(state: Dict[str, Any], *, is_complete: bool) -> str:
    next_state = _vision_state_from_complete(is_complete)
    state["fsm_state"] = next_state
    state["fsm_state_entered_at"] = _now_iso()
    return next_state


async def _run_setup(session_id: str, project_id: int, spec_file_path: str) -> Dict[str, Any]:
    context = await _hydrate_context(session_id, project_id)

    result = link_spec_to_product(
        {
            "product_id": project_id,
            "spec_path": spec_file_path,
        },
        tool_context=context,
    )

    # Rehydrate after setup attempt to refresh active project + compiled authority cache.
    select_project(project_id, context)

    setup_passed = bool(result.get("success") and result.get("compile_success"))
    error_message = None
    next_state = OrchestratorState.SETUP_REQUIRED.value
    vision_auto_run: Dict[str, Any] = {
        "attempted": False,
        "success": False,
        "is_complete": None,
        "error": None,
        "trigger": "auto_setup_transition",
        **_failure_meta(None),
    }

    if not setup_passed:
        error_message = result.get("compile_error") or result.get("error") or "Setup failed"
    else:
        latest_product = product_repo.get_by_id(project_id)
        blocker = _setup_blocker(latest_product)
        if blocker:
            setup_passed = False
            error_message = blocker
        else:
            vision_result = await run_vision_agent_from_state(
                context.state,
                project_id=project_id,
                user_input="",
            )
            attempt_is_complete = bool(vision_result.get("is_complete")) if vision_result.get("success") else False
            _record_vision_attempt(
                context.state,
                trigger="auto_setup_transition",
                input_context=vision_result.get("input_context") or {},
                output_artifact=vision_result.get("output_artifact") or {},
                is_complete=attempt_is_complete,
                failure_meta=vision_result,
            )
            next_state = _set_vision_fsm_state(
                context.state,
                is_complete=attempt_is_complete,
            )
            vision_auto_run = {
                "attempted": True,
                "success": bool(vision_result.get("success")),
                "is_complete": vision_result.get("is_complete") if vision_result.get("success") else None,
                "error": vision_result.get("error"),
                "trigger": "auto_setup_transition",
                **_failure_meta(vision_result, fallback_summary=vision_result.get("error")),
            }

    if not setup_passed:
        context.state["fsm_state"] = OrchestratorState.SETUP_REQUIRED.value
        context.state["fsm_state_entered_at"] = _now_iso()
        next_state = OrchestratorState.SETUP_REQUIRED.value
        setup_failure_meta = _set_setup_failure_meta(
            context.state,
            result,
            error_message=error_message,
        )
    else:
        _clear_setup_failure_meta(context.state)
        setup_failure_meta = _failure_meta(None)
    context.state["setup_status"] = "passed" if setup_passed else "failed"
    context.state["setup_error"] = error_message
    context.state["setup_spec_file_path"] = spec_file_path

    _save_session_state(session_id, context.state)

    return {
        "passed": setup_passed,
        "error": error_message,
        "detail": result,
        "fsm_state": next_state,
        "vision_auto_run": vision_auto_run,
        **setup_failure_meta,
    }


def _effective_project_state(project: Any, raw_state: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(raw_state)
    blocker = _setup_blocker(project)
    spec_path = getattr(project, "spec_file_path", None)

    if blocker:
        state["fsm_state"] = OrchestratorState.SETUP_REQUIRED.value
        state["setup_status"] = "failed"
        existing_error = state.get("setup_error")
        state["setup_error"] = existing_error or blocker
    else:
        state["fsm_state"] = _normalize_fsm_state(state.get("fsm_state"))
        state.setdefault("setup_status", "passed")
        state.setdefault("setup_error", None)
    state.setdefault("setup_failure_artifact_id", None)
    state.setdefault("setup_failure_stage", None)
    state.setdefault("setup_failure_summary", state.get("setup_error"))
    state.setdefault("setup_raw_output_preview", None)
    state.setdefault("setup_has_full_artifact", False)
    if spec_path:
        state["setup_spec_file_path"] = spec_path

    return state


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/api/dashboard/config")
def get_dashboard_config():
    return {
        "status": "success",
        "data": {
            "workflow_steps": WORKFLOW_STEPS,
        },
    }


@app.get("/api/projects")
def get_projects():
    try:
        products = product_repo.get_all()
        payload = []

        for product in products:
            session_id = str(product.product_id)
            raw_state = workflow_service.get_session_status(session_id) or {}
            effective_state = _effective_project_state(product, raw_state)

            payload.append(
                {
                    "id": product.product_id,
                    "name": product.name,
                    "summary": product.description or "No description provided",
                    "fsm_state": effective_state.get("fsm_state", OrchestratorState.SETUP_REQUIRED.value),
                "setup_status": effective_state.get("setup_status", "failed"),
                "setup_error": effective_state.get("setup_error"),
                "setup_failure_artifact_id": effective_state.get("setup_failure_artifact_id"),
                "setup_failure_stage": effective_state.get("setup_failure_stage"),
                "setup_failure_summary": effective_state.get("setup_failure_summary"),
                "setup_raw_output_preview": effective_state.get("setup_raw_output_preview"),
                "setup_has_full_artifact": effective_state.get("setup_has_full_artifact", False),
            }
        )

        return {"status": "success", "data": payload}
    except Exception as exc:
        logger.error("Error fetching projects: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/projects")
async def create_project(req: CreateProjectRequest):
    try:
        new_product = product_repo.create(name=req.name)
        session_id = str(new_product.product_id)
        await workflow_service.initialize_session(session_id=session_id)

        setup_result = await _run_setup(session_id, int(new_product.product_id), req.spec_file_path)

        return {
            "status": "success",
            "data": {
                "id": new_product.product_id,
                "name": new_product.name,
                "setup_status": "passed" if setup_result["passed"] else "failed",
                "setup_error": setup_result["error"],
                "fsm_state": setup_result["fsm_state"],
                "vision_auto_run": setup_result.get("vision_auto_run"),
                **_failure_meta(setup_result, fallback_summary=setup_result["error"]),
            },
        }
    except Exception as exc:
        logger.error("Error creating project: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create project") from exc


@app.post("/api/projects/{project_id}/setup/retry")
async def retry_project_setup(project_id: int, req: RetrySetupRequest):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    await _ensure_session(session_id)
    setup_result = await _run_setup(session_id, project_id, req.spec_file_path)

    return {
        "status": "success",
        "data": {
            "id": project_id,
            "name": product.name,
            "setup_status": "passed" if setup_result["passed"] else "failed",
                "setup_error": setup_result["error"],
                "fsm_state": setup_result["fsm_state"],
                "vision_auto_run": setup_result.get("vision_auto_run"),
                **_failure_meta(setup_result, fallback_summary=setup_result["error"]),
            },
        }


@app.get("/api/projects/{project_id}/state")
async def get_project_state(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    effective_state = _effective_project_state(product, state)

    _save_session_state(session_id, effective_state)

    return {"status": "success", "data": effective_state}


@app.get("/api/projects/{project_id}/debug/failures/{artifact_id}")
async def get_project_failure_artifact(project_id: int, artifact_id: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    artifact = read_failure_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Failure artifact not found")

    if artifact.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail="Failure artifact not found for project")

    return {"status": "success", "data": artifact}


@app.post("/api/projects/{project_id}/vision/generate")
async def generate_project_vision(project_id: int, req: VisionGenerateRequest):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    blocker = _setup_blocker(product)
    if blocker:
        raise HTTPException(status_code=409, detail=f"Setup required: {blocker}")

    session_id = str(project_id)
    context = await _hydrate_context(session_id, project_id)

    attempts = _ensure_vision_attempts(context.state)
    has_attempts = len(attempts) > 0
    user_input = (req.user_input or "").strip()
    if has_attempts and not user_input:
        raise HTTPException(
            status_code=409,
            detail="Feedback is required for Vision refinement attempts",
        )

    vision_result = await run_vision_agent_from_state(
        context.state,
        project_id=project_id,
        user_input=user_input,
    )
    is_complete = bool(vision_result.get("is_complete")) if vision_result.get("success") else False

    attempt_count = _record_vision_attempt(
        context.state,
        trigger="manual_refine",
        input_context=vision_result.get("input_context") or {},
        output_artifact=vision_result.get("output_artifact") or {},
        is_complete=is_complete,
        failure_meta=vision_result,
    )
    next_state = _set_vision_fsm_state(
        context.state,
        is_complete=is_complete,
    )

    _save_session_state(session_id, context.state)

    return {
        "status": "success",
        "data": {
            "fsm_state": next_state,
            "is_complete": is_complete,
            "vision_run_success": bool(vision_result.get("success")),
            "error": vision_result.get("error"),
            "trigger": "manual_refine",
            "input_context": vision_result.get("input_context"),
            "output_artifact": vision_result.get("output_artifact"),
            "attempt_count": attempt_count,
            **_failure_meta(vision_result, fallback_summary=vision_result.get("error")),
        },
    }


@app.get("/api/projects/{project_id}/vision/history")
async def get_project_vision_history(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    attempts = state.get("vision_attempts")
    if not isinstance(attempts, list):
        attempts = []

    return {
        "status": "success",
        "data": {
            "items": attempts,
            "count": len(attempts),
        },
    }


@app.post("/api/projects/{project_id}/vision/save")
async def save_project_vision(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    blocker = _setup_blocker(product)
    if blocker:
        raise HTTPException(status_code=409, detail=f"Setup required: {blocker}")

    session_id = str(project_id)
    state = await _ensure_session(session_id)

    assessment = state.get("product_vision_assessment")
    if not isinstance(assessment, dict):
        raise HTTPException(status_code=409, detail="No vision draft available to save")

    if not bool(assessment.get("is_complete", False)):
        raise HTTPException(
            status_code=409,
            detail="Vision cannot be saved until is_complete is true",
        )

    statement = assessment.get("product_vision_statement")
    if not isinstance(statement, str) or not statement.strip():
        raise HTTPException(status_code=409, detail="Vision statement is empty")

    context = await _hydrate_context(session_id, project_id)
    result = save_vision_tool(
        SaveVisionInput(
            product_id=project_id,
            project_name=product.name,
            product_vision_statement=statement,
        ),
        context,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to save vision"))

    context.state["fsm_state"] = OrchestratorState.VISION_PERSISTENCE.value
    context.state["fsm_state_entered_at"] = _now_iso()
    context.state["vision_saved_at"] = _now_iso()
    context.state["setup_status"] = "passed"

    _save_session_state(session_id, context.state)

    return {
        "status": "success",
        "data": {
            "fsm_state": OrchestratorState.VISION_PERSISTENCE.value,
            "save_result": result,
        },
    }


def _backlog_state_from_complete(is_complete: bool) -> str:
    return (
        OrchestratorState.BACKLOG_REVIEW.value
        if is_complete
        else OrchestratorState.BACKLOG_INTERVIEW.value
    )


def _ensure_backlog_attempts(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    attempts = state.get("backlog_attempts")
    if not isinstance(attempts, list):
        attempts = []
    return attempts


def _record_backlog_attempt(
    state: Dict[str, Any],
    *,
    trigger: str,
    input_context: Dict[str, Any],
    output_artifact: Dict[str, Any],
    is_complete: bool,
    failure_meta: Optional[Dict[str, Any]] = None,
) -> int:
    attempts = _ensure_backlog_attempts(state)
    normalized_failure = _failure_meta(failure_meta)
    attempts.append(
        {
            "created_at": _now_iso(),
            "trigger": trigger,
            "input_context": input_context,
            "output_artifact": output_artifact,
            "is_complete": is_complete,
            **normalized_failure,
        }
    )
    state["backlog_attempts"] = attempts
    state["backlog_last_input_context"] = input_context
    state["product_backlog_assessment"] = output_artifact
    if isinstance(output_artifact.get("backlog_items"), list):
        state["backlog_items"] = output_artifact["backlog_items"]
    return len(attempts)


def _set_backlog_fsm_state(state: Dict[str, Any], *, is_complete: bool) -> str:
    next_state = _backlog_state_from_complete(is_complete)
    state["fsm_state"] = next_state
    state["fsm_state_entered_at"] = _now_iso()
    return next_state


@app.post("/api/projects/{project_id}/backlog/generate")
async def generate_project_backlog(project_id: int, req: BacklogGenerateRequest):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    context = await _hydrate_context(session_id, project_id)

    if context.state.get("fsm_state") in [OrchestratorState.SETUP_REQUIRED.value]:
         raise HTTPException(status_code=409, detail="Setup required before backlog")
         
    if context.state.get("fsm_state") not in [
        OrchestratorState.VISION_PERSISTENCE.value,
        OrchestratorState.BACKLOG_INTERVIEW.value,
        OrchestratorState.BACKLOG_REVIEW.value,
        OrchestratorState.BACKLOG_PERSISTENCE.value,
        OrchestratorState.ROADMAP_INTERVIEW.value, 
    ]:
         raise HTTPException(status_code=409, detail=f"Invalid FSM State for backlog: {context.state.get('fsm_state')}")

    attempts = _ensure_backlog_attempts(context.state)
    has_attempts = len(attempts) > 0
    user_input = (req.user_input or "").strip()
    if has_attempts and not user_input:
        raise HTTPException(
            status_code=409,
            detail="Feedback is required for Backlog refinement attempts",
        )

    backlog_result = await run_backlog_agent_from_state(
        context.state,
        project_id=project_id,
        user_input=user_input,
    )
    is_complete = bool(backlog_result.get("is_complete")) if backlog_result.get("success") else False

    attempt_count = _record_backlog_attempt(
        context.state,
        trigger="manual_refine" if has_attempts else "auto_transition",
        input_context=backlog_result.get("input_context") or {},
        output_artifact=backlog_result.get("output_artifact") or {},
        is_complete=is_complete,
        failure_meta=backlog_result,
    )
    next_state = _set_backlog_fsm_state(
        context.state,
        is_complete=is_complete,
    )

    _save_session_state(session_id, context.state)

    return {
        "status": "success",
        "data": {
            "fsm_state": next_state,
            "is_complete": is_complete,
            "backlog_run_success": bool(backlog_result.get("success")),
            "error": backlog_result.get("error"),
            "trigger": "manual_refine" if has_attempts else "auto_transition",
            "input_context": backlog_result.get("input_context"),
            "output_artifact": backlog_result.get("output_artifact"),
            "attempt_count": attempt_count,
            **_failure_meta(backlog_result, fallback_summary=backlog_result.get("error")),
        },
    }


@app.get("/api/projects/{project_id}/backlog/history")
async def get_project_backlog_history(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    attempts = state.get("backlog_attempts")
    if not isinstance(attempts, list):
        attempts = []

    return {
        "status": "success",
        "data": {
            "items": attempts,
            "count": len(attempts),
        },
    }


@app.post("/api/projects/{project_id}/backlog/save")
async def save_project_backlog(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)

    assessment = state.get("product_backlog_assessment")
    if not isinstance(assessment, dict):
        raise HTTPException(status_code=409, detail="No backlog draft available to save")

    if not bool(assessment.get("is_complete", False)):
        raise HTTPException(
            status_code=409,
            detail="Backlog cannot be saved until is_complete is true",
        )

    items = assessment.get("backlog_items")
    if not isinstance(items, list) or len(items) == 0:
        raise HTTPException(status_code=409, detail="Backlog items are empty")

    context = await _hydrate_context(session_id, project_id)
    result = await save_backlog_tool(
        SaveBacklogInput(
            product_id=project_id,
            backlog_items=items,
        ),
        context,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to save backlog"))

    context.state["fsm_state"] = OrchestratorState.BACKLOG_PERSISTENCE.value
    context.state["fsm_state_entered_at"] = _now_iso()
    context.state["backlog_saved_at"] = _now_iso()

    _save_session_state(session_id, context.state)

    return {
        "status": "success",
        "data": {
            "fsm_state": OrchestratorState.BACKLOG_PERSISTENCE.value,
            "save_result": result,
        },
    }


def _roadmap_state_from_complete(is_complete: bool) -> str:
    return (
        OrchestratorState.ROADMAP_REVIEW.value
        if is_complete
        else OrchestratorState.ROADMAP_INTERVIEW.value
    )


def _ensure_roadmap_attempts(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    attempts = state.get("roadmap_attempts")
    if not isinstance(attempts, list):
        attempts = []
    return attempts


def _record_roadmap_attempt(
    state: Dict[str, Any],
    *,
    trigger: str,
    input_context: Dict[str, Any],
    output_artifact: Dict[str, Any],
    is_complete: bool,
    failure_meta: Optional[Dict[str, Any]] = None,
) -> int:
    attempts = _ensure_roadmap_attempts(state)
    normalized_failure = _failure_meta(failure_meta)
    attempts.append(
        {
            "created_at": _now_iso(),
            "trigger": trigger,
            "input_context": input_context,
            "output_artifact": output_artifact,
            "is_complete": is_complete,
            **normalized_failure,
        }
    )
    state["roadmap_attempts"] = attempts
    state["roadmap_last_input_context"] = input_context
    state["product_roadmap_assessment"] = output_artifact
    if isinstance(output_artifact.get("roadmap_releases"), list):
        state["roadmap_releases"] = output_artifact["roadmap_releases"]
    return len(attempts)


def _set_roadmap_fsm_state(state: Dict[str, Any], *, is_complete: bool) -> str:
    current_state = _normalize_fsm_state(state.get("fsm_state"))
    if current_state in (
        OrchestratorState.ROADMAP_PERSISTENCE.value,
        OrchestratorState.STORY_INTERVIEW.value,
        OrchestratorState.STORY_REVIEW.value,
        OrchestratorState.STORY_PERSISTENCE.value,
        OrchestratorState.SPRINT_SETUP.value,
        OrchestratorState.SPRINT_DRAFT.value,
        OrchestratorState.SPRINT_PERSISTENCE.value,
        OrchestratorState.SPRINT_COMPLETE.value,
    ):
        return current_state

    new_state = _roadmap_state_from_complete(is_complete)
    state["fsm_state"] = new_state
    state["fsm_state_entered_at"] = _now_iso()
    return new_state


@app.post("/api/projects/{project_id}/roadmap/generate")
async def generate_project_roadmap(project_id: int, req: RoadmapGenerateRequest):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)

    attempts = _ensure_roadmap_attempts(state)
    has_attempts = len(attempts) > 0

    if has_attempts and not req.user_input:
        raise HTTPException(
            status_code=400,
            detail="User input is required to refine an existing roadmap.",
        )

    roadmap_result = await run_roadmap_agent_from_state(
        state,
        project_id=project_id,
        user_input=req.user_input,
    )

    is_complete = bool(roadmap_result.get("is_complete", False))
    attempt_count = _record_roadmap_attempt(
        state,
        trigger="manual_refine" if has_attempts else "auto_transition",
        input_context=roadmap_result.get("input_context") or {},
        output_artifact=roadmap_result.get("output_artifact") or {},
        is_complete=is_complete,
        failure_meta=roadmap_result,
    )
    next_state = _set_roadmap_fsm_state(
        state,
        is_complete=is_complete,
    )

    _save_session_state(session_id, state)

    return {
        "status": "success",
        "data": {
            "fsm_state": next_state,
            "is_complete": is_complete,
            "roadmap_run_success": bool(roadmap_result.get("success")),
            "error": roadmap_result.get("error"),
            "trigger": "manual_refine" if has_attempts else "auto_transition",
            "input_context": roadmap_result.get("input_context"),
            "output_artifact": roadmap_result.get("output_artifact"),
            "attempt_count": attempt_count,
            **_failure_meta(roadmap_result, fallback_summary=roadmap_result.get("error")),
        },
    }


@app.get("/api/projects/{project_id}/roadmap/history")
async def get_project_roadmap_history(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    attempts = state.get("roadmap_attempts")
    if not isinstance(attempts, list):
        attempts = []

    return {
        "status": "success",
        "data": {
            "items": attempts,
            "count": len(attempts),
        },
    }


@app.post("/api/projects/{project_id}/roadmap/save")
async def save_project_roadmap(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)

    assessment = state.get("product_roadmap_assessment")
    if not isinstance(assessment, dict):
        raise HTTPException(status_code=409, detail="No roadmap draft available to save")

    if not bool(assessment.get("is_complete", False)):
        raise HTTPException(
            status_code=409,
            detail="Roadmap cannot be saved until is_complete is true",
        )

    from orchestrator_agent.agent_tools.roadmap_builder.schemes import RoadmapBuilderOutput
    context = await _hydrate_context(session_id, project_id)
    
    try:
        roadmap_data = RoadmapBuilderOutput.model_validate(assessment)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invalid roadmap data in session: {str(e)}")
        
    result = save_roadmap_tool(
        SaveRoadmapToolInput(
            product_id=project_id,
            roadmap_data=roadmap_data,
        ),
        context,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to save roadmap"))

    state["fsm_state"] = OrchestratorState.ROADMAP_PERSISTENCE.value
    state["fsm_state_entered_at"] = _now_iso()
    state["roadmap_saved_at"] = _now_iso()

    _save_session_state(session_id, state)

    return {
        "status": "success",
        "data": {
            "fsm_state": OrchestratorState.ROADMAP_PERSISTENCE.value,
            "save_result": result,
        },
    }


# ==============================================================================
# STORY ENDPOINTS
# ==============================================================================

def _get_all_roadmap_requirements(state: Dict[str, Any]) -> List[str]:
    """Helper: extract all assigned backlog items from saved roadmap releases."""
    releases = state.get("roadmap_releases") or []
    reqs: List[str] = []
    for rel in releases:
        items = rel.get("items") or []
        reqs.extend(items)
    return reqs


def _ensure_story_attempts(state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    attempts = state.get("story_attempts")
    if not isinstance(attempts, dict):
        attempts = {}
    return attempts


def _record_story_attempt(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
    trigger: str,
    input_context: Dict[str, Any],
    output_artifact: Dict[str, Any],
    is_complete: bool,
    failure_meta: Optional[Dict[str, Any]] = None,
) -> int:
    attempts_dict = _ensure_story_attempts(state)
    if parent_requirement not in attempts_dict:
        attempts_dict[parent_requirement] = []
    
    attempts = attempts_dict[parent_requirement]
    normalized_failure = _failure_meta(failure_meta)
    attempts.append(
        {
            "created_at": _now_iso(),
            "trigger": trigger,
            "input_context": input_context,
            "output_artifact": output_artifact,
            "is_complete": is_complete,
            **normalized_failure,
        }
    )
    state["story_attempts"] = attempts_dict
    
    # Also log latest overall for the requirement
    latest_outputs = state.get("story_outputs", {})
    latest_outputs[parent_requirement] = output_artifact
    state["story_outputs"] = latest_outputs
    
    return len(attempts)


@app.get("/api/projects/{project_id}/story/pending")
async def get_project_story_pending(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    
    roadmap_releases = state.get("roadmap_releases") or []
    attempts_dict = _ensure_story_attempts(state)
    saved_reqs_dict = state.get("story_saved", {})  # track which ones successfully saved

    grouped_items = []
    total_count = 0
    saved_count = 0

    # Build structural hierarchy
    for release_index, rel in enumerate(roadmap_releases):
        reqs = rel.get("items") or []
        theme = rel.get("theme", f"Milestone Context")
        reasoning = rel.get("reasoning", "")
        
        milestone_group = {
            "group_id": f"milestone_{release_index}",
            "theme": theme,
            "reasoning": reasoning,
            "requirements": []
        }
        
        for req in reqs:
            req_attempts = attempts_dict.get(req, [])
            if saved_reqs_dict.get(req):
                status = "Saved"
                saved_count += 1
            elif len(req_attempts) > 0:
                status = "Attempted"
            else:
                status = "Pending"
                
            milestone_group["requirements"].append({
                "requirement": req,
                "status": status,
                "attempt_count": len(req_attempts)
            })
            total_count += 1
            
        grouped_items.append(milestone_group)

    return {
        "status": "success",
        "data": {
            "grouped_items": grouped_items,
            "total_count": total_count,
            "saved_count": saved_count,
        },
    }


@app.post("/api/projects/{project_id}/story/generate")
async def generate_project_story(project_id: int, parent_requirement: str, req: StoryGenerateRequest):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)

    # Validate parent_requirement exists in roadmap
    req_names = _get_all_roadmap_requirements(state)
    if parent_requirement not in req_names:
        if parent_requirement.strip() in [r.strip() for r in req_names]:
            # handle minor whitespace
            for r in req_names:
                if r.strip() == parent_requirement.strip():
                    parent_requirement = r
                    break
        else:
            raise HTTPException(status_code=400, detail=f"Requirement '{parent_requirement}' not found in saved roadmap.")

    attempts_dict = _ensure_story_attempts(state)
    req_attempts = attempts_dict.get(parent_requirement, [])
    has_attempts = len(req_attempts) > 0

    if has_attempts and not req.user_input:
        raise HTTPException(
            status_code=400,
            detail="User input is required to refine an existing story.",
        )

    story_result = await run_story_agent_from_state(
        state, 
        project_id=project_id,
        parent_requirement=parent_requirement,
        user_input=req.user_input
    )

    is_complete = bool(story_result.get("is_complete", False))
    attempt_count = _record_story_attempt(
        state,
        parent_requirement=parent_requirement,
        trigger="manual_refine" if has_attempts else "auto_transition",
        input_context=story_result.get("input_context") or {},
        output_artifact=story_result.get("output_artifact") or {},
        is_complete=is_complete,
        failure_meta=story_result,
    )

    _save_session_state(session_id, state)

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "is_complete": is_complete,
            "story_run_success": bool(story_result.get("success")),
            "error": story_result.get("error"),
            "trigger": "manual_refine" if has_attempts else "auto_transition",
            "input_context": story_result.get("input_context"),
            "output_artifact": story_result.get("output_artifact"),
            "attempt_count": attempt_count,
            **_failure_meta(story_result, fallback_summary=story_result.get("error")),
        },
    }


@app.get("/api/projects/{project_id}/story/history")
async def get_project_story_history(project_id: int, parent_requirement: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    
    attempts_dict = _ensure_story_attempts(state)
    req_attempts = attempts_dict.get(parent_requirement, [])

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "items": req_attempts,
            "count": len(req_attempts),
        },
    }


@app.post("/api/projects/{project_id}/story/save")
async def save_project_story(project_id: int, parent_requirement: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)

    outputs_dict = state.get("story_outputs", {})
    assessment = outputs_dict.get(parent_requirement)
    
    if not assessment:
        raise HTTPException(status_code=409, detail=f"No story draft available for '{parent_requirement}'")

    if not assessment.get("is_complete"):
        raise HTTPException(
            status_code=409,
            detail="Cannot persist stories because the latest output indicates it is incomplete.",
        )

    stories = assessment.get("user_stories")
    if not isinstance(stories, list) or len(stories) == 0:
        raise HTTPException(status_code=409, detail="Stories are empty")

    context = await _hydrate_context(session_id, project_id)
    result = save_stories_tool(
        SaveStoriesInput(
            product_id=project_id,
            parent_requirement=parent_requirement,
            stories=stories,
        ),
        context,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to save stories"))

    # Record that this specific requirement was saved successfully
    saved_reqs_dict = context.state.get("story_saved", {})
    saved_reqs_dict[parent_requirement] = True
    context.state["story_saved"] = saved_reqs_dict
    
    _save_session_state(session_id, context.state)

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "save_result": result,
        },
    }


@app.delete("/api/projects/{project_id}/story")
async def delete_project_story(project_id: int, parent_requirement: str):
    """
    Deletes all generated stories for a specific requirement and resets its state.
    """
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    engine = get_engine()
    with Session(engine) as session:
        # Find all stories for this requirement in this product
        stmt = select(UserStory).where(
            UserStory.product_id == project_id,
            UserStory.source_requirement == parent_requirement
        )
        stories = session.exec(stmt).all()
        
        deleted_count = 0
        for story in stories:
            # Delete sprint mappings
            sprint_mappings = session.exec(select(SprintStory).where(SprintStory.story_id == story.story_id)).all()
            for sm in sprint_mappings:
                session.delete(sm)
                
            # Delete completion logs
            logs = session.exec(select(StoryCompletionLog).where(StoryCompletionLog.story_id == story.story_id)).all()
            for log in logs:
                session.delete(log)
                
            # Delete the story (cascades to Tasks per schema)
            session.delete(story)
            deleted_count += 1
            
        session.commit()

    # Clean up session state
    session_id = str(project_id)
    state = await _ensure_session(session_id)
    state_modified = False

    # 1. Remove from saved list
    if "story_saved" in state and parent_requirement in state["story_saved"]:
        del state["story_saved"][parent_requirement]
        state_modified = True
        
    # 2. Remove latest output artifact
    if "story_outputs" in state and parent_requirement in state["story_outputs"]:
        del state["story_outputs"][parent_requirement]
        state_modified = True

    # 3. Add a soft "reset" marker to the history if there are attempts
    if "story_attempts" in state and parent_requirement in state["story_attempts"]:
        state["story_attempts"][parent_requirement].append({
            "is_complete": False,
            "trigger": "manual_refine",
            "input_context": {"system_message": "Stories deleted and state reset by user."},
            "output_artifact": None,
            "created_at": _now_iso(),
        })
        state_modified = True

    if state_modified:
        _save_session_state(session_id, state)

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "deleted_count": deleted_count,
            "message": "Stories deleted successfully"
        }
    }


@app.post("/api/projects/{project_id}/story/complete_phase")
async def complete_story_phase(project_id: int):
    """
    Called when the user has verified/saved all requirements and wants to advance
    to the Sprint phase.
    """
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    
    req_names = _get_all_roadmap_requirements(state)
    saved_reqs_dict = state.get("story_saved", {})
    
    missing = [r for r in req_names if not saved_reqs_dict.get(r)]
    
    if len(missing) > 0:
        raise HTTPException(
            status_code=409, 
            detail=f"Cannot complete phase. Missing {len(missing)} requirements."
        )

    # All pass, update FSM state to STORY_PERSISTENCE
    current_state = _normalize_fsm_state(state.get("fsm_state"))
    # Only update if we aren't already past it
    if current_state not in (
        OrchestratorState.STORY_PERSISTENCE.value,
        OrchestratorState.SPRINT_SETUP.value,
        OrchestratorState.SPRINT_DRAFT.value,
        OrchestratorState.SPRINT_PERSISTENCE.value,
        OrchestratorState.SPRINT_COMPLETE.value,
    ):
        state["fsm_state"] = OrchestratorState.STORY_PERSISTENCE.value
        state["fsm_state_entered_at"] = _now_iso()
        state["story_phase_completed_at"] = _now_iso()
        _save_session_state(session_id, state)
    
    return {
        "status": "success",
        "data": {
            "fsm_state": state.get("fsm_state")
        }
    }


if __name__ == "__main__":
    host = get_api_host()
    port = get_api_port()
    reload_enabled = get_api_reload()
    print(f"Starting AgenticFlow Dashboard on http://{host}:{port}")
    uvicorn.run("api:app", host=host, port=port, reload=reload_enabled)
