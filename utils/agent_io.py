"""This module contains utility functions for handling agent I/O operations."""

# utils/agent_io.py

from typing import Optional

from google.adk.runners import Runner
from google.genai import types

from .colors import Colors
from .state import display_state


async def process_agent_event(event) -> Optional[str]:
    """
    Handle a single streamed event from the agent:
    - print debug info (tool calls, code execution, etc.)
    - print final response in a nice block
    - return final response text if this event is the final response
    """
    print(f"Event ID: {event.id}, Author: {event.author}")

    # Streamed parts (tool calls, partials, etc.)
    if event.content and event.content.parts:
        for part in event.content.parts:
            # executable code
            if hasattr(part, "executable_code") and part.executable_code:
                print(
                    f"  Debug: Agent generated code:\n```python\n{part.executable_code.code}\n```"
                )

            # code execution result
            elif hasattr(part, "code_execution_result") and part.code_execution_result:
                print(
                    "  Debug: Code Execution Result: "
                    f"{part.code_execution_result.outcome} - Output:\n"
                    f"{part.code_execution_result.output}"
                )

            # tool responses
            elif hasattr(part, "tool_response") and part.tool_response:
                print(f"  Tool Response: {part.tool_response.output}")

            # regular text snippets
            elif hasattr(part, "text") and part.text and not part.text.isspace():
                print(f"  Text: '{part.text.strip()}'")

    # Final block?
    final_response_text = None
    if hasattr(event, "is_final_response") and event.is_final_response():
        # pull text safely
        if (
            event.content
            and event.content.parts
            and hasattr(event.content.parts[0], "text")
            and event.content.parts[0].text
        ):
            final_response_text = event.content.parts[0].text.strip()
            print(
                f"\n{Colors.BG_BLUE}{Colors.WHITE}{Colors.BOLD}"
                "╔══ AGENT RESPONSE ═════════════════════════════════════════"
                f"{Colors.RESET}"
            )
            print(f"{Colors.CYAN}{Colors.BOLD}{final_response_text}{Colors.RESET}")
            print(
                f"{Colors.BG_BLUE}{Colors.WHITE}{Colors.BOLD}"
                "╚═════════════════════════════════════════════════════════════"
                f"{Colors.RESET}\n"
            )
        else:
            print(
                f"\n{Colors.BG_RED}{Colors.WHITE}{Colors.BOLD}"
                "==> Final Agent Response: [No text content in final event]"
                f"{Colors.RESET}\n"
            )

    return final_response_text


async def call_agent_async(
    runner: Runner,
    user_id: str,
    session_id: str,
    app_name: str,
    user_text: str,
) -> Optional[str]:
    """
    High-level helper:
    - show state BEFORE
    - send the user's text to the agent runner
    - stream intermediate events
    - collect and return the agent's final structured JSON text
    - show state AFTER
    """
    content = types.Content(role="user", parts=[types.Part(text=user_text)])

    print(
        f"\n{Colors.BG_GREEN}{Colors.BLACK}{Colors.BOLD}"
        f"--- Running Query: {user_text} ---"
        f"{Colors.RESET}"
    )
    final_response_text: Optional[str] = None

    # BEFORE
    await display_state(
        session_service=runner.session_service,
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        label="State BEFORE processing",
    )

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            maybe_final = await process_agent_event(event)
            if maybe_final:
                final_response_text = maybe_final
    except (RuntimeError, ValueError) as e:
        print(f"Error during agent call: {e}")

    # AFTER
    await display_state(
        session_service=runner.session_service,
        app_name=app_name,
        user_id=user_id,
        session_id=session_id,
        label="State AFTER processing",
    )

    return final_response_text
