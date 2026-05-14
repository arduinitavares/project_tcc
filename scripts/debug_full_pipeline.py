"""Diagnostic: Simulates the full ADK _preprocess_async pipeline for ROUTING_MODE.

Checks whether the agent_transfer request processor interferes with tools_dict.
"""

import os
import sys
from collections.abc import Iterable

from utils.cli_output import emit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # noqa: PTH100, PTH120

from google.adk.models.llm_request import LlmRequest
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.function_tool import FunctionTool

from orchestrator_agent.fsm.definitions import STATE_REGISTRY
from orchestrator_agent.fsm.states import OrchestratorState


def _dedupe_tools(tools: Iterable[object]) -> list[object]:
    seen: set[str] = set()
    deduped: list[object] = []
    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        name = name or repr(tool)
        if name in seen:
            continue
        seen.add(name)
        deduped.append(tool)
    return deduped


state_def = STATE_REGISTRY[OrchestratorState.SETUP_REQUIRED]
tools = _dedupe_tools(state_def.tools)

# Simulate what _preprocess_async does
llm_request = LlmRequest()

for tool_union in tools:
    if isinstance(tool_union, BaseTool):
        # BaseTool.process_llm_request calls llm_request.append_tools([self])
        llm_request.append_tools([tool_union])
    elif callable(tool_union):
        ft = FunctionTool(func=tool_union)
        llm_request.append_tools([ft])

emit("After appending all tools:")
emit(
    f"  tools_dict keys ({len(llm_request.tools_dict)}): {list(llm_request.tools_dict.keys())}"  # noqa: E501
)
emit(
    f"  'sprint_planner_tool' in tools_dict: {'sprint_planner_tool' in llm_request.tools_dict}"  # noqa: E501
)

# Now simulate the agent_transfer processor adding transfer_to_agent
from google.adk.tools.transfer_to_agent_tool import transfer_to_agent  # noqa: E402

transfer_tool = FunctionTool(func=transfer_to_agent)
llm_request.append_tools([transfer_tool])

emit("\nAfter agent_transfer processor:")
emit(
    f"  tools_dict keys ({len(llm_request.tools_dict)}): {list(llm_request.tools_dict.keys())}"  # noqa: E501
)
emit(
    f"  'sprint_planner_tool' in tools_dict: {'sprint_planner_tool' in llm_request.tools_dict}"  # noqa: E501
)

# Check if any tool name conflicts
all_names = [getattr(t, "name", None) or getattr(t, "__name__", None) for t in tools]
emit(f"\nOriginal tool names: {all_names}")

# Check if AgentTool instances are the ones from definitions.py or agent.py
for tool_union in tools:
    if isinstance(tool_union, AgentTool) and tool_union.name == "sprint_planner_tool":
        emit("\nsprint_planner_tool AgentTool details:")
        emit(f"  Python id: {id(tool_union)}")
        emit(f"  Agent name: {tool_union.agent.name}")
        emit(f"  Agent type: {type(tool_union.agent).__name__}")
        emit(f"  Agent input_schema: {getattr(tool_union.agent, 'input_schema', None)}")
        output_schema = getattr(tool_union.agent, "output_schema", None)
        emit(f"  Agent output_schema: {output_schema}")
        emit(f"  Declaration: {tool_union._get_declaration()}")
