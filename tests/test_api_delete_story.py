import uuid
from datetime import datetime, timezone

import httpx
import pytest
from httpx import AsyncClient
from sqlmodel import Session, select

from agile_sqlmodel import (
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    StoryCompletionLog,
    StoryStatus,
    Task,
    TaskExecutionLog,
    TaskStatus,
    Team,
    UserStory,
)
from api import app


@pytest.fixture
def setup_test_data(session: Session):
    # Create product
    product = Product(name=f"Test Product {uuid.uuid4()}", description="Test")
    session.add(product)
    session.commit()
    session.refresh(product)

    # Create unique team
    team = Team(name=f"Test Team {uuid.uuid4()}")
    session.add(team)
    session.commit()
    session.refresh(team)

    # Create Sprints
    sprints = []
    now = datetime.now(timezone.utc)
    for _ in range(2):
        s = Sprint(
            product_id=product.product_id,
            team_id=team.team_id,
            start_date=now,
            end_date=now,
            status=SprintStatus.PLANNED,
        )
        session.add(s)
        sprints.append(s)
    session.commit()
    for s in sprints:
        session.refresh(s)

    parent_req = f"test-req-{uuid.uuid4()}"

    stories = []
    sprint_mappings = []
    logs = []
    tasks = []
    task_execution_logs = []

    # Create Stories
    for i in range(3):
        story = UserStory(
            product_id=product.product_id,
            title=f"Test Story {i}",
            source_requirement=parent_req,
            status=StoryStatus.TO_DO,
        )
        stories.append(story)

    session.add_all(stories)
    session.commit()
    for s in stories:
        session.refresh(s)

    # Create Mappings, Logs, Tasks, and Task Execution Logs
    for story in stories:
        for s in sprints:
            sm = SprintStory(sprint_id=s.sprint_id, story_id=story.story_id)
            sprint_mappings.append(sm)

        for _ in range(2):
            log = StoryCompletionLog(
                story_id=story.story_id,
                old_status=StoryStatus.TO_DO,
                new_status=StoryStatus.IN_PROGRESS,
            )
            logs.append(log)

        for _ in range(3):
            t = Task(
                story_id=story.story_id,
                description="Task",
                status=TaskStatus.TO_DO,
            )
            tasks.append(t)

    session.add_all(sprint_mappings)
    session.add_all(logs)
    session.add_all(tasks)
    session.commit()
    for t in tasks:
        session.refresh(t)

    # Add Task Execution Logs for tasks
    for t in tasks:
        t_log = TaskExecutionLog(
            task_id=t.task_id,
            sprint_id=sprints[0].sprint_id,
            new_status=TaskStatus.IN_PROGRESS,
        )
        task_execution_logs.append(t_log)

    session.add_all(task_execution_logs)
    session.commit()

    return (
        product.product_id,
        parent_req,
        [s.story_id for s in stories],
        [t.task_id for t in tasks],
    )


