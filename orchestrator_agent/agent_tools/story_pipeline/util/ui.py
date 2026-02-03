import json
import logging
from typing import Any
from rich.console import Console
from rich.panel import Panel

# Rich console for formatted output
_console = Console()
MAX_PAYLOAD_CHARS = 2000

# Module-level logger for file logging
_ui_logger = logging.getLogger("story_pipeline.ui")


def serialize_for_display(payload: Any) -> str:
    """Serialize payloads for console display with safe truncation."""
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(payload)

    if len(text) > MAX_PAYLOAD_CHARS:
        return f"{text[:MAX_PAYLOAD_CHARS]}\n... (truncated)"
    return text


def display_subagent_output(author: str, output_text: str) -> None:
    """Display sub-agent output in a Rich Panel."""
    # Log to file
    _ui_logger.info("SUB-AGENT OUTPUT [%s]:\n%s", author, serialize_for_display(output_text))
    # Display to console
    panel = Panel(
        f"[bold]Output:[/bold]\n{serialize_for_display(output_text)}",
        title=f"[SUB-AGENT: {author}]",
        border_style="green",
        expand=False,
    )
    _console.print(panel)


def display_subagent_tool_call(author: str, tool_name: str, args: Any) -> None:
    """Display sub-agent tool call in a Rich Panel."""
    # Log to file
    _ui_logger.info("SUB-AGENT TOOL CALL [%s] Function: %s\nArguments:\n%s", author, tool_name, serialize_for_display(args))
    # Display to console
    panel = Panel(
        f"[bold]Function:[/bold] {tool_name}\n[bold]Arguments:[/bold]\n{serialize_for_display(args)}",
        title=f"[SUB-AGENT TOOL CALL: {author}]",
        border_style="yellow",
        expand=False,
    )
    _console.print(panel)


def display_subagent_tool_response(author: str, tool_name: str, response: Any) -> None:
    """Display sub-agent tool response in a Rich Panel."""
    # Log to file
    _ui_logger.info("SUB-AGENT TOOL RESPONSE [%s] From: %s\nResult:\n%s", author, tool_name, serialize_for_display(response))
    # Display to console
    panel = Panel(
        f"[bold]From:[/bold] {tool_name}\n[bold]Result:[/bold]\n{serialize_for_display(response)}",
        title=f"[SUB-AGENT TOOL RESPONSE: {author}]",
        border_style="blue",
        expand=False,
    )
    _console.print(panel)


def display_subagent_input(title: str, payload: Any) -> None:
    """Display sub-agent input in a Rich Panel."""
    # Log to file
    _ui_logger.info("%s:\n%s", title, serialize_for_display(payload))
    # Display to console
    panel = Panel(
        f"[bold]Input:[/bold]\n{serialize_for_display(payload)}",
        title=title,
        border_style="magenta",
        expand=False,
    )
    _console.print(panel)
