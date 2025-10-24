"""This is the orchestrator main script."""

import asyncio
import json
from typing import Annotated

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService

# Note: You are importing product_roadmap_agent but not using it.
# This is fine, but it's why you see the "Invalid config" warning.
from product_roadmap_agent.agent import product_roadmap_agent
from product_vision_agent.agent import product_vision_agent
from pydantic import BaseModel, Field, ValidationError
from utils.utils import call_agent_async

load_dotenv()

# ===== PART 1: Initialize Persistent Session Service =====
DB_URL = "sqlite:///./my_agent_data.db"
session_service = DatabaseSessionService(db_url=DB_URL)


# ===== PART 2: Define Initial State =====
initial_state = {
    "product_vision_statement": "To be defined.",
    "Product_roadmap": "To be defined.",
    "unstructured_requirements": "To be defined.",
}


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


async def main_async():
    """Main async function to run the memory agent with session management."""

    # Setup constants
    APP_NAME = "ProductManager"  # pylint: disable=invalid-name
    USER_ID = "user_123".strip()  # pylint: disable=invalid-name

    # ===== PART 3: Session Management - Find or Create =====
    # Check for existing sessions for this user
    #
    # FIX 1: Added 'await'
    existing_sessions = await session_service.list_sessions(
        app_name=APP_NAME,
        user_id=USER_ID,
    )

    # If there's an existing session, use it, otherwise create a new one
    if existing_sessions and len(existing_sessions.sessions) > 0:
        # Use the most recent session
        session_id = existing_sessions.sessions[0].id
        print(f"Continuing existing session: {session_id}")
    else:
        # Create a new session with initial state
        #
        # FIX 2: Added 'await'
        new_session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            state=initial_state,
        )
        session_id = new_session.id
        print(f"Created new session: {session_id}")

    # ===== PART 4: Agent Runner Setup =====
    # Create a runner with the memory agent
    runner = Runner(
        agent=product_vision_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    # ===== PART 5: Interactive Conversation Loop =====
    print("\nWelcome to Memory Agent Chat!")
    print("Your reminders will be remembered across conversations.")
    print("Type 'exit' or 'quit' to end the conversation.\n")

    while True:
        user_input_str: str = input("You: ")

        # exit check first
        if user_input_str.lower() in ["exit", "quit"]:
            print("Ending conversation. Your data has been saved to the database.")
            break

        # Call the agent with the raw string (not the Pydantic InputSchema instance)
        final_response_text = await call_agent_async(
            runner,
            USER_ID,
            session_id,
            user_input_str,
        )

        # Safety: agent might not return anything
        if not final_response_text:
            print("⚠ No final structured response from agent.")
            continue

        # Try to parse agent's output as JSON
        try:
            response_obj = json.loads(final_response_text)
        except json.JSONDecodeError:
            print("⚠ Agent final response was not valid JSON:")
            print(str(final_response_text))
            continue

        # Validate with OutputSchema so we get nice attributes
        try:
            structured = OutputSchema(**response_obj)
        except ValidationError as e:
            print("⚠ Agent JSON didn't match OutputSchema:")
            print(e)
            print("Raw response was:", response_obj)
            continue

        # Now you can interact with fields directly:
        print("\nParsed agent output:")
        print("Vision:", structured.product_vision_statement)
        print("Complete?:", structured.is_complete)

        if structured.is_complete:
            print("✅ Vision is complete. We can move to roadmap next.")
            # <- This is where you'd switch runner to product_roadmap_agent.
        else:
            print("❗ Vision is NOT complete. We still need answers to:")
            for i, q in enumerate(structured.clarifying_questions, start=1):
                print(f"  {i}. {q}")


if __name__ == "__main__":
    # FIX 3: Removed the duplicate call to asyncio.run()
    asyncio.run(main_async())
