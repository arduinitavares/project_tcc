"""Schemas and status helpers for smoke-run result records."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-"
    r"[0-9a-fA-F]{12}$"
)
_REFINER_DISABLED_NOTES = "Story refiner disabled."


class _SmokeSchemaInvariantError(ValueError):
    """Raised when a smoke run record violates schema-level invariants."""

    @classmethod
    def acceptance_blocked_pipeline_ms(cls) -> _SmokeSchemaInvariantError:
        return cls("Acceptance blocked runs must have pipeline_ms=None")

    @classmethod
    def acceptance_blocked_stage(cls) -> _SmokeSchemaInvariantError:
        return cls("Acceptance blocked runs must have stage=acceptance_blocked")

    @classmethod
    def alignment_rejected_pipeline_ms(cls) -> _SmokeSchemaInvariantError:
        return cls("Alignment rejected runs must have pipeline_ms=None")

    @classmethod
    def alignment_rejected_stage(cls) -> _SmokeSchemaInvariantError:
        return cls("Alignment rejected runs must have stage=alignment_rejected")

    @classmethod
    def refiner_disabled_but_ran(cls) -> _SmokeSchemaInvariantError:
        return cls("Refiner cannot run when enable_refiner is false")

    @classmethod
    def refiner_disabled_final_story_mismatch(cls) -> _SmokeSchemaInvariantError:
        return cls("Final story must equal draft when refiner is disabled")

    @classmethod
    def refiner_disabled_output_mismatch(cls) -> _SmokeSchemaInvariantError:
        return cls("Refiner output must be stub when refiner disabled")

    @classmethod
    def refiner_enabled_final_story_mismatch(cls) -> _SmokeSchemaInvariantError:
        return cls("Final story presence mismatch for refiner-enabled runs")

    @classmethod
    def alignment_issue_count_mismatch(cls) -> _SmokeSchemaInvariantError:
        return cls("alignment_issues_count must match ALIGNMENT_ISSUES length")

    @classmethod
    def alignment_issue_count_without_list(cls) -> _SmokeSchemaInvariantError:
        return cls("alignment_issues_count must be 0 when no alignment issues")


class Variant(BaseModel):
    """Variant configuration for a smoke run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    enable_refiner: Annotated[
        bool, Field(description="Whether story refiner is enabled")
    ]
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
        float | None, Field(description="Spec compile time in milliseconds")
    ]
    pipeline_ms: Annotated[
        float | None, Field(description="Pipeline runtime in milliseconds")
    ]
    validation_ms: Annotated[
        float | None, Field(description="Validation runtime in milliseconds")
    ]


