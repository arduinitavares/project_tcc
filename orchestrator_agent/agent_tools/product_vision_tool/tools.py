# product_vision_tool/tools.py

"""
product_tools.py

Defines custom tools for agents to interact with the
shared session state (ToolContext).
"""

from datetime import datetime
from typing import Annotated, Any, Dict

from google.adk.tools.tool_context import ToolContext
from pydantic import BaseModel, Field

# --- Tool for SAVING the vision ---


class SaveVisionInput(BaseModel):
    """Schema for the 'save_vision' tool."""

    product_vision_statement: Annotated[
        str,
        Field(description="The final, approved product vision statement."),
    ]


def save_vision_tool(vision_input: SaveVisionInput, tool_context: ToolContext) -> str:
    """
    Saves the final product vision statement to the
    shared session state.
    """
    try:
        tool_context.state["vision_statement"] = vision_input.product_vision_statement
        print(
            f"[Tool Log]: Saved to state: {vision_input.product_vision_statement[:20]}..."
        )
        return "Product vision saved successfully to session state."
    except (KeyError, TypeError) as e:
        return f"Error saving vision to state: {e}"


# --- Tool for READING the vision ---


def read_vision_tool(tool_context: ToolContext) -> str:
    """
    Reads the product vision statement from the shared
    session state.
    """
    vision_statement = tool_context.state.get("vision_statement")
    if vision_statement:
        print(f"[Tool Log]: Read from state: {vision_statement[:20]}...")
        return vision_statement

    return "Error: No product vision statement found in session state."


# --- Output Schema ---


class CurrentTimeOutput(BaseModel):
    """
    Schema for the 'get_current_time' tool's dictionary output.
    """

    status: Annotated[
        str,
        Field(description="The outcome of the operation, e.g., 'success' or 'error'."),
    ]

    current_time: Annotated[
        str | None,  # Use | None (or Optional[str])
        Field(
            default=None,
            description="The current time, or None if an error occurred.",
        ),
    ]

    error_message: Annotated[
        str | None,  # Use | None (or Optional[str])
        Field(default=None, description="Details of the error, or None on success."),
    ]


# --- Tool Function ---
def get_current_time_tool(
    tool_context: ToolContext,
) -> Dict[str, Any]:  # <-- 2. Return type is a dict
    """
    Returns the current time in a descriptive dictionary.
    """
    try:
        time_str: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 3. Return a dict that matches CurrentTimeOutput
        return {"status": "success", "current_time": time_str}

    except ValueError as e:
        # 4. Also return a dict on error
        return {"status": "error", "error_message": str(e)}
