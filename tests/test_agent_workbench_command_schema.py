"""Tests for agent workbench command schema contracts."""

from services.agent_workbench.command_registry import (
    CommandMetadata,
    command_is_available,
    installed_command_names,
    installed_commands,
)
from services.agent_workbench.command_schema import (
    _guard_policy,
    capabilities_payload,
    command_schema_payload,
)
from services.agent_workbench.error_codes import ErrorCode, error_metadata
from services.agent_workbench.version import COMMAND_VERSION, STORAGE_SCHEMA_VERSION

EXPECTED_PHASE_1_COMMAND_NAMES = {
    "agileforge status",
    "agileforge project list",
    "agileforge project show",
    "agileforge workflow state",
    "agileforge workflow next",
    "agileforge authority status",
    "agileforge authority invariants",
    "agileforge story show",
    "agileforge sprint candidates",
    "agileforge context pack",
}

EXPECTED_PHASE_2A_COMMAND_NAMES = {
    "agileforge doctor",
    "agileforge schema check",
    "agileforge capabilities",
    "agileforge command schema",
    "agileforge mutation show",
    "agileforge mutation list",
    "agileforge mutation resume",
}

EXPECTED_PHASE_1_INPUTS = {
    "agileforge status": (["project_id"], []),
    "agileforge project list": ([], []),
    "agileforge project show": (["project_id"], []),
    "agileforge workflow state": (["project_id"], []),
    "agileforge workflow next": (["project_id"], []),
    "agileforge authority status": (["project_id"], []),
    "agileforge authority invariants": (["project_id"], ["spec_version_id"]),
    "agileforge story show": (["story_id"], []),
    "agileforge sprint candidates": (["project_id"], []),
    "agileforge context pack": (["project_id"], ["phase"]),
}


def _capability_by_name() -> dict[str, dict[str, object]]:
    """Return capabilities keyed by command name."""
    payload = capabilities_payload()
    commands = payload["commands"]

    assert isinstance(commands, list)
    return {str(command["name"]): command for command in commands}


def test_installed_commands_include_contract_metadata_for_phase_1() -> None:
    """Expose stable contract metadata for existing Phase 1 commands."""
    commands = {
        command.name: command
        for command in installed_commands()
        if command.name in EXPECTED_PHASE_1_COMMAND_NAMES
    }

    assert set(commands) == EXPECTED_PHASE_1_COMMAND_NAMES
    for command in commands.values():
        assert command.command_version == COMMAND_VERSION
        assert command.stable is True
        assert command.mutates is False
        assert command.destructive is False


def test_capabilities_expose_mutation_command_mutability() -> None:
    """Expose read-only versus mutating mutation commands."""
    commands = _capability_by_name()

    assert commands["agileforge mutation show"]["mutates"] is False
    assert commands["agileforge mutation list"]["mutates"] is False
    assert commands["agileforge mutation resume"]["mutates"] is True
    assert commands["agileforge mutation resume"]["destructive"] is False


def test_capabilities_include_top_level_contract_metadata() -> None:
    """Expose capabilities payload metadata useful to agents."""
    payload = capabilities_payload()
    commands = payload["commands"]

    assert isinstance(commands, list)
    assert payload["schema_version"] == "agileforge.cli.capabilities.v1"
    assert payload["command_version"] == COMMAND_VERSION
    assert payload["storage_schema_version"] == STORAGE_SCHEMA_VERSION
    assert payload["installed_command_count"] == len(commands)


def test_phase_1_command_schema_payloads_publish_real_inputs() -> None:
    """Expose real Phase 1 CLI input contracts in command schemas."""
    for command_name, (required, optional) in EXPECTED_PHASE_1_INPUTS.items():
        payload = command_schema_payload(command_name)

        assert payload["input"]["required"] == required
        assert payload["input"]["optional"] == optional


def test_phase_1_capabilities_publish_real_inputs() -> None:
    """Expose real Phase 1 CLI input contracts in capabilities."""
    commands = _capability_by_name()

    for command_name, (required, optional) in EXPECTED_PHASE_1_INPUTS.items():
        assert commands[command_name]["input"] == {
            "required": required,
            "optional": optional,
        }


def test_command_schema_payload_describes_mutation_resume_contract() -> None:
    """Describe mutation resume inputs, errors, and envelope output."""
    payload = command_schema_payload("agileforge mutation resume")

    assert payload["name"] == "agileforge mutation resume"
    assert payload["command_version"] == COMMAND_VERSION
    assert payload["mutates"] is True
    assert payload["guard_policy"] == []
    assert payload["input"]["required"] == ["mutation_event_id"]
    assert payload["input"]["optional"] == ["correlation_id"]
    assert ErrorCode.MUTATION_RESUME_CONFLICT.value in payload["errors"]
    assert payload["output"]["envelope_schema"]["type"] == "object"


def test_command_schema_exit_codes_match_error_registry() -> None:
    """Derive command schema exit codes from registered error metadata."""
    payload = command_schema_payload("agileforge mutation resume")

    assert payload["exit_codes"] == {
        ErrorCode.MUTATION_IN_PROGRESS.value: error_metadata(
            ErrorCode.MUTATION_IN_PROGRESS
        ).default_exit_code,
        ErrorCode.MUTATION_RESUME_CONFLICT.value: error_metadata(
            ErrorCode.MUTATION_RESUME_CONFLICT
        ).default_exit_code,
    }


def test_command_schema_guard_policy_lists_enabled_guard_fields() -> None:
    """Return only enabled guard field names in command schema contracts."""
    command = CommandMetadata(
        name="agileforge future guarded command",
        mutates=True,
        phase="phase_future",
        accepts_expected_state=True,
        accepts_expected_context_fingerprint=True,
    )

    assert _guard_policy(command) == [
        "expected_state",
        "expected_context_fingerprint",
    ]


def test_phase_2a_commands_are_registered_and_available() -> None:
    """Expose Phase 2A operational command names through the registry."""
    names = installed_command_names()

    assert EXPECTED_PHASE_2A_COMMAND_NAMES.issubset(names)
    for command_name in EXPECTED_PHASE_2A_COMMAND_NAMES:
        assert command_is_available(command_name) is True
