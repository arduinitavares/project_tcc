"""Tests for task status CLI normalization."""

import pytest

from models.enums import TaskStatus
from services.agent_workbench.task_status import normalize_task_status


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("To Do", TaskStatus.TO_DO),
        ("to do", TaskStatus.TO_DO),
        (" to-do ", TaskStatus.TO_DO),
        ("IN_PROGRESS", TaskStatus.IN_PROGRESS),
        ("in progress", TaskStatus.IN_PROGRESS),
        ("Done", TaskStatus.DONE),
        ("cancelled", TaskStatus.CANCELLED),
        ("CANCELLED", TaskStatus.CANCELLED),
    ],
)
def test_normalize_task_status_accepts_display_and_cli_labels(
    raw: str,
    expected: TaskStatus,
) -> None:
    """Verify task status normalization accepts documented labels."""
    assert normalize_task_status(raw) == expected


def test_normalize_task_status_rejects_invalid_label() -> None:
    """Verify invalid labels fail before Phase 2 writes."""
    with pytest.raises(ValueError, match="Invalid task status"):
        normalize_task_status("started")
