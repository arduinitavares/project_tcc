from datetime import datetime, timezone

from sqlmodel import select

from agile_sqlmodel import Sprint, SprintStatus, StoryStatus, UserStory, WorkflowEvent, WorkflowEventType


def test_get_sprint_close_returns_guidance_for_non_active_sprint(session, monkeypatch):
    from tests.test_api_sprint_flow import _build_client, _seed_saved_sprint

    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=False,
        created_title="Planned Sprint",
    )

    response = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}/close")

    assert response.status_code == 200
    payload = response.json()
    assert payload["close_eligible"] is False
    assert payload["ineligible_reason"] == "Only active sprints can be closed."
    assert payload["history_fidelity"] == "derived"


def test_post_sprint_close_persists_snapshot_and_completion_event(session, monkeypatch):
    from tests.test_api_sprint_flow import _build_client, _seed_saved_sprint

    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=True,
        created_title="Closable Sprint",
    )

    story = session.exec(select(UserStory).where(UserStory.product_id == project_id)).first()
    assert story is not None
    story.status = StoryStatus.DONE
    story.completed_at = datetime.now(timezone.utc)
    session.add(story)
    session.commit()

    response = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/close",
        json={
            "completion_notes": "Closed after review.",
            "follow_up_notes": "Carry remaining backlog forward manually.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_status"] == SprintStatus.COMPLETED.value
    assert payload["close_eligible"] is False
    assert payload["ineligible_reason"] == "Sprint is already completed."
    assert payload["history_fidelity"] == "snapshotted"
    assert payload["close_snapshot"]["completion_notes"] == "Closed after review."
    assert payload["close_snapshot"]["follow_up_notes"] == "Carry remaining backlog forward manually."

    sprint = session.get(Sprint, sprint_id)
    assert sprint is not None
    assert sprint.status == SprintStatus.COMPLETED
    assert sprint.completed_at is not None
    assert sprint.close_snapshot_json is not None

    event = session.exec(
        select(WorkflowEvent).where(
            WorkflowEvent.event_type == WorkflowEventType.SPRINT_COMPLETED
        )
    ).first()
    assert event is not None

    detail_response = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["data"]["sprint"]
    assert detail_payload["history_fidelity"] == "snapshotted"
    assert detail_payload["close_snapshot"]["completion_notes"] == "Closed after review."
