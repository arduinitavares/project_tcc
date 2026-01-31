from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-"
    r"[0-9a-fA-F]{12}$"
)


class Variant(BaseModel):
    """Variant configuration for a smoke run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    enable_refiner: Annotated[bool, Field(description="Whether story refiner is enabled")]
    enable_spec_validator: Annotated[
        bool, Field(description="Whether spec validator is enabled")
    ]
    pass_raw_spec_text: Annotated[
        bool, Field(description="Whether raw spec text is passed to the pipeline")
    ]


class TimingMs(BaseModel):
    """Timing information in milliseconds for a smoke run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    total_ms: Annotated[float, Field(description="Total runtime in milliseconds")]
    compile_ms: Annotated[
        Optional[float], Field(description="Spec compile time in milliseconds")
    ]
    pipeline_ms: Annotated[
        Optional[float], Field(description="Pipeline runtime in milliseconds")
    ]
    validation_ms: Annotated[
        Optional[float], Field(description="Validation runtime in milliseconds")
    ]


class Metrics(BaseModel):
    """Computed metrics for a smoke run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    acceptance_blocked: Annotated[bool, Field(description="Acceptance gate blocked")]
    alignment_rejected: Annotated[bool, Field(description="Alignment rejection occurred")]
    contract_passed: Annotated[
        Optional[bool], Field(description="Contract validation result")
    ]
    required_fields_missing_count: Annotated[
        Optional[int], Field(description="Count of missing required fields", ge=0)
    ]
    spec_version_id_match: Annotated[
        Optional[bool], Field(description="Spec version id match result")
    ]
    draft_present: Annotated[bool, Field(description="Draft story present")]
    refiner_output_present: Annotated[
        bool, Field(description="Refiner output object present (may be stub)")
    ]
    refiner_ran: Annotated[
        bool, Field(description="Refiner agent actually ran")
    ]
    final_story_present: Annotated[
        bool, Field(description="Final story present (refined or draft)")
    ]
    ac_count: Annotated[Optional[int], Field(description="Acceptance criteria count", ge=0)]
    alignment_issues_count: Annotated[
        int, Field(description="Alignment issues count", ge=0)
    ]
    stage: Annotated[
        Literal[
            "crashed",
            "acceptance_blocked",
            "alignment_rejected",
            "pipeline_ran",
            "pipeline_not_run",
        ],
        Field(description="Run terminal stage"),
    ]


class SmokeRunRecord(BaseModel):
    """Schema for a smoke run JSONL record."""

    model_config = ConfigDict(extra="allow", strict=True)

    RUN_ID: Annotated[str, Field(description="Run UUID", pattern=UUID_PATTERN)]
    SCENARIO_ID: Annotated[int, Field(description="Scenario identifier", ge=0)]
    VARIANT: Annotated[Variant, Field(description="Variant configuration")]
    TIMING_MS: Annotated[TimingMs, Field(description="Timing information")]
    METRICS: Annotated[Metrics, Field(description="Metrics information")]
    ERROR: Annotated[Optional[Dict[str, Any]], Field(description="Error payload")] = None
    ACCEPTANCE_GATE_BLOCKED: Annotated[
        Optional[bool], Field(description="Acceptance gate blocked flag")
    ] = None
    ALIGNMENT_REJECTED: Annotated[
        Optional[bool], Field(description="Alignment rejected flag")
    ] = None
    ALIGNMENT_ISSUES: Annotated[
        Optional[List[Any]], Field(description="Alignment issues list")
    ] = None
    DRAFT_AGENT_OUTPUT: Annotated[
        Optional[Dict[str, Any]], Field(description="Draft agent output")
    ] = None
    REFINER_OUTPUT: Annotated[
        Optional[Dict[str, Any]], Field(description="Refiner output payload")
    ] = None
    SPEC_VERSION_ID_MATCH: Annotated[
        Optional[bool], Field(description="Spec version id match")
    ] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "SmokeRunRecord":
        metrics = self.METRICS
        timing = self.TIMING_MS
        variant = self.VARIANT

        if metrics.acceptance_blocked:
            if timing.pipeline_ms is not None:
                raise ValueError("Acceptance blocked runs must have pipeline_ms=None")
            if metrics.stage != "acceptance_blocked":
                raise ValueError("Acceptance blocked runs must have stage=acceptance_blocked")

        if metrics.alignment_rejected:
            if timing.pipeline_ms is not None:
                raise ValueError("Alignment rejected runs must have pipeline_ms=None")
            if metrics.stage != "alignment_rejected":
                raise ValueError("Alignment rejected runs must have stage=alignment_rejected")

        if not variant.enable_refiner:
            if metrics.refiner_ran:
                raise ValueError("Refiner cannot run when enable_refiner is false")
            if metrics.final_story_present != metrics.draft_present:
                raise ValueError("Final story must equal draft when refiner is disabled")
            if isinstance(self.REFINER_OUTPUT, dict):
                notes = self.REFINER_OUTPUT.get("refinement_notes")
                if notes is not None and notes != "Story refiner disabled.":
                    raise ValueError("Refiner output must be stub when refiner disabled")

        if variant.enable_refiner:
            expected_final = metrics.refiner_ran or metrics.draft_present
            if metrics.final_story_present != expected_final:
                raise ValueError("Final story presence mismatch for refiner-enabled runs")

        if isinstance(self.ALIGNMENT_ISSUES, list):
            if metrics.alignment_issues_count != len(self.ALIGNMENT_ISSUES):
                raise ValueError("alignment_issues_count must match ALIGNMENT_ISSUES length")
        else:
            if metrics.alignment_issues_count != 0:
                raise ValueError("alignment_issues_count must be 0 when no alignment issues")

        return self


def parse_smoke_run_record(data: Dict[str, Any]) -> SmokeRunRecord:
    """Parse and validate a smoke run record."""

    return SmokeRunRecord.model_validate(data)


def terminal_status(record: SmokeRunRecord) -> str:
    """Return terminal status using schema-aware logic.
    
    Terminal status values:
    - crashed: Error occurred
    - acceptance_blocked: Spec authority not accepted
    - alignment_rejected: Feature violates spec authority
    - pipeline_not_run: Pipeline was not called
    - contract_failed: Contract validation explicitly failed (is_valid=False)
    - missing_required_fields: Required fields missing from story
    - spec_version_mismatch: Spec version ID mismatch
    - success: All checks passed (contract_passed=True)
    - unknown: Validation was skipped (contract_passed=None) or indeterminate
    """

    metrics = record.METRICS

    if record.ERROR is not None or metrics.stage == "crashed":
        return "crashed"
    if metrics.stage == "acceptance_blocked":
        return "acceptance_blocked"
    if metrics.stage == "alignment_rejected":
        return "alignment_rejected"
    if metrics.stage == "pipeline_not_run":
        return "pipeline_not_run"

    # contract_passed=False means explicit failure
    if metrics.contract_passed is False:
        return "contract_failed"

    missing_required = metrics.required_fields_missing_count
    if isinstance(missing_required, int) and missing_required > 0:
        return "missing_required_fields"

    if metrics.spec_version_id_match is False:
        return "spec_version_mismatch"

    # contract_passed=None means validation was skipped (unknown quality)
    if metrics.contract_passed is None:
        return "unknown"

    success = compute_success(record)
    if success is True:
        return "success"

    return "unknown"


def compute_success(record: SmokeRunRecord) -> Optional[bool]:
    """Compute success classification for a smoke run record."""

    metrics = record.METRICS

    if metrics.acceptance_blocked or metrics.alignment_rejected:
        return False

    if metrics.contract_passed is None:
        return None
    if metrics.required_fields_missing_count is None:
        return None
    if metrics.final_story_present is None:
        return None

    if not metrics.contract_passed:
        return False
    if metrics.required_fields_missing_count != 0:
        return False
    if not metrics.final_story_present:
        return False
    if metrics.spec_version_id_match is False:
        return False

    return True