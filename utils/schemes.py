# utils/schemes.py
"""
Define all shared Pydantic schemas used across multiple agents.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, List, Optional, Literal, Union, Dict, Any

from pydantic import BaseModel, Field, ConfigDict, RootModel, model_validator









# --- Validation Evidence Schema (Story Validation Pinning v2) ---


class ValidationFailure(BaseModel):
    """A single validation failure record."""

    rule: Annotated[str, Field(description="Rule ID or name that failed")]
    expected: Annotated[
        Optional[str],
        Field(default=None, description="Expected value/condition")
    ]
    actual: Annotated[
        Optional[str],
        Field(default=None, description="Actual value found")
    ]
    message: Annotated[str, Field(description="Human-readable failure message")]


class AlignmentFinding(BaseModel):
    """Structured alignment finding for audit evidence."""

    code: Annotated[str, Field(description="Stable identifier for the finding")]
    invariant: Annotated[
        Optional[str],
        Field(default=None, description="Invariant text or ID used")
    ]
    source_requirement: Optional[str] = Field(
        default=None, description="Source requirement ID from backlog."
    )
    capability: Annotated[
        Optional[str],
        Field(default=None, description="Capability token (if applicable)")
    ]
    message: Annotated[str, Field(description="Human-readable message")]
    severity: Annotated[
        Literal["warning", "failure"],
        Field(description="Severity level")
    ]
    created_at: Annotated[
        datetime,
        Field(description="UTC timestamp for the finding")
    ]


class ValidationEvidence(BaseModel):
    """
    Complete validation evidence for a story validation run.

    Persisted to UserStory.validation_evidence as JSON.
    Every validation (pass or fail) produces this evidence.
    """

    spec_version_id: Annotated[
        int,
        Field(description="Spec version used for validation")
    ]
    validated_at: Annotated[
        datetime,
        Field(description="UTC timestamp of validation")
    ]
    passed: Annotated[bool, Field(description="Overall validation result")]
    rules_checked: Annotated[
        List[str],
        Field(description="List of rule IDs/names checked")
    ]
    invariants_checked: Annotated[
        List[str],
        Field(description="List of invariant IDs/strings checked")
    ]
    evaluated_invariant_ids: Annotated[
        List[str],
        Field(default_factory=list, description="IDs of invariants whose validation logic actually ran")
    ]
    finding_invariant_ids: Annotated[
        List[str],
        Field(default_factory=list, description="IDs of invariants referenced in alignment warnings or failures")
    ]
    failures: Annotated[
        List[ValidationFailure],
        Field(default_factory=list, description="List of failures")
    ]
    warnings: Annotated[
        List[str],
        Field(default_factory=list, description="Non-blocking warnings")
    ]
    alignment_warnings: Annotated[
        List[AlignmentFinding],
        Field(default_factory=list, description="Alignment warnings")
    ]
    alignment_failures: Annotated[
        List[AlignmentFinding],
        Field(default_factory=list, description="Alignment failures")
    ]
    validator_version: Annotated[
        str,
        Field(description="Version of validator logic used")
    ]
    input_hash: Annotated[
        str,
        Field(description="SHA-256 hash of story content at validation time")
    ]


# --- 3. The Agent Output (The "Response") ---




# --- 4. Spec Authority Compiler Schemas ---


class SpecAuthorityCompilerInput(BaseModel):
    """Input schema for spec_authority_compiler_agent."""

    spec_source: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Raw specification text. Provide exactly one of spec_source or spec_content_ref.",
        ),
    ]
    spec_content_ref: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Path or identifier for spec content. Provide exactly one of spec_source or spec_content_ref.",
        ),
    ]
    domain_hint: Annotated[
        Optional[str],
        Field(default=None, description="Optional domain hint for extraction."),
    ]
    product_id: Annotated[
        Optional[int],
        Field(default=None, description="Optional product identifier."),
    ]
    spec_version_id: Annotated[
        Optional[int],
        Field(default=None, description="Optional spec version identifier."),
    ]

    @model_validator(mode="after")
    def validate_exactly_one_source(self) -> "SpecAuthorityCompilerInput":
        has_source = bool(self.spec_source and self.spec_source.strip())
        has_ref = bool(self.spec_content_ref and self.spec_content_ref.strip())
        if has_source == has_ref:
            raise ValueError(
                "Provide exactly one of spec_source or spec_content_ref."
            )
        return self


class InvariantType(str, Enum):
    """Allowed invariant types for compiled spec authority."""

    FORBIDDEN_CAPABILITY = "FORBIDDEN_CAPABILITY"
    REQUIRED_FIELD = "REQUIRED_FIELD"
    MAX_VALUE = "MAX_VALUE"


class ForbiddenCapabilityParams(BaseModel):
    """Parameters for FORBIDDEN_CAPABILITY invariants."""

    model_config = ConfigDict(extra="forbid")

    capability: Annotated[
        str,
        Field(min_length=1, description="Capability or technology that is forbidden."),
    ]


class RequiredFieldParams(BaseModel):
    """Parameters for REQUIRED_FIELD invariants."""

    model_config = ConfigDict(extra="forbid")

    field_name: Annotated[
        str,
        Field(min_length=1, description="Required field or artifact name."),
    ]


class MaxValueParams(BaseModel):
    """Parameters for MAX_VALUE invariants."""

    model_config = ConfigDict(extra="forbid")

    field_name: Annotated[
        str,
        Field(min_length=1, description="Field constrained by a maximum value."),
    ]
    max_value: Annotated[
        Union[int, float],
        Field(description="Maximum allowed numeric value."),
    ]


InvariantParameters = Union[
    ForbiddenCapabilityParams,
    RequiredFieldParams,
    MaxValueParams,
]


class Invariant(BaseModel):
    """Typed invariant with deterministic ID and structured parameters."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[
        str,
        Field(
            pattern=r"^INV-[0-9a-f]{16}$",
            description="Deterministic invariant identifier (INV- + 16 hex chars).",
        ),
    ]
    type: Annotated[
        InvariantType,
        Field(description="Invariant type enum."),
    ]
    parameters: Annotated[
        InvariantParameters,
        Field(description="Typed parameters for the invariant."),
    ]

    @model_validator(mode="after")
    def validate_parameters_match_type(self) -> "Invariant":
        type_map = {
            InvariantType.FORBIDDEN_CAPABILITY: ForbiddenCapabilityParams,
            InvariantType.REQUIRED_FIELD: RequiredFieldParams,
            InvariantType.MAX_VALUE: MaxValueParams,
        }
        expected_type = type_map.get(self.type)
        if expected_type and not isinstance(self.parameters, expected_type):
            raise ValueError(
                f"Invariant parameters do not match type {self.type}."
            )
        return self


