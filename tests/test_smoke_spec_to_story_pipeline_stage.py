from __future__ import annotations

from typing import Any, Dict

from scripts.smoke_spec_to_story_pipeline import _finalize_stage


def _metrics(
    *,
    acceptance_blocked: bool = False,
    alignment_rejected: bool = False,
) -> Dict[str, Any]:
    return {
        "acceptance_blocked": acceptance_blocked,
        "alignment_rejected": alignment_rejected,
    }


def test_finalize_stage_pipeline_called_alignment_rejected() -> None:
    assert (
        _finalize_stage(_metrics(alignment_rejected=True), pipeline_called=True)
        == "alignment_rejected"
    )


def test_finalize_stage_pipeline_called_acceptance_blocked() -> None:
    assert (
        _finalize_stage(_metrics(acceptance_blocked=True), pipeline_called=True)
        == "acceptance_blocked"
    )


def test_finalize_stage_pipeline_called_success() -> None:
    assert _finalize_stage(_metrics(), pipeline_called=True) == "pipeline_ran"


def test_finalize_stage_pipeline_not_called_alignment_rejected() -> None:
    assert (
        _finalize_stage(_metrics(alignment_rejected=True), pipeline_called=False)
        == "alignment_rejected"
    )


def test_finalize_stage_pipeline_not_called_acceptance_blocked() -> None:
    assert (
        _finalize_stage(_metrics(acceptance_blocked=True), pipeline_called=False)
        == "acceptance_blocked"
    )


def test_finalize_stage_pipeline_not_called_default() -> None:
    assert _finalize_stage(_metrics(), pipeline_called=False) == "pipeline_not_run"
