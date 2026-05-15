"""Tests for context pack composition."""

from __future__ import annotations

from typing import Any

from services.agent_workbench.context_pack import ContextPackService

PROJECT_ID = 7
WORKFLOW_FINGERPRINT = "sha256:" + "1" * 64
CANDIDATES_FINGERPRINT = "sha256:" + "2" * 64
AUTHORITY_FINGERPRINT = "sha256:" + "3" * 64


class _FakeReadProjection:
    """Fake read projection used to verify bounded composition."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def workflow_state(self, *, project_id: int) -> dict[str, Any]:
        """Return a workflow state projection."""
        self.calls.append("workflow_state")
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "state": {
                    "fsm_state": "SPRINT_SETUP",
                    "setup_status": "passed",
                },
                "source_fingerprint": WORKFLOW_FINGERPRINT,
            },
            "warnings": [],
            "errors": [],
        }

    def sprint_candidates(self, *, project_id: int) -> dict[str, Any]:
        """Return a sprint candidates projection."""
        self.calls.append("sprint_candidates")
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "items": [{"story_id": 10, "story_title": "Story"}],
                "count": 1,
                "excluded_counts": {},
                "source_fingerprint": CANDIDATES_FINGERPRINT,
            },
            "warnings": [],
            "errors": [],
        }


class _NonSprintReadProjection(_FakeReadProjection):
    """Fake read projection for a non-sprint workflow state."""

    def workflow_state(self, *, project_id: int) -> dict[str, Any]:
        """Return a workflow state outside sprint planning."""
        self.calls.append("workflow_state")
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "state": {
                    "fsm_state": "VISION_INTERVIEW",
                    "setup_status": "passed",
                },
                "source_fingerprint": WORKFLOW_FINGERPRINT,
            },
            "warnings": [],
            "errors": [],
        }


class _ChangedCandidateReadProjection(_FakeReadProjection):
    """Fake read projection with a different candidate fingerprint."""

    def sprint_candidates(self, *, project_id: int) -> dict[str, Any]:
        """Return a candidate projection with changed fingerprint inputs."""
        result = super().sprint_candidates(project_id=project_id)
        result["data"]["source_fingerprint"] = "sha256:" + "9" * 64
        return result


class _FailingReadProjection(_FakeReadProjection):
    """Fake read projection that fails sprint candidate composition."""

    def sprint_candidates(self, *, project_id: int) -> dict[str, Any]:
        """Return a sentinel failure envelope."""
        self.calls.append("sprint_candidates")
        return {
            "ok": False,
            "data": None,
            "warnings": [],
            "errors": [{"code": "SCHEMA_NOT_READY", "project_id": project_id}],
        }


class _FakeAuthorityProjection:
    """Fake authority projection used to verify bounded composition."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return an authority status projection."""
        self.calls.append("status")
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "status": "current",
                "authority_fingerprint": AUTHORITY_FINGERPRINT,
            },
            "warnings": [],
            "errors": [],
        }


class _BlockingAuthorityProjection(_FakeAuthorityProjection):
    """Fake authority projection with a sprint-planning blocker."""

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return a stale authority status projection."""
        result = super().status(project_id=project_id)
        result["data"]["status"] = "stale"
        return result


class _WarningAuthorityProjection(_FakeAuthorityProjection):
    """Fake authority projection with a warning to preserve."""

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return authority status with a disk warning."""
        result = super().status(project_id=project_id)
        result["warnings"] = [
            {
                "code": "DISK_SPEC_UNREADABLE",
                "message": "Spec file could not be read.",
                "details": {"path": "specs/app.md"},
                "remediation": ["Fix the spec file path."],
            }
        ]
        return result


