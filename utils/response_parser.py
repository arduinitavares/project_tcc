# utils/response_parser.py

"""This module contains utility functions for parsing agent responses."""

import json
from typing import Annotated

from pydantic import BaseModel, Field, ValidationError


class OutputSchema(BaseModel):
    """Schema for the output of the product vision agent."""

    product_vision_statement: Annotated[str, Field(...)]
    is_complete: Annotated[bool, Field(...)]
    clarifying_questions: Annotated[list[str], Field(default_factory=list)]


def parse_agent_output(
    final_response_text: str | None,
) -> tuple[object | None, str | None]:
    """
    Attempt to parse the agent's final JSON response into a Pydantic model.

    Returns:
    - (structured_instance, None) if OK
    - (None, error_message) if not OK
    """
    output_schema = OutputSchema

    # First: is there any text?
    if not final_response_text:
        return None, "No final structured response from agent."

    # Second: parse and validate with Pydantic
    try:
        structured = output_schema.model_validate_json(final_response_text)
    except ValidationError as e:
        return None, (
            "Agent response didn't match OutputSchema:\n"
            f"{e!s}\n"
            f"Raw response was: {final_response_text}"
        )
    except json.JSONDecodeError:
        return None, (
            f"Agent final response was not valid JSON:\n{final_response_text}"
        )

    return structured, None
