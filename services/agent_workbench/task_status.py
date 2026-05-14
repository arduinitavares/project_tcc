"""Task status normalization for CLI stale-write checks."""

from models.enums import TaskStatus

_TASK_STATUS_LABELS: dict[str, TaskStatus] = {
    "to do": TaskStatus.TO_DO,
    "in progress": TaskStatus.IN_PROGRESS,
    "done": TaskStatus.DONE,
    "cancelled": TaskStatus.CANCELLED,
}


def _normalize_label(value: str) -> str:
    """Normalize CLI label spelling differences."""
    return " ".join(value.strip().replace("_", " ").replace("-", " ").split()).lower()


def normalize_task_status(value: str) -> TaskStatus:
    """Normalize a CLI task status label into the persisted enum."""
    normalized = _normalize_label(value)
    try:
        return _TASK_STATUS_LABELS[normalized]
    except KeyError as exc:
        allowed = ", ".join(
            sorted(status.value for status in _TASK_STATUS_LABELS.values())
        )
        msg = f"Invalid task status {value!r}. Expected one of: {allowed}."
        raise ValueError(msg) from exc
