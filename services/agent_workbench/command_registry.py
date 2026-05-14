"""Installed command metadata for the agent workbench."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandMetadata:
    """Metadata for an installed workbench command."""

    name: str
    mutates: bool
    phase: str


_PHASE_1_COMMANDS: tuple[CommandMetadata, ...] = (
    CommandMetadata(name="tcc status", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc project list", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc project show", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc workflow state", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc workflow next", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc authority status", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc authority invariants", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc story show", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc sprint candidates", mutates=False, phase="phase_1"),
    CommandMetadata(name="tcc context pack", mutates=False, phase="phase_1"),
)


def installed_commands() -> tuple[CommandMetadata, ...]:
    """Return installed command metadata for the current workbench phase."""
    return _PHASE_1_COMMANDS


def installed_command_names() -> set[str]:
    """Return names for installed commands."""
    return {command.name for command in installed_commands()}


def command_is_available(name: str) -> bool:
    """Return whether a command is installed."""
    return name in installed_command_names()
