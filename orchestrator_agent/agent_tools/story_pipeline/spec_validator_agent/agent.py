"""
SpecValidatorAgent - Validates a user story against technical specifications.

This agent receives a story draft and the product's technical specification.
It determines if the story complies with explicit constraints (must/shall/required).

ENHANCED: Now includes deterministic requirement binding that:
1. Extracts HARD requirements (MUST/SHALL/REQUIRED) from spec
2. Binds requirements to stories based on domain/theme keywords
3. Validates acceptance criteria contain required artifacts
4. Forces refinement when domain-specific invariants are missing

The agent uses Pydantic V2 field validators to enforce logical consistency.
When validation fails, Pydantic raises descriptive errors that the calling
pipeline can use to trigger retries or provide feedback to upstream agents.
"""

import os
from pathlib import Path
from typing import Annotated, Optional, List

import dotenv
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from utils.helper import load_instruction
from utils.model_config import get_model_id

# --- Load Environment ---
dotenv.load_dotenv()


class BoundRequirementInfo(BaseModel):
    """Information about a requirement bound to this story's domain."""
    requirement_id: Annotated[str, Field(description="Unique ID like REQ-001")]
    requirement_text: Annotated[str, Field(description="Original requirement text from spec")]
    is_satisfied: Annotated[bool, Field(description="True if AC addresses this requirement")]
    missing_artifacts: Annotated[
        List[str], 
        Field(default_factory=list, description="Required artifacts not found in AC")
    ]


class DomainComplianceInfo(BaseModel):
    """Domain-specific compliance analysis."""
    matched_domain: Annotated[
        Optional[str], 
        Field(default=None, description="Primary domain matched (e.g., 'review', 'ingestion')")
    ]
    bound_requirement_count: Annotated[
        int, 
        Field(default=0, description="Number of requirements bound to this domain")
    ]
    satisfied_count: Annotated[
        int, 
        Field(default=0, description="Number of bound requirements satisfied by AC")
    ]
    critical_gaps: Annotated[
        List[str], 
        Field(default_factory=list, description="Missing artifacts/invariants that MUST be added")
    ]


class SpecValidationResult(BaseModel):
    """
    Structured specification compliance output with domain-aware validation.
    
    Enforces logical consistency via Pydantic validators:
    - Compliant stories cannot have issues or suggestions
    - Non-compliant stories must have at least one issue
    - Domain compliance gaps are blocking (force refinement)
    
    Validation failures trigger LLM retries automatically.
    """
    is_compliant: Annotated[
        bool, 
        Field(description="True if story complies with ALL spec requirements including domain invariants")
    ]
    issues: Annotated[
        List[str], 
        Field(default_factory=list, description="Specific spec violations found. Empty if compliant.")
    ]
    suggestions: Annotated[
        List[str], 
        Field(default_factory=list, description="Actionable edits to fix spec violations. Empty if compliant.")
    ]
    domain_compliance: Annotated[
        Optional[DomainComplianceInfo],
        Field(default=None, description="Domain-specific compliance analysis (null if no spec)")
    ]
    verdict: Annotated[
        str, 
        Field(description="Brief summary of spec compliance check")
    ]
    
    @field_validator('issues', 'suggestions', mode='after')
    @classmethod
    def validate_compliant_has_no_issues(cls, v: List[str], info: ValidationInfo) -> List[str]:
        """
        Enforce: If is_compliant is True, issues and suggestions MUST be empty.
        
        This validator runs after field assignment to check logical consistency.
        Triggers LLM retry if violated.
        """
        # Access the is_compliant field from the context
        if info.data.get('is_compliant') is True and len(v) > 0:
            field_name = info.field_name
            raise ValueError(
                f"Logical inconsistency: is_compliant=True but {field_name} is not empty. "
                f"When a story is compliant, there should be no {field_name}. "
                f"Either set is_compliant=False or clear the {field_name} list."
            )
        return v
    
    @field_validator('issues', mode='after')
    @classmethod
    def validate_non_compliant_has_issues(cls, v: List[str], info: ValidationInfo) -> List[str]:
        """
        Enforce: If is_compliant is False, issues MUST NOT be empty.
        
        Triggers LLM retry if violated.
        """
        if info.data.get('is_compliant') is False and len(v) == 0:
            raise ValueError(
                "Logical inconsistency: is_compliant=False but issues list is empty. "
                "If a story is non-compliant, you must specify at least one issue."
            )
        return v
    
    @model_validator(mode='after')
    def validate_domain_compliance_consistency(self) -> 'SpecValidationResult':
        """
        Enforce: If domain_compliance has critical_gaps, is_compliant MUST be False.
        
        This ensures domain-specific invariants force refinement.
        """
        if self.domain_compliance and self.domain_compliance.critical_gaps:
            if self.is_compliant:
                raise ValueError(
                    f"Logical inconsistency: is_compliant=True but domain_compliance.critical_gaps "
                    f"is not empty: {self.domain_compliance.critical_gaps}. "
                    f"Critical gaps are blocking issues that MUST be resolved. Set is_compliant=False."
                )
        return self

# --- Model ---
model = LiteLlm(
    model=get_model_id("spec_validator"),
    api_key=os.getenv("OPEN_ROUTER_API_KEY"),
    drop_params=True,
)

# --- Agent Definition ---
spec_validator_agent = LlmAgent(
    name="SpecValidatorAgent",
    model=model,
    instruction=load_instruction(Path(__file__).parent / "instructions.txt"),
    description="Validates story compliance with technical specifications using Pydantic-enforced logic checks.",
    output_key="spec_validation_result",
    output_schema=SpecValidationResult,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
