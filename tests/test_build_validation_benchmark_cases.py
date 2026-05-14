"""Tests for build validation benchmark cases."""

from __future__ import annotations

import pytest  # noqa: TC002

from agile_sqlmodel import UserStory
from scripts import build_validation_benchmark_cases as builder


def _story(title: str, description: str, acceptance_criteria: str) -> UserStory:
    return UserStory(
        product_id=1,
        title=title,
        story_description=description,
        acceptance_criteria=acceptance_criteria,
    )


def test_compute_content_hash_changes_with_story_text() -> None:
    """Verify compute content hash changes with story text."""
    s1 = _story("A", "B", "C")
    s2 = _story("A", "B changed", "C")
    h1 = builder._compute_content_hash(s1)  # pylint: disable=protected-access
    h2 = builder._compute_content_hash(s2)  # pylint: disable=protected-access
    assert h1 != h2


def test_apply_no_evidence_labels_clears_labels() -> None:
    """Verify apply no evidence labels clears labels."""
    expected_pass, reasons = builder._apply_no_evidence_labels(  # pylint: disable=protected-access
        True,
        ["RULE_X"],
        "validation_evidence",
        no_evidence_labels=True,
    )
    assert expected_pass is None
    assert reasons == []


def test_apply_no_evidence_labels_keeps_non_evidence() -> None:
    """Verify apply no evidence labels keeps non evidence."""
    expected_pass, reasons = builder._apply_no_evidence_labels(  # pylint: disable=protected-access
        False,
        ["RULE_X"],
        "human_review",
        no_evidence_labels=True,
    )
    assert expected_pass is False
    assert reasons == ["RULE_X"]


def test_warn_when_all_cases_are_validation_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify warn when all cases are validation evidence."""
    rows = [
        {"label_source": "validation_evidence"},
        {"label_source": "validation_evidence"},
    ]
    builder._maybe_warn_evidence_only(rows)  # pylint: disable=protected-access
    captured = capsys.readouterr()
    assert "WARNING: All labels derive from validation_evidence" in captured.err
