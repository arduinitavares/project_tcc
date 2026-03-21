"""API tests for sprint setup, candidates, and generation flow."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional

from fastapi.testclient import TestClient
from sqlmodel import select

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Product,
    SpecRegistry,
    Sprint,
    SprintStatus,
    SprintStory,
    Task,
    Team,
    UserStory,
    WorkflowEvent,
    WorkflowEventType,
)
from tools.spec_tools import _compute_story_input_hash
from utils.schemes import (
    AlignmentFinding,
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SourceMapEntry,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
    ValidationEvidence,
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


def _seed_task_packet_context(
    session,
    repo: DummyProductRepository,
    *,
    pinned: bool,
) -> tuple[int, int, int, int]:
    product = repo.create("Task Packet Project")
    session.add(
        Product(
            product_id=product.product_id,
            name=product.name,
            vision="Build trustworthy execution handoffs.\n\nIgnore this second paragraph.",
        )
    )

    team = Team(name=f"Packet Team {product.product_id}")
    session.add(team)
    session.flush()

    story = UserStory(
        product_id=product.product_id,
        title="Payload Validation Story",
        story_description="As a developer, I want payload validation so that requests are safe.",
        acceptance_criteria="- include user_id\n- reject invalid payloads",
        persona="Developer",
        story_points=3,
        rank="1",
        source_requirement="api_payload_validation",
    )
    session.add(story)
    session.flush()

    task = Task(
        description="Implement payload validation for incoming requests",
        story_id=story.story_id,
    )
    session.add(task)
    session.flush()

    sprint = Sprint(
        goal="Ship a trustworthy task packet API",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 14),
        status=SprintStatus.PLANNED,
        product_id=product.product_id,
        team_id=team.team_id,
    )
    session.add(sprint)
    session.flush()

    link = SprintStory(sprint_id=sprint.sprint_id, story_id=story.story_id)
    session.add(link)

    if pinned:
        spec_version = SpecRegistry(
            product_id=product.product_id,
            spec_hash="a" * 64,
            content="# Spec\n\n## Invariants\n- Requests must include user_id.",
            status="approved",
            approved_at=datetime.now(timezone.utc),
            approved_by="tester",
        )
        session.add(spec_version)
        session.flush()

        invariant = Invariant(
            id="INV-0123456789abcdef",
            type=InvariantType.REQUIRED_FIELD,
            parameters=RequiredFieldParams(field_name="user_id"),
        )
        artifact = SpecAuthorityCompilationSuccess(
            scope_themes=["API"],
            domain="api",
            invariants=[invariant],
            eligible_feature_rules=[],
            gaps=[],
            assumptions=[],
            source_map=[
                SourceMapEntry(
                    invariant_id=invariant.id,
                    excerpt="Requests must include user_id.",
                    location="Spec §1",
                )
            ],
            compiler_version="1.0.0",
            prompt_hash="0" * 64,
        )
        authority = CompiledSpecAuthority(
            spec_version_id=spec_version.spec_version_id,
            compiler_version="1.0.0",
            prompt_hash="0" * 64,
            scope_themes='["API"]',
            invariants='["REQUIRED_FIELD:user_id"]',
            eligible_feature_ids="[]",
            rejected_features="[]",
            spec_gaps="[]",
            compiled_artifact_json=SpecAuthorityCompilerOutput(
                root=artifact
            ).model_dump_json(),
        )
        session.add(authority)
        session.flush()

        story.accepted_spec_version_id = spec_version.spec_version_id
        story.validation_evidence = ValidationEvidence(
            spec_version_id=spec_version.spec_version_id,
            validated_at=datetime.now(timezone.utc),
            passed=True,
            rules_checked=["SPEC_VERSION_EXISTS", "SPEC_PRODUCT_MATCH"],
            invariants_checked=["REQUIRED_FIELD:user_id"],
            failures=[],
            warnings=["Double-check payload casing."],
            alignment_warnings=[
                AlignmentFinding(
                    code="REQUIRED_FIELD_MISSING",
                    invariant=invariant.id,
                    capability=None,
                    message="Acceptance criteria may be missing required field 'user_id'.",
                    severity="warning",
                    created_at=datetime.now(timezone.utc),
                )
            ],
            alignment_failures=[],
            validator_version="1.0.0",
            input_hash=_compute_story_input_hash(story),
        ).model_dump_json()

    session.add(story)
    session.commit()

    return product.product_id, sprint.sprint_id, story.story_id, task.task_id


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


def test_get_task_packet_returns_canonical_packet_for_pinned_story(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, _story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
    )

    response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet"
    )

    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["schema_version"] == "task_packet.v1"
    assert payload["metadata"]["packet_id"].startswith("tp_")
    assert payload["metadata"]["generator_version"] == "v1"

    assert payload["task"]["task_id"] == task_id
    assert payload["task"]["status"] == "To Do"
    assert payload["task"]["label"] == "Implement payload validation for incoming requests"

    assert payload["context"]["story"]["title"] == "Payload Validation Story"
    assert payload["context"]["sprint"]["goal"] == "Ship a trustworthy task packet API"
    assert payload["context"]["product"]["vision_excerpt"] == "Build trustworthy execution handoffs."

    constraints = payload["constraints"]
    assert constraints["acceptance_criteria_items"] == [
        "include user_id",
        "reject invalid payloads",
    ]
    assert constraints["spec_binding"]["binding_status"] == "pinned"
    assert constraints["spec_binding"]["authority_artifact_status"] == "available"
    assert constraints["validation"]["present"] is True
    assert constraints["validation"]["freshness_status"] == "current"
    assert constraints["validation"]["input_hash_matches"] is True
    assert constraints["relevant_invariants"] == [
        {
            "invariant_id": "INV-0123456789abcdef",
            "type": "REQUIRED_FIELD",
            "parameters": {"field_name": "user_id"},
            "source_excerpt": "Requests must include user_id.",
            "source_location": "Spec §1",
        }
    ]
    assert any(
        finding["source"] == "validation_warning"
        for finding in constraints["findings"]
    )
    assert any(
        finding["source"] == "alignment_warning"
        for finding in constraints["findings"]
    )


def test_get_task_packet_rejects_unlinked_task_sprint_pair(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, _sprint_id, story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=False,
    )

    team = session.exec(select(Team).where(Team.name == f"Packet Team {project_id}")).first()
    assert team is not None

    other_sprint = Sprint(
        goal="Unlinked sprint",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 14),
        status=SprintStatus.PLANNED,
        product_id=project_id,
        team_id=team.team_id,
    )
    session.add(other_sprint)
    session.commit()

    response = client.get(
        f"/api/projects/{project_id}/sprints/{other_sprint.sprint_id}/tasks/{task_id}/packet"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Task packet context not found"

    linked_story = session.get(UserStory, story_id)
    assert linked_story is not None


def test_same_task_gets_different_packet_identity_across_sprints(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=False,
    )

    team = session.exec(select(Team).where(Team.name == f"Packet Team {project_id}")).first()
    assert team is not None

    second_sprint = Sprint(
        goal="Carry the task into another sprint",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 14),
        status=SprintStatus.PLANNED,
        product_id=project_id,
        team_id=team.team_id,
    )
    session.add(second_sprint)
    session.flush()
    session.add(SprintStory(sprint_id=second_sprint.sprint_id, story_id=story_id))
    session.commit()

    first_payload = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet"
    ).json()["data"]
    second_payload = client.get(
        f"/api/projects/{project_id}/sprints/{second_sprint.sprint_id}/tasks/{task_id}/packet"
    ).json()["data"]

    assert first_payload["metadata"]["packet_id"] != second_payload["metadata"]["packet_id"]
    assert (
        first_payload["metadata"]["source_fingerprint"]
        != second_payload["metadata"]["source_fingerprint"]
    )
    assert first_payload["context"]["sprint"]["goal"] != second_payload["context"]["sprint"]["goal"]


def test_unpinned_story_packet_has_no_authority_fallback(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, _story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=False,
    )

    response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet"
    )

    assert response.status_code == 200
    constraints = response.json()["data"]["constraints"]
    assert constraints["spec_binding"]["binding_status"] == "unpinned"
    assert constraints["spec_binding"]["spec_version_id"] is None
    assert constraints["spec_binding"]["authority_artifact_status"] == "missing"
    assert constraints["relevant_invariants"] == []
    assert constraints["validation"]["freshness_status"] == "missing"


def test_task_packet_marks_validation_as_stale_when_story_content_changes(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
    )

    story = session.get(UserStory, story_id)
    assert story is not None
    story.acceptance_criteria = "- include user_id\n- reject invalid payloads\n- log failures"
    story.ac_updated_at = datetime.now(timezone.utc)
    session.add(story)
    session.commit()

    response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet"
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["constraints"]["validation"]["freshness_status"] == "stale"
    assert payload["source_snapshot"]["story_ac_updated_at"] is not None


def test_packet_renderer_escapes_html_and_xml_safely(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
    )

    task = session.get(Task, task_id)
    assert task is not None
    task.description = '<script>alert("XSS")</script> and </task> breaking out **bold**'
    session.add(task)
    session.commit()

    # Test human flavor preventing unescaped HTML injection and Markdown restructuring
    res_human = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet?flavor=human"
    )
    assert res_human.status_code == 200
    human_text = res_human.json()["data"]["render"]
    assert '&lt;script&gt;alert("XSS")&lt;/script&gt;' in human_text
    assert "<script>" not in human_text
    assert "&#42;&#42;bold&#42;&#42;" in human_text

    # Test agent flavor preventing unescaped XML closure injection
    res_agent = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet?flavor=cursor"
    )
    assert res_agent.status_code == 200
    agent_text = res_agent.json()["data"]["render"]
    assert "&lt;/task&gt;" in agent_text
    assert "</task> breaking out" not in agent_text


def test_list_sprints_returns_task_objects(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
    )

    response = client.get(f"/api/projects/{project_id}/sprints")
    assert response.status_code == 200
    
    data = response.json()["data"]
    items = data["items"]
    assert len(items) > 0
    sprint = items[0]
    
    assert len(sprint["selected_stories"]) > 0
    story = sprint["selected_stories"][0]
    
    assert len(story["tasks"]) > 0
    task_obj = story["tasks"][0]
    
    assert isinstance(task_obj, dict)
    assert "id" in task_obj
    assert "description" in task_obj
    assert "status" in task_obj
