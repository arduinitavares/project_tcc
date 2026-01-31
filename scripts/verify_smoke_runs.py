"""Verify smoke harness JSONL output for deterministic expectations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from pydantic import ValidationError

from utils.smoke_schema import SmokeRunRecord, parse_smoke_run_record, terminal_status


def _read_jsonl(path: Path) -> List[SmokeRunRecord]:
    records: List[SmokeRunRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                records.append(parse_smoke_run_record(raw))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {idx}") from exc
            except ValidationError as exc:
                raise ValueError(f"Schema validation failed on line {idx}") from exc
    return records


def _variant_label(variant_dict: Dict[str, Any]) -> str:
    """Convert variant dict to label like V110."""
    refiner = "1" if variant_dict.get("enable_refiner") else "0"
    validator = "1" if variant_dict.get("enable_spec_validator") else "0"
    raw_spec = "1" if variant_dict.get("pass_raw_spec_text") else "0"
    return f"V{refiner}{validator}{raw_spec}"


def _invest_validation_expected(variant_dict: Dict[str, Any]) -> bool:
    """INVEST validation runs only when BOTH refiner AND spec_validator are enabled."""
    return bool(variant_dict.get("enable_refiner")) and bool(variant_dict.get("enable_spec_validator"))


def verify_records(records: Iterable[Any]) -> None:
    normalized: List[SmokeRunRecord] = []
    for record in records:
        if isinstance(record, SmokeRunRecord):
            normalized.append(record)
        else:
            normalized.append(parse_smoke_run_record(record))

    if not normalized:
        raise AssertionError("No records provided")

    scenario1 = [r for r in normalized if int(r.SCENARIO_ID) == 1]
    scenario2 = [r for r in normalized if int(r.SCENARIO_ID) == 2]
    scenario3 = [r for r in normalized if int(r.SCENARIO_ID) == 3]

    if not scenario1 or not scenario2 or not scenario3:
        raise AssertionError("Missing scenario records for 1, 2, or 3")

    # --- Scenario 1: Happy path with strict per-variant rules ---
    # INVEST validation expected (V110, V111): must be "success" - NOT unknown, NOT contract_failed
    # INVEST validation NOT expected (V0xx, V10x): must be "unknown" - NOT contract_failed
    scenario1_errors: List[str] = []
    for r in scenario1:
        variant = r.VARIANT.model_dump()
        status = terminal_status(r)
        label = _variant_label(variant)
        
        if _invest_validation_expected(variant):
            # Validator enabled → must succeed (not unknown, not failed)
            if status != "success":
                scenario1_errors.append(
                    f"{label} (validator enabled) expected 'success', got '{status}' (RUN_ID={r.RUN_ID})"
                )
        else:
            # Validator disabled → must be unknown (not failed)
            if status == "contract_failed":
                scenario1_errors.append(
                    f"{label} (validator disabled) should NOT be 'contract_failed' (RUN_ID={r.RUN_ID})"
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
        r for r in scenario2
        if r.METRICS.alignment_rejected is True or r.ALIGNMENT_REJECTED is True
    ]
    if not scenario2_alignment:
        raise AssertionError("Scenario 2 has zero alignment_rejected")
    
    # Alignment rejected runs must have pipeline_ms=None
    for r in scenario2_alignment:
        timing = r.TIMING_MS.model_dump()
        if timing.get("pipeline_ms") is not None:
            raise AssertionError(
                f"Scenario 2 alignment_rejected run has pipeline_ms != None (RUN_ID={r.RUN_ID})"
            )

    # --- Scenario 3: Acceptance gate ---
    # All variants must be acceptance_blocked (spec not accepted)
    scenario3_blocked = [
        r for r in scenario3
        if r.METRICS.acceptance_blocked is True or r.ACCEPTANCE_GATE_BLOCKED is True
    ]
    if len(scenario3_blocked) != len(scenario3):
        raise AssertionError(
            f"Scenario 3 is not 100% acceptance_blocked ({len(scenario3_blocked)}/{len(scenario3)})"
        )
    
    # Acceptance blocked runs must have pipeline_ms=None
    for r in scenario3_blocked:
        timing = r.TIMING_MS.model_dump()
        if timing.get("pipeline_ms") is not None:
            raise AssertionError(
                f"Scenario 3 acceptance_blocked run has pipeline_ms != None (RUN_ID={r.RUN_ID})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify smoke harness JSONL output")
    parser.add_argument("--jsonl", required=True, help="Path to smoke JSONL output")
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl).resolve()
    records = _read_jsonl(jsonl_path)
    verify_records(records)
    print("Smoke run verification passed.")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, ValueError) as exc:
        print(f"Verification failed: {exc}")
        sys.exit(1)
