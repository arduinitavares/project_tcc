"""API tests for backlog generation, history, and save flow."""

from dataclasses import dataclass

from fastapi.testclient import TestClient

import api as api_module


@dataclass
class DummyProduct:
    product_id: int
    name: str
    description: str | None = None
    vision: str | None = None
    spec_file_path: str | None = None
    compiled_authority_json: str | None = None


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

    def create(self, name: str, description: str | None = None):
        product = DummyProduct(
            product_id=len(self.products) + 1,
            name=name,
            description=description,
        )
        self.products.append(product)
        return product


class DummyWorkflowService:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, object]] = {}

    async def initialize_session(self, session_id: str | None = None) -> str:
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

    async def fake_run_backlog_agent_from_state(state, *, project_id, user_input):
        normalized = (user_input or "").lower().strip()
        if normalized == "force-runtime-error":
            return {
                "success": False,
                "input_context": {
                    "user_raw_text": user_input or "",
                    "product_vision_statement": "A clear vision",
                    "technical_spec": "SPEC",
                    "compiled_authority": '{"ok": true}',
                    "prior_backlog_state": "NO_HISTORY",
                },
                "output_artifact": {
                    "error": "BACKLOG_GENERATION_FAILED",
                    "message": "provider timeout",
                    "is_complete": False,
                    "clarifying_questions": [],
                },
                "is_complete": None,
                "error": "provider timeout",
                "failure_artifact_id": "backlog-failure-1",
                "failure_stage": "invocation_exception",
                "failure_summary": "provider timeout",
                "raw_output_preview": '{"partial": true}',
                "has_full_artifact": True,
            }

        is_complete = normalized.startswith("complete")
        return {
            "success": True,
            "input_context": {
                "user_raw_text": user_input or "",
                "product_vision_statement": "A clear vision",
                "technical_spec": "SPEC",
                "compiled_authority": '{"ok": true}',
                "prior_backlog_state": "NO_HISTORY",
            },
            "output_artifact": {
                "backlog_items": [{"title": "Seed backlog item"}],
                "is_complete": is_complete,
                "clarifying_questions": [] if is_complete else ["Need more detail"],
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
        "run_backlog_agent_from_state",
        fake_run_backlog_agent_from_state,
    )

    def fake_save_backlog_tool(backlog_input, tool_context):
        return {
            "success": True,
            "product_id": backlog_input.product_id,
            "saved_count": len(backlog_input.backlog_items),
            "message": "saved",
        }

    monkeypatch.setattr(api_module, "save_backlog_tool", fake_save_backlog_tool)

    return TestClient(api_module.app), repo, workflow


def _seed_vision_persisted_project(
    repo: DummyProductRepository, workflow: DummyWorkflowService
) -> int:
    product = repo.create("Backlog Project")
    product.spec_file_path = __file__
    product.compiled_authority_json = '{"ok": true}'
    workflow.states[str(product.product_id)] = {
        "fsm_state": "VISION_PERSISTENCE",
        "product_vision_assessment": {
            "product_vision_statement": "A clear vision",
            "is_complete": True,
        },
        "pending_spec_content": "SPEC",
        "compiled_authority_cached": '{"ok": true}',
    }
    return product.product_id


def test_backlog_generate_allows_empty_input_on_first_attempt(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_vision_persisted_project(repo, workflow)

    response = client.post(f"/api/projects/{project_id}/backlog/generate", json={})
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["trigger"] == "auto_transition"
    assert payload["data"]["fsm_state"] == "BACKLOG_INTERVIEW"
    assert (
        workflow.states[str(project_id)]["backlog_attempts"][0]["trigger"]
        == "auto_transition"
    )


def test_backlog_generate_requires_feedback_after_first_attempt(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_vision_persisted_project(repo, workflow)

    first_response = client.post(
        f"/api/projects/{project_id}/backlog/generate",
        json={},
    )
    assert first_response.status_code == 200

    second_response = client.post(
        f"/api/projects/{project_id}/backlog/generate",
        json={},
    )
    assert second_response.status_code == 409
    assert "Feedback is required" in second_response.json()["detail"]


def test_backlog_generate_translates_phase_error(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_vision_persisted_project(repo, workflow)

    async def failing_service(**_kwargs):
        raise api_module.BacklogPhaseError("service boom", status_code=418)

    monkeypatch.setattr(
        api_module,
        "generate_backlog_draft_service",
        failing_service,
    )

    response = client.post(
        f"/api/projects/{project_id}/backlog/generate",
        json={"user_input": "complete this"},
    )
    assert response.status_code == 418
    assert response.json()["detail"] == "service boom"


def test_backlog_history_endpoint_returns_attempts(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_vision_persisted_project(repo, workflow)

    client.post(
        f"/api/projects/{project_id}/backlog/generate",
        json={},
    )
    client.post(
        f"/api/projects/{project_id}/backlog/generate",
        json={"user_input": "complete this now"},
    )

    response = client.get(f"/api/projects/{project_id}/backlog/history")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["count"] == 2
    assert all(
        item.get("trigger") == "auto_transition"
        for item in payload["data"]["items"][:1]
    )


def test_backlog_save_succeeds_when_complete(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_vision_persisted_project(repo, workflow)

    client.post(
        f"/api/projects/{project_id}/backlog/generate",
        json={"user_input": "complete this backlog"},
    )

    response = client.post(f"/api/projects/{project_id}/backlog/save")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["fsm_state"] == "BACKLOG_PERSISTENCE"
    assert workflow.states[str(project_id)]["fsm_state"] == "BACKLOG_PERSISTENCE"


def test_backlog_save_rejects_incomplete_assessment(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_vision_persisted_project(repo, workflow)

    workflow.states[str(project_id)]["product_backlog_assessment"] = {
        "backlog_items": [{"title": "Seed backlog item"}],
        "is_complete": False,
    }

    response = client.post(f"/api/projects/{project_id}/backlog/save")
    assert response.status_code == 409
