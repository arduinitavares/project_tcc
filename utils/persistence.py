# utils/persistence.py

"""This module contains utility functions for persisting agent state."""

from google.adk.sessions import DatabaseSessionService


async def persist_product_vision_state(
    session_service: DatabaseSessionService,
    app_name: str,
    user_id: str,
    session_id: str,
    structured,
):
    """
    Merge latest product vision info into session.state and persist it.
    Assumes `session_service.save_session(session)` exists.
    """
    session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
    )

    if session is None:
        print("⚠ Could not load session to persist state.")
        return

    # Update state in memory
    session.state["product_vision_statement"] = structured.product_vision_statement
    session.state["product_vision_is_complete"] = structured.is_complete
    session.state["product_vision_questions"] = structured.clarifying_questions

    # Persist
    if hasattr(session_service, "save_session"):
        await session_service.save_session(session)
    else:
        # fallback: warn loudly so we know to implement a custom writer
        print("⚠ session_service.save_session() not available; state not persisted.")

    print("💾 Session state persisted.")
