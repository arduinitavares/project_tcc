from types import SimpleNamespace

import pytest

from agile_sqlmodel import StoryResolution, StoryStatus
from services.story_close_service import (
    close_story,
    get_story_close_readiness,
    StoryCloseServiceError,
)


def test_get_story_close_readiness_marks_done_story_ineligible():
    story = SimpleNamespace(
        story_id=7,
        status=StoryStatus.DONE,
        resolution=StoryResolution.COMPLETED,
        completion_notes="Already finished",
        evidence_links='["pr-123"]',
        completed_at="2026-04-04T12:00:00Z",
    )
    sprint = SimpleNamespace(sprint_id=3, product_id=2)

    payload = get_story_close_readiness(
        project_id=2,
        sprint_id=3,
        story_id=7,
        load_story=lambda: story,
        load_sprint=lambda: sprint,
        load_sprint_story=lambda current_story: object(),
        load_tasks=lambda: [object()],
        task_progress=lambda tasks: (1, 1, 0, True),
    )

    assert payload["close_eligible"] is False
    assert payload["ineligible_reason"] == "Story is already Done."
    assert payload["current_status"] == StoryStatus.DONE.value


def test_get_story_close_readiness_reports_no_executable_tasks():
    story = SimpleNamespace(
        story_id=7,
        status=StoryStatus.TO_DO,
        resolution=None,
        completion_notes=None,
        evidence_links=None,
        completed_at=None,
    )
    sprint = SimpleNamespace(sprint_id=3, product_id=2)

    payload = get_story_close_readiness(
        project_id=2,
        sprint_id=3,
        story_id=7,
        load_story=lambda: story,
        load_sprint=lambda: sprint,
        load_sprint_story=lambda current_story: object(),
        load_tasks=lambda: [],
        task_progress=lambda tasks: (0, 0, 0, False),
    )

    assert payload["close_eligible"] is False
    assert payload["ineligible_reason"] == "Story has no executable tasks."
    assert payload["readiness"].total_tasks == 0


def test_close_story_rejects_incomplete_actionable_tasks():
    story = SimpleNamespace(
        story_id=7,
        status=StoryStatus.TO_DO,
        resolution=None,
        completion_notes=None,
        evidence_links=None,
        completed_at=None,
    )
    sprint = SimpleNamespace(sprint_id=3, product_id=2)

    with pytest.raises(StoryCloseServiceError) as exc_info:
        close_story(
            project_id=2,
            sprint_id=3,
            story_id=7,
            resolution=StoryResolution.COMPLETED,
            completion_notes="Attempted early close",
            evidence_links=["pr-123"],
            known_gaps=None,
            follow_up_notes=None,
            changed_by=None,
            now=lambda: "2026-04-04T12:00:00Z",
            load_story=lambda: story,
            load_sprint=lambda: sprint,
            load_sprint_story=lambda current_story: object(),
            load_tasks=lambda: [object()],
            task_progress=lambda tasks: (1, 0, 0, False),
            persist_story_close=lambda **kwargs: None,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == (
        "Cannot close a story unless all actionable tasks are Done or Cancelled."
    )


def test_close_story_marks_story_done_and_returns_payload():
    story = SimpleNamespace(
        story_id=7,
        status=StoryStatus.TO_DO,
        resolution=None,
        completion_notes=None,
        evidence_links=None,
        completed_at=None,
    )
    sprint = SimpleNamespace(sprint_id=3, product_id=2)
    persisted: dict[str, object] = {}

    payload = close_story(
        project_id=2,
        sprint_id=3,
        story_id=7,
        resolution=StoryResolution.COMPLETED,
        completion_notes="We are done!",
        evidence_links=["pr-123"],
        known_gaps="Minor styling issue.",
        follow_up_notes="Track polish separately.",
        changed_by=None,
        now=lambda: "2026-04-04T12:00:00Z",
        load_story=lambda: story,
        load_sprint=lambda: sprint,
        load_sprint_story=lambda current_story: object(),
        load_tasks=lambda: [object()],
        task_progress=lambda tasks: (1, 1, 0, True),
        persist_story_close=lambda **kwargs: persisted.update(kwargs),
    )

    assert story.status == StoryStatus.DONE
    assert story.resolution == StoryResolution.COMPLETED
    assert story.completion_notes == "We are done!"
    assert story.evidence_links == '["pr-123"]'
    assert story.completed_at == "2026-04-04T12:00:00Z"
    assert persisted["old_status"] == StoryStatus.TO_DO
    assert persisted["changed_by"] == "manual-ui"
    assert persisted["known_gaps"] == "Minor styling issue."
    assert persisted["follow_up_notes"] == "Track polish separately."
    assert payload["current_status"] == StoryStatus.DONE.value
    assert payload["resolution"] == StoryResolution.COMPLETED
    assert payload["close_eligible"] is False
    assert payload["ineligible_reason"] == "Story is already Done."
