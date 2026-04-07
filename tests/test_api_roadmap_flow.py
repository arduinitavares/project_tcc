"""API tests for roadmap generation, history, and save flow."""

from dataclasses import dataclass
from typing import Dict, Optional

from fastapi.testclient import TestClient

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

    def fake_select_project(product_id: int, context):
        product = repo.get_by_id(product_id)
        if not product:
            return {"success": False, "error": "missing"}
        context.state["active_project"] = {
            "product_id": product_id,
            "name": product.name,
            "vision": product.vision,
            "spec_file_path": product.spec_file_path,
        }
        context.state.setdefault("pending_spec_content", "SPEC")
        context.state.setdefault("compiled_authority_cached", '{"ok": true}')
        return {"success": True}

    monkeypatch.setattr(api_module, "select_project", fake_select_project)

    async def fake_run_roadmap_agent_from_state(state, *, project_id, user_input):
        normalized = (user_input or "").lower().strip()
        if normalized == "force-runtime-error":
            return {
                "success": False,
                "input_context": {
                    "user_input": user_input or "",
                    "product_vision": "A clear vision",
                    "technical_spec": "SPEC",
                    "compiled_authority": '{"ok": true}',
                    "prior_roadmap_state": "NO_HISTORY",
                },
                "output_artifact": {
                    "error": "ROADMAP_GENERATION_FAILED",
                    "message": "provider timeout",
                    "is_complete": False,
                    "clarifying_questions": [],
                },
                "is_complete": None,
                "error": "provider timeout",
                "failure_artifact_id": "roadmap-failure-1",
                "failure_stage": "invocation_exception",
                "failure_summary": "provider timeout",
                "raw_output_preview": '{"partial": true}',
                "has_full_artifact": True,
            }

        is_complete = normalized.startswith("complete")
        return {
            "success": True,
            "input_context": {
                "user_input": user_input or "",
                "product_vision": "A clear vision",
                "technical_spec": "SPEC",
                "compiled_authority": '{"ok": true}',
                "prior_roadmap_state": "NO_HISTORY",
            },
            "output_artifact": {
                "roadmap_releases": [
                    {
                        "release_name": "Milestone 1",
                        "theme": "Foundation",
                        "focus_area": "Technical Foundation",
                        "items": ["Seed backlog item"],
                        "reasoning": "Start here",
                    }
                ],
                "roadmap_summary": "Draft roadmap",
                "is_complete": is_complete,
                "clarifying_questions": []
                if is_complete
                else ["Need more detail"],
            },
            "is_complete": is_complete,
            "error": None,
            "failure_artifact_id": None,
            "failure_stage": None,
            "failure_summary": None,
            "raw_output_preview": None,
            "has_full_artifact": False,
        }

    monkeypatch.setattr(
        api_module,
        "run_roadmap_agent_from_state",
        fake_run_roadmap_agent_from_state,
    )

    def fake_save_roadmap_tool(roadmap_input, tool_context):
        return {
            "success": True,
            "product_id": roadmap_input.product_id,
            "message": "saved",
            "releases_count": len(roadmap_input.roadmap_data.roadmap_releases),
        }

    monkeypatch.setattr(api_module, "save_roadmap_tool", fake_save_roadmap_tool)

    return TestClient(api_module.app), repo, workflow


def _seed_backlog_persisted_project(
    repo: DummyProductRepository, workflow: DummyWorkflowService
) -> int:
    product = repo.create("Roadmap Project")
    product.spec_file_path = __file__
    product.compiled_authority_json = '{"ok": true}'
    workflow.states[str(product.product_id)] = {
        "fsm_state": "BACKLOG_PERSISTENCE",
        "product_vision_assessment": {
            "product_vision_statement": "A clear vision",
            "is_complete": True,
        },
        "backlog_items": [{"title": "Seed backlog item"}],
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
    }
    return product.product_id


