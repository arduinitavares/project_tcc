"""
Main entry point for the Orchestrator Agent application.
Acts as the Workflow Engine to manage state transitions.
"""

import os

# --- SAFETY CONFIGURATION ---
# We keep these to ensure LiteLLM behaves deterministically.
os.environ["LITELLM_DISABLE_ASYNC_LOGGING"] = "1"
os.environ["LITELLM_LOG"] = "ERROR"
os.environ["LITELLM_SUPPRESS_INSTRUMENTATION"] = "True"

import asyncio
import json
import logging
import re
import sqlite3
import sys
import traceback
import uuid
from datetime import datetime
from pathlib import Path
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
from tools.orchestrator_tools import get_real_business_state
from utils.model_config import OPENROUTER_PRIVACY_ERROR_MESSAGE

# --- CONFIGURATION ---
litellm.telemetry = False
litellm.suppress_debug_info = True
litellm.drop_params = True

# --- LOGGING CONFIGURATION ---
# Create logs directory if it doesn't exist
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Create timestamped log file
LOG_FILENAME = LOGS_DIR / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Configure logging to file only
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILENAME, encoding='utf-8')
    ]
)

# Create application logger
app_logger = logging.getLogger("main")
app_logger.setLevel(logging.INFO)

# Configure dependency log levels
# SQLAlchemy at INFO to capture SQL queries for debugging
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
# Suppress verbose LiteLLM logs
logging.getLogger("litellm").setLevel(logging.ERROR)
logging.getLogger("LiteLLM").setLevel(logging.ERROR)

console = Console()
load_dotenv()

APP_NAME = "agile_orchestrator"
USER_ID = "local_developer"
PERSIST_LLM_OUTPUT = os.getenv("PERSIST_LLM_OUTPUT", "0") == "1"
SHOW_TOOL_PAYLOADS = os.getenv("SHOW_TOOL_PAYLOADS", "1") == "1"
MAX_TOOL_PAYLOAD_CHARS = int(os.getenv("MAX_TOOL_PAYLOAD_CHARS", "4000"))

# --- FIX 1: VOLATILE SESSION (Random ID) ---
# Every time you run this script, it generates a NEW ID.
# This ensures you start with a blank slate (Volatile Memory is Empty),
# matching your specific requirement.
SESSION_ID = str(uuid.uuid4())
DB_PATH = "agile_sqlmodel.db"

# --- LITELLM CALLBACKS DISABLED ---
litellm.success_callback = []
litellm.failure_callback = []
litellm.callbacks = []

# --- 1. HELPER FUNCTIONS (Logic & I/O) ---


