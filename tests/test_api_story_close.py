import pytest
from httpx import AsyncClient
from sqlmodel import Session, select
from agile_sqlmodel import UserStory, StoryStatus, StoryCompletionLog, Task, TaskStatus

def test_story_close_flow(session: Session, monkeypatch):
    from tests.test_api_sprint_flow import _build_client, _seed_task_packet_context
    from utils.task_metadata import TaskMetadata

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
        ),
    )

    # 1. GET /close (Not all tasks done)
    resp = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close")
    assert resp.status_code == 200
    data = resp.json()
    assert data["close_eligible"] is False
    assert data["readiness"]["total_tasks"] == 1
    assert data["readiness"]["done_tasks"] == 0
    assert data["readiness"]["all_actionable_tasks_done"] is False

    # 2. POST /close (Fails because tasks are not done)
    resp = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={
            "resolution": "Completed",
            "completion_notes": "Attempted close too early"
        }
    )
    assert resp.status_code == 409
    assert "Cannot close a story unless all tasks are Done" in resp.json()["detail"]

    # Mark the only task as done
    task = session.get(Task, task_id)
    task.status = TaskStatus.DONE
    session.commit()

    # 3. GET /close (Eligible now)
    resp = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close")
    assert resp.status_code == 200
    data = resp.json()
    assert data["close_eligible"] is True
    assert data["readiness"]["total_tasks"] == 1
    assert data["readiness"]["done_tasks"] == 1
    assert data["readiness"]["all_actionable_tasks_done"] is True

    # 4. POST /close (Success)
    resp = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={
            "resolution": "Completed",
            "completion_notes": "We are done!",
            "known_gaps": "Minor styling issue.",
            "evidence_links": ["pr-123"]
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_status"] == StoryStatus.DONE.value
    assert data["resolution"] == "Completed"
    assert data["completion_notes"] == "We are done!"
    
    # Check DB state
    story = session.get(UserStory, story_id)
    assert story.status == StoryStatus.DONE
    assert story.completion_notes == "We are done!"
    assert story.completed_at is not None

    log = session.exec(select(StoryCompletionLog).where(StoryCompletionLog.story_id == story_id)).first()
    assert log is not None
    assert log.resolution.value == "Completed"
    assert log.delivered == "We are done!"
    assert log.known_gaps == "Minor styling issue."

    # 5. POST /close bounds check
    from agile_sqlmodel import Product
    product2 = repo.create(Product(name="Project 2"))
    resp = client.post(
        f"/api/projects/{product2.product_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={"resolution": "Completed", "completion_notes": "Hacking"}
    )
    assert resp.status_code == 404

    # 6. GET /close on a Done story
    resp = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close")
    assert resp.status_code == 200
    assert resp.json()["close_eligible"] is False
    assert "already Done" in resp.json()["ineligible_reason"]

    # 7. POST /close on a Done story
    resp = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        json={"resolution": "Completed", "completion_notes": "Attempting rewrite"}
    )
    assert resp.status_code == 409
    assert "Cannot modify an already Done story" in resp.json()["detail"]