def test_roadmap_generate_allows_empty_input_on_first_attempt(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_backlog_persisted_project(repo, workflow)

    response = client.post(f"/api/projects/{project_id}/roadmap/generate", json={})
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["trigger"] == "auto_transition"
    assert payload["data"]["fsm_state"] == "ROADMAP_INTERVIEW"
    assert workflow.states[str(project_id)]["roadmap_attempts"][0]["trigger"] == (
        "auto_transition"
    )


def test_roadmap_generate_requires_feedback_after_first_attempt(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_backlog_persisted_project(repo, workflow)

    first_response = client.post(
        f"/api/projects/{project_id}/roadmap/generate",
        json={},
    )
    assert first_response.status_code == 200

    second_response = client.post(
        f"/api/projects/{project_id}/roadmap/generate",
        json={},
    )
    assert second_response.status_code == 400
    assert second_response.json()["detail"] == (
        "User input is required to refine an existing roadmap."
    )


def test_roadmap_generate_translates_phase_error(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_backlog_persisted_project(repo, workflow)

    async def failing_service(**_kwargs):
        raise api_module.RoadmapPhaseError("service boom", status_code=418)

    monkeypatch.setattr(
        api_module,
        "generate_roadmap_draft_service",
        failing_service,
    )

    response = client.post(
        f"/api/projects/{project_id}/roadmap/generate",
        json={"user_input": "complete this"},
    )
    assert response.status_code == 418
    assert response.json()["detail"] == "service boom"


def test_roadmap_generate_failed_run_cannot_mark_complete(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_backlog_persisted_project(repo, workflow)

    async def failed_runtime(state, *, project_id, user_input):
        return {
            "success": False,
            "input_context": {"user_input": user_input or ""},
            "output_artifact": {
                "error": "ROADMAP_GENERATION_FAILED",
                "message": "provider timeout",
                "is_complete": True,
                "clarifying_questions": [],
            },
            "is_complete": True,
            "error": "provider timeout",
            "failure_artifact_id": "roadmap-failure-1",
            "failure_stage": "invocation_exception",
            "failure_summary": "provider timeout",
            "raw_output_preview": '{"partial": true}',
            "has_full_artifact": True,
        }

    monkeypatch.setattr(
        api_module,
        "run_roadmap_agent_from_state",
        failed_runtime,
    )

    response = client.post(
        f"/api/projects/{project_id}/roadmap/generate",
        json={"user_input": "complete this roadmap"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["data"]["roadmap_run_success"] is False
    assert payload["data"]["is_complete"] is False
    assert payload["data"]["fsm_state"] == "ROADMAP_INTERVIEW"


def test_roadmap_history_endpoint_returns_attempts(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_backlog_persisted_project(repo, workflow)

    client.post(
        f"/api/projects/{project_id}/roadmap/generate",
        json={},
    )
    client.post(
        f"/api/projects/{project_id}/roadmap/generate",
        json={"user_input": "complete this roadmap"},
    )

    response = client.get(f"/api/projects/{project_id}/roadmap/history")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["count"] == 2
    assert payload["data"]["items"][0]["trigger"] == "auto_transition"


def test_roadmap_save_succeeds_when_complete(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_backlog_persisted_project(repo, workflow)

    client.post(
        f"/api/projects/{project_id}/roadmap/generate",
        json={"user_input": "complete this roadmap"},
    )

    response = client.post(f"/api/projects/{project_id}/roadmap/save")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["fsm_state"] == "ROADMAP_PERSISTENCE"
    assert workflow.states[str(project_id)]["fsm_state"] == "ROADMAP_PERSISTENCE"


def test_roadmap_save_rejects_incomplete_assessment(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_backlog_persisted_project(repo, workflow)

    workflow.states[str(project_id)]["product_roadmap_assessment"] = {
        "roadmap_releases": [
            {
                "release_name": "Milestone 1",
                "theme": "Foundation",
                "focus_area": "Technical Foundation",
                "items": ["Seed backlog item"],
                "reasoning": "Start here",
            }
        ],
        "roadmap_summary": "Draft roadmap",
        "is_complete": False,
        "clarifying_questions": ["Need more detail"],
    }

    response = client.post(f"/api/projects/{project_id}/roadmap/save")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Roadmap cannot be saved until is_complete is true"
    )
