"""Interactive orchestrator loop for product vision -> roadmap."""

import asyncio
from typing import Annotated, Any, Dict, Tuple

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from pydantic import BaseModel, Field

from product_roadmap_agent.agent import product_roadmap_agent
from product_vision_agent.agent import product_vision_agent
from utils.agent_io import call_agent_async
from utils.persistence import persist_product_vision_state
from utils.response_parser import parse_agent_output

load_dotenv()


DB_URL = "sqlite:///./my_agent_data.db"
SESSION_SERVICE = DatabaseSessionService(db_url=DB_URL)


class OutputSchema(BaseModel):
    """Structured response from the product_vision_agent."""

    product_vision_statement: Annotated[str, Field(...)]
    is_complete: Annotated[bool, Field(...)]
    clarifying_questions: Annotated[list[str], Field(default_factory=list)]


async def load_or_create_session(
    app_name: str,
    user_id: str,
    initial_state: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    """Get or create a session, and return (session_id, state dict)."""
    sessions_list = await SESSION_SERVICE.list_sessions(
        app_name=app_name,
        user_id=user_id,
    )

    if sessions_list and sessions_list.sessions:
        session_id = sessions_list.sessions[0].id
        print(f"Continuing existing session: {session_id}")

        session_data = await SESSION_SERVICE.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )

        # Make a mutable copy
        state: Dict[str, Any] = dict(session_data.state)

        # Normalize keys / defaults across old runs
        state.setdefault("product_vision_statement", "")
        state.setdefault("product_roadmap", "")
        state.setdefault("unstructured_requirements", "")
        state.setdefault("is_complete", False)
        state.setdefault("clarifying_questions", [])

        # Clean up legacy placeholder values like "To be defined."
        if state["unstructured_requirements"].strip().lower() == "to be defined.":
            state["unstructured_requirements"] = ""
        if state["product_vision_statement"].strip().lower() == "to be defined.":
            state["product_vision_statement"] = ""
        if (
            isinstance(state.get("product_roadmap"), str)
            and state["product_roadmap"].strip().lower() == "to be defined."
        ):
            state["product_roadmap"] = ""

        return session_id, state

    # No session found → create new
    new_session = await SESSION_SERVICE.create_session(
        app_name=app_name,
        user_id=user_id,
        state=initial_state,
    )
    print(f"Created new session: {new_session.id}")
    return new_session.id, dict(initial_state)


def append_user_text_to_requirements(
    state: Dict[str, Any],
    user_text: str,
) -> None:
    """Append user's new message to accumulated unstructured_requirements."""
    user_text_clean = user_text.strip()
    current_req = str(state.get("unstructured_requirements", "")).strip()
    if current_req:
        combined = current_req + " " + user_text_clean
    else:
        combined = user_text_clean
    state["unstructured_requirements"] = combined


async def run_agent_with_accumulated_requirements(
    runner: Runner,
    app_name: str,
    user_id: str,
    session_id: str,
    state: Dict[str, Any],
) -> str:
    """Call the current runner (vision or roadmap) with the full accumulated requirements."""
    # For now, both product_vision_agent and product_roadmap_agent
    # are driven by the same call interface: user_text -> response_text.
    #
    # IMPORTANT:
    # We always pass the accumulated requirements, not just last user turn.
    #
    accumulated = str(state["unstructured_requirements"])
    response_text = await call_agent_async(
        runner=runner,
        user_id=user_id,
        session_id=session_id,
        app_name=app_name,
        user_text=accumulated,
    )
    return response_text


def integrate_vision_result(
    state: Dict[str, Any],
    structured: OutputSchema,
) -> None:
    """Copy parsed agent output into local state."""
    state["product_vision_statement"] = structured.product_vision_statement
    state["is_complete"] = structured.is_complete
    state["clarifying_questions"] = structured.clarifying_questions


async def main_async() -> None:
    """Main async REPL-like loop."""

    app_name = "ProductManager"
    user_id = "user_123"

    # Minimal clean initial state
    initial_state: Dict[str, Any] = {
        "product_vision_statement": "",
        "product_roadmap": "",
        "unstructured_requirements": "",
        "is_complete": False,
        "clarifying_questions": [],
    }

    # Load or create session and hydrate local state
    session_id, state = await load_or_create_session(
        app_name=app_name,
        user_id=user_id,
        initial_state=initial_state,
    )

    # Start with the vision agent
    runner = Runner(
        agent=product_vision_agent,
        app_name=app_name,
        session_service=SESSION_SERVICE,
    )

    print("\nWelcome to Product Manager Chat!")
    print("Type 'exit' or 'quit' to end the conversation.\n")

    while True:
        user_text = input("You: ")

        if user_text.lower() in ("exit", "quit"):
            print("Ending conversation. Session state is stored in memory for now.")
            break

        # 1. Accumulate this new user message into requirements
        append_user_text_to_requirements(state, user_text)

        # 2. Call the active agent with ALL accumulated requirements
        print(f"\n--- Running Query: {state['unstructured_requirements']} ---")
        response_text = await run_agent_with_accumulated_requirements(
            runner=runner,
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            state=state,
        )

        # 3. Parse the agent output
        structured, err = parse_agent_output(response_text)

        if err:
            print(f"⚠ {err}")
            # We still continue the loop; state already has updated requirements
            continue

        # 4. Show the parsed results
        print("\nParsed agent output:")
        print("Vision:", structured.product_vision_statement)
        print("Complete?:", structured.is_complete)

        if structured.is_complete:
            print("✅ Vision is complete. We can move to roadmap next.")
        else:
            print("❗ We still need answers to:")
            for i, q in enumerate(structured.clarifying_questions, start=1):
                print(f"  {i}. {q}")

        # 5. Sync the structured result back into our local state
        integrate_vision_result(state, structured)

        # 6. Optionally call your persistence helper (logging, audit, etc.)
        await persist_product_vision_state(
            session_service=SESSION_SERVICE,
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            structured=structured,
        )

        # 7. If vision is complete, switch the runner to roadmap agent
        if structured.is_complete and runner.agent is not product_roadmap_agent:
            print("🔀 Switching runner to product_roadmap_agent ...")
            runner = Runner(
                agent=product_roadmap_agent,
                app_name=app_name,
                session_service=SESSION_SERVICE,
            )
            # NOTE: actually calling the roadmap agent and integrating
            # its output comes next in your roadmap step (issue 5).
            # Right now we just switch so the NEXT loop iteration will
            # talk to product_roadmap_agent.
            #
            # Later you'll probably want to call it immediately instead
            # of waiting for another user input.
            #
            # That will be a small addition:
            # - detect `is_complete`
            # - immediately run roadmap agent using
            #   `state["product_vision_statement"]`
            #   instead of full unstructured_requirements.
            # We'll wire that once you're ready.
            # ---------------------------------------------------------


if __name__ == "__main__":
    asyncio.run(main_async())
