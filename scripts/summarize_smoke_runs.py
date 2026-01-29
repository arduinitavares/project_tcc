"""Summarize smoke harness JSONL runs into markdown tables.

Usage:
  python scripts/summarize_smoke_runs.py --jsonl artifacts/smoke_runs.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from pydantic import ValidationError

from utils.smoke_schema import SmokeRunRecord, parse_smoke_run_record, terminal_status


def _safe_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    return None


def _safe_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    numbers = [v for v in values if isinstance(v, (int, float))]
    if not numbers:
        return None
    return float(median(numbers))


def _variant_label(variant: Dict[str, Any]) -> str:
    refiner = "1" if variant.get("enable_refiner") else "0"
    validator = "1" if variant.get("enable_spec_validator") else "0"
    raw_spec = "1" if variant.get("pass_raw_spec_text") else "0"
    return f"V{refiner}{validator}{raw_spec}"


def _get_metrics(record: SmokeRunRecord) -> Dict[str, Any]:
    return record.METRICS.model_dump()


def _get_variant(record: SmokeRunRecord) -> Dict[str, Any]:
    return record.VARIANT.model_dump()


def _get_timing(record: SmokeRunRecord) -> Dict[str, Any]:
    return record.TIMING_MS.model_dump()


def _read_jsonl(path: Path, *, skip_invalid: bool) -> List[SmokeRunRecord]:
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
                if skip_invalid:
                    continue
                raise ValueError(f"Invalid JSON on line {idx}") from exc
            except ValidationError as exc:
                if skip_invalid:
                    continue
                raise ValueError(f"Schema validation failed on line {idx}") from exc
    return records


def _group_key(record: SmokeRunRecord) -> Tuple[int, str]:
    scenario_id = int(record.SCENARIO_ID)
    variant = _get_variant(record)
    return scenario_id, _variant_label(variant)


def _format_pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0%"
    return f"{(numerator / denominator) * 100:.1f}%"


def _format_ms(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


def _format_int(value: Optional[int]) -> str:
    if value is None:
        return "-"
    return str(value)


def _bool_summary(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "-"


def _normalize_records(records: Iterable[Any]) -> List[SmokeRunRecord]:
    normalized: List[SmokeRunRecord] = []
    for record in records:
        if isinstance(record, SmokeRunRecord):
            normalized.append(record)
        else:
            normalized.append(parse_smoke_run_record(record))
    return normalized


def summarize(records: List[Dict[str, Any]]) -> str:
    normalized = _normalize_records(records)
    grouped: Dict[Tuple[int, str], List[SmokeRunRecord]] = {}
    for record in normalized:
        grouped.setdefault(_group_key(record), []).append(record)

    lines: List[str] = []
    lines.append(
        "| Scenario | Variant | Runs | Completed | Crashed | Acceptance Block % | Alignment Reject % | "
        "Success % | Median Total ms | Median Compile ms | Median Pipeline ms | Median Validation ms | Median AC Count |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    sanity_partial_groups: List[str] = []
    sanity_unknown_groups: List[str] = []

    for (scenario_id, variant_label), rows in sorted(grouped.items()):
        runs = len(rows)
        blocked = 0
        alignment = 0
        success = 0
        completed = 0
        crashed = 0
        unknown = 0

        total_ms: List[Optional[float]] = []
        compile_ms: List[Optional[float]] = []
        pipeline_ms: List[Optional[float]] = []
        validation_ms: List[Optional[float]] = []
        ac_counts: List[Optional[float]] = []

        for row in rows:
            metrics = _get_metrics(row)
            timing = _get_timing(row)

            if metrics.get("acceptance_blocked") is True or row.ACCEPTANCE_GATE_BLOCKED is True:
                blocked += 1
            if metrics.get("alignment_rejected") is True or row.ALIGNMENT_REJECTED is True:
                alignment += 1

            status = terminal_status(row)
            if status == "crashed":
                crashed += 1
            else:
                completed += 1
                if status == "success":
                    success += 1
            if status == "unknown":
                unknown += 1

            total_ms.append(_safe_float(timing.get("total_ms")))
            compile_ms.append(_safe_float(timing.get("compile_ms")))
            pipeline_ms.append(_safe_float(timing.get("pipeline_ms")))
            validation_ms.append(_safe_float(timing.get("validation_ms")))

            ac_count = _safe_int(metrics.get("ac_count"))
            ac_counts.append(float(ac_count) if ac_count is not None else None)

        if completed < runs:
            sanity_partial_groups.append(f"Scenario {scenario_id} {variant_label} ({completed}/{runs})")
        if unknown > 0:
            sanity_unknown_groups.append(f"Scenario {scenario_id} {variant_label} ({unknown} unknown)")

        success_pct = _format_pct(success, completed) if completed else "-"

        lines.append(
            "| "
            + " | ".join(
                [
                    str(scenario_id),
                    variant_label,
                    str(runs),
                    str(completed),
                    str(crashed),
                    _format_pct(blocked, runs),
                    _format_pct(alignment, runs),
                    success_pct,
                    _format_ms(_median(total_ms)),
                    _format_ms(_median(compile_ms)),
                    _format_ms(_median(pipeline_ms)),
                    _format_ms(_median(validation_ms)),
                    _format_ms(_median(ac_counts)),
                ]
            )
            + " |"
        )

    lines.append("")
    lines.append("## Terminal status counts (per scenario)")

    scenarios = sorted({int(record.SCENARIO_ID) for record in normalized})
    status_order = [
        "crashed",
        "acceptance_blocked",
        "alignment_rejected",
        "pipeline_not_run",
        "contract_failed",
        "missing_required_fields",
        "spec_version_mismatch",
        "success",
        "unknown",
    ]

    sanity_alignment_zero = False

    for scenario_id in scenarios:
        rows = [r for r in normalized if int(r.SCENARIO_ID) == scenario_id]
        counts = {status: 0 for status in status_order}
        alignment_any = 0

        for row in rows:
            status = terminal_status(row)
            counts[status] = counts.get(status, 0) + 1
            if _get_metrics(row).get("alignment_rejected") is True or row.ALIGNMENT_REJECTED is True:
                alignment_any += 1

        if scenario_id == 2 and alignment_any == 0:
            sanity_alignment_zero = True

        lines.append(f"### Scenario {scenario_id}")
        lines.append("| Status | Count |")
        lines.append("|---|---:|")
        for status in status_order:
            lines.append(f"| {status} | {counts.get(status, 0)} |")

        unknown_rows = [r for r in rows if terminal_status(r) == "unknown"]
        if unknown_rows:
            lines.append("")
            lines.append("Unknown examples:")
            for row in unknown_rows[:3]:
                metrics = _get_metrics(row)
                timing = _get_timing(row)
                run_id = row.RUN_ID
                metrics_keys = sorted(metrics.keys())
                timing_keys = sorted(timing.keys())
                draft_present = row.DRAFT_AGENT_OUTPUT is not None
                refiner_present = row.REFINER_OUTPUT is not None
                lines.append(
                    f"- RUN_ID={run_id} METRICS={metrics_keys} TIMING_MS={timing_keys} "
                    f"ALIGNMENT_REJECTED={_bool_summary(row.ALIGNMENT_REJECTED)} "
                    f"ACCEPTANCE_GATE_BLOCKED={_bool_summary(row.ACCEPTANCE_GATE_BLOCKED)} "
                    f"DRAFT_AGENT_OUTPUT={_bool_summary(draft_present)} "
                    f"REFINER_OUTPUT={_bool_summary(refiner_present)}"
                )

        lines.append("")

    # Scenario 1 contract_failed breakdown
    lines.append("## Scenario 1 contract_failed breakdown")
    scenario1_rows = [r for r in normalized if int(r.SCENARIO_ID) == 1]
    failed_rows = [r for r in scenario1_rows if terminal_status(r) == "contract_failed"]
    if not failed_rows:
        lines.append("- None")
    else:
        for row in failed_rows:
            metrics = _get_metrics(row)
            variant_label = _variant_label(_get_variant(row))
            lines.append(
                "- "
                "RUN_ID={run_id} "
                "VARIANT={variant} "
                "stage={stage} "
                "contract_passed={contract_passed} "
                "required_fields_missing_count={missing} "
                "final_story_present={final_story_present} "
                "spec_version_id_match={spec_match}"
                .format(
                    run_id=row.RUN_ID,
                    variant=variant_label,
                    stage=metrics.get("stage"),
                    contract_passed=_bool_summary(metrics.get("contract_passed")),
                    missing=_format_int(metrics.get("required_fields_missing_count")),
                    final_story_present=_bool_summary(metrics.get("final_story_present")),
                    spec_match=_bool_summary(metrics.get("spec_version_id_match")),
                )
            )

    lines.append("## Sanity warnings")
    warnings: List[str] = []
    if sanity_alignment_zero:
        warnings.append("Scenario 2 has 0 alignment_rejected across all variants.")
    if sanity_partial_groups:
        warnings.append("Groups with partial runs: " + "; ".join(sanity_partial_groups))
    if sanity_unknown_groups:
        warnings.append("Groups with unknown terminal status: " + "; ".join(sanity_unknown_groups))

    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- None")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize smoke harness JSONL runs")
    parser.add_argument("--jsonl", required=True, help="Path to smoke JSONL output")
    parser.add_argument(
        "--skip-invalid",
        action="store_true",
        help="Skip invalid JSONL rows instead of failing",
    )
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl).resolve()
    records = _read_jsonl(jsonl_path, skip_invalid=args.skip_invalid)
    if not records:
        print("No valid JSONL records found.")
        return

    print(summarize(records))


if __name__ == "__main__":
    main()
