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