class SourceMapEntry(BaseModel):
    """Mapping of invariants to source excerpts."""

    model_config = ConfigDict(extra="forbid")

    invariant_id: Annotated[
        str,
        Field(description="Invariant ID referenced in this mapping."),
    ]
    excerpt: Annotated[
        str,
        Field(description="Exact excerpt from spec supporting the invariant."),
    ]
    location: Annotated[
        Optional[str],
        Field(default=None, description="Optional location reference (e.g., line or section)."),
    ]


class EligibleFeatureRule(BaseModel):
    """Closed schema for optional feature eligibility notes."""

    model_config = ConfigDict(extra="forbid")

    rule: Annotated[
        str,
        Field(description="Short eligibility rule or note tied to a candidate feature."),
    ]


class SpecAuthorityCompilationSuccess(BaseModel):
    """Successful spec authority compilation output."""

    model_config = ConfigDict(extra="forbid")

    scope_themes: Annotated[
        List[str],
        Field(description="Top-level scope themes extracted from the spec."),
    ]
    domain: Annotated[
        Optional[str],
        Field(default=None, description="Optional primary domain for spec (e.g., training, review)."),
    ]
    invariants: Annotated[
        List[Invariant],
        Field(description="Structured invariants extracted from the spec."),
    ]
    eligible_feature_rules: Annotated[
        List[EligibleFeatureRule],
        Field(description="Optional feature eligibility rules (may be empty)."),
    ]
    gaps: Annotated[
        List[str],
        Field(description="Missing or ambiguous spec items."),
    ]
    assumptions: Annotated[
        List[str],
        Field(description="Explicit assumptions made during compilation."),
    ]
    source_map: Annotated[
        List[SourceMapEntry],
        Field(description="Mapping of invariants to source excerpts."),
    ]
    compiler_version: Annotated[
        str,
        Field(description="Compiler version identifier."),
    ]
    prompt_hash: Annotated[
        str,
        Field(
            pattern=r"^[0-9a-f]{64}$",
            description="SHA-256 hash of the compiler prompt/instructions.",
        ),
    ]


