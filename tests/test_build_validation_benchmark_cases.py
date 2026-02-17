from __future__ import annotations

from types import SimpleNamespace

from scripts import build_validation_benchmark_cases as builder


def _story(title: str, description: str, acceptance_criteria: str):
    return SimpleNamespace(
        title=title,
        story_description=description,
        acceptance_criteria=acceptance_criteria,
    )


def test_compute_content_hash_changes_with_story_text() -> None:
    s1 = _story("A", "B", "C")
    s2 = _story("A", "B changed", "C")
    h1 = builder._compute_content_hash(s1)  # pylint: disable=protected-access
    h2 = builder._compute_content_hash(s2)  # pylint: disable=protected-access
    assert h1 != h2


def test_apply_no_evidence_labels_clears_labels() -> None:
    expected_pass, reasons = builder._apply_no_evidence_labels(  # pylint: disable=protected-access
        True,
        ["RULE_X"],
        "validation_evidence",
        no_evidence_labels=True,
    )
    assert expected_pass is None
    assert reasons == []


def test_apply_no_evidence_labels_keeps_non_evidence() -> None:
    expected_pass, reasons = builder._apply_no_evidence_labels(  # pylint: disable=protected-access
        False,
        ["RULE_X"],
        "human_review",
        no_evidence_labels=True,
    )
    assert expected_pass is False
    assert reasons == ["RULE_X"]


def test_warn_when_all_cases_are_validation_evidence(capsys) -> None:
    rows = [
        {"label_source": "validation_evidence"},
        {"label_source": "validation_evidence"},
    ]
    builder._maybe_warn_evidence_only(rows)  # pylint: disable=protected-access
    captured = capsys.readouterr()
    assert "WARNING: All labels derive from validation_evidence" in captured.err
