"""API tests for story close readiness and persistence behavior."""

from typing import TYPE_CHECKING, Any, Literal

import pytest
from sqlmodel import Session, select

from agile_sqlmodel import StoryCompletionLog, StoryStatus, Task, TaskStatus, UserStory
from tests.test_api_sprint_flow import (
    DummyProduct,
    _build_client,
    _seed_task_packet_context,
)
from utils.task_metadata import TaskMetadata, serialize_task_metadata

if TYPE_CHECKING:
    from httpx._models import Response

HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409


def test_story_close_flow(  # noqa: PLR0915
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story close flow enforces readiness, persists completion, and blocks rewrites."""
    client, repo, _ = _build_client(monkeypatch)

    project_id, sprint_id, story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
        task_metadata=TaskMetadata(
            task_kind="design",
            artifact_targets=["mock.py"],
            workstream_tags=["backend"],
            relevant_invariant_ids=[],
            checklist_items=["Implement the mock module", "Mark the task complete"],
        ),
    )

    reference_task = Task(
        description="Document the rollout notes",
        story_id=story_id,
        metadata_json=serialize_task_metadata(
            TaskMetadata(
                task_kind="documentation",
                artifact_targets=["release-notes.md"],
                workstream_tags=["docs"],
                relevant_invariant_ids=[],
                checklist_items=[],
            )
        ),
    )
    session.add(reference_task)
    session.commit()

    # 1. GET /close (Not all tasks done)
    resp: Response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close"
    )
    assert resp.status_code == HTTP_OK
    data = resp.json()
    assert data["close_eligible"] is False
    assert data["readiness"]["total_tasks"] == 1
    assert data["readiness"]["done_tasks"] == 0
    assert data["readiness"]["all_actionable_tasks_done"] is False

    # 2. POST /close (Fails because tasks are not done)
    resp: Response = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={
            "resolution": "Completed",
            "completion_notes": "Attempted close too early",
        },
    )
    assert resp.status_code == HTTP_CONFLICT
    assert (
        resp.json()["detail"]
        == "Cannot close a story unless all actionable tasks are Done or Cancelled."
    )

    # Mark the only task as done
    task: Task | None = session.get(Task, task_id)
    assert task is not None
    task.status: Literal[TaskStatus.DONE] = TaskStatus.DONE
    session.commit()

    # 3. GET /close (Eligible now)
    resp: Response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close"
    )
    assert resp.status_code == HTTP_OK
    data = resp.json()
    assert data["close_eligible"] is True
    assert data["readiness"]["total_tasks"] == 1
    assert data["readiness"]["done_tasks"] == 1
    assert data["readiness"]["all_actionable_tasks_done"] is True

    # 4. POST /close (Success)
    resp: Response = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={
            "resolution": "Completed",
            "completion_notes": "We are done!",
            "known_gaps": "Minor styling issue.",
            "evidence_links": ["pr-123"],
        },
    )
    assert resp.status_code == HTTP_OK
    data: Any = resp.json()
    assert data["current_status"] == StoryStatus.DONE.value
    assert data["resolution"] == "Completed"
    assert data["completion_notes"] == "We are done!"

    # Check DB state
    story: UserStory | None = session.get(UserStory, story_id)
    assert story is not None
    assert story.status == StoryStatus.DONE
    assert story.completion_notes == "We are done!"
    assert story.completed_at is not None

    log: StoryCompletionLog | None = session.exec(
        select(StoryCompletionLog).where(StoryCompletionLog.story_id == story_id)
    ).first()
    assert log is not None
    assert log.resolution is not None
    assert log.resolution.value == "Completed"
    assert log.delivered == "We are done!"
    assert log.known_gaps == "Minor styling issue."

    # 5. POST /close bounds check
    product2: DummyProduct = repo.create("Project 2")
    resp: Response = client.post(
        f"/api/projects/{product2.product_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={"resolution": "Completed", "completion_notes": "Hacking"},
    )
    assert resp.status_code == HTTP_NOT_FOUND

    # 6. GET /close on a Done story
    resp: Response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close"
    )
    assert resp.status_code == HTTP_OK
    assert resp.json()["close_eligible"] is False
    assert "already Done" in resp.json()["ineligible_reason"]

    # 7. POST /close on a Done story
    resp: Response = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={"resolution": "Completed", "completion_notes": "Attempting rewrite"},
    )
    assert resp.status_code == HTTP_CONFLICT
    assert "Cannot modify an already Done story" in resp.json()["detail"]


def test_story_close_rejects_stories_with_only_reference_tasks(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Story close remains blocked when a story only contains reference tasks."""
    client, repo, _ = _build_client(monkeypatch)

    project_id, sprint_id, story_id, _task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
        task_metadata=TaskMetadata(
            task_kind="documentation",
            artifact_targets=["runbook.md"],
            workstream_tags=["docs"],
            relevant_invariant_ids=[],
            checklist_items=[],
        ),
    )

    resp: Response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close"
    )
    assert resp.status_code == HTTP_OK
    data: Any = resp.json()
    assert data["close_eligible"] is False
    assert data["readiness"]["total_tasks"] == 0
    assert data["readiness"]["done_tasks"] == 0
    assert data["readiness"]["all_actionable_tasks_done"] is False
    assert data["ineligible_reason"] == "Story has no executable tasks."

    resp: Response = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={
            "resolution": "Completed",
            "completion_notes": "Attempted close without actionable work",
        },
    )
    assert resp.status_code == HTTP_CONFLICT
    assert resp.json()["detail"] == "Cannot close a story with no executable tasks."