class SpecAuthorityCompilationFailure(BaseModel):
    """Structured failure response from compiler agent."""

    model_config = ConfigDict(extra="forbid")

    error: Annotated[
        str,
        Field(description="Error code for compilation failure."),
    ]
    reason: Annotated[
        str,
        Field(description="Short reason for failure."),
    ]
    blocking_gaps: Annotated[
        List[str],
        Field(description="Blocking gaps that prevented compilation."),
    ]


class SpecAuthorityCompilerOutput(RootModel[Union[
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilationFailure,
]]):
    """Root output schema for spec authority compilation."""


class SpecAuthorityCompilerEnvelope(BaseModel):
    """Envelope schema for spec authority compilation output."""

    model_config = ConfigDict(extra="forbid")

    result: Annotated[
        Union[SpecAuthorityCompilationSuccess, SpecAuthorityCompilationFailure],
        Field(description="Compiler output payload."),
    ]


# --- Story Draft Schemas ---


class StoryDraftMetadata(BaseModel):
    """Traceability metadata for drafted stories."""

    model_config = ConfigDict(extra="forbid")

    spec_version_id: Annotated[
        int,
        Field(description="Pinned compiled spec version ID used for this story."),
    ]


class StoryDraft(BaseModel):
    """
    Schema for a User Story draft.
    NOTE: feature_id and feature_title are NOT part of this schema.
    They are preserved from input state to prevent LLM override causing data corruption.
    """

    model_config = ConfigDict(extra="forbid")

    title: Annotated[
        str,
        Field(description="Short, action-oriented title for the story."),
    ]
    description: Annotated[
        str,
        Field(
            description=(
                "The story narrative in the format: 'As a <persona>, I want <action> so that <benefit>.'"
            )
        ),
    ]
    acceptance_criteria: Annotated[
        str,
        Field(
            description="A list of 3-5 specific, testable criteria, each starting with '- '."
        ),
    ]
    story_points: Annotated[
        Optional[int],
        Field(
            description=(
                "Estimated effort (1-8 points). Null if not estimable or if story points are disabled."
            )
        ),
    ]
    metadata: Annotated[
        StoryDraftMetadata,
        Field(description="Traceability metadata (must include spec_version_id)."),
    ]

    @model_validator(mode="after")
    def _validate_story_points(self):
        if self.story_points is not None and (self.story_points < 1 or self.story_points > 8):
            raise ValueError("Story points must be between 1 and 8 (INVEST principle: Small).")
        return self

    @model_validator(mode="after")
    def _validate_description_format(self):
        desc = self.description or ""
        desc_lower = desc.lower()
        if not desc_lower.startswith("as a"):
            raise ValueError("Story description must start with 'As a ...'")
        if " i want " not in desc_lower:
            raise ValueError("Story description must contain '... I want ...'")
        if " so that " not in desc_lower:
            raise ValueError("Story description must contain '... so that ...'")
        return self


