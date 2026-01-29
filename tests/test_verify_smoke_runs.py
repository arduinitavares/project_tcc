from __future__ import annotations

from typing import Any, Dict, List

import pytest

from scripts.verify_smoke_runs import verify_records


def _base_record(
    *,
    scenario_id: int,
    stage: str,
    enable_refiner: bool = False,
    enable_spec_validator: bool = False,
    pass_raw_spec_text: bool = False,
    alignment_rejected: bool = False,
    acceptance_blocked: bool = False,
    contract_passed: bool | None = None,
    required_fields_missing_count: int | None = None,
    spec_version_id_match: bool | None = None,
    final_story_present: bool = True,
) -> Dict[str, Any]:
    return {
        "RUN_ID": "00000000-0000-4000-8000-000000000000",
        "SCENARIO_ID": scenario_id,
        "VARIANT": {
            "enable_refiner": enable_refiner,
            "enable_spec_validator": enable_spec_validator,
            "pass_raw_spec_text": pass_raw_spec_text,
        },
        "TIMING_MS": {
            "total_ms": 1.0,
            "compile_ms": 1.0,
            "pipeline_ms": None if stage in ("alignment_rejected", "acceptance_blocked") else 1.0,
            "validation_ms": 0.1,
        },
        "METRICS": {
            "acceptance_blocked": acceptance_blocked,
            "alignment_rejected": alignment_rejected,
            "contract_passed": contract_passed,
            "required_fields_missing_count": required_fields_missing_count,
            "spec_version_id_match": spec_version_id_match,
            "draft_present": final_story_present,
            "refiner_output_present": False,
            "refiner_ran": False,
            "final_story_present": final_story_present,
            "ac_count": 3,
            "alignment_issues_count": 0,
            "stage": stage,
        },
    }


def test_verify_records_happy_path_validator_enabled() -> None:
    """V110 (refiner+validator enabled) must be 'success'."""
    records = [
        _base_record(
            scenario_id=1,
            stage="pipeline_ran",
            enable_refiner=True,
            enable_spec_validator=True,
            contract_passed=True,
            required_fields_missing_count=0,
            spec_version_id_match=True,
        ),
        _base_record(
            scenario_id=2,
            stage="alignment_rejected",
            alignment_rejected=True,
        ),
        _base_record(
            scenario_id=3,
            stage="acceptance_blocked",
            acceptance_blocked=True,
        ),
    ]

    verify_records(records)


def test_verify_records_validator_disabled_unknown_is_acceptable() -> None:
    """V000 (validator disabled) with contract_passed=None -> 'unknown' is acceptable."""
    records = [
        _base_record(
            scenario_id=1,
            stage="pipeline_ran",
            enable_refiner=False,
            enable_spec_validator=False,
            contract_passed=None,  # Unknown - validation was skipped
            required_fields_missing_count=0,
            spec_version_id_match=True,
        ),
        _base_record(
            scenario_id=2,
            stage="alignment_rejected",
            alignment_rejected=True,
        ),
        _base_record(
            scenario_id=3,
            stage="acceptance_blocked",
            acceptance_blocked=True,
        ),
    ]

    # Should NOT raise - "unknown" is acceptable when validator is disabled
    verify_records(records)


def test_verify_records_validator_enabled_unknown_fails() -> None:
    """V110 (validator enabled) with contract_passed=None -> must fail (should be success)."""
    records = [
        _base_record(
            scenario_id=1,
            stage="pipeline_ran",
            enable_refiner=True,
            enable_spec_validator=True,
            contract_passed=None,  # Unknown - but validator was enabled!
            required_fields_missing_count=0,
            spec_version_id_match=True,
        ),
        _base_record(
            scenario_id=2,
            stage="alignment_rejected",
            alignment_rejected=True,
        ),
        _base_record(
            scenario_id=3,
            stage="acceptance_blocked",
            acceptance_blocked=True,
        ),
    ]

    with pytest.raises(AssertionError, match="validator enabled.*expected 'success'"):
        verify_records(records)


def test_verify_records_validator_disabled_contract_failed_fails() -> None:
    """V000 (validator disabled) should NOT get contract_failed."""
    records = [
        _base_record(
            scenario_id=1,
            stage="pipeline_ran",
            enable_refiner=False,
            enable_spec_validator=False,
            contract_passed=False,  # contract_failed - but validator was disabled!
            required_fields_missing_count=0,
            spec_version_id_match=True,
        ),
        _base_record(
            scenario_id=2,
            stage="alignment_rejected",
            alignment_rejected=True,
        ),
        _base_record(
            scenario_id=3,
            stage="acceptance_blocked",
            acceptance_blocked=True,
        ),
    ]

    with pytest.raises(AssertionError, match="validator disabled.*should NOT be 'contract_failed'"):
        verify_records(records)


def test_verify_records_fails_on_missing_alignment_reject() -> None:
    records = [
        _base_record(
            scenario_id=1,
            stage="pipeline_ran",
            enable_refiner=True,
            enable_spec_validator=True,
            contract_passed=True,
            required_fields_missing_count=0,
            spec_version_id_match=True,
        ),
        _base_record(
            scenario_id=2,
            stage="pipeline_ran",
            contract_passed=True,
            required_fields_missing_count=0,
            spec_version_id_match=True,
        ),
        _base_record(
            scenario_id=3,
            stage="acceptance_blocked",
            acceptance_blocked=True,
        ),
    ]

    with pytest.raises(AssertionError, match="zero alignment_rejected"):
        verify_records(records)


def test_verify_records_fails_on_scenario_3_not_all_blocked() -> None:
    records = [
        _base_record(
            scenario_id=1,
            stage="pipeline_ran",
            enable_refiner=True,
            enable_spec_validator=True,
            contract_passed=True,
            required_fields_missing_count=0,
            spec_version_id_match=True,
        ),
        _base_record(
            scenario_id=2,
            stage="alignment_rejected",
            alignment_rejected=True,
        ),
        _base_record(
            scenario_id=3,
            stage="pipeline_ran",
            contract_passed=True,
            required_fields_missing_count=0,
            spec_version_id_match=True,
        ),
    ]

    with pytest.raises(AssertionError, match="not 100% acceptance_blocked"):
        verify_records(records)
