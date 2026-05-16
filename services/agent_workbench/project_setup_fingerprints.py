"""Shared fingerprints for project setup mutation guards."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from services.agent_workbench.fingerprints import canonical_hash

if TYPE_CHECKING:
    from pathlib import Path

PROJECT_SETUP_RETRY_COMMAND: Final[str] = "agileforge project setup retry"


def setup_retry_context_fingerprint(
    *,
    project_id: int,
    resolved_spec_path: Path,
    workflow_state: dict[str, Any],
) -> str:
    """Return the guard token required by `project setup retry`."""
    return canonical_hash(
        {
            "command": PROJECT_SETUP_RETRY_COMMAND,
            "project_id": project_id,
            "resolved_spec_path": str(resolved_spec_path),
            "spec_hash": setup_spec_hash(resolved_spec_path),
            "workflow_state": workflow_state,
        }
    )


def setup_spec_hash(path: Path) -> str:
    """Return the setup contract hash for a spec file."""
    return canonical_hash(path.read_text(encoding="utf-8"))
