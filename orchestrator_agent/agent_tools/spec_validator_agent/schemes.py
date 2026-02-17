"""Schemas for the spec validator agent."""

from typing import Annotated, List, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class DomainComplianceInfo(BaseModel):
    """Domain-specific compliance analysis."""

    matched_domain: Annotated[
        Optional[str],
        Field(default=None, description="Primary domain matched (e.g., review, ingestion)"),
    ]
    bound_requirement_count: Annotated[
        int, Field(default=0, description="Number of requirements bound to this domain")
    ]
    satisfied_count: Annotated[
        int, Field(default=0, description="Number of bound requirements satisfied by AC")
    ]
    critical_gaps: Annotated[
        List[str],
        Field(
            default_factory=list,
            description="Missing artifacts/invariants that MUST be added",
        ),
    ]
    out_of_scope_invariants: Annotated[
        List[str],
        Field(
            default_factory=list,
            description="Invariant IDs explicitly skipped because they are out of feature scope",
        ),
    ]


class SpecValidationResult(BaseModel):
    """Structured specification compliance output with domain-aware validation."""

    is_compliant: Annotated[
        bool,
        Field(
            description="True if story complies with ALL spec requirements including domain invariants"
        ),
    ]
    issues: Annotated[
        List[str],
        Field(
            default_factory=list,
            description="Specific spec violations found. Empty if compliant.",
        ),
    ]
    suggestions: Annotated[
        List[str],
        Field(
            default_factory=list,
            description="Actionable edits to fix spec violations. Empty if compliant.",
        ),
    ]
    domain_compliance: Annotated[
        Optional[DomainComplianceInfo],
        Field(default=None, description="Domain-specific compliance analysis (null if no spec)"),
    ]
    verdict: Annotated[str, Field(description="Brief summary of spec compliance check")]

    @field_validator("issues", "suggestions", mode="after")
    @classmethod
    def validate_compliant_has_no_issues(
        cls, v: List[str], info: ValidationInfo
    ) -> List[str]:
        """If is_compliant=True, issues and suggestions must be empty."""
        if info.data.get("is_compliant") is True and len(v) > 0:
            field_name = info.field_name
            raise ValueError(
                f"Logical inconsistency: is_compliant=True but {field_name} is not empty. "
                f"When a story is compliant, there should be no {field_name}. "
                f"Either set is_compliant=False or clear the {field_name} list."
            )
        return v

    @field_validator("issues", mode="after")
    @classmethod
    def validate_non_compliant_has_issues(
        cls, v: List[str], info: ValidationInfo
    ) -> List[str]:
        """If is_compliant=False, issues must not be empty."""
        if info.data.get("is_compliant") is False and len(v) == 0:
            raise ValueError(
                "Logical inconsistency: is_compliant=False but issues list is empty. "
                "If a story is non-compliant, you must specify at least one issue."
            )
        return v

    @model_validator(mode="after")
    def validate_domain_compliance_consistency(self) -> "SpecValidationResult":
        """If critical_gaps exist, is_compliant must be False."""
        if self.domain_compliance and self.domain_compliance.critical_gaps and self.is_compliant:
            raise ValueError(
                "Logical inconsistency: is_compliant=True but "
                f"domain_compliance.critical_gaps is not empty: {self.domain_compliance.critical_gaps}. "
                "Critical gaps are blocking issues that MUST be resolved. Set is_compliant=False."
            )
        return self