class Metrics(BaseModel):
    """Computed metrics for a smoke run."""

    model_config = ConfigDict(extra="forbid", strict=True)

    acceptance_blocked: Annotated[bool, Field(description="Acceptance gate blocked")]
    alignment_rejected: Annotated[
        bool, Field(description="Alignment rejection occurred")
    ]
    contract_passed: Annotated[
        bool | None, Field(description="Contract validation result")
    ]
    required_fields_missing_count: Annotated[
        int | None, Field(description="Count of missing required fields", ge=0)
    ]
    spec_version_id_match: Annotated[
        bool | None, Field(description="Spec version id match result")
    ]
    draft_present: Annotated[bool, Field(description="Draft story present")]
    refiner_output_present: Annotated[
        bool, Field(description="Refiner output object present (may be stub)")
    ]
    refiner_ran: Annotated[bool, Field(description="Refiner agent actually ran")]
    final_story_present: Annotated[
        bool, Field(description="Final story present (refined or draft)")
    ]
    ac_count: Annotated[
        int | None, Field(description="Acceptance criteria count", ge=0)
    ]
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
    ERROR: Annotated[dict[str, Any] | None, Field(description="Error payload")] = None
    ACCEPTANCE_GATE_BLOCKED: Annotated[
        bool | None, Field(description="Acceptance gate blocked flag")
    ] = None
    ALIGNMENT_REJECTED: Annotated[
        bool | None, Field(description="Alignment rejected flag")
    ] = None
    ALIGNMENT_ISSUES: Annotated[
        list[Any] | None, Field(description="Alignment issues list")
    ] = None
    DRAFT_AGENT_OUTPUT: Annotated[
        dict[str, Any] | None, Field(description="Draft agent output")
    ] = None
    REFINER_OUTPUT: Annotated[
        dict[str, Any] | None, Field(description="Refiner output payload")
    ] = None
    SPEC_VERSION_ID_MATCH: Annotated[
        bool | None, Field(description="Spec version id match")
    ] = None

    def _validate_stage_invariants(self) -> None:
        metrics = self.METRICS
        pipeline_ms = self.TIMING_MS.pipeline_ms

        if metrics.acceptance_blocked:
            if pipeline_ms is not None:
                raise _SmokeSchemaInvariantError.acceptance_blocked_pipeline_ms()
            if metrics.stage != "acceptance_blocked":
                raise _SmokeSchemaInvariantError.acceptance_blocked_stage()

        if metrics.alignment_rejected:
            if pipeline_ms is not None:
                raise _SmokeSchemaInvariantError.alignment_rejected_pipeline_ms()
            if metrics.stage != "alignment_rejected":
                raise _SmokeSchemaInvariantError.alignment_rejected_stage()

    def _validate_refiner_invariants(self) -> None:
        metrics = self.METRICS
        if not self.VARIANT.enable_refiner:
            self._validate_refiner_disabled_invariants(metrics)
            return

        expected_final = metrics.refiner_ran or metrics.draft_present
        if metrics.final_story_present != expected_final:
            raise _SmokeSchemaInvariantError.refiner_enabled_final_story_mismatch()

    def _validate_refiner_disabled_invariants(self, metrics: Metrics) -> None:
        if metrics.refiner_ran:
            raise _SmokeSchemaInvariantError.refiner_disabled_but_ran()
        if metrics.final_story_present != metrics.draft_present:
            raise _SmokeSchemaInvariantError.refiner_disabled_final_story_mismatch()
        if not isinstance(self.REFINER_OUTPUT, dict):
            return

        notes = self.REFINER_OUTPUT.get("refinement_notes")
        if notes is not None and notes != _REFINER_DISABLED_NOTES:
            raise _SmokeSchemaInvariantError.refiner_disabled_output_mismatch()

    def _validate_alignment_issue_invariants(self) -> None:
        metrics = self.METRICS
        if isinstance(self.ALIGNMENT_ISSUES, list):
            if metrics.alignment_issues_count != len(self.ALIGNMENT_ISSUES):
                raise _SmokeSchemaInvariantError.alignment_issue_count_mismatch()
            return

        if metrics.alignment_issues_count != 0:
            raise _SmokeSchemaInvariantError.alignment_issue_count_without_list()

    @model_validator(mode="after")
    def _validate_invariants(self) -> SmokeRunRecord:
        self._validate_stage_invariants()
        self._validate_refiner_invariants()
        self._validate_alignment_issue_invariants()
        return self


def parse_smoke_run_record(data: dict[str, Any]) -> SmokeRunRecord:
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

    stage_status = _terminal_stage_status(record)
    if stage_status is not None:
        return stage_status

    if metrics.contract_passed is False:
        return "contract_failed"

    missing_required = metrics.required_fields_missing_count
    if isinstance(missing_required, int) and missing_required > 0:
        return "missing_required_fields"

    if metrics.spec_version_id_match is False:
        return "spec_version_mismatch"

    if metrics.contract_passed is None:
        return "unknown"

    return "success" if compute_success(record) is True else "unknown"


def compute_success(record: SmokeRunRecord) -> bool | None:
    """Compute success classification for a smoke run record."""
    metrics = record.METRICS

    if metrics.acceptance_blocked or metrics.alignment_rejected:
        return False

    if metrics.contract_passed is None:
        return None
    if metrics.required_fields_missing_count is None:
        return None

    failure_conditions = (
        not metrics.contract_passed,
        metrics.required_fields_missing_count != 0,
        not metrics.final_story_present,
        metrics.spec_version_id_match is False,
    )
    return not any(failure_conditions)


def _terminal_stage_status(record: SmokeRunRecord) -> str | None:
    metrics = record.METRICS
    if record.ERROR is not None or metrics.stage == "crashed":
        return "crashed"
    if metrics.stage == "acceptance_blocked":
        return "acceptance_blocked"
    if metrics.stage == "alignment_rejected":
        return "alignment_rejected"
    if metrics.stage == "pipeline_not_run":
        return "pipeline_not_run"
    return None
