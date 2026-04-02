import pytest
from types import SimpleNamespace
from httpx import AsyncClient
from sqlmodel import Session, select
from agile_sqlmodel import Task, TaskStatus

import api as api_module

def test_task_execution_flow(session, monkeypatch):
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
            checklist_items=["Implement the mock module", "Write the execution log"],
        ),
    )

    # 1. GET execution before any logs
    resp = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["current_status"] == "To Do"
    assert data["latest_entry"] is None
    assert len(data["history"]) == 0

    # 2. POST execution (Valid) -> Start task
    resp = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
        json={
            "new_status": "In Progress",
            "notes": "Starting work now."
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_status"] == "In Progress"
    assert len(data["history"]) == 1
    assert data["latest_entry"]["old_status"] == "To Do"
    assert data["latest_entry"]["new_status"] == "In Progress"
    assert data["latest_entry"]["notes"] == "Starting work now."

    # 3. POST execution (Invalid Done - missing summary)
    resp = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
        json={
            "new_status": "Done"
        }
    )
    assert resp.status_code == 422 # Pydantic model validation failure

    # 4. POST execution (Valid Done)
    resp = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
        json={
            "new_status": "Done",
            "outcome_summary": "Finished mock up.",
            "artifact_refs": ["file1.txt", "file2.txt"],
            "acceptance_result": "fully_met"
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_status"] == "Done"
    assert len(data["history"]) == 2
    assert data["latest_entry"]["new_status"] == "Done"
    assert data["latest_entry"]["acceptance_result"] == "fully_met"
    assert data["latest_entry"]["artifact_refs"] == ["file1.txt", "file2.txt"]

    # Verify atomic update
    task = session.get(Task, task_id)
    assert task.status.value == "Done"

    # 5. POST execution cross-project bounds check
    from agile_sqlmodel import Product
    product2 = repo.create(Product(name="Project 2"))
    resp = client.post(
        f"/api/projects/{product2.product_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
        json={"new_status": "To Do", "notes": "Hacking"}
    )
    assert resp.status_code == 404

    # 6. GET execution across sprints check
    from agile_sqlmodel import Sprint
    sprint2 = session.exec(select(Sprint).where(Sprint.sprint_id == sprint_id)).first()
    sprint2_clone = Sprint(
        product_id=project_id,
        team_id=sprint2.team_id,
        goal="Sprint 2",
        start_date=sprint2.start_date,
        end_date=sprint2.end_date
    )
    session.add(sprint2_clone)
    session.commit()
    
    from agile_sqlmodel import SprintStory
    session.add(SprintStory(sprint_id=sprint2_clone.sprint_id, story_id=story_id))
    session.commit()

    resp = client.get(f"/api/projects/{project_id}/sprints/{sprint2_clone.sprint_id}/tasks/{task_id}/execution")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["history"]) == 0  # Should not show Sprint 1 logs!


def test_task_execution_rejects_non_executable_tasks(session, monkeypatch):
    from tests.test_api_sprint_flow import _build_client, _seed_task_packet_context
    from utils.task_metadata import TaskMetadata

    client, repo, _ = _build_client(monkeypatch)

    project_id, sprint_id, _story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
        task_metadata=TaskMetadata(
            task_kind="documentation",
            artifact_targets=["design-notes.md"],
            workstream_tags=["docs"],
            relevant_invariant_ids=[],
            checklist_items=[],
        ),
    )

    resp = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
        json={
            "new_status": "In Progress",
            "notes": "Trying to run a reference-only task.",
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Task has no executable checklist items."


def test_get_task_execution_skips_logs_without_primary_key(monkeypatch):
    task = SimpleNamespace(task_id=7, story_id=11, status=TaskStatus.TO_DO)
    sprint = SimpleNamespace(sprint_id=3, product_id=2)
    sprint_story = SimpleNamespace(sprint_id=3, story_id=11)
    malformed_log = SimpleNamespace(
        log_id=None,
        task_id=7,
        sprint_id=3,
        old_status="To Do",
        new_status="In Progress",
        outcome_summary=None,
        artifact_refs_json=None,
        acceptance_result="not_checked",
        notes="broken row",
        changed_by="tester",
        changed_at="2026-03-31T00:00:00Z",
    )

    class _FakeExecResult:
        def __init__(self, payload):
            self._payload = payload

        def first(self):
            return self._payload

        def all(self):
            return self._payload

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, model, key):
            if model is api_module.Task and key == 7:
                return task
            if model is api_module.Sprint and key == 3:
                return sprint
            return None

        def exec(self, statement):
            sql = str(statement)
            if "FROM sprint_stories" in sql:
                return _FakeExecResult(sprint_story)
            if "FROM task_execution_logs" in sql:
                return _FakeExecResult([malformed_log])
            raise AssertionError(f"Unexpected statement: {sql}")

    monkeypatch.setattr(api_module, "Session", lambda _engine: _FakeSession())
    monkeypatch.setattr(api_module, "get_engine", lambda: object())

    response = api_module.get_task_execution(project_id=2, sprint_id=3, task_id=7)

    assert response.success is True
    assert response.history == []
    assert response.latest_entry is None
