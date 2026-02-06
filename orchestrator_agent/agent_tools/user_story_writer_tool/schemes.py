"""Input and output schemas for the User Story Writer agent."""

from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserStoryItem(BaseModel):
    """A single user story produced by the User Story Writer (Page 69)."""

    model_config = ConfigDict(extra="forbid")

    story_title: Annotated[
        str,
        Field(
            min_length=3,
            description="Concise functional label for the story.",
        ),
    ]
    statement: Annotated[
        str,
        Field(
            min_length=10,
            description=(
                "The story narrative in strict format: "
                "'As a [role], I want [feature], so that [benefit].' (Page 72)"
            ),
        ),
    ]
    acceptance_criteria: Annotated[
        List[str],
        Field(
            min_length=1,
            description=(
                "Testable Conditions of Satisfaction (Page 77). "
                "Functional: 'Verify that ...', Non-functional: 'Ensure that ...'."
            ),
        ),
    ]
    invest_score: Annotated[
        Literal["High", "Medium", "Low"],
        Field(description="INVEST compliance score for this story (Page 73)."),
    ]
    decomposition_warning: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Reason for low INVEST score. "
                "Include ONLY when invest_score is 'Low'. "
                "Omit (null) for 'High' or 'Medium'."
            ),
        ),
    ]

    @model_validator(mode="after")
    def _validate_statement_format(self):
        """Enforce 'As a ... I want ... so that ...' syntax (Page 72)."""
        stmt = self.statement or ""
        stmt_lower = stmt.lower()
        if not stmt_lower.startswith("as a"):
            raise ValueError("Statement must start with 'As a ...'")
        if " i want " not in stmt_lower:
            raise ValueError("Statement must contain '... I want ...'")
        if " so that " not in stmt_lower:
            raise ValueError("Statement must contain '... so that ...'")
        return self

    @model_validator(mode="after")
    def _validate_warning_consistency(self):
        """decomposition_warning must be present only when invest_score is Low."""
        if self.invest_score in ("High", "Medium") and self.decomposition_warning is not None:
            raise ValueError(
                "decomposition_warning must be omitted (null) when invest_score is "
                "'High' or 'Medium'."
            )
        if self.invest_score == "Low" and not self.decomposition_warning:
            raise ValueError(
                "decomposition_warning is required when invest_score is 'Low'."
            )
        return self


class UserStoryWriterInput(BaseModel):
    """Structured input payload for the User Story Writer agent.

    NOTE: No ``extra="forbid"`` or ``min_length`` constraints here.
    ADK's automatic function-calling parser cannot handle strict Pydantic
    config on input schemas.  Validation constraints belong on the
    *output* schema and internal models only.
    """

    parent_requirement: Annotated[
        str,
        Field(
            description="Roadmap item name (copied verbatim from roadmap).",
        ),
    ]
    requirement_context: Annotated[
        str,
        Field(
            description="Business justification and technical notes for this requirement.",
        ),
    ]
    technical_spec: Annotated[
        str,
        Field(
            description="Relevant technical constraints and system behaviors.",
        ),
    ]
    compiled_authority: Annotated[
        str,
        Field(
            description="Regulatory, architectural, or organizational constraints.",
        ),
    ]


class UserStoryWriterOutput(BaseModel):
    """Structured output payload from the User Story Writer agent."""

    model_config = ConfigDict(extra="forbid")

    parent_requirement: Annotated[
        str,
        Field(description="Copied verbatim from input for traceability."),
    ]
    user_stories: Annotated[
        List[UserStoryItem],
        Field(
            min_length=1,
            description="List of decomposed, INVEST-compliant user stories.",
        ),
    ]
    is_complete: Annotated[
        bool,
        Field(
            description=(
                "True if all stories pass INVEST validation and fully cover "
                "the parent requirement. False if clarification is needed."
            ),
        ),
    ]
    clarifying_questions: Annotated[
        List[str],
        Field(
            default_factory=list,
            description="Questions for the user if is_complete is False.",
        ),
    ]
