"""API tests for sprint setup, candidates, and generation flow."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional

from fastapi.testclient import TestClient
from sqlmodel import select

from agile_sqlmodel import (
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    Team,
    UserStory,
    WorkflowEvent,
    WorkflowEventType,
)

import api as api_module


@dataclass
class DummyProduct:
    product_id: int
    name: str
    description: Optional[str] = None
    vision: Optional[str] = None
    spec_file_path: Optional[str] = None
    compiled_authority_json: Optional[str] = None


class DummyProductRepository:
    def __init__(self) -> None:
        self.products = []

    def get_all(self):
        return list(self.products)

    def get_by_id(self, product_id: int):
        for product in self.products:
            if product.product_id == product_id:
                return product
        return None

    def create(self, name: str, description: Optional[str] = None):
        product = DummyProduct(
            product_id=len(self.products) + 1,
            name=name,
            description=description,
        )
        self.products.append(product)
        return product


class DummyWorkflowService:
    def __init__(self) -> None:
        self.states: Dict[str, Dict[str, object]] = {}

    async def initialize_session(self, session_id: Optional[str] = None) -> str:
        sid = str(session_id or "generated")
        self.states[sid] = {"fsm_state": "SETUP_REQUIRED"}
        return sid

    def get_session_status(self, session_id: str):
        return dict(self.states.get(str(session_id), {}))

    def update_session_status(self, session_id: str, partial_update):
        sid = str(session_id)
        current = dict(self.states.get(sid, {}))
        current.update(partial_update)
        self.states[sid] = current

    def migrate_legacy_setup_state(self) -> int:
        return 0


def _build_client(monkeypatch):
    repo = DummyProductRepository()
    workflow = DummyWorkflowService()

    monkeypatch.setattr(api_module, "product_repo", repo)
    monkeypatch.setattr(api_module, "workflow_service", workflow)

    return TestClient(api_module.app), repo, workflow


def _seed_story_phase_project(repo: DummyProductRepository, workflow: DummyWorkflowService) -> int:
    product = repo.create("Sprint Project")
    product.spec_file_path = __file__
    product.compiled_authority_json = '{"ok": true}'
    workflow.states[str(product.product_id)] = {
        "fsm_state": "STORY_PERSISTENCE",
        "roadmap_releases": [
            {
                "release_name": "Release 1",
                "items": ["Enable login"],
            }
        ],
        "story_saved": {"Enable login": True},
    }
    return product.product_id


def _seed_sprint_setup_project(repo: DummyProductRepository, workflow: DummyWorkflowService) -> int:
    product = repo.create("Sprint Project")
    product.spec_file_path = __file__
    product.compiled_authority_json = '{"ok": true}'
    workflow.states[str(product.product_id)] = {
        "fsm_state": "SPRINT_SETUP",
    }
    return product.product_id


def _build_sprint_assessment(*, is_complete: bool = True) -> Dict[str, Any]:
    return {
        "sprint_goal": "Persist event deltas safely",
        "sprint_number": 1,
        "duration_days": 14,
        "selected_stories": [],
        "deselected_stories": [],
        "capacity_analysis": {
            "velocity_assumption": "Medium",
            "capacity_band": "4-5 stories",
            "selected_count": 0,
            "story_points_used": 0,
            "max_story_points": 13,
            "commitment_note": "Does this scope feel achievable in 2 weeks?",
            "reasoning": "Fits the chosen capacity.",
        },
        "is_complete": is_complete,
    }


def _seed_sprint_draft_project(
    repo: DummyProductRepository,
    workflow: DummyWorkflowService,
    *,
    is_complete: bool = True,
) -> int:
    product = repo.create("Sprint Draft Project")
    product.spec_file_path = __file__
    product.compiled_authority_json = '{"ok": true}'
    workflow.states[str(product.product_id)] = {
        "fsm_state": "SPRINT_DRAFT",
        "sprint_plan_assessment": _build_sprint_assessment(is_complete=is_complete),
    }
    return product.product_id


def _seed_saved_sprint(
    session,
    repo: DummyProductRepository,
    *,
    started: bool,
    created_title: str,
) -> tuple[int, int]:
    product = repo.create(created_title)
    session.add(Product(product_id=product.product_id, name=product.name))

    team = Team(name=f"Team {product.product_id}")
    session.add(team)
    session.flush()

    story = UserStory(
        product_id=product.product_id,
        title=f"{created_title} Story",
        story_description="As a user, I want saved sprint coverage",
        acceptance_criteria="- AC",
    )
    session.add(story)
    session.flush()

    sprint = Sprint(
        goal=f"{created_title} Goal",
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 15),
        status=SprintStatus.ACTIVE if started else SprintStatus.PLANNED,
        started_at=(
            datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc) if started else None
        ),
        product_id=product.product_id,
        team_id=team.team_id,
    )
    session.add(sprint)
    session.flush()

    session.add(SprintStory(sprint_id=sprint.sprint_id, story_id=story.story_id))
    session.commit()

    return product.product_id, sprint.sprint_id


def test_complete_story_phase_moves_to_sprint_setup(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_story_phase_project(repo, workflow)

    response = client.post(f"/api/projects/{project_id}/story/complete_phase")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["fsm_state"] == "SPRINT_SETUP"
    assert workflow.states[str(project_id)]["fsm_state"] == "SPRINT_SETUP"


def test_sprint_candidates_endpoint_returns_normalized_items(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_setup_project(repo, workflow)

    monkeypatch.setattr(
        api_module,
        "load_sprint_candidates",
        lambda project_id: {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "persona": "Reviewer",
                    "story_origin": "refined",
                }
            ],
            "excluded_counts": {"non_refined": 1, "superseded": 0},
            "message": "Found 1 sprint candidate.",
        },
    )

    response = client.get(f"/api/projects/{project_id}/sprint/candidates")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["count"] == 1
    assert payload["data"]["items"][0]["story_title"] == "Event Delta Persistence"
    assert payload["data"]["excluded_counts"]["non_refined"] == 1


def test_sprint_generate_rejects_numeric_velocity_request(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_setup_project(repo, workflow)

    response = client.post(
        f"/api/projects/{project_id}/sprint/generate",
        json={
            "team_velocity_assumption": 40,
            "sprint_duration_days": 14,
            "include_task_decomposition": True,
        },
    )

    assert response.status_code == 422


def test_sprint_generate_failure_stays_in_setup_and_records_attempt(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_setup_project(repo, workflow)

    async def fake_run_sprint_agent_from_state(
        state,
        *,
        project_id,
        team_velocity_assumption,
        sprint_duration_days,
        max_story_points,
        include_task_decomposition,
        selected_story_ids,
        user_input,
    ):
        return {
            "success": False,
            "input_context": {
                "available_stories": [],
                "team_velocity_assumption": team_velocity_assumption,
            },
            "output_artifact": {
                "error": "SPRINT_GENERATION_FAILED",
                "message": "No eligible stories.",
                "is_complete": False,
            },
            "is_complete": None,
            "error": "No eligible stories.",
        }

    monkeypatch.setattr(api_module, "run_sprint_agent_from_state", fake_run_sprint_agent_from_state)

    response = client.post(
        f"/api/projects/{project_id}/sprint/generate",
        json={
            "team_velocity_assumption": "Medium",
            "sprint_duration_days": 14,
            "include_task_decomposition": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["is_complete"] is False
    assert payload["data"]["fsm_state"] == "SPRINT_SETUP"
    assert workflow.states[str(project_id)]["fsm_state"] == "SPRINT_SETUP"
    attempts = workflow.states[str(project_id)]["sprint_attempts"]
    assert isinstance(attempts, list)
    assert len(attempts) == 1
    assert attempts[0]["output_artifact"]["error"] == "SPRINT_GENERATION_FAILED"


def test_sprint_generate_success_moves_to_draft_and_marks_assessment_complete(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_setup_project(repo, workflow)
    captured: Dict[str, Any] = {}

    async def fake_run_sprint_agent_from_state(
        state,
        *,
        project_id,
        team_velocity_assumption,
        sprint_duration_days,
        max_story_points,
        include_task_decomposition,
        selected_story_ids,
        user_input,
    ):
        captured["selected_story_ids"] = selected_story_ids
        captured["team_velocity_assumption"] = team_velocity_assumption
        return {
            "success": True,
            "input_context": {
                "available_stories": [
                    {
                        "story_id": 12,
                        "story_title": "Event Delta Persistence",
                        "priority": 2,
                        "story_points": 3,
                    }
                ],
                "team_velocity_assumption": team_velocity_assumption,
                "sprint_duration_days": sprint_duration_days,
            },
            "output_artifact": {
                "sprint_goal": "Persist event deltas safely",
                "sprint_number": 1,
                "duration_days": 14,
                "selected_stories": [],
                "deselected_stories": [],
                "capacity_analysis": {
                    "velocity_assumption": team_velocity_assumption,
                    "capacity_band": "4-5 stories",
                    "selected_count": 0,
                    "story_points_used": 0,
                    "max_story_points": max_story_points,
                    "commitment_note": "Does this scope feel achievable in 2 weeks?",
                    "reasoning": "Fits the chosen capacity.",
                },
                "is_complete": True,
            },
            "is_complete": True,
            "error": None,
        }

    monkeypatch.setattr(api_module, "run_sprint_agent_from_state", fake_run_sprint_agent_from_state)

    response = client.post(
        f"/api/projects/{project_id}/sprint/generate",
        json={
            "team_velocity_assumption": "High",
            "sprint_duration_days": 14,
            "max_story_points": 13,
            "include_task_decomposition": False,
            "selected_story_ids": [12],
            "user_input": "Focus on persistence",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["is_complete"] is True
    assert payload["data"]["fsm_state"] == "SPRINT_DRAFT"
    assert workflow.states[str(project_id)]["fsm_state"] == "SPRINT_DRAFT"
    assert workflow.states[str(project_id)]["sprint_plan_assessment"]["is_complete"] is True
    assert captured["selected_story_ids"] == [12]
    assert captured["team_velocity_assumption"] == "High"


def test_sprint_save_sanitizes_assessment_and_uses_tool_contract(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_draft_project(repo, workflow)
    hydrated_context = SimpleNamespace(state={"preserved": True}, session_id=str(project_id))
    captured: Dict[str, Any] = {}

    async def fake_hydrate_context(session_id: str, project_id: int):
        assert session_id == str(project_id)
        return hydrated_context

    def fake_save_sprint_plan_tool(input_data, tool_context):
        captured["input_data"] = input_data
        captured["tool_context"] = tool_context
        return {"success": True, "sprint_id": 9}

    monkeypatch.setattr(api_module, "_hydrate_context", fake_hydrate_context)
    monkeypatch.setattr(api_module, "save_sprint_plan_tool", fake_save_sprint_plan_tool)

    response = client.post(
        f"/api/projects/{project_id}/sprint/save",
        json={
            "team_name": "Team Alpha",
            "sprint_start_date": "2026-03-15",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["fsm_state"] == "SPRINT_PERSISTENCE"
    assert workflow.states[str(project_id)]["fsm_state"] == "SPRINT_PERSISTENCE"
    assert captured["input_data"].team_name == "Team Alpha"
    assert captured["input_data"].sprint_start_date == "2026-03-15"
    assert captured["input_data"].sprint_duration_days == 14
    assert captured["tool_context"].state["preserved"] is True
    assert captured["tool_context"].state["sprint_plan"]["duration_days"] == 14
    assert "is_complete" not in captured["tool_context"].state["sprint_plan"]


def test_sprint_save_requires_team_name(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_draft_project(repo, workflow)

    response = client.post(
        f"/api/projects/{project_id}/sprint/save",
        json={"sprint_start_date": "2026-03-15"},
    )

    assert response.status_code == 422


def test_sprint_save_requires_start_date(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_draft_project(repo, workflow)

    response = client.post(
        f"/api/projects/{project_id}/sprint/save",
        json={"team_name": "Team Alpha"},
    )

    assert response.status_code == 422


def test_sprint_save_rejects_incomplete_assessment(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_draft_project(repo, workflow, is_complete=False)

    response = client.post(
        f"/api/projects/{project_id}/sprint/save",
        json={
            "team_name": "Team Alpha",
            "sprint_start_date": "2026-03-15",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Sprint cannot be saved until is_complete is true"


def test_sprint_save_surfaces_persistence_tool_error(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_draft_project(repo, workflow)

    async def fake_hydrate_context(session_id: str, project_id: int):
        return SimpleNamespace(state={}, session_id=session_id)

    def fake_save_sprint_plan_tool(input_data, tool_context):
        return {"success": False, "error": "Stories already assigned to active or planned sprints: [12]"}

    monkeypatch.setattr(api_module, "_hydrate_context", fake_hydrate_context)
    monkeypatch.setattr(api_module, "save_sprint_plan_tool", fake_save_sprint_plan_tool)

    response = client.post(
        f"/api/projects/{project_id}/sprint/save",
        json={
            "team_name": "Team Alpha",
            "sprint_start_date": "2026-03-15",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Stories already assigned to active or planned sprints: [12]"


def test_list_sprints_returns_saved_sprints_newest_first(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, _older_sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=True,
        created_title="Older Sprint",
    )

    team = session.exec(select(Team).where(Team.name == f"Team {project_id}")).first()
    assert team is not None

    second_story = UserStory(
        product_id=project_id,
        title="Newest Sprint Story",
        story_description="As a user, I want another sprint",
        acceptance_criteria="- AC",
    )
    session.add(second_story)
    session.flush()

    newer_sprint = Sprint(
        goal="Newest Sprint Goal",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 15),
        status=SprintStatus.PLANNED,
        product_id=project_id,
        team_id=team.team_id,
    )
    session.add(newer_sprint)
    session.flush()
    session.add(
        SprintStory(sprint_id=newer_sprint.sprint_id, story_id=second_story.story_id)
    )
    session.commit()

    response = client.get(f"/api/projects/{project_id}/sprints")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["count"] == 2
    assert payload["data"]["items"][0]["id"] == newer_sprint.sprint_id
    assert payload["data"]["items"][0]["started_at"] is None
    assert payload["data"]["items"][1]["started_at"] is not None
    assert payload["data"]["items"][0]["story_count"] == 1


def test_start_sprint_sets_started_at_once_and_logs_event(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=False,
        created_title="Planned Sprint",
    )

    first_response = client.patch(f"/api/projects/{project_id}/sprints/{sprint_id}/start")
    assert first_response.status_code == 200
    first_payload = first_response.json()
    started_at = first_payload["data"]["sprint"]["started_at"]
    assert started_at is not None
    assert first_payload["data"]["sprint"]["status"] == SprintStatus.ACTIVE.value

    second_response = client.patch(f"/api/projects/{project_id}/sprints/{sprint_id}/start")
    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert second_payload["data"]["sprint"]["started_at"] == started_at

    events = session.exec(
        select(WorkflowEvent).where(
            WorkflowEvent.event_type == WorkflowEventType.SPRINT_STARTED
        )
    ).all()
    assert len(events) == 1
