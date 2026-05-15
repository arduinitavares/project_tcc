"""Tests for the agent workbench application facade."""

from __future__ import annotations

from typing import Any

from services.agent_workbench.application import AgentWorkbenchApplication

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
