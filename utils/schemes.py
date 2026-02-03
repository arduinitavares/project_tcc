# utils/schemes.py
"""
Define all shared Pydantic schemas used across multiple agents.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, List, Optional, Literal, Union, Dict, Any

from pydantic import BaseModel, Field, ConfigDict, RootModel, model_validator

# --- 1. The Atomic State (The "Letter" inside the envelope) ---


class VisionComponents(BaseModel):
    """
    The granular components of the vision.
    This is the object we serialize/deserialize to DB.
    """

    # NOTE: We use Optional[str] and instruct the LLM to use 'null'
    # so we don't have to parse strings like "UNKNOWN" or "N/A".

    project_name: Annotated[
        Optional[str],
        Field(description="Name of project. Return null if not yet defined."),
    ]
    target_user: Annotated[
        Optional[str],
        Field(
            description="Who is the customer? Return null if ambiguous or unknown."
        ),
    ]
    problem: Annotated[
        Optional[str],
        Field(description="What is the pain point? Return null if unknown."),
    ]
    product_category: Annotated[
        Optional[str],
        Field(
            description="What is it? (App, Service, Device). Return null if unknown."
        ),
    ]
    key_benefit: Annotated[
        Optional[str],
        Field(
            description="Primary value proposition. Return null if unknown."
        ),
    ]
    competitors: Annotated[
        Optional[str],
        Field(description="Existing alternatives. Return null if unknown."),
    ]
    differentiator: Annotated[
        Optional[str],
        Field(description="Why us? (USP). Return null if unknown."),
    ]

    def is_fully_defined(self) -> bool:
        """
        Returns True only if ALL 7 fields are present (not None) and not empty strings.
        """
        # We check strictly for None or empty whitespace
        missing_fields = [
            k
            for k, v in self.model_dump().items()
            if v is None
            or (isinstance(v, str) and not v.strip())
            or v == "/UNKNOWN"
        ]
        return len(missing_fields) == 0


# --- 2. The Agent Input (The "Envelope") ---


class InputSchema(BaseModel):
    """
    Schema for the input arguments the Orchestrator MUST provide to the tool.

    CRITICAL: All fields must be REQUIRED (no defaults) so the Google ADK
    knows to force the Orchestrator to generate/provide them.
    """

    user_raw_text: Annotated[
        str,
        Field(
            description="The latest instruction or feedback text provided by the user."
        ),
    ]
    prior_vision_state: Annotated[
        str,
        Field(
            description=(
                "The raw JSON string representing the previous 'VisionComponents' state. "
                "If this is the first turn, pass the string 'NO_HISTORY'. "
                "Do not attempt to parse or summarize this; pass it exactly as received."
            ),
        ),
    ]


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


class OutputSchema(BaseModel):
    """
    The structured response returned by the Product Vision Agent.
    """

    # A. The State (To be saved to DB)
    updated_components: Annotated[
        VisionComponents,
        Field(
            description="The updated state object containing the 7 vision components."
        ),
    ]

    # B. The Artifact (To be shown to User)
    product_vision_statement: Annotated[
        str,
        Field(
            description=(
                "A natural language vision statement generated from the components. "
                "If components are missing, draft what you have with placeholders."
            )
        ),
    ]

    # C. Metadata (For Orchestrator logic)
    is_complete: Annotated[
        bool,
        Field(
            description="True ONLY if all 7 components are fully defined in updated_components."
        ),
    ]

    clarifying_questions: Annotated[
        List[str],
        Field(
            description="A list of specific questions to ask the user to fill missing components."
        ),
    ]


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
        List[Dict[str, Any]],
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
