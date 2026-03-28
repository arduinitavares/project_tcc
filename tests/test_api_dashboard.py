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

    def get_session_states_batch(self, session_ids: list[str]):
        return {
            str(sid): dict(self.states.get(str(sid), {}))
            for sid in session_ids
            if str(sid) in self.states
        }

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
                "failure_artifact_id": "setup-artifact-1",
                "failure_stage": "output_validation",
                "failure_summary": "SPEC_COMPILATION_FAILED: invalid spec path",
                "raw_output_preview": '{"invalid": true}',
                "has_full_artifact": True,
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

    async def fake_run_vision_agent_from_state(state, *, project_id, user_input):
        return {
            "success": True,
            "input_context": {
                "user_raw_text": user_input or "",
                "prior_vision_state": "NO_HISTORY",
                "specification_content": state.get("pending_spec_content", "SPEC"),
                "compiled_authority": state.get(
                    "compiled_authority_cached", '{"ok": true}'
                ),
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
            "failure_artifact_id": None,
            "failure_stage": None,
            "failure_summary": None,
            "raw_output_preview": None,
            "has_full_artifact": False,
        }

    monkeypatch.setattr(
        api_module, "run_vision_agent_from_state", fake_run_vision_agent_from_state
    )

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


def test_root_redirects_to_dashboard(monkeypatch):
    client, _, _ = _build_client(monkeypatch)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard"


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


def test_get_project_state_preserves_specific_setup_error(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)

    create_response = client.post(
        "/api/projects",
        json={"name": "Project Retry", "spec_file_path": "invalid/path.md"},
    )
    assert create_response.status_code == 200

    project_id = create_response.json()["data"]["id"]

    state_response = client.get(f"/api/projects/{project_id}/state")
    assert state_response.status_code == 200

    payload = state_response.json()
    assert payload["data"]["setup_status"] == "failed"
    assert payload["data"]["setup_error"] == "invalid spec path"
    assert payload["data"]["setup_failure_artifact_id"] == "setup-artifact-1"
    assert payload["data"]["setup_failure_stage"] == "output_validation"
    assert payload["data"]["setup_has_full_artifact"] is True


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

    async def failing_auto_vision(state, *, project_id, user_input):
        return {
            "success": False,
            "input_context": {
                "user_raw_text": user_input or "",
                "prior_vision_state": "NO_HISTORY",
                "specification_content": state.get("pending_spec_content", "SPEC"),
                "compiled_authority": state.get(
                    "compiled_authority_cached", '{"ok": true}'
                ),
            },
            "output_artifact": {
                "error": "VISION_GENERATION_FAILED",
                "message": "provider error",
                "is_complete": False,
                "clarifying_questions": [],
            },
            "is_complete": None,
            "error": "provider error",
            "failure_artifact_id": "vision-auto-failure",
            "failure_stage": "invocation_exception",
            "failure_summary": "provider error",
            "raw_output_preview": '{"partial": true}',
            "has_full_artifact": True,
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
    assert (
        payload["data"]["vision_auto_run"]["failure_artifact_id"]
        == "vision-auto-failure"
    )

    history = workflow.states["1"]["vision_attempts"]
    assert isinstance(history, list)
    assert len(history) == 1
    assert history[0]["trigger"] == "auto_setup_transition"
    assert history[0]["is_complete"] is False
    assert history[0]["failure_artifact_id"] == "vision-auto-failure"


def test_create_project_setup_failure_exposes_failure_metadata(monkeypatch):
    client, _, workflow = _build_client(monkeypatch)

    response = client.post(
        "/api/projects",
        json={"name": "Project Retry", "spec_file_path": "invalid/path.md"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["data"]["setup_status"] == "failed"
    assert payload["data"]["failure_artifact_id"] == "setup-artifact-1"
    assert payload["data"]["failure_stage"] == "output_validation"
    assert payload["data"]["has_full_artifact"] is True
    assert workflow.states["1"]["setup_failure_artifact_id"] == "setup-artifact-1"


def test_get_projects_batch_session_lookup(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)

    # Create dummy products
    product1 = repo.create("Project 1")
    product2 = repo.create("Project 2")
    product3 = repo.create("Project 3")

    # Only products 1 and 2 will have session states in the mock
    product1.spec_file_path = (
        __file__  # Use a file that exists on disk to pass _setup_blocker
    )
    product1.compiled_authority_json = '{"ok": true}'  # Also needed for _setup_blocker

    workflow.states[str(product1.product_id)] = {
        "fsm_state": "VISION_INTERVIEW",
        "setup_status": "passed",
    }
    workflow.states[str(product2.product_id)] = {
        "fsm_state": "SETUP_REQUIRED",
        "setup_status": "failed",
    }
    # product3 has no state

    # Keep track of how many times get_session_status is called (should be 0 now for get_projects)
    call_counts = {"get_session_status": 0, "get_session_states_batch": 0}

    # We don't necessarily need to mock the workflow methods since _build_client might mock them already
    # Let's mock the get_session_states_batch to verify it's called
    original_batch = workflow.get_session_states_batch

    def fake_batch(session_ids):
        call_counts["get_session_states_batch"] += 1
        return original_batch(session_ids)

    original_single = workflow.get_session_status

    def fake_single(session_id):
        call_counts["get_session_status"] += 1
        return original_single(session_id)

    monkeypatch.setattr(workflow, "get_session_states_batch", fake_batch)
    monkeypatch.setattr(workflow, "get_session_status", fake_single)

    response = client.get("/api/projects")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    data = payload["data"]

    assert len(data) >= 3  # at least our 3 products

    # Check that batch was called instead of single status
    assert call_counts["get_session_states_batch"] == 1
    assert call_counts["get_session_status"] == 0

    # Verify the correct payloads are returned
    found1 = next(p for p in data if p["id"] == product1.product_id)
    assert found1["fsm_state"] == "VISION_INTERVIEW"
    assert found1["setup_status"] == "passed"

    found2 = next(p for p in data if p["id"] == product2.product_id)
    assert found2["fsm_state"] == "SETUP_REQUIRED"
    assert found2["setup_status"] == "failed"

    found3 = next(p for p in data if p["id"] == product3.product_id)
    # the fallback in _effective_project_state logic should give defaults:
    assert found3["fsm_state"] == "SETUP_REQUIRED"
    assert found3["setup_status"] == "failed"