@pytest.mark.asyncio
async def test_delete_project_story(
    session: Session, setup_test_data, monkeypatch, engine
):
    import api as api_module

    monkeypatch.setattr(api_module, "get_engine", lambda: engine)
    monkeypatch.setattr(
        api_module.product_repo, "_get_session", lambda: session
    )
    monkeypatch.setattr("agile_sqlmodel.get_engine", lambda: engine)

    product_id, parent_req, story_ids, task_ids = setup_test_data

    # 1. Seed session state data to ensure cleanup works
    str(product_id)

    # Mock _ensure_session and _save_session_state for easier verification
    mock_state = {
        "story_saved": {parent_req: True},
        "story_outputs": {parent_req: {"data": "some artifact"}},
        "story_attempts": {
            parent_req: [
                {
                    "created_at": "2026-03-28T10:00:00Z",
                    "trigger": "manual_refine",
                    "input_context": {},
                    "output_artifact": {"data": "some artifact"},
                    "is_complete": True,
                    "failure_artifact_id": None,
                    "failure_stage": None,
                    "failure_summary": None,
                    "raw_output_preview": None,
                    "has_full_artifact": False,
                }
            ]
        },
        "interview_runtime": {
            "story": {
                parent_req: {
                    "phase": "story",
                    "subject_key": parent_req,
                    "attempt_history": [
                        {
                            "attempt_id": "attempt-1",
                            "created_at": "2026-03-28T10:00:00Z",
                            "trigger": "manual_refine",
                            "request_snapshot_id": "request-1",
                            "draft_basis_attempt_id": None,
                            "included_feedback_ids": ["feedback-1"],
                            "classification": "reusable_content_result",
                            "is_reusable": True,
                            "retryable": False,
                            "draft_kind": "complete_draft",
                            "output_artifact": {
                                "data": "some artifact",
                                "is_complete": True,
                            },
                            "failure_artifact_id": None,
                            "failure_stage": None,
                            "failure_summary": None,
                            "raw_output_preview": None,
                            "has_full_artifact": False,
                        }
                    ],
                    "draft_projection": {
                        "latest_reusable_attempt_id": "attempt-1",
                        "kind": "complete_draft",
                        "is_complete": True,
                        "updated_at": "2026-03-28T10:00:00Z",
                    },
                    "feedback_projection": {
                        "items": [
                            {
                                "feedback_id": "feedback-1",
                                "text": "keep it smaller",
                                "created_at": "2026-03-28T09:59:00Z",
                                "status": "absorbed",
                                "absorbed_by_attempt_id": "attempt-1",
                            }
                        ],
                        "next_feedback_sequence": 1,
                    },
                    "request_projection": {
                        "request_snapshot_id": "request-1",
                        "payload": {"parent_requirement": parent_req},
                        "request_hash": "hash-1",
                        "created_at": "2026-03-28T10:00:00Z",
                        "draft_basis_attempt_id": None,
                        "included_feedback_ids": ["feedback-1"],
                        "context_version": "story-runtime.v1",
                    },
                }
            }
        },
        "another_req": "should not be touched",
    }

    saved_state_calls = []

    async def mock_ensure_session(sid):
        return mock_state

    def mock_save_session_state(sid, state):
        saved_state_calls.append(state.copy())

    monkeypatch.setattr(api_module, "_ensure_session", mock_ensure_session)
    monkeypatch.setattr(
        api_module, "_save_session_state", mock_save_session_state
    )

    # Assert data exists before deletion
    assert len(
        session.exec(
            select(UserStory).where(UserStory.story_id.in_(story_ids))
        ).all()
    ) == len(story_ids)
    assert (
        len(
            session.exec(
                select(SprintStory).where(SprintStory.story_id.in_(story_ids))
            ).all()
        )
        > 0
    )
    assert (
        len(
            session.exec(
                select(StoryCompletionLog).where(
                    StoryCompletionLog.story_id.in_(story_ids)
                )
            ).all()
        )
        > 0
    )
    assert len(
        session.exec(select(Task).where(Task.story_id.in_(story_ids))).all()
    ) == len(task_ids)
    assert (
        len(
            session.exec(
                select(TaskExecutionLog).where(
                    TaskExecutionLog.task_id.in_(task_ids)
                )
            ).all()
        )
        > 0
    )

    # Invoke the API
    async with AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(
            f"/api/projects/{product_id}/story",
            params={"parent_requirement": parent_req},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Assert data is completely removed
    assert (
        len(
            session.exec(
                select(UserStory).where(UserStory.story_id.in_(story_ids))
            ).all()
        )
        == 0
    )
    assert (
        len(
            session.exec(
                select(SprintStory).where(SprintStory.story_id.in_(story_ids))
            ).all()
        )
        == 0
    )
    assert (
        len(
            session.exec(
                select(StoryCompletionLog).where(
                    StoryCompletionLog.story_id.in_(story_ids)
                )
            ).all()
        )
        == 0
    )
    assert (
        len(
            session.exec(
                select(Task).where(Task.story_id.in_(story_ids))
            ).all()
        )
        == 0
    )
    assert (
        len(
            session.exec(
                select(TaskExecutionLog).where(
                    TaskExecutionLog.task_id.in_(task_ids)
                )
            ).all()
        )
        == 0
    )

    # Assert session state was cleaned up properly
    assert len(saved_state_calls) == 1
    final_state = saved_state_calls[0]

    assert parent_req not in final_state["story_saved"]
    assert parent_req not in final_state["story_outputs"]
    assert len(final_state["story_attempts"][parent_req]) == 1
    assert final_state["story_attempts"][parent_req][0]["trigger"] == "manual_refine"

    runtime = final_state["interview_runtime"]["story"][parent_req]
    assert runtime["draft_projection"] == {}
    assert runtime["request_projection"] == {}
    assert runtime["feedback_projection"]["items"] == []
    assert len(runtime["attempt_history"]) == 2
    reset_attempt = runtime["attempt_history"][-1]
    assert reset_attempt["trigger"] == "reset"
    assert reset_attempt["classification"] == "reset_marker"
    assert "state reset by user" in reset_attempt["summary"]
    assert "another_req" in final_state
