"""Test that sprint_planner_tool is correctly wired end-to-end.

Validates:
1. FSM definitions register the tool under the correct name
2. _dedupe_tools preserves it
3. AgentTool._get_declaration() produces a valid declaration
4. The tool name in declaration matches the expected name
5. Simulated tools_dict build includes sprint_planner_tool
"""

import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.function_tool import FunctionTool

from orchestrator_agent.fsm.definitions import STATE_REGISTRY
from orchestrator_agent.fsm.states import OrchestratorState


def _build_tools_dict(tools: list) -> dict:
    """Simulate what ADK's LlmRequest.append_tools does."""
    tools_dict: dict = {}
    for tool in tools:
        if isinstance(tool, BaseTool):
            decl = tool._get_declaration()
            if decl:
                tools_dict[tool.name] = tool
        elif callable(tool):
            ft = FunctionTool(func=tool)
            decl = ft._get_declaration()
            if decl:
                tools_dict[ft.name] = ft
    return tools_dict


# --- Import main.py's _dedupe_tools without running the whole module ---
def _dedupe_tools(tools):
    """Exact copy of the _dedupe_tools from main.py."""
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


class TestSprintPlannerToolRegistration:
    """Verify that sprint_planner_tool is accessible in all FSM states that list it."""

    STATES_WITH_SPRINT_PLANNER = [
        OrchestratorState.ROUTING_MODE,
        OrchestratorState.STORY_PERSISTENCE,
        OrchestratorState.SPRINT_SETUP,
        OrchestratorState.SPRINT_DRAFT,
        OrchestratorState.SPRINT_PERSISTENCE,
    ]

    def test_sprint_planner_in_routing_mode_tools(self):
        state_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
        names = [
            getattr(t, "name", None) or getattr(t, "__name__", None)
            for t in state_def.tools
        ]
        assert "sprint_planner_tool" in names, (
            f"sprint_planner_tool not in ROUTING_MODE tools: {names}"
        )

    def test_sprint_planner_survives_dedupe(self):
        state_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
        deduped = _dedupe_tools(state_def.tools)
        names = [
            getattr(t, "name", None) or getattr(t, "__name__", None)
            for t in deduped
        ]
        assert "sprint_planner_tool" in names, (
            f"sprint_planner_tool lost after _dedupe_tools: {names}"
        )

    def test_sprint_planner_declaration_valid(self):
        state_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
        for tool in state_def.tools:
            name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
            if name == "sprint_planner_tool":
                assert isinstance(tool, BaseTool), (
                    f"sprint_planner_tool should be BaseTool, got {type(tool)}"
                )
                decl = tool._get_declaration()
                assert decl is not None, "sprint_planner_tool declaration is None"
                assert decl.name == "sprint_planner_tool", (
                    f"Declaration name mismatch: {decl.name}"
                )
                return
        assert False, "sprint_planner_tool not found in ROUTING_MODE tools"

    def test_sprint_planner_in_simulated_tools_dict(self):
        """Key test: Simulates the full ADK tools_dict build pipeline."""
        state_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
        deduped = _dedupe_tools(state_def.tools)
        tools_dict = _build_tools_dict(deduped)
        assert "sprint_planner_tool" in tools_dict, (
            f"sprint_planner_tool not in tools_dict! "
            f"Keys: {list(tools_dict.keys())}"
        )

    def test_all_states_with_sprint_planner(self):
        """Verify sprint_planner_tool is in tools_dict for ALL states that should have it."""
        for state in self.STATES_WITH_SPRINT_PLANNER:
            state_def = STATE_REGISTRY.get(state)
            assert state_def is not None, f"State {state} not in registry"
            deduped = _dedupe_tools(state_def.tools)
            tools_dict = _build_tools_dict(deduped)
            assert "sprint_planner_tool" in tools_dict, (
                f"sprint_planner_tool not in tools_dict for {state.value}! "
                f"Keys: {list(tools_dict.keys())}"
            )

    def test_no_duplicate_tool_names(self):
        """Verify no two tools share the same name in ROUTING_MODE."""
        state_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
        names = []
        for tool in state_def.tools:
            name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
            names.append(name)
        seen = set()
        dupes = [n for n in names if n in seen or seen.add(n)]
        assert not dupes, f"Duplicate tool names: {dupes}"
