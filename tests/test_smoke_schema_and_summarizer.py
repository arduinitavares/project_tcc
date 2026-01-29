from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4

import pytest
from pydantic import ValidationError

from scripts.summarize_smoke_runs import summarize
from utils.smoke_schema import parse_smoke_run_record, terminal_status, compute_success


def _record(
    *,
    variant: Dict[str, Any] | None = None,
    metrics: Dict[str, Any] | None = None,
    timing: Dict[str, Any] | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if variant is None:
        variant = {
            "enable_refiner": False,
            "enable_spec_validator": False,
            "pass_raw_spec_text": False,
        }
    if metrics is None:
        metrics = {}
    if timing is None:
        timing = {}
    record: Dict[str, Any] = {
        "RUN_ID": str(uuid4()),
        "SCENARIO_ID": 1,
        "VARIANT": variant,
        "TIMING_MS": {
            "total_ms": timing.get("total_ms", 10.0),
            "compile_ms": timing.get("compile_ms"),
            "pipeline_ms": timing.get("pipeline_ms", 5.0),
            "validation_ms": timing.get("validation_ms"),
        },
        "METRICS": {
            "acceptance_blocked": metrics.get("acceptance_blocked", False),
            "alignment_rejected": metrics.get("alignment_rejected", False),
            "contract_passed": metrics.get("contract_passed"),
            "required_fields_missing_count": metrics.get("required_fields_missing_count"),
            "spec_version_id_match": metrics.get("spec_version_id_match"),
            "draft_present": metrics.get("draft_present", False),
            "refiner_output_present": metrics.get("refiner_output_present", False),
            "refiner_ran": metrics.get("refiner_ran", False),
            "final_story_present": metrics.get("final_story_present", False),
            "ac_count": metrics.get("ac_count"),
            "alignment_issues_count": metrics.get("alignment_issues_count", 0),
            "stage": metrics.get("stage", "pipeline_ran"),
        },
    }
    if extra:
        record.update(extra)
    return record


def _summary_row(markdown: str, scenario_id: int, variant_label: str) -> List[str]:
    target = f"| {scenario_id} | {variant_label} |"
    for line in markdown.splitlines():
        if line.startswith(target):
            return [part.strip() for part in line.strip("|").split("|")]
    raise AssertionError("Summary row not found")


def _status_counts(markdown: str, scenario_id: int) -> Dict[str, int]:
    lines = markdown.splitlines()
    header = f"### Scenario {scenario_id}"
    start = lines.index(header) + 3
    counts: Dict[str, int] = {}
    for line in lines[start:]:
        if not line.startswith("| "):
            break
        parts = [part.strip() for part in line.strip("|").split("|")]
        counts[parts[0]] = int(parts[1])
    return counts


def test_refiner_disabled_stub_does_not_count_as_refiner_ran() -> None:
    record = _record(
        variant={
            "enable_refiner": False,
            "enable_spec_validator": False,
            "pass_raw_spec_text": False,
        },
        metrics={
            "contract_passed": True,
            "required_fields_missing_count": 0,
            "spec_version_id_match": True,
            "draft_present": True,
            "refiner_output_present": True,
            "refiner_ran": False,
            "final_story_present": True,
        },
        extra={
            "REFINER_OUTPUT": {"refinement_notes": "Story refiner disabled."},
        },
    )

    parsed = parse_smoke_run_record(record)
    assert parsed.METRICS.refiner_ran is False
    assert parsed.METRICS.final_story_present is True


def test_refiner_disabled_but_refiner_ran_true_is_rejected() -> None:
    record = _record(
        variant={
            "enable_refiner": False,
            "enable_spec_validator": False,
            "pass_raw_spec_text": False,
        },
        metrics={
            "contract_passed": True,
            "required_fields_missing_count": 0,
            "spec_version_id_match": True,
            "draft_present": True,
            "refiner_output_present": True,
            "refiner_ran": True,
            "final_story_present": True,
        },
        extra={
            "REFINER_OUTPUT": {"refinement_notes": "Story refiner disabled."},
        },
    )

    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_alignment_rejected_requires_pipeline_ms_none() -> None:
    record = _record(
        metrics={
            "alignment_rejected": True,
            "stage": "alignment_rejected",
        },
        timing={"pipeline_ms": 123.0},
    )

    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_summarizer_uses_terminal_status_and_success_consistently() -> None:
    records = [
        _record(
            metrics={
                "contract_passed": True,
                "required_fields_missing_count": 0,
                "spec_version_id_match": True,
                "draft_present": True,
                "final_story_present": True,
            }
        ),
        _record(
            metrics={
                "acceptance_blocked": True,
                "stage": "acceptance_blocked",
                "final_story_present": False,
            },
            timing={"pipeline_ms": None},
        ),
        _record(
            metrics={
                "alignment_rejected": True,
                "stage": "alignment_rejected",
                "final_story_present": False,
            },
            timing={"pipeline_ms": None},
        ),
    ]

    output = summarize(records)
    row = _summary_row(output, 1, "V000")
    assert row[2] == "3"
    assert row[3] == "3"
    assert row[4] == "0"
    assert row[5] == "33.3%"
    assert row[6] == "33.3%"
    assert row[7] == "33.3%"

    counts = _status_counts(output, 1)
    assert counts.get("success") == 1
    assert counts.get("acceptance_blocked") == 1
    assert counts.get("alignment_rejected") == 1


def test_acceptance_blocked_requires_correct_stage() -> None:
    """acceptance_blocked=True must have stage=acceptance_blocked."""
    record = _record(
        metrics={
            "acceptance_blocked": True,
            "stage": "pipeline_ran",  # Wrong stage
        },
        timing={"pipeline_ms": None},
    )
    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_acceptance_blocked_requires_pipeline_ms_none() -> None:
    """acceptance_blocked=True must have pipeline_ms=None."""
    record = _record(
        metrics={
            "acceptance_blocked": True,
            "stage": "acceptance_blocked",
        },
        timing={"pipeline_ms": 100.0},  # Should be None
    )
    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_alignment_rejected_requires_correct_stage() -> None:
    """alignment_rejected=True must have stage=alignment_rejected."""
    record = _record(
        metrics={
            "alignment_rejected": True,
            "stage": "pipeline_ran",  # Wrong stage
        },
        timing={"pipeline_ms": None},
    )
    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_alignment_issues_count_must_match_list_length() -> None:
    """alignment_issues_count must equal len(ALIGNMENT_ISSUES) when list present."""
    record = _record(
        metrics={
            "alignment_issues_count": 1,  # Wrong count
        },
        extra={
            "ALIGNMENT_ISSUES": [{"issue": "a"}, {"issue": "b"}],  # Length 2
        },
    )
    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_alignment_issues_count_zero_when_no_list() -> None:
    """alignment_issues_count must be 0 when ALIGNMENT_ISSUES is not a list."""
    record = _record(
        metrics={
            "alignment_issues_count": 5,  # Should be 0
        },
    )
    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_alignment_issues_count_matches_valid() -> None:
    """Valid case: alignment_issues_count matches list length."""
    record = _record(
        metrics={
            "alignment_issues_count": 2,
        },
        extra={
            "ALIGNMENT_ISSUES": [{"issue": "a"}, {"issue": "b"}],
        },
    )
    parsed = parse_smoke_run_record(record)
    assert parsed.METRICS.alignment_issues_count == 2


def test_refiner_enabled_final_story_mismatch_rejected() -> None:
    """When refiner enabled, final_story_present must equal (refiner_ran OR draft_present)."""
    record = _record(
        variant={
            "enable_refiner": True,
            "enable_spec_validator": False,
            "pass_raw_spec_text": False,
        },
        metrics={
            "draft_present": True,
            "refiner_ran": False,
            "final_story_present": False,  # Should be True (draft_present)
        },
    )
    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_refiner_disabled_final_story_mismatch_rejected() -> None:
    """When refiner disabled, final_story_present must equal draft_present."""
    record = _record(
        variant={
            "enable_refiner": False,
            "enable_spec_validator": False,
            "pass_raw_spec_text": False,
        },
        metrics={
            "draft_present": False,
            "refiner_ran": False,
            "final_story_present": True,  # Should be False (matches draft_present)
        },
    )
    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_refiner_disabled_with_real_output_rejected() -> None:
    """When refiner disabled, REFINER_OUTPUT must be stub or missing."""
    record = _record(
        variant={
            "enable_refiner": False,
            "enable_spec_validator": False,
            "pass_raw_spec_text": False,
        },
        metrics={
            "draft_present": True,
            "refiner_ran": False,
            "final_story_present": True,
        },
        extra={
            "REFINER_OUTPUT": {"refinement_notes": "Real refiner output here."},
        },
    )
    with pytest.raises(ValidationError):
        parse_smoke_run_record(record)


def test_scenario_1_happy_path_success_for_all_variants() -> None:
    variants = [
        {"enable_refiner": False, "enable_spec_validator": False, "pass_raw_spec_text": False},
        {"enable_refiner": False, "enable_spec_validator": False, "pass_raw_spec_text": True},
        {"enable_refiner": False, "enable_spec_validator": True, "pass_raw_spec_text": False},
        {"enable_refiner": False, "enable_spec_validator": True, "pass_raw_spec_text": True},
        {"enable_refiner": True, "enable_spec_validator": False, "pass_raw_spec_text": False},
        {"enable_refiner": True, "enable_spec_validator": False, "pass_raw_spec_text": True},
        {"enable_refiner": True, "enable_spec_validator": True, "pass_raw_spec_text": False},
        {"enable_refiner": True, "enable_spec_validator": True, "pass_raw_spec_text": True},
    ]

    for variant in variants:
        record = _record(
            variant=variant,
            metrics={
                "contract_passed": True,
                "required_fields_missing_count": 0,
                "spec_version_id_match": True,
                "draft_present": True,
                "refiner_output_present": variant["enable_refiner"],
                "refiner_ran": variant["enable_refiner"],
                "final_story_present": True,
                "stage": "pipeline_ran",
            },
            extra={
                "DRAFT_AGENT_OUTPUT": {"title": "Story"},
                "REFINER_OUTPUT": {"refinement_notes": "No changes needed."}
                if variant["enable_refiner"]
                else {"refinement_notes": "Story refiner disabled."},
                "VALIDATION_RESULT": {"passed": True, "missing_fields": []},
            },
        )

        parsed = parse_smoke_run_record(record)
        assert terminal_status(parsed) == "success"


def test_contract_failed_reason_breakdown() -> None:
    contract_failed = _record(
        metrics={
            "contract_passed": False,
            "required_fields_missing_count": 0,
            "spec_version_id_match": True,
            "draft_present": True,
            "final_story_present": True,
            "stage": "pipeline_ran",
        }
    )

    missing_required = _record(
        metrics={
            "contract_passed": True,
            "required_fields_missing_count": 1,
            "spec_version_id_match": True,
            "draft_present": True,
            "final_story_present": True,
            "stage": "pipeline_ran",
        }
    )

    spec_mismatch = _record(
        metrics={
            "contract_passed": True,
            "required_fields_missing_count": 0,
            "spec_version_id_match": False,
            "draft_present": True,
            "final_story_present": True,
            "stage": "pipeline_ran",
        }
    )

    final_missing = _record(
        metrics={
            "contract_passed": True,
            "required_fields_missing_count": 0,
            "spec_version_id_match": True,
            "draft_present": False,
            "final_story_present": False,
            "stage": "pipeline_ran",
        }
    )

    assert terminal_status(parse_smoke_run_record(contract_failed)) == "contract_failed"
    assert terminal_status(parse_smoke_run_record(missing_required)) == "missing_required_fields"
    assert terminal_status(parse_smoke_run_record(spec_mismatch)) == "spec_version_mismatch"
    assert terminal_status(parse_smoke_run_record(final_missing)) == "unknown"
    assert compute_success(parse_smoke_run_record(final_missing)) is False


def test_contract_passed_none_returns_unknown_status() -> None:
    """When contract_passed=None (validation skipped), terminal_status should be 'unknown'.
    
    This tests the new semantic: when enable_spec_validator=False and INVEST validation
    is skipped, is_valid=None propagates to contract_passed=None, and terminal_status
    should be 'unknown' (not 'contract_failed').
    """
    # Scenario: enable_refiner=True, enable_spec_validator=False (V100 variant)
    # Expected: contract_passed=None, terminal_status='unknown'
    record = _record(
        variant={
            "enable_refiner": True,
            "enable_spec_validator": False,
            "pass_raw_spec_text": False,
        },
        metrics={
            "contract_passed": None,  # INVEST validation was skipped
            "required_fields_missing_count": 0,
            "spec_version_id_match": True,
            "draft_present": True,
            "refiner_output_present": True,
            "refiner_ran": True,
            "final_story_present": True,
            "stage": "pipeline_ran",
        },
        extra={
            "DRAFT_AGENT_OUTPUT": {"title": "Story"},
            "REFINER_OUTPUT": {"refinement_notes": "Changes applied."},
        },
    )

    parsed = parse_smoke_run_record(record)
    assert parsed.METRICS.contract_passed is None
    assert terminal_status(parsed) == "unknown"
    # compute_success should return None when contract_passed is None (indeterminate)
    assert compute_success(parsed) is None


def test_spec_validator_disabled_does_not_produce_contract_failed() -> None:
    """Variants with enable_spec_validator=False should NOT have terminal_status='contract_failed'.
    
    This is the key test for the A/B matrix fix: when spec_validator is disabled,
    the missing INVEST validation_result should NOT cause contract enforcement to fail.
    Instead, it should result in contract_passed=None and terminal_status='unknown'.
    """
    # V100: enable_refiner=True, enable_spec_validator=False
    v100_record = _record(
        variant={
            "enable_refiner": True,
            "enable_spec_validator": False,
            "pass_raw_spec_text": False,
        },
        metrics={
            "contract_passed": None,  # Validation skipped
            "required_fields_missing_count": 0,
            "spec_version_id_match": True,
            "draft_present": True,
            "refiner_output_present": True,
            "refiner_ran": True,
            "final_story_present": True,
            "stage": "pipeline_ran",
        },
    )

    parsed = parse_smoke_run_record(v100_record)
    status = terminal_status(parsed)
    
    # Key assertion: status should NOT be 'contract_failed'
    assert status != "contract_failed", (
        f"V100 variant (spec_validator disabled) should NOT produce 'contract_failed', "
        f"got '{status}' instead"
    )
    assert status == "unknown", (
        f"V100 variant should produce 'unknown' status when validation skipped, "
        f"got '{status}' instead"
    )


def test_spec_validator_enabled_missing_validation_is_contract_failed() -> None:
    """Variants with enable_spec_validator=True should fail if validation_result is missing.
    
    When spec validator is enabled (expected to run), but contract_passed=False
    (e.g., INVEST_RESULT_MISSING violation), terminal_status should be 'contract_failed'.
    """
    # V110: enable_refiner=True, enable_spec_validator=True
    v110_record = _record(
        variant={
            "enable_refiner": True,
            "enable_spec_validator": True,
            "pass_raw_spec_text": False,
        },
        metrics={
            "contract_passed": False,  # Contract failed (e.g., INVEST_RESULT_MISSING)
            "required_fields_missing_count": 0,
            "spec_version_id_match": True,
            "draft_present": True,
            "refiner_output_present": True,
            "refiner_ran": True,
            "final_story_present": True,
            "stage": "pipeline_ran",
        },
    )

    parsed = parse_smoke_run_record(v110_record)
    assert terminal_status(parsed) == "contract_failed"
    assert compute_success(parsed) is False