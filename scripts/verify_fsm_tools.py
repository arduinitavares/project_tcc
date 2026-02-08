"""Quick verification of FSM state -> tool mappings."""
from orchestrator_agent.fsm.definitions import STATE_REGISTRY

for state, defn in STATE_REGISTRY.items():
    tool_names = []
    for t in defn.tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", "?")
        tool_names.append(name)
    print(f"{state.value:30s} -> {tool_names}")
