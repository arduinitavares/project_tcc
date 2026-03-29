"""Tests for task metadata canonicalization."""

# ruff: noqa: D103, S101, I001

import json

import pytest
from pydantic import ValidationError

from utils.task_metadata import (
    TaskMetadata,
    StructuredTaskSpec,
    parse_task_metadata,
)


@pytest.mark.parametrize(
    ("raw_task_kind", "expected_task_kind"),
    [
        ("  TESTING  ", "testing"),
        ("Review", "testing"),
        ("qa", "testing"),
        ("validation", "testing"),
    ],
)
def test_structured_task_spec_canonicalizes_task_kind(
    raw_task_kind: str, expected_task_kind: str
) -> None:
    spec = StructuredTaskSpec(
        description="Add coverage",
        task_kind=raw_task_kind,
    )

    assert spec.task_kind == expected_task_kind


def test_task_metadata_canonicalizes_legacy_task_kind_values() -> None:
    metadata = TaskMetadata.model_validate({"task_kind": "  Review  "})

    assert metadata.task_kind == "testing"


def test_parse_task_metadata_canonicalizes_legacy_task_kind_values() -> None:
    metadata = parse_task_metadata(json.dumps({"task_kind": "qa"}))

    assert metadata.task_kind == "testing"


def test_task_kind_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        StructuredTaskSpec(
            description="Add coverage",
            task_kind="approval",
        )
