"""Tests for the agent workbench application facade."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

import services.agent_workbench.application as application_mod
from db.migrations import ensure_schema_current
from models import db as model_db
from services.agent_workbench.application import AgentWorkbenchApplication
from services.agent_workbench.mutation_ledger import (
    MutationLedgerRepository,
    MutationStatus,
    RecoveryAction,
)
from services.agent_workbench.version import STORAGE_SCHEMA_VERSION

PROJECT_ID = 7
SPEC_VERSION_ID = 3
STORY_ID = 12
WORKFLOW_FINGERPRINT = "sha256:" + "1" * 64
CANDIDATES_FINGERPRINT = "sha256:" + "2" * 64
AUTHORITY_FINGERPRINT = "sha256:" + "3" * 64
PROJECT_FINGERPRINT = "sha256:" + "4" * 64


class _FakeReadProjection:
    """Fake read projection used to verify facade delegation."""

    def project_list(self) -> dict[str, Any]:
        """Return a project list payload."""
        return {"ok": True, "data": {"items": []}, "warnings": [], "errors": []}

    def project_show(self, *, project_id: int) -> dict[str, Any]:
        """Return a project detail payload."""
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "name": "Workbench",
                "source_fingerprint": PROJECT_FINGERPRINT,
            },
            "warnings": [],
            "errors": [],
        }

    def workflow_state(self, *, project_id: int) -> dict[str, Any]:
        """Return a workflow state payload."""
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "state": {},
                "source_fingerprint": WORKFLOW_FINGERPRINT,
            },
            "warnings": [],
            "errors": [],
        }

    def story_show(self, *, story_id: int) -> dict[str, Any]:
        """Return a story detail payload."""
        return {
            "ok": True,
            "data": {"story_id": story_id},
            "warnings": [],
            "errors": [],
        }

    def sprint_candidates(self, *, project_id: int) -> dict[str, Any]:
        """Return a sprint candidate payload."""
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "items": [],
                "count": 0,
                "excluded_counts": {},
                "source_fingerprint": CANDIDATES_FINGERPRINT,
            },
            "warnings": [],
            "errors": [],
        }


class _FalseyReadProjection(_FakeReadProjection):
    """Falsey read projection used to verify explicit dependency checks."""

    def __bool__(self) -> bool:
        """Return false to catch truthiness-based dependency selection."""
        return False

    def project_list(self) -> dict[str, Any]:
        """Return a sentinel project list payload."""
        return {
            "ok": True,
            "data": {"sentinel": "falsey-read"},
            "warnings": [],
            "errors": [],
        }


class _SprintReadyReadProjection(_FakeReadProjection):
    """Fake read projection for sprint-planning-valid workflow state."""

    def workflow_state(self, *, project_id: int) -> dict[str, Any]:
        """Return sprint setup workflow state."""
        result = super().workflow_state(project_id=project_id)
        result["data"]["state"] = {
            "fsm_state": "SPRINT_SETUP",
            "setup_status": "passed",
        }
        return result


class _ChangedProjectReadProjection(_FakeReadProjection):
    """Fake read projection with a changed project fingerprint."""

    def project_show(self, *, project_id: int) -> dict[str, Any]:
        """Return project detail payload with changed fingerprint inputs."""
        result = super().project_show(project_id=project_id)
        result["data"]["source_fingerprint"] = "sha256:" + "8" * 64
        return result


class _ChangedCandidateReadProjection(_SprintReadyReadProjection):
    """Fake read projection with a changed candidate fingerprint."""

    def sprint_candidates(self, *, project_id: int) -> dict[str, Any]:
        """Return candidate payload with changed fingerprint inputs."""
        result = super().sprint_candidates(project_id=project_id)
        result["data"]["source_fingerprint"] = "sha256:" + "9" * 64
        return result


class _FakeAuthorityProjection:
    """Fake authority projection used to verify facade delegation."""

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return an authority status payload."""
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "status": "missing",
                "authority_fingerprint": AUTHORITY_FINGERPRINT,
            },
            "warnings": [],
            "errors": [],
        }

    def invariants(
        self,
        *,
        project_id: int,
        spec_version_id: int | None = None,
    ) -> dict[str, Any]:
        """Return an authority invariants payload."""
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "spec_version_id": spec_version_id,
                "invariants": [],
            },
            "warnings": [],
            "errors": [],
        }