class StoryDraftInput(BaseModel):
    """Structured input payload for StoryDraftAgent."""

    model_config = ConfigDict(extra="forbid")

    current_feature: Annotated[
        Dict[str, Any],
        Field(
            description=(
                "Feature context (id, title, theme, epic, time_frame, justification, siblings)."
            )
        ),
    ]
    product_context: Annotated[
        Dict[str, Any],
        Field(description="Product context (id, name, vision, time_frame)."),
    ]
    spec_version_id: Annotated[
        int,
        Field(description="Pinned compiled spec version ID."),
    ]
    authority_context: Annotated[
        Dict[str, Any],
        Field(
            description=(
                "Compiled authority context (scope themes, invariants, gaps, assumptions, hashes)."
            )
        ),
    ]
    user_persona: Annotated[
        Optional[str],
        Field(description="Optional persona hint. Use if provided; otherwise infer."),
    ] = None
    story_preferences: Annotated[
        Dict[str, Any],
        Field(description="Story preferences (e.g., include_story_points)."),
    ]
    refinement_feedback: Annotated[
        str,
        Field(description="Validator feedback from previous attempt, or empty string."),
    ]
    raw_spec_text: Annotated[
        Optional[str],
        Field(description="Optional raw spec text for phrasing only."),
    ] = None


class NegationCheckInput(BaseModel):
    """Structured input payload for NegationCheckerAgent."""

    model_config = ConfigDict(extra="forbid")

    text: Annotated[
        str,
        Field(min_length=1, description="Full text where the forbidden term appears."),
    ]
    forbidden_term: Annotated[
        str,
        Field(min_length=1, description="Forbidden capability term detected in text."),
    ]
    context_label: Annotated[
        str,
        Field(min_length=1, description="Context label (e.g., story, feature)."),
    ]


class NegationCheckOutput(BaseModel):
    """Structured output payload for NegationCheckerAgent."""

    model_config = ConfigDict(extra="forbid")

    is_negated: Annotated[
        bool,
        Field(
            description=(
                "True if the forbidden term is only mentioned as a prohibition or negation."
            ),
        ),
    ]
    confidence: Annotated[
        int,
        Field(ge=0, le=100, description="Confidence score from 0 to 100."),
    ]
    rationale: Annotated[
        str,
        Field(min_length=1, description="Short rationale for the decision."),
    ]


class StoryRefinerInput(BaseModel):
    """Structured input payload for StoryRefinerAgent."""

    model_config = ConfigDict(extra="allow")

    story_draft: Annotated[
        Optional[Any],
        Field(description="Original story draft payload from state."),
    ]
    spec_validation_result: Annotated[
        Optional[Any],
        Field(description="Spec validation feedback from state."),
    ]
    authority_context: Annotated[
        Dict[str, Any],
        Field(description="Compiled authority context (scope themes, invariants, gaps, assumptions)."),
    ]
    spec_version_id: Annotated[
        int,
        Field(description="Pinned compiled spec version ID."),
    ]
    current_feature: Annotated[
        Dict[str, Any],
        Field(description="Feature context (id, title, theme, epic, time_frame, justification, siblings)."),
    ]
    story_preferences: Annotated[
        Dict[str, Any],
        Field(description="Story preferences (e.g., include_story_points)."),
    ]
    raw_spec_text: Annotated[
        Optional[str],
        Field(description="Optional raw spec text for phrasing only."),
    ] = None


# --- 10. Task Execution Write-Back Tracking ---

from agile_sqlmodel import TaskStatus, TaskAcceptanceResult
from datetime import datetime

