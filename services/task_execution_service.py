# services/task_execution_service.py

"""Task execution endpoint orchestration helpers."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Protocol, Self, TypedDict, Unpack

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

from models.enums import TaskAcceptanceResult, TaskStatus
from utils.api_schemas import TaskExecutionLogEntry


class TaskExecutionServiceError(Exception):
    """Domain-level task execution error for router translation."""

    def __init__(self, detail: str, *, status_code: int) -> None:
        """Store an API-ready error detail and HTTP status code."""
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code

    @classmethod
    def task_not_found(cls) -> Self:
        """Build the 404 error raised when the task cannot be loaded."""
        return cls(detail="Task not found", status_code=404)

    @classmethod
    def sprint_not_in_project(cls) -> Self:
        """Build the 404 error raised for cross-project or missing sprints."""
        return cls(detail="Sprint not found in this project", status_code=404)

    @classmethod
    def task_not_in_sprint(cls) -> Self:
        """Build the 404 error raised when the task is outside the sprint."""
        return cls(detail="Task does not belong to the given sprint", status_code=404)

    @classmethod
    def task_not_executable(cls) -> Self:
        """Build the 409 error raised for tasks without executable checklist items."""
        return cls(detail="Task has no executable checklist items.", status_code=409)


class _TaskLike(Protocol):
    task_id: int
    story_id: int
    status: TaskStatus
    metadata_json: object | None


class _SprintLike(Protocol):
    sprint_id: int
    product_id: int | None


class _TaskExecutionLogLike(Protocol):
    log_id: int | None
    task_id: int
    sprint_id: int
    old_status: TaskStatus | None
    new_status: TaskStatus
    outcome_summary: str | None
    artifact_refs_json: object | None
    acceptance_result: TaskAcceptanceResult
    notes: str | None
    changed_by: str
    changed_at: object


class _TaskMetadataLike(Protocol):
    checklist_items: Sequence[object]


class _PersistExecutionLogOptions(TypedDict):
    task: _TaskLike
    old_status: TaskStatus
    new_status: TaskStatus
    outcome_summary: str | None
    artifact_refs_json: str | None
    notes: str | None
    acceptance_result: TaskAcceptanceResult
    changed_by: str


class _PersistExecutionLog(Protocol):
    def __call__(self, **kwargs: Unpack[_PersistExecutionLogOptions]) -> None: ...


class _TaskExecutionSubjectOptions(TypedDict):
    load_task: Callable[[], _TaskLike | None]
    load_sprint: Callable[[], _SprintLike | None]
    load_sprint_story: Callable[[_TaskLike], object | None]


class _TaskExecutionHistoryOptions(_TaskExecutionSubjectOptions):
    load_logs: Callable[[], Sequence[_TaskExecutionLogLike]]


class _TaskExecutionRecordOptions(_TaskExecutionHistoryOptions):
    new_status: TaskStatus | None
    outcome_summary: str | None
    artifact_refs: Sequence[str] | None
    notes: str | None
    acceptance_result: TaskAcceptanceResult | None
    changed_by: str | None
    parse_task_metadata: Callable[[object | None], _TaskMetadataLike]
    persist_execution_log: _PersistExecutionLog


def _load_task_execution_subject(
    *,
    project_id: int,
    load_task: Callable[[], _TaskLike | None],
    load_sprint: Callable[[], _SprintLike | None],
    load_sprint_story: Callable[[_TaskLike], object | None],
) -> tuple[_TaskLike, _SprintLike]:
    task: _TaskLike | None = load_task()
    if not task:
        raise TaskExecutionServiceError.task_not_found()

    sprint = load_sprint()
    if not sprint or getattr(sprint, "product_id", None) != project_id:
        raise TaskExecutionServiceError.sprint_not_in_project()

    sprint_story: object = load_sprint_story(task)
    if not sprint_story:
        raise TaskExecutionServiceError.task_not_in_sprint()

    return task, sprint


def _deserialize_artifact_refs(raw_value: object) -> list[str]:
    if not raw_value:
        return []
    with suppress(Exception):
        value: Any = json.loads(str(raw_value))
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
    return []


def _normalize_artifact_refs(raw_refs: Sequence[str] | None) -> str | None:
    if not raw_refs:
        return None

    refs: list[str] = []
    seen: set[str] = set()
    for ref in raw_refs:
        normalized: str = str(ref).strip()
        if normalized and normalized not in seen:
            refs.append(normalized)
            seen.add(normalized)
    return json.dumps(refs) if refs else None


def get_task_execution_history(
    *,
    project_id: int,
    sprint_id: int,
    task_id: int,
    **options: Unpack[_TaskExecutionHistoryOptions],
) -> dict[str, Any]:
    """Return the current task status together with its persisted execution history."""
    task, _sprint = _load_task_execution_subject(
        project_id=project_id,
        load_task=options["load_task"],
        load_sprint=options["load_sprint"],
        load_sprint_story=options["load_sprint_story"],
    )

    history: list[TaskExecutionLogEntry] = []
    for log in options["load_logs"]():
        if getattr(log, "log_id", None) is None:
            continue
        history.append(
            TaskExecutionLogEntry(
                log_id=log.log_id,
                task_id=log.task_id,
                sprint_id=log.sprint_id,
                old_status=log.old_status,
                new_status=log.new_status,
                outcome_summary=log.outcome_summary,
                artifact_refs=_deserialize_artifact_refs(
                    getattr(log, "artifact_refs_json", None)
                ),
                acceptance_result=log.acceptance_result,
                notes=log.notes,
                changed_by=log.changed_by,
                changed_at=log.changed_at,
            )
        )

    return {
        "success": True,
        "task_id": task_id,
        "sprint_id": sprint_id,
        "current_status": task.status,
        "latest_entry": history[0] if history else None,
        "history": history,
    }


def record_task_execution(
    *,
    project_id: int,
    sprint_id: int,
    task_id: int,
    **options: Unpack[_TaskExecutionRecordOptions],
) -> dict[str, Any]:
    """Persist a task execution update and return the refreshed execution history."""
    task, _sprint = _load_task_execution_subject(
        project_id=project_id,
        load_task=options["load_task"],
        load_sprint=options["load_sprint"],
        load_sprint_story=options["load_sprint_story"],
    )

    task_metadata = options["parse_task_metadata"](getattr(task, "metadata_json", None))
    if not getattr(task_metadata, "checklist_items", []):
        raise TaskExecutionServiceError.task_not_executable()

    old_status: TaskStatus = task.status
    if options["new_status"] is not None:
        task.status = options["new_status"]

    options["persist_execution_log"](
        task=task,
        old_status=old_status,
        new_status=task.status,
        outcome_summary=options["outcome_summary"],
        artifact_refs_json=_normalize_artifact_refs(options["artifact_refs"]),
        notes=options["notes"],
        acceptance_result=options["acceptance_result"]
        or TaskAcceptanceResult.NOT_CHECKED,
        changed_by=options["changed_by"] or "manual-ui",
    )

    return get_task_execution_history(
        project_id=project_id,
        sprint_id=sprint_id,
        task_id=task_id,
        load_task=options["load_task"],
        load_sprint=options["load_sprint"],
        load_sprint_story=options["load_sprint_story"],
        load_logs=options["load_logs"],
    )
