"""Define all shared Pydantic schemas used across multiple agents."""

from typing import Annotated

from pydantic import BaseModel, Field


# --- Define Schemas ---
class InputSchema(BaseModel):
    """Schema for the input unstructured requirements text."""

    unstructured_requirements: Annotated[
        str,
        Field(
            description=(
                "Raw, unstructured text containing product requirements and " "ideas."
            ),
        ),
    ]


class OutputSchema(BaseModel):
    """
    Schema for the output, which can be a final vision or a
    draft with questions.
    """

    product_vision_statement: Annotated[
        str,
        Field(
            description=(
                "The product vision statement. This will be a final, "
                "complete statement OR a draft with placeholders "
                "(e.g., '[Missing Target User]') if info is missing."
            ),
        ),
    ]

    is_complete: Annotated[
        bool,
        Field(
            description=(
                "True if the vision statement is final and complete. "
                "False if it is a draft and requires more information."
            ),
        ),
    ]

    clarifying_questions: Annotated[
        list[str],
        Field(
            default_factory=list,
            description=(
                "A list of specific questions for the user to answer "
                "to fill in the missing parts of the vision. "
                "This list will be empty if 'is_complete' is True."
            ),
        ),
    ]
