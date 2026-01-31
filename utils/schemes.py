# utils/schemes.py
"""
Define all shared Pydantic schemas used across multiple agents.
"""

from typing import Annotated, List, Optional

from pydantic import BaseModel, Field

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
