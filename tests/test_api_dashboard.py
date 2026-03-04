"""API tests for deterministic setup-first dashboard endpoints."""

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
        migrated = 0
        for sid, payload in self.states.items():
            if payload.get("fsm_state") == "ROUTING_MODE":
                self.states[sid]["fsm_state"] = "SETUP_REQUIRED"
                migrated += 1
        return migrated


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
        return {"success": True}

    def fake_link_spec_to_product(params, tool_context=None):
        product = repo.get_by_id(int(params["product_id"]))
        spec_path = params["spec_path"]

        if "invalid" in spec_path.lower():
            if tool_context:
                tool_context.state["setup_error"] = "invalid spec path"
            return {
                "success": True,
                "compile_success": False,
                "compile_error": "invalid spec path",
            }

        product.spec_file_path = spec_path
        product.compiled_authority_json = '{"ok": true}'

        if tool_context:
            tool_context.state["pending_spec_path"] = spec_path
            tool_context.state["pending_spec_content"] = "SPEC"
            tool_context.state["compiled_authority_cached"] = '{"ok": true}'

        return {
            "success": True,
            "compile_success": True,
            "spec_path": spec_path,
        }

    monkeypatch.setattr(api_module, "select_project", fake_select_project)
    monkeypatch.setattr(api_module, "link_spec_to_product", fake_link_spec_to_product)
    
    async def fake_run_vision_agent_from_state(state, *, user_input):
        return {
            "success": True,
            "input_context": {
                "user_raw_text": user_input or "",
                "prior_vision_state": "NO_HISTORY",
                "specification_content": state.get("pending_spec_content", "SPEC"),
                "compiled_authority": state.get("compiled_authority_cached", '{"ok": true}'),
            },
            "output_artifact": {
                "updated_components": {
                    "project_name": "Vision Project",
                    "target_user": None,
                    "problem": None,
                    "product_category": None,
                    "key_benefit": None,
                    "competitors": None,
                    "differentiator": None,
                },
                "product_vision_statement": "Draft",
                "is_complete": False,
                "clarifying_questions": ["Need details"],
            },
            "is_complete": False,
            "error": None,
        }

    monkeypatch.setattr(api_module, "run_vision_agent_from_state", fake_run_vision_agent_from_state)

    return TestClient(api_module.app), repo, workflow


def test_get_dashboard_config_returns_setup_state(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    response = client.get("/api/dashboard/config")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    steps = payload["data"]["workflow_steps"]

    assert steps[0]["id"] == "setup"
    assert steps[0]["states"] == ["SETUP_REQUIRED"]


def test_create_project_requires_spec_file_path(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    response = client.post("/api/projects", json={"name": "Alpha"})
    assert response.status_code == 422


def test_create_project_success_advances_to_vision(monkeypatch):
    client, _, workflow = _build_client(monkeypatch)

    response = client.post(
        "/api/projects",
        json={"name": "Project Alpha", "spec_file_path": __file__},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["setup_status"] == "passed"
    assert payload["data"]["fsm_state"] == "VISION_INTERVIEW"
    assert payload["data"]["vision_auto_run"]["attempted"] is True
    assert payload["data"]["vision_auto_run"]["success"] is True
    assert payload["data"]["vision_auto_run"]["is_complete"] is False

    assert workflow.states["1"]["fsm_state"] == "VISION_INTERVIEW"


def test_create_project_setup_fail_and_retry_same_project(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)

    create_response = client.post(
        "/api/projects",
        json={"name": "Project Retry", "spec_file_path": "invalid/path.md"},
    )
    assert create_response.status_code == 200

    create_payload = create_response.json()
    assert create_payload["data"]["setup_status"] == "failed"
    assert create_payload["data"]["fsm_state"] == "SETUP_REQUIRED"
    assert create_payload["data"]["vision_auto_run"]["attempted"] is False

    product = repo.get_by_id(create_payload["data"]["id"])
    assert product is not None

    retry_response = client.post(
        f"/api/projects/{product.product_id}/setup/retry",
        json={"spec_file_path": __file__},
    )
    assert retry_response.status_code == 200

    retry_payload = retry_response.json()
    assert retry_payload["data"]["setup_status"] == "passed"
    assert retry_payload["data"]["fsm_state"] == "VISION_INTERVIEW"
    assert retry_payload["data"]["vision_auto_run"]["attempted"] is True
    assert workflow.states[str(product.product_id)]["fsm_state"] == "VISION_INTERVIEW"


def test_state_forces_setup_required_when_product_missing_spec(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)

    product = repo.create("Legacy")
    workflow.states[str(product.product_id)] = {
        "fsm_state": "VISION_REVIEW",
        "setup_status": "passed",
    }

    response = client.get(f"/api/projects/{product.product_id}/state")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["fsm_state"] == "SETUP_REQUIRED"
    assert payload["data"]["setup_status"] == "failed"


def test_create_project_auto_vision_failure_is_recorded(monkeypatch):
    client, _, workflow = _build_client(monkeypatch)

    async def failing_auto_vision(state, *, user_input):
        return {
            "success": False,
            "input_context": {
                "user_raw_text": user_input or "",
                "prior_vision_state": "NO_HISTORY",
                "specification_content": state.get("pending_spec_content", "SPEC"),
                "compiled_authority": state.get("compiled_authority_cached", '{"ok": true}'),
            },
            "output_artifact": {
                "error": "VISION_GENERATION_FAILED",
                "message": "provider error",
                "is_complete": False,
                "clarifying_questions": [],
            },
            "is_complete": None,
            "error": "provider error",
        }

    monkeypatch.setattr(api_module, "run_vision_agent_from_state", failing_auto_vision)

    response = client.post(
        "/api/projects",
        json={"name": "Project Auto Fail", "spec_file_path": __file__},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["data"]["setup_status"] == "passed"
    assert payload["data"]["fsm_state"] == "VISION_INTERVIEW"
    assert payload["data"]["vision_auto_run"]["attempted"] is True
    assert payload["data"]["vision_auto_run"]["success"] is False
    assert payload["data"]["vision_auto_run"]["is_complete"] is None

    history = workflow.states["1"]["vision_attempts"]
    assert isinstance(history, list)
    assert len(history) == 1
    assert history[0]["trigger"] == "auto_setup_transition"
    assert history[0]["is_complete"] is False
