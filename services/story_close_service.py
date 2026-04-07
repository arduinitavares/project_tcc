"""Story close endpoint orchestration helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from typing import Any

from models.enums import StoryStatus
from utils.api_schemas import StoryTaskProgressSummary


class StoryCloseServiceError(Exception):
    """Domain-level story close error for router translation."""

    def __init__(self, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _load_story_close_subject(
    *,
    project_id: int,
    load_story: Callable[[], Any | None],
    load_sprint: Callable[[], Any | None],
    load_sprint_story: Callable[[Any], Any | None],
) -> tuple[Any, Any]:
    story = load_story()
    if not story:
        raise StoryCloseServiceError("Story not found", status_code=404)

    sprint = load_sprint()
    if not sprint or getattr(sprint, "product_id", None) != project_id:
        raise StoryCloseServiceError(
            "Sprint not found in this project",
            status_code=404,
        )

    sprint_story = load_sprint_story(story)
    if not sprint_story:
        raise StoryCloseServiceError(
            "Story does not belong to the given sprint",
            status_code=404,
        )

    return story, sprint


def _build_readiness_summary(
    *,
    tasks: Sequence[Any],
    task_progress: Callable[[Sequence[Any]], tuple[int, int, int, bool]],
) -> StoryTaskProgressSummary:
    total_tasks, done_tasks, cancelled_tasks, all_actionable_done = task_progress(
        tasks
    )
    return StoryTaskProgressSummary(
        total_tasks=total_tasks,
        done_tasks=done_tasks,
        cancelled_tasks=cancelled_tasks,
        all_actionable_tasks_done=all_actionable_done,
    )


def get_story_close_readiness(
    *,
    project_id: int,
    sprint_id: int,
    story_id: int,
    load_story: Callable[[], Any | None],
    load_sprint: Callable[[], Any | None],
    load_sprint_story: Callable[[Any], Any | None],
    load_tasks: Callable[[], Sequence[Any]],
    task_progress: Callable[[Sequence[Any]], tuple[int, int, int, bool]],
) -> dict[str, Any]:
    story, _sprint = _load_story_close_subject(
        project_id=project_id,
        load_story=load_story,
        load_sprint=load_sprint,
        load_sprint_story=load_sprint_story,
    )

    readiness = _build_readiness_summary(
        tasks=load_tasks(),
        task_progress=task_progress,
    )

    close_eligible = readiness.all_actionable_tasks_done
    ineligible_reason = (
        None
        if close_eligible
        else "Not all actionable tasks are completed or cancelled."
    )
    if readiness.total_tasks == 0:
        close_eligible = False
        ineligible_reason = "Story has no executable tasks."

    if story.status in (StoryStatus.ACCEPTED, StoryStatus.DONE):
        close_eligible = False
        ineligible_reason = f"Story is already {story.status.value}."

    return {
        "success": True,
        "story_id": story_id,
        "sprint_id": sprint_id,
        "current_status": story.status.value,
        "resolution": getattr(story, "resolution", None),
        "completion_notes": getattr(story, "completion_notes", None),
        "evidence_links": getattr(story, "evidence_links", None),
        "completed_at": getattr(story, "completed_at", None),
        "readiness": readiness,
        "close_eligible": close_eligible,
        "ineligible_reason": ineligible_reason,
    }


def close_story(
    *,
    project_id: int,
    sprint_id: int,
    story_id: int,
    resolution: Any,
    completion_notes: str,
    evidence_links: Sequence[str] | None,
    known_gaps: str | None,
    follow_up_notes: str | None,
    changed_by: str | None,
    now: Callable[[], Any],
    load_story: Callable[[], Any | None],
    load_sprint: Callable[[], Any | None],
    load_sprint_story: Callable[[Any], Any | None],
    load_tasks: Callable[[], Sequence[Any]],
    task_progress: Callable[[Sequence[Any]], tuple[int, int, int, bool]],
    persist_story_close: Callable[..., None],
) -> dict[str, Any]:
    story, _sprint = _load_story_close_subject(
        project_id=project_id,
        load_story=load_story,
        load_sprint=load_sprint,
        load_sprint_story=load_sprint_story,
    )

    readiness = _build_readiness_summary(
        tasks=load_tasks(),
        task_progress=task_progress,
    )

    if readiness.total_tasks == 0:
        raise StoryCloseServiceError(
            "Cannot close a story with no executable tasks.",
            status_code=409,
        )

    if not readiness.all_actionable_tasks_done:
        raise StoryCloseServiceError(
            "Cannot close a story unless all actionable tasks are Done or Cancelled.",
            status_code=409,
        )

    old_status = story.status
    if old_status in (StoryStatus.ACCEPTED, StoryStatus.DONE):
        raise StoryCloseServiceError(
            f"Cannot modify an already {old_status.value} story.",
            status_code=409,
        )

    evidence_json = json.dumps(list(evidence_links)) if evidence_links else None

    story.status = StoryStatus.DONE
    story.resolution = resolution
    story.completion_notes = completion_notes
    story.evidence_links = evidence_json
    story.completed_at = now()

    persist_story_close(
        story=story,
        old_status=old_status,
        evidence_json=evidence_json,
        known_gaps=known_gaps,
        follow_up_notes=follow_up_notes,
        changed_by=changed_by or "manual-ui",
    )

    return {
        "success": True,
        "story_id": story_id,
        "sprint_id": sprint_id,
        "current_status": story.status.value,
        "resolution": story.resolution,
        "completion_notes": story.completion_notes,
        "evidence_links": story.evidence_links,
        "completed_at": story.completed_at,
        "readiness": readiness,
        "close_eligible": False,
        "ineligible_reason": f"Story is already {story.status.value}.",
    }