def test_sprint_planning_pack_filters_unimplemented_next_commands() -> None:
    """Verify next commands only include installed capabilities."""
    service = ContextPackService(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    result = service.pack(project_id=PROJECT_ID, phase="sprint-planning")

    assert result["ok"] is True
    data = result["data"]
    assert data["project_id"] == PROJECT_ID
    assert data["phase"] == "sprint-planning"
    assert data["fsm_state"] == "SPRINT_SETUP"
    assert data["next_valid_commands"] == [
        "agileforge sprint candidates --project-id 7",
    ]
    assert data["blocked_commands"] == []
    assert data["blocked_future_commands"] == [
        "agileforge sprint generate --project-id 7 --selected-story-ids 1,2,3",
    ]
    assert data["included_sections"] == [
        "workflow",
        "authority",
        "sprint_candidates",
    ]
    assert "raw_spec" in data["omitted_sections"]
    assert "authority_full" in data["omitted_sections"]
    assert data["truncation"] == []
    assert data["authority_fingerprint"] == AUTHORITY_FINGERPRINT
    assert data["source_fingerprint"].startswith("sha256:")
    assert data["phase_data"]["sprint_candidates"]["count"] == 1
    assert data["workflow"]["source_fingerprint"] == WORKFLOW_FINGERPRINT
    assert data["authority"]["authority_fingerprint"] == AUTHORITY_FINGERPRINT


def test_overview_pack_omits_sprint_phase_data() -> None:
    """Verify overview packs stay bounded to workflow and authority."""
    read_projection = _FakeReadProjection()
    service = ContextPackService(
        read_projection=read_projection,
        authority_projection=_FakeAuthorityProjection(),
    )

    result = service.pack(project_id=PROJECT_ID)

    assert result["ok"] is True
    data = result["data"]
    assert data["phase"] == "overview"
    assert data["included_sections"] == ["workflow", "authority"]
    assert data["phase_data"] == {}
    assert data["next_valid_commands"] == []
    assert data["blocked_commands"] == []
    assert data["blocked_future_commands"] == []
    assert read_projection.calls == ["workflow_state"]


def test_sprint_planning_pack_blocks_candidates_outside_sprint_state() -> None:
    """Verify non-sprint workflow states do not advertise candidate commands."""
    read_projection = _NonSprintReadProjection()
    service = ContextPackService(
        read_projection=read_projection,
        authority_projection=_FakeAuthorityProjection(),
    )

    result = service.pack(project_id=PROJECT_ID, phase="sprint-planning")

    assert result["ok"] is True
    data = result["data"]
    assert data["next_valid_commands"] == []
    assert data["blocked_future_commands"] == []
    assert data["included_sections"] == ["workflow", "authority"]
    assert data["phase_data"] == {}
    assert data["blocked_commands"] == [
        {
            "command": "agileforge sprint candidates --project-id 7",
            "reason_code": "WORKFLOW_STATE_NOT_SPRINT_PLANNING",
            "details": {"fsm_state": "VISION_INTERVIEW"},
        }
    ]
    assert read_projection.calls == ["workflow_state"]


def test_sprint_planning_pack_blocks_candidates_when_authority_blocks() -> None:
    """Verify blocking authority states use installed blocked commands."""
    read_projection = _FakeReadProjection()
    service = ContextPackService(
        read_projection=read_projection,
        authority_projection=_BlockingAuthorityProjection(),
    )

    result = service.pack(project_id=PROJECT_ID, phase="sprint-planning")

    assert result["ok"] is True
    data = result["data"]
    assert data["next_valid_commands"] == []
    assert data["blocked_future_commands"] == []
    assert data["included_sections"] == ["workflow", "authority"]
    assert data["phase_data"] == {}
    assert data["blocked_commands"] == [
        {
            "command": "agileforge sprint candidates --project-id 7",
            "reason_code": "AUTHORITY_BLOCKING_STATE",
            "details": {"authority_status": "stale"},
        }
    ]
    assert read_projection.calls == ["workflow_state"]


def test_context_pack_preserves_child_warnings_with_section_labels() -> None:
    """Verify child projection warnings remain visible to agents."""
    service = ContextPackService(
        read_projection=_FakeReadProjection(),
        authority_projection=_WarningAuthorityProjection(),
    )

    result = service.pack(project_id=PROJECT_ID, phase="sprint-planning")

    warning = {
        "section": "authority",
        "source": "authority_status",
        "code": "DISK_SPEC_UNREADABLE",
        "message": "Spec file could not be read.",
        "details": {"path": "specs/app.md"},
        "remediation": ["Fix the spec file path."],
    }
    assert result["warnings"] == [warning]
    assert result["data"]["warnings"] == [warning]


def test_context_pack_source_fingerprint_changes_with_child_inputs() -> None:
    """Verify context pack fingerprint includes child projection fingerprints."""
    first = ContextPackService(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    ).pack(project_id=PROJECT_ID, phase="sprint-planning")
    changed = ContextPackService(
        read_projection=_ChangedCandidateReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    ).pack(project_id=PROJECT_ID, phase="sprint-planning")

    assert first["data"]["source_fingerprint"].startswith("sha256:")
    assert changed["data"]["source_fingerprint"].startswith("sha256:")
    assert first["data"]["source_fingerprint"] != changed["data"]["source_fingerprint"]


def test_pack_propagates_underlying_projection_failure_unchanged() -> None:
    """Verify context packs do not wrap or hydrate failed child projections."""
    read_projection = _FailingReadProjection()
    service = ContextPackService(
        read_projection=read_projection,
        authority_projection=_FakeAuthorityProjection(),
    )

    result = service.pack(project_id=PROJECT_ID, phase="sprint-planning")

    assert result == {
        "ok": False,
        "data": None,
        "warnings": [],
        "errors": [{"code": "SCHEMA_NOT_READY", "project_id": PROJECT_ID}],
    }
