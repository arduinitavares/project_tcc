"""
Main entry point for the Orchestrator Agent application.
Acts as the Workflow Engine to manage state transitions.
"""

import os
import sys

# --- SAFETY CONFIGURATION ---
# We keep these to ensure LiteLLM behaves deterministically,
# but the real fix is switching to runner.run_async() below.
os.environ["LITELLM_DISABLE_ASYNC_LOGGING"] = "1"
os.environ["LITELLM_LOG"] = "ERROR"
os.environ["LITELLM_SUPPRESS_INSTRUMENTATION"] = "True"

import asyncio
import json
import logging
import re
import sqlite3
import uuid
from typing import Any, Dict, Optional

import litellm
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from rich.console import Console
from rich.panel import Panel

# Import Agent
from orchestrator_agent.agent import root_agent

# Import Initialization Logic
from tools.orchestrator_tools import get_real_business_state

# --- CONFIGURATION ---
litellm.telemetry = False
litellm.suppress_debug_info = True
# Added for stability with newer models
litellm.drop_params = True

logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
# Mute LiteLLM logger explicitly
logging.getLogger("litellm").setLevel(logging.ERROR)
logging.getLogger("LiteLLM").setLevel(logging.ERROR)

console = Console()
load_dotenv()

APP_NAME = "agile_orchestrator"
USER_ID = "local_developer"
SESSION_ID = str(uuid.uuid4())
DB_PATH = "agile_sqlmodel.db"

# --- LITELLM CALLBACKS DISABLED ---
litellm.success_callback = []
litellm.failure_callback = []
litellm.callbacks = []

# --- 1. HELPER FUNCTIONS (Logic & I/O) ---


