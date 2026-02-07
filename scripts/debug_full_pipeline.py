"""Diagnostic: Simulates the full ADK _preprocess_async pipeline for ROUTING_MODE.

Checks whether the agent_transfer request processor interferes with tools_dict.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.adk.models.llm_request import LlmRequest

from orchestrator_agent.fsm.definitions import STATE_REGISTRY
from orchestrator_agent.fsm.states import OrchestratorState


def _dedupe_tools(tools):
    seen: set = set()
    deduped: list = []
    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        name = name or repr(tool)
        if name in seen:
            continue
        seen.add(name)
        deduped.append(tool)
    return deduped


state_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
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

print(f"After appending all tools:")
print(f"  tools_dict keys ({len(llm_request.tools_dict)}): {list(llm_request.tools_dict.keys())}")
print(f"  'sprint_planner_tool' in tools_dict: {'sprint_planner_tool' in llm_request.tools_dict}")

# Now simulate the agent_transfer processor adding transfer_to_agent
from google.adk.tools.transfer_to_agent_tool import transfer_to_agent
transfer_tool = FunctionTool(func=transfer_to_agent)
llm_request.append_tools([transfer_tool])

print(f"\nAfter agent_transfer processor:")
print(f"  tools_dict keys ({len(llm_request.tools_dict)}): {list(llm_request.tools_dict.keys())}")
print(f"  'sprint_planner_tool' in tools_dict: {'sprint_planner_tool' in llm_request.tools_dict}")

# Check if any tool name conflicts
all_names = [
    getattr(t, "name", None) or getattr(t, "__name__", None)
    for t in tools
]
print(f"\nOriginal tool names: {all_names}")

# Check if AgentTool instances are the ones from definitions.py or agent.py
for tool_union in tools:
    if isinstance(tool_union, AgentTool) and tool_union.name == "sprint_planner_tool":
        print(f"\nsprint_planner_tool AgentTool details:")
        print(f"  Python id: {id(tool_union)}")
        print(f"  Agent name: {tool_union.agent.name}")
        print(f"  Agent type: {type(tool_union.agent).__name__}")
        print(f"  Agent input_schema: {tool_union.agent.input_schema}")
        print(f"  Agent output_schema: {tool_union.agent.output_schema}")
        print(f"  Declaration: {tool_union._get_declaration()}")
