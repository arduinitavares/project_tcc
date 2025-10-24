"""Utility functions for the orchestrator."""

# utils/state.py
from google.adk.sessions import DatabaseSessionService


async def display_state(
    session_service: DatabaseSessionService,
    app_name: str,
    user_id: str,
    session_id: str,
    label: str,
) -> None:
    """Fetch and pretty-print the current session state for debugging."""
    print(f"---------- {label} ----------")
    try:
        session = await session_service.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )

        if session is None:
            print("No session state yet.")
            return

        sid = getattr(session, "id", "<no id>")
        st = getattr(session, "state", "<no .state attr>")

        print("Session ID:", sid)
        print("State:", st)
    except AttributeError as e:
        print(f"Attribute error displaying state: {e}")