def get_current_state(app_name: str, user_id: str, session_id: str) -> Dict[str, Any]:
    """Fetch raw state dict from SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT state FROM sessions WHERE app_name=? AND user_id=? AND id=?",
            (app_name, user_id, session_id),
        )
        row = cursor.fetchone()
        conn.close()
        return json.loads(row[0]) if row else {}
    except sqlite3.Error:
        return {}


def update_state_in_db(partial_update: Dict[str, Any]) -> None:
    """Merges new data into the existing SQL blob."""
    current = get_current_state(APP_NAME, USER_ID, SESSION_ID)
    current.update(partial_update)

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sessions SET state=? WHERE app_name=? AND user_id=? AND id=?",
            (json.dumps(current), APP_NAME, USER_ID, SESSION_ID),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        console.print(f"[bold red]DB WRITE ERROR:[/bold red] {e}")


def extract_json_from_response(text: str) -> Dict[str, Any]:
    """
    Robustly extracts the last JSON object from a text stream.
    Handles markdown code blocks or raw JSON.
    """
    try:
        # 1. Try to find markdown block
        match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        # 2. Try to find raw JSON brace pattern at the end of string
        match = re.search(r"(\{.*\})$", text.strip(), re.DOTALL)
        if match:
            return json.loads(match.group(1))

        # 3. Fallback: Try loading the whole string
        return json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        return {}


def print_system_message(text: str, style: str = "bold cyan") -> None:
    """Print a system level message."""
    console.print(f"[{style}]{text}[/{style}]")


def _display_tool_call(part: types.Part) -> None:
    """Helper to visualize tool calls in the console."""
    if not part.function_call:
        return

    tool_name = part.function_call.name
    args = part.function_call.args

    # Convert args to pretty JSON
    args_json = json.dumps(args, indent=2, ensure_ascii=False)

    # Create the detailed Panel
    tool_panel = Panel(
        f"[bold]Function:[/bold] {tool_name}\n[bold]Arguments:[/bold]\n{args_json}",
        title="[TOOL CALL]",
        border_style="magenta",
        expand=False,
    )

    console.print("\n")
    console.print(tool_panel)
    console.print("[bold blue]ORCHESTRATOR > [/bold blue]", end="")


# --- 2. WORKFLOW LOGIC ---


def evaluate_workflow_triggers(state: Dict[str, Any]) -> Optional[str]:
    """
    Inspects the Shared Memory to decide if the Orchestrator needs
    to automatically trigger the next agent.
    """
    # Check for Step 3: Backlog is ready -> Trigger Scrum Master
    has_backlog = state.get("product_backlog") and len(state["product_backlog"]) > 0
    has_sprint_plan = state.get("sprint_plan")

    if has_backlog and not has_sprint_plan:
        return (
            "[SYSTEM TRIGGER]: The Product Backlog has been updated. "
            "Immediately activate the Scrum Master Agent to create a Sprint Plan."
        )

    # Check for Step 9: Plan Confirmed -> Trigger Dev Agent
    plan_confirmed = state.get("sprint_plan_confirmed", False)
    dev_tasks_active = state.get("dev_tasks_active", False)

    if plan_confirmed and not dev_tasks_active:
        return (
            "[SYSTEM TRIGGER]: The Sprint Plan has been confirmed by the user. "
            "Immediately activate the Dev Support Agent to initialize development tasks."
        )

    return None


async def run_agent_turn(
    runner: Runner, user_input: str, is_system_trigger: bool = False
) -> None:
    """
    Executes a single turn of the agent.
    Handles the 'Bucket Brigade' state injection, visualization, and persistence.
    """
    # 1. PREPARE STATE
    full_state = get_current_state(APP_NAME, USER_ID, SESSION_ID)

    # We isolate the specific vision data.
    # If it doesn't exist, we default to "NO_HISTORY" so the agent knows to start fresh.
    vision_draft = full_state.get("vision_components", "NO_HISTORY")

    if isinstance(vision_draft, dict):
        prior_state_str = json.dumps(vision_draft)
    else:
        prior_state_str = "NO_HISTORY"

    prompt_with_state = f"""
    <prior_vision_state>
    {prior_state_str}
    </prior_vision_state>

    <user_raw_text>
    {user_input}
    </user_raw_text>
    """

    message = types.Content(role="user", parts=[types.Part(text=prompt_with_state)])

    # 2. VISUALS
    if is_system_trigger:
        console.rule(style="bold yellow")
        console.print(f"[bold yellow]SYSTEM TRIGGER:[/bold yellow] {user_input}")
    else:
        console.print(f"\n[bold green]USER > [/bold green]{user_input}")

    console.print("\n[bold blue]ORCHESTRATOR > [/bold blue]", end="")

    # 3. RUN AGENT
    full_response_text = ""

    # --- CRITICAL FIX: USE ASYNC RUNNER ---
    # We use runner.run_async() instead of runner.run().
    # This prevents creating a nested event loop that crashes LiteLLM.
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=message,
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.function_call:
                    _display_tool_call(part)

                if part.text:
                    full_response_text += part.text
                    console.print(part.text, end="", style="white")

    console.print("\n")

    # 4. CAPTURE OUTPUT & UPDATE DB
    structured_output = extract_json_from_response(full_response_text)

    if structured_output:
        if "updated_components" in structured_output:
            update_state_in_db(
                {"vision_components": structured_output["updated_components"]}
            )

            console.print(
                Panel(
                    "[green]Updated Vision Draft in DB[/green]",
                    title="[MEMORY SAVE]",
                    border_style="green",
                    expand=False,
                )
            )

        elif "sprint_plan" in structured_output:
            update_state_in_db({"sprint_plan": structured_output["sprint_plan"]})
            console.print(
                "[bold dim cyan]>> Memory Updated (Sprint Plan)[/bold dim cyan]"
            )


# --- 3. MAIN LOOP ---


async def main():
    """Main application loop."""
    console.clear()
    print_system_message(f"INITIALIZING SESSION: {SESSION_ID}")

    # Initialize DB
    session_service = DatabaseSessionService(f"sqlite:///{DB_PATH}")
    with console.status("[bold green]Hydrating Business State...", spinner="dots"):
        initial_state = get_real_business_state()

    await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID, state=initial_state
    )

    runner = Runner(
        agent=root_agent, app_name=APP_NAME, session_service=session_service
    )
    print_system_message("SYSTEM READY. Type 'exit' to quit.\n")

    while True:
        try:
            # Note: input() is blocking, but acceptable for a simple CLI loop.
            # In a true async CLI, you'd use aioinput or similar, but this is fine here.
            user_input = input("USER > ")
            if user_input.lower() in ["exit", "quit"]:
                break

            # A. Run User Turn
            await run_agent_turn(runner, user_input, is_system_trigger=False)

            # B. Check for Automated Workflow Steps
            while True:
                current_state = get_current_state(APP_NAME, USER_ID, SESSION_ID)
                system_instruction = evaluate_workflow_triggers(current_state)

                if system_instruction:
                    await run_agent_turn(
                        runner, system_instruction, is_system_trigger=True
                    )
                else:
                    break

            print_system_message("Turn Complete. Waiting for input.", style="dim")

        except KeyboardInterrupt:
            print_system_message("INTERRUPTED.")
            break
        # pylint: disable=broad-exception-caught
        except Exception as e:
            console.print(f"[bold red]ERROR:[/bold red] {e}")


if __name__ == "__main__":
    asyncio.run(main())
