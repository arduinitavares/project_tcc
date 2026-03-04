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

from orchestrator_agent.agent_tools.product_vision_tool.tools import (
    SaveVisionInput,
    save_vision_tool,
)
from orchestrator_agent.fsm.states import OrchestratorState
from repositories.product import ProductRepository
from services.vision_runtime import run_vision_agent_from_state
from services.workflow import WorkflowService
from tools.orchestrator_tools import select_project
from tools.spec_tools import link_spec_to_product

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

product_repo = ProductRepository()
workflow_service = WorkflowService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_fsm_state(value: Optional[str]) -> str:
    """Normalize state to canonical key, fallback to SETUP_REQUIRED."""
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in VALID_FSM_STATES:
            return normalized
    return OrchestratorState.SETUP_REQUIRED.value


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
) -> int:
    attempts = _ensure_vision_attempts(state)
    attempts.append(
        {
            "created_at": _now_iso(),
            "trigger": trigger,
            "input_context": input_context,
            "output_artifact": output_artifact,
            "is_complete": is_complete,
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
                user_input="",
            )
            attempt_is_complete = bool(vision_result.get("is_complete")) if vision_result.get("success") else False
            _record_vision_attempt(
                context.state,
                trigger="auto_setup_transition",
                input_context=vision_result.get("input_context") or {},
                output_artifact=vision_result.get("output_artifact") or {},
                is_complete=attempt_is_complete,
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
            }

    if not setup_passed:
        context.state["fsm_state"] = OrchestratorState.SETUP_REQUIRED.value
        context.state["fsm_state_entered_at"] = _now_iso()
        next_state = OrchestratorState.SETUP_REQUIRED.value
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
    }


def _effective_project_state(project: Any, raw_state: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(raw_state)
    blocker = _setup_blocker(project)
    spec_path = getattr(project, "spec_file_path", None)

    if blocker:
        state["fsm_state"] = OrchestratorState.SETUP_REQUIRED.value
        state["setup_status"] = "failed"
        state["setup_error"] = blocker
    else:
        state["fsm_state"] = _normalize_fsm_state(state.get("fsm_state"))
        state.setdefault("setup_status", "passed")
        state.setdefault("setup_error", None)
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
        user_input=user_input,
    )
    is_complete = bool(vision_result.get("is_complete")) if vision_result.get("success") else False

    attempt_count = _record_vision_attempt(
        context.state,
        trigger="manual_refine",
        input_context=vision_result.get("input_context") or {},
        output_artifact=vision_result.get("output_artifact") or {},
        is_complete=is_complete,
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


if __name__ == "__main__":
    print("Starting AgenticFlow Dashboard on http://localhost:8000")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
