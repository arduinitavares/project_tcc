"""Tests for agent workbench envelope and registry contracts."""

from services.agent_workbench.command_registry import (
    command_is_available,
    installed_command_names,
    installed_commands,
)
from services.agent_workbench.envelope import (
    WorkbenchError,
    WorkbenchWarning,
    error_envelope,
    success_envelope,
)

EXPECTED_PHASE_1_COMMAND_NAMES = {
    "tcc status",
    "tcc project list",
    "tcc project show",
    "tcc workflow state",
    "tcc workflow next",
    "tcc authority status",
    "tcc authority invariants",
    "tcc story show",
    "tcc sprint candidates",
    "tcc context pack",
}


def test_success_envelope_has_stable_shape() -> None:
    """Serialize success responses with stable top-level keys."""
    envelope = success_envelope(
        command="tcc project list",
        data={"items": []},
        warnings=[
            WorkbenchWarning(
                code="EMPTY_PROJECTS",
                message="No projects exist.",
                details={"count": 0},
                remediation=[
                    "tcc project create --name Example --spec-file specs/app.md"
                ],
            )
        ],
        generated_at="2026-05-14T00:00:00Z",
    )

    assert envelope == {
        "ok": True,
        "data": {"items": []},
        "warnings": [
            {
                "code": "EMPTY_PROJECTS",
                "message": "No projects exist.",
                "details": {"count": 0},
                "remediation": [
                    "tcc project create --name Example --spec-file specs/app.md"
                ],
            }
        ],
        "errors": [],
        "meta": {
            "schema_version": "tcc.cli.v1",
            "command": "tcc project list",
            "generated_at": "2026-05-14T00:00:00Z",
        },
    }


def test_error_envelope_has_retryable_exit_code_error() -> None:
    """Serialize a singular command error with warning context."""
    envelope = error_envelope(
        command="tcc sprint candidates",
        error=WorkbenchError(
            code="PROJECT_NOT_FOUND",
            message="Project does not exist.",
            details={"project_id": "missing"},
            remediation=["tcc project list"],
            exit_code=2,
            retryable=True,
        ),
        warnings=[WorkbenchWarning(code="STALE_INDEX", message="Index is stale.")],
        generated_at="2026-05-14T00:00:00Z",
    )

    assert envelope == {
        "ok": False,
        "data": None,
        "warnings": [
            {
                "code": "STALE_INDEX",
                "message": "Index is stale.",
                "details": {},
                "remediation": [],
            }
        ],
        "errors": [
            {
                "code": "PROJECT_NOT_FOUND",
                "message": "Project does not exist.",
                "details": {"project_id": "missing"},
                "remediation": ["tcc project list"],
                "exit_code": 2,
                "retryable": True,
            }
        ],
        "meta": {
            "schema_version": "tcc.cli.v1",
            "command": "tcc sprint candidates",
            "generated_at": "2026-05-14T00:00:00Z",
        },
    }


def test_problem_to_dict_returns_shallow_copies() -> None:
    """Keep dataclass internals isolated from serialized payload mutation."""
    warning = WorkbenchWarning(
        code="WARN",
        message="Warning.",
        details={"count": 1},
        remediation=["retry"],
    )
    error = WorkbenchError(
        code="ERR",
        message="Error.",
        details={"count": 2},
        remediation=["fix"],
    )

    warning_payload = warning.to_dict()
    error_payload = error.to_dict()

    assert warning_payload["details"] == {"count": 1}
    assert warning_payload["details"] is not warning.details
    assert warning_payload["remediation"] == ["retry"]
    assert warning_payload["remediation"] is not warning.remediation
    assert error_payload["details"] == {"count": 2}
    assert error_payload["details"] is not error.details
    assert error_payload["remediation"] == ["fix"]
    assert error_payload["remediation"] is not error.remediation


def test_registry_exposes_only_phase_1_commands() -> None:
    """Expose exactly the read-only commands available in Phase 1."""
    names = installed_command_names()

    assert isinstance(names, set)
    assert names == EXPECTED_PHASE_1_COMMAND_NAMES
    assert "tcc sprint generate" not in names
    assert command_is_available("tcc sprint candidates") is True
    assert command_is_available("tcc context pack") is True
    assert command_is_available("tcc sprint generate") is False


def test_registry_metadata_has_phase_1_shape() -> None:
    """Keep registry metadata stable for every installed Phase 1 command."""
    commands = installed_commands()

    assert commands
    assert {command.name for command in commands} == EXPECTED_PHASE_1_COMMAND_NAMES
    assert all(command.phase == "phase_1" for command in commands)
    assert all(command.mutates is False for command in commands)
