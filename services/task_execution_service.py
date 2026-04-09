"""Task execution endpoint orchestration helpers."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any

from models.enums import TaskAcceptanceResult
from utils.api_schemas import TaskExecutionLogEntry


class TaskExecutionServiceError(Exception):
    """Domain-level task execution error for router translation."""

    def __init__(self, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _load_task_execution_subject(
    *,
    project_id: int,
    load_task: Callable[[], Any | None],
    load_sprint: Callable[[], Any | None],
    load_sprint_story: Callable[[Any], Any | None],
) -> tuple[Any, Any]:
    task = load_task()
    if not task:
        raise TaskExecutionServiceError("Task not found", status_code=404)

    sprint = load_sprint()
    if not sprint or getattr(sprint, "product_id", None) != project_id:
        raise TaskExecutionServiceError(
            "Sprint not found in this project",
            status_code=404,
        )

    sprint_story = load_sprint_story(task)
    if not sprint_story:
        raise TaskExecutionServiceError(
            "Task does not belong to the given sprint",
            status_code=404,
        )

    return task, sprint


def _deserialize_artifact_refs(raw_value: object) -> list[str]:
    if not raw_value:
        return []
    with suppress(Exception):
        value = json.loads(str(raw_value))
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
    return []


def _normalize_artifact_refs(raw_refs: Sequence[str] | None) -> str | None:
    if not raw_refs:
        return None

    refs: list[str] = []
    seen: set[str] = set()
    for ref in raw_refs:
        normalized = str(ref).strip()
        if normalized and normalized not in seen:
            refs.append(normalized)
            seen.add(normalized)
    return json.dumps(refs) if refs else None


def get_task_execution_history(
    *,
    project_id: int,
    sprint_id: int,
    task_id: int,
    load_task: Callable[[], Any | None],
    load_sprint: Callable[[], Any | None],
    load_sprint_story: Callable[[Any], Any | None],
    load_logs: Callable[[], Sequence[Any]],
) -> dict[str, Any]:
    task, _sprint = _load_task_execution_subject(
        project_id=project_id,
        load_task=load_task,
        load_sprint=load_sprint,
        load_sprint_story=load_sprint_story,
    )

    history: list[TaskExecutionLogEntry] = []
    for log in load_logs():
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
    new_status: Any | None,
    outcome_summary: str | None,
    artifact_refs: Sequence[str] | None,
    notes: str | None,
    acceptance_result: Any | None,
    changed_by: str | None,
    load_task: Callable[[], Any | None],
    load_sprint: Callable[[], Any | None],
    load_sprint_story: Callable[[Any], Any | None],
    load_logs: Callable[[], Sequence[Any]],
    parse_task_metadata: Callable[[Any], Any],
    persist_execution_log: Callable[..., None],
) -> dict[str, Any]:
    task, _sprint = _load_task_execution_subject(
        project_id=project_id,
        load_task=load_task,
        load_sprint=load_sprint,
        load_sprint_story=load_sprint_story,
    )

    task_metadata = parse_task_metadata(getattr(task, "metadata_json", None))
    if not getattr(task_metadata, "checklist_items", []):
        raise TaskExecutionServiceError(
            "Task has no executable checklist items.",
            status_code=409,
        )

    old_status = task.status
    if new_status is not None:
        task.status = new_status

    persist_execution_log(
        task=task,
        old_status=old_status,
        new_status=task.status,
        outcome_summary=outcome_summary,
        artifact_refs_json=_normalize_artifact_refs(artifact_refs),
        notes=notes,
        acceptance_result=acceptance_result
        or TaskAcceptanceResult.NOT_CHECKED,
        changed_by=changed_by or "manual-ui",
    )

    return get_task_execution_history(
        project_id=project_id,
        sprint_id=sprint_id,
        task_id=task_id,
        load_task=load_task,
        load_sprint=load_sprint,
        load_sprint_story=load_sprint_story,
        load_logs=load_logs,
    )
