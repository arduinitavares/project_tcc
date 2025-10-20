"""Email Generation Agent"""

from typing import Annotated, List

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field


# --- Define the input scheme ---
class EmailRequest(BaseModel):
    """Schema for the user's request to generate an email."""

    to_recipient: Annotated[
        str, Field(description="The primary recipient's email address")
    ]
    from_sender: Annotated[str, Field(description="The sender's email address")]
    purpose: Annotated[str, Field(description="The main purpose or topic of the email")]
    key_points: Annotated[
        List[str],
        Field(
            description="A list of key points or details to include in the email body"
        ),
    ]
    tone: Annotated[
        str,
        Field(
            description="The desired tone of the email (e.g., formal, casual, urgent)",
            default="formal",
        ),
    ]


# --- Define the output scheme (already present) ---
class EmailContent(BaseModel):
    """Schema for generated email content."""

    subject: Annotated[str, Field(description="The subject of the email")]
    body: Annotated[str, Field(description="The body of the email")]
    to: Annotated[str, Field(description="The recipient of the email")]
    from_: Annotated[str, Field(description="The sender of the email", alias="from")]
    attachments: Annotated[
        List[str],
        Field(description="List of suggested attachments (empty list if none needed)"),
    ]
    attachments: Annotated[
        List[str],
        Field(description="List of suggested attachments (empty list if none needed)"),
    ]


# --- Create Email Generator Agent with updated instruction ---
root_agent: LlmAgent = LlmAgent(
    name="email_agent",
    description="An agent that generates email content based on user input.",
    model="gemini-2.0-flash",
    instruction="""
    You are an email generation assistant.
    Your task is to generate a professional email based on the user's input.

    **USER INPUT GUIDELINES:**
    The user will provide information structured around the following concepts:
    - **Recipient (to_recipient):** The email address of the person receiving the email.
    - **Sender (from_sender):** The email address of the person sending the email.
    - **Purpose (purpose):** The main reason or topic for the email.
    - **Key Points (key_points):** A list of specific details or messages to include in the email body.
    - **Tone (tone):** The desired style of the email (e.g., formal, casual, urgent). Defaults to formal.

    **EMAIL GENERATION GUIDELINES:**
    - Using the information extracted from the user's input, construct a professional email.
    - Formulate a clear and concise subject line based on the 'purpose' and 'key_points'.
    - Draft the email body, incorporating all 'key_points' naturally and adhering to the specified 'tone'.
    - Ensure the email is clear, concise, and professional.
    - Format the email appropriately with greetings and sign-offs.
    - Suggest relevant attachments if applicable. (empty list if none needed)
    - Keep emails concise but complete.

    IMPORTANT: Your response MUST be valid JSON matching this structure:
    {
        "email": {
            "subject": str,
            "body": str,
            "to": str,
            "from": str,
            "attachments": List[str]
        }
    }

    DO NOT include any explanations or additional text outside the JSON structure.
    """,
    output_schema=EmailContent,
    output_key="email",
)
