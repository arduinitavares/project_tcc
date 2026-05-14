"""Tests for canonical workbench fingerprints."""

import re
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from services.agent_workbench.fingerprints import (
    canonical_hash,
    canonical_json,
    normalize_for_hash,
)


def test_canonical_hash_is_order_stable_and_prefixed() -> None:
    """Verify mapping key order does not affect hash output."""
    left = {"b": 2, "a": {"z": None, "m": [3, 2, 1]}}
    right = {"a": {"m": [3, 2, 1], "z": None}, "b": 2}
    fingerprint = canonical_hash(left)

    assert fingerprint == canonical_hash(right)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)


def test_normalize_for_hash_formats_utc_datetimes_with_z() -> None:
    """Verify datetime normalization uses deterministic UTC strings."""
    value = normalize_for_hash(
        {"created_at": datetime(2026, 5, 14, 12, 30, tzinfo=UTC)}
    )

    assert value == {"created_at": "2026-05-14T12:30:00Z"}


def test_normalize_for_hash_converts_datetimes_to_utc_and_dates_to_iso() -> None:
    """Verify temporal values normalize to stable ISO strings."""
    value = normalize_for_hash(
        {
            "due_on": date(2026, 5, 14),
            "created_at": datetime(
                2026,
                5,
                14,
                9,
                30,
                tzinfo=timezone(timedelta(hours=-3)),
            ),
        }
    )

    assert value == {
        "created_at": "2026-05-14T12:30:00Z",
        "due_on": "2026-05-14",
    }


def test_canonical_hash_preserves_null_values() -> None:
    """Verify null values remain part of the hash payload."""
    with_null = canonical_hash({"a": None})
    without_key = canonical_hash({})

    assert with_null != without_key


def test_canonical_json_sorts_stringified_mapping_keys_and_preserves_lists() -> None:
    """Verify JSON serialization uses the documented canonical shape."""
    payload = {
        2: "two",
        "10": "ten",
        "items": ["é", None, {"b": 2, "a": 1}],
    }

    assert canonical_json(payload) == (
        '{"10":"ten","2":"two","items":["\\u00e9",null,{"a":1,"b":2}]}'
    )
    assert canonical_hash({"items": [1, 2]}) != canonical_hash({"items": [2, 1]})


def test_normalize_for_hash_rejects_duplicate_stringified_mapping_keys() -> None:
    """Verify distinct keys cannot collapse during canonical normalization."""
    with pytest.raises(ValueError, match="Duplicate canonical mapping key"):
        normalize_for_hash({1: "integer key", "1": "string key"})
