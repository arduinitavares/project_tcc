"""Diagnostic: simulate ADK's tools_dict build for ROUTING_MODE."""

from orchestrator_agent.fsm.definitions import STATE_REGISTRY
from orchestrator_agent.fsm.states import OrchestratorState
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.function_tool import FunctionTool

state_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE]
print("Tools in ROUTING_MODE:")
for tool in state_def.tools:
    name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    print(f"  {name!r}  ({type(tool).__name__})")

# Simulate what ADK does: call _get_declaration for each tool
tools_dict: dict = {}
failed = []
for tool in state_def.tools:
    if isinstance(tool, BaseTool):
        try:
            decl = tool._get_declaration()
            if decl:
                tools_dict[tool.name] = tool
                print(f"  OK: {tool.name!r} -> decl.name={decl.name!r}")
            else:
                failed.append((tool.name, "declaration is None"))
        except Exception as e:
            failed.append((tool.name, str(e)))
    elif callable(tool):
        ft = FunctionTool(func=tool)
        try:
            decl = ft._get_declaration()
            if decl:
                tools_dict[ft.name] = ft
                print(f"  OK: {ft.name!r} -> decl.name={decl.name!r}")
            else:
                failed.append((ft.name, "declaration is None"))
        except Exception as e:
            failed.append((getattr(tool, "__name__", "?"), str(e)))

print()
print(f"tools_dict keys: {list(tools_dict.keys())}")
found = "sprint_planner_tool" in tools_dict
print(f"sprint_planner_tool in tools_dict: {found}")
if failed:
    print(f"FAILED: {failed}")