class TaskExecutionWriteRequest(BaseModel):
    """Payload for updating a task's status and logging its outcome."""

    new_status: TaskStatus
    outcome_summary: Optional[str] = None
    artifact_refs: Optional[List[str]] = None
    acceptance_result: Optional[TaskAcceptanceResult] = None
    notes: Optional[str] = None
    changed_by: Optional[str] = None

    @model_validator(mode="after")
    def validate_execution_rules(self) -> "TaskExecutionWriteRequest":
        if self.artifact_refs is not None:
            self.artifact_refs = [
                ref.strip() for ref in self.artifact_refs if ref and ref.strip()
            ]

        has_outcome = bool(self.outcome_summary and self.outcome_summary.strip())
        has_artifacts = bool(self.artifact_refs)
        has_notes = bool(self.notes and self.notes.strip())

        if not (has_outcome or has_artifacts or has_notes):
            if self.new_status != TaskStatus.TO_DO:
                raise ValueError("Must provide outcome_summary, artifact_refs, or notes.")

        if self.new_status == TaskStatus.DONE:
            if not has_outcome:
                raise ValueError("An outcome_summary is required when marking a task Done.")
            if self.acceptance_result == TaskAcceptanceResult.NOT_CHECKED:
                raise ValueError("An acceptance_result must be recorded when mapping a task Done.")
            if not self.acceptance_result:
                self.acceptance_result = TaskAcceptanceResult.NOT_CHECKED
                raise ValueError("An explicit acceptance_result is required when marking a task Done.")

        return self


class TaskExecutionLogEntry(BaseModel):
    log_id: int
    task_id: int
    sprint_id: int
    old_status: Optional[TaskStatus]
    new_status: TaskStatus
    outcome_summary: Optional[str]
    artifact_refs: List[str]
    acceptance_result: TaskAcceptanceResult
    notes: Optional[str]
    changed_by: str
    changed_at: datetime


class TaskExecutionReadResponse(BaseModel):
    success: bool
    task_id: int
    sprint_id: int
    current_status: TaskStatus
    latest_entry: Optional[TaskExecutionLogEntry] = None
    history: List[TaskExecutionLogEntry] = Field(default_factory=list)


# --- 11. Story Manual Close Tracking ---

from agile_sqlmodel import StoryResolution

class StoryTaskProgressSummary(BaseModel):
    total_tasks: int
    done_tasks: int
    cancelled_tasks: int
    all_actionable_tasks_done: bool


class StoryCloseReadResponse(BaseModel):
    success: bool
    story_id: int
    sprint_id: int
    current_status: str
    resolution: Optional[StoryResolution] = None
    completion_notes: Optional[str] = None
    evidence_links: Optional[str] = None
    completed_at: Optional[datetime] = None
    readiness: StoryTaskProgressSummary
    close_eligible: bool
    ineligible_reason: Optional[str] = None


class StoryCloseWriteRequest(BaseModel):
    resolution: StoryResolution
    completion_notes: str = Field(min_length=1)
    evidence_links: Optional[List[str]] = None
    known_gaps: Optional[str] = None
    follow_up_notes: Optional[str] = None
    changed_by: Optional[str] = Field(default="manual-ui")

    @model_validator(mode="after")
    def validate_story_close(self) -> "StoryCloseWriteRequest":
        if self.evidence_links is not None:
            self.evidence_links = [
                ref.strip() for ref in self.evidence_links if ref and ref.strip()
            ]
        if not self.completion_notes or not self.completion_notes.strip():
            raise ValueError("completion_notes is required to close a story")
        return self


class SprintCloseStorySummary(BaseModel):
    story_id: int
    story_title: str
    story_status: str
    total_tasks: int
    done_tasks: int
    cancelled_tasks: int
    completion_state: Literal["completed", "unfinished"]


class SprintCloseReadiness(BaseModel):
    completed_story_count: int
    open_story_count: int
    unfinished_story_ids: List[int] = Field(default_factory=list)
    stories: List[SprintCloseStorySummary] = Field(default_factory=list)


class SprintCloseReadResponse(BaseModel):
    success: bool
    sprint_id: int
    current_status: str
    completed_at: Optional[datetime] = None
    readiness: SprintCloseReadiness
    close_eligible: bool
    ineligible_reason: Optional[str] = None
    history_fidelity: Literal["snapshotted", "derived"] = "derived"
    close_snapshot: Optional[Dict[str, Any]] = None


class SprintCloseWriteRequest(BaseModel):
    completion_notes: str = Field(min_length=1)
    follow_up_notes: Optional[str] = None
    changed_by: Optional[str] = Field(default="manual-ui")
