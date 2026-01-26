import copy
from typing import Any, Dict, Optional, Callable, AsyncGenerator
from pydantic import ValidationError, Field, model_validator
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext

class SelfHealingAgent(BaseAgent):
    """
    Wraps an ADK Agent to provide resilience against Pydantic validation errors.
    """
    agent: BaseAgent = Field(description="The inner agent to wrap.")
    max_retries: int = Field(default=3, description="Number of retries on validation failure.")
    name: str = Field(default="SelfHealingAgent", description="Name of the agent")
    description: str = Field(default="Wrapper for resilience", description="Description of the agent")

    @model_validator(mode='before')
    @classmethod
    def set_meta_from_agent(cls, data: Any) -> Any:
        if isinstance(data, dict):
            agent = data.get('agent')
            if agent:
                 # agent might be an object or dict
                 name = getattr(agent, 'name', None) or (agent.get('name') if isinstance(agent, dict) else None)
                 desc = getattr(agent, 'description', None) or (agent.get('description') if isinstance(agent, dict) else None)

                 if name and 'name' not in data:
                     # Sanitize name to be identifier-compliant
                     sanitized_name = "".join(c if c.isalnum() or c == '_' else '_' for c in name)
                     data['name'] = f"SelfHealing_{sanitized_name}"
                 if desc and 'description' not in data:
                     data['description'] = desc
        return data

    async def run_async(self, parent_context: InvocationContext) -> AsyncGenerator[Any, None]:
        print(f"DEBUG: SelfHealingAgent {self.name} starting run_async")
        for attempt in range(self.max_retries + 1):
            try:
                print(f"DEBUG: SelfHealingAgent attempt {attempt}")
                # Delegate execution to the inner agent
                async for event in self.agent.run_async(parent_context):
                    yield event

                print("DEBUG: SelfHealingAgent inner run successful")
                return

            except ValidationError as e:
                print(f"DEBUG: SelfHealingAgent caught validation error: {e}")
                if attempt == self.max_retries:
                    raise  # Propagate error if retries exhausted

                # Update state in parent_context for next retry
                state = parent_context.state

                error_msg = f"Validation Error on attempt {attempt + 1}: {str(e)}"

                # Inject feedback into state
                if isinstance(state, dict):
                    history = state.get("_validation_history", [])
                    if isinstance(history, list):
                        new_history = list(history) + [error_msg]
                    else:
                        new_history = [str(history), error_msg]

                    state["_validation_history"] = new_history
                    state["last_validation_error"] = error_msg

                # Loop continues to next attempt

class ConditionalLoopAgent(BaseAgent):
    """
    Executes an inner agent in a loop until a condition is met or max_iterations reached.
    """
    agent: BaseAgent = Field(description="The agent to run in a loop.")
    max_iterations: int = Field(default=4, description="Maximum number of iterations.")
    exit_condition_key: str = Field(default="refinement_result.is_valid", description="State key path to check for True to exit loop.")
    name: str = Field(default="ConditionalLoopAgent", description="Name of the loop agent")
    description: str = Field(default="Loops until condition met", description="Description of the loop agent")

    async def run_async(self, parent_context: InvocationContext) -> AsyncGenerator[Any, None]:
        for i in range(self.max_iterations):
            print(f"DEBUG: ConditionalLoopAgent iteration {i}")
            async for event in self.agent.run_async(parent_context):
                yield event

            if self._should_exit(parent_context.state):
                print("DEBUG: ConditionalLoopAgent exit condition met")
                break

    def _should_exit(self, state: Dict[str, Any]) -> bool:
        refinement = state.get("refinement_result")
        if not refinement:
            return False

        if hasattr(refinement, "is_valid"):
            return getattr(refinement, "is_valid")
        elif isinstance(refinement, dict):
            return refinement.get("is_valid", False)

        return False
