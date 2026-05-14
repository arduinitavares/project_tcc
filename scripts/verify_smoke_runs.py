"""Verify smoke harness JSONL output for deterministic expectations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.cli_output import emit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from pydantic import ValidationError  # noqa: E402

from utils.smoke_schema import (  # noqa: E402
    SmokeRunRecord,
    parse_smoke_run_record,
    terminal_status,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


def _read_jsonl(path: Path) -> list[SmokeRunRecord]:
    records: list[SmokeRunRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            line = line.strip()  # noqa: PLW2901
            if not line:
                continue
            try:
                raw = json.loads(line)
                records.append(parse_smoke_run_record(raw))
            except json.JSONDecodeError as exc:
                msg = f"Invalid JSON on line {idx}"
                raise ValueError(msg) from exc
            except ValidationError as exc:
                msg = f"Schema validation failed on line {idx}"
                raise ValueError(msg) from exc
    return records


def _variant_label(variant_dict: dict[str, Any]) -> str:
    """Convert variant dict to label like V110."""
    refiner = "1" if variant_dict.get("enable_refiner") else "0"
    validator = "1" if variant_dict.get("enable_spec_validator") else "0"
    raw_spec = "1" if variant_dict.get("pass_raw_spec_text") else "0"
    return f"V{refiner}{validator}{raw_spec}"


def _invest_validation_expected(variant_dict: dict[str, Any]) -> bool:
    """INVEST validation runs only when BOTH refiner AND spec_validator are enabled."""
    return bool(variant_dict.get("enable_refiner")) and bool(
        variant_dict.get("enable_spec_validator")
    )


def verify_records(records: Iterable[Any]) -> None:  # noqa: C901, PLR0912
    """Return verify records."""
    normalized: list[SmokeRunRecord] = []
    for record in records:
        if isinstance(record, SmokeRunRecord):
            normalized.append(record)
        else:
            normalized.append(parse_smoke_run_record(record))

    if not normalized:
        msg = "No records provided"
        raise AssertionError(msg)

    scenario1 = [r for r in normalized if int(r.SCENARIO_ID) == 1]
    scenario2 = [r for r in normalized if int(r.SCENARIO_ID) == 2]  # noqa: PLR2004
    scenario3 = [r for r in normalized if int(r.SCENARIO_ID) == 3]  # noqa: PLR2004

    if not scenario1 or not scenario2 or not scenario3:
        msg = "Missing scenario records for 1, 2, or 3"
        raise AssertionError(msg)

    # --- Scenario 1: Happy path with strict per-variant rules ---
    # INVEST validation expected (V110, V111): must be "success" - NOT unknown, NOT contract_failed  # noqa: E501
    # INVEST validation NOT expected (V0xx, V10x): must be "unknown" - NOT contract_failed  # noqa: E501
    scenario1_errors: list[str] = []
    for r in scenario1:
        variant = r.VARIANT.model_dump()
        status = terminal_status(r)
        label = _variant_label(variant)

        if _invest_validation_expected(variant):
            # Validator enabled → must succeed (not unknown, not failed)
            if status != "success":
                scenario1_errors.append(
                    f"{label} (validator enabled) expected 'success', got '{status}' (RUN_ID={r.RUN_ID})"  # noqa: E501
                )
        # Validator disabled → must be unknown (not failed)
        elif status == "contract_failed":
            scenario1_errors.append(
                f"{label} (validator disabled) should NOT be 'contract_failed' (RUN_ID={r.RUN_ID})"  # noqa: E501
            )
        elif status not in {"success", "unknown"}:
            scenario1_errors.append(
                f"{label} unexpected status '{status}' (RUN_ID={r.RUN_ID})"
            )

    if scenario1_errors:
        raise AssertionError("Scenario 1 failures:\n  " + "\n  ".join(scenario1_errors))

    # --- Scenario 2: Alignment rejection gate ---
    # At least some variants must hit alignment_rejected (OAuth1 feature)
    scenario2_alignment = [
        r
        for r in scenario2
        if r.METRICS.alignment_rejected is True or r.ALIGNMENT_REJECTED is True
    ]
    if not scenario2_alignment:
        msg = "Scenario 2 has zero alignment_rejected"
        raise AssertionError(msg)

    # Alignment rejected runs must have pipeline_ms=None
    for r in scenario2_alignment:
        timing = r.TIMING_MS.model_dump()
        if timing.get("pipeline_ms") is not None:
            msg = f"Scenario 2 alignment_rejected run has pipeline_ms != None (RUN_ID={r.RUN_ID})"  # noqa: E501
            raise AssertionError(
                msg
            )

    # --- Scenario 3: Acceptance gate ---
    # All variants must be acceptance_blocked (spec not accepted)
    scenario3_blocked = [
        r
        for r in scenario3
        if r.METRICS.acceptance_blocked is True or r.ACCEPTANCE_GATE_BLOCKED is True
    ]
    if len(scenario3_blocked) != len(scenario3):
        msg = f"Scenario 3 is not 100% acceptance_blocked ({len(scenario3_blocked)}/{len(scenario3)})"  # noqa: E501
        raise AssertionError(
            msg
        )

    # Acceptance blocked runs must have pipeline_ms=None
    for r in scenario3_blocked:
        timing = r.TIMING_MS.model_dump()
        if timing.get("pipeline_ms") is not None:
            msg = f"Scenario 3 acceptance_blocked run has pipeline_ms != None (RUN_ID={r.RUN_ID})"  # noqa: E501
            raise AssertionError(
                msg
            )


def main() -> None:
    """Return main."""
    parser = argparse.ArgumentParser(description="Verify smoke harness JSONL output")
    parser.add_argument("--jsonl", required=True, help="Path to smoke JSONL output")
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl).resolve()
    records = _read_jsonl(jsonl_path)
    verify_records(records)
    emit("Smoke run verification passed.")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, ValueError) as exc:
        emit(f"Verification failed: {exc}")
        sys.exit(1)
