"""FastAPI application for AgenticFlow orchestration and workflow management.

Provides REST endpoints for project setup, vision generation, backlog management,
roadmap planning, user story creation, and sprint execution.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal, cast

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    StoryCompletionLog,
    StoryStatus,
    Task,
    TaskAcceptanceResult,
    TaskExecutionLog,
    TaskStatus,
    UserStory,
    WorkflowEvent,
    WorkflowEventType,
    ensure_business_db_ready,
    get_engine,
)
from orchestrator_agent.agent_tools.backlog_primer.tools import (
    SaveBacklogInput,
    save_backlog_tool,
)
from orchestrator_agent.agent_tools.product_vision_tool.tools import (
    SaveVisionInput,
    save_vision_tool,
)
from orchestrator_agent.agent_tools.roadmap_builder.tools import (
    SaveRoadmapToolInput,
    save_roadmap_tool,
)
from orchestrator_agent.agent_tools.sprint_planner_tool.tools import (
    SaveSprintPlanInput,
    save_sprint_plan_tool,
)
from orchestrator_agent.agent_tools.story_linkage import (
    normalize_requirement_key,
)
from orchestrator_agent.agent_tools.user_story_writer_tool.tools import (
    SaveStoriesInput,
    save_stories_tool,
)
from orchestrator_agent.fsm.states import OrchestratorState
from repositories.product import ProductRepository
from services.backlog_runtime import run_backlog_agent_from_state
from services.interview_runtime import (
    append_attempt,
    append_feedback_entry,
    hydrate_story_runtime_from_legacy,
    mark_feedback_absorbed,
    promote_reusable_draft,
    reset_subject_working_set,
    set_request_projection,
)
from services.roadmap_runtime import run_roadmap_agent_from_state
from services.sprint_input import load_sprint_candidates
from services.sprint_runtime import PUBLIC_TASK_KIND_VALUES, run_sprint_agent_from_state
from services.story_runtime import (
    run_story_agent_from_state,
    run_story_agent_request,
)
from services.vision_runtime import run_vision_agent_from_state
from services.workflow import WorkflowService
from tools.orchestrator_tools import select_project
from tools.spec_tools import (
    _compute_story_input_hash,
    _load_compiled_artifact,
    link_spec_to_product,
)
from utils.failure_artifacts import read_failure_artifact
from utils.logging_config import configure_logging
from utils.schemes import (
    SprintCloseReadiness,
    SprintCloseReadResponse,
    SprintCloseStorySummary,
    SprintCloseWriteRequest,
    StoryCloseReadResponse,
    StoryCloseWriteRequest,
    StoryTaskProgressSummary,
    TaskExecutionLogEntry,
    TaskExecutionReadResponse,
    TaskExecutionWriteRequest,
    ValidationEvidence,
)
from utils.task_metadata import hash_task_metadata, parse_task_metadata

if TYPE_CHECKING:
    from google.adk.tools import ToolContext
else:
    ToolContext = Any

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
        logger.info(
            "Migrated %s legacy sessions from ROUTING_MODE to SETUP_REQUIRED",
            migrated,
        )
    yield


app = FastAPI(title="AgenticFlow API", lifespan=lifespan)

app.mount(
    "/dashboard", StaticFiles(directory="frontend", html=True), name="frontend"
)


class CreateProjectRequest(BaseModel):
    """Request body for creating a new project."""

    name: str = Field(min_length=1)
    spec_file_path: str = Field(min_length=1)


class RetrySetupRequest(BaseModel):
    """Request body for retrying project setup after a failure."""

    spec_file_path: str = Field(min_length=1)


class VisionGenerateRequest(BaseModel):
    """Request body for generating product vision."""

    user_input: str | None = None


class BacklogGenerateRequest(BaseModel):
    """Request body for generating product backlog."""

    user_input: str | None = None


class RoadmapGenerateRequest(BaseModel):
    """Request body for generating product roadmap."""

    user_input: str | None = None


class StoryGenerateRequest(BaseModel):
    """Request body for generating user stories."""

    user_input: str | None = None


class SprintGenerateRequest(BaseModel):
    """Request body for generating sprint plans."""

    user_input: str | None = None
    team_velocity_assumption: Literal["Low", "Medium", "High"] = "Medium"
    sprint_duration_days: int = 14
    max_story_points: int | None = None
    include_task_decomposition: bool = True
    selected_story_ids: list[int] | None = None


class SprintSaveRequest(BaseModel):
    """Request body for saving sprint details after execution."""

    team_name: str = Field(min_length=1)
    sprint_start_date: str = Field(min_length=1)


WORKFLOW_STEPS: list[dict[str, Any]] = [
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
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_fsm_state(value: str | None) -> str:
    """Normalize state to canonical key, fallback to SETUP_REQUIRED."""
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in VALID_FSM_STATES:
            return normalized
    return OrchestratorState.SETUP_REQUIRED.value


def _normalize_shell_fsm_state(value: str | None) -> str:
    """Normalize shell-visible FSM state while collapsing legacy terminal sprint state."""
    state = _normalize_fsm_state(value)
    if state == OrchestratorState.SPRINT_COMPLETE.value:
        return OrchestratorState.SPRINT_PERSISTENCE.value
    return state


def _failure_meta(
    source: dict[str, Any] | None,
    *,
    fallback_summary: str | None = None,
) -> dict[str, Any]:
    payload = source or {}
    return {
        "failure_artifact_id": payload.get("failure_artifact_id"),
        "failure_stage": payload.get("failure_stage"),
        "failure_summary": payload.get("failure_summary") or fallback_summary,
        "raw_output_preview": payload.get("raw_output_preview"),
        "has_full_artifact": bool(payload.get("has_full_artifact", False)),
    }


def _normalize_sprint_validation_errors(validation_errors: Any) -> list[str]:
    if not isinstance(validation_errors, list):
        return []

    hints: list[str] = []
    allowed_task_kinds = ", ".join(PUBLIC_TASK_KIND_VALUES)
    for error in validation_errors:
        hint: str | None = None
        if isinstance(error, str):
            trimmed = error.strip()
            if not trimmed:
                hint = None
            else:
                described_task_kind = re.match(
                    r"Task '(?P<description>[^']+)' has invalid task_kind\.",
                    trimmed,
                )
                unsupported_task_kind = re.match(
                    r"Unsupported task_kind '(?P<value>[^']+)'\.",
                    trimmed,
                )
                if described_task_kind and "other" in trimmed:
                    hint = (
                        f"Task '{described_task_kind.group('description')}' has "
                        f"invalid task_kind. Use one of: {allowed_task_kinds}."
                    )
                elif unsupported_task_kind:
                    hint = (
                        f"Unsupported task_kind "
                        f"'{unsupported_task_kind.group('value').strip()}'. "
                        f"Use one of: {allowed_task_kinds}."
                    )
                elif "task_kind" in trimmed and "other" in trimmed:
                    hint = f"Task has invalid task_kind. Use one of: {allowed_task_kinds}."
                else:
                    hint = trimmed
        elif isinstance(error, dict):
            loc = error.get("loc")
            if isinstance(loc, (list, tuple)) and loc and loc[-1] == "task_kind":
                input_value = error.get("input")
                if isinstance(input_value, str) and input_value.strip():
                    hint = (
                        f"Unsupported task_kind '{input_value.strip()}'. "
                        f"Use one of: {allowed_task_kinds}."
                    )
                else:
                    hint = f"Task has invalid task_kind. Use one of: {allowed_task_kinds}."
            else:
                msg = error.get("msg")
                if isinstance(msg, str):
                    trimmed = msg.strip()
                    hint = trimmed or None
        if hint and hint not in hints:
            hints.append(hint)
    return hints


def _normalize_sprint_output_artifact(
    output_artifact: dict[str, Any] | None,
) -> dict[str, Any]:
    artifact = dict(output_artifact or {})
    if "validation_errors" not in artifact and artifact.get("error") != "SPRINT_GENERATION_FAILED":
        return artifact
    artifact["validation_errors"] = _normalize_sprint_validation_errors(
        artifact.get("validation_errors")
    )
    return artifact


def _normalize_sprint_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(attempt)
    output_artifact = normalized.get("output_artifact")
    if isinstance(output_artifact, dict):
        normalized["output_artifact"] = _normalize_sprint_output_artifact(output_artifact)
    return normalized


def _set_setup_failure_meta(
    state: dict[str, Any],
    source: dict[str, Any] | None,
    *,
    error_message: str | None,
) -> dict[str, Any]:
    metadata = _failure_meta(source, fallback_summary=error_message)
    state["setup_failure_artifact_id"] = metadata["failure_artifact_id"]
    state["setup_failure_stage"] = metadata["failure_stage"]
    state["setup_failure_summary"] = metadata["failure_summary"]
    state["setup_raw_output_preview"] = metadata["raw_output_preview"]
    state["setup_has_full_artifact"] = metadata["has_full_artifact"]
    return metadata


def _clear_setup_failure_meta(state: dict[str, Any]) -> None:
    state["setup_failure_artifact_id"] = None
    state["setup_failure_stage"] = None
    state["setup_failure_summary"] = None
    state["setup_raw_output_preview"] = None
    state["setup_has_full_artifact"] = False


def _setup_blocker(product: Any) -> str | None:
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


async def _ensure_session(session_id: str) -> dict[str, Any]:
    state = workflow_service.get_session_status(session_id) or {}
    if not state.get("fsm_state"):
        await workflow_service.initialize_session(session_id=session_id)
        state = workflow_service.get_session_status(session_id) or {}
    return state


def _build_tool_context(
    context: SimpleNamespace,
) -> ToolContext:
    # API flows use a lightweight state container outside the ADK runtime.
    return cast(ToolContext, context)


async def _hydrate_context(
    session_id: str, project_id: int
) -> SimpleNamespace:
    state = await _ensure_session(session_id)
    context = SimpleNamespace(state=dict(state), session_id=session_id)
    select_project(project_id, _build_tool_context(context))
    return context


def _save_session_state(session_id: str, state: dict[str, Any]) -> None:
    workflow_service.update_session_status(session_id, state)


def _serialize_sprint_task(task: Task) -> dict[str, Any]:
    meta = parse_task_metadata(task.metadata_json)
    return {
        "id": task.task_id,
        "description": task.description,
        "status": task.status.value
        if hasattr(task.status, "value")
        else task.status,
        "task_kind": meta.task_kind,
        "artifact_targets": meta.artifact_targets,
        "workstream_tags": meta.workstream_tags,
        "checklist_items": meta.checklist_items,
        "is_executable": bool(meta.checklist_items),
    }


def _build_story_task_plan(story: UserStory) -> list[dict[str, Any]]:
    return sorted(
        [_serialize_sprint_task(task) for task in story.tasks],
        key=lambda item: (item["description"].lower(), item["id"]),
    )


def _story_task_progress(tasks: list[Task]) -> tuple[int, int, int, bool]:
    actionable_tasks = [
        task
        for task in tasks
        if bool(parse_task_metadata(task.metadata_json).checklist_items)
    ]
    total_tasks = len(actionable_tasks)
    done_tasks = sum(
        1 for task in actionable_tasks if task.status == TaskStatus.DONE
    )
    cancelled_tasks = sum(
        1 for task in actionable_tasks if task.status == TaskStatus.CANCELLED
    )
    all_actionable_tasks_done = (
        total_tasks > 0 and (done_tasks + cancelled_tasks) == total_tasks
    )
    return total_tasks, done_tasks, cancelled_tasks, all_actionable_tasks_done


def _build_sprint_close_readiness(
    stories: list[UserStory],
) -> SprintCloseReadiness:
    summaries: list[SprintCloseStorySummary] = []
    completed_story_count = 0
    unfinished_story_ids: list[int] = []

    for story in stories:
        total_tasks, done_tasks, cancelled_tasks, _all_actionable_done = (
            _story_task_progress(story.tasks)
        )
        completion_state = (
            "completed"
            if story.status in (StoryStatus.DONE, StoryStatus.ACCEPTED)
            else "unfinished"
        )
        if completion_state == "completed":
            completed_story_count += 1
        elif story.story_id is not None:
            unfinished_story_ids.append(int(story.story_id))

        summaries.append(
            SprintCloseStorySummary(
                story_id=int(story.story_id),
                story_title=story.title,
                story_status=story.status.value,
                total_tasks=total_tasks,
                done_tasks=done_tasks,
                cancelled_tasks=cancelled_tasks,
                completion_state=completion_state,
            )
        )

    return SprintCloseReadiness(
        completed_story_count=completed_story_count,
        open_story_count=len(summaries) - completed_story_count,
        unfinished_story_ids=unfinished_story_ids,
        stories=summaries,
    )


def _serialize_sprint_story(story: UserStory) -> dict[str, Any]:
    tasks = sorted(
        [_serialize_sprint_task(task) for task in story.tasks],
        key=lambda t: t["description"].lower(),
    )
    return {
        "story_id": story.story_id,
        "story_title": story.title,
        "status": story.status.value
        if hasattr(story.status, "value")
        else story.status,
        "story_points": story.story_points,
        "persona": story.persona,
        "tasks": tasks,
    }


def _history_fidelity(sprint: Sprint) -> str:
    return "snapshotted" if bool(sprint.close_snapshot_json) else "derived"


def _load_sprint_close_snapshot(sprint: Sprint) -> dict[str, Any] | None:
    if not sprint.close_snapshot_json:
        return None
    try:
        return json.loads(sprint.close_snapshot_json)
    except (TypeError, ValueError):
        logger.warning(
            "Failed to parse sprint close snapshot for sprint %s",
            sprint.sprint_id,
        )
        return None


def _build_sprint_runtime_summary(sprints: list[Sprint]) -> dict[str, Any]:
    active = next(
        (sprint for sprint in sprints if sprint.status == SprintStatus.ACTIVE),
        None,
    )
    planned = next(
        (
            sprint
            for sprint in sprints
            if sprint.status == SprintStatus.PLANNED
        ),
        None,
    )
    completed = sorted(
        [
            sprint
            for sprint in sprints
            if sprint.status == SprintStatus.COMPLETED
        ],
        key=lambda sprint: (
            sprint.completed_at or sprint.updated_at or sprint.created_at
        ),
        reverse=True,
    )
    return {
        "active_sprint_id": active.sprint_id if active else None,
        "planned_sprint_id": planned.sprint_id if planned else None,
        "latest_completed_sprint_id": completed[0].sprint_id
        if completed
        else None,
        "can_create_next_sprint": planned is None,
        "create_next_sprint_disabled_reason": (
            None
            if planned is None
            else "A planned sprint already exists. Modify it instead of creating another."
        ),
    }


def _allowed_actions_for_sprint(
    sprint: Sprint,
    *,
    runtime_summary: dict[str, Any],
) -> dict[str, Any]:
    is_planned = sprint.status == SprintStatus.PLANNED
    is_active = sprint.status == SprintStatus.ACTIVE
    can_start = bool(
        is_planned and runtime_summary.get("active_sprint_id") is None
    )
    can_close = bool(is_active)
    can_modify_planned = bool(is_planned)
    return {
        "can_start": can_start,
        "start_disabled_reason": (
            None
            if can_start
            else "Only planned sprints without another active sprint can be started."
        ),
        "can_close": can_close,
        "close_disabled_reason": (
            None if can_close else "Only active sprints can be closed."
        ),
        "can_modify_planned": can_modify_planned,
        "modify_disabled_reason": (
            None
            if can_modify_planned
            else "Only planned sprints can be edited in place."
        ),
    }


def _serialize_sprint_list_item(
    sprint: Sprint,
    *,
    runtime_summary: dict[str, Any],
) -> dict[str, Any]:
    stories = sorted(
        sprint.stories,
        key=lambda story: (
            story.rank or "",
            story.story_id or 0,
        ),
    )
    return {
        "id": sprint.sprint_id,
        "goal": sprint.goal,
        "status": sprint.status.value,
        "created_at": _serialize_temporal(sprint.created_at),
        "updated_at": _serialize_temporal(sprint.updated_at),
        "started_at": _serialize_temporal(sprint.started_at),
        "completed_at": _serialize_temporal(sprint.completed_at),
        "start_date": _serialize_temporal(sprint.start_date),
        "end_date": _serialize_temporal(sprint.end_date),
        "team_id": sprint.team_id,
        "team_name": sprint.team.name if sprint.team else None,
        "story_count": len(stories),
        "history_fidelity": _history_fidelity(sprint),
        "allowed_actions": _allowed_actions_for_sprint(
            sprint,
            runtime_summary=runtime_summary,
        ),
    }


def _serialize_sprint_detail(
    sprint: Sprint,
    *,
    runtime_summary: dict[str, Any],
) -> dict[str, Any]:
    stories = sorted(
        sprint.stories,
        key=lambda story: (
            story.rank or "",
            story.story_id or 0,
        ),
    )
    payload = _serialize_sprint_list_item(
        sprint, runtime_summary=runtime_summary
    )
    payload["selected_stories"] = [
        _serialize_sprint_story(story) for story in stories
    ]
    payload["close_snapshot"] = _load_sprint_close_snapshot(sprint)
    return payload


def _saved_sprint_query():
    return select(Sprint).options(
        selectinload(Sprint.team),
        selectinload(Sprint.stories).selectinload(UserStory.tasks),
    )


def _list_saved_sprints(project_id: int) -> dict[str, Any]:
    with Session(get_engine()) as session:
        sprints = session.exec(
            _saved_sprint_query()
            .where(Sprint.product_id == project_id)
            .order_by(Sprint.created_at.desc())
        ).all()
        runtime_summary = _build_sprint_runtime_summary(sprints)
        return {
            "items": [
                _serialize_sprint_list_item(
                    sprint,
                    runtime_summary=runtime_summary,
                )
                for sprint in sprints
            ],
            "runtime_summary": runtime_summary,
        }


def _get_saved_sprint(
    session: Session, project_id: int, sprint_id: int
) -> Sprint | None:
    return session.exec(
        _saved_sprint_query().where(
            Sprint.product_id == project_id,
            Sprint.sprint_id == sprint_id,
        )
    ).first()


def _serialize_temporal(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _hash_payload(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _truncate_text(text: str, max_length: int) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."


def _build_task_label(description: str) -> str:
    normalized = _truncate_text(description or "Task", 80)
    return normalized or "Task"


def _extract_vision_excerpt(vision: str | None) -> str | None:
    if not vision or not vision.strip():
        return None
    for paragraph in re.split(r"\n\s*\n", vision.strip()):
        normalized = " ".join(paragraph.split())
        if normalized:
            return _truncate_text(normalized, 500)
    return None


def _normalize_acceptance_criteria(text: str | None) -> list[str]:
    if not text or not text.strip():
        return []

    items: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        normalized = re.sub(r"^\s*(?:[-*•]+|\d+[.)])\s*", "", stripped).strip()
        if normalized:
            items.append(normalized)

    if items:
        return items

    collapsed = " ".join(text.split())
    return [collapsed] if collapsed else []


def _load_validation_evidence(
    raw_value: str | None,
) -> ValidationEvidence | None:
    if not raw_value:
        return None
    try:
        return ValidationEvidence.model_validate_json(raw_value)
    except Exception as exc:  # pragma: no cover - legacy malformed evidence
        logger.warning("Failed to parse validation evidence: %s", exc)
        return None


def _load_pinned_authority(
    session: Session,
    accepted_spec_version_id: int | None,
) -> CompiledSpecAuthority | None:
    if accepted_spec_version_id is None:
        return None
    return session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == accepted_spec_version_id
        )
    ).first()


def _build_packet_findings(
    evidence: ValidationEvidence | None,
) -> list[dict[str, str | None]]:
    if not evidence:
        return []

    findings: list[dict[str, str | None]] = []
    for failure in evidence.failures:
        findings.append(
            {
                "severity": "failure",
                "source": "validation_failure",
                "code": failure.rule,
                "message": failure.message,
                "invariant_id": None,
                "rule": failure.rule,
                "capability": None,
            }
        )
    for warning in evidence.warnings:
        findings.append(
            {
                "severity": "warning",
                "source": "validation_warning",
                "code": warning,
                "message": warning,
                "invariant_id": None,
                "rule": None,
                "capability": None,
            }
        )
    for finding in evidence.alignment_warnings:
        findings.append(
            {
                "severity": finding.severity,
                "source": "alignment_warning",
                "code": finding.code,
                "message": finding.message,
                "invariant_id": finding.invariant,
                "rule": None,
                "capability": finding.capability,
            }
        )
    for finding in evidence.alignment_failures:
        findings.append(
            {
                "severity": finding.severity,
                "source": "alignment_failure",
                "code": finding.code,
                "message": finding.message,
                "invariant_id": finding.invariant,
                "rule": None,
                "capability": finding.capability,
            }
        )
    return findings


def _build_story_compliance_boundaries(
    authority: CompiledSpecAuthority | None,
    evidence: ValidationEvidence | None,
) -> list[dict[str, Any]]:
    if not authority or not evidence:
        return []

    artifact = _load_compiled_artifact(authority)
    if not artifact:
        return []

    referenced_ids = set()
    if (
        hasattr(evidence, "finding_invariant_ids")
        and evidence.finding_invariant_ids
    ):
        referenced_ids.update(evidence.finding_invariant_ids)

    if not referenced_ids:
        return []

    source_map: dict[str, Any] = {}
    for entry in artifact.source_map:
        source_map.setdefault(entry.invariant_id, entry)

    relevant: list[dict[str, Any]] = []
    for invariant in artifact.invariants:
        if invariant.id not in referenced_ids:
            continue

        source_entry = source_map.get(invariant.id)
        parameters = invariant.parameters.model_dump(mode="json")
        relevant.append(
            {
                "invariant_id": invariant.id,
                "type": invariant.type.value,
                "parameters": parameters,
                "source_excerpt": source_entry.excerpt
                if source_entry
                else None,
                "source_location": source_entry.location
                if source_entry
                else None,
            }
        )
    return relevant


def _build_task_hard_constraints(
    authority: CompiledSpecAuthority | None,
    *,
    task_metadata,
) -> list[dict[str, Any]]:
    if not authority or not task_metadata.relevant_invariant_ids:
        return []

    artifact = _load_compiled_artifact(authority)
    if not artifact:
        return []

    source_map: dict[str, Any] = {}
    for entry in artifact.source_map:
        source_map.setdefault(entry.invariant_id, entry)

    invariant_map = {
        invariant.id: invariant for invariant in artifact.invariants
    }
    constraints: list[dict[str, Any]] = []
    for invariant_id in task_metadata.relevant_invariant_ids:
        invariant = invariant_map.get(invariant_id)
        if invariant is None:
            logger.warning(
                "Ignoring unknown invariant id '%s' while building task packet hard constraints.",
                invariant_id,
            )
            continue
        source_entry = source_map.get(invariant.id)
        constraints.append(
            {
                "invariant_id": invariant.id,
                "type": invariant.type.value,
                "parameters": invariant.parameters.model_dump(mode="json"),
                "source_excerpt": source_entry.excerpt
                if source_entry
                else None,
                "source_location": source_entry.location
                if source_entry
                else None,
            }
        )
    return constraints


def _load_packet_story_context(
    session: Session,
    *,
    project_id: int,
    sprint_id: int,
    story_id: int | None = None,
    task_id: int | None = None,
) -> SimpleNamespace | None:
    task = None
    if task_id is not None:
        task = session.exec(
            select(Task)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.story).selectinload(UserStory.product),
                selectinload(Task.story).selectinload(UserStory.tasks),
            )
            .where(Task.task_id == task_id)
        ).first()
        if not task or not task.story or task.story.product_id != project_id:
            return None
        story = task.story
    else:
        story = session.exec(
            select(UserStory)
            .options(
                selectinload(UserStory.product),
                selectinload(UserStory.tasks),
            )
            .where(UserStory.story_id == story_id)
        ).first()
        if not story or story.product_id != project_id:
            return None

    sprint = session.exec(
        select(Sprint)
        .options(selectinload(Sprint.team))
        .where(
            Sprint.product_id == project_id,
            Sprint.sprint_id == sprint_id,
        )
    ).first()
    if not sprint:
        return None

    sprint_story = session.exec(
        select(SprintStory).where(
            SprintStory.sprint_id == sprint_id,
            SprintStory.story_id == story.story_id,
        )
    ).first()
    if not sprint_story:
        return None

    product = story.product
    if not product or product.product_id != project_id:
        product = session.get(Product, project_id)
        if not product:
            return None

    evidence = _load_validation_evidence(story.validation_evidence)
    current_story_input_hash = _compute_story_input_hash(story)
    validation_input_hash = evidence.input_hash if evidence else None
    input_hash_matches = (
        current_story_input_hash == validation_input_hash
        if validation_input_hash is not None
        else None
    )
    validation_freshness = (
        "missing"
        if evidence is None
        else "current"
        if input_hash_matches
        else "stale"
    )

    authority = _load_pinned_authority(session, story.accepted_spec_version_id)
    compiled_artifact = (
        _load_compiled_artifact(authority) if authority else None
    )
    spec_binding_status = (
        "pinned" if story.accepted_spec_version_id is not None else "unpinned"
    )
    authority_status = (
        "available" if compiled_artifact is not None else "missing"
    )

    task_metadata = None
    if task is not None:
        task_metadata = parse_task_metadata(
            task.metadata_json,
            logger=logger,
            task_id=task.task_id,
        )

    return SimpleNamespace(
        task=task,
        task_metadata=task_metadata,
        story=story,
        sprint=sprint,
        sprint_story=sprint_story,
        product=product,
        evidence=evidence,
        current_story_input_hash=current_story_input_hash,
        validation_input_hash=validation_input_hash,
        input_hash_matches=input_hash_matches,
        validation_freshness=validation_freshness,
        authority=authority,
        spec_binding_status=spec_binding_status,
        authority_status=authority_status,
    )


def _build_story_packet(
    session: Session,
    *,
    project_id: int,
    sprint_id: int,
    story_id: int,
) -> dict[str, Any] | None:
    context = _load_packet_story_context(
        session,
        project_id=project_id,
        sprint_id=sprint_id,
        story_id=story_id,
    )
    if not context:
        return None

    story = context.story
    sprint = context.sprint
    sprint_story = context.sprint_story
    product = context.product
    evidence = context.evidence
    task_plan_tasks = _build_story_task_plan(story)

    source_snapshot = {
        "product_id": project_id,
        "sprint_id": sprint_id,
        "story_id": story.story_id,
        "product_updated_at": _serialize_temporal(product.updated_at),
        "sprint_updated_at": _serialize_temporal(sprint.updated_at),
        "sprint_story_added_at": _serialize_temporal(sprint_story.added_at),
        "story_updated_at": _serialize_temporal(story.updated_at),
        "story_ac_updated_at": _serialize_temporal(story.ac_updated_at),
        "accepted_spec_version_id": story.accepted_spec_version_id,
        "validation_validated_at": _serialize_temporal(
            evidence.validated_at if evidence else None
        ),
        "validation_input_hash": context.validation_input_hash,
        "compiled_authority_compiled_at": _serialize_temporal(
            context.authority.compiled_at if context.authority else None
        ),
        "task_plan_hash": _hash_payload(task_plan_tasks),
    }

    packet_id_hash = hashlib.sha256(
        f"story_packet.v1:{sprint_id}:{story_id}".encode()
    ).hexdigest()[:16]

    return {
        "schema_version": "story_packet.v1",
        "metadata": {
            "packet_id": f"sp_{packet_id_hash}",
            "generated_at": _serialize_temporal(datetime.now(UTC)),
            "generator_version": "v1",
            "source_fingerprint": _hash_payload(source_snapshot),
        },
        "source_snapshot": source_snapshot,
        "story": {
            "story_id": story.story_id,
            "title": story.title,
            "persona": story.persona,
            "story_description": story.story_description,
            "status": story.status.value,
            "story_points": story.story_points,
            "rank": story.rank,
            "source_requirement": story.source_requirement,
        },
        "task_plan": {"tasks": task_plan_tasks},
        "context": {
            "sprint": {
                "sprint_id": sprint.sprint_id,
                "goal": sprint.goal,
                "status": sprint.status.value,
                "started_at": _serialize_temporal(sprint.started_at),
                "start_date": _serialize_temporal(sprint.start_date),
                "end_date": _serialize_temporal(sprint.end_date),
                "team_id": sprint.team_id,
                "team_name": sprint.team.name if sprint.team else None,
            },
            "product": {
                "product_id": product.product_id,
                "name": product.name,
                "vision_excerpt": _extract_vision_excerpt(product.vision),
            },
        },
        "constraints": {
            "story_acceptance_criteria_text": story.acceptance_criteria,
            "story_acceptance_criteria_items": _normalize_acceptance_criteria(
                story.acceptance_criteria
            ),
            "spec_binding": {
                "mode": "pinned_story_authority",
                "binding_status": context.spec_binding_status,
                "spec_version_id": story.accepted_spec_version_id,
                "authority_artifact_status": context.authority_status,
            },
            "validation": {
                "present": evidence is not None,
                "passed": evidence.passed if evidence else None,
                "freshness_status": context.validation_freshness,
                "validated_at": _serialize_temporal(
                    evidence.validated_at if evidence else None
                ),
                "validator_version": evidence.validator_version
                if evidence
                else None,
                "current_story_input_hash": context.current_story_input_hash,
                "validation_input_hash": context.validation_input_hash,
                "input_hash_matches": context.input_hash_matches,
                "rules_checked": list(evidence.rules_checked)
                if evidence
                else [],
            },
            "story_compliance_boundaries": _build_story_compliance_boundaries(
                context.authority,
                evidence,
            ),
            "findings": _build_packet_findings(evidence),
        },
    }


def _build_task_packet(
    session: Session,
    *,
    project_id: int,
    sprint_id: int,
    task_id: int,
) -> dict[str, Any] | None:
    context = _load_packet_story_context(
        session,
        project_id=project_id,
        sprint_id=sprint_id,
        task_id=task_id,
    )
    if not context or context.task is None or context.task_metadata is None:
        return None

    task = context.task
    task_metadata = context.task_metadata
    story = context.story
    sprint = context.sprint
    sprint_story = context.sprint_story
    product = context.product
    evidence = context.evidence

    source_snapshot = {
        "product_id": project_id,
        "sprint_id": sprint_id,
        "story_id": story.story_id,
        "task_id": task_id,
        "product_updated_at": _serialize_temporal(product.updated_at),
        "sprint_updated_at": _serialize_temporal(sprint.updated_at),
        "sprint_story_added_at": _serialize_temporal(sprint_story.added_at),
        "story_updated_at": _serialize_temporal(story.updated_at),
        "story_ac_updated_at": _serialize_temporal(story.ac_updated_at),
        "task_updated_at": _serialize_temporal(task.updated_at),
        "task_metadata_hash": hash_task_metadata(task_metadata),
        "accepted_spec_version_id": story.accepted_spec_version_id,
        "validation_validated_at": _serialize_temporal(
            evidence.validated_at if evidence else None
        ),
        "validation_input_hash": context.validation_input_hash,
        "compiled_authority_compiled_at": _serialize_temporal(
            context.authority.compiled_at if context.authority else None
        ),
    }

    packet_id_hash = hashlib.sha256(
        f"task_packet.v2:{sprint_id}:{task_id}".encode()
    ).hexdigest()[:16]

    return {
        "schema_version": "task_packet.v2",
        "metadata": {
            "packet_id": f"tp_{packet_id_hash}",
            "generated_at": _serialize_temporal(datetime.now(UTC)),
            "generator_version": "v2",
            "source_fingerprint": _hash_payload(source_snapshot),
        },
        "source_snapshot": source_snapshot,
        "task": {
            "task_id": task.task_id,
            "label": _build_task_label(task.description),
            "description": task.description,
            "status": task.status.value,
            "assignee_member_id": task.assigned_to_member_id,
            "assignee_name": task.assignee.name if task.assignee else None,
            "task_kind": task_metadata.task_kind,
            "artifact_targets": list(task_metadata.artifact_targets),
            "workstream_tags": list(task_metadata.workstream_tags),
            "checklist_items": list(task_metadata.checklist_items),
            "is_executable": bool(task_metadata.checklist_items),
        },
        "context": {
            "story": {
                "story_id": story.story_id,
                "title": story.title,
                "persona": story.persona,
                "story_description": story.story_description,
                "status": story.status.value,
                "story_points": story.story_points,
                "rank": story.rank,
                "source_requirement": story.source_requirement,
            },
            "sprint": {
                "sprint_id": sprint.sprint_id,
                "goal": sprint.goal,
                "status": sprint.status.value,
                "started_at": _serialize_temporal(sprint.started_at),
                "start_date": _serialize_temporal(sprint.start_date),
                "end_date": _serialize_temporal(sprint.end_date),
                "team_id": sprint.team_id,
                "team_name": sprint.team.name if sprint.team else None,
            },
            "product": {
                "product_id": product.product_id,
                "name": product.name,
                "vision_excerpt": _extract_vision_excerpt(product.vision),
            },
        },
        "constraints": {
            "spec_binding": {
                "mode": "pinned_story_authority",
                "binding_status": context.spec_binding_status,
                "spec_version_id": story.accepted_spec_version_id,
                "authority_artifact_status": context.authority_status,
            },
            "validation": {
                "present": evidence is not None,
                "passed": evidence.passed if evidence else None,
                "freshness_status": context.validation_freshness,
                "validated_at": _serialize_temporal(
                    evidence.validated_at if evidence else None
                ),
                "validator_version": evidence.validator_version
                if evidence
                else None,
                "current_story_input_hash": context.current_story_input_hash,
                "validation_input_hash": context.validation_input_hash,
                "input_hash_matches": context.input_hash_matches,
                "rules_checked": list(evidence.rules_checked)
                if evidence
                else [],
            },
            "task_hard_constraints": _build_task_hard_constraints(
                context.authority,
                task_metadata=task_metadata,
            ),
            "story_compliance_boundaries": _build_story_compliance_boundaries(
                context.authority,
                evidence,
            ),
            "findings": _build_packet_findings(evidence),
        },
    }


def _vision_state_from_complete(is_complete: bool) -> str:
    return (
        OrchestratorState.VISION_REVIEW.value
        if is_complete
        else OrchestratorState.VISION_INTERVIEW.value
    )


def _ensure_vision_attempts(state: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = state.get("vision_attempts")
    if not isinstance(attempts, list):
        attempts = []
    return attempts


def _record_vision_attempt(
    state: dict[str, Any],
    *,
    trigger: str,
    input_context: dict[str, Any],
    output_artifact: dict[str, Any],
    is_complete: bool,
    failure_meta: dict[str, Any] | None = None,
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


def _set_vision_fsm_state(state: dict[str, Any], *, is_complete: bool) -> str:
    next_state = _vision_state_from_complete(is_complete)
    state["fsm_state"] = next_state
    state["fsm_state_entered_at"] = _now_iso()
    return next_state


async def _run_setup(
    session_id: str, project_id: int, spec_file_path: str
) -> dict[str, Any]:
    context = await _hydrate_context(session_id, project_id)

    result = link_spec_to_product(
        {
            "product_id": project_id,
            "spec_path": spec_file_path,
        },
        tool_context=_build_tool_context(context),
    )

    # Rehydrate after setup attempt to refresh active project + compiled authority cache.
    select_project(project_id, _build_tool_context(context))

    setup_passed = bool(
        result.get("success") and result.get("compile_success")
    )
    error_message = None
    next_state = OrchestratorState.SETUP_REQUIRED.value
    vision_auto_run: dict[str, Any] = {
        "attempted": False,
        "success": False,
        "is_complete": None,
        "error": None,
        "trigger": "auto_setup_transition",
        **_failure_meta(None),
    }

    if not setup_passed:
        error_message = (
            result.get("compile_error")
            or result.get("error")
            or "Setup failed"
        )
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
            attempt_is_complete = (
                bool(vision_result.get("is_complete"))
                if vision_result.get("success")
                else False
            )
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
                "is_complete": vision_result.get("is_complete")
                if vision_result.get("success")
                else None,
                "error": vision_result.get("error"),
                "trigger": "auto_setup_transition",
                **_failure_meta(
                    vision_result, fallback_summary=vision_result.get("error")
                ),
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


def _effective_project_state(
    project: Any, raw_state: dict[str, Any]
) -> dict[str, Any]:
    state = dict(raw_state)
    blocker = _setup_blocker(project)
    spec_path = getattr(project, "spec_file_path", None)

    if blocker:
        state["fsm_state"] = OrchestratorState.SETUP_REQUIRED.value
        state["setup_status"] = "failed"
        existing_error = state.get("setup_error")
        state["setup_error"] = existing_error or blocker
    else:
        state["fsm_state"] = _normalize_shell_fsm_state(state.get("fsm_state"))
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
                    "summary": product.description
                    or "No description provided",
                    "fsm_state": effective_state.get(
                        "fsm_state", OrchestratorState.SETUP_REQUIRED.value
                    ),
                    "setup_status": effective_state.get(
                        "setup_status", "failed"
                    ),
                    "setup_error": effective_state.get("setup_error"),
                    "setup_failure_artifact_id": effective_state.get(
                        "setup_failure_artifact_id"
                    ),
                    "setup_failure_stage": effective_state.get(
                        "setup_failure_stage"
                    ),
                    "setup_failure_summary": effective_state.get(
                        "setup_failure_summary"
                    ),
                    "setup_raw_output_preview": effective_state.get(
                        "setup_raw_output_preview"
                    ),
                    "setup_has_full_artifact": effective_state.get(
                        "setup_has_full_artifact", False
                    ),
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

        setup_result = await _run_setup(
            session_id, int(new_product.product_id), req.spec_file_path
        )

        return {
            "status": "success",
            "data": {
                "id": new_product.product_id,
                "name": new_product.name,
                "setup_status": "passed"
                if setup_result["passed"]
                else "failed",
                "setup_error": setup_result["error"],
                "fsm_state": setup_result["fsm_state"],
                "vision_auto_run": setup_result.get("vision_auto_run"),
                **_failure_meta(
                    setup_result, fallback_summary=setup_result["error"]
                ),
            },
        }
    except Exception as exc:
        logger.error("Error creating project: %s", exc)
        raise HTTPException(
            status_code=500, detail="Failed to create project"
        ) from exc


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        # Delete volatile session state
        workflow_service.delete_session(str(project_id))
        # Cascade delete products and all artifacts
        success = product_repo.delete_project(project_id)
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to delete project due to database error.",
            )
        return {
            "status": "success",
            "data": {"message": f"Project {project_id} deleted."},
        }
    except Exception as exc:
        logger.error("Error deleting project %d: %s", project_id, exc)
        raise HTTPException(
            status_code=500, detail="Failed to delete project"
        ) from exc


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
            **_failure_meta(
                setup_result, fallback_summary=setup_result["error"]
            ),
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
        raise HTTPException(
            status_code=404, detail="Failure artifact not found"
        )

    if artifact.get("project_id") != project_id:
        raise HTTPException(
            status_code=404, detail="Failure artifact not found for project"
        )

    return {"status": "success", "data": artifact}


@app.post("/api/projects/{project_id}/vision/generate")
async def generate_project_vision(project_id: int, req: VisionGenerateRequest):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    blocker = _setup_blocker(product)
    if blocker:
        raise HTTPException(
            status_code=409, detail=f"Setup required: {blocker}"
        )

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
    is_complete = (
        bool(vision_result.get("is_complete"))
        if vision_result.get("success")
        else False
    )

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
            **_failure_meta(
                vision_result, fallback_summary=vision_result.get("error")
            ),
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
        raise HTTPException(
            status_code=409, detail=f"Setup required: {blocker}"
        )

    session_id = str(project_id)
    state = await _ensure_session(session_id)

    assessment = state.get("product_vision_assessment")
    if not isinstance(assessment, dict):
        raise HTTPException(
            status_code=409, detail="No vision draft available to save"
        )

    if not bool(assessment.get("is_complete", False)):
        raise HTTPException(
            status_code=409,
            detail="Vision cannot be saved until is_complete is true",
        )

    statement = assessment.get("product_vision_statement")
    if not isinstance(statement, str) or not statement.strip():
        raise HTTPException(
            status_code=409, detail="Vision statement is empty"
        )

    context = await _hydrate_context(session_id, project_id)
    result = save_vision_tool(
        SaveVisionInput(
            product_id=project_id,
            project_name=product.name,
            product_vision_statement=statement,
        ),
        _build_tool_context(context),
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save vision"),
        )

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


def _ensure_backlog_attempts(state: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = state.get("backlog_attempts")
    if not isinstance(attempts, list):
        attempts = []
    return attempts


def _record_backlog_attempt(
    state: dict[str, Any],
    *,
    trigger: str,
    input_context: dict[str, Any],
    output_artifact: dict[str, Any],
    is_complete: bool,
    failure_meta: dict[str, Any] | None = None,
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


def _set_backlog_fsm_state(state: dict[str, Any], *, is_complete: bool) -> str:
    next_state = _backlog_state_from_complete(is_complete)
    state["fsm_state"] = next_state
    state["fsm_state_entered_at"] = _now_iso()
    return next_state


@app.post("/api/projects/{project_id}/backlog/generate")
async def generate_project_backlog(
    project_id: int, req: BacklogGenerateRequest
):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    context = await _hydrate_context(session_id, project_id)

    if context.state.get("fsm_state") in [
        OrchestratorState.SETUP_REQUIRED.value
    ]:
        raise HTTPException(
            status_code=409, detail="Setup required before backlog"
        )

    if context.state.get("fsm_state") not in [
        OrchestratorState.VISION_PERSISTENCE.value,
        OrchestratorState.BACKLOG_INTERVIEW.value,
        OrchestratorState.BACKLOG_REVIEW.value,
        OrchestratorState.BACKLOG_PERSISTENCE.value,
        OrchestratorState.ROADMAP_INTERVIEW.value,
    ]:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid FSM State for backlog: {context.state.get('fsm_state')}",
        )

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
    is_complete = (
        bool(backlog_result.get("is_complete"))
        if backlog_result.get("success")
        else False
    )

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
            **_failure_meta(
                backlog_result, fallback_summary=backlog_result.get("error")
            ),
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
        raise HTTPException(
            status_code=409, detail="No backlog draft available to save"
        )

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
        _build_tool_context(context),
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save backlog"),
        )

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


def _ensure_roadmap_attempts(state: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = state.get("roadmap_attempts")
    if not isinstance(attempts, list):
        attempts = []
    return attempts


def _record_roadmap_attempt(
    state: dict[str, Any],
    *,
    trigger: str,
    input_context: dict[str, Any],
    output_artifact: dict[str, Any],
    is_complete: bool,
    failure_meta: dict[str, Any] | None = None,
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


def _set_roadmap_fsm_state(state: dict[str, Any], *, is_complete: bool) -> str:
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
async def generate_project_roadmap(
    project_id: int, req: RoadmapGenerateRequest
):
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
            **_failure_meta(
                roadmap_result, fallback_summary=roadmap_result.get("error")
            ),
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
        raise HTTPException(
            status_code=409, detail="No roadmap draft available to save"
        )

    if not bool(assessment.get("is_complete", False)):
        raise HTTPException(
            status_code=409,
            detail="Roadmap cannot be saved until is_complete is true",
        )

    from orchestrator_agent.agent_tools.roadmap_builder.schemes import (
        RoadmapBuilderOutput,
    )

    context = await _hydrate_context(session_id, project_id)

    try:
        roadmap_data = RoadmapBuilderOutput.model_validate(assessment)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Invalid roadmap data in session: {e!s}"
        )

    result = save_roadmap_tool(
        SaveRoadmapToolInput(
            product_id=project_id,
            roadmap_data=roadmap_data,
        ),
        _build_tool_context(context),
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save roadmap"),
        )

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


def _get_all_roadmap_requirements(state: dict[str, Any]) -> list[str]:
    """Helper: extract all assigned backlog items from saved roadmap releases."""
    releases = state.get("roadmap_releases") or []
    reqs: list[str] = []
    for rel in releases:
        items = rel.get("items") or []
        reqs.extend(items)
    return reqs


def _ensure_story_attempts(
    state: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    attempts = state.get("story_attempts")
    if not isinstance(attempts, dict):
        attempts = {}
    return attempts


def _story_retryable(classification: str | None) -> bool:
    return classification in {
        "nonreusable_provider_failure",
        "nonreusable_transport_failure",
    }


def _ensure_story_runtime(
    state: dict[str, Any],
    *,
    parent_requirement: str,
) -> dict[str, Any]:
    return hydrate_story_runtime_from_legacy(
        state,
        parent_requirement=parent_requirement,
    )


def _find_attempt_by_id(
    runtime: dict[str, Any],
    attempt_id: str,
) -> dict[str, Any] | None:
    for attempt in reversed(runtime.get("attempt_history") or []):
        if not isinstance(attempt, dict):
            continue
        if attempt.get("attempt_id") == attempt_id:
            return attempt
    return None


def _story_current_draft_artifact(
    runtime: dict[str, Any],
) -> dict[str, Any] | None:
    draft_projection = runtime.get("draft_projection") or {}
    attempt_id = draft_projection.get("latest_reusable_attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        return None

    attempt = _find_attempt_by_id(runtime, attempt_id)
    artifact = (attempt or {}).get("output_artifact")
    if not isinstance(artifact, dict):
        return None

    stories = artifact.get("user_stories")
    if not isinstance(stories, list) or len(stories) == 0:
        return None
    return artifact


def _story_merge_recommendation_from_artifact(
    artifact: dict[str, Any],
) -> dict[str, Any] | None:
    stories = artifact.get("user_stories")
    if not isinstance(stories, list):
        return None

    for story in stories:
        if not isinstance(story, dict):
            continue
        if story.get("invest_score") != "Low":
            continue

        warning = story.get("decomposition_warning")
        if not isinstance(warning, str) or not warning.strip():
            continue

        normalized_warning = " ".join(warning.lower().split())
        if not any(
            signal in normalized_warning
            for signal in (
                "recommend consolidating",
                "merge this",
                "retire this separate requirement",
                "retire this requirement",
                "merge into",
                "consolidated into",
                "may be redundant",
                "requirement may be redundant",
            )
        ):
            continue

        owner_match = re.search(r"owned by '([^']+)'", warning, flags=re.IGNORECASE)
        if not owner_match:
            continue

        acceptance_criteria = story.get("acceptance_criteria")
        if not isinstance(acceptance_criteria, list):
            acceptance_criteria = []

        return {
            "action": "merge_into_requirement",
            "owner_requirement": owner_match.group(1).strip(),
            "reason": warning.strip(),
            "acceptance_criteria_to_move": [
                item
                for item in acceptance_criteria
                if isinstance(item, str) and item.strip()
            ],
        }

    return None


def _story_save_payload(runtime: dict[str, Any]) -> dict[str, Any] | None:
    draft_projection = runtime.get("draft_projection") or {}
    if draft_projection.get("kind") != "complete_draft":
        return None

    artifact = _story_current_draft_artifact(runtime)
    if not isinstance(artifact, dict):
        return None
    if _story_merge_recommendation_from_artifact(artifact):
        return None
    if not artifact.get("is_complete"):
        return None
    return artifact


def _story_current_resolution(
    runtime: dict[str, Any],
) -> dict[str, Any] | None:
    resolution_projection = runtime.get("resolution_projection") or {}
    if not isinstance(resolution_projection, dict) or not resolution_projection:
        return None
    if resolution_projection.get("status") != "merged":
        return None
    owner_requirement = resolution_projection.get("owner_requirement")
    reason = resolution_projection.get("reason")
    criteria = resolution_projection.get("acceptance_criteria_to_move")
    if not isinstance(owner_requirement, str) or not owner_requirement.strip():
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    if not isinstance(criteria, list):
        criteria = []
    return {
        "status": "merged",
        "owner_requirement": owner_requirement,
        "reason": reason,
        "acceptance_criteria_to_move": [
            item for item in criteria if isinstance(item, str) and item.strip()
        ],
        "resolved_at": resolution_projection.get("resolved_at"),
    }


def _story_merge_recommendation_payload(
    runtime: dict[str, Any],
) -> dict[str, Any] | None:
    artifact = _story_current_draft_artifact(runtime)
    if not isinstance(artifact, dict):
        return None
    return _story_merge_recommendation_from_artifact(artifact)


def _story_resolution_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    current = _story_current_resolution(runtime)
    recommendation = None if current else _story_merge_recommendation_payload(runtime)
    return {
        "available": bool(recommendation),
        "current": current,
        "recommendation": recommendation,
    }


def _story_has_working_state(runtime: dict[str, Any]) -> bool:
    if _story_current_resolution(runtime):
        return True

    draft_projection = runtime.get("draft_projection") or {}
    if draft_projection:
        return True

    request_projection = runtime.get("request_projection") or {}
    if isinstance(request_projection.get("payload"), dict):
        return True

    feedback_projection = runtime.get("feedback_projection") or {}
    items = feedback_projection.get("items") or []
    if not isinstance(items, list):
        return False

    return any(
        isinstance(item, dict)
        and item.get("status") == "unabsorbed"
        and isinstance(item.get("text"), str)
        and item.get("text").strip()
        for item in items
    )


def _story_retry_target_attempt_id(runtime: dict[str, Any]) -> str | None:
    attempts = runtime.get("attempt_history") or []
    latest_attempt = attempts[-1] if attempts else {}
    request_projection = runtime.get("request_projection") or {}
    if not (
        isinstance(latest_attempt, dict)
        and latest_attempt.get("retryable")
        and isinstance(request_projection.get("payload"), dict)
    ):
        return None

    attempt_id = latest_attempt.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        return None
    return attempt_id


def _story_interview_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    draft_projection = runtime.get("draft_projection") or {}
    retry_target_attempt_id = _story_retry_target_attempt_id(runtime)

    current_draft = None
    if draft_projection:
        current_draft = {
            "attempt_id": draft_projection.get("latest_reusable_attempt_id"),
            "kind": draft_projection.get("kind"),
            "is_complete": bool(draft_projection.get("is_complete", False)),
        }

    return {
        "current_draft": current_draft,
        "retry": {
            "available": bool(retry_target_attempt_id),
            "target_attempt_id": retry_target_attempt_id,
        },
        "save": {
            "available": bool(_story_save_payload(runtime)),
        },
        "resolution": _story_resolution_summary(runtime),
    }


def _story_unabsorbed_feedback_ids(runtime: dict[str, Any]) -> list[str]:
    feedback_projection = runtime.get("feedback_projection") or {}
    if not isinstance(feedback_projection, dict):
        return []

    items = feedback_projection.get("items") or []
    if not isinstance(items, list):
        return []

    feedback_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "unabsorbed":
            continue
        feedback_id = item.get("feedback_id")
        if isinstance(feedback_id, str) and feedback_id:
            feedback_ids.append(feedback_id)
    return feedback_ids


def _sync_story_legacy_mirrors(
    state: dict[str, Any],
    *,
    parent_requirement: str,
    runtime: dict[str, Any],
) -> None:
    story_attempts = state.get("story_attempts")
    if not isinstance(story_attempts, dict):
        story_attempts = {}
        state["story_attempts"] = story_attempts

    story_attempts[parent_requirement] = [
        {
            "created_at": attempt.get("created_at"),
            "trigger": attempt.get("trigger"),
            "input_context": (
                attempt.get("input_context")
                if isinstance(attempt.get("input_context"), dict)
                else {}
            ),
            "output_artifact": attempt.get("output_artifact"),
            "is_complete": bool(
                (
                    (attempt.get("output_artifact") or {})
                    if isinstance(attempt, dict)
                    else {}
                ).get("is_complete")
            ),
            "failure_artifact_id": attempt.get("failure_artifact_id"),
            "failure_stage": attempt.get("failure_stage"),
            "failure_summary": attempt.get("failure_summary"),
            "raw_output_preview": attempt.get("raw_output_preview"),
            "has_full_artifact": bool(attempt.get("has_full_artifact", False)),
        }
        for attempt in runtime.get("attempt_history") or []
        if isinstance(attempt, dict) and attempt.get("trigger") != "reset"
    ]

    story_outputs = state.get("story_outputs")
    if not isinstance(story_outputs, dict):
        story_outputs = {}
        state["story_outputs"] = story_outputs

    reusable = _story_save_payload(runtime)
    if reusable:
        story_outputs[parent_requirement] = reusable
    else:
        story_outputs.pop(parent_requirement, None)


@app.get("/api/projects/{project_id}/story/pending")
async def get_project_story_pending(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)

    roadmap_releases = state.get("roadmap_releases") or []
    attempts_dict = _ensure_story_attempts(state)
    saved_reqs_dict = state.get(
        "story_saved", {}
    )  # track which ones successfully saved

    grouped_items = []
    total_count = 0
    saved_count = 0

    # Build structural hierarchy
    for release_index, rel in enumerate(roadmap_releases):
        reqs = rel.get("items") or []
        theme = rel.get("theme", "Milestone Context")
        reasoning = rel.get("reasoning", "")

        milestone_group = {
            "group_id": f"milestone_{release_index}",
            "theme": theme,
            "reasoning": reasoning,
            "requirements": [],
        }

        for req in reqs:
            req_attempts = attempts_dict.get(req, [])
            runtime = _ensure_story_runtime(
                state,
                parent_requirement=req,
            )
            if saved_reqs_dict.get(req):
                status = "Saved"
                saved_count += 1
            elif _story_current_resolution(runtime):
                status = "Merged"
            elif _story_has_working_state(runtime):
                status = "Attempted"
            else:
                status = "Pending"

            milestone_group["requirements"].append(
                {
                    "requirement": req,
                    "status": status,
                    "attempt_count": len(req_attempts),
                }
            )
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
async def generate_project_story(
    project_id: int, parent_requirement: str, req: StoryGenerateRequest
):
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
            raise HTTPException(
                status_code=400,
                detail=f"Requirement '{parent_requirement}' not found in saved roadmap.",
            )

    runtime = _ensure_story_runtime(
        state,
        parent_requirement=parent_requirement,
    )
    has_attempts = _story_has_working_state(runtime)
    normalized_user_input = (
        req.user_input.strip() if isinstance(req.user_input, str) else None
    )

    if has_attempts and not normalized_user_input:
        raise HTTPException(
            status_code=400,
            detail="User input is required to refine an existing story.",
        )

    if normalized_user_input:
        append_feedback_entry(
            runtime,
            normalized_user_input,
            _now_iso(),
        )
    included_feedback_ids = _story_unabsorbed_feedback_ids(runtime)

    story_result = await run_story_agent_from_state(
        state,
        project_id=project_id,
        parent_requirement=parent_requirement,
        user_input=None if included_feedback_ids else req.user_input,
    )
    request_payload = story_result.get("request_payload")
    if not isinstance(request_payload, dict):
        request_payload = {}

    created_at = _now_iso()
    draft_basis_attempt_id = (runtime.get("draft_projection") or {}).get(
        "latest_reusable_attempt_id"
    )
    request_projection = set_request_projection(
        runtime,
        request_snapshot_id=f"request-{len(runtime.get('attempt_history') or []) + 1}",
        payload=request_payload,
        request_hash=hashlib.sha256(
            json.dumps(request_payload, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        created_at=created_at,
        draft_basis_attempt_id=draft_basis_attempt_id
        if isinstance(draft_basis_attempt_id, str)
        else None,
        included_feedback_ids=included_feedback_ids,
        context_version="story-runtime.v1",
    )

    attempt_id = f"attempt-{len(runtime.get('attempt_history') or []) + 1}"
    append_attempt(
        runtime,
        {
            "attempt_id": attempt_id,
            "created_at": created_at,
            "trigger": "manual_refine"
            if normalized_user_input
            else "auto_transition",
            "request_snapshot_id": request_projection.get(
                "request_snapshot_id"
            ),
            "draft_basis_attempt_id": request_projection.get(
                "draft_basis_attempt_id"
            ),
            "included_feedback_ids": list(included_feedback_ids),
            "input_context": story_result.get("input_context")
            or request_payload,
            "classification": story_result.get("classification"),
            "is_reusable": bool(story_result.get("is_reusable", False)),
            "retryable": _story_retryable(story_result.get("classification")),
            "draft_kind": story_result.get("draft_kind"),
            "output_artifact": story_result.get("output_artifact") or {},
            **_failure_meta(
                story_result, fallback_summary=story_result.get("error")
            ),
        },
    )

    if story_result.get("is_reusable"):
        runtime["resolution_projection"] = {}
        promote_reusable_draft(
            runtime,
            attempt_id=attempt_id,
            kind=story_result.get("draft_kind") or "incomplete_draft",
            is_complete=bool(story_result.get("is_complete", False)),
            updated_at=created_at,
        )
        mark_feedback_absorbed(
            runtime,
            feedback_ids=included_feedback_ids,
            attempt_id=attempt_id,
        )

    _sync_story_legacy_mirrors(
        state,
        parent_requirement=parent_requirement,
        runtime=runtime,
    )

    _save_session_state(session_id, state)

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "output_artifact": story_result.get("output_artifact"),
            **_story_interview_summary(runtime),
        },
    }


@app.post("/api/projects/{project_id}/story/retry")
async def retry_project_story(project_id: int, parent_requirement: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    runtime = _ensure_story_runtime(
        state,
        parent_requirement=parent_requirement,
    )
    request_projection = runtime.get("request_projection") or {}
    request_payload = request_projection.get("payload")
    if not isinstance(request_payload, dict):
        raise HTTPException(
            status_code=409,
            detail="No replayable story request is available.",
        )
    if not _story_retry_target_attempt_id(runtime):
        raise HTTPException(
            status_code=409,
            detail="The latest story attempt is not eligible for retry.",
        )

    story_result = await run_story_agent_request(
        request_payload,
        project_id=project_id,
        parent_requirement=parent_requirement,
    )

    created_at = _now_iso()
    included_feedback_ids = list(
        request_projection.get("included_feedback_ids") or []
    )
    attempt_id = f"attempt-{len(runtime.get('attempt_history') or []) + 1}"
    append_attempt(
        runtime,
        {
            "attempt_id": attempt_id,
            "created_at": created_at,
            "trigger": "retry_same_input",
            "request_snapshot_id": request_projection.get(
                "request_snapshot_id"
            ),
            "draft_basis_attempt_id": request_projection.get(
                "draft_basis_attempt_id"
            ),
            "included_feedback_ids": included_feedback_ids,
            "input_context": story_result.get("input_context")
            or request_payload,
            "classification": story_result.get("classification"),
            "is_reusable": bool(story_result.get("is_reusable", False)),
            "retryable": _story_retryable(story_result.get("classification")),
            "draft_kind": story_result.get("draft_kind"),
            "output_artifact": story_result.get("output_artifact") or {},
            **_failure_meta(
                story_result, fallback_summary=story_result.get("error")
            ),
        },
    )

    if story_result.get("is_reusable"):
        runtime["resolution_projection"] = {}
        promote_reusable_draft(
            runtime,
            attempt_id=attempt_id,
            kind=story_result.get("draft_kind") or "incomplete_draft",
            is_complete=bool(story_result.get("is_complete", False)),
            updated_at=created_at,
        )
        mark_feedback_absorbed(
            runtime,
            feedback_ids=included_feedback_ids,
            attempt_id=attempt_id,
        )

    _sync_story_legacy_mirrors(
        state,
        parent_requirement=parent_requirement,
        runtime=runtime,
    )
    _save_session_state(session_id, state)

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "output_artifact": story_result.get("output_artifact"),
            **_story_interview_summary(runtime),
        },
    }


@app.get("/api/projects/{project_id}/story/history")
async def get_project_story_history(project_id: int, parent_requirement: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    runtime = _ensure_story_runtime(
        state,
        parent_requirement=parent_requirement,
    )
    attempt_history = runtime.get("attempt_history") or []

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "items": attempt_history,
            "count": len(attempt_history),
            **_story_interview_summary(runtime),
        },
    }


@app.post("/api/projects/{project_id}/story/save")
async def save_project_story(project_id: int, parent_requirement: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    runtime = _ensure_story_runtime(
        state,
        parent_requirement=parent_requirement,
    )
    assessment = _story_save_payload(runtime)

    if not assessment:
        raise HTTPException(
            status_code=409,
            detail=f"No story draft available for '{parent_requirement}'",
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
        _build_tool_context(context),
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save stories"),
        )

    # Record that this specific requirement was saved successfully
    saved_reqs_dict = context.state.get("story_saved", {})
    if not isinstance(saved_reqs_dict, dict):
        saved_reqs_dict = {}
    saved_reqs_dict[parent_requirement] = True
    context.state["story_saved"] = saved_reqs_dict
    _sync_story_legacy_mirrors(
        context.state,
        parent_requirement=parent_requirement,
        runtime=runtime,
    )

    _save_session_state(session_id, context.state)

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "save_result": result,
        },
    }


@app.post("/api/projects/{project_id}/story/merge")
async def merge_project_story(project_id: int, parent_requirement: str):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    runtime = _ensure_story_runtime(
        state,
        parent_requirement=parent_requirement,
    )

    recommendation = _story_merge_recommendation_payload(runtime)
    if not recommendation:
        raise HTTPException(
            status_code=409,
            detail="No merge recommendation is available for this requirement.",
        )

    resolution = {
        "status": "merged",
        "owner_requirement": recommendation["owner_requirement"],
        "reason": recommendation["reason"],
        "acceptance_criteria_to_move": recommendation["acceptance_criteria_to_move"],
        "resolved_at": _now_iso(),
    }
    runtime["resolution_projection"] = resolution

    _sync_story_legacy_mirrors(
        state,
        parent_requirement=parent_requirement,
        runtime=runtime,
    )
    _save_session_state(session_id, state)

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "resolution": _story_resolution_summary(runtime),
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

    normalized_requirement = normalize_requirement_key(parent_requirement)

    engine = get_engine()
    with Session(engine) as session:
        # Find all stories for this requirement in this product
        # 1. Get the list of story IDs to delete
        stmt = select(UserStory.story_id).where(
            UserStory.product_id == project_id,
            UserStory.source_requirement == normalized_requirement,
        )
        story_ids = session.exec(stmt).all()

        deleted_count = len(story_ids)

        if story_ids:
            # When batch deleting, we must explicitly delete child records to satisfy foreign keys
            # since bulk delete operations bypass SQLAlchemy ORM-level cascades.
            # Chunking the IN clause is a good practice to avoid SQLite limits
            chunk_size = 500
            for i in range(0, len(story_ids), chunk_size):
                chunk_ids = story_ids[i : i + chunk_size]

                # Delete sprint mappings
                session.exec(
                    delete(SprintStory).where(
                        SprintStory.story_id.in_(chunk_ids)
                    )
                )

                # Delete completion logs
                session.exec(
                    delete(StoryCompletionLog).where(
                        StoryCompletionLog.story_id.in_(chunk_ids)
                    )
                )

                # Delete tasks (and potentially their execution logs if they exist)
                # First get task IDs to delete any task execution logs

                task_ids_stmt = select(Task.task_id).where(
                    Task.story_id.in_(chunk_ids)
                )
                task_ids = session.exec(task_ids_stmt).all()
                if task_ids:
                    for j in range(0, len(task_ids), chunk_size):
                        task_chunk = task_ids[j : j + chunk_size]
                        session.exec(
                            delete(TaskExecutionLog).where(
                                TaskExecutionLog.task_id.in_(task_chunk)
                            )
                        )

                # Now delete tasks
                session.exec(delete(Task).where(Task.story_id.in_(chunk_ids)))

                # Delete the stories
                session.exec(
                    delete(UserStory).where(UserStory.story_id.in_(chunk_ids))
                )

        session.commit()

    # Clean up session state
    session_id = str(project_id)
    state = await _ensure_session(session_id)
    runtime = _ensure_story_runtime(
        state,
        parent_requirement=parent_requirement,
    )
    reset_subject_working_set(
        runtime,
        created_at=_now_iso(),
        summary="Stories deleted and state reset by user.",
    )

    story_saved = state.get("story_saved")
    if isinstance(story_saved, dict):
        story_saved.pop(parent_requirement, None)

    _sync_story_legacy_mirrors(
        state,
        parent_requirement=parent_requirement,
        runtime=runtime,
    )
    _save_session_state(session_id, state)

    return {
        "status": "success",
        "parent_requirement": parent_requirement,
        "data": {
            "deleted_count": deleted_count,
            "message": "Stories deleted successfully",
        },
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

    saved = [r for r in req_names if saved_reqs_dict.get(r)]

    if len(saved) == 0:
        raise HTTPException(
            status_code=409,
            detail="Cannot complete phase. No requirements have saved stories.",
        )

    # All pass, transition into Sprint Setup for explicit planning inputs.
    current_state = _normalize_fsm_state(state.get("fsm_state"))
    # Only update if we aren't already past it
    if current_state not in (
        OrchestratorState.SPRINT_SETUP.value,
        OrchestratorState.SPRINT_DRAFT.value,
        OrchestratorState.SPRINT_PERSISTENCE.value,
        OrchestratorState.SPRINT_COMPLETE.value,
    ):
        state["fsm_state"] = OrchestratorState.SPRINT_SETUP.value
        state["fsm_state_entered_at"] = _now_iso()
        state["story_phase_completed_at"] = _now_iso()
        _save_session_state(session_id, state)

    return {"status": "success", "data": {"fsm_state": state.get("fsm_state")}}


# ==============================================================================
# SPRINT ENDPOINTS
# ==============================================================================


def _ensure_sprint_attempts(state: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = state.get("sprint_attempts")
    if not isinstance(attempts, list):
        attempts = []
    return attempts


def _load_current_planned_sprint_id(project_id: int) -> int | None:
    with Session(get_engine()) as session:
        planned_sprint = session.exec(
            select(Sprint.sprint_id)
            .where(
                Sprint.product_id == project_id,
                Sprint.status == SprintStatus.PLANNED,
            )
            .order_by(
                Sprint.updated_at.desc(),
                Sprint.created_at.desc(),
                Sprint.sprint_id.desc(),
            )
        ).first()
    return planned_sprint


def _reset_sprint_planner_working_set(state: dict[str, Any]) -> None:
    state["sprint_attempts"] = []
    state["sprint_last_input_context"] = None
    state["sprint_plan_assessment"] = None
    state["sprint_saved_at"] = None
    state["sprint_planner_owner_sprint_id"] = None


def _reset_stale_saved_sprint_planner_working_set(
    state: dict[str, Any],
    *,
    project_id: int,
) -> bool:
    owner_sprint_id = state.get("sprint_planner_owner_sprint_id")
    if owner_sprint_id is None:
        return False

    planned_sprint_id = _load_current_planned_sprint_id(project_id)
    if owner_sprint_id == planned_sprint_id:
        return False

    _reset_sprint_planner_working_set(state)
    return True


def _record_sprint_attempt(
    state: dict[str, Any],
    *,
    trigger: str,
    input_context: dict[str, Any],
    output_artifact: dict[str, Any],
    is_complete: bool,
    failure_meta: dict[str, Any] | None = None,
) -> int:
    attempts = _ensure_sprint_attempts(state)
    normalized_failure = _failure_meta(failure_meta)
    normalized_output_artifact = _normalize_sprint_output_artifact(output_artifact)
    attempts.append(
        {
            "created_at": _now_iso(),
            "trigger": trigger,
            "input_context": input_context,
            "output_artifact": normalized_output_artifact,
            "is_complete": is_complete,
            **normalized_failure,
        }
    )
    state["sprint_attempts"] = attempts
    state["sprint_last_input_context"] = input_context
    state["sprint_plan_assessment"] = normalized_output_artifact
    return len(attempts)


@app.get("/api/projects/{project_id}/sprint/candidates")
async def get_project_sprint_candidates(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    result = load_sprint_candidates(project_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("message") or "Failed to load sprint candidates",
        )

    return {
        "status": "success",
        "data": {
            "items": result.get("stories", []),
            "count": result.get("count", 0),
            "excluded_counts": result.get("excluded_counts", {}),
            "message": result.get("message"),
        },
    }


@app.post("/api/projects/{project_id}/sprint/generate")
async def generate_project_sprint(project_id: int, req: SprintGenerateRequest):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    _reset_stale_saved_sprint_planner_working_set(
        state,
        project_id=project_id,
    )

    # Validate valid FSM state to allow sprint planning
    valid_states = [
        OrchestratorState.STORY_PERSISTENCE.value,
        OrchestratorState.SPRINT_SETUP.value,
        OrchestratorState.SPRINT_DRAFT.value,
        OrchestratorState.SPRINT_PERSISTENCE.value,
    ]
    if state.get("fsm_state") not in valid_states:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid phase for sprint generation (state: {state.get('fsm_state')})",
        )

    attempts = _ensure_sprint_attempts(state)
    has_attempts = len(attempts) > 0

    sprint_result = await run_sprint_agent_from_state(
        state,
        project_id=project_id,
        team_velocity_assumption=req.team_velocity_assumption,
        sprint_duration_days=req.sprint_duration_days,
        max_story_points=req.max_story_points,
        include_task_decomposition=req.include_task_decomposition,
        selected_story_ids=req.selected_story_ids,
        user_input=req.user_input,
    )
    normalized_output_artifact = _normalize_sprint_output_artifact(
        cast(dict[str, Any] | None, sprint_result.get("output_artifact"))
    )

    is_complete = bool(sprint_result.get("is_complete", False))
    attempt_count = _record_sprint_attempt(
        state,
        trigger="manual_refine" if has_attempts else "auto_transition",
        input_context=sprint_result.get("input_context") or {},
        output_artifact=normalized_output_artifact,
        is_complete=is_complete,
        failure_meta=sprint_result,
    )

    state["fsm_state"] = (
        OrchestratorState.SPRINT_DRAFT.value
        if is_complete
        else OrchestratorState.SPRINT_SETUP.value
    )
    state["fsm_state_entered_at"] = _now_iso()

    _save_session_state(session_id, state)

    return {
        "status": "success",
        "data": {
            "is_complete": is_complete,
            "sprint_run_success": bool(sprint_result.get("success")),
            "error": sprint_result.get("error"),
            "trigger": "manual_refine" if has_attempts else "auto_transition",
            "input_context": sprint_result.get("input_context"),
            "output_artifact": normalized_output_artifact,
            "attempt_count": attempt_count,
            **_failure_meta(
                sprint_result, fallback_summary=sprint_result.get("error")
            ),
            "fsm_state": state.get("fsm_state"),
        },
    }


@app.get("/api/projects/{project_id}/sprint/history")
async def get_project_sprint_history(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    if _reset_stale_saved_sprint_planner_working_set(
        state,
        project_id=project_id,
    ):
        _save_session_state(session_id, state)
    attempts = _ensure_sprint_attempts(state)
    normalized_attempts = [
        _normalize_sprint_attempt(attempt)
        for attempt in attempts
        if isinstance(attempt, dict)
    ]
    if normalized_attempts != attempts:
        state["sprint_attempts"] = normalized_attempts
        _save_session_state(session_id, state)
    attempts = normalized_attempts

    return {
        "status": "success",
        "data": {
            "items": attempts,
            "count": len(attempts),
        },
    }


@app.post("/api/projects/{project_id}/sprint/planner/reset")
async def reset_project_sprint_planner(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    planned_sprint_id = _load_current_planned_sprint_id(project_id)
    if planned_sprint_id is not None:
        raise HTTPException(
            status_code=409,
            detail="A planned sprint already exists. Modify it instead of creating another.",
        )

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    _reset_sprint_planner_working_set(state)
    _save_session_state(session_id, state)

    return {
        "status": "success",
        "data": {
            "items": [],
            "count": 0,
        },
    }


@app.get("/api/projects/{project_id}/sprints")
async def list_project_sprints(project_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = _list_saved_sprints(project_id)
    return {
        "status": "success",
        "data": {
            "items": payload["items"],
            "count": len(payload["items"]),
            "runtime_summary": payload["runtime_summary"],
        },
    }


@app.get("/api/projects/{project_id}/sprints/{sprint_id}")
async def get_project_sprint(project_id: int, sprint_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    with Session(get_engine()) as session:
        sprint = _get_saved_sprint(session, project_id, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")

        all_sprints = session.exec(
            _saved_sprint_query()
            .where(Sprint.product_id == project_id)
            .order_by(Sprint.created_at.desc())
        ).all()
        runtime_summary = _build_sprint_runtime_summary(all_sprints)

        return {
            "status": "success",
            "data": {
                "sprint": _serialize_sprint_detail(
                    sprint,
                    runtime_summary=runtime_summary,
                ),
                "runtime_summary": runtime_summary,
            },
        }


@app.get(
    "/api/projects/{project_id}/sprints/{sprint_id}/close",
    response_model=SprintCloseReadResponse,
)
def get_sprint_close(project_id: int, sprint_id: int):
    with Session(get_engine()) as session:
        sprint = _get_saved_sprint(session, project_id, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")

        readiness = _build_sprint_close_readiness(list(sprint.stories))
        close_eligible = sprint.status == SprintStatus.ACTIVE
        if close_eligible:
            ineligible_reason = None
        elif sprint.status == SprintStatus.COMPLETED:
            ineligible_reason = "Sprint is already completed."
        else:
            ineligible_reason = "Only active sprints can be closed."

        return SprintCloseReadResponse(
            success=True,
            sprint_id=sprint_id,
            current_status=sprint.status.value,
            completed_at=sprint.completed_at,
            readiness=readiness,
            close_eligible=close_eligible,
            ineligible_reason=ineligible_reason,
            history_fidelity=_history_fidelity(sprint),
            close_snapshot=_load_sprint_close_snapshot(sprint),
        )


@app.post(
    "/api/projects/{project_id}/sprints/{sprint_id}/close",
    response_model=SprintCloseReadResponse,
)
def post_sprint_close(
    project_id: int, sprint_id: int, req: SprintCloseWriteRequest
):
    with Session(get_engine()) as session:
        sprint = _get_saved_sprint(session, project_id, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")
        if sprint.status != SprintStatus.ACTIVE:
            raise HTTPException(
                status_code=409, detail="Only active sprints can be closed."
            )

        readiness = _build_sprint_close_readiness(list(sprint.stories))
        snapshot = {
            "closed_at": _now_iso(),
            "completion_notes": req.completion_notes,
            "follow_up_notes": req.follow_up_notes,
            "completed_story_count": readiness.completed_story_count,
            "open_story_count": readiness.open_story_count,
            "unfinished_story_ids": readiness.unfinished_story_ids,
            "stories": [
                story.model_dump(mode="json") for story in readiness.stories
            ],
        }

        sprint.status = SprintStatus.COMPLETED
        sprint.completed_at = datetime.now(UTC)
        sprint.close_snapshot_json = json.dumps(snapshot)
        session.add(sprint)
        session.add(
            WorkflowEvent(
                event_type=WorkflowEventType.SPRINT_COMPLETED,
                product_id=project_id,
                sprint_id=sprint_id,
                session_id=str(project_id),
                event_metadata=json.dumps(snapshot),
            )
        )
        session.commit()

        return SprintCloseReadResponse(
            success=True,
            sprint_id=sprint_id,
            current_status=SprintStatus.COMPLETED.value,
            completed_at=sprint.completed_at,
            readiness=readiness,
            close_eligible=False,
            ineligible_reason="Sprint is already completed.",
            history_fidelity="snapshotted",
            close_snapshot=snapshot,
        )


@app.get(
    "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet"
)
async def get_project_task_packet(
    project_id: int, sprint_id: int, task_id: int, flavor: str | None = None
):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    with Session(get_engine()) as session:
        packet = _build_task_packet(
            session,
            project_id=project_id,
            sprint_id=sprint_id,
            task_id=task_id,
        )
        if not packet:
            raise HTTPException(
                status_code=404, detail="Task packet context not found"
            )

        payload = dict(packet)
        if flavor:
            from services.packet_renderer import render_packet

            payload["render"] = render_packet(packet, flavor)

        return {
            "status": "success",
            "data": payload,
        }


@app.get(
    "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/packet"
)
async def get_project_story_packet(
    project_id: int,
    sprint_id: int,
    story_id: int,
    flavor: str | None = None,
):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    with Session(get_engine()) as session:
        packet = _build_story_packet(
            session,
            project_id=project_id,
            sprint_id=sprint_id,
            story_id=story_id,
        )
        if not packet:
            raise HTTPException(
                status_code=404, detail="Story packet context not found"
            )

        payload = dict(packet)
        if flavor:
            from services.packet_renderer import render_packet

            payload["render"] = render_packet(packet, flavor)

        return {
            "status": "success",
            "data": payload,
        }


@app.get(
    "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
    response_model=TaskExecutionReadResponse,
)
def get_task_execution(project_id: int, sprint_id: int, task_id: int):
    with Session(get_engine()) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        sprint = session.get(Sprint, sprint_id)
        if not sprint or sprint.product_id != project_id:
            raise HTTPException(
                status_code=404, detail="Sprint not found in this project"
            )

        sprint_story = session.exec(
            select(SprintStory).where(
                SprintStory.sprint_id == sprint_id,
                SprintStory.story_id == task.story_id,
            )
        ).first()

        if not sprint_story:
            raise HTTPException(
                status_code=404,
                detail="Task does not belong to the given sprint",
            )

        logs = session.exec(
            select(TaskExecutionLog)
            .where(
                TaskExecutionLog.task_id == task_id,
                TaskExecutionLog.sprint_id == sprint_id,
            )
            .order_by(TaskExecutionLog.changed_at.desc())
        ).all()

        history = []
        for log in logs:
            artifact_refs = []
            if log.artifact_refs_json:
                try:
                    artifact_refs = json.loads(log.artifact_refs_json)
                except Exception:
                    pass
            history.append(
                TaskExecutionLogEntry(
                    log_id=log.log_id,
                    task_id=log.task_id,
                    sprint_id=log.sprint_id,
                    old_status=log.old_status,
                    new_status=log.new_status,
                    outcome_summary=log.outcome_summary,
                    artifact_refs=artifact_refs,
                    acceptance_result=log.acceptance_result,
                    notes=log.notes,
                    changed_by=log.changed_by,
                    changed_at=log.changed_at,
                )
            )

        return TaskExecutionReadResponse(
            success=True,
            task_id=task_id,
            sprint_id=sprint_id,
            current_status=task.status,
            latest_entry=history[0] if history else None,
            history=history,
        )


@app.post(
    "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
    response_model=TaskExecutionReadResponse,
)
def post_task_execution(
    project_id: int,
    sprint_id: int,
    task_id: int,
    req: TaskExecutionWriteRequest,
):
    with Session(get_engine()) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        sprint = session.get(Sprint, sprint_id)
        if not sprint or sprint.product_id != project_id:
            raise HTTPException(
                status_code=404, detail="Sprint not found in this project"
            )

        sprint_story = session.exec(
            select(SprintStory).where(
                SprintStory.sprint_id == sprint_id,
                SprintStory.story_id == task.story_id,
            )
        ).first()

        if not sprint_story:
            raise HTTPException(
                status_code=404,
                detail="Task does not belong to the given sprint",
            )

        task_metadata = parse_task_metadata(task.metadata_json)
        if not task_metadata.checklist_items:
            raise HTTPException(
                status_code=409,
                detail="Task has no executable checklist items.",
            )

        old_status = task.status
        if req.new_status:
            task.status = req.new_status

        artifact_refs_json = None
        if req.artifact_refs:
            refs = []
            seen = set()
            for r in req.artifact_refs:
                rs = r.strip()
                if rs and rs not in seen:
                    refs.append(rs)
                    seen.add(rs)
            artifact_refs_json = json.dumps(refs) if refs else None

        log_entry = TaskExecutionLog(
            task_id=task_id,
            sprint_id=sprint_id,
            old_status=old_status,
            new_status=task.status,
            outcome_summary=req.outcome_summary,
            artifact_refs_json=artifact_refs_json,
            notes=req.notes,
            acceptance_result=req.acceptance_result
            or TaskAcceptanceResult.NOT_CHECKED,
            changed_by=req.changed_by or "manual-ui",
        )
        session.add(log_entry)
        session.commit()

    return get_task_execution(project_id, sprint_id, task_id)


@app.get(
    "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
    response_model=StoryCloseReadResponse,
)
def get_story_close(project_id: int, sprint_id: int, story_id: int):
    with Session(get_engine()) as session:
        story = session.get(UserStory, story_id)
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        sprint = session.get(Sprint, sprint_id)
        if not sprint or sprint.product_id != project_id:
            raise HTTPException(
                status_code=404, detail="Sprint not found in this project"
            )

        sprint_story = session.exec(
            select(SprintStory).where(
                SprintStory.sprint_id == sprint_id,
                SprintStory.story_id == story_id,
            )
        ).first()

        if not sprint_story:
            raise HTTPException(
                status_code=404,
                detail="Story does not belong to the given sprint",
            )

        tasks = session.exec(
            select(Task).where(Task.story_id == story_id)
        ).all()
        total_tasks, done_tasks, cancelled_tasks, all_actionable_done = (
            _story_task_progress(tasks)
        )

        readiness = StoryTaskProgressSummary(
            total_tasks=total_tasks,
            done_tasks=done_tasks,
            cancelled_tasks=cancelled_tasks,
            all_actionable_tasks_done=all_actionable_done,
        )

        close_eligible = all_actionable_done
        ineligible_reason = (
            None
            if close_eligible
            else "Not all actionable tasks are completed or cancelled."
        )
        if total_tasks == 0:
            close_eligible = False
            ineligible_reason = "Story has no executable tasks."

        if story.status in (StoryStatus.ACCEPTED, StoryStatus.DONE):
            close_eligible = False
            ineligible_reason = f"Story is already {story.status.value}."

        return StoryCloseReadResponse(
            success=True,
            story_id=story_id,
            sprint_id=sprint_id,
            current_status=story.status.value,
            resolution=story.resolution,
            completion_notes=story.completion_notes,
            evidence_links=story.evidence_links,
            completed_at=story.completed_at,
            readiness=readiness,
            close_eligible=close_eligible,
            ineligible_reason=ineligible_reason,
        )


@app.post(
    "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
    response_model=StoryCloseReadResponse,
)
def post_story_close(
    project_id: int, sprint_id: int, story_id: int, req: StoryCloseWriteRequest
):
    with Session(get_engine()) as session:
        story = session.get(UserStory, story_id)
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")

        sprint = session.get(Sprint, sprint_id)
        if not sprint or sprint.product_id != project_id:
            raise HTTPException(
                status_code=404, detail="Sprint not found in this project"
            )

        sprint_story = session.exec(
            select(SprintStory).where(
                SprintStory.sprint_id == sprint_id,
                SprintStory.story_id == story_id,
            )
        ).first()

        if not sprint_story:
            raise HTTPException(
                status_code=404,
                detail="Story does not belong to the given sprint",
            )

        tasks = session.exec(
            select(Task).where(Task.story_id == story_id)
        ).all()
        total_tasks, done_tasks, cancelled_tasks, all_actionable_done = (
            _story_task_progress(tasks)
        )

        if total_tasks == 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot close a story with no executable tasks.",
            )

        if not all_actionable_done:
            raise HTTPException(
                status_code=409,
                detail="Cannot close a story unless all actionable tasks are Done or Cancelled.",
            )

        old_status = story.status
        if old_status in (StoryStatus.ACCEPTED, StoryStatus.DONE):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot modify an already {old_status.value} story.",
            )

        evidence_json = None
        if req.evidence_links:
            evidence_json = json.dumps(req.evidence_links)

        story.status = StoryStatus.DONE
        story.resolution = req.resolution
        story.completion_notes = req.completion_notes
        story.evidence_links = evidence_json
        story.completed_at = datetime.now(UTC)

        log = StoryCompletionLog(
            story_id=story_id,
            old_status=old_status,
            new_status=StoryStatus.DONE,
            resolution=req.resolution,
            delivered=req.completion_notes,
            evidence=evidence_json,
            known_gaps=req.known_gaps,
            follow_ups_created=req.follow_up_notes,
            changed_by=req.changed_by or "manual-ui",
            changed_at=datetime.now(UTC),
        )
        session.add(log)
        session.commit()

    return get_story_close(project_id, sprint_id, story_id)


@app.post("/api/projects/{project_id}/sprint/save")
async def save_project_sprint(project_id: int, req: SprintSaveRequest):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    session_id = str(project_id)
    state = await _ensure_session(session_id)
    if _reset_stale_saved_sprint_planner_working_set(
        state,
        project_id=project_id,
    ):
        _save_session_state(session_id, state)

    assessment = state.get("sprint_plan_assessment")
    if not isinstance(assessment, dict):
        raise HTTPException(
            status_code=409, detail="No sprint draft available to save"
        )

    if not bool(assessment.get("is_complete", False)):
        raise HTTPException(
            status_code=409,
            detail="Sprint cannot be saved until is_complete is true",
        )

    from orchestrator_agent.agent_tools.sprint_planner_tool.schemes import (
        SprintPlannerOutput,
    )

    team_name = req.team_name.strip()
    sprint_start_date = req.sprint_start_date.strip()
    if not team_name:
        raise HTTPException(status_code=422, detail="team_name is required")
    if not sprint_start_date:
        raise HTTPException(
            status_code=422, detail="sprint_start_date is required"
        )

    assessment_payload = dict(assessment)
    assessment_payload.pop("is_complete", None)

    try:
        sprint_data = SprintPlannerOutput.model_validate(assessment_payload)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Invalid sprint data in session: {e!s}"
        )

    context = await _hydrate_context(session_id, project_id)
    context.state["sprint_plan"] = sprint_data.model_dump(exclude_none=True)

    result = save_sprint_plan_tool(
        SaveSprintPlanInput(
            product_id=project_id,
            team_name=team_name,
            sprint_start_date=sprint_start_date,
            sprint_duration_days=sprint_data.duration_days,
        ),
        _build_tool_context(context),
    )

    if not result.get("success"):
        status_code = (
            409
            if result.get("error_code") == "STORY_ALREADY_IN_OPEN_SPRINT"
            else 500
        )
        raise HTTPException(
            status_code=status_code,
            detail=result.get("error", "Failed to save sprint plan"),
        )

    state["fsm_state"] = OrchestratorState.SPRINT_PERSISTENCE.value
    state["fsm_state_entered_at"] = _now_iso()
    state["sprint_saved_at"] = _now_iso()
    state["sprint_planner_owner_sprint_id"] = result.get("sprint_id")

    _save_session_state(session_id, state)

    return {
        "status": "success",
        "data": {
            "fsm_state": OrchestratorState.SPRINT_PERSISTENCE.value,
            "save_result": result,
        },
    }


@app.patch("/api/projects/{project_id}/sprints/{sprint_id}/start")
async def start_project_sprint(project_id: int, sprint_id: int):
    product = product_repo.get_by_id(project_id)
    if not product:
        raise HTTPException(status_code=404, detail="Project not found")

    with Session(get_engine()) as session:
        sprint = _get_saved_sprint(session, project_id, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")

        other_active = session.exec(
            select(Sprint).where(
                Sprint.product_id == project_id,
                Sprint.status == SprintStatus.ACTIVE,
                Sprint.sprint_id != sprint_id,
            )
        ).first()
        if other_active:
            raise HTTPException(
                status_code=409,
                detail="Another sprint is already active for this project.",
            )

        if sprint.status == SprintStatus.COMPLETED:
            raise HTTPException(
                status_code=409,
                detail="Completed sprints cannot be restarted.",
            )

        if (
            sprint.status == SprintStatus.ACTIVE
            and sprint.started_at is not None
        ):
            all_sprints = session.exec(
                _saved_sprint_query()
                .where(Sprint.product_id == project_id)
                .order_by(Sprint.created_at.desc())
            ).all()
            runtime_summary = _build_sprint_runtime_summary(all_sprints)
            return {
                "status": "success",
                "data": {
                    "sprint": _serialize_sprint_detail(
                        sprint,
                        runtime_summary=runtime_summary,
                    ),
                },
            }

        if sprint.started_at is None:
            sprint.started_at = datetime.now(UTC)
            sprint.status = SprintStatus.ACTIVE
            session.add(sprint)
            session.add(
                WorkflowEvent(
                    event_type=WorkflowEventType.SPRINT_STARTED,
                    product_id=project_id,
                    sprint_id=sprint_id,
                    session_id=str(project_id),
                    event_metadata=json.dumps(
                        {
                            "team_id": sprint.team_id,
                            "planned_start_date": str(sprint.start_date),
                            "planned_end_date": str(sprint.end_date),
                        }
                    ),
                )
            )
            session.commit()
            session.refresh(sprint)
            sprint = _get_saved_sprint(session, project_id, sprint_id)
            if not sprint:
                raise HTTPException(status_code=404, detail="Sprint not found")

        all_sprints = session.exec(
            _saved_sprint_query()
            .where(Sprint.product_id == project_id)
            .order_by(Sprint.created_at.desc())
        ).all()
        runtime_summary = _build_sprint_runtime_summary(all_sprints)

        return {
            "status": "success",
            "data": {
                "sprint": _serialize_sprint_detail(
                    sprint,
                    runtime_summary=runtime_summary,
                ),
            },
        }


if __name__ == "__main__":
    host = get_api_host()
    port = get_api_port()
    reload_enabled = get_api_reload()
    print(f"Starting AgenticFlow Dashboard on http://{host}:{port}")
    uvicorn.run("api:app", host=host, port=port, reload=reload_enabled)
