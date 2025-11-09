import asyncio
from typing import Annotated

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
session_service = DatabaseSessionService(db_url=DB_URL)

# >>> CHANGED: make initial_state consistent snake_case and start fields empty
initial_state: dict[str, object] = {
    "product_vision_statement": "",
    "product_roadmap": "",
    "unstructured_requirements": "",
    "is_complete": False,
    "clarifying_questions": [],
}


class OutputSchema(BaseModel):
    """Schema for the output of the product vision agent."""

    product_vision_statement: Annotated[str, Field(...)]
    is_complete: Annotated[bool, Field(...)]
    clarifying_questions: Annotated[list[str], Field(default_factory=list)]


async def load_or_create_session(
    session_service: DatabaseSessionService,
    app_name: str,
    user_id: str,
    initial_state: dict[str, object],
) -> str:
    """Get an existing session id or create one."""
    sessions_list = await session_service.list_sessions(
        app_name=app_name,
        user_id=user_id,
    )

    if sessions_list and sessions_list.sessions:
        session_id = sessions_list.sessions[0].id
        print(f"Continuing existing session: {session_id}")
        return session_id

    new_session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        state=initial_state,
    )
    print(f"Created new session: {new_session.id}")
    return new_session.id


async def get_session_state(
    session_service: DatabaseSessionService,
    app_name: str,
    user_id: str,
    session_id: str,
) -> dict[str, object]:
    """Fetch latest session state dict from DB."""
    session_data = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )
    # The SDK usually returns an object with `.state`
    # We'll assume it's already a dict-like structure.
    return dict(session_data.state)


def append_user_text_to_requirements(
    state: dict[str, object],
    user_text: str,
) -> None:
    """Append user's message to accumulated unstructured_requirements."""
    user_text_clean = user_text.strip()

    current_req = str(state.get("unstructured_requirements", "")).strip()

    if current_req:
        updated = current_req + " " + user_text_clean
    else:
        updated = user_text_clean

    state["unstructured_requirements"] = updated


async def save_state(
    session_service: DatabaseSessionService,
    app_name: str,
    user_id: str,
    session_id: str,
    state: dict[str, object],
) -> None:
    """Write updated state back to DB."""
    await session_service.update_session_state(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        state=state,
    )


async def run_vision_agent(
    runner: Runner,
    user_id: str,
    session_id: str,
    app_name: str,
    accumulated_requirements: str,
) -> str:
    """Call product_vision_agent with the FULL accumulated requirements."""
    # >>> CHANGED: instead of passing only the latest user_text,
    # we pass the combined requirements string.
    vision_input = accumulated_requirements
    response_text = await call_agent_async(
        runner=runner,
        user_id=user_id,
        session_id=session_id,
        app_name=app_name,
        user_text=vision_input,
    )
    return response_text


async def main_async() -> None:
    """Main async function to run the product management workflow."""

    APP_NAME = "ProductManager"
    USER_ID = "user_123"

    # Get or create session
    session_id = await load_or_create_session(
        session_service=session_service,
        app_name=APP_NAME,
        user_id=USER_ID,
        initial_state=initial_state,
    )

    # Start with product_vision_agent as the active runner
    runner = Runner(
        agent=product_vision_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    print("\nWelcome to Product Manager Chat!")
    print("Type 'exit' or 'quit' to end the conversation.\n")

    while True:
        user_text = input("You: ")

        if user_text.lower() in ("exit", "quit"):
            print("Ending conversation. Your data has been saved to the database.")
            break

        # ------------------------------------------------------------------
        # 1. Load current session state from DB
        # ------------------------------------------------------------------
        state = await get_session_state(
            session_service=session_service,
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id,
        )

        # Ensure default keys exist even if DB had an older schema
        state.setdefault("product_vision_statement", "")
        state.setdefault("product_roadmap", "")
        state.setdefault("unstructured_requirements", "")
        state.setdefault("is_complete", False)
        state.setdefault("clarifying_questions", [])

        # ------------------------------------------------------------------
        # 2. Append this user message into unstructured_requirements
        #    (this is the core of fix #2)
        # ------------------------------------------------------------------
        append_user_text_to_requirements(state, user_text)

        # ------------------------------------------------------------------
        # 3. Call product_vision_agent using the FULL accumulated requirements
        # ------------------------------------------------------------------
        final_response_text = await run_vision_agent(
            runner=runner,
            user_id=USER_ID,
            session_id=session_id,
            app_name=APP_NAME,
            accumulated_requirements=str(state["unstructured_requirements"]),
        )

        # ------------------------------------------------------------------
        # 4. Parse agent output and handle errors
        # ------------------------------------------------------------------
        structured, err = parse_agent_output(final_response_text)

        if err:
            print(f"⚠ {err}")
            # Even on parse failure, persist updated requirements text
            await save_state(
                session_service=session_service,
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=session_id,
                state=state,
            )
            continue

        # ------------------------------------------------------------------
        # 5. Show results to the user
        # ------------------------------------------------------------------
        print("\nParsed agent output:")
        print("Vision:", structured.product_vision_statement)
        print("Complete?:", structured.is_complete)

        if structured.is_complete:
            print("✅ Vision is complete. We can move to roadmap next.")
        else:
            print("❗ We still need answers to:")
            for i, q in enumerate(structured.clarifying_questions, start=1):
                print(f"  {i}. {q}")

        # ------------------------------------------------------------------
        # 6. Mirror vision results into in-memory state
        #    so that state always reflects latest agent output
        # ------------------------------------------------------------------
        state["product_vision_statement"] = structured.product_vision_statement
        state["is_complete"] = structured.is_complete
        state["clarifying_questions"] = structured.clarifying_questions

        # You still call your helper if you want (it could eg. do logging).
        # This is optional now, because we're updating state directly here.
        await persist_product_vision_state(
            session_service=session_service,
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id,
            structured=structured,
        )

        # ------------------------------------------------------------------
        # 7. Save updated session state (this is persistence for future turns)
        # ------------------------------------------------------------------
        await save_state(
            session_service=session_service,
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=session_id,
            state=state,
        )

        # ------------------------------------------------------------------
        # 8. If vision is complete, switch runner to roadmap agent
        #    (we are NOT yet making the roadmap call here; that's step 5
        #     from the earlier analysis, but structurally this is ready)
        # ------------------------------------------------------------------
        if structured.is_complete and runner.agent is not product_roadmap_agent:
            print("🔀 Switching runner to product_roadmap_agent ...")
            runner = Runner(
                agent=product_roadmap_agent,
                app_name=APP_NAME,
                session_service=session_service,
            )


if __name__ == "__main__":
    asyncio.run(main_async())
