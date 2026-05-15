"""Installed command metadata for the agent workbench."""

from dataclasses import dataclass

from services.agent_workbench.error_codes import ErrorCode
from services.agent_workbench.version import COMMAND_VERSION


@dataclass(frozen=True)
class CommandMetadata:
    """Metadata for an installed workbench command."""

    name: str
    mutates: bool
    phase: str
    command_version: str = COMMAND_VERSION
    stable: bool = True
    destructive: bool = False
    accepts_expected_state: bool = False
    accepts_expected_artifact_fingerprint: bool = False
    accepts_expected_context_fingerprint: bool = False
    accepts_expected_authority_version: bool = False
    requires_idempotency_key: bool = False
    input_required: tuple[str, ...] = ()
    input_optional: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


_PHASE_1_COMMANDS: tuple[CommandMetadata, ...] = (
    CommandMetadata(
        name="agileforge status",
        mutates=False,
        phase="phase_1",
        input_required=("project_id",),
    ),
    CommandMetadata(name="agileforge project list", mutates=False, phase="phase_1"),
    CommandMetadata(
        name="agileforge project show",
        mutates=False,
        phase="phase_1",
        input_required=("project_id",),
    ),
    CommandMetadata(
        name="agileforge workflow state",
        mutates=False,
        phase="phase_1",
        input_required=("project_id",),
    ),
    CommandMetadata(
        name="agileforge workflow next",
        mutates=False,
        phase="phase_1",
        input_required=("project_id",),
    ),
    CommandMetadata(
        name="agileforge authority status",
        mutates=False,
        phase="phase_1",
        input_required=("project_id",),
    ),
    CommandMetadata(
        name="agileforge authority invariants",
        mutates=False,
        phase="phase_1",
        input_required=("project_id",),
        input_optional=("spec_version_id",),
    ),
    CommandMetadata(
        name="agileforge story show",
        mutates=False,
        phase="phase_1",
        input_required=("story_id",),
    ),
    CommandMetadata(
        name="agileforge sprint candidates",
        mutates=False,
        phase="phase_1",
        input_required=("project_id",),
    ),
    CommandMetadata(
        name="agileforge context pack",
        mutates=False,
        phase="phase_1",
        input_required=("project_id",),
        input_optional=("phase",),
    ),
)

_PHASE_2A_COMMANDS: tuple[CommandMetadata, ...] = (
    CommandMetadata(name="agileforge doctor", mutates=False, phase="phase_2a"),
    CommandMetadata(name="agileforge schema check", mutates=False, phase="phase_2a"),
    CommandMetadata(name="agileforge capabilities", mutates=False, phase="phase_2a"),
    CommandMetadata(
        name="agileforge command schema",
        mutates=False,
        phase="phase_2a",
        input_required=("command_name",),
    ),
    CommandMetadata(
        name="agileforge mutation show",
        mutates=False,
        phase="phase_2a",
        input_required=("mutation_event_id",),
    ),
    CommandMetadata(
        name="agileforge mutation list",
        mutates=False,
        phase="phase_2a",
        input_optional=("project_id", "status"),
    ),
    CommandMetadata(
        name="agileforge mutation resume",
        mutates=True,
        phase="phase_2a",
        input_required=("mutation_event_id",),
        input_optional=("correlation_id",),
        errors=(
            ErrorCode.MUTATION_IN_PROGRESS.value,
            ErrorCode.MUTATION_RESUME_CONFLICT.value,
        ),
    ),
)


def installed_commands() -> tuple[CommandMetadata, ...]:
    """Return installed command metadata for the current workbench phase."""
    return (*_PHASE_1_COMMANDS, *_PHASE_2A_COMMANDS)


def installed_command_names() -> set[str]:
    """Return names for installed commands."""
    return {command.name for command in installed_commands()}


def command_is_available(name: str) -> bool:
    """Return whether a command is installed."""
    return name in installed_command_names()