class _CurrentAuthorityProjection(_FakeAuthorityProjection):
    """Fake authority projection that permits sprint planning."""

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return a current authority status payload."""
        result = super().status(project_id=project_id)
        result["data"]["status"] = "current"
        return result


class _FalseyAuthorityProjection(_FakeAuthorityProjection):
    """Falsey authority projection used to verify explicit dependency checks."""

    def __bool__(self) -> bool:
        """Return false to catch truthiness-based dependency selection."""
        return False

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return a sentinel authority status payload."""
        return {
            "ok": True,
            "data": {"project_id": project_id, "status": "falsey-authority"},
            "warnings": [],
            "errors": [],
        }


def test_application_delegates_to_read_projection() -> None:
    """Verify application facade is thin and explicit."""
    app = AgentWorkbenchApplication(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    assert app.project_list()["data"]["items"] == []
    assert app.project_show(project_id=PROJECT_ID)["data"]["project_id"] == PROJECT_ID
    assert app.workflow_state(project_id=PROJECT_ID)["data"]["state"] == {}
    assert app.story_show(story_id=STORY_ID)["data"]["story_id"] == STORY_ID
    assert app.sprint_candidates(project_id=PROJECT_ID)["data"]["items"] == []


def test_application_delegates_to_authority_projection() -> None:
    """Verify authority projections stay behind the facade."""
    app = AgentWorkbenchApplication(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    assert app.authority_status(project_id=PROJECT_ID)["data"]["status"] == "missing"
    assert app.authority_invariants(
        project_id=PROJECT_ID,
        spec_version_id=SPEC_VERSION_ID,
    )["data"] == {
        "project_id": PROJECT_ID,
        "spec_version_id": SPEC_VERSION_ID,
        "invariants": [],
    }


def test_application_keeps_falsey_injected_dependencies() -> None:
    """Verify explicit None checks preserve falsey injected projections."""
    app = AgentWorkbenchApplication(
        read_projection=_FalseyReadProjection(),
        authority_projection=_FalseyAuthorityProjection(),
    )

    assert app.project_list()["data"] == {"sentinel": "falsey-read"}
    assert app.authority_status(project_id=PROJECT_ID)["data"]["status"] == (
        "falsey-authority"
    )


def test_application_context_pack_facade_composes_sprint_planning_pack() -> None:
    """Verify context pack facade returns bounded sprint-planning data."""
    app = AgentWorkbenchApplication(
        read_projection=_SprintReadyReadProjection(),
        authority_projection=_CurrentAuthorityProjection(),
    )

    result = app.context_pack(project_id=PROJECT_ID, phase="sprint-planning")

    assert result["ok"] is True
    data = result["data"]
    assert data["phase"] == "sprint-planning"
    assert data["included_sections"] == [
        "workflow",
        "authority",
        "sprint_candidates",
    ]
    assert data["next_valid_commands"] == [
        "agileforge sprint candidates --project-id 7",
    ]
    assert data["blocked_commands"] == []
    assert data["blocked_future_commands"] == [
        "agileforge sprint generate --project-id 7 --selected-story-ids 1,2,3",
    ]


def test_application_status_combines_project_workflow_and_authority() -> None:
    """Verify status facade combines orientation projections."""
    app = AgentWorkbenchApplication(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    result = app.status(project_id=PROJECT_ID)

    assert result == {
        "ok": True,
        "data": {
            "project": {
                "project_id": PROJECT_ID,
                "name": "Workbench",
                "source_fingerprint": PROJECT_FINGERPRINT,
            },
            "workflow": {
                "project_id": PROJECT_ID,
                "state": {},
                "source_fingerprint": WORKFLOW_FINGERPRINT,
            },
            "authority": {
                "project_id": PROJECT_ID,
                "status": "missing",
                "authority_fingerprint": AUTHORITY_FINGERPRINT,
            },
            "source_fingerprint": result["data"]["source_fingerprint"],
        },
        "warnings": [],
        "errors": [],
    }
    assert result["data"]["source_fingerprint"].startswith("sha256:")


def test_application_status_fingerprint_changes_with_child_inputs() -> None:
    """Verify status source fingerprint includes child fingerprints."""
    first = AgentWorkbenchApplication(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    ).status(project_id=PROJECT_ID)
    changed = AgentWorkbenchApplication(
        read_projection=_ChangedProjectReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    ).status(project_id=PROJECT_ID)

    assert first["data"]["source_fingerprint"].startswith("sha256:")
    assert changed["data"]["source_fingerprint"].startswith("sha256:")
    assert first["data"]["source_fingerprint"] != changed["data"]["source_fingerprint"]


def test_application_workflow_next_derives_from_sprint_planning_pack() -> None:
    """Verify workflow next facade exposes installed and blocked next commands."""
    app = AgentWorkbenchApplication(
        read_projection=_SprintReadyReadProjection(),
        authority_projection=_CurrentAuthorityProjection(),
    )

    result = app.workflow_next(project_id=PROJECT_ID)

    assert result == {
        "ok": True,
        "data": {
            "project_id": PROJECT_ID,
            "next_valid_commands": ["agileforge sprint candidates --project-id 7"],
            "blocked_commands": [],
            "blocked_future_commands": [
                "agileforge sprint generate --project-id 7 --selected-story-ids 1,2,3",
            ],
            "source_fingerprint": result["data"]["source_fingerprint"],
        },
        "warnings": [],
        "errors": [],
    }
    assert result["data"]["source_fingerprint"].startswith("sha256:")


def test_application_workflow_next_fingerprint_changes_with_pack_inputs() -> None:
    """Verify workflow next fingerprint includes context pack inputs."""
    first = AgentWorkbenchApplication(
        read_projection=_SprintReadyReadProjection(),
        authority_projection=_CurrentAuthorityProjection(),
    ).workflow_next(project_id=PROJECT_ID)
    changed = AgentWorkbenchApplication(
        read_projection=_ChangedCandidateReadProjection(),
        authority_projection=_CurrentAuthorityProjection(),
    ).workflow_next(project_id=PROJECT_ID)

    assert first["data"]["source_fingerprint"].startswith("sha256:")
    assert changed["data"]["source_fingerprint"].startswith("sha256:")
    assert first["data"]["source_fingerprint"] != changed["data"]["source_fingerprint"]


def test_application_diagnostics_facades_return_envelopes(engine: Engine) -> None:
    """Expose diagnostics payloads through application envelopes."""
    ensure_schema_current(engine)
    app = AgentWorkbenchApplication(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    doctor = app.doctor(business_engine=engine, session_db_url="sqlite:///:memory:")
    schema_check = app.schema_check(
        business_engine=engine,
        session_db_url="sqlite:///:memory:",
    )

    assert doctor["ok"] is True
    assert doctor["warnings"] == []
    assert doctor["errors"] == []
    assert doctor["data"]["central_repo_root"]["status"] == "ok"
    assert doctor["data"]["caller_cwd"]["status"] == "ok"

    assert schema_check == {
        "ok": True,
        "data": schema_check["data"],
        "warnings": [],
        "errors": [],
    }
    assert schema_check["data"]["business_db"]["required_version"] == (
        STORAGE_SCHEMA_VERSION
    )
    assert schema_check["data"]["business_db"]["status"] == "ok"


def test_default_application_doctor_does_not_initialize_read_projections(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow injected diagnostics to run without default read projection DB access."""
    ensure_schema_current(engine)

    def guarded_get_engine() -> Engine:
        message = "default projection DB access should be lazy"
        raise AssertionError(message)

    monkeypatch.setattr(model_db, "get_engine", guarded_get_engine)

    result = AgentWorkbenchApplication().doctor(
        business_engine=engine,
        session_db_url="sqlite:///:memory:",
    )

    assert result["ok"] is True
    assert result["data"]["business_db"]["status"] == "ok"


def test_application_contract_facades_return_envelopes() -> None:
    """Expose capabilities and command schema through application envelopes."""
    app = AgentWorkbenchApplication(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    capabilities = app.capabilities()
    command_schema = app.command_schema("agileforge status")

    assert capabilities["ok"] is True
    assert capabilities["warnings"] == []
    assert capabilities["errors"] == []
    assert capabilities["data"]["installed_command_count"] >= 1

    assert command_schema == {
        "ok": True,
        "data": command_schema["data"],
        "warnings": [],
        "errors": [],
    }
    assert command_schema["data"]["name"] == "agileforge status"


def test_application_unknown_command_schema_uses_registered_error() -> None:
    """Unknown command schema requests use registry-backed error metadata."""
    app = AgentWorkbenchApplication(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    result = app.command_schema("agileforge not installed")

    assert result["ok"] is False
    assert result["data"] == {}
    assert result["warnings"] == []
    assert result["errors"] == [
        {
            "code": "COMMAND_NOT_IMPLEMENTED",
            "message": "Unknown command: agileforge not installed",
            "details": {"command_name": "agileforge not installed"},
            "remediation": ["agileforge capabilities"],
            "exit_code": 2,
            "retryable": False,
        }
    ]


def test_application_mutation_facades_return_ledger_envelopes(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose mutation ledger operational methods through the facade."""
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(application_mod, "get_engine", lambda: engine, raising=False)
    repo = MutationLedgerRepository(engine=engine)
    row = repo.create_or_load(
        command="agileforge fake mutate",
        idempotency_key="fake-key-001",
        request_hash="sha256:req",
        project_id=PROJECT_ID,
        correlation_id="corr-1",
        changed_by="cli-agent",
        lease_owner="worker-1",
        now=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
        lease_seconds=1,
    ).ledger
    assert row.mutation_event_id is not None
    repo._force_recovery_required_for_test(
        mutation_event_id=row.mutation_event_id,
        recovery_action=RecoveryAction.RESUME_FROM_STEP,
        safe_to_auto_resume=True,
        last_error={"code": "CRASHED"},
        now=datetime(2026, 5, 15, 12, 0, 2, tzinfo=UTC),
    )
    app = AgentWorkbenchApplication()

    show = app.mutation_show(mutation_event_id=row.mutation_event_id)
    listed = app.mutation_list(project_id=PROJECT_ID, status="recovery_required")
    resumed = app.mutation_resume(
        mutation_event_id=row.mutation_event_id,
        correlation_id="corr-resume",
    )

    assert show["ok"] is True
    assert show["data"]["mutation_event_id"] == row.mutation_event_id
    assert listed["ok"] is True
    assert listed["data"]["items"][0]["mutation_event_id"] == row.mutation_event_id
    assert resumed["ok"] is True
    assert resumed["data"]["status"] == MutationStatus.PENDING.value
    assert resumed["data"]["recovery"]["domain_resume_required"] is True


def test_application_mutation_facades_report_schema_not_ready_without_creating_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation ledger facade methods should not create absent SQLite files."""
    db_path = tmp_path / "missing-ledger.sqlite3"
    missing_engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(
        application_mod,
        "get_engine",
        lambda: missing_engine,
        raising=False,
    )

    result = AgentWorkbenchApplication().mutation_list()

    assert result["ok"] is False
    assert result["data"] is None
    assert result["errors"][0]["code"] == "SCHEMA_NOT_READY"
    assert "cli_mutation_ledger" in result["errors"][0]["details"]["missing"]
    assert not db_path.exists()
