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
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

import litellm
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from rich.console import Console
from rich.panel import Panel

# Import Agent
from orchestrator_agent.agent import root_agent
from orchestrator_agent.fsm.controller import FSMController
from orchestrator_agent.fsm.states import OrchestratorState
from tools.orchestrator_tools import get_real_business_state
# NOTE: Retry configuration (ZDR, rate limit, provider errors) is now handled
# exclusively by SelfHealingAgent in orchestrator_agent/agent_tools/utils/resilience.py

# --- MONKEY-PATCH: Enhanced error for tools_dict misses ---
import google.adk.flows.llm_flows.functions as _adk_functions
_original_get_tool_and_context = _adk_functions._get_tool_and_context

def _patched_get_tool_and_context(invocation_context, function_call, tools_dict, tool_confirmation=None):
    if function_call.name not in tools_dict:
        _keys = list(tools_dict.keys())
        logging.getLogger("main").error(
            f"TOOL MISS: '{function_call.name}' not in tools_dict. "
            f"Available keys ({len(_keys)}): {_keys}"
        )
    return _original_get_tool_and_context(invocation_context, function_call, tools_dict, tool_confirmation)

_adk_functions._get_tool_and_context = _patched_get_tool_and_context
# --- END MONKEY-PATCH ---

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
MAX_CONSECUTIVE_SYSTEM_TRIGGERS = 5

# --- FSM CONTROLLER ---
fsm_controller = FSMController()

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
    except (sqlite3.Error, json.JSONDecodeError) as e:
        app_logger.error("Error fetching state from DB: %s", e)
        return {}


def update_state_in_db(partial_update: Dict[str, Any], force: bool = False) -> None:
    """Updates the Volatile State (O in your diagram)."""
    if not PERSIST_LLM_OUTPUT and not force:
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
    except sqlite3.Error:
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


