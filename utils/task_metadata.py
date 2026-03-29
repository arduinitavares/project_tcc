"""Helpers and schemas for persisted task metadata."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

TASK_METADATA_VERSION = "task_metadata.v1"
TASK_KIND_VALUES = (
    "analysis",
    "design",
    "implementation",
    "testing",
    "documentation",
    "refactor",
    "other",
)
TaskKind = Literal[
    "analysis",
    "design",
    "implementation",
    "testing",
    "documentation",
    "refactor",
    "other",
]

_TASK_KIND_SYNONYMS = {
    "review": "testing",
    "qa": "testing",
    "validation": "testing",
}


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a list of strings.")

    normalized: List[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Expected a list of strings.")
        trimmed = item.strip()
        if not trimmed:
            raise ValueError("List values must not be empty.")
        if trimmed in seen:
            continue
        seen.add(trimmed)
        normalized.append(trimmed)
    return normalized


def _canonicalize_task_kind(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    return _TASK_KIND_SYNONYMS.get(normalized, normalized)


class TaskMetadata(BaseModel):
    """Canonical metadata persisted with a task row."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["task_metadata.v1"] = TASK_METADATA_VERSION
    task_kind: TaskKind = "other"
    artifact_targets: List[str] = Field(default_factory=list)
    workstream_tags: List[str] = Field(default_factory=list)
    relevant_invariant_ids: List[str] = Field(default_factory=list)
    checklist_items: List[str] = Field(default_factory=list)

    @field_validator("task_kind", mode="before")
    @classmethod
    def _validate_task_kind(cls, value: Any) -> Any:
        return _canonicalize_task_kind(value)

    @field_validator(
        "artifact_targets",
        "workstream_tags",
        "relevant_invariant_ids",
        "checklist_items",
        mode="before",
    )
    @classmethod
    def _validate_lists(cls, value: Any) -> List[str]:
        return _normalize_string_list(value)


class StructuredTaskSpec(BaseModel):
    """Structured task emitted by the sprint planner."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, description="Concrete task description.")
    task_kind: TaskKind = Field(description="Primary task category.")
    artifact_targets: List[str] = Field(default_factory=list)
    workstream_tags: List[str] = Field(default_factory=list)
    relevant_invariant_ids: List[str] = Field(default_factory=list)
    checklist_items: List[str] = Field(default_factory=list)

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("description must be a string.")
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("description must not be empty.")
        return trimmed

    @field_validator("task_kind", mode="before")
    @classmethod
    def _validate_task_kind(cls, value: Any) -> Any:
        return _canonicalize_task_kind(value)

    @field_validator(
        "artifact_targets",
        "workstream_tags",
        "relevant_invariant_ids",
        "checklist_items",
        mode="before",
    )
    @classmethod
    def _validate_lists(cls, value: Any) -> List[str]:
        return _normalize_string_list(value)


def canonical_task_metadata() -> TaskMetadata:
    """Return the canonical empty metadata object."""

    return TaskMetadata()


def serialize_task_metadata(metadata: TaskMetadata) -> str:
    """Return canonical serialized JSON for persisted task metadata."""

    return json.dumps(
        metadata.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_task_metadata_json() -> str:
    """Return the canonical empty metadata JSON payload."""

    return serialize_task_metadata(canonical_task_metadata())


def parse_task_metadata(
    raw_value: Optional[str],
    *,
    logger: Optional[logging.Logger] = None,
    task_id: Optional[int] = None,
) -> TaskMetadata:
    """Parse persisted task metadata with a safe fallback."""

    if not raw_value:
        if logger:
            logger.warning(
                "Task %s missing metadata_json; falling back to canonical defaults.",
                task_id,
            )
        return canonical_task_metadata()

    try:
        payload = json.loads(raw_value)
        return TaskMetadata.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        if logger:
            logger.warning(
                "Task %s has invalid metadata_json; falling back to canonical defaults: %s",
                task_id,
                exc,
            )
        return canonical_task_metadata()


def metadata_from_structured_task(task: StructuredTaskSpec) -> TaskMetadata:
    """Project planner task output into persisted metadata."""

    return TaskMetadata(
        task_kind=task.task_kind,
        artifact_targets=list(task.artifact_targets),
        workstream_tags=list(task.workstream_tags),
        relevant_invariant_ids=list(task.relevant_invariant_ids),
        checklist_items=list(task.checklist_items),
    )


def hash_task_metadata(metadata: TaskMetadata) -> str:
    """Stable hash for packet source snapshots."""

    return hashlib.sha256(serialize_task_metadata(metadata).encode("utf-8")).hexdigest()