def get_current_state(
    app_name: str, user_id: str, session_id: str
) -> Dict[str, Any]:
    """Fetch raw state dict from SQLite (Acts as Volatile RAM)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT state FROM sessions WHERE app_name=? AND user_id=? AND id=?",
            (app_name, user_id, session_id),
        )
        row = cursor.fetchone()
        conn.close()
        state: Dict[str, Any] = json.loads(row[0]) if row else {}
        app_logger.debug("Retrieved state (redacted).")
        return state
    except sqlite3.Error as e:
        app_logger.error("Error fetching state from DB.")
        return {}


def update_state_in_db(partial_update: Dict[str, Any]) -> None:
    """Updates the Volatile State (O in your diagram)."""
    if not PERSIST_LLM_OUTPUT:
        app_logger.info("State persistence disabled; skipping update.")
        return
    app_logger.info("Updating state (redacted).")
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
        app_logger.info("State updated successfully in DB")
    except sqlite3.Error as e:
        app_logger.error("DB WRITE ERROR.")
        console.print("[bold red]DB WRITE ERROR.[/bold red]")


def extract_json_from_response(text: str) -> Dict[str, Any]:
    """Robustly extracts the last JSON object from a text stream (Fallback)."""
    try:
        match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"(\{.*\})$", text.strip(), re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        return {}


def print_system_message(text: str, style: str = "bold cyan") -> None:
    """Helper to print system messages consistently."""
    console.print(f"[{style}]{text}[/{style}]")


def _serialize_for_display(payload: Any) -> str:
    """Serialize payloads for console display with safe truncation."""
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(payload)

    if len(text) > MAX_TOOL_PAYLOAD_CHARS:
        return f"{text[:MAX_TOOL_PAYLOAD_CHARS]}\n... (truncated)"
    return text


def _display_tool_call(part: types.Part) -> None:
    """Helper to visualize tool calls."""
    if not part.function_call:
        return

    tool_name = part.function_call.name
    args = part.function_call.args
    if SHOW_TOOL_PAYLOADS:
        args_json = _serialize_for_display(args)
    else:
        args_keys = sorted(args.keys()) if isinstance(args, dict) else []
        args_json = json.dumps({"keys": args_keys}, indent=2, ensure_ascii=False)

    # Log the tool call with full arguments
    app_logger.info("TOOL CALL: %s", tool_name)
    app_logger.info("TOOL ARGUMENTS:\n%s", _serialize_for_display(args))

    tool_panel = Panel(
        f"[bold]Function:[/bold] {tool_name}\n[bold]Arguments:[/bold]\n{args_json}",
        title="[TOOL CALL]",
        border_style="magenta",
        expand=False,
    )
    console.print("\n")
    console.print(tool_panel)
    console.print("[bold blue]ORCHESTRATOR > [/bold blue]", end="")


def _display_tool_response(part: types.Part) -> None:
    """Helper to visualize the RETURN VALUE from the tool."""
    if not part.function_response:
        return

    tool_name = part.function_response.name
    response_content = part.function_response.response

    if SHOW_TOOL_PAYLOADS:
        resp_json = _serialize_for_display(response_content)
    else:
        # Pretty print only response keys (redacted)
        resp_keys = (
            sorted(response_content.keys()) if isinstance(response_content, dict) else []
        )
        resp_json = json.dumps({"keys": resp_keys}, indent=2, ensure_ascii=False)

    # Log the tool response with full result
    app_logger.info("TOOL RESPONSE FROM: %s", tool_name)
    app_logger.info("TOOL RESULT:\n%s", _serialize_for_display(response_content))

    tool_panel = Panel(
        f"[bold]From:[/bold] {tool_name}\n[bold]Result:[/bold]\n{resp_json}",
        title="[TOOL RESPONSE]",
        border_style="cyan",
        expand=False,
    )
    console.print("\n")
    console.print(tool_panel)
    console.print("[bold blue]ORCHESTRATOR > [/bold blue]", end="")


async def get_user_input(prompt: str = "") -> str:
    """
    Async wrapper for console.input to prevent blocking the event loop.
    Uses run_in_executor to offload the blocking call.
    """
    return await asyncio.get_running_loop().run_in_executor(
        None, console.input, prompt
    )


# --- 2. WORKFLOW LOGIC ---


def evaluate_workflow_triggers(state: Dict[str, Any]) -> Optional[str]:
    """Evaluates workflow triggers based on the current state."""
    has_backlog = (
        state.get("product_backlog") and len(state["product_backlog"]) > 0
    )
    has_sprint_plan = state.get("sprint_plan")

    if has_backlog and not has_sprint_plan:
        return "[SYSTEM TRIGGER]: The Product Backlog has been updated..."

    plan_confirmed = state.get("sprint_plan_confirmed", False)
    dev_tasks_active = state.get("dev_tasks_active", False)

    if plan_confirmed and not dev_tasks_active:
        return "[SYSTEM TRIGGER]: The Sprint Plan has been confirmed..."

    return None


async def run_agent_turn(
    runner: Runner, user_input: str, is_system_trigger: bool = False
) -> None:
    """
    Executes a single turn of the agent.
    """
    # Log the input with actual text
    if is_system_trigger:
        app_logger.info("SYSTEM TRIGGER INPUT: %s", user_input)
    else:
        app_logger.info("USER INPUT: %s", user_input)
    
    # 1. PREPARE STATE
    full_state = get_current_state(APP_NAME, USER_ID, SESSION_ID)
    vision_draft = full_state.get("vision_components", "NO_HISTORY")

    # Serialize only if it's a dict (meaning we have history)
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

    # Convert to Content object for ADK runner
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_with_state)],
    )

    # 2. VISUALS
    if is_system_trigger:
        console.rule(style="bold yellow")
        console.print(
            f"[bold yellow]SYSTEM TRIGGER:[/bold yellow] {user_input}"
        )

    # We rely on console.input() for the user text, so no print needed here.

    console.print("\n[bold blue]ORCHESTRATOR > [/bold blue]", end="")

    # 3. RUN AGENT
    full_response_text = ""
    latest_tool_data = {}  # Capture the raw data here

    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=SESSION_ID,
            new_message=new_message,
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:

                    # A. Tool Call
                    if part.function_call:
                        _display_tool_call(part)

                    # B. Tool Response (The Fix for Amnesia between turns)
                    if part.function_response:
                        _display_tool_response(part)
                        latest_tool_data = part.function_response.response

                    # C. Text
                    if part.text:
                        full_response_text += part.text
                        console.print(part.text, end="", style="white")

        console.print("\n")
        
        # Log the complete response text
        if full_response_text:
            app_logger.info("AGENT RESPONSE TEXT:\n%s", full_response_text)
        else:
            app_logger.info("AGENT RESPONSE: (no text, tool-only turn)")
    except Exception as e:
        message = str(e).lower()
        if (
            "zdr" in message
            or "data_collection" in message
            or "provider" in message
            or "no providers" in message
        ):
            app_logger.error("OpenRouter privacy routing failure.")
            raise RuntimeError(OPENROUTER_PRIVACY_ERROR_MESSAGE) from e
        app_logger.error("Error during agent turn.")
        console.print("\n[bold red]ERROR during agent turn.[/bold red]")
        raise

    # 4. CAPTURE OUTPUT & UPDATE DB
    # We prefer the intercepted data from the tool response.
    # We only assume persistence here means "Updating the Volatile State", not final DB.
    data_to_save = latest_tool_data or extract_json_from_response(
        full_response_text
    )

    if data_to_save:
        if "updated_components" in data_to_save:
            # This matches O -> O: UPDATE VOLATILE STATE in your diagram
            update_state_in_db(
                {"vision_components": data_to_save["updated_components"]}
            )
            console.print(
                Panel(
                    "[green]Updated Volatile Draft[/green]",
                    title="[STATE UPDATE]",
                    border_style="green",
                    expand=False,
                )
            )

        elif "roadmap_draft" in data_to_save:
            # Update roadmap state
            update_state_in_db({"roadmap_draft": data_to_save["roadmap_draft"]})
            console.print(
                Panel(
                    "[green]Updated Roadmap Draft[/green]",
                    title="[STATE UPDATE]",
                    border_style="green",
                    expand=False,
                )
            )

        elif "sprint_plan" in data_to_save:
            update_state_in_db({"sprint_plan": data_to_save["sprint_plan"]})
            console.print(
                "[bold dim cyan]>> State Updated (Sprint Plan)[/bold dim cyan]"
            )


# --- 3. MAIN LOOP ---


async def main():
    """Main application loop."""
    console.clear()
    app_logger.info("="*80)
    app_logger.info("NEW SESSION STARTED: %s", SESSION_ID)
    app_logger.info("Log file: %s", LOG_FILENAME)
    app_logger.info("="*80)
    print_system_message(f"INITIALIZING SESSION: {SESSION_ID}")
    print_system_message(f"Logging to: {LOG_FILENAME}")

    # Initialize DB (Volatile State Holder)
    session_service = DatabaseSessionService(f"sqlite:///{DB_PATH}")

    # We always start fresh because the UUID is new.
    # But we hydrate business state if needed (e.g. knowing about OTHER projects)
    with console.status(
        "[bold green]Hydrating Business State...", spinner="dots"
    ):
        initial_state = get_real_business_state()
        app_logger.info("Initial business state loaded: %s", json.dumps(initial_state, indent=2, ensure_ascii=False, default=str))

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
        state=initial_state,
    )
    app_logger.info("Session created successfully")

    runner = Runner(
        agent=root_agent, app_name=APP_NAME, session_service=session_service
    )
    print_system_message("SYSTEM READY. Type 'exit' to quit.\n")

    while True:
        try:
            # FIX: Use Rich's console.input for better UI
            # We use get_user_input (async) to avoid blocking the event loop.
            user_input = await get_user_input("[bold green]USER > [/bold green]")

            if user_input.lower() in ["exit", "quit"]:
                app_logger.info("User requested session termination")
                print_system_message("ENDING SESSION.")
                break

            # A. Run User Turn
            await run_agent_turn(runner, user_input, is_system_trigger=False)

            # B. Check for Automated Workflow Steps
            while True:
                current_state = get_current_state(
                    APP_NAME, USER_ID, SESSION_ID
                )
                system_instruction = evaluate_workflow_triggers(current_state)

                if system_instruction:
                    await run_agent_turn(
                        runner, system_instruction, is_system_trigger=True
                    )
                else:
                    break

            console.rule(style="dim")

        except KeyboardInterrupt:
            app_logger.warning("Session interrupted by user (Ctrl+C)")
            print_system_message("\nINTERRUPTED.")
            break
        except Exception as e:
            app_logger.error("Unexpected error in main loop.")
            console.print(f"[bold red]ERROR:[/bold red] {e}")
            console.print(f"[dim]See log file for details: {LOG_FILENAME}[/dim]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        app_logger.critical("Critical error in application.")
        console.print(f"\n[bold red]CRITICAL ERROR:[/bold red] {e}")
        console.print(f"[dim]See log file for details: {LOG_FILENAME}[/dim]")
        sys.exit(1)
    finally:
        app_logger.info("="*80)
        app_logger.info("SESSION ENDED")
        app_logger.info("="*80)