def _dedupe_tools(tools: List[Any]) -> List[Any]:
    """Remove tools with duplicate names to prevent provider errors."""
    seen: set[str] = set()
    deduped: List[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        name = name or repr(tool)
        if name in seen:
            continue
        seen.add(name)
        deduped.append(tool)
    return deduped


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
    """Evaluates workflow triggers based on the current state.

    Currently returns None — automated triggers are disabled until
    the sprint planning agent is implemented. The Vision → Backlog → Roadmap
    pipeline is driven entirely by user interaction.
    """
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

    # --- FSM CONFIGURATION ---
    active_state_key = full_state.get("fsm_state", OrchestratorState.ROUTING_MODE)
    try:
        active_state = OrchestratorState(active_state_key)
    except ValueError:
        active_state = OrchestratorState.ROUTING_MODE

    state_def = fsm_controller.get_state_definition(active_state)

    # Inject FSM Context into Agent
    # Since runner.agent is a SelfHealingAgent wrapper, we need to access result.agent
    inner_agent: Any = getattr(runner.agent, "agent", None)
    if inner_agent is None:
        raise RuntimeError("Runner agent wrapper missing inner agent.")
    inner_agent.instruction = state_def.instruction
    # Hermetic tool injection: each FSM state defines its complete tool set.
    # No BASE_TOOLS merge — prevents the LLM from seeing tools the FSM can't track.
    inner_agent.tools = _dedupe_tools(state_def.tools)

    # --- DEBUG: Log injected tool names for diagnostics ---
    _injected_names = [
        getattr(t, "name", None) or getattr(t, "__name__", "?")
        for t in inner_agent.tools
    ]
    app_logger.info(f"FSM STATE: {active_state.value} | Tools injected: {_injected_names}")

    # --- DEBUG: Validate declarations (catches silent _get_declaration failures) ---
    from google.adk.tools.base_tool import BaseTool as _BT
    for _tool in inner_agent.tools:
        if isinstance(_tool, _BT):
            try:
                _decl = _tool._get_declaration()
                if not _decl:
                    app_logger.warning(f"Tool {_tool.name!r} returned None declaration!")
            except Exception as _e:
                app_logger.error(f"Tool {_tool.name!r} declaration FAILED: {_e}")
    # State display moved to after turn completes (shows transition if any)

    # Construct Prompt
    vision_draft = full_state.get("vision_components", "NO_HISTORY")
    prior_state_str = json.dumps(vision_draft) if isinstance(vision_draft, dict) else "NO_HISTORY"

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
    latest_tool_data: Dict[str, Any] = {}  # Capture the raw data here
    last_tool_name = None  # Capture tool name for FSM
    current_text_chunk = ""  # Accumulate text between tool calls for logging

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
                        # Log any accumulated text BEFORE the tool call
                        if current_text_chunk.strip():
                            app_logger.info("AGENT OUTPUT (before tool call):\n%s", current_text_chunk.strip())
                            current_text_chunk = ""
                        _display_tool_call(part)

                    # B. Tool Response (The Fix for Amnesia between turns)
                    if part.function_response:
                        _display_tool_response(part)
                        last_tool_name = part.function_response.name
                        latest_tool_data = part.function_response.response or {}

                    # C. Text
                    if part.text:
                        full_response_text += part.text
                        current_text_chunk += part.text
                        console.print(part.text, end="", style="white")

        console.print("\n")
        
        # Log any remaining text after all tool calls completed
        if current_text_chunk.strip():
            app_logger.info("AGENT FINAL OUTPUT:\n%s", current_text_chunk.strip())
        elif not full_response_text:
            app_logger.info("AGENT RESPONSE: (no text, tool-only turn)")
    except Exception as e:
        # All transient errors (ZDR, 429, 5xx) are now handled by SelfHealingAgent.
        # If we get here, SelfHealingAgent has exhausted retries.
        app_logger.error("Error during agent turn: %s", e, exc_info=True)
        console.print("\n[bold red]ERROR during agent turn.[/bold red]")
        raise

    # 4. CALCULATE NEXT STATE
    next_state = fsm_controller.determine_next_state(
        active_state,
        last_tool_name,
        latest_tool_data,
        user_input
    )

    if next_state != active_state:
        # Force persist FSM state regardless of configuration flag
        update_state_in_db({"fsm_state": next_state.value}, force=True)
        console.print(f"[dim cyan]State: {active_state.value} → {next_state.value}[/dim cyan]")
    else:
        console.print(f"[dim]State: {active_state.value}[/dim]", style="dim cyan")

    # 5. CAPTURE OUTPUT & UPDATE DB
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


async def run_user_turn_with_retries(runner: Runner, user_input: str) -> None:
    """Run a user turn.
    
    NOTE: All transient error handling (ZDR, 429, 5xx) is now handled by
    SelfHealingAgent at the inner agent level. This function simply runs
    the turn and lets errors bubble up after SelfHealingAgent exhausts retries.
    """
    try:
        await run_agent_turn(runner, user_input, is_system_trigger=False)
    except Exception as e:
        app_logger.error("Agent turn failed after SelfHealingAgent retries: %s", e)
        console.print(f"[bold red]ERROR:[/bold red] {e}")


# --- 3. MAIN LOOP ---


async def process_automated_workflows(runner: Runner) -> None:
    """
    Checks for and executes automated workflow steps with a safety limit.
    Enforces MAX_CONSECUTIVE_SYSTEM_TRIGGERS to prevent infinite loops.
    """
    trigger_count = 0
    while True:
        current_state = get_current_state(APP_NAME, USER_ID, SESSION_ID)
        system_instruction = evaluate_workflow_triggers(current_state)

        if system_instruction:
            trigger_count += 1
            if trigger_count > MAX_CONSECUTIVE_SYSTEM_TRIGGERS:
                app_logger.warning(
                    "System trigger loop limit reached (%d). Stopping to prevent infinite loop.",
                    MAX_CONSECUTIVE_SYSTEM_TRIGGERS,
                )
                console.print(
                    f"[bold red]WARNING:[/bold red] System trigger limit reached ({MAX_CONSECUTIVE_SYSTEM_TRIGGERS}). Stopping."
                )
                break

            await run_agent_turn(runner, system_instruction, is_system_trigger=True)
        else:
            break


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

            # A. Run User Turn (with ZDR + RateLimit retry)
            await run_user_turn_with_retries(runner, user_input)

            # B. Check for Automated Workflow Steps
            await process_automated_workflows(runner)

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
