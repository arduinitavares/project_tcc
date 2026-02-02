import json
import os
from typing import Any, Callable, Dict, Optional
from google.adk.tools import ToolContext

from orchestrator_agent.agent_tools.story_pipeline.pipeline_constants import (
    CYAN, GREEN, YELLOW, RED, MAGENTA, RESET, BOLD, DIM
)

class PipelineLogger:
    """Handles logging and debug dumping for the story pipeline."""

    def __init__(self, output_callback: Optional[Callable[[str], None]] = None, tool_context: Optional[ToolContext] = None):
        self.output_callback = output_callback
        self.tool_context = tool_context

    def log(self, msg: str):
        """Log a message to the output callback or stdout."""
        if self.output_callback:
            self.output_callback(msg)
        else:
            print(msg)

    def log_header(self, feature_title: str, theme: str, epic: str):
        self.log(f"\n{CYAN}[Pipeline]{RESET} Processing feature: {BOLD}'{feature_title}'{RESET}")
        self.log(f"{DIM}   Theme: {theme} | Epic: {epic}{RESET}")

    def should_dump_debug(self) -> bool:
        """Check if debug dumping is enabled via env var or tool context."""
        # Env var check
        if os.environ.get("STORY_PIPELINE_DEBUG_DUMP", "").lower() in ("1", "true", "yes"):
            return True

        # Tool context check
        if self.tool_context and self.tool_context.state:
            if self.tool_context.state.get("debug_dump_enabled"):
                return True

        return False

    def dump_debug_info(self, debug_info: Dict[str, Any], file_path: str = "logs/debug_story_pipeline_input.txt"):
        """Dumps debug info to a file if enabled."""
        if not self.should_dump_debug():
            return

        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(debug_info, f, indent=2, default=str)
            self.log(f"{YELLOW}[Debug]{RESET} Dumped pipeline input to {file_path}")
        except Exception as e:
            self.log(f"{RED}[Debug Error]{RESET} Failed to dump debug info: {e}")

    @staticmethod
    def extract_agent_instructions(agent: Any, prefix: str = "") -> Dict[str, Any]:
        """Recursively extract instructions from agent hierarchy."""
        results = {}

        # Unwrap SelfHealingAgent if needed
        actual_agent = agent
        if hasattr(agent, "agent"):
            actual_agent = agent.agent

        name = getattr(actual_agent, "name", "unknown")
        key = f"{prefix}{name}" if prefix else name

        # Get instruction if it's an LlmAgent
        if hasattr(actual_agent, "instruction"):
            instr = getattr(actual_agent, "instruction", None)
            if instr:
                results[key] = instr

        # Get model if available
        if hasattr(actual_agent, "model"):
            model = getattr(actual_agent, "model", None)
            if model:
                results[f"{key}_model"] = str(model)

        # Get output_schema if available
        if hasattr(actual_agent, "output_schema"):
            schema = getattr(actual_agent, "output_schema", None)
            if schema:
                results[f"{key}_output_schema"] = str(schema)

        # Recurse into sub_agents (SequentialAgent, LoopAgent, etc.)
        if hasattr(actual_agent, "sub_agents"):
            for i, sub in enumerate(actual_agent.sub_agents or []):
                sub_results = PipelineLogger.extract_agent_instructions(sub, prefix=f"{key}.")
                results.update(sub_results)

        # Check for LoopAgent's sub_agent (singular)
        if hasattr(actual_agent, "sub_agent"):
            sub = getattr(actual_agent, "sub_agent", None)
            if sub:
                sub_results = PipelineLogger.extract_agent_instructions(sub, prefix=f"{key}.")
                results.update(sub_results)

        return results
