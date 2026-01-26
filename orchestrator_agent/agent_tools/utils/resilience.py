import copy
from pydantic import ValidationError
from typing import Any, Dict

class SelfHealingAgent:
    """
    Wraps an ADK Agent to provide resilience against Pydantic validation errors.

    If the inner agent raises a ValidationError (indicating output schema violation),
    this wrapper catches it, appends the error to the state/prompt, and retries
    up to `max_retries` times.
    """

    def __init__(self, agent: Any, max_retries: int = 3):
        """
        Args:
            agent: The inner agent to wrap (must have a .run(state) method).
            max_retries: Number of retries on validation failure.
        """
        self.agent = agent
        self.max_retries = max_retries

        # Proxy common attributes to look like the inner agent
        self.name = getattr(agent, "name", "SelfHealingAgent")
        self.description = getattr(agent, "description", "")
        self.output_key = getattr(agent, "output_key", None)

    def run(self, state: Dict[str, Any]) -> Any:
        """
        Executes the inner agent with retry logic.
        """
        # Master copy for this run execution to avoid mutating the caller's state reference
        current_state = copy.copy(state)

        for attempt in range(self.max_retries + 1):
            try:
                # Pass a shallow copy to the agent to ensure:
                # 1. Isolation (agent doesn't mutate our retry logic state unexpectedly)
                # 2. Testability (mock records distinct objects)
                # 3. Clean slate for retry (if agent mutates in-place, we retry with 'clean' state + error)
                agent_input = copy.copy(current_state)
                return self.agent.run(agent_input)
            except ValidationError as e:
                if attempt == self.max_retries:
                    raise  # Propagate error if retries exhausted

                # Format error for feedback
                error_msg = f"Validation Error on attempt {attempt + 1}: {str(e)}"

                # Inject feedback into state.
                # We create new objects (list, str) to ensure we don't mutate
                # structures that might be shared with previous 'agent_input' snapshots
                # stored in mocks or logs.

                history = current_state.get("_validation_history", [])
                if isinstance(history, list):
                    new_history = list(history) + [error_msg]
                else:
                    new_history = [str(history), error_msg]

                current_state["_validation_history"] = new_history
                current_state["last_validation_error"] = error_msg

        return None  # Should be unreachable
