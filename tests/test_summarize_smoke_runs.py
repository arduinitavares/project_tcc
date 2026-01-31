from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4

from scripts.summarize_smoke_runs import summarize


def _record(
    *,
    scenario_id: int = 1,
    variant: Dict[str, Any] | None = None,
    metrics: Dict[str, Any] | None = None,
    timing: Dict[str, Any] | None = None,
    error: Dict[str, Any] | None = None,
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
        "SCENARIO_ID": scenario_id,
        "VARIANT": variant,
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
        "TIMING_MS": {
            "total_ms": timing.get("total_ms", 1.0),
            "compile_ms": timing.get("compile_ms"),
            "pipeline_ms": timing.get("pipeline_ms", 1.0),
            "validation_ms": timing.get("validation_ms"),
        },
    }
    if error is not None:
        record["ERROR"] = error
    return record


def _scenario_status_counts(markdown: str, scenario_id: int) -> Dict[str, int]:
    lines = markdown.splitlines()
    header = f"### Scenario {scenario_id}"
    if header not in lines:
        raise AssertionError(f"Missing scenario section: {header}")
    start = lines.index(header) + 3
    counts: Dict[str, int] = {}
    for line in lines[start:]:
        if not line.startswith("| "):
            break
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) >= 2:
            status = parts[0]
            count = int(parts[1])
            counts[status] = count
    return counts


def _find_summary_row(markdown: str, scenario_id: int, variant_label: str) -> List[str]:
    target = f"| {scenario_id} | {variant_label} |"
    for line in markdown.splitlines():
        if line.startswith(target):
            return [part.strip() for part in line.strip("|").split("|")]
    raise AssertionError(f"Missing summary row for {scenario_id} {variant_label}")


def test_terminal_status_priority_order() -> None:
    records = [
        _record(
            metrics={"acceptance_blocked": True, "stage": "acceptance_blocked"},
            timing={"total_ms": 1.0, "pipeline_ms": None},
            error={"type": "Boom"},
        ),
        _record(
            metrics={"acceptance_blocked": True, "stage": "acceptance_blocked"},
            timing={"total_ms": 1.0, "pipeline_ms": None, "validation_ms": None},
        ),
        _record(
            metrics={"alignment_rejected": True, "stage": "alignment_rejected"},
            timing={"total_ms": 1.0, "pipeline_ms": None},
        ),
        _record(
            metrics={"stage": "pipeline_not_run"},
            timing={"total_ms": 1.0, "pipeline_ms": None},
        ),
        _record(
            metrics={"contract_passed": False},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        ),
        _record(
            metrics={"required_fields_missing_count": 1, "contract_passed": True},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        ),
        _record(
            metrics={"spec_version_id_match": False, "contract_passed": True},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        ),
        _record(
            metrics={
                "contract_passed": True,
                "required_fields_missing_count": 0,
                "spec_version_id_match": True,
                "final_story_present": True,
                "draft_present": True,
                "acceptance_blocked": False,
                "alignment_rejected": False,
            },
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        ),
    ]

    output = summarize(records)
    counts = _scenario_status_counts(output, 1)

    assert counts.get("crashed") == 1
    assert counts.get("acceptance_blocked") == 1
    assert counts.get("alignment_rejected") == 1
    assert counts.get("pipeline_not_run") == 1
    assert counts.get("contract_failed") == 1
    assert counts.get("missing_required_fields") == 1
    assert counts.get("spec_version_mismatch") == 1
    assert counts.get("success") == 1


def test_alignment_reject_percentage_computation() -> None:
    variant = {
        "enable_refiner": True,
        "enable_spec_validator": True,
        "pass_raw_spec_text": True,
    }
    records = [
        _record(
            scenario_id=2,
            variant=variant,
            metrics={"alignment_rejected": True, "stage": "alignment_rejected"},
            timing={"total_ms": 1.0, "pipeline_ms": None},
        ),
        _record(
            scenario_id=2,
            variant=variant,
            metrics={"alignment_rejected": True, "stage": "alignment_rejected"},
            timing={"total_ms": 1.0, "pipeline_ms": None},
        ),
        _record(
            scenario_id=2,
            variant=variant,
            metrics={"alignment_rejected": False},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        ),
        _record(
            scenario_id=2,
            variant=variant,
            metrics={"alignment_rejected": False},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        ),
    ]

    output = summarize(records)
    row = _find_summary_row(output, 2, "V111")
    assert row[6] == "50.0%"


def test_completed_and_crashed_counts() -> None:
    records = [
        _record(
            metrics={"contract_passed": True},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
            error={"type": "Boom"},
        ),
        _record(
            metrics={"contract_passed": True},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
            error={"type": "Boom"},
        ),
        _record(
            metrics={"contract_passed": True},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        ),
        _record(
            metrics={"contract_passed": True},
            timing={"total_ms": 2.0, "pipeline_ms": 1.0},
        ),
    ]

    output = summarize(records)
    row = _find_summary_row(output, 1, "V000")

    assert row[3] == "2"
    assert row[4] == "2"


def test_median_ignores_none() -> None:
    records = [
        _record(
            metrics={"contract_passed": True},
            timing={"total_ms": 1.0, "compile_ms": 10.0, "pipeline_ms": None},
        ),
        _record(
            metrics={"contract_passed": True},
            timing={"total_ms": 1.0, "compile_ms": None, "pipeline_ms": None},
        ),
        _record(
            metrics={"contract_passed": True},
            timing={"total_ms": 1.0, "compile_ms": 30.0, "pipeline_ms": None},
        ),
    ]

    output = summarize(records)
    row = _find_summary_row(output, 1, "V000")

    assert row[9] == "20.0"
    assert row[10] == "-"


def test_variant_labeling() -> None:
    records = [
        _record(
            variant={
                "enable_refiner": True,
                "enable_spec_validator": False,
                "pass_raw_spec_text": True,
            },
            metrics={"contract_passed": True},
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        )
    ]

    output = summarize(records)
    assert "| 1 | V101 |" in output


def test_success_gate_requires_final_story_present() -> None:
    records = [
        _record(
            metrics={
                "acceptance_blocked": False,
                "alignment_rejected": False,
                "contract_passed": True,
                "required_fields_missing_count": 0,
                "spec_version_id_match": True,
                "final_story_present": False,
            },
            timing={"total_ms": 1.0, "pipeline_ms": 1.0},
        )
    ]

    output = summarize(records)
    row = _find_summary_row(output, 1, "V000")

    assert row[7] == "0.0%"