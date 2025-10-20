"""Question Answering Agent Runner."""

import asyncio  # 1. Import asyncio
import uuid

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from questions_answering_agent import question_answering_agent

load_dotenv()


# 2. Wrap the logic in an async function
async def main():
    """Create a session and run the question-answering agent."""
    # Create a stateful session service to store state
    session_service_stateful = InMemorySessionService()

    initial_state = {
        "user_name": "Alexandre",
        "favorite_topics": """
        - Artificial Intelligence
        - Machine Learning
        - Natural Language Processing
        - I like pizza;
        - I like wine and beer;
        - I love playing video games;
        - I love playing tennis;
        """,
    }

    # Create a new session with the initial state
    APP_NAME = "questions_answering_agent"
    USER_ID = "alex_id_1234"
    SESSION_ID = str(uuid.uuid4())

    # 3. Add 'await' to the async method call
    await session_service_stateful.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
        state=initial_state,
    )

    print("CREATED STATEFUL SESSION:")
    print(f"Session ID: {SESSION_ID}")
    print(f"User ID: {USER_ID}")
    print(f"App Name: {APP_NAME}")
    print("-" * 20)

    runner = Runner(
        agent=question_answering_agent,
        app_name=APP_NAME,
        session_service=session_service_stateful,
    )

    new_message = types.Content(
        role="user", parts=[types.Part(text="what do I like eating?")]
    )

    # The runner.run() method itself is synchronous, so no await is needed here.
    for event in runner.run(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=new_message,
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                print("FINAL RESPONSE:")
                print(event.content.parts[0].text)

    print("==== Session Event Exploration ====")
    # 3. Add 'await' to the async method call
    session = await session_service_stateful.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )

    # Log final Session state
    print("FINAL SESSION STATE:")
    for key, value in session.state.items():
        print(f"{key}: {value}")


# 4. Add the entry point to run the async function
if __name__ == "__main__":
    asyncio.run(main())
