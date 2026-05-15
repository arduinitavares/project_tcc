"""Agent workbench application facade."""

from __future__ import annotations

from typing import Any, Final, Protocol

from services.agent_workbench.authority_projection import AuthorityProjectionService
from services.agent_workbench.command_registry import installed_command_names
from services.agent_workbench.context_pack import ContextPackService
from services.agent_workbench.fingerprints import canonical_hash
from services.agent_workbench.read_projection import ReadProjectionService

STATUS_COMMAND: Final[str] = "tcc status"
WORKFLOW_NEXT_COMMAND: Final[str] = "tcc workflow next"


class _ReadProjection(Protocol):
    """Read projection methods exposed by the application facade."""

    def project_list(self) -> dict[str, Any]:
        """Return project list projection."""
        ...

    def project_show(self, *, project_id: int) -> dict[str, Any]:
        """Return project detail projection."""
        ...

    def workflow_state(self, *, project_id: int) -> dict[str, Any]:
        """Return workflow session projection."""
        ...

    def story_show(self, *, story_id: int) -> dict[str, Any]:
        """Return story detail projection."""
        ...

    def sprint_candidates(self, *, project_id: int) -> dict[str, Any]:
        """Return sprint candidate projection."""
        ...


class _AuthorityProjection(Protocol):
    """Authority projection methods exposed by the application facade."""

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return authority status projection."""
        ...

    def invariants(
        self,
        *,
        project_id: int,
        spec_version_id: int | None = None,
    ) -> dict[str, Any]:
        """Return authority invariants projection."""
        ...


class AgentWorkbenchApplication:
    """Thin facade shared by CLI transport and future API parity paths."""

    def __init__(
        self,
        *,
        read_projection: _ReadProjection | None = None,
        authority_projection: _AuthorityProjection | None = None,
    ) -> None:
        """Initialize the facade with explicit projection dependencies."""
        self._read_projection = (
            read_projection if read_projection is not None else ReadProjectionService()
        )
        self._authority_projection = (
            authority_projection
            if authority_projection is not None
            else AuthorityProjectionService()
        )
        self._context_pack = ContextPackService(
            read_projection=self._read_projection,
            authority_projection=self._authority_projection,
        )

    def project_list(self) -> dict[str, Any]:
        """Return project list projection."""
        return self._read_projection.project_list()

    def project_show(self, *, project_id: int) -> dict[str, Any]:
        """Return project detail projection."""
        return self._read_projection.project_show(project_id=project_id)

    def workflow_state(self, *, project_id: int) -> dict[str, Any]:
        """Return workflow session projection."""
        return self._read_projection.workflow_state(project_id=project_id)

    def story_show(self, *, story_id: int) -> dict[str, Any]:
        """Return story detail projection."""
        return self._read_projection.story_show(story_id=story_id)

    def sprint_candidates(self, *, project_id: int) -> dict[str, Any]:
        """Return sprint candidate projection."""
        return self._read_projection.sprint_candidates(project_id=project_id)

    def context_pack(
        self,
        *,
        project_id: int,
        phase: str = "overview",
    ) -> dict[str, Any]:
        """Return a phase-scoped context pack."""
        return self._context_pack.pack(project_id=project_id, phase=phase)

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return project orientation status from read-only projections."""
        project = self.project_show(project_id=project_id)
        if not project.get("ok"):
            return project

        workflow = self.workflow_state(project_id=project_id)
        if not workflow.get("ok"):
            return workflow

        authority = self.authority_status(project_id=project_id)
        if not authority.get("ok"):
            return authority

        project_data = _envelope_data(project)
        workflow_data = _envelope_data(workflow)
        authority_data = _envelope_data(authority)
        data: dict[str, Any] = {
            "project": project_data,
            "workflow": workflow_data,
            "authority": authority_data,
        }
        data["source_fingerprint"] = canonical_hash(
            {
                "command": STATUS_COMMAND,
                "project_id": project_id,
                "project": _fingerprint_input(project_data),
                "workflow": _fingerprint_input(workflow_data),
                "authority": _fingerprint_input(authority_data),
            }
        )

        return {
            "ok": True,
            "data": data,
            "warnings": [
                *_section_warnings(
                    section="project",
                    source="project_show",
                    envelope=project,
                ),
                *_section_warnings(
                    section="workflow",
                    source="workflow_state",
                    envelope=workflow,
                ),
                *_section_warnings(
                    section="authority",
                    source="authority_status",
                    envelope=authority,
                ),
            ],
            "errors": [],
        }

    def workflow_next(self, *, project_id: int) -> dict[str, Any]:
        """Return installed next commands for the current workflow state."""
        pack = self.context_pack(project_id=project_id, phase="sprint-planning")
        if not pack.get("ok"):
            return pack

        pack_data = pack["data"]
        data = {
            "project_id": project_id,
            "next_valid_commands": pack_data["next_valid_commands"],
            "blocked_commands": pack_data["blocked_commands"],
            "blocked_future_commands": pack_data["blocked_future_commands"],
        }
        data["source_fingerprint"] = canonical_hash(
            {
                "command": WORKFLOW_NEXT_COMMAND,
                "project_id": project_id,
                "context_pack": pack_data.get("source_fingerprint"),
                "authority": pack_data.get("authority_fingerprint"),
                "installed_command_names": sorted(installed_command_names()),
                "next_valid_commands": data["next_valid_commands"],
                "blocked_commands": data["blocked_commands"],
                "blocked_future_commands": data["blocked_future_commands"],
            }
        )
        return {
            "ok": True,
            "data": data,
            "warnings": pack.get("warnings", []),
            "errors": [],
        }

    def authority_status(self, *, project_id: int) -> dict[str, Any]:
        """Return authority status projection."""
        return self._authority_projection.status(project_id=project_id)

    def authority_invariants(
        self,
        *,
        project_id: int,
        spec_version_id: int | None = None,
    ) -> dict[str, Any]:
        """Return authority invariants projection."""
        return self._authority_projection.invariants(
            project_id=project_id,
            spec_version_id=spec_version_id,
        )


def _envelope_data(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return dictionary data from a successful child projection."""
    data = envelope.get("data")
    return data if isinstance(data, dict) else {}


def _fingerprint_input(data: dict[str, Any]) -> object:
    """Return the stable child fingerprint when available, else child data."""
    return data.get("source_fingerprint") or data.get("authority_fingerprint") or data


def _section_warnings(
    *,
    section: str,
    source: str,
    envelope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return child warnings with facade section labels."""
    warnings = envelope.get("warnings", [])
    if not isinstance(warnings, list):
        return []

    labeled: list[dict[str, Any]] = []
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        labeled.append({"section": section, "source": source, **warning})
    return labeled
