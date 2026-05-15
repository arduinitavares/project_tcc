"""Tests for the agent workbench application facade."""

from __future__ import annotations

from typing import Any

from services.agent_workbench.application import AgentWorkbenchApplication

PROJECT_ID = 7
SPEC_VERSION_ID = 3
STORY_ID = 12


class _FakeReadProjection:
    """Fake read projection used to verify facade delegation."""

    def project_list(self) -> dict[str, Any]:
        """Return a project list payload."""
        return {"ok": True, "data": {"items": []}, "warnings": [], "errors": []}

    def project_show(self, *, project_id: int) -> dict[str, Any]:
        """Return a project detail payload."""
        return {
            "ok": True,
            "data": {"project_id": project_id},
            "warnings": [],
            "errors": [],
        }

    def workflow_state(self, *, project_id: int) -> dict[str, Any]:
        """Return a workflow state payload."""
        return {
            "ok": True,
            "data": {"project_id": project_id, "state": {}},
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
            "data": {"project_id": project_id, "items": []},
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


class _FakeAuthorityProjection:
    """Fake authority projection used to verify facade delegation."""

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return an authority status payload."""
        return {
            "ok": True,
            "data": {"project_id": project_id, "status": "missing"},
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
